import math
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import uuid4

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.module_client.app.model import ClientAppModel
from app.api.v1.module_client.app.model_policy import allowed_modes, billing_user, current_mode, get_model_policy, require_platform_model
from app.api.v1.module_client.user.model import ClientUserModel
from app.core.base_schema import AuthSchema
from app.core.database import async_db_session
from app.core.exceptions import CustomException

from .grant_messages import notify_credit_grant
from .model import (
    AppCatalogPlanModel,
    AppPricingStrategyItemModel,
    AppPricingStrategyModel,
    CreditAccountModel,
    CreditGrantModel,
    CreditLedgerModel,
    CreditReservationModel,
    PricingPlanTemplateModel,
    PricingStandardVersionModel,
    SubscriptionCycleModel,
    SubscriptionModel,
)
from .plan_rules import validate_entitlement
from .reservation_policy import RESERVATION_STALE_SECONDS
from .schema import (
    CatalogPlanCreateSchema,
    CatalogPlanOutSchema,
    CatalogPlanUpdateSchema,
    ClientCreditLedgerOutSchema,
    ClientSubscriptionOutSchema,
    CreditAccountOutSchema,
    PricingStrategyCreateSchema,
    PricingStrategyItemOutSchema,
    PricingStrategyOutSchema,
    PricingStrategyStatusSchema,
    PricingTemplateOutSchema,
    PricingVersionCreateSchema,
    PricingVersionOutSchema,
    PricingVersionUpdateSchema,
    SubscriptionAdminOutSchema,
    SubscriptionStatusSchema,
)
from .upgrades import supersede_pending_grants, suppress_legacy_upgrade_grants


class PricingService:
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db

    async def _lock_versions(self) -> None:
        # Serialize platform-wide publishing with edits/deletions, including different versions.
        if self.db.get_bind().dialect.name == "postgresql":
            from sqlalchemy import text

            await self.db.execute(text("SELECT pg_advisory_xact_lock(742019001)"))

    async def versions(self) -> list[PricingVersionOutSchema]:
        rows = list((await self.db.scalars(select(PricingStandardVersionModel).where(PricingStandardVersionModel.is_deleted == False).order_by(PricingStandardVersionModel.id.desc()))).all())
        result: list[PricingVersionOutSchema] = []
        for row in rows:
            item = PricingVersionOutSchema.model_validate(row)
            item.template_count = int(
                await self.db.scalar(select(func.count()).select_from(PricingPlanTemplateModel).where(PricingPlanTemplateModel.version_id == row.id, PricingPlanTemplateModel.is_deleted == False)) or 0
            )
            result.append(item)
        return result

    async def create_version(self, data: PricingVersionCreateSchema) -> PricingVersionOutSchema:
        await self._lock_versions()
        if await self.db.scalar(select(PricingStandardVersionModel.id).where(PricingStandardVersionModel.version == data.version)):
            raise CustomException(msg="价格体系版本已存在")
        version = PricingStandardVersionModel(**data.model_dump(exclude={"templates"}), status="draft", created_id=self.auth.user.id, updated_id=self.auth.user.id)
        self.db.add(version)
        await self.db.flush()
        for template in data.templates:
            self.db.add(PricingPlanTemplateModel(version_id=version.id, **template.model_dump(), created_id=self.auth.user.id, updated_id=self.auth.user.id))
        await self.db.flush()
        output = PricingVersionOutSchema.model_validate(version)
        output.template_count = len(data.templates)
        return output

    async def templates(self, version_id: int) -> list[PricingTemplateOutSchema]:
        if not await self.db.scalar(select(PricingStandardVersionModel.id).where(PricingStandardVersionModel.id == version_id, PricingStandardVersionModel.is_deleted == False)):
            raise CustomException(msg="价格体系版本不存在", status_code=404)
        rows = list(
            (
                await self.db.scalars(
                    select(PricingPlanTemplateModel)
                    .where(
                        PricingPlanTemplateModel.version_id == version_id,
                        PricingPlanTemplateModel.is_deleted == False,
                    )
                    .order_by(PricingPlanTemplateModel.order.asc())
                )
            ).all()
        )
        return [PricingTemplateOutSchema.model_validate(row) for row in rows]

    async def update_version(
        self,
        version_id: int,
        data: PricingVersionUpdateSchema,
    ) -> PricingVersionOutSchema:
        await self._lock_versions()
        version = await self.db.scalar(
            select(PricingStandardVersionModel).where(
                PricingStandardVersionModel.id == version_id,
                PricingStandardVersionModel.is_deleted == False,
            )
        )
        if not version:
            raise CustomException(msg="价格体系版本不存在", status_code=404)
        duplicate = await self.db.scalar(
            select(PricingStandardVersionModel.id).where(
                PricingStandardVersionModel.version == data.version,
                PricingStandardVersionModel.id != version_id,
            )
        )
        if duplicate:
            raise CustomException(msg="价格体系版本已存在")
        values = data.model_dump(exclude={"templates"})
        for key, value in values.items():
            setattr(version, key, value)
        version.updated_id = self.auth.user.id
        # Preserve template identities and all existing catalog references.
        existing = {row.code: row for row in (await self.db.scalars(select(PricingPlanTemplateModel).where(PricingPlanTemplateModel.version_id == version_id))).all()}
        incoming = {template.code for template in data.templates}
        for code, row in existing.items():
            if code not in incoming and not row.is_deleted:
                row.is_deleted, row.deleted_time, row.deleted_id = True, datetime.now(UTC), self.auth.user.id
        for template in data.templates:
            row = existing.get(template.code)
            if row is None:
                row = PricingPlanTemplateModel(version_id=version.id, created_id=self.auth.user.id)
                self.db.add(row)
            for key, value in template.model_dump().items():
                setattr(row, key, value)
            row.is_deleted, row.deleted_time, row.deleted_id = False, None, None
            row.updated_id = self.auth.user.id
        await self.db.flush()
        output = PricingVersionOutSchema.model_validate(version)
        output.template_count = len(data.templates)
        return output

    async def delete_version(self, version_id: int) -> None:
        await self._lock_versions()
        version = await self.db.scalar(select(PricingStandardVersionModel).where(PricingStandardVersionModel.id == version_id, PricingStandardVersionModel.is_deleted == False).with_for_update())
        if not version:
            raise CustomException(msg="价格体系版本不存在", status_code=404)
        if version.status == "published":
            raise CustomException(msg="已发布的价格体系不能删除", status_code=409)
        template_ids = select(PricingPlanTemplateModel.id).where(PricingPlanTemplateModel.version_id == version_id)
        has_catalog = await self.db.scalar(
            select(AppCatalogPlanModel.id)
            .where(or_(AppCatalogPlanModel.pricing_version_id == version_id, AppCatalogPlanModel.template_id.in_(template_ids)), AppCatalogPlanModel.is_deleted == False)
            .limit(1)
        )
        has_strategy = await self.db.scalar(select(AppPricingStrategyModel.id).where(AppPricingStrategyModel.pricing_version_id == version_id, AppPricingStrategyModel.is_deleted == False).limit(1))
        if has_catalog or has_strategy:
            raise CustomException(msg="此版本仍有关联的产品刊例或定价策略，请先处理关联数据后再删除", status_code=409)
        now = datetime.now(UTC)
        version.is_deleted, version.deleted_time, version.deleted_id = True, now, self.auth.user.id
        version.updated_id = self.auth.user.id
        await self.db.execute(
            update(PricingPlanTemplateModel)
            .where(PricingPlanTemplateModel.version_id == version_id, PricingPlanTemplateModel.is_deleted == False)
            .values(is_deleted=True, deleted_time=now, deleted_id=self.auth.user.id, updated_id=self.auth.user.id)
        )
        await self.db.flush()

    async def publish(self, version_id: int) -> PricingVersionOutSchema:
        await self._lock_versions()
        version = await self.db.scalar(select(PricingStandardVersionModel).where(PricingStandardVersionModel.id == version_id, PricingStandardVersionModel.is_deleted == False))
        if not version:
            raise CustomException(msg="价格体系版本不存在")
        template_count = int(
            await self.db.scalar(select(func.count()).select_from(PricingPlanTemplateModel).where(PricingPlanTemplateModel.version_id == version_id, PricingPlanTemplateModel.is_deleted == False)) or 0
        )
        if not template_count:
            raise CustomException(msg="至少配置一个完整套餐模板后才能发布")
        await self.db.execute(
            PricingStandardVersionModel.__table__.update().where(PricingStandardVersionModel.status == "published", PricingStandardVersionModel.is_deleted == False).values(status="archived")
        )
        version.status = "published"
        version.published_at = datetime.now(UTC)
        await self.db.flush()
        output = PricingVersionOutSchema.model_validate(version)
        output.template_count = template_count
        return output


class CatalogService:
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db

    def _app_id(self) -> int:
        if not self.auth.app_id:
            raise CustomException(msg="请先选择客户端", status_code=409)
        return self.auth.app_id

    @staticmethod
    def purchase_type_for_plan(plan: AppCatalogPlanModel | CatalogPlanOutSchema, subscription: SubscriptionModel | None) -> str:
        # An existing subscription to another tier is an upgrade, not a renewal of this plan.
        return "renewal" if plan.plan_type == "subscription" and subscription and subscription.entitlement_kind == plan.entitlement_kind and (getattr(plan, "entitlement_kind", "credits") == "duration" or subscription.catalog_plan_id == plan.id) else "first"

    async def list_plans(self, *, public_only: bool = False, purchase_type: str | None = None, user_id: int | None = None, entitlement_kind: str | None = None) -> list[CatalogPlanOutSchema]:
        now = datetime.now(UTC)
        stmt = select(AppCatalogPlanModel).where(AppCatalogPlanModel.app_id == self._app_id(), AppCatalogPlanModel.is_deleted == False)
        if entitlement_kind:
            stmt = stmt.where(AppCatalogPlanModel.entitlement_kind == entitlement_kind)
        if public_only:
            app = await get_model_policy(self.db, self._app_id())
            stmt = stmt.where(
                AppCatalogPlanModel.entitlement_kind.in_(allowed_modes(app)),
                AppCatalogPlanModel.status == "on_sale",
                or_(AppCatalogPlanModel.effective_from.is_(None), AppCatalogPlanModel.effective_from <= now),
                or_(AppCatalogPlanModel.effective_until.is_(None), AppCatalogPlanModel.effective_until > now),
            )
        ordering = (
            [AppCatalogPlanModel.plan_type.asc(), AppCatalogPlanModel.one_time_price_fen.asc(), AppCatalogPlanModel.order.asc(), AppCatalogPlanModel.id.asc()]
            if public_only
            else [AppCatalogPlanModel.order.asc(), AppCatalogPlanModel.id.asc()]
        )
        rows = list((await self.db.scalars(stmt.order_by(*ordering))).all())
        result = [CatalogPlanOutSchema.model_validate(row) for row in rows]
        if public_only:
            resolved_user_id = self.auth.user.id if self.auth.actor_type == "client" else user_id
            if resolved_user_id is not None:
                user = await self.db.scalar(
                    select(ClientUserModel.id).where(
                        ClientUserModel.id == resolved_user_id,
                        ClientUserModel.app_id == self._app_id(),
                        ClientUserModel.is_deleted == False,
                    )
                )
                if user is None:
                    raise CustomException(msg="客户端用户不存在", status_code=404)
            subscription_row = (
                await self.db.execute(
                    select(SubscriptionModel, AppCatalogPlanModel)
                    .join(AppCatalogPlanModel, AppCatalogPlanModel.id == SubscriptionModel.catalog_plan_id)
                    .where(
                        SubscriptionModel.app_id == self._app_id(),
                        SubscriptionModel.user_id == resolved_user_id,
                        SubscriptionModel.is_deleted == False,
                    )
                )
            ).first()
            current_subscription, current_plan = subscription_row if subscription_row else (None, None)
            prior_subscription = current_subscription
            if current_subscription:
                end = current_subscription.current_period_end
                if current_subscription.status != "active" or (end.replace(tzinfo=UTC) if end.tzinfo is None else end) <= now:
                    current_subscription, current_plan = None, None
            mode = current_mode(app, await billing_user(self.db, app, resolved_user_id)) if resolved_user_id else None
            for item in result:
                item.requires_mode_switch = mode is not None and item.entitlement_kind != mode
                item.purchase_type = self.purchase_type_for_plan(item, prior_subscription) if resolved_user_id is not None or item.plan_type == "credit_pack" else (purchase_type or "first")
                resolution = await self.resolve_pricing(item.id, item.purchase_type, now=now, user_id=resolved_user_id)
                item.base_price_fen = item.recurring_price_fen if item.purchase_type == "renewal" else item.one_time_price_fen
                item.effective_price_fen = resolution["execution_price_fen"]
                item.discount_amount_fen = max(0, item.base_price_fen - item.effective_price_fen)
                item.strategy_version = resolution.get("strategy_version")
                item.strategy_name = resolution.get("strategy_name")
                item.is_current = bool(current_subscription and item.id == current_subscription.catalog_plan_id)
                if item.plan_type == "credit_pack":
                    item.eligible = not item.requires_active_subscription or (current_subscription is not None and current_subscription.entitlement_kind == "credits")
                    item.disabled_reason = None if item.eligible else "订阅后才可购买追加包"
                elif item.entitlement_kind != "duration" and current_plan is not None and current_plan.entitlement_kind == item.entitlement_kind and item.tier_order <= current_plan.tier_order:
                    item.eligible = False
                    item.disabled_reason = "当前套餐" if item.is_current else "仅支持升级到更高等级套餐"
        return result

    async def effective_price(self, plan: CatalogPlanOutSchema, purchase_type: str, now: datetime | None = None) -> int:
        return int((await self.resolve_pricing(plan.id, purchase_type, now=now))["execution_price_fen"])

    async def _matches_scope(self, strategy: AppPricingStrategyModel, user: ClientUserModel | None) -> bool:
        if strategy.scope_type == "all":
            return True
        if user is None:
            return False
        value = strategy.scope_value or {}
        if strategy.scope_type == "new":
            registered = user.registered_at
            if registered.tzinfo is None:
                registered = registered.replace(tzinfo=UTC)
            return registered >= datetime.now(UTC) - timedelta(days=int(value.get("days") or 30))
        if strategy.scope_type == "level":
            from app.api.v1.module_growth.filters import grade_codes

            return bool(
                await self.db.scalar(
                    select(ClientUserModel.id).where(ClientUserModel.id == user.id, ClientUserModel.app_id == self._app_id(), grade_codes(self._app_id(), value.get("level_codes") or []))
                )
            )
        if strategy.scope_type == "users":
            return user.id in {int(item) for item in (value.get("user_ids") or [])}
        if strategy.scope_type == "segment":
            from app.api.v1.module_client.user.model import ClientUserSegmentModel

            segment = await self.db.scalar(
                select(ClientUserSegmentModel).where(
                    ClientUserSegmentModel.id == value.get("segment_id"),
                    ClientUserSegmentModel.app_id == self._app_id(),
                    ClientUserSegmentModel.status == "active",
                    ClientUserSegmentModel.is_deleted == False,
                )
            )
            if not segment:
                return False
            filters = segment.filters or {}
            from app.api.v1.module_growth.filters import segment_conditions

            if not await self.db.scalar(select(ClientUserModel.id).where(ClientUserModel.id == user.id, ClientUserModel.app_id == self._app_id(), *segment_conditions(self._app_id(), filters))):
                return False
            if filters.get("registered_days"):
                registered = user.registered_at
                if registered.tzinfo is None:
                    registered = registered.replace(tzinfo=UTC)
                if registered < datetime.now(UTC) - timedelta(days=int(filters["registered_days"])):
                    return False
            return True
        return False

    async def resolve_pricing(
        self,
        plan_id: int,
        purchase_type: str,
        *,
        now: datetime | None = None,
        user_id: int | None = None,
    ) -> dict:
        """Resolve the executable price and immutable cost conversion snapshot."""
        at = now or datetime.now(UTC)
        plan = await self.db.scalar(
            select(AppCatalogPlanModel).where(
                AppCatalogPlanModel.id == plan_id,
                AppCatalogPlanModel.app_id == self._app_id(),
                AppCatalogPlanModel.is_deleted == False,
            )
        )
        if not plan:
            raise CustomException(msg="刊例不存在", status_code=404)
        resolved_user_id = user_id or (self.auth.user.id if self.auth.actor_type == "client" else None)
        user = None
        if resolved_user_id:
            user = await self.db.scalar(
                select(ClientUserModel).where(
                    ClientUserModel.id == resolved_user_id,
                    ClientUserModel.app_id == self._app_id(),
                    ClientUserModel.is_deleted == False,
                )
            )
        strategies = list(
            (
                await self.db.scalars(
                    select(AppPricingStrategyModel)
                    .options(selectinload(AppPricingStrategyModel.items))
                    .where(
                        AppPricingStrategyModel.app_id == self._app_id(),
                        AppPricingStrategyModel.status == "active",
                        AppPricingStrategyModel.is_deleted == False,
                        AppPricingStrategyModel.starts_at <= at,
                        AppPricingStrategyModel.ends_at > at,
                    )
                    .order_by(AppPricingStrategyModel.published_at.desc(), AppPricingStrategyModel.id.desc())
                )
            ).all()
        )
        base_price = plan.recurring_price_fen if purchase_type == "renewal" else plan.one_time_price_fen
        for strategy in strategies:
            if not await self._matches_scope(strategy, user):
                continue
            matching = [item for item in strategy.items if item.catalog_plan_id == plan.id and item.is_deleted is False and item.purchase_type in {purchase_type, "all"}]
            if not matching:
                continue
            item = sorted(matching, key=lambda row: row.purchase_type != purchase_type)[0]
            # Catalog edits affect new quotes; paid orders and grants retain their own snapshots.
            execution = int((Decimal(base_price) * Decimal(str(item.discount_rate))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            allowed_cost = Decimal(execution) / 100 * (Decimal(100) - Decimal(str(item.margin_rate))) / 100 if execution else Decimal(str(item.allowed_cost_yuan))
            rate = Decimal(plan.total_credits) / allowed_cost if allowed_cost > 0 else Decimal(str(item.credits_per_cost_yuan))
            if plan.entitlement_kind == "duration":
                allowed_cost, rate = Decimal(0), Decimal(0)
            return {
                "execution_price_fen": execution,
                "strategy_id": strategy.id,
                "strategy_version": strategy.version,
                "strategy_name": strategy.name,
                "strategy_item_id": item.id,
                "discount_rate": float(item.discount_rate),
                "margin_rate": float(item.margin_rate),
                "allowed_cost_yuan": float(allowed_cost),
                "credits_per_cost_yuan": float(rate),
                "scope_type": strategy.scope_type,
            }
        version = await self.db.scalar(
            select(PricingStandardVersionModel).where(
                PricingStandardVersionModel.id == plan.pricing_version_id,
                PricingStandardVersionModel.is_deleted == False,
            )
        )
        margin_rate = float(version.margin_baseline if version else 60)
        if margin_rate <= 0:
            margin_rate = 60
        allowed_cost = float(plan.cost_budget_yuan or (Decimal(base_price) / 100 * (Decimal(100) - Decimal(str(margin_rate))) / 100))
        rate = float(Decimal(plan.total_credits) / Decimal(str(allowed_cost))) if allowed_cost > 0 else 2500.0
        if plan.entitlement_kind == "duration":
            margin_rate, allowed_cost, rate = 0, 0, 0
        return {
            "execution_price_fen": base_price,
            "strategy_id": None,
            "strategy_version": None,
            "strategy_name": None,
            "strategy_item_id": None,
            "discount_rate": 1.0,
            "margin_rate": margin_rate,
            "allowed_cost_yuan": allowed_cost,
            "credits_per_cost_yuan": rate,
            "scope_type": "all",
        }

    async def create(self, data: CatalogPlanCreateSchema) -> CatalogPlanOutSchema:
        app = await get_model_policy(self.db, self._app_id(), lock=True)
        if data.entitlement_kind not in allowed_modes(app):
            raise CustomException(msg="套餐权益类型与当前客户端模型模式不一致", status_code=409)
        version = await self.db.scalar(
            select(PricingStandardVersionModel).where(
                PricingStandardVersionModel.id == data.pricing_version_id, PricingStandardVersionModel.status == "published", PricingStandardVersionModel.is_deleted == False
            )
        )
        if not version:
            raise CustomException(msg="只能引用已发布的价格体系版本")
        if data.template_id and not await self.db.scalar(
            select(PricingPlanTemplateModel.id).where(
                PricingPlanTemplateModel.id == data.template_id,
                PricingPlanTemplateModel.version_id == data.pricing_version_id,
                PricingPlanTemplateModel.entitlement_kind == data.entitlement_kind,
                PricingPlanTemplateModel.is_deleted == False,
            )
        ):
            raise CustomException(msg="套餐模板不存在或不属于所选价格体系，请重新选择模板", status_code=409)
        if await self.db.scalar(select(AppCatalogPlanModel.id).where(AppCatalogPlanModel.app_id == self._app_id(), AppCatalogPlanModel.code == data.code, AppCatalogPlanModel.is_deleted == False)):
            raise CustomException(msg="当前客户端已存在相同刊例编码")
        if data.entitlement_kind == "duration" and data.status == "on_sale" and min(data.one_time_price_fen, data.recurring_price_fen) <= 0:
            raise CustomException(msg="时长套餐上架需设置大于0的首购和续费价格", status_code=422)
        if data.entitlement_kind == "credits" and data.status == "on_sale" and data.one_time_price_fen == 0 and not data.cost_budget_yuan:
            raise CustomException(msg="零元刊例上架前必须显式填写允许成本")
        plan = AppCatalogPlanModel(app_id=self._app_id(), **data.model_dump(), created_id=self.auth.user.id, updated_id=self.auth.user.id)
        self.db.add(plan)
        await self.db.flush()
        return CatalogPlanOutSchema.model_validate(plan)

    async def update(self, plan_id: int, data: CatalogPlanUpdateSchema) -> CatalogPlanOutSchema:
        app = await get_model_policy(self.db, self._app_id(), lock=True)
        plan = await self.db.scalar(
            select(AppCatalogPlanModel).where(
                AppCatalogPlanModel.id == plan_id,
                AppCatalogPlanModel.app_id == self._app_id(),
                AppCatalogPlanModel.is_deleted == False,
            )
        )
        if not plan:
            raise CustomException(msg="刊例不存在", status_code=404)
        values = data.model_dump(exclude_unset=True)
        if values.get("entitlement_kind", plan.entitlement_kind) != plan.entitlement_kind:
            raise CustomException(msg="不能变更已有刊例的权益类型，请创建新刊例", status_code=409)
        # Old-mode products can still be taken off sale without being rewritten.
        if values.get("status", plan.status) == "on_sale" and plan.entitlement_kind not in allowed_modes(app):
            raise CustomException(msg="该套餐不适用于当前客户端模型模式", status_code=409)
        release_plan = values.get("release_plan", plan.release_plan)
        total_credits = values.get("total_credits", plan.total_credits)
        try:
            validate_entitlement(plan.entitlement_kind, plan.plan_type, total_credits, release_plan, values.get("requires_active_subscription", plan.requires_active_subscription))
        except (ValueError, TypeError) as exc:
            raise CustomException(msg="套餐积分与订阅时长配置不合法", status_code=422) from exc
        normalized_plan = [item.model_dump() if hasattr(item, "model_dump") else item for item in release_plan]
        if sum(int(item["amount"]) for item in normalized_plan) != total_credits:
            raise CustomException(msg="释放计划之和必须等于总积分")
        values["release_plan"] = normalized_plan
        next_status = values.get("status", plan.status)
        next_price = values.get("one_time_price_fen", plan.one_time_price_fen)
        next_budget = values.get("cost_budget_yuan", plan.cost_budget_yuan)
        if plan.entitlement_kind == "duration" and next_status == "on_sale" and min(next_price, values.get("recurring_price_fen", plan.recurring_price_fen)) <= 0:
            raise CustomException(msg="时长套餐上架需设置大于0的首购和续费价格", status_code=422)
        if plan.entitlement_kind == "credits" and next_status == "on_sale" and next_price == 0 and not next_budget:
            raise CustomException(msg="零元刊例上架前必须显式填写允许成本")
        for key, value in values.items():
            setattr(plan, key, value)
        plan.updated_id = self.auth.user.id
        await self.db.flush()
        return CatalogPlanOutSchema.model_validate(plan)

    async def create_strategy(self, data: PricingStrategyCreateSchema) -> PricingStrategyOutSchema:
        return await self._save_strategy(data)

    async def _get_strategy(self, strategy_id: int, *, lock: bool = False) -> AppPricingStrategyModel:
        stmt = (
            select(AppPricingStrategyModel)
            .options(selectinload(AppPricingStrategyModel.items))
            .where(
                AppPricingStrategyModel.id == strategy_id,
                AppPricingStrategyModel.app_id == self._app_id(),
                AppPricingStrategyModel.is_deleted == False,
            )
        )
        if lock:
            stmt = stmt.with_for_update()
        strategy = await self.db.scalar(stmt)
        if not strategy:
            raise CustomException(msg="定价策略不存在", status_code=404)
        return strategy

    async def strategy(self, strategy_id: int) -> PricingStrategyOutSchema:
        return await self._strategy_out(await self._get_strategy(strategy_id))

    async def update_strategy(self, strategy_id: int, data: PricingStrategyCreateSchema) -> PricingStrategyOutSchema:
        await get_model_policy(self.db, self._app_id(), lock=True)
        strategy = await self._get_strategy(strategy_id, lock=True)
        if strategy.status == "active":
            raise CustomException(msg="请先下架策略再编辑，已购权益仍按原快照结算")
        return await self._save_strategy(data, strategy)

    async def delete_strategy(self, strategy_id: int) -> None:
        strategy = await self._get_strategy(strategy_id, lock=True)
        if strategy.status == "active":
            raise CustomException(msg="请先下架策略再删除")
        strategy.is_deleted = True
        strategy.updated_id = self.auth.user.id
        for item in strategy.items:
            item.is_deleted = True
            item.updated_id = self.auth.user.id
        await self.db.flush()

    async def _save_strategy(self, data: PricingStrategyCreateSchema, strategy: AppPricingStrategyModel | None = None) -> PricingStrategyOutSchema:
        app_policy = await get_model_policy(self.db, self._app_id(), lock=True)
        items = data.items or []
        if not items:
            plan = await self.db.scalar(
                select(AppCatalogPlanModel).where(AppCatalogPlanModel.id == data.catalog_plan_id, AppCatalogPlanModel.app_id == self._app_id(), AppCatalogPlanModel.is_deleted == False)
            )
            if not plan:
                raise CustomException(msg="刊例不存在")
            base = plan.recurring_price_fen if data.purchase_type == "renewal" else plan.one_time_price_fen
            discount = float(data.discount_rate) if data.discount_rate is not None else (float(data.fixed_price_fen or 0) / base if base else 1)
            items = [{"catalog_plan_id": plan.id, "purchase_type": data.purchase_type, "discount_rate": discount, "margin_rate": 60, "remark": data.description}]
        if not data.version:
            data.version = f"V{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}"
        if await self.db.scalar(
            select(AppPricingStrategyModel.id).where(
                AppPricingStrategyModel.app_id == self._app_id(),
                AppPricingStrategyModel.version == data.version,
                AppPricingStrategyModel.is_deleted == False,
                AppPricingStrategyModel.id != (strategy.id if strategy else 0),
            )
        ):
            raise CustomException(msg="当前客户端已存在相同策略版本")
        pricing_version_id = data.pricing_version_id or await self.db.scalar(
            select(PricingStandardVersionModel.id).where(PricingStandardVersionModel.status == "published", PricingStandardVersionModel.is_deleted == False)
        )
        version = await self.db.scalar(select(PricingStandardVersionModel).where(PricingStandardVersionModel.id == pricing_version_id, PricingStandardVersionModel.is_deleted == False))
        if not version or (version.status != "published" and (not strategy or strategy.pricing_version_id != version.id)):
            raise CustomException(msg="请先发布价格体系")
        normalized_items: list[dict] = []
        for raw in items:
            item = raw if isinstance(raw, dict) else raw.model_dump()
            purchase_types = ["first", "renewal"] if item["purchase_type"] == "all" else [item["purchase_type"]]
            normalized_items.extend([{**item, "purchase_type": purchase_type} for purchase_type in purchase_types])
        if len({(item["catalog_plan_id"], item["purchase_type"]) for item in normalized_items}) != len(normalized_items):
            raise CustomException(msg="同一刊例和购买类型不能重复配置")
        first = normalized_items[0]
        values = {
            "app_id": self._app_id(),
            "version": data.version,
            "pricing_version_id": version.id,
            "catalog_plan_id": first["catalog_plan_id"] if isinstance(first, dict) else first.catalog_plan_id,
            "name": data.name,
            "purchase_type": data.purchase_type,
            "discount_rate": data.discount_rate,
            "fixed_price_fen": data.fixed_price_fen,
            "starts_at": data.starts_at,
            "ends_at": data.ends_at,
            "status": "inactive",
            "description": data.description,
            "scope_type": data.scope_type,
            "scope_value": data.scope_value,
            "updated_id": self.auth.user.id,
        }
        existing_items = {}
        if strategy:
            existing_items = {(item.catalog_plan_id, item.purchase_type): item for item in strategy.items}
            for item in strategy.items:
                item.is_deleted = True
                item.updated_id = self.auth.user.id
            for key, value in values.items():
                setattr(strategy, key, value)
        else:
            strategy = AppPricingStrategyModel(**values, created_id=self.auth.user.id)
            self.db.add(strategy)
        await self.db.flush()
        for item in normalized_items:
            plan = await self.db.scalar(
                select(AppCatalogPlanModel).where(AppCatalogPlanModel.id == item["catalog_plan_id"], AppCatalogPlanModel.app_id == self._app_id(), AppCatalogPlanModel.is_deleted == False)
            )
            if not plan:
                raise CustomException(msg="策略包含不存在的刊例")
            if plan.entitlement_kind not in allowed_modes(app_policy):
                raise CustomException(msg="策略刊例与当前模型服务模式不一致", status_code=409)
            if plan.entitlement_kind != "duration" and item["margin_rate"] < float(version.margin_floor):
                raise CustomException(msg=f"{plan.name} 的目标毛利率不能低于安全线 {version.margin_floor}%")
            base = plan.recurring_price_fen if item["purchase_type"] == "renewal" else plan.one_time_price_fen
            execution = int((Decimal(base) * Decimal(str(item["discount_rate"]))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            allowed_cost = Decimal(execution) / 100 * (Decimal(100) - Decimal(str(item["margin_rate"]))) / 100
            if execution == 0:
                allowed_cost = Decimal(str(item.get("allowed_cost_yuan") or plan.cost_budget_yuan or 0))
            if plan.entitlement_kind != "duration" and allowed_cost <= 0:
                raise CustomException(msg=f"{plan.name} 为零元刊例，请在策略刊例项中填写大于 0 的允许模型成本")
            rate = Decimal(plan.total_credits) / allowed_cost if allowed_cost > 0 else Decimal(0)
            if plan.entitlement_kind == "duration":
                if execution <= 0:
                    raise CustomException(msg="时长套餐执行价必须大于0", status_code=422)
                allowed_cost, rate = Decimal(0), Decimal(0)
                item["margin_rate"] = 0
            item_values = {
                "app_id": self._app_id(),
                "strategy_id": strategy.id,
                "catalog_plan_id": plan.id,
                "purchase_type": item["purchase_type"],
                "discount_rate": item["discount_rate"],
                "execution_price_fen": execution,
                "margin_rate": item["margin_rate"],
                "allowed_cost_yuan": allowed_cost,
                "credits_per_cost_yuan": rate,
                "remark": item.get("remark"),
                "updated_id": self.auth.user.id,
                "is_deleted": False,
            }
            existing = existing_items.get((plan.id, item["purchase_type"]))
            if existing:
                for key, value in item_values.items():
                    setattr(existing, key, value)
            else:
                self.db.add(AppPricingStrategyItemModel(**item_values, created_id=self.auth.user.id))
        await self.db.flush()
        if data.status == "active":
            await self._activate(strategy)
        return await self._strategy_out(strategy)

    async def strategies(self) -> list[PricingStrategyOutSchema]:
        rows = list(
            (
                await self.db.scalars(
                    select(AppPricingStrategyModel)
                    .options(selectinload(AppPricingStrategyModel.items))
                    .where(AppPricingStrategyModel.app_id == self._app_id(), AppPricingStrategyModel.is_deleted == False)
                    .order_by(AppPricingStrategyModel.id.desc())
                )
            ).all()
        )
        return [await self._strategy_out(row) for row in rows]

    async def _strategy_out(self, strategy: AppPricingStrategyModel) -> PricingStrategyOutSchema:
        # Newly-created strategies have not gone through a selectinload query yet.
        # Refresh the relationship explicitly so Pydantic never triggers async lazy IO.
        await self.db.flush()
        await self.db.refresh(strategy, attribute_names=["items"])
        output = PricingStrategyOutSchema.model_validate(strategy)
        output.items = [PricingStrategyItemOutSchema.model_validate(item) for item in strategy.items if not item.is_deleted]
        return output

    async def _activate(self, strategy: AppPricingStrategyModel) -> None:
        item_count = int(
            await self.db.scalar(
                select(func.count()).select_from(AppPricingStrategyItemModel).where(AppPricingStrategyItemModel.strategy_id == strategy.id, AppPricingStrategyItemModel.is_deleted == False)
            )
            or 0
        )
        if not item_count:
            raise CustomException(msg="策略至少需要一个刊例项")
        plans = list(
            (
                await self.db.scalars(
                    select(AppCatalogPlanModel)
                    .join(AppPricingStrategyItemModel, AppPricingStrategyItemModel.catalog_plan_id == AppCatalogPlanModel.id)
                    .where(
                        AppPricingStrategyItemModel.strategy_id == strategy.id,
                        AppPricingStrategyItemModel.is_deleted == False,
                        AppCatalogPlanModel.status == "on_sale",
                        AppCatalogPlanModel.is_deleted == False,
                    )
                )
            ).all()
        )
        if len(plans) != item_count:
            raise CustomException(msg="策略中的所有刊例必须已上架")
        await self.db.execute(
            update(AppPricingStrategyModel)
            .where(AppPricingStrategyModel.app_id == self._app_id(), AppPricingStrategyModel.id != strategy.id, AppPricingStrategyModel.status == "active", AppPricingStrategyModel.is_deleted == False)
            .values(status="inactive")
        )
        strategy.status = "active"
        strategy.published_at = datetime.now(UTC)

    async def set_strategy_status(self, strategy_id: int, data: PricingStrategyStatusSchema) -> PricingStrategyOutSchema:
        await get_model_policy(self.db, self._app_id(), lock=True)
        strategy = await self._get_strategy(strategy_id, lock=True)
        if data.status == "active":
            await self._activate(strategy)
        else:
            strategy.status = data.status
        strategy.updated_id = self.auth.user.id
        await self.db.flush()
        return await self._strategy_out(strategy)


class CreditService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def account(self, app_id: int, user_id: int, *, lock: bool = False) -> CreditAccountModel:
        stmt = select(CreditAccountModel).where(
            CreditAccountModel.app_id == app_id,
            CreditAccountModel.user_id == user_id,
            CreditAccountModel.is_deleted == False,
        )
        if lock:
            stmt = stmt.with_for_update()
        account = await self.db.scalar(stmt)
        if not account:
            account = CreditAccountModel(app_id=app_id, user_id=user_id, status="active")
            self.db.add(account)
            await self.db.flush()
        return account

    async def account_out(self, app_id: int, user_id: int) -> CreditAccountOutSchema:
        await self.release_due(app_id=app_id, user_id=user_id)
        account = await self.account(app_id, user_id, lock=True)
        await suppress_legacy_upgrade_grants(self.db, account, now=datetime.now(UTC))
        return CreditAccountOutSchema.model_validate(account, from_attributes=True)

    async def release_due(self, *, app_id: int | None = None, user_id: int | None = None) -> int:
        """幂等释放到期积分并回收过期余额；查询和调用前也会执行，避免依赖定时器可用性。"""
        now = datetime.now(UTC)
        pending_stmt = select(CreditGrantModel).where(
            CreditGrantModel.status == "pending",
            CreditGrantModel.release_at <= now,
            CreditGrantModel.is_deleted == False,
        )
        expired_stmt = select(CreditGrantModel).where(
            CreditGrantModel.status == "released",
            CreditGrantModel.available > 0,
            CreditGrantModel.expires_at <= now,
            CreditGrantModel.is_deleted == False,
        )
        stale_stmt = select(CreditReservationModel).where(
            CreditReservationModel.status == "reserved",
            CreditReservationModel.created_time <= now - timedelta(seconds=RESERVATION_STALE_SECONDS),
            CreditReservationModel.is_deleted == False,
        )
        if app_id is not None:
            pending_stmt = pending_stmt.where(CreditGrantModel.app_id == app_id)
            expired_stmt = expired_stmt.where(CreditGrantModel.app_id == app_id)
            stale_stmt = stale_stmt.where(CreditReservationModel.app_id == app_id)
        if user_id is not None:
            pending_stmt = pending_stmt.where(CreditGrantModel.user_id == user_id)
            expired_stmt = expired_stmt.where(CreditGrantModel.user_id == user_id)
            stale_stmt = stale_stmt.where(CreditReservationModel.user_id == user_id)
        # All financial writers take account locks before reservation/grant locks.
        # Snapshot IDs first so newly inserted grants are handled by the next pass.
        pending_keys = (await self.db.execute(pending_stmt.with_only_columns(CreditGrantModel.id, CreditGrantModel.app_id, CreditGrantModel.user_id))).all()
        stale_keys = (await self.db.execute(stale_stmt.with_only_columns(CreditReservationModel.id, CreditReservationModel.app_id, CreditReservationModel.user_id))).all()
        expired_keys = (await self.db.execute(expired_stmt.with_only_columns(CreditGrantModel.id, CreditGrantModel.app_id, CreditGrantModel.user_id))).all()
        for scope, owner in sorted({(r[1], r[2]) for r in [*pending_keys, *stale_keys, *expired_keys]}):
            locked_account = await self.account(scope, owner, lock=True)
            await suppress_legacy_upgrade_grants(self.db, locked_account, now=now)
        pending = list((await self.db.scalars(pending_stmt.where(CreditGrantModel.id.in_([r[0] for r in pending_keys])).with_for_update().execution_options(populate_existing=True))).all())
        stale = list((await self.db.scalars(stale_stmt.where(CreditReservationModel.id.in_([r[0] for r in stale_keys])).with_for_update().execution_options(populate_existing=True))).all())
        expired = list((await self.db.scalars(expired_stmt.where(CreditGrantModel.id.in_([r[0] for r in expired_keys])).with_for_update().execution_options(populate_existing=True))).all())
        for grant in pending:
            account = await self.account(grant.app_id, grant.user_id, lock=True)
            expires_at = grant.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at <= now:
                grant.status = "expired"
                account.pending = max(0, account.pending - grant.amount)
                continue
            grant.status = "released"
            grant.available = grant.amount
            account.pending = max(0, account.pending - grant.amount)
            account.available += grant.amount
            account.total_granted += grant.amount
            self.db.add(
                CreditLedgerModel(
                    app_id=grant.app_id,
                    user_id=grant.user_id,
                    grant_id=grant.id,
                    entry_type="scheduled_release",
                    amount=grant.amount,
                    balance_after=account.available,
                    idempotency_key=f"release:{grant.app_id}:{grant.id}",
                    reference_type=grant.source_type,
                    reference_id=str(grant.source_id),
                    status="posted",
                )
            )
            await notify_credit_grant(self.db, grant)
        for reservation in stale:
            account = await self.account(reservation.app_id, reservation.user_id, lock=True)
            refunded = 0
            for allocation in reservation.allocations:
                grant = await self.db.scalar(
                    select(CreditGrantModel)
                    .where(
                        CreditGrantModel.id == allocation["grant_id"],
                        CreditGrantModel.app_id == reservation.app_id,
                        CreditGrantModel.user_id == reservation.user_id,
                    )
                    .with_for_update()
                )
                if not grant:
                    continue
                amount = min(int(allocation["amount"]), grant.reserved)
                grant.reserved -= amount
                expires_at = grant.expires_at
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=UTC)
                if grant.status == "released" and expires_at > now:
                    grant.available += amount
                    refunded += amount
                elif grant.available <= 0 and grant.reserved <= 0:
                    grant.status = "expired"
            account.reserved = max(0, account.reserved - reservation.estimated)
            account.available += refunded
            reservation.actual = 0
            reservation.status = "cancelled"
            reservation.settled_at = now
            self.db.add(
                CreditLedgerModel(
                    app_id=reservation.app_id,
                    user_id=reservation.user_id,
                    entry_type="reservation_release",
                    amount=refunded,
                    balance_after=account.available,
                    idempotency_key=f"cancel:{reservation.app_id}:{reservation.request_id}",
                    reference_type="model_request",
                    reference_id=reservation.request_id,
                    reason="模型请求超时，释放预占积分",
                    status="posted",
                )
            )
        for grant in expired:
            account = await self.account(grant.app_id, grant.user_id, lock=True)
            amount = grant.available
            grant.available = 0
            grant.status = "expired"
            account.available = max(0, account.available - amount)
            self.db.add(
                CreditLedgerModel(
                    app_id=grant.app_id,
                    user_id=grant.user_id,
                    grant_id=grant.id,
                    entry_type="expiration",
                    amount=-amount,
                    balance_after=account.available,
                    idempotency_key=f"expire:{grant.app_id}:{grant.id}",
                    reference_type=grant.source_type,
                    reference_id=str(grant.source_id),
                    status="posted",
                )
            )
        if pending or stale or expired:
            await self.db.flush()
        return len(pending) + len(stale) + len(expired)

    async def adjust(
        self,
        app_id: int,
        user_id: int,
        amount: int,
        reason: str,
        operator_id: int,
        expires_in_days: int = 365,
        idempotency_key: str | None = None,
    ) -> CreditAccountOutSchema:
        await require_platform_model(self.db, app_id, user_id=user_id, lock=True)
        if amount == 0:
            raise CustomException(msg="调整积分不能为0")
        await self.release_due(app_id=app_id, user_id=user_id)
        account = await self.account(app_id, user_id, lock=True)
        key = f"manual:{app_id}:{user_id}:{idempotency_key or uuid4().hex}"
        prior = await self.db.scalar(select(CreditLedgerModel).where(CreditLedgerModel.app_id == app_id, CreditLedgerModel.idempotency_key == key))
        if prior:
            if prior.amount != amount or prior.reason != reason or prior.operator_id != operator_id or prior.reference_type != "manual_adjustment" or prior.reference_id != str(expires_in_days):
                raise CustomException(msg="该请求编号已用于不同的积分调整", status_code=409)
            return CreditAccountOutSchema.model_validate(account, from_attributes=True)
        grant: CreditGrantModel | None = None
        if amount > 0:
            account.available += amount
            account.total_granted += amount
            entry_type = "manual_grant"
        else:
            consume = -amount
            if account.available < consume:
                raise CustomException(msg="可用积分不足，不能扣减")
            await self._consume_fifo(app_id, user_id, consume)
            account.available -= consume
            account.total_consumed += consume
            entry_type = "manual_deduct"
        ledger = CreditLedgerModel(
            app_id=app_id,
            user_id=user_id,
            grant_id=None,
            entry_type=entry_type,
            amount=amount,
            balance_after=account.available,
            idempotency_key=key,
            reference_type="manual_adjustment",
            reference_id=str(expires_in_days),
            reason=reason,
            operator_id=operator_id,
            status="posted",
        )
        self.db.add(ledger)
        await self.db.flush()
        if amount > 0:
            rate = await self.default_credits_per_cost_yuan(app_id, user_id)
            grant = CreditGrantModel(
                app_id=app_id,
                user_id=user_id,
                source_type="manual",
                source_id=ledger.id,
                release_index=0,
                amount=amount,
                available=amount,
                release_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(days=expires_in_days),
                status="released",
                account_type="manual",
                credits_per_cost_yuan=rate,
                pricing_snapshot={"source": "manual", "credits_per_cost_yuan": rate},
            )
            self.db.add(grant)
            await self.db.flush()
            ledger.grant_id = grant.id
            await notify_credit_grant(self.db, grant, reason=reason)
        await self.db.flush()
        return CreditAccountOutSchema.model_validate(account, from_attributes=True)

    async def default_credits_per_cost_yuan(self, app_id: int, user_id: int | None = None) -> float:
        if user_id:
            cycle = await self.db.scalar(
                select(SubscriptionCycleModel)
                .where(
                    SubscriptionCycleModel.app_id == app_id,
                    SubscriptionCycleModel.user_id == user_id,
                    SubscriptionCycleModel.status == "active",
                    SubscriptionCycleModel.is_deleted == False,
                )
                .order_by(SubscriptionCycleModel.id.desc())
            )
            if cycle and cycle.plan_snapshot.get("credits_per_cost_yuan"):
                return float(cycle.plan_snapshot["credits_per_cost_yuan"])
        return 2500.0

    async def _account_priority(self) -> list[str]:
        version = await self.db.scalar(
            select(PricingStandardVersionModel)
            .where(
                PricingStandardVersionModel.status == "published",
                PricingStandardVersionModel.is_deleted == False,
            )
            .order_by(PricingStandardVersionModel.id.desc())
        )
        return list(version.account_priority) if version and version.account_priority else ["activity_reward", "current_cycle", "monthly_reserve", "traffic_pack", "enterprise_pool", "manual"]

    async def _available_grants(self, app_id: int, user_id: int, *, lock: bool = False) -> list[CreditGrantModel]:
        priority = await self._account_priority()
        ordering = case({name: index for index, name in enumerate(priority)}, value=CreditGrantModel.account_type, else_=len(priority))
        stmt = (
            select(CreditGrantModel)
            .where(
                CreditGrantModel.app_id == app_id,
                CreditGrantModel.user_id == user_id,
                CreditGrantModel.status == "released",
                CreditGrantModel.available > 0,
                CreditGrantModel.expires_at > datetime.now(UTC),
                CreditGrantModel.is_deleted == False,
            )
            .order_by(ordering.asc(), CreditGrantModel.expires_at.asc(), CreditGrantModel.id.asc())
        )
        if lock:
            stmt = stmt.with_for_update()
        return list((await self.db.scalars(stmt)).all())

    async def cost_capacity_yuan(self, app_id: int, user_id: int) -> Decimal:
        await self.release_due(app_id=app_id, user_id=user_id)
        grants = await self._available_grants(app_id, user_id)
        return sum(
            (Decimal(grant.available) / Decimal(str(grant.credits_per_cost_yuan or 2500)) for grant in grants),
            Decimal(0),
        )

    async def estimate_credits_for_cost(self, app_id: int, user_id: int, cost_yuan: Decimal) -> int:
        if cost_yuan <= 0:
            return 0
        remaining = cost_yuan
        credits = 0
        for grant in await self._available_grants(app_id, user_id):
            rate = Decimal(str(grant.credits_per_cost_yuan or 2500))
            capacity = Decimal(grant.available) / rate
            used_cost = min(remaining, capacity)
            credits += min(grant.available, math.ceil(used_cost * rate))
            remaining -= used_cost
            if remaining <= Decimal("0.000000001"):
                return credits
        raise CustomException(msg="算力积分不足", status_code=402)

    async def reserve_cost(
        self,
        app_id: int,
        user_id: int,
        request_id: str,
        estimated_cost_yuan: Decimal,
    ) -> CreditReservationModel:
        await require_platform_model(self.db, app_id, user_id=user_id, lock=True)
        if estimated_cost_yuan <= 0:
            raise CustomException(msg="预占模型成本必须大于0")
        await self.release_due(app_id=app_id, user_id=user_id)
        existing = await self.db.scalar(select(CreditReservationModel.id).where(CreditReservationModel.app_id == app_id, CreditReservationModel.request_id == request_id))
        if existing:
            raise CustomException(msg="request_id 已使用，请勿重复提交", status_code=409)
        account = await self.account(app_id, user_id, lock=True)
        grants = await self._available_grants(app_id, user_id, lock=True)
        remaining_cost = estimated_cost_yuan
        allocations: list[dict] = []
        total_credits = 0
        for grant in grants:
            rate = Decimal(str(grant.credits_per_cost_yuan or 2500))
            capacity = Decimal(grant.available) / rate
            cost_used = min(remaining_cost, capacity)
            amount = min(grant.available, math.ceil(cost_used * rate))
            if amount:
                grant.available -= amount
                grant.reserved += amount
                total_credits += amount
                allocations.append(
                    {
                        "grant_id": grant.id,
                        "amount": amount,
                        "credits_per_cost_yuan": str(rate),
                        "cost_yuan": str(cost_used),
                        "account_type": grant.account_type,
                    }
                )
                remaining_cost -= cost_used
            if remaining_cost <= Decimal("0.000000001"):
                break
        if remaining_cost > Decimal("0.000000001"):
            raise CustomException(msg="算力积分不足", status_code=402)
        account.available -= total_credits
        account.reserved += total_credits
        reservation = CreditReservationModel(
            app_id=app_id,
            user_id=user_id,
            request_id=request_id,
            estimated=total_credits,
            estimated_cost_yuan=estimated_cost_yuan,
            allocations=allocations,
            status="reserved",
        )
        self.db.add(reservation)
        await self.db.flush()
        return reservation

    @staticmethod
    def _return_unused_reserved(grant: CreditGrantModel, amount: int) -> int:
        """Only a still-valid grant may receive unused reservation credits."""
        expires_at = grant.expires_at.replace(tzinfo=UTC) if grant.expires_at.tzinfo is None else grant.expires_at
        if grant.status != "released" or expires_at <= datetime.now(UTC):
            return 0
        grant.available += amount
        return amount

    async def settle_cost(
        self,
        app_id: int,
        user_id: int,
        request_id: str,
        actual_cost_yuan: Decimal,
    ) -> CreditReservationModel:
        if actual_cost_yuan < 0:
            raise CustomException(msg="实际模型成本不能小于0")
        await self.account(app_id, user_id, lock=True)
        reservation = await self.db.scalar(
            select(CreditReservationModel)
            .where(
                CreditReservationModel.app_id == app_id,
                CreditReservationModel.user_id == user_id,
                CreditReservationModel.request_id == request_id,
            )
            .with_for_update()
        )
        if not reservation:
            raise CustomException(msg="积分预占不存在")
        if reservation.status in ("settled", "cancelled"):
            return reservation
        estimated_cost = Decimal(str(reservation.estimated_cost_yuan or 0))
        if actual_cost_yuan > estimated_cost + Decimal("0.00000001"):
            actual_cost_yuan = estimated_cost
        account = await self.account(app_id, user_id, lock=True)
        remaining_cost = actual_cost_yuan
        consumed_total = 0
        refunded = 0
        for allocation in reservation.allocations:
            grant = await self.db.scalar(
                select(CreditGrantModel).where(CreditGrantModel.id == allocation["grant_id"], CreditGrantModel.app_id == app_id, CreditGrantModel.user_id == user_id).with_for_update()
            )
            if not grant:
                raise CustomException(msg="积分批次不存在")
            allocated = int(allocation["amount"])
            rate = Decimal(str(allocation.get("credits_per_cost_yuan") or grant.credits_per_cost_yuan or 2500))
            reserved_cost = Decimal(str(allocation.get("cost_yuan") or (Decimal(allocated) / rate)))
            cost_used = min(remaining_cost, reserved_cost)
            consumed = min(allocated, math.ceil(cost_used * rate)) if cost_used > 0 else 0
            refund = allocated - consumed
            grant.reserved = max(0, grant.reserved - allocated)
            refund = self._return_unused_reserved(grant, refund)
            consumed_total += consumed
            refunded += refund
            remaining_cost -= cost_used
        account.reserved = max(0, account.reserved - reservation.estimated)
        account.available += refunded
        account.total_consumed += consumed_total
        reservation.actual = consumed_total
        reservation.actual_cost_yuan = actual_cost_yuan
        reservation.status = "settled"
        reservation.settled_at = datetime.now(UTC)
        self.db.add(
            CreditLedgerModel(
                app_id=app_id,
                user_id=user_id,
                entry_type="model_settlement",
                amount=-consumed_total,
                balance_after=account.available,
                idempotency_key=f"settle:{app_id}:{request_id}",
                reference_type="model_request",
                reference_id=request_id,
                reason=f"实际模型成本 ¥{actual_cost_yuan}",
                status="posted",
            )
        )
        await self.db.flush()
        return reservation

    async def reserve(self, app_id: int, user_id: int, request_id: str, estimated: int) -> CreditReservationModel:
        await require_platform_model(self.db, app_id, user_id=user_id, lock=True)
        if estimated <= 0:
            raise CustomException(msg="预占积分必须大于0")
        await self.release_due(app_id=app_id, user_id=user_id)
        existing = await self.db.scalar(
            select(CreditReservationModel).where(
                CreditReservationModel.app_id == app_id,
                CreditReservationModel.request_id == request_id,
            )
        )
        if existing:
            raise CustomException(msg="request_id 已使用，请勿重复提交", status_code=409)
        account = await self.account(app_id, user_id, lock=True)
        if account.status != "active" or account.available < estimated:
            raise CustomException(msg="算力积分不足", status_code=402)
        grants = await self._available_grants(app_id, user_id, lock=True)
        remaining = estimated
        allocations: list[dict] = []
        for grant in grants:
            amount = min(grant.available, remaining)
            if amount:
                grant.available -= amount
                grant.reserved += amount
                allocations.append({"grant_id": grant.id, "amount": amount})
                remaining -= amount
            if remaining == 0:
                break
        if remaining:
            raise CustomException(msg="有效积分批次不足", status_code=402)
        account.available -= estimated
        account.reserved += estimated
        reservation = CreditReservationModel(
            app_id=app_id,
            user_id=user_id,
            request_id=request_id,
            estimated=estimated,
            allocations=allocations,
            status="reserved",
        )
        self.db.add(reservation)
        await self.db.flush()
        return reservation

    async def settle(self, app_id: int, user_id: int, request_id: str, actual: int) -> CreditReservationModel:
        if actual < 0:
            raise CustomException(msg="实际消耗不能小于0")
        await self.account(app_id, user_id, lock=True)
        reservation = await self.db.scalar(
            select(CreditReservationModel)
            .where(
                CreditReservationModel.app_id == app_id,
                CreditReservationModel.user_id == user_id,
                CreditReservationModel.request_id == request_id,
            )
            .with_for_update()
        )
        if not reservation:
            raise CustomException(msg="积分预占不存在")
        if reservation.status in ("settled", "cancelled"):
            return reservation
        if actual > reservation.estimated:
            raise CustomException(msg="实际消耗不能超过预占积分")
        account = await self.account(app_id, user_id, lock=True)
        remaining_actual = actual
        refunded = 0
        for allocation in reservation.allocations:
            grant = await self.db.scalar(
                select(CreditGrantModel)
                .where(
                    CreditGrantModel.id == allocation["grant_id"],
                    CreditGrantModel.app_id == app_id,
                    CreditGrantModel.user_id == user_id,
                )
                .with_for_update()
            )
            if not grant:
                raise CustomException(msg="积分批次不存在")
            allocated = int(allocation["amount"])
            consumed = min(allocated, remaining_actual)
            refund = allocated - consumed
            grant.reserved -= allocated
            refund = self._return_unused_reserved(grant, refund)
            remaining_actual -= consumed
            refunded += refund
        account.reserved -= reservation.estimated
        account.available += refunded
        account.total_consumed += actual
        reservation.actual = actual
        reservation.status = "settled"
        reservation.settled_at = datetime.now(UTC)
        self.db.add(
            CreditLedgerModel(
                app_id=app_id,
                user_id=user_id,
                entry_type="model_settlement",
                amount=-actual,
                balance_after=account.available,
                idempotency_key=f"settle:{app_id}:{request_id}",
                reference_type="model_request",
                reference_id=request_id,
                status="posted",
            )
        )
        await self.db.flush()
        return reservation

    async def _consume_fifo(self, app_id: int, user_id: int, amount: int) -> None:
        remaining = amount
        grants = await self._available_grants(app_id, user_id, lock=True)
        for grant in grants:
            used = min(grant.available, remaining)
            grant.available -= used
            remaining -= used
            if remaining == 0:
                return
        if remaining:
            raise CustomException(msg="有效积分批次不足")


class SubscriptionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def expire_due(self, app_id: int) -> int:
        await self.db.flush()
        now = datetime.now(UTC)
        from .subscription_periods import apply_subscription_projection, project_subscription

        due = list(
            await self.db.scalars(
                select(SubscriptionModel)
                .where(
                    SubscriptionModel.app_id == app_id,
                    SubscriptionModel.status.in_(("active", "expired")),
                    or_(
                        SubscriptionModel.status == "active",
                        select(SubscriptionCycleModel.id)
                        .where(
                            SubscriptionCycleModel.subscription_id == SubscriptionModel.id,
                            SubscriptionCycleModel.app_id == app_id,
                            SubscriptionCycleModel.status == "active",
                            SubscriptionCycleModel.ends_at > now,
                            SubscriptionCycleModel.is_deleted == False,
                        )
                        .exists(),
                    ),
                    or_(SubscriptionModel.current_period_end <= now, SubscriptionModel.current_period_start > now),
                    SubscriptionModel.is_deleted == False,
                )
                .with_for_update()
            )
        )
        for subscription in due:
            projection = await project_subscription(self.db, subscription, now=now)
            if projection["status"] == "cancelled":
                projection["status"] = "expired"
            apply_subscription_projection(subscription, projection)
        await self.db.flush()
        await self.db.execute(
            update(SubscriptionCycleModel)
            .where(
                SubscriptionCycleModel.app_id == app_id,
                SubscriptionCycleModel.status == "active",
                SubscriptionCycleModel.ends_at <= now,
                SubscriptionCycleModel.is_deleted == False,
            )
            .values(status="expired", updated_time=now)
            .execution_options(synchronize_session="fetch")
        )
        return len(due)

    async def list_admin(self, app_id: int, *, entitlement_kind: str | None = None) -> list[SubscriptionAdminOutSchema]:
        await self.expire_due(app_id)
        rows = (
            await self.db.execute(
                select(SubscriptionModel, ClientUserModel, AppCatalogPlanModel, CreditAccountModel)
                .join(
                    ClientUserModel,
                    (ClientUserModel.id == SubscriptionModel.user_id) & (ClientUserModel.app_id == SubscriptionModel.app_id),
                )
                .join(AppCatalogPlanModel, AppCatalogPlanModel.id == SubscriptionModel.catalog_plan_id)
                .outerjoin(
                    CreditAccountModel,
                    (CreditAccountModel.user_id == SubscriptionModel.user_id) & (CreditAccountModel.app_id == SubscriptionModel.app_id) & (CreditAccountModel.is_deleted == False),
                )
                .where(SubscriptionModel.app_id == app_id, SubscriptionModel.is_deleted == False, *([SubscriptionModel.entitlement_kind == entitlement_kind] if entitlement_kind else []))
                .order_by(SubscriptionModel.id.desc())
                .execution_options(populate_existing=True)
            )
        ).all()
        return [
            SubscriptionAdminOutSchema(
                id=subscription.id,
                uuid=subscription.uuid,
                created_time=subscription.created_time,
                updated_time=subscription.updated_time,
                app_id=subscription.app_id,
                user_id=subscription.user_id,
                username=user.username,
                display_name=user.display_name,
                catalog_plan_id=subscription.catalog_plan_id,
                plan_name=plan.name,
                entitlement_kind=subscription.entitlement_kind,
                status=subscription.status,
                auto_renew=subscription.auto_renew,
                current_period_start=subscription.current_period_start,
                current_period_end=subscription.current_period_end,
                next_renewal_at=subscription.next_renewal_at,
                available_credits=account.available if account else 0,
                pending_credits=account.pending if account else 0,
            )
            for subscription, user, plan, account in rows
        ]

    async def set_status(
        self,
        app_id: int,
        subscription_id: int,
        data: SubscriptionStatusSchema,
    ) -> SubscriptionAdminOutSchema:
        subscription = await self.db.scalar(
            select(SubscriptionModel).where(
                SubscriptionModel.id == subscription_id,
                SubscriptionModel.app_id == app_id,
                SubscriptionModel.is_deleted == False,
            )
        )
        if not subscription:
            raise CustomException(msg="订阅不存在", status_code=404)
        period_end = subscription.current_period_end
        if period_end.tzinfo is None:
            period_end = period_end.replace(tzinfo=UTC)
        if data.status == "active" and period_end <= datetime.now(UTC):
            raise CustomException(msg="订阅周期已结束，不能修正为有效")
        subscription.status = data.status
        if data.status != "active":
            subscription.auto_renew = False
            subscription.next_renewal_at = None
        await self.db.flush()
        rows = await self.list_admin(app_id)
        return next(item for item in rows if item.id == subscription_id)

    async def current_for_client(
        self,
        app_id: int,
        user_id: int,
    ) -> ClientSubscriptionOutSchema | None:
        await self.expire_due(app_id)
        row = (
            await self.db.execute(
                select(SubscriptionModel, AppCatalogPlanModel)
                .join(
                    AppCatalogPlanModel,
                    (AppCatalogPlanModel.id == SubscriptionModel.catalog_plan_id) & (AppCatalogPlanModel.app_id == SubscriptionModel.app_id),
                )
                .where(
                    SubscriptionModel.app_id == app_id,
                    SubscriptionModel.user_id == user_id,
                    SubscriptionModel.is_deleted == False,
                )
                .execution_options(populate_existing=True)
            )
        ).first()
        if not row:
            return None
        subscription, plan = row
        return ClientSubscriptionOutSchema(
            id=subscription.id,
            uuid=subscription.uuid,
            created_time=subscription.created_time,
            updated_time=subscription.updated_time,
            catalog_plan_id=subscription.catalog_plan_id,
            plan_name=plan.name,
            entitlement_kind=subscription.entitlement_kind,
            tier_code=plan.tier_code,
            tier_order=plan.tier_order,
            status=subscription.status,
            current_period_start=subscription.current_period_start,
            current_period_end=subscription.current_period_end,
            auto_renew=subscription.auto_renew,
        )

    async def ledger_for_client(
        self,
        app_id: int,
        user_id: int,
    ) -> list[ClientCreditLedgerOutSchema]:
        rows = list(
            (
                await self.db.scalars(
                    select(CreditLedgerModel)
                    .where(
                        CreditLedgerModel.app_id == app_id,
                        CreditLedgerModel.user_id == user_id,
                        CreditLedgerModel.is_deleted == False,
                    )
                    .order_by(CreditLedgerModel.id.desc())
                    .limit(100)
                )
            ).all()
        )
        return [ClientCreditLedgerOutSchema.model_validate(row) for row in rows]

    async def activate_paid_order(
        self,
        *,
        app_id: int,
        user_id: int,
        order_id: int,
        catalog_plan_id: int,
        plan_snapshot: dict,
        auto_renew: bool,
    ) -> SubscriptionModel | None:
        from app.api.v1.module_client.app.model_policy import order_matches_model_policy

        if not await order_matches_model_policy(self.db, app_id, plan_snapshot):
            raise CustomException(msg="订单权益与当前模型模式不一致，请在财务中心核对或退款", status_code=409)
        app = await get_model_policy(self.db, app_id, lock=True)
        user = await billing_user(self.db, app, user_id, lock=True)
        target = plan_snapshot.get("entitlement_kind", "credits")
        mode = current_mode(app, user)
        if mode is not None and mode != target:
            raise CustomException(msg="请通过模式切换确认流程处理跨模式权益", status_code=409)
        if user.active_billing_mode is None:
            user.active_billing_mode = target
            if mode != target:
                user.mode_version += 1
            await self.db.flush()
        if plan_snapshot.get("entitlement_kind") == "duration":
            from .duration import activate_duration_order

            return await activate_duration_order(self.db, app_id=app_id, user_id=user_id, order_id=order_id, catalog_plan_id=catalog_plan_id, snapshot=plan_snapshot)
        now = datetime.now(UTC)
        plan_type = plan_snapshot.get("plan_type", "subscription")
        account = await CreditService(self.db).account(app_id, user_id, lock=True)
        existing_cycle = await self.db.scalar(
            select(SubscriptionCycleModel).where(
                SubscriptionCycleModel.app_id == app_id,
                SubscriptionCycleModel.user_id == user_id,
                SubscriptionCycleModel.order_id == order_id,
            )
        )
        if existing_cycle:
            return await self.db.get(SubscriptionModel, existing_cycle.subscription_id)
        if await self.db.scalar(
            select(CreditGrantModel.id)
            .where(
                CreditGrantModel.app_id == app_id,
                CreditGrantModel.user_id == user_id,
                CreditGrantModel.source_type == "credit_pack_order",
                CreditGrantModel.source_id == order_id,
            )
            .limit(1)
        ):
            return None
        if plan_type == "credit_pack":
            account = await CreditService(self.db).account(app_id, user_id, lock=True)
            for index, item in enumerate(plan_snapshot.get("release_plan") or [{"offset_day": 0, "amount": plan_snapshot["total_credits"], "account_type": "traffic_pack"}]):
                amount = int(item["amount"])
                release_at = now + timedelta(days=int(item.get("offset_day") or 0))
                released = release_at <= now
                grant = CreditGrantModel(
                    app_id=app_id,
                    user_id=user_id,
                    source_type="credit_pack_order",
                    source_id=order_id,
                    release_index=index,
                    account_type="traffic_pack",
                    amount=amount,
                    available=amount if released else 0,
                    release_at=release_at,
                    expires_at=release_at + timedelta(days=int(plan_snapshot["credit_valid_days"])),
                    status="released" if released else "pending",
                    credits_per_cost_yuan=float(plan_snapshot.get("credits_per_cost_yuan") or 2500),
                    pricing_snapshot=plan_snapshot.get("pricing_snapshot") or {},
                )
                self.db.add(grant)
                await self.db.flush()
                if released:
                    account.available += amount
                    account.total_granted += amount
                    self.db.add(
                        CreditLedgerModel(
                            app_id=app_id,
                            user_id=user_id,
                            grant_id=grant.id,
                            entry_type="credit_pack_release",
                            amount=amount,
                            balance_after=account.available,
                            idempotency_key=f"release:{app_id}:{grant.id}",
                            reference_type="payment_order",
                            reference_id=str(order_id),
                            status="posted",
                        )
                    )
                    await notify_credit_grant(self.db, grant)
                else:
                    account.pending += amount
            await self.db.flush()
            return None
        subscription = await self.db.scalar(
            select(SubscriptionModel)
            .where(
                SubscriptionModel.app_id == app_id,
                SubscriptionModel.user_id == user_id,
                SubscriptionModel.is_deleted == False,
            )
            .with_for_update()
        )
        if subscription:
            current_period_end = subscription.current_period_end
            if current_period_end.tzinfo is None:
                current_period_end = current_period_end.replace(tzinfo=UTC)
            # Cross-plan purchases take effect now. Only a same-plan renewal
            # appends to the existing paid period; earlier orders keep their dates.
            same_plan = subscription.catalog_plan_id == catalog_plan_id and subscription.status == "active"
            start = max(now, current_period_end) if same_plan else now
            subscription.entitlement_kind = "credits"
            subscription.catalog_plan_id = catalog_plan_id
            subscription.status = "active"
            subscription.auto_renew = auto_renew
            subscription.current_period_start = start
            subscription.current_period_end = start + timedelta(days=int(plan_snapshot["benefit_period_days"]))
        else:
            start = now
            subscription = SubscriptionModel(
                app_id=app_id,
                user_id=user_id,
                catalog_plan_id=catalog_plan_id,
                status="active",
                auto_renew=auto_renew,
                current_period_start=start,
                current_period_end=start + timedelta(days=int(plan_snapshot["benefit_period_days"])),
            )
            self.db.add(subscription)
        subscription.next_renewal_at = subscription.current_period_end if auto_renew else None
        await self.db.flush()
        cycle_count = await self.db.scalar(
            select(func.count())
            .select_from(SubscriptionCycleModel)
            .where(
                SubscriptionCycleModel.app_id == app_id,
                SubscriptionCycleModel.subscription_id == subscription.id,
            )
        )
        cycle = SubscriptionCycleModel(
            app_id=app_id,
            subscription_id=subscription.id,
            user_id=user_id,
            order_id=order_id,
            cycle_no=int(cycle_count or 0) + 1,
            starts_at=start,
            ends_at=subscription.current_period_end,
            plan_snapshot=plan_snapshot,
            status="active",
        )
        self.db.add(cycle)
        await self.db.flush()
        account = await CreditService(self.db).account(app_id, user_id, lock=True)
        if start <= now:
            await supersede_pending_grants(self.db, account, new_cycle=cycle, now=now)
        for index, item in enumerate(plan_snapshot.get("release_plan") or []):
            amount = int(item["amount"])
            release_at = start + timedelta(days=int(item["offset_day"]))
            released = release_at <= now
            grant = CreditGrantModel(
                app_id=app_id,
                user_id=user_id,
                source_type="subscription_cycle",
                source_id=cycle.id,
                release_index=index,
                amount=amount,
                available=amount if released else 0,
                release_at=release_at,
                expires_at=release_at + timedelta(days=int(plan_snapshot["credit_valid_days"])),
                status="released" if released else "pending",
                account_type=str(item.get("account_type") or "current_cycle"),
                credits_per_cost_yuan=float(plan_snapshot.get("credits_per_cost_yuan") or 2500),
                pricing_snapshot=plan_snapshot.get("pricing_snapshot") or {},
            )
            self.db.add(grant)
            await self.db.flush()
            if released:
                account.available += amount
                account.total_granted += amount
                self.db.add(
                    CreditLedgerModel(
                        app_id=app_id,
                        user_id=user_id,
                        grant_id=grant.id,
                        entry_type="subscription_release",
                        amount=amount,
                        balance_after=account.available,
                        idempotency_key=f"release:{app_id}:{grant.id}",
                        reference_type="subscription_cycle",
                        reference_id=str(cycle.id),
                        status="posted",
                    )
                )
                await notify_credit_grant(self.db, grant)
            else:
                account.pending += amount
        from .subscription_periods import apply_subscription_projection, project_subscription

        await self.db.flush()
        apply_subscription_projection(subscription, await project_subscription(self.db, subscription, now=now))
        await self.db.flush()
        return subscription


async def run_billing_maintenance() -> None:
    """Release/expire benefits per explicit client scope; safe to replay after downtime."""
    async with async_db_session() as db, db.begin():
        app_ids = list((await db.scalars(select(ClientAppModel.id).where(ClientAppModel.is_deleted == False))).all())
        for app_id in app_ids:
            await CreditService(db).release_due(app_id=app_id)
            await SubscriptionService(db).expire_due(app_id)
