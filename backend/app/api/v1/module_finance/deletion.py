"""Remove unpaid order working records while retaining late-payment reconciliation."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import String, cast, delete, func, inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.module_agreement.model import AgreementAcceptanceModel
from app.api.v1.module_billing.model import CreditGrantModel, CreditLedgerModel, SubscriptionCycleModel
from app.api.v1.module_growth.model import GrowthEventModel
from app.api.v1.module_growth.service import lock_app
from app.api.v1.module_payment.order.cancellation import close_unpaid_order
from app.api.v1.module_payment.order.model import PaymentAttemptModel, PaymentCallbackModel, PaymentOrderModel, PaymentRefundModel
from app.core.exceptions import CustomException

from .common import audit
from .model import FinanceAuditModel, FinanceBillEntryModel, FinanceBillModel, FinanceIssueModel, FinanceRefundRequestModel


async def _assert_unfunded(db: AsyncSession, order: PaymentOrderModel) -> None:
    if order.status == "paid" or order.paid_at or order.provider_trade_no or (order.mode_switch and order.mode_switch.get("status") == "completed"):
        raise CustomException(msg="已付款或已履约订单不能删除，请走退款和财务核对流程", status_code=409)
    checks = (
        select(SubscriptionCycleModel.id).where(SubscriptionCycleModel.app_id == order.app_id, SubscriptionCycleModel.order_id == order.id),
        select(CreditGrantModel.id).where(CreditGrantModel.app_id == order.app_id, CreditGrantModel.source_type == "credit_pack_order", CreditGrantModel.source_id == order.id),
        select(CreditLedgerModel.id).where(CreditLedgerModel.app_id == order.app_id, CreditLedgerModel.reference_type == "payment_order", CreditLedgerModel.reference_id == str(order.id)),
        select(PaymentRefundModel.id).where(PaymentRefundModel.app_id == order.app_id, PaymentRefundModel.order_id == order.id),
        select(FinanceRefundRequestModel.id).where(FinanceRefundRequestModel.app_id == order.app_id, FinanceRefundRequestModel.order_id == order.id),
        select(PaymentCallbackModel.id).where(PaymentCallbackModel.order_no == order.order_no, PaymentCallbackModel.status == "processed"),
        select(FinanceBillEntryModel.id).where(FinanceBillEntryModel.app_id == order.app_id, FinanceBillEntryModel.order_id == order.id, FinanceBillEntryModel.channel_amount_fen != 0),
        select(GrowthEventModel.id).where(GrowthEventModel.app_id == order.app_id, cast(GrowthEventModel.facts["order_id"].as_string(), String) == str(order.id)),
    )
    for query in checks:
        if await db.scalar(query.limit(1)) is not None:
            raise CustomException(msg="订单已有支付、权益、退款或账本关联，不能删除，需先财务核对", status_code=409)


async def delete_unpaid_order(db: AsyncSession, app_id: int, order_id: int, reason: str, operator_id: int | None, *, close_channel: bool = True) -> dict:
    await lock_app(db, app_id)
    order = await db.scalar(select(PaymentOrderModel).where(PaymentOrderModel.app_id == app_id, PaymentOrderModel.id == order_id).with_for_update().execution_options(populate_existing=True))
    if not order:
        raise CustomException(msg="当前客户端下未找到该订单", status_code=404)
    await _assert_unfunded(db, order)
    if order.is_deleted:
        return {"order_id": order.id, "deleted": True, "channel_status": order.status, "removed": {}}
    if close_channel and order.status != "closed":
        await close_unpaid_order(db, order)
        if order.status == "paid" or order.paid_at:
            # Return instead of raising: the verified payment must be committed.
            return {"order_id": order.id, "deleted": False, "channel_status": "paid", "removed": {}}
    await _assert_unfunded(db, order)
    before = order.status
    bill_ids = list(await db.scalars(select(FinanceBillEntryModel.bill_id).where(FinanceBillEntryModel.app_id == app_id, FinanceBillEntryModel.order_id == order.id).distinct()))
    statements = {
        "payment_attempts": delete(PaymentAttemptModel).where(PaymentAttemptModel.app_id == app_id, PaymentAttemptModel.order_id == order.id),
        "payment_callbacks": delete(PaymentCallbackModel).where(PaymentCallbackModel.order_no == order.order_no, PaymentCallbackModel.provider == order.provider),
        "agreement_acceptances": delete(AgreementAcceptanceModel).where(
            AgreementAcceptanceModel.app_id == app_id, AgreementAcceptanceModel.user_id == order.user_id, AgreementAcceptanceModel.business_ref == f"order:{order.order_no}"
        ),
        "finance_issues": delete(FinanceIssueModel).where(FinanceIssueModel.app_id == app_id, FinanceIssueModel.object_type == "order", FinanceIssueModel.object_id == order.id),
        "bill_entries": delete(FinanceBillEntryModel).where(FinanceBillEntryModel.app_id == app_id, FinanceBillEntryModel.order_id == order.id),
        "old_order_audits": delete(FinanceAuditModel).where(FinanceAuditModel.app_id == app_id, FinanceAuditModel.object_type == "order", FinanceAuditModel.object_id == str(order.id)),
    }
    removed = {name: (await db.execute(statement)).rowcount for name, statement in statements.items()}
    # This legacy preview table is present on older installations only.
    connection = await db.connection()
    if await connection.run_sync(lambda conn: inspect(conn).has_table("billing_mode_preview")):
        removed["mode_previews"] = (await db.execute(text("DELETE FROM billing_mode_preview WHERE app_id=:app_id AND order_id=:order_id"), {"app_id": app_id, "order_id": order.id})).rowcount
    for bill_id in bill_ids:
        bill = await db.get(FinanceBillModel, bill_id)
        total = int(await db.scalar(select(func.count()).select_from(FinanceBillEntryModel).where(FinanceBillEntryModel.app_id == app_id, FinanceBillEntryModel.bill_id == bill_id)) or 0)
        matched = int(
            await db.scalar(
                select(func.count())
                .select_from(FinanceBillEntryModel)
                .where(FinanceBillEntryModel.app_id == app_id, FinanceBillEntryModel.bill_id == bill_id, FinanceBillEntryModel.match_status == "matched")
            )
            or 0
        )
        if bill and bill.app_id == app_id:
            bill.summary = {**(bill.summary or {}), "entries": total, "matched": matched, "differences": total - matched}
    order.is_deleted = True
    order.deleted_time = datetime.now(UTC)
    order.next_query_at = None if order.status == "closed" else datetime.now(UTC) + timedelta(days=1)
    order.pay_url = None
    if order.mode_switch:
        order.mode_switch = {**order.mode_switch, "status": "cancelled", "message": "未支付订单已删除；迟到付款需财务核对"}
    audit(db, app_id, "order", order.id, "delete_unpaid", operator_id, reason, {"status": before, "order_no": order.order_no}, {"deleted": True, "channel_status": order.status, "removed": removed})
    await db.flush()
    return {"order_id": order.id, "deleted": True, "channel_status": order.status, "removed": removed}
