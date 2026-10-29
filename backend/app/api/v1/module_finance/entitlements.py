from sqlalchemy import and_, or_, select

from app.api.v1.module_billing.model import CreditGrantModel, CreditLedgerModel, SubscriptionCycleModel, SubscriptionModel
from app.api.v1.module_billing.service import CreditService


async def terminate_order_entitlements(db, order, refund_no: str) -> dict:
    """Revoke only this order's remaining rights; reserved usage settles without re-release."""
    account = await CreditService(db).account(order.app_id, order.user_id, lock=True)
    from app.api.v1.module_billing.duration import reflow_duration_refund

    await reflow_duration_refund(db, order)
    cycles = list(
        await db.scalars(
            select(SubscriptionCycleModel)
            .where(SubscriptionCycleModel.app_id == order.app_id, SubscriptionCycleModel.order_id == order.id, SubscriptionCycleModel.is_deleted == False)
            .with_for_update()
        )
    )
    grants = list(
        await db.scalars(
            select(CreditGrantModel)
            .where(
                CreditGrantModel.app_id == order.app_id,
                CreditGrantModel.user_id == order.user_id,
                CreditGrantModel.is_deleted == False,
                or_(
                    and_(CreditGrantModel.source_type == "credit_pack_order", CreditGrantModel.source_id == order.id),
                    and_(CreditGrantModel.source_type == "subscription_cycle", CreditGrantModel.source_id.in_([c.id for c in cycles])),
                ),
            )
            .with_for_update()
        )
    )
    result = {
        "action": "terminate",
        "entitlement_kind": order.plan_snapshot.get("entitlement_kind", "credits"),
        "revoked_available": 0,
        "cancelled_pending": 0,
        "reserved_at_refund": 0,
        "consumed_or_expired": 0,
        "superseded_credits": 0,
        "cycles_cancelled": 0,
    }
    for grant in grants:
        prior = await db.scalar(select(CreditLedgerModel.id).where(CreditLedgerModel.app_id == order.app_id, CreditLedgerModel.idempotency_key == f"order-refund:{order.app_id}:{grant.id}"))
        if grant.status == "refunded" or prior:
            continue
        available = grant.available
        pending = grant.amount if grant.status == "pending" else 0
        result["revoked_available"] += available
        result["cancelled_pending"] += pending
        result["reserved_at_refund"] += grant.reserved
        superseded = grant.amount if grant.status == "superseded" else 0
        result["superseded_credits"] += superseded
        result["consumed_or_expired"] += max(0, grant.amount - available - pending - superseded - grant.reserved)
        account.available -= available
        account.pending -= pending
        grant.available = 0
        grant.status = "refunded"
        db.add(
            CreditLedgerModel(
                app_id=order.app_id,
                user_id=order.user_id,
                grant_id=grant.id,
                entry_type="order_refund",
                amount=-available,
                balance_after=account.available,
                idempotency_key=f"order-refund:{order.app_id}:{grant.id}",
                reference_type="payment_order",
                reference_id=str(order.id),
                reason=f"退款{refund_no}终止剩余权益；取消待释放{pending}积分",
                status="posted",
            )
        )
    if account.available < 0 or account.pending < 0:
        from app.core.exceptions import CustomException

        raise CustomException(msg="权益账户与批次余额不一致，请核查后重试", status_code=409)
    for cycle in cycles:
        if cycle.status != "refunded":
            result["cycles_cancelled"] += int(cycle.status == "active")
            cycle.status = "refunded"
    await db.flush()
    for subscription_id in {c.subscription_id for c in cycles}:
        subscription = await db.scalar(select(SubscriptionModel).where(SubscriptionModel.app_id == order.app_id, SubscriptionModel.id == subscription_id).with_for_update())
        if not subscription:
            continue
        from app.api.v1.module_billing.subscription_periods import apply_subscription_projection, project_subscription

        projection = await project_subscription(db, subscription, respect_cancellation=True)
        apply_subscription_projection(subscription, projection)
        result.update(subscription_after=projection["plan_name"], subscription_ends_at=projection["ends_at"].isoformat() if projection["ends_at"] else None)
    return result


async def preview_order_entitlements(db, order, action):
    """Read-only estimate; calculated again at approval and at channel success."""
    from app.api.v1.module_billing.subscription_periods import project_subscription

    cycles = list(
        await db.scalars(
            select(SubscriptionCycleModel).where(
                SubscriptionCycleModel.app_id == order.app_id,
                SubscriptionCycleModel.order_id == order.id,
                SubscriptionCycleModel.is_deleted == False,
            )
        )
    )
    grants = list(
        await db.scalars(
            select(CreditGrantModel).where(
                CreditGrantModel.app_id == order.app_id,
                CreditGrantModel.user_id == order.user_id,
                CreditGrantModel.is_deleted == False,
                CreditGrantModel.status != "refunded",
                or_(
                    and_(CreditGrantModel.source_type == "credit_pack_order", CreditGrantModel.source_id == order.id),
                    and_(CreditGrantModel.source_type == "subscription_cycle", CreditGrantModel.source_id.in_([c.id for c in cycles])),
                ),
            )
        )
    )
    subscription = await db.scalar(
        select(SubscriptionModel).where(
            SubscriptionModel.app_id == order.app_id,
            SubscriptionModel.user_id == order.user_id,
            SubscriptionModel.is_deleted == False,
        )
    )
    empty = {"status": "cancelled", "catalog_plan_id": None, "plan_name": "无有效订阅", "starts_at": None, "ends_at": None}
    before = await project_subscription(db, subscription, respect_cancellation=True) if subscription else empty
    after = await project_subscription(db, subscription, exclude_order_id=order.id, respect_cancellation=True) if subscription and action == "terminate" else before
    return {
        "entitlement_kind": order.plan_snapshot.get("entitlement_kind", "credits"),
        "action": action,
        "before": before,
        "after": after,
        "revoked_available": sum(g.available for g in grants) if action == "terminate" else 0,
        "cancelled_pending": sum(g.amount for g in grants if g.status == "pending") if action == "terminate" else 0,
        "reserved_at_refund": sum(g.reserved for g in grants),
        "consumed_or_expired": sum(max(0, g.amount - g.available - g.reserved - (g.amount if g.status in {"pending", "superseded"} else 0)) for g in grants),
        "superseded_credits": sum(g.amount for g in grants if g.status == "superseded"),
        "cycles_cancelled": sum(c.status == "active" for c in cycles) if action == "terminate" else 0,
    }
