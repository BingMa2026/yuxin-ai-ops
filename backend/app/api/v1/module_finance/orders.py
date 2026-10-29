from datetime import UTC, datetime

from sqlalchemy import and_, exists, func, or_, select

from app.api.v1.module_billing.model import CreditGrantModel, SubscriptionCycleModel
from app.api.v1.module_client.app.model_policy import order_matches_model_policy
from app.api.v1.module_client.user.model import ClientUserModel
from app.api.v1.module_growth.model import GrowthEventModel, RewardModel
from app.api.v1.module_growth.service import lock_app
from app.api.v1.module_payment.order.model import PaymentAttemptModel, PaymentCallbackModel, PaymentOrderModel, PaymentRefundModel
from app.api.v1.module_payment.order.providers import VerifiedPayment, query_alipay_order, query_wechat_order
from app.api.v1.module_payment.order.service import PaymentCallbackService
from app.core.exceptions import CustomException

from .common import audit, date_conditions, fields, formal_order_condition, paginate
from .model import FinanceAuditModel, FinanceRefundRequestModel
from .schema import FinanceQuery, OrderOut

ACTIVE_REFUNDS = ("review", "queued", "processing", "unknown")
ORDER_FIELDS = (
    "id",
    "order_no",
    "user_id",
    "provider",
    "provider_trade_no",
    "purchase_type",
    "amount_fen",
    "status",
    "currency",
    "created_time",
    "paid_at",
    "expires_at",
    "closed_at",
    "failure_reason",
)


def fulfilled_expression():
    return or_(
        exists(select(SubscriptionCycleModel.id).where(SubscriptionCycleModel.app_id == PaymentOrderModel.app_id, SubscriptionCycleModel.order_id == PaymentOrderModel.id)),
        exists(
            select(CreditGrantModel.id).where(
                CreditGrantModel.app_id == PaymentOrderModel.app_id, CreditGrantModel.source_type == "credit_pack_order", CreditGrantModel.source_id == PaymentOrderModel.id
            )
        ),
    )


def order_statement(app_id: int, q: FinanceQuery):
    refunded = (
        select(func.coalesce(func.sum(PaymentRefundModel.amount_fen), 0))
        .where(PaymentRefundModel.order_id == PaymentOrderModel.id, PaymentRefundModel.app_id == app_id, PaymentRefundModel.status == "succeeded", PaymentRefundModel.is_deleted == False)
        .correlate(PaymentOrderModel)
        .scalar_subquery()
    )
    reserved = (
        select(func.coalesce(func.sum(FinanceRefundRequestModel.amount_fen), 0))
        .where(FinanceRefundRequestModel.order_id == PaymentOrderModel.id, FinanceRefundRequestModel.app_id == app_id, FinanceRefundRequestModel.status.in_(ACTIVE_REFUNDS))
        .correlate(PaymentOrderModel)
        .scalar_subquery()
    )
    condition = [PaymentOrderModel.app_id == app_id, PaymentOrderModel.is_deleted == False, formal_order_condition()]
    if q.keyword.strip():
        term = "%" + q.keyword.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        condition.append(
            or_(*[column.ilike(term, escape="\\") for column in (PaymentOrderModel.order_no, PaymentOrderModel.provider_trade_no, ClientUserModel.username, ClientUserModel.display_name)])
        )
    for field in ("provider", "purchase_type", "user_id"):
        if getattr(q, field) is not None:
            condition.append(getattr(PaymentOrderModel, field) == getattr(q, field))
    if q.entitlement_kind:
        condition.append(func.coalesce(PaymentOrderModel.plan_snapshot["entitlement_kind"].as_string(), "credits") == q.entitlement_kind)
    if q.mode_switch_status:
        condition.append(PaymentOrderModel.mode_switch["status"].as_string() == q.mode_switch_status)
    if q.status == "partially_refunded":
        condition.extend([refunded > 0, refunded < PaymentOrderModel.amount_fen])
    elif q.status == "refunded":
        condition.extend([refunded >= PaymentOrderModel.amount_fen, refunded > 0])
    elif q.status == "unfulfilled":
        condition.extend([PaymentOrderModel.paid_at.is_not(None), ~fulfilled_expression()])
    elif q.status:
        condition.append(PaymentOrderModel.status == q.status)
    condition.extend(date_conditions(getattr(PaymentOrderModel, q.time_field), q))
    if q.min_amount_fen is not None:
        condition.append(PaymentOrderModel.amount_fen >= q.min_amount_fen)
    if q.max_amount_fen is not None:
        condition.append(PaymentOrderModel.amount_fen <= q.max_amount_fen)
    revoked = exists(
        select(FinanceRefundRequestModel.id).where(
            FinanceRefundRequestModel.app_id == app_id,
            FinanceRefundRequestModel.order_id == PaymentOrderModel.id,
            FinanceRefundRequestModel.status == "succeeded",
            FinanceRefundRequestModel.entitlement_action == "terminate",
        )
    )
    return (
        select(
            PaymentOrderModel,
            ClientUserModel.username,
            ClientUserModel.display_name,
            refunded.label("refunded"),
            reserved.label("reserved"),
            fulfilled_expression().label("fulfilled"),
            revoked.label("revoked"),
        )
        .join(ClientUserModel, and_(ClientUserModel.id == PaymentOrderModel.user_id, ClientUserModel.app_id == app_id))
        .where(*condition)
        .order_by(PaymentOrderModel.id.desc())
    )


def order_row(row) -> OrderOut:
    order, username, name, refunded, reserved, fulfilled, revoked = row
    refund_status = "full" if refunded and refunded >= order.amount_fen else "partial" if refunded else "none"
    fulfillment = "not_paid" if not order.paid_at else "revoked" if revoked else "fulfilled" if fulfilled else "missing"
    return OrderOut(
        **fields(order, ORDER_FIELDS),
        username=username,
        display_name=name or "",
        product_name=str(order.plan_snapshot.get("name") or "—"),
        entitlement_kind=order.plan_snapshot.get("entitlement_kind", "credits"),
        mode_switch=order.mode_switch,
        refunded_fen=int(refunded),
        refund_reserved_fen=int(reserved),
        refundable_fen=max(0, order.amount_fen - refunded - reserved) if order.paid_at else 0,
        refund_status=refund_status,
        fulfillment_status=fulfillment,
    )


async def list_orders(db, app_id: int, q: FinanceQuery):
    stmt = order_statement(app_id, q)
    result = await paginate(db, stmt, q, order_row)
    source = stmt.order_by(None).subquery()
    result["summary"] = {
        "amount_fen": int(await db.scalar(select(func.coalesce(func.sum(source.c.amount_fen), 0))) or 0),
        "refunded_fen": int(await db.scalar(select(func.coalesce(func.sum(source.c.refunded), 0))) or 0),
    }
    for kind in ("credits", "duration"):
        result["summary"][f"{kind}_amount_fen"] = int(
            await db.scalar(select(func.coalesce(func.sum(source.c.amount_fen), 0)).where(func.coalesce(source.c.plan_snapshot["entitlement_kind"].as_string(), "credits") == kind)) or 0
        )
    return result


async def get_order(db, app_id: int, order_id: int):
    order = await db.scalar(select(PaymentOrderModel).where(PaymentOrderModel.app_id == app_id, PaymentOrderModel.id == order_id, PaymentOrderModel.is_deleted == False, formal_order_condition()))
    if not order:
        raise CustomException(msg="当前客户端下未找到该订单", status_code=404)
    return order


async def order_detail(db, app_id: int, order_id: int):
    order = await get_order(db, app_id, order_id)
    row = (await db.execute(order_statement(app_id, FinanceQuery()).where(PaymentOrderModel.id == order_id))).one()
    cycles = list(await db.scalars(select(SubscriptionCycleModel).where(SubscriptionCycleModel.app_id == app_id, SubscriptionCycleModel.order_id == order_id)))
    grants = list(
        await db.scalars(
            select(CreditGrantModel).where(
                CreditGrantModel.app_id == app_id,
                or_(
                    and_(CreditGrantModel.source_type == "credit_pack_order", CreditGrantModel.source_id == order_id),
                    and_(CreditGrantModel.source_type == "subscription_cycle", CreditGrantModel.source_id.in_([c.id for c in cycles])),
                ),
            )
        )
    )
    attempts = await db.scalars(select(PaymentAttemptModel).where(PaymentAttemptModel.app_id == app_id, PaymentAttemptModel.order_id == order_id).order_by(PaymentAttemptModel.id.desc()).limit(100))
    callbacks = await db.scalars(
        select(PaymentCallbackModel).where(PaymentCallbackModel.order_no == order.order_no, PaymentCallbackModel.provider == order.provider).order_by(PaymentCallbackModel.id.desc()).limit(100)
    )
    refunds = await db.scalars(select(PaymentRefundModel).where(PaymentRefundModel.app_id == app_id, PaymentRefundModel.order_id == order_id).order_by(PaymentRefundModel.id.desc()))
    audits = await db.scalars(
        select(FinanceAuditModel)
        .where(FinanceAuditModel.app_id == app_id, FinanceAuditModel.object_type == "order", FinanceAuditModel.object_id == str(order_id))
        .order_by(FinanceAuditModel.id.desc())
        .limit(100)
    )
    rewards = await db.scalars(
        select(RewardModel)
        .join(GrowthEventModel, GrowthEventModel.id == RewardModel.event_id)
        .where(RewardModel.app_id == app_id, GrowthEventModel.facts["order_id"].as_integer() == order_id)
        .limit(100)
    )
    return {
        "order": order_row(row),
        "plan_snapshot": order.plan_snapshot,
        "strategy_snapshot": order.strategy_snapshot,
        "cycles": [fields(c, ("id", "starts_at", "ends_at", "status")) for c in cycles],
        "credits": [fields(g, ("id", "amount", "available", "reserved", "status", "release_at", "expires_at")) for g in grants],
        "attempts": [fields(a, ("id", "action", "status", "error_message", "created_time", "completed_at")) for a in attempts],
        "callbacks": [fields(c, ("id", "status", "failure_reason", "created_time", "verified_at")) for c in callbacks],
        "refunds": [fields(r, ("id", "refund_no", "provider_refund_no", "amount_fen", "status", "reason", "refunded_at")) for r in refunds],
        "rewards": [fields(r, ("id", "user_id", "asset", "amount", "reversed_amount", "status")) for r in rewards],
        "audits": [fields(a, ("id", "action", "operator_id", "reason", "created_time")) for a in audits],
    }


async def verify_order(db, app_id: int, order_id: int, operator: int, reason: str):
    from app.api.v1.module_payment.order.cancellation import apply_query_result, close_unpaid_order

    await lock_app(db, app_id)
    order = await get_order(db, app_id, order_id)
    await db.refresh(order)
    before = order.status
    paid = await (query_alipay_order(order.order_no, include_closed=True) if order.provider == "alipay" else query_wechat_order(order.order_no, include_closed=True))
    if isinstance(paid, VerifiedPayment):
        await PaymentCallbackService(db).process(order.provider, paid)
        await lock_app(db, app_id)
        await db.refresh(order)
        if paid.order_no != order.order_no or paid.amount_fen != order.amount_fen or paid.provider_trade_no != order.provider_trade_no:
            raise CustomException(msg="渠道查单与原订单不一致，未补发权益", status_code=409)
        fulfilled = await db.scalar(select(fulfilled_expression()).select_from(PaymentOrderModel).where(PaymentOrderModel.id == order.id))
        refunded = await db.scalar(select(PaymentRefundModel.id).where(PaymentRefundModel.app_id == app_id, PaymentRefundModel.order_id == order_id).limit(1))
        refund_pending = await db.scalar(
            select(FinanceRefundRequestModel.id)
            .where(FinanceRefundRequestModel.app_id == app_id, FinanceRefundRequestModel.order_id == order_id, FinanceRefundRequestModel.status.in_((*ACTIVE_REFUNDS, "succeeded")))
            .limit(1)
        )
        if not fulfilled and not refunded and not refund_pending and await order_matches_model_policy(db, app_id, order.plan_snapshot):
            from app.api.v1.module_billing.mode_switch.service import fulfill_paid_order

            repaired = await fulfill_paid_order(db, order)
            if repaired:
                audit(db, app_id, "order", order_id, "repair_entitlements", operator, reason)
    elif not order.paid_at and order.status not in {"paid", "closed"}:
        terminal = await apply_query_result(db, order, paid)
        if not terminal and (order.cancel_requested_at or (order.expires_at and (order.expires_at.replace(tzinfo=UTC) if order.expires_at.tzinfo is None else order.expires_at) < datetime.now(UTC))):
            await close_unpaid_order(db, order)
    audit(db, app_id, "order", order_id, "query", operator, reason, {"status": before}, {"status": order.status, "verified_paid": isinstance(paid, VerifiedPayment)})
    await db.flush()
    return await order_detail(db, app_id, order_id)
