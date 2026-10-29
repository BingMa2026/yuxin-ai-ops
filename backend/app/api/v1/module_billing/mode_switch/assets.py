"""Inspect and retire explicitly confirmed remaining benefits under the account lock."""

from datetime import UTC, datetime

from sqlalchemy import select

from app.api.v1.module_billing.duration import utc
from app.api.v1.module_billing.model import CreditGrantModel, CreditLedgerModel, CreditReservationModel, SubscriptionCycleModel, SubscriptionModel
from app.api.v1.module_finance.model import FinanceRefundRequestModel


async def remaining_assets(db, app_id, user_id, source_mode):
    from app.api.v1.module_billing.service import CreditService

    account = await CreditService(db).account(app_id, user_id, lock=True)
    reserved = await db.scalar(
        select(CreditReservationModel.id).where(CreditReservationModel.app_id == app_id, CreditReservationModel.user_id == user_id, CreditReservationModel.status == "reserved").limit(1)
    )
    refunds = await db.scalar(
        select(FinanceRefundRequestModel.id)
        .where(FinanceRefundRequestModel.app_id == app_id, FinanceRefundRequestModel.user_id == user_id, FinanceRefundRequestModel.status.in_(["review", "queued", "processing", "unknown"]))
        .limit(1)
    )
    blocked = "存在模型调用预占或待处理退款，请结算完成后重试" if account.reserved or reserved or refunds else None
    now = datetime.now(UTC)
    summary = {"available_credits_to_expire": 0, "pending_credits_to_expire": 0, "duration_seconds_to_expire": 0, "items": []}
    grants = []
    if source_mode == "credits":
        grants = list(
            await db.scalars(
                select(CreditGrantModel)
                .where(CreditGrantModel.app_id == app_id, CreditGrantModel.user_id == user_id, CreditGrantModel.is_deleted == False, CreditGrantModel.status.in_(["pending", "released"]))
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        for grant in grants:
            pending = grant.amount if grant.status == "pending" else 0
            summary["available_credits_to_expire"] += grant.available
            summary["pending_credits_to_expire"] += pending
            if grant.reserved:
                blocked = "存在未结算积分，请稍后重试"
            if grant.available or pending:
                summary["items"].append({"kind": "credit_grant", "id": grant.id, "source": grant.source_type, "available": grant.available, "pending": pending})
        if (summary["available_credits_to_expire"], summary["pending_credits_to_expire"]) != (account.available, account.pending):
            blocked = "积分账户与权益明细不一致，请联系运营核对"
    sub = await db.scalar(
        select(SubscriptionModel)
        .where(SubscriptionModel.app_id == app_id, SubscriptionModel.user_id == user_id, SubscriptionModel.is_deleted == False)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    cycles = list(
        await db.scalars(
            select(SubscriptionCycleModel)
            .where(SubscriptionCycleModel.app_id == app_id, SubscriptionCycleModel.user_id == user_id, SubscriptionCycleModel.is_deleted == False, SubscriptionCycleModel.status == "active")
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    if sub and sub.entitlement_kind != source_mode and utc(sub.current_period_end) > now:
        blocked = "当前模式与订阅记录不一致，请联系运营核对"
    if any(c.plan_snapshot.get("entitlement_kind", "credits") != source_mode and utc(c.ends_at) > now for c in cycles):
        blocked = "存在其他模式的未结束权益，请联系运营核对"
    cycles = [c for c in cycles if c.plan_snapshot.get("entitlement_kind", "credits") == source_mode]
    for cycle in cycles:
        if utc(cycle.ends_at) > now:
            summary["items"].append(
                {
                    "kind": "subscription_cycle",
                    "id": cycle.id,
                    "source": "subscription" if cycle.order_id else "manual_duration_adjustment",
                    "starts_at": utc(cycle.starts_at).isoformat(),
                    "ends_at": utc(cycle.ends_at).isoformat(),
                }
            )
    if sub and sub.entitlement_kind == source_mode and utc(sub.current_period_end) > now:
        summary["items"].append(
            {"kind": "subscription", "id": sub.id, "source": "subscription", "starts_at": utc(sub.current_period_start).isoformat(), "ends_at": utc(sub.current_period_end).isoformat()}
        )
        if source_mode == "duration":
            summary["duration_seconds_to_expire"] = max(0, int((utc(sub.current_period_end) - now).total_seconds()))
    return summary, blocked, account, grants, sub, cycles


async def reset_assets(db, order, assets):
    summary, _, account, grants, sub, cycles = assets
    for grant in grants:
        amount = grant.available
        pending = grant.amount if grant.status == "pending" else 0
        if not amount and not pending:
            continue
        account.available -= amount
        account.pending -= pending
        grant.available = 0
        grant.status = "mode_reset"
        db.add(
            CreditLedgerModel(
                app_id=order.app_id,
                user_id=order.user_id,
                grant_id=grant.id,
                entry_type="mode_reset",
                amount=-amount,
                balance_after=account.available,
                idempotency_key=f"mode-reset:{order.id}:{grant.id}",
                reference_type="payment_order",
                reference_id=str(order.id),
                reason=f"用户确认切换模式，失效可用积分{amount}、待释放积分{pending}",
                status="posted",
            )
        )
    for cycle in cycles:
        if utc(cycle.ends_at) > datetime.now(UTC):
            cycle.status = "mode_reset"
    if sub:
        sub.status = "expired"
        sub.auto_renew = False
        sub.next_renewal_at = None
        sub.current_period_end = min(utc(sub.current_period_end), datetime.now(UTC))
    await db.flush()
    return summary
