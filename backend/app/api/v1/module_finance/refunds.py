import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select

from app.api.v1.module_growth.refund_service import reconcile_order_rewards
from app.api.v1.module_growth.service import lock_app
from app.api.v1.module_payment.order.model import PaymentRefundModel
from app.core.database import async_db_session
from app.core.exceptions import CustomException

from .common import audit, utc
from .entitlements import preview_order_entitlements, terminate_order_entitlements
from .gateway import RefundResult, identity, refund_request
from .model import FinanceRefundRequestModel
from .orders import ACTIVE_REFUNDS, get_order


async def preview_refund(db, app_id, order_id, action):
    from fastapi.encoders import jsonable_encoder

    order = await get_order(db, app_id, order_id)
    preview = jsonable_encoder(await preview_order_entitlements(db, order, action))
    fingerprint = dict(preview)
    if preview["entitlement_kind"] == "duration":
        from app.api.v1.module_billing.model import SubscriptionCycleModel

        # Refund reflow starts at processing time. Its preview dates naturally
        # advance, so compare persisted rights instead of this moving clock.
        fingerprint["after"] = {key: value for key, value in preview["after"].items() if key not in {"starts_at", "ends_at"}}
        cycles = await db.scalars(
            select(SubscriptionCycleModel)
            .where(
                SubscriptionCycleModel.app_id == app_id,
                SubscriptionCycleModel.user_id == order.user_id,
                SubscriptionCycleModel.is_deleted == False,
            )
            .order_by(SubscriptionCycleModel.id)
        )
        fingerprint["periods"] = jsonable_encoder([{"id": cycle.id, "status": cycle.status, "starts_at": cycle.starts_at, "ends_at": cycle.ends_at} for cycle in cycles])
    raw = json.dumps({"app_id": app_id, "order_id": order_id, **fingerprint}, sort_keys=True, ensure_ascii=False)
    preview["preview_token"] = hashlib.sha256(raw.encode()).hexdigest()
    return preview


def check_preview(preview, token):
    if token is not None and token != preview["preview_token"]:
        raise CustomException(msg="用户订阅或积分已变化，请刷新权益预览后重新确认", status_code=409)


async def get_refund(db, app_id, request_id):
    row = await db.scalar(select(FinanceRefundRequestModel).where(FinanceRefundRequestModel.app_id == app_id, FinanceRefundRequestModel.id == request_id).execution_options(populate_existing=True))
    if not row:
        raise CustomException(msg="退款申请不存在", status_code=404)
    return row


async def create_refund(db, app_id, operator, data):
    await lock_app(db, app_id)
    prior = await db.scalar(select(FinanceRefundRequestModel).where(FinanceRefundRequestModel.app_id == app_id, FinanceRefundRequestModel.idempotency_key == data.idempotency_key))
    if prior:
        if (prior.order_id, prior.amount_fen, prior.entitlement_action, prior.reason) != (data.order_id, data.amount_fen, data.entitlement_action, data.reason):
            raise CustomException(msg="该请求编号已用于另一笔退款申请", status_code=409)
        return prior
    order = await get_order(db, app_id, data.order_id)
    if not order.paid_at or not order.provider_trade_no:
        raise CustomException(msg="仅渠道已确认支付的订单可申请退款", status_code=409)
    from .channels import enabled

    if not await enabled(db, app_id, order.provider, "refund"):
        raise CustomException(msg="当前客户端已暂停该渠道退款", status_code=409)
    succeeded = int(
        await db.scalar(
            select(func.coalesce(func.sum(PaymentRefundModel.amount_fen), 0)).where(
                PaymentRefundModel.app_id == app_id, PaymentRefundModel.order_id == order.id, PaymentRefundModel.status == "succeeded"
            )
        )
        or 0
    )
    reserved = int(
        await db.scalar(
            select(func.coalesce(func.sum(FinanceRefundRequestModel.amount_fen), 0)).where(
                FinanceRefundRequestModel.app_id == app_id, FinanceRefundRequestModel.order_id == order.id, FinanceRefundRequestModel.status.in_(ACTIVE_REFUNDS)
            )
        )
        or 0
    )
    if data.amount_fen > order.amount_fen - succeeded - reserved:
        raise CustomException(msg="退款金额超过可退余额（已扣除已退及处理中的退款）", status_code=409)
    preview = await preview_refund(db, app_id, order.id, data.entitlement_action)
    check_preview(preview, data.preview_token)
    row = FinanceRefundRequestModel(
        app_id=app_id,
        order_id=order.id,
        user_id=order.user_id,
        provider=order.provider,
        refund_no="YXRF" + uuid4().hex,
        idempotency_key=data.idempotency_key,
        amount_fen=data.amount_fen,
        reason=data.reason,
        entitlement_action=data.entitlement_action,
        requested_by=operator,
        merchant_identity=identity(order.provider),
        status="review",
    )
    db.add(row)
    await db.flush()
    audit(
        db,
        app_id,
        "refund",
        row.id,
        "request",
        operator,
        data.reason,
        after={"amount_fen": row.amount_fen, "order_no": order.order_no, "entitlement_action": row.entitlement_action, "entitlement_preview": preview},
    )
    return row


async def review_refund(db, app_id, request_id, operator, data):
    await lock_app(db, app_id)
    row = await get_refund(db, app_id, request_id)
    if row.status != "review":
        raise CustomException(msg="退款申请已审核，请刷新后查看", status_code=409)
    preview = await preview_refund(db, app_id, row.order_id, row.entitlement_action) if data.approved else None
    if preview:
        check_preview(preview, data.preview_token)
    row.reviewed_by, row.reviewed_at, row.review_reason = operator, datetime.now(UTC), data.reason
    row.status = "queued" if data.approved else "rejected"
    row.next_attempt_at = datetime.now(UTC) if data.approved else None
    audit(db, app_id, "refund", row.id, "approve" if data.approved else "reject", operator, data.reason, {"status": "review"}, {"status": row.status, "entitlement_preview": preview})
    await db.flush()
    return row


async def apply_refund(db, row, result: RefundResult):
    if row.status in ("succeeded", "failed", "rejected"):
        return
    if result.status == "succeeded":
        order = await get_order(db, row.app_id, row.order_id)
        ledger = await db.scalar(select(PaymentRefundModel).where(PaymentRefundModel.provider == row.provider, PaymentRefundModel.provider_refund_no == result.provider_no))
        if ledger and (ledger.app_id != row.app_id or ledger.order_id != row.order_id or ledger.amount_fen != row.amount_fen):
            raise CustomException(msg="渠道退款结果与已有流水不一致", status_code=409)
        if not ledger:
            paid_refunds = int(
                await db.scalar(
                    select(func.coalesce(func.sum(PaymentRefundModel.amount_fen), 0)).where(
                        PaymentRefundModel.app_id == row.app_id, PaymentRefundModel.order_id == row.order_id, PaymentRefundModel.status == "succeeded"
                    )
                )
                or 0
            )
            if paid_refunds + row.amount_fen > order.amount_fen:
                raise CustomException(msg="累计退款超过原单金额，请核对外部退款流水", status_code=409)
            db.add(
                PaymentRefundModel(
                    app_id=row.app_id,
                    user_id=row.user_id,
                    order_id=row.order_id,
                    refund_no=row.refund_no,
                    provider=row.provider,
                    provider_refund_no=result.provider_no,
                    amount_fen=row.amount_fen,
                    reason=row.reason,
                    status="succeeded",
                    refunded_at=result.completed_at,
                )
            )
            await db.flush()
        row.entitlement_result = await terminate_order_entitlements(db, order, row.refund_no) if row.entitlement_action == "terminate" else {"action": "retain"}
        if order.mode_switch and order.mode_switch.get("status") == "requires_confirmation" and row.entitlement_action == "terminate":
            order.mode_switch = {**order.mode_switch, "status": "cancelled", "message": "切换订单已退款并终止权益，原模式保持不变"}
        await reconcile_order_rewards(db, row.app_id, row.order_id)
        row.completed_at = result.completed_at
    row.status = result.status
    row.provider_refund_no = result.provider_no or row.provider_refund_no
    row.failure_code, row.failure_reason = result.code or None, result.reason or None
    row.next_attempt_at = None if result.status in ("succeeded", "failed") else datetime.now(UTC) + timedelta(minutes=min(60, 2 ** min(row.attempt_count, 6)))
    audit(db, row.app_id, "refund", row.id, "channel_result", None, result.reason or "渠道结果已核验", after={"status": row.status, "code": result.code})
    await db.flush()


async def dispatch_refund(app_id: int, request_id: int):
    async with async_db_session() as db, db.begin():
        await lock_app(db, app_id)
        row = await get_refund(db, app_id, request_id)
        if row.status not in ("queued", "processing", "unknown") or (row.next_attempt_at and utc(row.next_attempt_at) > datetime.now(UTC)):
            return
        from .channels import enabled

        query = row.status != "queued"
        first_submission = row.submitted_at is None
        if row.merchant_identity != identity(row.provider) or (not query and not await enabled(db, app_id, row.provider, "refund")):
            row.failure_reason = "退款渠道暂停或商户配置已变更，保留原退款申请"
            row.next_attempt_at = datetime.now(UTC) + timedelta(minutes=15)
            return
        order = await get_order(db, app_id, row.order_id)
        args = (row.provider, order.order_no, order.provider_trade_no, row.refund_no, row.amount_fen, order.amount_fen, row.reason)
        row.status, row.next_attempt_at = "unknown", datetime.now(UTC) + timedelta(minutes=5)
        row.attempt_count += 1
        if not query:
            row.submitted_at = datetime.now(UTC)
        audit(db, app_id, "refund", row.id, "query" if query else "submit", None, "按持久化商户退款号处理")
    try:
        result = await refund_request(*args, query=query)
        if not query and not first_submission and result.status == "failed":
            result = RefundResult("unknown", code=result.code, reason="原退款曾提交且结果未确认；重提被拒绝，仍保留金额并查询原单")
    except Exception:
        result = RefundResult("unknown", reason="退款结果未确认，保留金额并继续查单")
    async with async_db_session() as db, db.begin():
        await lock_app(db, app_id)
        await apply_refund(db, await get_refund(db, app_id, request_id), result)
