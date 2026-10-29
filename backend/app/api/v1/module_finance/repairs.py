"""只修复能由渠道签名查单结果唯一确认的支付差异。"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, func, select

from app.api.v1.module_billing.mode_switch.service import fulfill_paid_order
from app.api.v1.module_client.app.model_policy import order_matches_model_policy
from app.api.v1.module_growth.service import lock_app
from app.api.v1.module_payment.channel.model import PaymentChannelModel
from app.api.v1.module_payment.order.model import PaymentOrderModel, PaymentRefundModel
from app.api.v1.module_payment.order.providers import query_alipay_order, query_wechat_order
from app.core.database import async_db_session
from app.core.logger import logger

from .common import audit
from .model import FinanceBillEntryModel, FinanceBillModel, FinanceRefundRequestModel
from .orders import ACTIVE_REFUNDS, fulfilled_expression


async def _query(provider: str, order_no: str, sandbox: bool):
    return await (query_wechat_order(order_no) if provider == "wechat" else query_alipay_order(order_no, sandbox=sandbox))


async def _has_refund(db, app_id: int, order_id: int) -> bool:
    settled = await db.scalar(select(PaymentRefundModel.id).where(PaymentRefundModel.app_id == app_id, PaymentRefundModel.order_id == order_id).limit(1))
    pending = await db.scalar(
        select(FinanceRefundRequestModel.id)
        .where(FinanceRefundRequestModel.app_id == app_id, FinanceRefundRequestModel.order_id == order_id, FinanceRefundRequestModel.status.in_((*ACTIVE_REFUNDS, "succeeded")))
        .limit(1)
    )
    return bool(settled or pending)


async def repair_bill_payment(app_id: int, entry_id: int) -> None:
    # 自动补查负责把渠道已付订单入账，这里仅复核已确认的本地交易号与账单。
    async with async_db_session() as db, db.begin():
        await lock_app(db, app_id)
        entry = await db.scalar(select(FinanceBillEntryModel).where(FinanceBillEntryModel.app_id == app_id, FinanceBillEntryModel.id == entry_id).with_for_update())
        if not entry or entry.match_status != "payment_missing" or not entry.order_id:
            return
        bill = await db.scalar(select(FinanceBillModel).where(FinanceBillModel.app_id == app_id, FinanceBillModel.id == entry.bill_id))
        order = await db.scalar(select(PaymentOrderModel).where(PaymentOrderModel.app_id == app_id, PaymentOrderModel.id == entry.order_id).with_for_update())
        if (
            not bill
            or not order
            or entry.entry_type != "payment"
            or entry.order_no != order.order_no
            or bill.provider != order.provider
            or order.status != "paid"
            or order.provider_trade_no != entry.provider_trade_no
            or order.amount_fen != entry.channel_amount_fen
            or await _has_refund(db, app_id, order.id)
        ):
            return
        entry.system_amount_fen = order.amount_fen
        entry.match_status = "matched"
        entry.resolution = "渠道签名回调或主动查单已确认，账单与原订单一致"
        entry.resolved_at = datetime.now(UTC)
        await db.flush()
        total = await db.scalar(select(func.count()).select_from(FinanceBillEntryModel).where(FinanceBillEntryModel.bill_id == bill.id))
        matched = await db.scalar(select(func.count()).select_from(FinanceBillEntryModel).where(FinanceBillEntryModel.bill_id == bill.id, FinanceBillEntryModel.match_status == "matched"))
        bill.summary = {**(bill.summary or {}), "entries": total, "matched": matched, "differences": total - matched}
        audit(db, app_id, "bill_entry", entry.id, "auto_repair_payment", None, entry.resolution)


async def repair_missing_entitlement(app_id: int, order_id: int) -> None:
    async with async_db_session() as db:
        order = await db.scalar(select(PaymentOrderModel).where(PaymentOrderModel.app_id == app_id, PaymentOrderModel.id == order_id))
        if not order or order.status != "paid" or not order.provider_trade_no:
            return
        channel = await db.scalar(select(PaymentChannelModel).where(PaymentChannelModel.provider == order.provider, PaymentChannelModel.is_deleted == False))
        provider, order_no, trade_no, amount = order.provider, order.order_no, order.provider_trade_no, order.amount_fen
        sandbox = bool(channel and channel.mode == "sandbox")
    paid = await _query(provider, order_no, sandbox)
    if not paid or (paid.order_no, paid.provider_trade_no, paid.amount_fen) != (order_no, trade_no, amount):
        async with async_db_session() as db, db.begin():
            row = await db.scalar(select(PaymentOrderModel).where(PaymentOrderModel.app_id == app_id, PaymentOrderModel.id == order_id))
            if row and row.status == "paid":
                row.updated_time = datetime.now(UTC)
        return
    async with async_db_session() as db, db.begin():
        await lock_app(db, app_id)
        order = await db.scalar(select(PaymentOrderModel).where(PaymentOrderModel.app_id == app_id, PaymentOrderModel.id == order_id).with_for_update())
        if not order or order.status != "paid" or order.provider_trade_no != trade_no or await _has_refund(db, app_id, order.id):
            return
        fulfilled = await db.scalar(select(fulfilled_expression()).select_from(PaymentOrderModel).where(PaymentOrderModel.id == order.id))
        if fulfilled:
            return
        if not await order_matches_model_policy(db, app_id, order.plan_snapshot):
            return
        if not await fulfill_paid_order(db, order):
            return
        audit(db, app_id, "order", order.id, "auto_repair_entitlements", None, "渠道签名查单确认，已补发原订单权益")


async def repair_due_differences(app_id: int) -> None:
    async with async_db_session() as db:
        entry_ids = list(
            await db.scalars(
                select(FinanceBillEntryModel.id)
                .join(PaymentOrderModel, PaymentOrderModel.id == FinanceBillEntryModel.order_id)
                .where(
                    FinanceBillEntryModel.app_id == app_id,
                    FinanceBillEntryModel.match_status == "payment_missing",
                    FinanceBillEntryModel.resolved_at.is_(None),
                    PaymentOrderModel.status == "paid",
                )
                .order_by(FinanceBillEntryModel.id)
                .limit(20)
            )
        )
        refunded = exists(select(PaymentRefundModel.id).where(PaymentRefundModel.order_id == PaymentOrderModel.id, PaymentRefundModel.app_id == app_id))
        order_ids = list(
            await db.scalars(
                select(PaymentOrderModel.id)
                .where(
                    PaymentOrderModel.app_id == app_id,
                    PaymentOrderModel.status == "paid",
                    PaymentOrderModel.amount_fen > 0,
                    PaymentOrderModel.paid_at.is_not(None),
                    PaymentOrderModel.updated_time <= datetime.now(UTC) - timedelta(minutes=10),
                    ~fulfilled_expression(),
                    ~refunded,
                )
                .order_by(PaymentOrderModel.id)
                .limit(20)
            )
        )
    for entry_id in entry_ids:
        try:
            await repair_bill_payment(app_id, entry_id)
        except Exception as exc:
            logger.warning("支付账单差异保留待核查: app_id={} entry_id={} exception_type={}", app_id, entry_id, type(exc).__name__)
    for order_id in order_ids:
        try:
            await repair_missing_entitlement(app_id, order_id)
        except Exception as exc:
            logger.warning("支付权益差异保留待核查: app_id={} order_id={} exception_type={}", app_id, order_id, type(exc).__name__)
