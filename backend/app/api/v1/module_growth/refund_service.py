from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.module_billing.model import CreditGrantModel, CreditLedgerModel
from app.api.v1.module_billing.service import CreditService
from app.api.v1.module_payment.order.model import PaymentOrderModel, PaymentRefundModel

from .engine import calculate_reward
from .model import CashLedgerModel, GrowthEventModel, RewardModel
from .referral_service import ReferralService
from .reward_service import RewardService, cash_account
from .schema import RewardAction
from .service import lock_app


async def reconcile_order_rewards(db: AsyncSession, app_id: int, order_id: int) -> None:
    await lock_app(db, app_id)
    order = await db.scalar(select(PaymentOrderModel).where(PaymentOrderModel.app_id == app_id, PaymentOrderModel.id == order_id))
    if not order:
        return
    refunded = int(
        await db.scalar(
            select(func.coalesce(func.sum(PaymentRefundModel.amount_fen), 0)).where(
                PaymentRefundModel.app_id == app_id, PaymentRefundModel.order_id == order_id, PaymentRefundModel.status == "succeeded"
            )
        )
        or 0
    )
    if not refunded:
        return
    rewards = list(
        await db.scalars(
            select(RewardModel)
            .join(GrowthEventModel, RewardModel.event_id == GrowthEventModel.id)
            .where(RewardModel.app_id == app_id, GrowthEventModel.facts["order_id"].as_integer() == order_id, RewardModel.status.in_(["review", "pending", "posted"]))
        )
    )
    for reward in rewards:
        net = max(0, order.amount_fen - refunded)
        target = (
            min(
                reward.amount,
                calculate_reward(
                    RewardAction.model_validate(reward.snapshot["action"]), net_paid_fen=net, usage_grade=reward.snapshot["usage_grade"], promotion_grade=reward.snapshot["promotion_grade"]
                ),
            )
            if net
            else 0
        )
        delta = reward.amount - target - reward.reversed_amount
        if delta <= 0:
            continue
        if reward.status in {"review", "pending"}:
            await RewardService(db, app_id).release_budget(reward, delta)
            reward.amount = target
            if not target:
                reward.status, reward.reason = "reversed", "原订单退款，已撤销待发奖励"
            continue
        if reward.asset == "cash":
            account = await cash_account(db, app_id, reward.user_id)
            recovered = min(account.available, delta)
            account.available -= recovered
            account.debt += delta - recovered
            db.add(
                CashLedgerModel(
                    app_id=app_id,
                    user_id=reward.user_id,
                    entry_key=f"refund:{reward.id}:{refunded}",
                    entry_type="reward_refund",
                    amount=-recovered,
                    balance_after=account.available,
                    debt_delta=delta - recovered,
                    reference_id=reward.id,
                )
            )
        else:
            account = await CreditService(db).account(app_id, reward.user_id, lock=True)
            grant = await db.scalar(
                select(CreditGrantModel)
                .where(CreditGrantModel.app_id == app_id, CreditGrantModel.user_id == reward.user_id, CreditGrantModel.source_type == "growth_reward", CreditGrantModel.source_id == reward.id)
                .with_for_update()
            )
            recovered = min(account.available, grant.available if grant else 0, delta)
            if grant:
                grant.available -= recovered
            account.available -= recovered
            profile = await ReferralService(db, app_id).profile(reward.user_id)
            profile.credit_debt += delta - recovered
            db.add(
                CreditLedgerModel(
                    app_id=app_id,
                    user_id=reward.user_id,
                    grant_id=grant.id if grant else None,
                    entry_type="growth_refund",
                    amount=-recovered,
                    balance_after=account.available,
                    idempotency_key=f"growth-refund:{reward.id}:{refunded}",
                    reference_type="growth_reward",
                    reference_id=str(reward.id),
                    reason=f"退款冲正；待追偿积分{delta - recovered}",
                )
            )
        await RewardService(db, app_id).release_budget(reward, delta)
        reward.reversed_amount += delta
        reward.reason = "原订单退款，奖励已冲正；不足部分保留原受益人追偿记录"
        if reward.reversed_amount == reward.amount:
            reward.status = "reversed"
    await db.flush()


async def reconcile_app_refunds(db: AsyncSession, app_id: int) -> None:
    # Replaying this scan is safe: the cumulative reversed amount is persisted per reward.
    ids = list(await db.scalars(select(PaymentRefundModel.order_id).where(PaymentRefundModel.app_id == app_id, PaymentRefundModel.status == "succeeded").distinct()))
    for order_id in ids:
        await reconcile_order_rewards(db, app_id, order_id)
