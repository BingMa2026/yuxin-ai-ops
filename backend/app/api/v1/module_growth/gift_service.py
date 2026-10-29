from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.module_billing.model import CreditGrantModel, CreditLedgerModel, CreditReservationModel, SubscriptionCycleModel, SubscriptionModel
from app.api.v1.module_billing.service import CreditService
from app.api.v1.module_payment.order.model import PaymentOrderModel, PaymentRefundModel
from app.core.exceptions import CustomException
from app.utils.password_util import PwdUtil

from .engine import BUSINESS_TZ, utc
from .model import GiftAllowanceModel, GiftModel
from .referral_service import ReferralService
from .schema import RightsPolicy, TransferIn
from .service import PolicyService, client_user, lock_app


class GiftService:
    def __init__(self, db: AsyncSession, app_id: int):
        self.db, self.app_id = db, app_id

    async def rights(self):
        rows = await PolicyService(self.db, self.app_id).active("rights")
        if not rows:
            raise CustomException(msg="权益政策尚未发布", status_code=409)
        return rows[0], RightsPolicy.model_validate(rows[0].config)

    def eligible_sources(self, policy: RightsPolicy):
        refunded = select(PaymentRefundModel.order_id).where(PaymentRefundModel.app_id == self.app_id, PaymentRefundModel.status == "succeeded")
        paid = select(PaymentOrderModel.id).where(
            PaymentOrderModel.app_id == self.app_id,
            PaymentOrderModel.amount_fen > 0,
            PaymentOrderModel.paid_at.is_not(None),
            PaymentOrderModel.id.not_in(refunded),
        )
        cycles = select(SubscriptionCycleModel.id).where(SubscriptionCycleModel.app_id == self.app_id, SubscriptionCycleModel.order_id.in_(paid))
        return or_(
            and_(CreditGrantModel.source_type == "credit_pack_order", CreditGrantModel.source_id.in_(paid)),
            and_(CreditGrantModel.source_type == "subscription_cycle", CreditGrantModel.source_id.in_(cycles)),
            and_(CreditGrantModel.source_type == "growth_reward", policy.gift_reward_credits),
        )

    async def allowance(self, user_id: int, policy: RightsPolicy) -> GiftAllowanceModel:
        now = datetime.now(UTC).astimezone(BUSINESS_TZ)
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        key = start.strftime("%Y-%m")
        row = await self.db.scalar(select(GiftAllowanceModel).where(GiftAllowanceModel.app_id == self.app_id, GiftAllowanceModel.user_id == user_id, GiftAllowanceModel.month == key))
        # Reconstruct the month boundary from immutable ledger entries and reservations.
        # A first visit mid-month must not treat newly purchased credits as opening balance.
        grants = list(
            await self.db.scalars(
                select(CreditGrantModel).where(
                    CreditGrantModel.app_id == self.app_id,
                    CreditGrantModel.user_id == user_id,
                    self.eligible_sources(policy),
                    CreditGrantModel.release_at < start,
                    CreditGrantModel.created_time < start,
                    CreditGrantModel.expires_at > start,
                )
            )
        )
        ledger = dict(
            (
                await self.db.execute(
                    select(CreditLedgerModel.grant_id, func.sum(CreditLedgerModel.amount))
                    .where(CreditLedgerModel.app_id == self.app_id, CreditLedgerModel.user_id == user_id, CreditLedgerModel.created_time < start)
                    .group_by(CreditLedgerModel.grant_id)
                )
            ).all()
        )
        reservations = list(
            await self.db.scalars(
                select(CreditReservationModel).where(CreditReservationModel.app_id == self.app_id, CreditReservationModel.user_id == user_id, CreditReservationModel.created_time < start)
            )
        )
        held: dict[int, int] = {}
        for reservation in reservations:
            if reservation.settled_at is None or utc(reservation.settled_at) >= start:
                for allocation in reservation.allocations:
                    gid = allocation["grant_id"]
                    held[gid] = held.get(gid, 0) + int(allocation["amount"])
        baseline = sum(max(0, int(ledger.get(g.id, 0)) - held.get(g.id, 0)) for g in grants)
        if row:
            row.baseline = baseline
        else:
            row = GiftAllowanceModel(app_id=self.app_id, user_id=user_id, month=key, baseline=baseline, used=0)
            self.db.add(row)
        await self.db.flush()
        return row

    async def summary(self, user_id: int) -> dict:
        await lock_app(self.db, self.app_id)
        rows = await PolicyService(self.db, self.app_id).active("rights")
        if not rows:
            return {"enabled": False, "reason": "转赠尚未开放"}
        policy = RightsPolicy.model_validate(rows[0].config)
        allowance = await self.allowance(user_id, policy)
        available = int(
            await self.db.scalar(
                select(func.coalesce(func.sum(CreditGrantModel.available), 0)).where(
                    CreditGrantModel.app_id == self.app_id,
                    CreditGrantModel.user_id == user_id,
                    self.eligible_sources(policy),
                    CreditGrantModel.status == "released",
                    CreditGrantModel.expires_at > datetime.now(UTC),
                )
            )
            or 0
        )
        remaining = max(0, allowance.baseline * policy.gift_monthly_percent // 100 - allowance.used)
        return {
            "enabled": policy.gift_enabled,
            "minimum": policy.gift_minimum,
            "daily_count": policy.gift_daily_count,
            "requires_subscription": policy.gift_requires_subscription,
            "monthly_remaining": remaining,
            "giftable": min(remaining, available),
            "month": allowance.month,
        }

    async def transfer(self, user_id: int, data: TransferIn) -> GiftModel:
        from app.api.v1.module_client.app.model_policy import require_platform_model

        await lock_app(self.db, self.app_id)
        await require_platform_model(self.db, self.app_id, user_id=user_id)
        sender = await client_user(self.db, self.app_id, user_id)
        if sender.status != "active" or not PwdUtil.verify_password(data.password, sender.password_hash):
            raise CustomException(msg="密码不正确", status_code=403)
        prior = await self.db.scalar(select(GiftModel).where(GiftModel.app_id == self.app_id, GiftModel.sender_id == user_id, GiftModel.idempotency_key == data.idempotency_key))
        recipient = await ReferralService(self.db, self.app_id).resolve(data.recipient_code)
        if prior:
            if prior.amount != data.amount or prior.recipient_id != recipient.user_id:
                raise CustomException(msg="请求标识已用于其他转赠", status_code=409)
            return prior
        await require_platform_model(self.db, self.app_id, user_id=recipient.user_id)
        receiver = await client_user(self.db, self.app_id, recipient.user_id)
        profile = await ReferralService(self.db, self.app_id).profile(user_id)
        if receiver.status != "active" or profile.credit_debt:
            raise CustomException(msg="接收方账号不可用或转赠方存在退款积分追偿", status_code=409)
        rule, policy = await self.rights()
        if not policy.gift_enabled:
            raise CustomException(msg="转赠尚未开放", status_code=409)
        if recipient.user_id == user_id:
            raise CustomException(msg="不能转赠给自己", status_code=422)
        if data.amount < policy.gift_minimum:
            raise CustomException(msg=f"单次至少转赠{policy.gift_minimum}积分", status_code=422)
        now = datetime.now(UTC)
        if policy.gift_requires_subscription and not await self.db.scalar(
            select(SubscriptionModel.id)
            .where(SubscriptionModel.app_id == self.app_id, SubscriptionModel.user_id == recipient.user_id, SubscriptionModel.status == "active", SubscriptionModel.current_period_end > now)
            .limit(1)
        ):
            raise CustomException(msg="接收方需要有效订阅", status_code=409)
        day = now.astimezone(BUSINESS_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
        count = int(await self.db.scalar(select(func.count()).select_from(GiftModel).where(GiftModel.app_id == self.app_id, GiftModel.sender_id == user_id, GiftModel.created_time >= day)) or 0)
        allowance = await self.allowance(user_id, policy)
        if count >= policy.gift_daily_count or allowance.used + data.amount > allowance.baseline * policy.gift_monthly_percent // 100:
            raise CustomException(msg="超出每日次数或本月转赠额度", status_code=409)
        billing = CreditService(self.db)
        accounts = {uid: await billing.account(self.app_id, uid, lock=True) for uid in sorted([user_id, recipient.user_id])}
        if any(a.status != "active" for a in accounts.values()):
            raise CustomException(msg="积分账户不可用", status_code=409)
        grants = list(
            await self.db.scalars(
                select(CreditGrantModel)
                .where(
                    CreditGrantModel.app_id == self.app_id,
                    CreditGrantModel.user_id == user_id,
                    self.eligible_sources(policy),
                    CreditGrantModel.status == "released",
                    CreditGrantModel.available > 0,
                    CreditGrantModel.expires_at > now,
                )
                .order_by(CreditGrantModel.expires_at, CreditGrantModel.id)
                .with_for_update()
            )
        )
        if min(accounts[user_id].available, sum(g.available for g in grants)) < data.amount:
            raise CustomException(msg="可转赠积分不足，预占、过期和受赠积分不可转赠", status_code=409)
        gift = GiftModel(app_id=self.app_id, sender_id=user_id, recipient_id=recipient.user_id, policy_id=rule.id, idempotency_key=data.idempotency_key, amount=data.amount, allocations=[])
        self.db.add(gift)
        await self.db.flush()
        remaining, allocations = data.amount, []
        for source in grants:
            amount = min(remaining, source.available)
            if not amount:
                break
            source.available -= amount
            accounts[user_id].available -= amount
            received = CreditGrantModel(
                app_id=self.app_id,
                user_id=recipient.user_id,
                source_type="growth_gift",
                source_id=gift.id,
                release_index=len(allocations),
                account_type=source.account_type,
                amount=amount,
                available=amount,
                status="released",
                release_at=now,
                expires_at=source.expires_at,
                credits_per_cost_yuan=source.credits_per_cost_yuan,
                pricing_snapshot={"source_grant_id": source.id, "source_pricing": source.pricing_snapshot},
            )
            self.db.add(received)
            await self.db.flush()
            accounts[recipient.user_id].available += amount
            accounts[recipient.user_id].total_granted += amount
            for uid, gid, sign, entry in [(user_id, source.id, -1, "gift_sent"), (recipient.user_id, received.id, 1, "gift_received")]:
                self.db.add(
                    CreditLedgerModel(
                        app_id=self.app_id,
                        user_id=uid,
                        grant_id=gid,
                        entry_type=entry,
                        amount=amount * sign,
                        balance_after=accounts[uid].available,
                        idempotency_key=f"gift:{gift.id}:{gid}:{entry}",
                        reference_type="growth_gift",
                        reference_id=str(gift.id),
                        reason="用户积分转赠",
                    )
                )
            allocations.append({"source_grant_id": source.id, "recipient_grant_id": received.id, "amount": amount})
            remaining -= amount
        gift.allocations = allocations
        allowance.used += data.amount
        await self.db.flush()
        return gift
