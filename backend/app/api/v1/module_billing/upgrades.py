"""Stop unreleased lower-tier credits without spending the user's balance."""

from sqlalchemy import select

from .model import CreditGrantModel, CreditLedgerModel, SubscriptionCycleModel


async def supersede_pending_grants(db, account, *, new_cycle, now):
    rows = (
        await db.execute(
            select(CreditGrantModel, SubscriptionCycleModel)
            .join(SubscriptionCycleModel, SubscriptionCycleModel.id == CreditGrantModel.source_id)
            .where(
                CreditGrantModel.app_id == account.app_id,
                CreditGrantModel.user_id == account.user_id,
                CreditGrantModel.source_type == "subscription_cycle",
                CreditGrantModel.status == "pending",
                CreditGrantModel.is_deleted == False,
                SubscriptionCycleModel.app_id == account.app_id,
                SubscriptionCycleModel.user_id == account.user_id,
                SubscriptionCycleModel.id < new_cycle.id,
                SubscriptionCycleModel.status == "active",
                SubscriptionCycleModel.is_deleted == False,
                SubscriptionCycleModel.ends_at > new_cycle.starts_at,
            )
            .with_for_update(of=CreditGrantModel)
            .execution_options(populate_existing=True)
        )
    ).all()
    rank = int(new_cycle.plan_snapshot.get("tier_order") or 0)
    for grant, cycle in rows:
        if rank <= int(cycle.plan_snapshot.get("tier_order") or 0):
            continue
        # The original period remains available for refund rollback. Only its
        # not-yet-issued credits are cancelled; released/reserved lots stay intact.
        grant.status = "superseded"
        account.pending -= grant.amount
        if account.pending < 0:
            from app.core.exceptions import CustomException

            raise CustomException(msg="待发放账户与积分批次不一致，请核查后重试", status_code=409)
        db.add(
            CreditLedgerModel(
                app_id=account.app_id,
                user_id=account.user_id,
                grant_id=grant.id,
                entry_type="subscription_upgrade",
                amount=0,
                balance_after=account.available,
                idempotency_key=f"supersede:{account.app_id}:{grant.id}",
                reference_type="payment_order",
                reference_id=str(new_cycle.order_id),
                reason=f"升级套餐，取消原套餐待发放积分 {grant.amount:,}，已到账积分不变",
                status="posted",
            )
        )
    await db.flush()


async def suppress_legacy_upgrade_grants(db, account, *, now):
    """Reconcile pre-fix upgrades under the account lock before releasing credits."""
    from app.api.v1.module_payment.order.model import PaymentOrderModel

    cycles = (
        await db.scalars(
            select(SubscriptionCycleModel)
            .join(PaymentOrderModel, PaymentOrderModel.id == SubscriptionCycleModel.order_id)
            .where(
                SubscriptionCycleModel.app_id == account.app_id,
                SubscriptionCycleModel.user_id == account.user_id,
                SubscriptionCycleModel.is_deleted == False,
                SubscriptionCycleModel.status == "active",
                SubscriptionCycleModel.starts_at <= now,
                SubscriptionCycleModel.ends_at > now,
                PaymentOrderModel.app_id == account.app_id,
                PaymentOrderModel.status == "paid",
                PaymentOrderModel.is_deleted == False,
            )
            .order_by(SubscriptionCycleModel.id)
        )
    ).all()
    for cycle in cycles:
        await supersede_pending_grants(db, account, new_cycle=cycle, now=now)
