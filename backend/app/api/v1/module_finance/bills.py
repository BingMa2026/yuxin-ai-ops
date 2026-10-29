import asyncio
import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.api.v1.module_growth.service import lock_app
from app.api.v1.module_payment.order.model import PaymentOrderModel, PaymentRefundModel
from app.core.database import async_db_session
from app.core.exceptions import CustomException

from .bill_gateway import download_bill, parse_bill
from .common import BUSINESS_TZ, audit, channel_receipt_conditions, date_conditions, formal_order_condition, utc
from .gateway import identity
from .model import FinanceBillEntryModel, FinanceBillModel
from .schema import BillCreate, FinanceQuery


async def request_bill_batch(db, app_id, operator, data):
    if data.end_date >= datetime.now(BUSINESS_TZ).date():
        raise CustomException(msg="只能核对已结束的账期，请选择昨日或更早日期", status_code=422)
    return [await request_bill(db, app_id, operator, BillCreate(provider=data.provider, bill_date=data.start_date + timedelta(days=i))) for i in range((data.end_date - data.start_date).days + 1)]


async def schedule_daily_bills(db, app_id, *, now=None):
    from app.api.v1.module_payment.channel.model import AppPaymentChannelModel, PaymentChannelModel
    from app.api.v1.module_payment.channel.service import PaymentChannelService
    from app.config.setting import settings

    now = (now or datetime.now(UTC)).astimezone(BUSINESS_TZ)
    if not settings.FINANCE_AUTO_RECONCILE or now.hour < settings.FINANCE_RECONCILE_HOUR:
        return []
    day = now.date() - timedelta(days=1)
    await lock_app(db, app_id)
    channels = list(
        await db.scalars(
            select(PaymentChannelModel)
            .join(
                AppPaymentChannelModel,
                AppPaymentChannelModel.channel_id == PaymentChannelModel.id,
            )
            .where(
                AppPaymentChannelModel.app_id == app_id,
                AppPaymentChannelModel.enabled == True,
                AppPaymentChannelModel.is_deleted == False,
                PaymentChannelModel.is_deleted == False,
                PaymentChannelModel.enabled == True,
                PaymentChannelModel.mode == "production",
            )
        )
    )
    created = []
    for channel in channels:
        if channel.provider not in ("alipay", "wechat"):
            continue
        missing, _, _ = PaymentChannelService._runtime_status(channel.provider, channel.mode)
        if missing:
            continue
        existing = await db.scalar(
            select(FinanceBillModel.id).where(
                FinanceBillModel.app_id == app_id,
                FinanceBillModel.provider == channel.provider,
                FinanceBillModel.bill_date == day,
            )
        )
        if existing:
            # Completed and failed days alike remain untouched by the scheduler.
            # Failed days are explicitly retried from the list, never every minute.
            continue
        created.append(await request_bill(db, app_id, 0, BillCreate(provider=channel.provider, bill_date=day)))
    return created


async def request_bill(db, app_id, operator, data):
    if data.bill_date >= datetime.now(BUSINESS_TZ).date():
        raise CustomException(msg="只能核对已结束的账期，请选择昨日或更早日期", status_code=422)
    await lock_app(db, app_id)
    row = await db.scalar(select(FinanceBillModel).where(FinanceBillModel.app_id == app_id, FinanceBillModel.provider == data.provider, FinanceBillModel.bill_date == data.bill_date))
    if row:
        if row.status == "failed":
            row.status, row.next_attempt_at, row.error_message = "queued", datetime.now(UTC), None
            audit(db, app_id, "bill", row.id, "retry", operator, "重新下载该账期渠道账单")
        return row
    row = FinanceBillModel(
        app_id=app_id, provider=data.provider, bill_date=data.bill_date, merchant_identity=identity(data.provider), requested_by=operator, status="queued", next_attempt_at=datetime.now(UTC)
    )
    db.add(row)
    await db.flush()
    audit(db, app_id, "bill", row.id, "request", operator or None, "自动申请昨日渠道账单" if operator == 0 else "申请渠道交易账单并核对当前客户端流水")
    return row


async def reconcile_bill(db, bill, lines):
    # Query only identifiers in this bill and movements in its day. Historical
    # orders from the whole app must not be loaded for each daily reconciliation.
    q = FinanceQuery(start_date=bill.bill_date, end_date=bill.bill_date)
    day_orders = list(
        await db.scalars(
            select(PaymentOrderModel).where(
                PaymentOrderModel.app_id == bill.app_id,
                PaymentOrderModel.provider == bill.provider,
                PaymentOrderModel.is_deleted == False,
                *channel_receipt_conditions(),
                *date_conditions(PaymentOrderModel.paid_at, q),
            )
        )
    )
    day_refunds = list(
        await db.scalars(
            select(PaymentRefundModel).where(
                PaymentRefundModel.app_id == bill.app_id, PaymentRefundModel.provider == bill.provider, PaymentRefundModel.status == "succeeded", *date_conditions(PaymentRefundModel.refunded_at, q)
            )
        )
    )
    order_rows = {o.id: o for o in day_orders}
    numbers = list({line.order_no for line in lines})
    missing_ids = list({r.order_id for r in day_refunds} - order_rows.keys())
    base = select(PaymentOrderModel).where(
        PaymentOrderModel.app_id == bill.app_id, PaymentOrderModel.provider == bill.provider, PaymentOrderModel.is_deleted == False, formal_order_condition(), PaymentOrderModel.amount_fen > 0
    )
    for keys, column in ((numbers, PaymentOrderModel.order_no), (missing_ids, PaymentOrderModel.id)):
        for offset in range(0, len(keys), 500):
            order_rows.update({o.id: o for o in await db.scalars(base.where(column.in_(keys[offset : offset + 500])))})
    orders = list(order_rows.values())
    lookup = {o.order_no: o for o in orders}
    ids = list(order_rows)
    refunds = []
    for offset in range(0, len(ids), 500):
        refunds.extend(
            await db.scalars(
                select(PaymentRefundModel).where(
                    PaymentRefundModel.app_id == bill.app_id,
                    PaymentRefundModel.provider == bill.provider,
                    PaymentRefundModel.status == "succeeded",
                    PaymentRefundModel.order_id.in_(ids[offset : offset + 500]),
                )
            )
        )
    refund_map = {(r.order_id, r.refund_no): r for r in refunds}
    entries, seen, excluded = [], set(), 0
    for line in lines:
        order = lookup.get(line.order_no)
        if not order:
            excluded += 1
            continue
        key = (line.kind, order.id, line.refund_no if line.kind == "refund" else "")
        if key in seen:
            raise CustomException(msg="账单出现重复业务流水，需人工核查，未覆盖原对账结果", status_code=409)
        seen.add(key)
        refund = refund_map.get((order.id, line.refund_no)) if line.kind == "refund" else None
        if line.kind == "refund" and not refund:
            legacy_no = "GXRF" + hashlib.sha256(f"{bill.provider}:{order.order_no}:{line.refund_no}".encode()).hexdigest()[:56]
            refund = refund_map.get((order.id, legacy_no))
        if refund:
            seen.add(("refund", order.id, refund.refund_no))
        system_amount = refund.amount_fen if refund else order.amount_fen if line.kind == "payment" and order.paid_at else 0
        state = "matched"
        if line.kind == "payment" and not order.paid_at and not order.provider_trade_no:
            state = "payment_missing"
        elif line.trade_no != order.provider_trade_no:
            state = "trade_mismatch"
        elif line.kind == "refund" and not refund:
            state = "refund_missing"
        elif line.kind == "payment" and not order.paid_at:
            state = "payment_missing"
        elif line.amount != system_amount:
            state = "amount_mismatch"
        entries.append(
            FinanceBillEntryModel(
                app_id=bill.app_id,
                bill_id=bill.id,
                entry_key=hashlib.sha256(repr(key).encode()).hexdigest(),
                order_id=order.id,
                order_no=order.order_no,
                provider_trade_no=line.trade_no,
                refund_no=line.refund_no or None,
                entry_type=line.kind,
                channel_amount_fen=line.amount,
                system_amount_fen=system_amount,
                fee_fen=line.fee,
                occurred_at=refund.refunded_at if refund else order.paid_at,
                match_status=state,
            )
        )
    for kind, records in (("payment", day_orders), ("refund", day_refunds)):
        for row in records:
            order = row if kind == "payment" else order_rows.get(row.order_id)
            if not order:
                continue
            key = (kind, order.id, row.refund_no if kind == "refund" else "")
            if key not in seen:
                entries.append(
                    FinanceBillEntryModel(
                        app_id=bill.app_id,
                        bill_id=bill.id,
                        entry_key=hashlib.sha256(repr(key).encode()).hexdigest(),
                        order_id=order.id,
                        order_no=order.order_no,
                        provider_trade_no=order.provider_trade_no,
                        refund_no=row.refund_no if kind == "refund" else None,
                        entry_type=kind,
                        channel_amount_fen=0,
                        system_amount_fen=row.amount_fen,
                        match_status="channel_missing",
                    )
                )
    db.add_all(entries)
    bill.summary = {
        "entries": len(entries),
        "matched": sum(e.match_status == "matched" for e in entries),
        "differences": sum(e.match_status != "matched" for e in entries),
        "excluded_merchant_rows": excluded,
        "payment_fen": sum(e.channel_amount_fen for e in entries if e.entry_type == "payment"),
        "refund_fen": sum(e.channel_amount_fen for e in entries if e.entry_type == "refund"),
        "fee_fen": sum(e.fee_fen or 0 for e in entries),
        "fee_rows": sum(e.fee_fen is not None for e in entries),
    }
    bill.status, bill.completed_at, bill.next_attempt_at = "completed", datetime.now(UTC), None
    audit(db, bill.app_id, "bill", bill.id, "reconcile", None, "已完成当前客户端交易与退款流水核对", after=bill.summary)


async def dispatch_bill(app_id, bill_id):
    async with async_db_session() as db, db.begin():
        await lock_app(db, app_id)
        bill = await db.scalar(select(FinanceBillModel).where(FinanceBillModel.app_id == app_id, FinanceBillModel.id == bill_id))
        if not bill or bill.status not in ("queued", "downloading") or (bill.next_attempt_at and utc(bill.next_attempt_at) > datetime.now(UTC)):
            return
        if identity(bill.provider) != bill.merchant_identity:
            bill.status, bill.error_message = "failed", "商户配置发生变更，无法继续原账单任务"
            return
        provider, day = bill.provider, bill.bill_date
        bill.status, bill.next_attempt_at = "downloading", datetime.now(UTC) + timedelta(minutes=10)
    try:
        content, digest = await download_bill(provider, day)
        lines = await asyncio.to_thread(parse_bill, content, provider)
        async with async_db_session() as db, db.begin():
            await lock_app(db, app_id)
            bill = await db.scalar(select(FinanceBillModel).where(FinanceBillModel.app_id == app_id, FinanceBillModel.id == bill_id))
            if bill.status == "completed":
                return
            bill.file_digest, bill.downloaded_at = digest, datetime.now(UTC)
            await reconcile_bill(db, bill, lines)
    except Exception as exc:
        async with async_db_session() as db, db.begin():
            await lock_app(db, app_id)
            bill = await db.scalar(select(FinanceBillModel).where(FinanceBillModel.app_id == app_id, FinanceBillModel.id == bill_id))
            if bill.status != "completed":
                bill.status, bill.next_attempt_at = "failed", None
                bill.error_message = exc.msg if isinstance(exc, CustomException) else "账单下载或解析失败，请重试；持续失败请检查渠道账单权限与文件格式"
                audit(db, app_id, "bill", bill.id, "failed", None, bill.error_message)


async def resolve_entry(db, app_id, entry_id, operator, reason):
    await lock_app(db, app_id)
    entry = await db.scalar(select(FinanceBillEntryModel).where(FinanceBillEntryModel.app_id == app_id, FinanceBillEntryModel.id == entry_id))
    if not entry:
        raise CustomException(msg="对账明细不存在", status_code=404)
    if entry.match_status == "matched":
        raise CustomException(msg="该流水已匹配，无需人工处理", status_code=409)
    entry.resolution, entry.resolved_by, entry.resolved_at = reason, operator, datetime.now(UTC)
    audit(db, app_id, "bill_entry", entry.id, "resolve", operator, reason, {"match_status": entry.match_status}, {"resolution": reason})
    return entry
