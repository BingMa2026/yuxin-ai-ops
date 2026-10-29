"""Project the current subscription from paid, non-refunded order periods."""

from datetime import UTC, datetime

from sqlalchemy import select

from app.api.v1.module_payment.order.model import PaymentOrderModel

from .model import AppCatalogPlanModel, SubscriptionCycleModel


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def project_subscription(db, subscription, *, exclude_order_id=None, now=None, respect_cancellation=False):
    suspended = respect_cancellation and subscription.status == "cancelled"
    if suspended and subscription.entitlement_kind != "duration":
        return {"status": "cancelled", "catalog_plan_id": None, "plan_name": "无有效订阅", "starts_at": None, "ends_at": None}
    now = now or datetime.now(UTC)
    rows = list(
        (
            await db.execute(
                select(SubscriptionCycleModel, PaymentOrderModel, AppCatalogPlanModel)
                .join(PaymentOrderModel, PaymentOrderModel.id == SubscriptionCycleModel.order_id)
                .join(AppCatalogPlanModel, AppCatalogPlanModel.id == PaymentOrderModel.catalog_plan_id)
                .where(
                    SubscriptionCycleModel.app_id == subscription.app_id,
                    SubscriptionCycleModel.subscription_id == subscription.id,
                    SubscriptionCycleModel.user_id == subscription.user_id,
                    SubscriptionCycleModel.status == "active",
                    SubscriptionCycleModel.is_deleted == False,
                    PaymentOrderModel.app_id == subscription.app_id,
                    PaymentOrderModel.is_deleted == False,
                    PaymentOrderModel.status == "paid",
                    AppCatalogPlanModel.app_id == subscription.app_id,
                )
            )
        ).all()
    )
    if subscription.entitlement_kind == "duration":
        from .duration import duration_intervals

        manual = list(
            await db.scalars(
                select(SubscriptionCycleModel).where(
                    SubscriptionCycleModel.app_id == subscription.app_id,
                    SubscriptionCycleModel.user_id == subscription.user_id,
                    SubscriptionCycleModel.subscription_id == subscription.id,
                    SubscriptionCycleModel.order_id.is_(None),
                    SubscriptionCycleModel.is_deleted == False,
                    SubscriptionCycleModel.status == "active",
                )
            )
        )
        manual = [c for c in manual if c.plan_snapshot.get("source") == "manual_duration_adjustment"]
        intervals = duration_intervals([r[0] for r in rows] + manual, excluded_order_id=exclude_order_id, now=now)
        live = [(c, start, end) for c, start, end in intervals if start <= now < end]
        if not live:
            return {"status": "cancelled" if suspended else "expired", "catalog_plan_id": None, "plan_name": "无有效订阅", "starts_at": None, "ends_at": None}
        cycle, start, end = live[0]
        for _, other_start, other_end in intervals:
            if other_start <= end:
                end = max(end, other_end)
        current = next((r for r in rows if r[0].id == cycle.id), None)
        return {
            "status": "cancelled" if suspended else "active",
            "catalog_plan_id": current[1].catalog_plan_id if current else cycle.plan_snapshot["catalog_plan_id"],
            "plan_name": cycle.plan_snapshot.get("name") or (current[2].name if current else "人工开通时长"),
            "starts_at": start,
            "ends_at": end,
        }
    rows = [r for r in rows if r[1].id != exclude_order_id and utc(r[0].ends_at) > now]
    active = [r for r in rows if utc(r[0].starts_at) <= now]
    if not active:
        return {"status": "expired" if rows else "cancelled", "catalog_plan_id": None, "plan_name": "无有效订阅", "starts_at": None, "ends_at": None}
    cycle, order, plan = max(active, key=lambda r: (int(r[0].plan_snapshot.get("tier_order", r[2].tier_order)), utc(r[0].starts_at), r[0].cycle_no))
    end = utc(cycle.ends_at)
    # Same-plan renewals extend the current interval; a future different plan
    # must never become the user's current plan before its own start time.
    for other, other_order, _ in sorted(rows, key=lambda r: utc(r[0].starts_at)):
        if other_order.catalog_plan_id == order.catalog_plan_id and utc(other.starts_at) <= end:
            end = max(end, utc(other.ends_at))
    return {"status": "active", "catalog_plan_id": order.catalog_plan_id, "plan_name": cycle.plan_snapshot.get("name") or plan.name, "starts_at": utc(cycle.starts_at), "ends_at": end}


def apply_subscription_projection(subscription, projection):
    subscription.status = projection["status"]
    if projection["catalog_plan_id"] is not None:
        subscription.catalog_plan_id = projection["catalog_plan_id"]
        subscription.current_period_start = projection["starts_at"]
        subscription.current_period_end = projection["ends_at"]
        subscription.next_renewal_at = projection["ends_at"] if subscription.auto_renew else None
    else:
        subscription.auto_renew = False
        subscription.next_renewal_at = None
        subscription.current_period_end = min(utc(subscription.current_period_end), datetime.now(UTC))
