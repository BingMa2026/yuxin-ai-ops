from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.module_billing.model import CreditGrantModel, CreditLedgerModel, SubscriptionCycleModel, SubscriptionModel
from app.api.v1.module_billing.service import CreditService
from app.api.v1.module_payment.order.model import PaymentOrderModel, PaymentRefundModel
from app.core.exceptions import CustomException

from .engine import BUSINESS_TZ, calculate_reward, utc
from .model import CashAccountModel, CashLedgerModel, GradeEvaluationModel, GrowthEventModel, GrowthPolicyModel, ReferralModel, RewardModel
from .referral_service import ReferralService
from .schema import IncentivePolicy, RewardAction, RightsPolicy
from .service import PolicyService, client_user, lock_app


async def cash_account(db: AsyncSession, app_id: int, user_id: int) -> CashAccountModel:
    await lock_app(db, app_id)
    account = await db.scalar(select(CashAccountModel).where(CashAccountModel.app_id == app_id, CashAccountModel.user_id == user_id).with_for_update())
    if not account:
        await client_user(db, app_id, user_id)
        account = CashAccountModel(app_id=app_id, user_id=user_id)
        db.add(account)
        await db.flush()
    return account


class RewardService:
    def __init__(self, db: AsyncSession, app_id: int):
        self.db, self.app_id = db, app_id

    async def emit(self, user_id: int, kind: str, key: str, facts: dict | None = None, *, occurred_at: datetime | None = None) -> GrowthEventModel:
        """Internal server event entry point; never expose arbitrary event ingestion."""
        await lock_app(self.db, self.app_id)
        existing = await self.db.scalar(select(GrowthEventModel).where(GrowthEventModel.app_id == self.app_id, GrowthEventModel.event_key == key))
        if existing:
            return existing
        at = utc(occurred_at or datetime.now(UTC))
        event = GrowthEventModel(app_id=self.app_id, user_id=user_id, kind=kind, event_key=key, facts=facts or {}, occurred_at=at)
        self.db.add(event)
        await self.db.flush()
        await self.match(event)
        return event

    async def grades_at(self, user_id: int, at: datetime):
        values = {"usage": "R1", "promotion": "ungraded"}
        rows = await self.db.scalars(
            select(GradeEvaluationModel)
            .where(GradeEvaluationModel.app_id == self.app_id, GradeEvaluationModel.user_id == user_id, GradeEvaluationModel.created_time <= at)
            .order_by(GradeEvaluationModel.created_time.desc(), GradeEvaluationModel.id.desc())
        )
        seen = set()
        for row in rows:
            if row.track not in seen:
                values[row.track] = row.new_grade
                seen.add(row.track)
        return SimpleNamespace(usage_grade=values["usage"], promotion_grade=values["promotion"])

    async def match(self, event: GrowthEventModel) -> None:
        from app.api.v1.module_client.app.model_policy import get_model_policy

        app_policy = await get_model_policy(self.db, self.app_id)
        policies = sorted(await PolicyService(self.db, self.app_id).active("incentive", at=event.occurred_at), key=lambda p: (int(p.config.get("priority", 100)), p.key))
        rights_rows = await PolicyService(self.db, self.app_id).active("rights", at=event.occurred_at)
        rights = RightsPolicy.model_validate(rights_rows[0].config) if rights_rows else None
        relation = await self.db.scalar(select(ReferralModel).where(ReferralModel.app_id == self.app_id, ReferralModel.invitee_id == event.user_id, ReferralModel.bound_at <= event.occurred_at))
        actor = await self.grades_at(event.user_id, event.occurred_at)
        base_matched = False
        any_matched = False
        reasons = []
        for row in policies:
            policy = IncentivePolicy.model_validate(row.config)
            if policy.event != event.kind or (base_matched and not policy.stackable):
                continue
            if policy.feedback_grade and policy.feedback_grade != event.facts.get("feedback_grade"):
                continue
            if policy.usage_grades and actor.usage_grade not in policy.usage_grades:
                continue
            if policy.promotion_grades and actor.promotion_grade not in policy.promotion_grades:
                continue
            if not rights:
                reasons.append("权益政策尚未生效")
                continue
            if policy.require_subscription and not await self.db.scalar(
                select(SubscriptionModel.id)
                .join(SubscriptionCycleModel, SubscriptionCycleModel.subscription_id == SubscriptionModel.id)
                .join(PaymentOrderModel, PaymentOrderModel.id == SubscriptionCycleModel.order_id)
                .where(
                    SubscriptionModel.app_id == self.app_id,
                    SubscriptionModel.user_id == event.user_id,
                    SubscriptionModel.status == "active",
                    SubscriptionCycleModel.starts_at <= event.occurred_at,
                    SubscriptionCycleModel.ends_at > event.occurred_at,
                    PaymentOrderModel.amount_fen > 0,
                    PaymentOrderModel.paid_at.is_not(None),
                )
                .limit(1)
            ):
                reasons.append("无有效月度套餐")
                continue
            outputs = []
            for action in policy.actions:
                user_id = event.user_id if action.recipient == "actor" else relation.inviter_id if relation else None
                if user_id is None or (action.recipient == "inviter" and relation.risk_status == "rejected"):
                    continue
                user = await client_user(self.db, self.app_id, user_id)
                from app.api.v1.module_client.app.model_policy import allowed_modes, current_mode
                if action.asset == "credits" and ("credits" not in allowed_modes(app_policy) or current_mode(app_policy, user) != "credits"):
                    continue
                if user.status != "active":
                    continue
                profile = await self.grades_at(user_id, event.occurred_at)
                amount = calculate_reward(action, net_paid_fen=int(event.facts.get("net_paid_fen", 0)), usage_grade=profile.usage_grade, promotion_grade=profile.promotion_grade)
                purpose = row.key if policy.stackable else "base"
                entitlement = f"{event.event_key}:{purpose}"
                duplicate = await self.db.scalar(
                    select(RewardModel.id).where(RewardModel.app_id == self.app_id, RewardModel.entitlement_key == entitlement, RewardModel.user_id == user_id, RewardModel.asset == action.asset)
                )
                if not amount or duplicate:
                    continue
                local = utc(event.occurred_at).astimezone(BUSINESS_TZ)
                day = local.replace(hour=0, minute=0, second=0, microsecond=0)
                month = day.replace(day=1)
                # Count distinct source events across versions, never reward-action rows.
                query = (
                    select(func.count(func.distinct(RewardModel.event_id)))
                    .join(GrowthPolicyModel, RewardModel.policy_id == GrowthPolicyModel.id)
                    .where(RewardModel.app_id == self.app_id, RewardModel.user_id == user_id, GrowthPolicyModel.key == row.key, RewardModel.status.not_in(["rejected", "reversed"]))
                )
                daily = int(await self.db.scalar(query.where(RewardModel.created_time >= day)) or 0)
                monthly = int(await self.db.scalar(query.where(RewardModel.created_time >= month)) or 0)
                if daily >= policy.daily_limit or monthly >= policy.monthly_limit:
                    reasons.append(f"{row.name}已达领取次数上限")
                    outputs = []
                    break
                outputs.append((action, user_id, profile, amount, entitlement))
            if policy.mode == "simulation":
                facts = dict(event.facts)
                facts["simulation_results"] = [
                    *facts.get("simulation_results", []),
                    {
                        "policy_id": row.id,
                        "name": row.name,
                        "version": row.version,
                        "rewards": [{"user_id": uid, "asset": action.asset, "amount": amount} for action, uid, profile, amount, entitlement in outputs],
                    },
                ]
                event.facts = facts
                reasons.append(f"{row.name}仅试运行，未占用预算或入账")
                continue
            credits = sum(x[3] for x in outputs if x[0].asset == "credits")
            cash = sum(x[3] for x in outputs if x[0].asset == "cash")
            totals = (
                await self.db.execute(
                    select(func.coalesce(func.sum(GrowthPolicyModel.used_credits), 0), func.coalesce(func.sum(GrowthPolicyModel.used_cash_fen), 0)).where(
                        GrowthPolicyModel.app_id == self.app_id, GrowthPolicyModel.key == row.key
                    )
                )
            ).one()
            if totals[0] + credits > policy.budget_credits or totals[1] + cash > policy.budget_cash_fen:
                reasons.append(f"{row.name}预算不足")
                continue
            if not outputs:
                continue
            row.used_credits += credits
            row.used_cash_fen += cash
            base_matched = base_matched or not policy.stackable
            any_matched = True
            for action, user_id, profile, amount, entitlement in outputs:
                reward = RewardModel(
                    app_id=self.app_id,
                    user_id=user_id,
                    event_id=event.id,
                    policy_id=row.id,
                    entitlement_key=entitlement,
                    asset=action.asset,
                    amount=amount,
                    status="review" if policy.mode == "review" or (relation and relation.risk_status != "passed") else "pending",
                    release_at=utc(event.occurred_at) + timedelta(days=policy.observe_days),
                    snapshot={
                        "referral_id": relation.id if relation else None,
                        "name": row.name,
                        "version": row.version,
                        "action": action.model_dump(mode="json"),
                        "usage_grade": profile.usage_grade,
                        "promotion_grade": profile.promotion_grade,
                        "rights": rights.model_dump(mode="json"),
                        "facts": event.facts,
                    },
                )
                self.db.add(reward)
        event.status = "matched" if any_matched else "simulated" if event.facts.get("simulation_results") else "skipped"
        event.reason = "；".join(reasons)[:500] if reasons else None if any_matched else "没有匹配的已发布奖励规则"
        await self.db.flush()

    async def review(self, reward_id: int, approved: bool, reason: str) -> RewardModel:
        await lock_app(self.db, self.app_id)
        reward = await self.db.scalar(select(RewardModel).where(RewardModel.id == reward_id, RewardModel.app_id == self.app_id).with_for_update())
        if not reward:
            raise CustomException(msg="奖励单不存在", status_code=404)
        if reward.status != "review":
            raise CustomException(msg="该奖励单已处理", status_code=409)
        if not approved:
            await self.release_budget(reward, reward.amount)
        reward.status, reward.reason = ("pending" if approved else "rejected"), reason
        await self.db.flush()
        return reward

    async def release_budget(self, reward: RewardModel, amount: int) -> None:
        policy = await self.db.get(GrowthPolicyModel, reward.policy_id)
        field = "used_credits" if reward.asset == "credits" else "used_cash_fen"
        setattr(policy, field, max(0, getattr(policy, field) - amount))

    async def post(self, reward: RewardModel) -> None:
        await lock_app(self.db, self.app_id)
        if reward.app_id != self.app_id:
            raise CustomException(msg="奖励所属客户端不匹配", status_code=404)
        await self.db.refresh(reward)
        if reward.status != "pending" or utc(reward.release_at) > datetime.now(UTC):
            return
        user = await client_user(self.db, self.app_id, reward.user_id)
        if user.status != "active":
            reward.status, reward.reason = "review", "账号已停用，需重新复核"
            return
        if reward.snapshot.get("referral_id"):
            relation = await self.db.scalar(select(ReferralModel).where(ReferralModel.app_id == self.app_id, ReferralModel.id == reward.snapshot["referral_id"]))
            if relation and relation.risk_status == "rejected":
                reward.status, reward.reason = "review", "邀请关系核验未通过，暂停到账并重新复核"
                return
        facts = reward.snapshot.get("facts", {})
        if facts.get("order_id"):
            order = await self.db.scalar(select(PaymentOrderModel).where(PaymentOrderModel.app_id == self.app_id, PaymentOrderModel.id == facts["order_id"]))
            if not order:
                reward.status, reward.reason = "review", "来源订单不存在，需人工核查"
                return
            refunded = int(
                await self.db.scalar(
                    select(func.coalesce(func.sum(PaymentRefundModel.amount_fen), 0)).where(
                        PaymentRefundModel.app_id == self.app_id, PaymentRefundModel.order_id == order.id, PaymentRefundModel.status == "succeeded"
                    )
                )
                or 0
            )
            net = max(0, order.amount_fen - refunded)
            revised = calculate_reward(
                RewardAction.model_validate(reward.snapshot["action"]), net_paid_fen=net, usage_grade=reward.snapshot["usage_grade"], promotion_grade=reward.snapshot["promotion_grade"]
            )
            revised = min(reward.amount, revised) if net else 0
            await self.release_budget(reward, reward.amount - revised)
            reward.amount = revised
        if not reward.amount:
            reward.status, reward.reason = "reversed", "原订单已退款，无可发奖励"
            return
        if reward.asset == "credits":
            account = await CreditService(self.db).account(self.app_id, reward.user_id, lock=True)
            now = datetime.now(UTC)
            rate = await CreditService(self.db).default_credits_per_cost_yuan(self.app_id, reward.user_id)
            grant = CreditGrantModel(
                app_id=self.app_id,
                user_id=reward.user_id,
                source_type="growth_reward",
                source_id=reward.id,
                account_type="activity_reward",
                amount=reward.amount,
                available=reward.amount,
                release_at=now,
                expires_at=now + timedelta(days=reward.snapshot["rights"]["credit_valid_days"]),
                status="released",
                credits_per_cost_yuan=rate,
                pricing_snapshot={"reward_id": reward.id, "policy_id": reward.policy_id},
            )
            self.db.add(grant)
            await self.db.flush()
            account.available += reward.amount
            account.total_granted += reward.amount
            self.db.add(
                CreditLedgerModel(
                    app_id=self.app_id,
                    user_id=reward.user_id,
                    grant_id=grant.id,
                    entry_type="growth_reward",
                    amount=reward.amount,
                    balance_after=account.available,
                    idempotency_key=f"growth:{reward.id}",
                    reference_type="growth_reward",
                    reference_id=str(reward.id),
                    reason=reward.snapshot["name"],
                )
            )
            profile = await ReferralService(self.db, self.app_id).profile(reward.user_id)
            offset = min(profile.credit_debt, reward.amount)
            if offset:
                profile.credit_debt -= offset
                grant.available -= offset
                account.available -= offset
                self.db.add(
                    CreditLedgerModel(
                        app_id=self.app_id,
                        user_id=reward.user_id,
                        grant_id=grant.id,
                        entry_type="growth_debt_offset",
                        amount=-offset,
                        balance_after=account.available,
                        idempotency_key=f"growth-debt:{reward.id}",
                        reference_type="growth_reward",
                        reference_id=str(reward.id),
                        reason="抵扣原受益人历史退款积分追偿",
                    )
                )
            from app.api.v1.module_billing.grant_messages import notify_credit_grant

            await notify_credit_grant(self.db, grant, reason=reward.snapshot["name"], offset=offset)
        else:
            account = await cash_account(self.db, self.app_id, reward.user_id)
            offset = min(account.debt, reward.amount)
            account.debt -= offset
            account.available += reward.amount - offset
            self.db.add(
                CashLedgerModel(
                    app_id=self.app_id,
                    user_id=reward.user_id,
                    entry_key=f"reward:{reward.id}",
                    entry_type="reward",
                    amount=reward.amount - offset,
                    debt_delta=-offset,
                    balance_after=account.available,
                    reference_id=reward.id,
                )
            )
        reward.status, reward.posted_at = "posted", datetime.now(UTC)
        await self.db.flush()

    async def paid_order(self, order: PaymentOrderModel) -> None:
        await lock_app(self.db, self.app_id)
        # Classify from the immutable purchased plan snapshot, not the current catalog.
        plan_type = order.plan_snapshot.get("plan_type") or order.plan_snapshot.get("type")
        kind = "first_traffic" if plan_type in {"credit_pack", "traffic", "traffic_pack"} else "first_subscription"
        paid_orders = (
            await self.db.scalars(
                select(PaymentOrderModel)
                .where(PaymentOrderModel.app_id == self.app_id, PaymentOrderModel.user_id == order.user_id, PaymentOrderModel.paid_at.is_not(None), PaymentOrderModel.amount_fen > 0)
                .order_by(PaymentOrderModel.paid_at, PaymentOrderModel.id)
            )
        ).all()
        same = [
            o
            for o in paid_orders
            if ("first_traffic" if (o.plan_snapshot.get("plan_type") or o.plan_snapshot.get("type")) in {"credit_pack", "traffic", "traffic_pack"} else "first_subscription") == kind
        ]
        if same and same[0].id == order.id:
            await self.emit(order.user_id, kind, f"{kind}:{order.user_id}", {"order_id": order.id, "net_paid_fen": order.amount_fen}, occurred_at=order.paid_at)
