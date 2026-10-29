from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.module_client.user.model import ClientUserModel
from app.api.v1.module_payment.order.model import PaymentOrderModel, PaymentRefundModel
from app.core.exceptions import CustomException

from .engine import BUSINESS_TZ, evaluate, period_key, utc
from .model import GradeEvaluationModel, GrowthEventModel, GrowthProfileModel, GrowthTaskModel, ReferralModel
from .referral_service import ReferralService
from .schema import GradePolicy
from .service import PolicyService, lock_app


class GradeService:
    def __init__(self, db: AsyncSession, app_id: int):
        self.db, self.app_id = db, app_id

    async def metrics(self, user_id: int, policy: GradePolicy, at: datetime) -> dict:
        since = utc(at) - timedelta(days=policy.window_days)
        if policy.track == "usage":
            orders = (
                await self.db.scalars(
                    select(PaymentOrderModel).where(
                        PaymentOrderModel.app_id == self.app_id,
                        PaymentOrderModel.user_id == user_id,
                        PaymentOrderModel.paid_at >= since,
                        PaymentOrderModel.paid_at < at,
                        PaymentOrderModel.is_deleted == False,
                    )
                )
            ).all()
            refunds = (
                await self.db.execute(
                    select(PaymentRefundModel.order_id, func.sum(PaymentRefundModel.amount_fen))
                    .where(PaymentRefundModel.app_id == self.app_id, PaymentRefundModel.status == "succeeded", PaymentRefundModel.refunded_at < at)
                    .group_by(PaymentRefundModel.order_id)
                )
            ).all()
            refunded = dict(refunds)
            tasks = (
                await self.db.scalars(
                    select(GrowthTaskModel).where(
                        GrowthTaskModel.app_id == self.app_id,
                        GrowthTaskModel.user_id == user_id,
                        GrowthTaskModel.status == "verified",
                        GrowthTaskModel.verified_at >= since,
                        GrowthTaskModel.verified_at < at,
                    )
                )
            ).all()
            feedback = int(
                await self.db.scalar(
                    select(func.count())
                    .select_from(GrowthEventModel)
                    .where(
                        GrowthEventModel.app_id == self.app_id,
                        GrowthEventModel.user_id == user_id,
                        GrowthEventModel.kind == "feedback",
                        GrowthEventModel.occurred_at >= since,
                        GrowthEventModel.occurred_at < at,
                    )
                )
                or 0
            )
            return {
                "net_paid_fen": sum(max(0, o.amount_fen - int(refunded.get(o.id, 0))) for o in orders),
                "active_days": len({utc(t.verified_at).astimezone(BUSINESS_TZ).date() for t in tasks}),
                "artifacts": len({(t.project_ref, t.artifact_ref) for t in tasks if t.artifact_ref}),
                "feedback": feedback,
            }

        relations = (await self.db.scalars(select(ReferralModel).where(ReferralModel.app_id == self.app_id, ReferralModel.inviter_id == user_id, ReferralModel.bound_at < at))).all()
        cohort = [r for r in relations if utc(r.bound_at) >= since]
        checked = [r for r in cohort if r.risk_status in {"passed", "rejected"}]
        valid = [r for r in cohort if r.risk_status == "passed"]
        valid_ids = [r.invitee_id for r in valid]
        starts = {r.invitee_id: utc(r.bound_at) for r in relations}
        profiles = (await self.db.scalars(select(GrowthProfileModel).where(GrowthProfileModel.app_id == self.app_id, GrowthProfileModel.user_id.in_(valid_ids)))).all() if valid_ids else []
        first_users = sum(1 for p in profiles if p.first_task_at and starts[p.user_id] <= utc(p.first_task_at) < at)
        all_ids = [r.invitee_id for r in relations]
        orders = (
            (
                await self.db.scalars(
                    select(PaymentOrderModel).where(
                        PaymentOrderModel.app_id == self.app_id, PaymentOrderModel.user_id.in_(all_ids), PaymentOrderModel.paid_at.is_not(None), PaymentOrderModel.paid_at < at
                    )
                )
            ).all()
            if all_ids
            else []
        )
        orders = [o for o in orders if utc(o.paid_at) >= starts[o.user_id]]
        refunds = dict(
            (
                await self.db.execute(
                    select(PaymentRefundModel.order_id, func.sum(PaymentRefundModel.amount_fen))
                    .where(PaymentRefundModel.app_id == self.app_id, PaymentRefundModel.status == "succeeded", PaymentRefundModel.refunded_at < at)
                    .group_by(PaymentRefundModel.order_id)
                )
            ).all()
        )
        payers = {o.user_id for o in orders if o.user_id in valid_ids and int(refunds.get(o.id, 0)) < o.amount_fen}
        observed_orders = [o for o in orders if since <= utc(o.paid_at) + timedelta(days=7) < at]
        users = (
            (
                await self.db.scalars(
                    select(ClientUserModel).where(
                        ClientUserModel.app_id == self.app_id,
                        ClientUserModel.id.in_([r.invitee_id for r in relations if r.risk_status == "passed"]),
                        ClientUserModel.registered_at < at - timedelta(days=30),
                    )
                )
            ).all()
            if all_ids
            else []
        )
        # Cohort maturity is calculated in Python for identical PostgreSQL/SQLite semantics.
        mature = [u for u in users if since <= utc(u.registered_at) + timedelta(days=30) < at]
        retained = 0
        for user in mature:
            hit = await self.db.scalar(
                select(GrowthTaskModel.id)
                .where(
                    GrowthTaskModel.app_id == self.app_id,
                    GrowthTaskModel.user_id == user.id,
                    GrowthTaskModel.status == "verified",
                    GrowthTaskModel.verified_at >= utc(user.registered_at) + timedelta(days=24),
                    GrowthTaskModel.verified_at < min(at, utc(user.registered_at) + timedelta(days=31)),
                )
                .limit(1)
            )
            retained += bool(hit)
        coverage = len(checked) * 100 / len(cohort) if cohort else 0
        return {
            "registrations": len(valid),
            "first_users": first_users,
            "first_payers": len(payers),
            "conversion_rate": round(len(payers) * 100 / len(valid), 2) if valid else None,
            "retention_rate": round(retained * 100 / len(mature), 2) if len(mature) >= policy.retention_min_samples else None,
            "retention_samples": len(mature),
            "compliance_rate": round(len(valid) * 100 / len(checked), 2) if checked and coverage >= policy.compliance_min_coverage else None,
            "compliance_coverage": round(coverage, 2),
            "refund_rate": round(sum(int(refunds.get(o.id, 0)) > 0 for o in observed_orders) * 100 / len(observed_orders), 2) if observed_orders else None,
        }

    async def preview(self, rule_id: int, page_no: int = 1, page_size: int = 20, *, persist: bool = False) -> dict:
        row = await PolicyService(self.db, self.app_id).get(rule_id)
        if row.kind not in {"usage", "promotion"}:
            raise CustomException(msg="当前规则不属于等级体系", status_code=422)
        policy = GradePolicy.model_validate(row.config)
        if persist and (row.status != "published" or utc(row.effective_at) > datetime.now(UTC)):
            raise CustomException(msg="只有已生效的发布版本可以正式评估", status_code=409)
        if persist:
            await lock_app(self.db, self.app_id)
            active = await PolicyService(self.db, self.app_id).active(row.kind)
            if not active or active[0].id != row.id:
                raise CustomException(msg="该版本已被替代或停用，请使用当前生效版本", status_code=409)
        at = datetime.now(UTC)
        stmt = select(ClientUserModel).where(ClientUserModel.app_id == self.app_id, ClientUserModel.is_deleted == False)
        total = int(await self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
        users = (await self.db.scalars(stmt.order_by(ClientUserModel.id).offset((page_no - 1) * page_size).limit(page_size))).all()
        items = []
        for user in users:
            if persist:
                existing = await self.db.scalar(
                    select(GradeEvaluationModel).where(
                        GradeEvaluationModel.app_id == self.app_id,
                        GradeEvaluationModel.user_id == user.id,
                        GradeEvaluationModel.track == policy.track,
                        GradeEvaluationModel.policy_id == row.id,
                        GradeEvaluationModel.period_key == period_key(policy, at),
                    )
                )
                if existing:
                    items.append(existing.result)
                    continue
            profile = await ReferralService(self.db, self.app_id).profile(user.id)
            result = evaluate(policy, await self.metrics(user.id, policy, at))
            old = profile.usage_grade if policy.track == "usage" else profile.promotion_grade
            candidate = result["grade"]
            previous = (profile.evaluations or {}).get(policy.track, {})

            def rank(code: str) -> int:
                return 0 if code == "ungraded" else int(code[-1])

            failure_count = int(previous.get("failure_count", 0)) if previous.get("policy_id") == row.id else 0
            if result["insufficient"] and rank(candidate) < rank(old):
                candidate = old
                result["reason"] = "数据不足，保留当前等级"
            elif rank(candidate) < rank(old):
                failure_count += 1
                if failure_count < policy.downgrade_periods:
                    candidate = old
                    result["reason"] = "仍处于降级缓冲期"
            else:
                failure_count = 0
            result.update(
                {
                    "user_id": user.id,
                    "name": user.display_name or user.username,
                    "old_grade": old,
                    "new_grade": candidate,
                    "failure_count": failure_count,
                    "policy_id": row.id,
                    "window_days": policy.window_days,
                    "evaluated_at": at.isoformat(),
                    "period_key": period_key(policy, at),
                }
            )
            if persist:
                exists = await self.db.scalar(
                    select(GradeEvaluationModel.id).where(
                        GradeEvaluationModel.app_id == self.app_id,
                        GradeEvaluationModel.user_id == user.id,
                        GradeEvaluationModel.track == policy.track,
                        GradeEvaluationModel.policy_id == row.id,
                        GradeEvaluationModel.period_key == result["period_key"],
                    )
                )
                if not exists:
                    self.db.add(
                        GradeEvaluationModel(
                            app_id=self.app_id, user_id=user.id, policy_id=row.id, track=policy.track, period_key=result["period_key"], old_grade=old, new_grade=candidate, result=result
                        )
                    )
                    profile.evaluations = {**(profile.evaluations or {}), policy.track: result}
                    if policy.track == "usage":
                        profile.usage_grade = candidate
                    else:
                        profile.promotion_grade = candidate
            items.append(result)
        await self.db.flush()
        return {"page_no": page_no, "page_size": page_size, "total": total, "has_next": page_no * page_size < total, "items": items}
