"""Audited duration changes use real entitlement periods, never fake payments."""

import hashlib
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.module_client.app.model_policy import allowed_modes, current_mode, get_model_policy
from app.api.v1.module_client.user.model import ClientUserModel
from app.core.base_schema import AuthSchema
from app.core.exceptions import CustomException

from .duration import utc
from .duration_schema import DurationAdjustmentOut, DurationAdjustSchema, DurationPlanOption, DurationStateOut
from .model import AppCatalogPlanModel, DurationAdjustmentModel, SubscriptionCycleModel, SubscriptionModel
from .service import CreditService
from .subscription_periods import apply_subscription_projection, project_subscription


class DurationAdjustmentService:
    def __init__(self, db: AsyncSession, auth: AuthSchema):
        self.db, self.auth = db, auth

    async def _scope(self, user_id: int, *, lock: bool = False) -> None:
        if self.auth.actor_type != "staff" or not self.auth.user or not self.auth.user.id:
            raise CustomException(msg="仅运营人员可以调整使用天数", status_code=403)
        app = await get_model_policy(self.db, self.auth.app_id, lock=lock)
        if "duration" not in allowed_modes(app):
            raise CustomException(msg="当前客户端为积分模式，不支持调整使用天数", status_code=409)
        user = await self.db.scalar(select(ClientUserModel).where(ClientUserModel.id == user_id, ClientUserModel.app_id == app.id, ClientUserModel.is_deleted == False))
        if not user:
            raise CustomException(msg="当前客户端下不存在该用户", status_code=404)
        if current_mode(app, user) != "duration":
            raise CustomException(msg="该用户当前未使用 token 自费模式，请先完成订阅模式选择", status_code=409)
        if lock and user.active_billing_mode is None:
            user.active_billing_mode = "duration"

    async def _subscription(self, user_id: int, *, lock: bool = False) -> SubscriptionModel | None:
        query = select(SubscriptionModel).where(SubscriptionModel.app_id == self.auth.app_id, SubscriptionModel.user_id == user_id, SubscriptionModel.is_deleted == False)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        return await self.db.scalar(query)

    async def state(self, user_id: int) -> DurationStateOut:
        await self._scope(user_id)
        sub = await self._subscription(user_id)
        now = datetime.now(UTC)
        end = utc(sub.current_period_end) if sub and sub.entitlement_kind == "duration" else None
        plans = await self.db.scalars(
            select(AppCatalogPlanModel).where(AppCatalogPlanModel.app_id == self.auth.app_id, AppCatalogPlanModel.entitlement_kind == "duration", AppCatalogPlanModel.is_deleted == False)
        )
        records = await self.db.scalars(
            select(DurationAdjustmentModel).where(DurationAdjustmentModel.app_id == self.auth.app_id, DurationAdjustmentModel.user_id == user_id).order_by(DurationAdjustmentModel.id.desc()).limit(20)
        )
        return DurationStateOut(
            status=sub.status if end else "not_purchased",
            expires_at=end,
            remaining_seconds=max(0, int((end - now).total_seconds())) if end else 0,
            server_time=now,
            catalog_plan_id=sub.catalog_plan_id if end else None,
            plans=[DurationPlanOption(id=p.id, name=p.name) for p in plans],
            records=[DurationAdjustmentOut.model_validate(row) for row in records],
        )

    async def adjust(self, user_id: int, data: DurationAdjustSchema) -> DurationAdjustmentOut:
        await self._scope(user_id, lock=True)
        fingerprint = hashlib.sha256(
            json.dumps({"user_id": user_id, "operator_id": self.auth.user.id, **data.model_dump(mode="json", exclude={"idempotency_key"})}, sort_keys=True).encode()
        ).hexdigest()
        # Same app lock as model-mode changes; same account lock as payment/refund.
        await CreditService(self.db).account(self.auth.app_id, user_id, lock=True)
        prior = await self.db.scalar(select(DurationAdjustmentModel).where(DurationAdjustmentModel.app_id == self.auth.app_id, DurationAdjustmentModel.idempotency_key == data.idempotency_key))
        if prior:
            if prior.request_fingerprint != fingerprint:
                raise CustomException(msg="本次调整标识已使用，请刷新后重新确认", status_code=409)
            return DurationAdjustmentOut.model_validate(prior)
        sub = await self._subscription(user_id, lock=True)
        now = datetime.now(UTC)
        before = utc(sub.current_period_end) if sub and sub.entitlement_kind == "duration" else None
        expected = utc(data.expected_expires_at) if data.expected_expires_at else None
        if before != expected:
            raise CustomException(msg="用户订阅已变化，请刷新后重新确认调整", status_code=409)
        if sub and sub.entitlement_kind != "duration" and utc(sub.current_period_end) > now:
            raise CustomException(msg="用户仍有其他类型权益，请先完成权益核对", status_code=409)
        if before and before > now:
            projection = await project_subscription(self.db, sub, now=now, respect_cancellation=True)
            if projection["ends_at"] != before:
                raise CustomException(msg="订阅与权益周期不一致，请先核对权益记录", status_code=409)
        changes = []
        if data.direction == "grant":
            plan_id = data.catalog_plan_id or (sub.catalog_plan_id if sub else None)
            plan = await self.db.scalar(
                select(AppCatalogPlanModel).where(
                    AppCatalogPlanModel.id == plan_id, AppCatalogPlanModel.app_id == self.auth.app_id, AppCatalogPlanModel.entitlement_kind == "duration", AppCatalogPlanModel.is_deleted == False
                )
            )
            if not plan:
                raise CustomException(msg="请选择当前客户端的时长套餐；没有套餐时请先创建时长刊例", status_code=422)
            if sub is None:
                sub = SubscriptionModel(app_id=self.auth.app_id, user_id=user_id, catalog_plan_id=plan.id, entitlement_kind="duration", current_period_start=now, current_period_end=now)
                self.db.add(sub)
                await self.db.flush()
            sub.entitlement_kind = "duration"
            start = max(before or now, now)
            sequence = await self.db.scalar(
                select(func.max(SubscriptionCycleModel.cycle_no)).where(SubscriptionCycleModel.app_id == self.auth.app_id, SubscriptionCycleModel.subscription_id == sub.id)
            )
            cycle = SubscriptionCycleModel(
                app_id=self.auth.app_id,
                user_id=user_id,
                subscription_id=sub.id,
                order_id=None,
                cycle_no=int(sequence or 0) + 1,
                starts_at=start,
                ends_at=start + timedelta(days=data.days),
                status="active",
                plan_snapshot={
                    "source": "manual_duration_adjustment",
                    "entitlement_kind": "duration",
                    "catalog_plan_id": plan.id,
                    "name": plan.name,
                    "benefit_period_days": data.days,
                    "total_credits": 0,
                    "release_plan": [],
                },
            )
            self.db.add(cycle)
            await self.db.flush()
            changes.append({"cycle_id": cycle.id, "before": None, "after": cycle.ends_at.isoformat()})
            seconds_delta = data.days * 86400
        else:
            if not before or before <= now:
                raise CustomException(msg="用户没有可扣减的剩余时长", status_code=409)
            cycles = list(
                await self.db.scalars(
                    select(SubscriptionCycleModel)
                    .where(
                        SubscriptionCycleModel.app_id == self.auth.app_id,
                        SubscriptionCycleModel.subscription_id == sub.id,
                        SubscriptionCycleModel.user_id == user_id,
                        SubscriptionCycleModel.status == "active",
                        SubscriptionCycleModel.is_deleted == False,
                    )
                    .order_by(SubscriptionCycleModel.ends_at.desc())
                    .with_for_update()
                )
            )
            to_remove = min(timedelta(days=data.days), before - now)
            seconds_delta = -int(to_remove.total_seconds())
            for cycle in cycles:
                if cycle.plan_snapshot.get("entitlement_kind") != "duration":
                    continue
                available = max(utc(cycle.ends_at) - max(utc(cycle.starts_at), now), timedelta(0))
                cut = min(available, to_remove)
                if cut <= timedelta(0):
                    continue
                old_end = utc(cycle.ends_at)
                cycle.ends_at = old_end - cut
                if cycle.ends_at <= utc(cycle.starts_at):
                    cycle.status = "cancelled"
                changes.append({"cycle_id": cycle.id, "before": old_end.isoformat(), "after": cycle.ends_at.isoformat()})
                to_remove -= cut
                if to_remove <= timedelta(0):
                    break
            if to_remove > timedelta(0):
                raise CustomException(msg="订阅与权益周期不一致，请先核对权益记录", status_code=409)
        await self.db.flush()
        apply_subscription_projection(sub, await project_subscription(self.db, sub, now=now, respect_cancellation=True))
        sub.auto_renew = False
        sub.next_renewal_at = None
        record = DurationAdjustmentModel(
            app_id=self.auth.app_id,
            user_id=user_id,
            subscription_id=sub.id,
            idempotency_key=data.idempotency_key,
            request_fingerprint=fingerprint,
            direction=data.direction,
            days=data.days,
            seconds_delta=seconds_delta,
            before_expires_at=before,
            after_expires_at=sub.current_period_end,
            reason=data.reason,
            operator_name=self.auth.user.username,
            created_id=self.auth.user.id,
            updated_id=self.auth.user.id,
            cycle_changes=changes,
        )
        self.db.add(record)
        await self.db.flush()
        return DurationAdjustmentOut.model_validate(record)
