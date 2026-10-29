import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.module_client.app.model import ClientAppModel
from app.api.v1.module_payment.order.model import PaymentOrderModel
from app.config.setting import settings
from app.core.exceptions import CustomException

from .engine import utc
from .model import GrowthPolicyModel, GrowthProfileModel, ReferralModel, RewardModel
from .service import PolicyService, client_user, lock_app


def parse_invite(value: str) -> str:
    value = value.strip()
    if "://" in value:
        parsed = urlsplit(value)
        base = urlsplit(settings.GROWTH_INVITE_BASE_URL)
        if parsed.scheme not in {"http", "https"} or parsed.netloc != base.netloc or parsed.username or parsed.password or not parsed.path.startswith("/invite/"):
            raise CustomException(msg="请填写邀请码或官方邀请链接", status_code=422)
        value = parsed.path.removeprefix("/invite/").strip("/")
    value = value.upper()
    if not 8 <= len(value) <= 24 or not value.isascii() or not value.isalnum():
        raise CustomException(msg="邀请码格式不正确", status_code=422)
    return value


class ReferralService:
    def __init__(self, db: AsyncSession, app_id: int):
        self.db, self.app_id = db, app_id

    async def profile(self, user_id: int) -> GrowthProfileModel:
        row = await self.db.scalar(select(GrowthProfileModel).where(GrowthProfileModel.app_id == self.app_id, GrowthProfileModel.user_id == user_id))
        if row:
            return row
        await lock_app(self.db, self.app_id)
        await client_user(self.db, self.app_id, user_id)
        row = await self.db.scalar(select(GrowthProfileModel).where(GrowthProfileModel.app_id == self.app_id, GrowthProfileModel.user_id == user_id))
        if not row:
            while True:
                code = secrets.token_hex(6).upper()
                if not await self.db.scalar(select(GrowthProfileModel.id).where(GrowthProfileModel.invite_code == code)):
                    break
            row = GrowthProfileModel(app_id=self.app_id, user_id=user_id, invite_code=code)
            self.db.add(row)
            await self.db.flush()
        return row

    async def resolve(self, code: str) -> GrowthProfileModel:
        profile = await self.db.scalar(select(GrowthProfileModel).where(GrowthProfileModel.app_id == self.app_id, GrowthProfileModel.invite_code == parse_invite(code)))
        if not profile:
            raise CustomException(msg="邀请码不存在或不属于当前客户端", status_code=404)
        user = await client_user(self.db, self.app_id, profile.user_id)
        if user.status != "active":
            raise CustomException(msg="该邀请链接暂不可用", status_code=409)
        return profile

    async def eligibility(self, user_id: int) -> dict:
        user = await client_user(self.db, self.app_id, user_id)
        profile = await self.profile(user_id)
        relation = await self.db.scalar(select(ReferralModel).where(ReferralModel.app_id == self.app_id, ReferralModel.invitee_id == user_id))
        paid = await self.db.scalar(
            select(PaymentOrderModel.id)
            .where(PaymentOrderModel.app_id == self.app_id, PaymentOrderModel.user_id == user_id, PaymentOrderModel.paid_at.is_not(None), PaymentOrderModel.amount_fen > 0)
            .limit(1)
        )
        expires = utc(user.registered_at) + timedelta(hours=72)
        reason = "已绑定邀请人" if relation else "已完成首个有效任务" if profile.first_task_at else "已有成功支付记录" if paid else "已超过注册后72小时" if datetime.now(UTC) >= expires else None
        return {
            "eligible": reason is None,
            "reason": reason,
            "expires_at": expires,
            "inviter_id": relation.inviter_id if relation else None,
            "bound_at": relation.bound_at if relation else None,
            "source": relation.source if relation else None,
        }

    async def bind(self, user_id: int, code: str, *, source: str = "profile") -> dict:
        await lock_app(self.db, self.app_id)
        user = await client_user(self.db, self.app_id, user_id, lock=True)
        allowed = await self.eligibility(user_id)
        if not allowed["eligible"]:
            raise CustomException(msg=allowed["reason"], status_code=409)
        inviter = await self.resolve(code)
        if inviter.user_id == user_id:
            raise CustomException(msg="不能绑定自己的邀请码", status_code=422)
        cursor, visited = inviter.user_id, {user_id}
        while cursor:
            if cursor in visited:
                raise CustomException(msg="该绑定会形成循环邀请", status_code=409)
            visited.add(cursor)
            cursor = await self.db.scalar(select(ReferralModel.inviter_id).where(ReferralModel.app_id == self.app_id, ReferralModel.invitee_id == cursor))
        self.db.add(ReferralModel(app_id=self.app_id, inviter_id=inviter.user_id, invitee_id=user_id, source=source, bound_at=datetime.now(UTC), risk_status="pending"))
        if source == "registration":
            user.registration_source = "referral"
        await self.db.flush()
        return await self.eligibility(user_id)

    async def summary(self, user_id: int) -> dict:
        profile = await self.profile(user_id)
        relation_count = int(await self.db.scalar(select(func.count()).select_from(ReferralModel).where(ReferralModel.app_id == self.app_id, ReferralModel.inviter_id == user_id)) or 0)
        reward_totals = (
            await self.db.execute(
                select(RewardModel.asset, func.sum(RewardModel.amount - RewardModel.reversed_amount))
                .where(RewardModel.app_id == self.app_id, RewardModel.user_id == user_id, RewardModel.status == "posted", RewardModel.snapshot["action"]["recipient"].as_string() == "inviter")
                .group_by(RewardModel.asset)
            )
        ).all()
        return {
            "invite_code": profile.invite_code,
            "invite_url": f"{settings.GROWTH_INVITE_BASE_URL.rstrip('/')}/invite/{profile.invite_code}",
            "usage_grade": profile.usage_grade,
            "promotion_grade": profile.promotion_grade,
            "evaluations": profile.evaluations,
            "invited_count": relation_count,
            "reward_totals": dict(reward_totals),
            "binding": await self.eligibility(user_id),
        }

    async def records(self, user_id: int, page_no: int, page_size: int, *, admin: bool = False) -> dict:
        stmt = select(ReferralModel).where(ReferralModel.app_id == self.app_id, ReferralModel.inviter_id == user_id)
        total = int(await self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
        rows = (await self.db.scalars(stmt.order_by(ReferralModel.id.desc()).offset((page_no - 1) * page_size).limit(page_size))).all()
        items = []
        for row in rows:
            user = await client_user(self.db, self.app_id, row.invitee_id)
            profile = await self.profile(user.id)
            first_paid = await self.db.scalar(
                select(func.min(PaymentOrderModel.paid_at)).where(
                    PaymentOrderModel.app_id == self.app_id, PaymentOrderModel.user_id == user.id, PaymentOrderModel.paid_at >= row.bound_at, PaymentOrderModel.amount_fen > 0
                )
            )
            name = user.display_name or user.username
            items.append(
                {
                    "id": row.id,
                    "user_id": user.id if admin else None,
                    "name": name if admin else name[:1] + "***",
                    "registered_at": utc(user.registered_at),
                    "bound_at": utc(row.bound_at),
                    "source": row.source,
                    "first_task_at": utc(profile.first_task_at) if profile.first_task_at else None,
                    "first_paid_at": utc(first_paid) if first_paid else None,
                    "risk_status": row.risk_status,
                }
            )
        return {"page_no": page_no, "page_size": page_size, "total": total, "has_next": page_no * page_size < total, "items": items}


async def public_invitation(db: AsyncSession, code: str) -> dict:
    profile = await db.scalar(select(GrowthProfileModel).where(GrowthProfileModel.invite_code == parse_invite(code)))
    if not profile:
        raise CustomException(msg="邀请链接不存在", status_code=404)
    app = await db.scalar(select(ClientAppModel).where(ClientAppModel.id == profile.app_id, ClientAppModel.status == "active", ClientAppModel.is_deleted == False))
    if not app or not app.registration_enabled:
        raise CustomException(msg="该客户端暂未开放注册", status_code=409)
    user = await client_user(db, app.id, profile.user_id)
    if user.status != "active":
        raise CustomException(msg="该邀请链接暂不可用", status_code=409)
    policies = await PolicyService(db, app.id).active("incentive")
    from .offers import offer_summary
    from .schema import IncentivePolicy

    rewards = []
    if await PolicyService(db, app.id).active("rights"):
        for row in policies:
            policy = IncentivePolicy.model_validate(row.config)
            if policy.event not in {"first_task", "first_subscription", "first_traffic"} or policy.mode == "simulation":
                continue
            used_credits, used_cash = (
                await db.execute(
                    select(func.coalesce(func.sum(GrowthPolicyModel.used_credits), 0), func.coalesce(func.sum(GrowthPolicyModel.used_cash_fen), 0)).where(
                        GrowthPolicyModel.app_id == app.id, GrowthPolicyModel.key == row.key
                    )
                )
            ).one()
            if any(a.asset == "credits" for a in policy.actions) and used_credits >= policy.budget_credits:
                continue
            if any(a.asset == "cash" for a in policy.actions) and used_cash >= policy.budget_cash_fen:
                continue
            rewards.append(
                {
                    "id": row.id,
                    "name": row.name,
                    "summary": offer_summary(policy, profile.usage_grade, profile.promotion_grade),
                    "config": {k: v for k, v in row.config.items() if k not in {"budget_credits", "budget_cash_fen"}},
                }
            )
    return {"code": profile.invite_code, "app_code": app.code, "inviter_name": (user.display_name or user.username)[:1] + "***", "rewards": rewards}
