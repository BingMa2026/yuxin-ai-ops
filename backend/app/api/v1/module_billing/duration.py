"""Duration uses the existing paid-order periods, without issuing any credits."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.core.exceptions import CustomException

from .model import SubscriptionCycleModel, SubscriptionModel


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def activate_duration_order(db, *, app_id, user_id, order_id, catalog_plan_id, snapshot):
    from .service import CreditService

    days = snapshot.get("benefit_period_days")
    if type(days) is not int or not 1 <= days <= 3650 or snapshot.get("total_credits", 0) != 0 or snapshot.get("release_plan"):
        raise CustomException(msg="订单时长权益快照无效，请联系运营处理", status_code=409)
    # Reuse the same per-user financial mutex as refunds and legacy payments.
    # The zero-balance account is only a lock; no grants or credit entries occur.
    await CreditService(db).account(app_id, user_id, lock=True)
    prior = await db.scalar(
        select(SubscriptionCycleModel).where(
            SubscriptionCycleModel.app_id == app_id,
            SubscriptionCycleModel.user_id == user_id,
            SubscriptionCycleModel.order_id == order_id,
        )
    )
    if prior:
        return await db.get(SubscriptionModel, prior.subscription_id)
    now = datetime.now(UTC)
    subscription = await db.scalar(
        select(SubscriptionModel)
        .where(
            SubscriptionModel.app_id == app_id,
            SubscriptionModel.user_id == user_id,
            SubscriptionModel.is_deleted == False,
        )
        .with_for_update()
    )
    start = now
    suspended = subscription is not None and subscription.status == "cancelled"
    if subscription:
        if subscription.status in {"active", "cancelled"} and utc(subscription.current_period_end) > now:
            if subscription.entitlement_kind != "duration":
                raise CustomException(msg="现有订阅权益类型不同，请先完成权益承接", status_code=409)
            start = utc(subscription.current_period_end)
    else:
        subscription = SubscriptionModel(app_id=app_id, user_id=user_id, catalog_plan_id=catalog_plan_id, current_period_start=now, current_period_end=now)
        db.add(subscription)
        await db.flush()
    subscription.entitlement_kind = "duration"
    subscription.catalog_plan_id = catalog_plan_id
    # Buying time must not undo an operator's suspension.
    subscription.status = "cancelled" if suspended else "active"
    subscription.auto_renew = False
    subscription.next_renewal_at = None
    if start == now:
        subscription.current_period_start = now
    subscription.current_period_end = start + timedelta(days=days)
    sequence = await db.scalar(
        select(func.max(SubscriptionCycleModel.cycle_no)).where(
            SubscriptionCycleModel.app_id == app_id,
            SubscriptionCycleModel.subscription_id == subscription.id,
        )
    )
    db.add(
        SubscriptionCycleModel(
            app_id=app_id,
            user_id=user_id,
            subscription_id=subscription.id,
            order_id=order_id,
            cycle_no=int(sequence or 0) + 1,
            starts_at=start,
            ends_at=subscription.current_period_end,
            plan_snapshot=snapshot,
            status="active",
        )
    )
    await db.flush()
    return subscription


def duration_intervals(cycles, *, excluded_order_id=None, now=None):
    """Pure refund preview; remove only the target's unused interval, close gaps."""
    now = now or datetime.now(UTC)
    shift = timedelta(0)
    result = []
    for cycle in sorted(cycles, key=lambda c: (utc(c.starts_at), c.cycle_no)):
        if cycle.status != "active" or cycle.plan_snapshot.get("entitlement_kind") != "duration":
            continue
        start, end = utc(cycle.starts_at), utc(cycle.ends_at)
        if excluded_order_id is not None and cycle.order_id == excluded_order_id:
            shift += max(end - max(start, now), timedelta(0))
            continue
        result.append((cycle, start - shift, end - shift))
    return result


async def reflow_duration_refund(db, order, *, now=None):
    if order.plan_snapshot.get("entitlement_kind") != "duration":
        return
    cycles = list(
        await db.scalars(
            select(SubscriptionCycleModel)
            .where(
                SubscriptionCycleModel.app_id == order.app_id,
                SubscriptionCycleModel.user_id == order.user_id,
                SubscriptionCycleModel.is_deleted == False,
            )
            .with_for_update()
        )
    )
    for cycle, start, end in duration_intervals(cycles, excluded_order_id=order.id, now=now):
        cycle.starts_at, cycle.ends_at = start, end
