from datetime import UTC, datetime, time, timedelta

from sqlalchemy import Date, cast, func, select

from app.api.v1.module_growth.model import CashAccountModel, WithdrawalModel
from app.api.v1.module_payment.order.model import PaymentOrderModel, PaymentRefundModel

from .common import BUSINESS_TZ, channel_receipt_conditions, formal_order_condition
from .model import FinanceBillEntryModel, FinanceBillModel, FinanceIssueModel, FinanceRefundRequestModel


async def overview(db, app_id, start_date, end_date):
    start = datetime.combine(start_date, time.min, BUSINESS_TZ).astimezone(UTC)
    end = datetime.combine(end_date + timedelta(days=1), time.min, BUSINESS_TZ).astimezone(UTC)
    period = end - start

    async def metrics(left, right):
        async def money(model, column, timestamp, *conditions):
            stmt = select(func.coalesce(func.sum(column), 0)).where(model.app_id == app_id, model.is_deleted == False, timestamp >= left, timestamp < right, *conditions)
            return int(await db.scalar(stmt) or 0)

        paid = int(
            await db.scalar(
                select(func.count())
                .select_from(PaymentOrderModel)
                .where(PaymentOrderModel.app_id == app_id, PaymentOrderModel.is_deleted == False, PaymentOrderModel.paid_at >= left, PaymentOrderModel.paid_at < right, *channel_receipt_conditions())
            )
            or 0
        )
        received = await money(PaymentOrderModel, PaymentOrderModel.amount_fen, PaymentOrderModel.paid_at, *channel_receipt_conditions())
        refunds = await money(PaymentRefundModel, PaymentRefundModel.amount_fen, PaymentRefundModel.refunded_at, PaymentRefundModel.status == "succeeded")
        payouts = await money(WithdrawalModel, WithdrawalModel.amount_fen, WithdrawalModel.completed_at, WithdrawalModel.status == "succeeded")
        return {
            "received_fen": received,
            "refund_fen": refunds,
            "net_received_fen": received - refunds,
            "payout_fen": payouts,
            "paid_orders": paid,
            "average_order_fen": round(received / paid) if paid else 0,
        }

    current, previous = await metrics(start, end), await metrics(start - period, start)
    daily = {
        (start_date + timedelta(days=i)).isoformat(): {"date": (start_date + timedelta(days=i)).isoformat(), "received_fen": 0, "refund_fen": 0, "payout_fen": 0, "paid_orders": 0}
        for i in range((end_date - start_date).days + 1)
    }
    pg = db.bind.dialect.name == "postgresql"
    for model, timestamp, amount, metric, conditions in [
        (PaymentOrderModel, PaymentOrderModel.paid_at, PaymentOrderModel.amount_fen, "received_fen", channel_receipt_conditions()),
        (PaymentRefundModel, PaymentRefundModel.refunded_at, PaymentRefundModel.amount_fen, "refund_fen", [PaymentRefundModel.status == "succeeded"]),
        (WithdrawalModel, WithdrawalModel.completed_at, WithdrawalModel.amount_fen, "payout_fen", [WithdrawalModel.status == "succeeded"]),
    ]:
        day = cast(func.timezone("Asia/Shanghai", timestamp), Date) if pg else func.date(timestamp, "+8 hours")
        rows = await db.execute(select(day, func.sum(amount), func.count()).where(model.app_id == app_id, model.is_deleted == False, timestamp >= start, timestamp < end, *conditions).group_by(day))
        for when, total, count in rows:
            key = str(when)
            if key in daily:
                daily[key][metric] = int(total or 0)
                if metric == "received_fen":
                    daily[key]["paid_orders"] = count
    channels = []
    for provider in ("alipay", "wechat"):
        scope = [PaymentOrderModel.app_id == app_id, PaymentOrderModel.is_deleted == False, PaymentOrderModel.provider == provider, formal_order_condition(), PaymentOrderModel.amount_fen > 0]
        paid_count, paid_amount = (
            await db.execute(
                select(func.count(), func.coalesce(func.sum(PaymentOrderModel.amount_fen), 0)).where(
                    *scope, PaymentOrderModel.status == "paid", PaymentOrderModel.paid_at >= start, PaymentOrderModel.paid_at < end
                )
            )
        ).one()
        created = int(await db.scalar(select(func.count()).select_from(PaymentOrderModel).where(*scope, PaymentOrderModel.created_time >= start, PaymentOrderModel.created_time < end)) or 0)
        converted = int(
            await db.scalar(
                select(func.count())
                .select_from(PaymentOrderModel)
                .where(*scope, PaymentOrderModel.status == "paid", PaymentOrderModel.created_time >= start, PaymentOrderModel.created_time < end, PaymentOrderModel.paid_at.is_not(None))
            )
            or 0
        )
        refund = int(
            await db.scalar(
                select(func.coalesce(func.sum(PaymentRefundModel.amount_fen), 0)).where(
                    PaymentRefundModel.app_id == app_id,
                    PaymentRefundModel.provider == provider,
                    PaymentRefundModel.status == "succeeded",
                    PaymentRefundModel.refunded_at >= start,
                    PaymentRefundModel.refunded_at < end,
                )
            )
            or 0
        )
        channels.append(
            {
                "provider": provider,
                "received_fen": int(paid_amount),
                "paid_orders": paid_count,
                "refund_fen": refund,
                "created_orders": created,
                "converted_orders": converted,
                "conversion_rate": round(converted * 100 / created, 2) if created else None,
            }
        )
    tasks = {}
    for name, model, condition in [
        ("refund_review", FinanceRefundRequestModel, FinanceRefundRequestModel.status == "review"),
        ("payout_review", WithdrawalModel, WithdrawalModel.status == "review"),
        ("payout_processing", WithdrawalModel, WithdrawalModel.status.in_(["queued", "processing", "unknown", "confirming"])),
        ("open_issues", FinanceIssueModel, FinanceIssueModel.status != "resolved"),
    ]:
        tasks[name] = int(await db.scalar(select(func.count()).select_from(model).where(model.app_id == app_id, condition)) or 0)
    balances = (
        await db.execute(
            select(func.coalesce(func.sum(CashAccountModel.available), 0), func.coalesce(func.sum(CashAccountModel.frozen), 0), func.coalesce(func.sum(CashAccountModel.debt), 0)).where(
                CashAccountModel.app_id == app_id
            )
        )
    ).one()
    bills = list(await db.scalars(select(FinanceBillModel).where(FinanceBillModel.app_id == app_id, FinanceBillModel.bill_date >= start_date, FinanceBillModel.bill_date <= end_date)))
    fees = await db.scalar(
        select(func.sum(FinanceBillEntryModel.fee_fen)).where(
            FinanceBillEntryModel.app_id == app_id, FinanceBillEntryModel.bill_id.in_([b.id for b in bills if b.status in ("completed", "differences")]), FinanceBillEntryModel.entry_type == "payment"
        )
    )
    return {
        "start_date": start_date,
        "end_date": end_date,
        "generated_at": datetime.now(UTC),
        "current": current,
        "previous": previous,
        "daily": list(daily.values()),
        "channels": channels,
        "tasks": tasks,
        "promotion_balances": {"available_fen": int(balances[0]), "frozen_fen": int(balances[1]), "debt_fen": int(balances[2])},
        "reconciliation": {
            "completed_days": sum(b.status in ("completed", "differences") for b in bills),
            "failed_days": sum(b.status == "failed" for b in bills),
            "difference_count": sum(int((b.summary or {}).get("differences", 0)) for b in bills),
            "verified_fee_fen": int(fees) if fees is not None else None,
        },
    }
