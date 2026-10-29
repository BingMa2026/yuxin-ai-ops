from datetime import UTC, datetime

from sqlalchemy import or_, select

from app.api.v1.module_client.app.model import ClientAppModel
from app.core.database import async_db_session
from app.core.logger import logger

from .grade_service import GradeService
from .model import RewardModel, WithdrawalModel
from .payout_service import dispatch_payout
from .refund_service import reconcile_app_refunds
from .reward_service import RewardService
from .service import PolicyService, lock_app


async def run_growth_maintenance() -> None:
    async with async_db_session() as db:
        scopes = list(await db.scalars(select(ClientAppModel.id).where(ClientAppModel.is_deleted == False)))
    for scope in scopes:
        try:
            # Serialize on the application row across workers. Always reload rewards after locking.
            async with async_db_session() as db, db.begin():
                await lock_app(db, scope)
                await reconcile_app_refunds(db, scope)
                rewards = list(
                    await db.scalars(
                        select(RewardModel).where(RewardModel.app_id == scope, RewardModel.status == "pending", RewardModel.release_at <= datetime.now(UTC)).order_by(RewardModel.id).limit(100)
                    )
                )
                for reward in rewards:
                    await RewardService(db, scope).post(reward)
                payouts = list(
                    await db.scalars(
                        select(WithdrawalModel.id)
                        .where(
                            WithdrawalModel.app_id == scope,
                            WithdrawalModel.status.in_(["queued", "unknown", "processing", "confirming"]),
                            or_(WithdrawalModel.next_attempt_at.is_(None), WithdrawalModel.next_attempt_at <= datetime.now(UTC)),
                        )
                        .order_by(WithdrawalModel.id)
                        .limit(100)
                    )
                )
            for withdrawal_id in payouts:
                await dispatch_payout(scope, withdrawal_id)
            for track in ("usage", "promotion"):
                async with async_db_session() as db, db.begin():
                    rules = await PolicyService(db, scope).active(track)
                    rule_id = rules[0].id if rules else None
                if rule_id:
                    page = 1
                    while True:
                        async with async_db_session() as db, db.begin():
                            result = await GradeService(db, scope).preview(rule_id, page, 100, persist=True)
                        if not result["has_next"]:
                            break
                        page += 1
        except Exception:
            logger.exception("等级与奖励维护失败: app_id={}", scope)
