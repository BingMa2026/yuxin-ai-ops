from datetime import UTC, datetime, timedelta

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.module_billing.model import (
    AppCatalogPlanModel,
    CreditAccountModel,
    CreditGrantModel,
    CreditLedgerModel,
    SubscriptionCycleModel,
    SubscriptionModel,
)
from app.api.v1.module_billing.service import SubscriptionService
from app.api.v1.module_model_gateway.cost_usage import RequestCostUsage
from app.api.v1.module_model_gateway.model import ModelUsageModel
from app.api.v1.module_payment.order.model import PaymentOrderModel
from app.api.v1.module_telemetry.model import TelemetryEventModel
from app.api.v1.module_user_operations.model import ClientSupportTicketModel
from app.core.base_schema import AuthSchema, PageResultSchema
from app.core.database import async_db_session
from app.core.exceptions import CustomException
from app.utils.password_util import PwdUtil

from .crud import ClientUserCRUD, ClientUserTagCRUD
from .model import (
    ClientAuthEventModel,
    ClientUserLevelConfigModel,
    ClientUserLevelHistoryModel,
    ClientUserModel,
    ClientUserSegmentModel,
    ClientUserTagModel,
)
from .schema import (
    ClientUserActivitySchema,
    ClientUserAdminUpdateSchema,
    ClientUserOutSchema,
    ClientUserQueryParam,
    ClientUserStatusSchema,
    ClientUserTagCreateSchema,
    ClientUserTagOutSchema,
    TemporaryPasswordOutSchema,
    UserLevelConfigOutSchema,
    UserLevelConfigSchema,
    UserSegmentCreateSchema,
    UserSegmentOutSchema,
)

DEFAULT_LEVEL_RULES = {
    "dimensions": [
        {"key": "total_paid_fen", "label": "累计支付", "weight": 30, "cap": 500000, "unit": "分", "window": "累计", "description": "已支付且未退款的实付金额"},
        {"key": "active_days_30d", "label": "产品活跃", "weight": 20, "cap": 20, "unit": "天", "window": "近30天", "description": "产生登录或核心业务行为的去重天数"},
        {"key": "model_calls_30d", "label": "模型使用", "weight": 20, "cap": 200, "unit": "次", "window": "近30天", "description": "成功或产生实际用量的模型调用次数"},
        {"key": "credits_used_30d", "label": "积分消耗", "weight": 20, "cap": 100000, "unit": "积分", "window": "近30天", "description": "按模型实际成本结算的积分"},
        {"key": "feedback_contribution", "label": "反馈贡献", "weight": 10, "cap": 5, "unit": "条", "window": "累计", "description": "已解决或被运营采纳的有效反馈"},
    ],
    "levels": [
        {"code": "LV1", "name": "新锐用户", "min_score": 0, "description": "完成注册，尚在价值验证期", "service_strategy": "新手引导与首个成果激活"},
        {"code": "LV2", "name": "活跃用户", "min_score": 20, "description": "形成稳定访问或轻度模型使用", "service_strategy": "场景教育与订阅转化"},
        {"code": "LV3", "name": "成长用户", "min_score": 40, "description": "持续使用并产生明确付费意愿", "service_strategy": "用量提升与续费培育"},
        {"code": "LV4", "name": "高价值用户", "min_score": 60, "description": "高频使用且贡献稳定收入", "service_strategy": "专属触达与流失预警"},
        {"code": "LV5", "name": "核心用户", "min_score": 80, "description": "长期高价值并积极反馈产品", "service_strategy": "重点维护与产品共创"},
    ],
}


class ClientUserService:
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db

    def _require_app_id(self) -> int:
        if not self.auth.app_id:
            raise CustomException(msg="请先选择客户端", status_code=409)
        return self.auth.app_id

    async def _get_user(
        self,
        user_id: int,
        *,
        with_tags: bool = False,
    ) -> ClientUserModel:
        """Load a client user strictly by app boundary.

        Client identities do not participate in the operations staff data-scope
        rules used by ``AppScopedCRUDBase``. Applying those rules here can add a
        ``created_id`` predicate and make a valid self-profile intermittently
        disappear when numeric client/staff ids happen to overlap.
        """

        stmt = select(ClientUserModel).where(
            ClientUserModel.id == user_id,
            ClientUserModel.app_id == self._require_app_id(),
            ClientUserModel.is_deleted == False,
        )
        if with_tags:
            stmt = stmt.options(selectinload(ClientUserModel.tags))
        user = await self.db.scalar(stmt)
        if not user:
            raise CustomException(msg="客户端用户不存在", status_code=404)
        return user

    def _list_stmt(self, search: ClientUserQueryParam):
        app_id = self._require_app_id()
        stmt = select(ClientUserModel).where(ClientUserModel.app_id == app_id, ClientUserModel.is_deleted == False)
        if search.keyword:
            keyword = f"%{search.keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    ClientUserModel.username.like(keyword),
                    ClientUserModel.display_name.like(keyword),
                    ClientUserModel.company_name.like(keyword),
                    ClientUserModel.mobile.like(keyword),
                )
            )
        if search.status:
            stmt = stmt.where(ClientUserModel.status == search.status)
        from app.api.v1.module_growth.filters import grade_value

        if search.usage_grade:
            stmt = stmt.where(grade_value(app_id, "usage") == search.usage_grade)
        if search.promotion_grade:
            stmt = stmt.where(grade_value(app_id, "promotion") == search.promotion_grade)
        if search.level_code:
            stmt = stmt.where(ClientUserModel.level_code == search.level_code)
        if search.registered_at and len(search.registered_at) == 2:
            stmt = stmt.where(ClientUserModel.registered_at.between(search.registered_at[0], search.registered_at[1]))
        if search.last_active_at and len(search.last_active_at) == 2:
            stmt = stmt.where(ClientUserModel.last_active_at.between(search.last_active_at[0], search.last_active_at[1]))
        if search.subscription_status:
            stmt = stmt.where(
                select(SubscriptionModel.id)
                .where(
                    SubscriptionModel.app_id == app_id,
                    SubscriptionModel.user_id == ClientUserModel.id,
                    SubscriptionModel.status == search.subscription_status,
                    SubscriptionModel.is_deleted == False,
                )
                .exists()
            )
        if search.catalog_plan_id:
            stmt = stmt.where(
                select(SubscriptionModel.id)
                .where(
                    SubscriptionModel.app_id == app_id,
                    SubscriptionModel.user_id == ClientUserModel.id,
                    SubscriptionModel.catalog_plan_id == search.catalog_plan_id,
                    SubscriptionModel.is_deleted == False,
                )
                .exists()
            )
        if search.min_credits is not None or search.max_credits is not None:
            credit_filters = [
                CreditAccountModel.app_id == app_id,
                CreditAccountModel.user_id == ClientUserModel.id,
                CreditAccountModel.is_deleted == False,
            ]
            if search.min_credits is not None:
                credit_filters.append(CreditAccountModel.available >= search.min_credits)
            if search.max_credits is not None:
                credit_filters.append(CreditAccountModel.available <= search.max_credits)
            stmt = stmt.where(select(CreditAccountModel.id).where(*credit_filters).exists())
        if search.tag:
            stmt = stmt.where(
                select(ClientUserTagModel.id)
                .where(
                    ClientUserTagModel.app_id == app_id,
                    ClientUserTagModel.user_id == ClientUserModel.id,
                    ClientUserTagModel.name.like(f"%{search.tag.strip()}%"),
                    ClientUserTagModel.status == "active",
                    ClientUserTagModel.is_deleted == False,
                )
                .exists()
            )
        if search.segment_id:
            from app.api.v1.module_growth.filters import grade_value

            segment_exists = (
                select(ClientUserSegmentModel.id).where(ClientUserSegmentModel.id == search.segment_id, ClientUserSegmentModel.app_id == app_id, ClientUserSegmentModel.is_deleted == False).exists()
            )
            stmt = stmt.where(segment_exists)
            for key, column in [
                ("level_code", ClientUserModel.level_code),
                ("status", ClientUserModel.status),
                ("usage_grade", grade_value(app_id, "usage")),
                ("promotion_grade", grade_value(app_id, "promotion")),
            ]:
                value = select(ClientUserSegmentModel.filters[key].as_string()).where(ClientUserSegmentModel.id == search.segment_id, ClientUserSegmentModel.app_id == app_id).scalar_subquery()
                stmt = stmt.where(or_(value.is_(None), value == "", column == value))

        now = datetime.now(UTC)
        if search.segment == "new":
            stmt = stmt.where(ClientUserModel.registered_at >= now - timedelta(days=7))
        elif search.segment == "inactive_7d":
            stmt = stmt.where(or_(ClientUserModel.last_active_at.is_(None), ClientUserModel.last_active_at < now - timedelta(days=7)))
        elif search.segment == "inactive_30d":
            stmt = stmt.where(or_(ClientUserModel.last_active_at.is_(None), ClientUserModel.last_active_at < now - timedelta(days=30)))
        elif search.segment == "subscribed":
            stmt = stmt.where(
                select(SubscriptionModel.id)
                .where(SubscriptionModel.app_id == app_id, SubscriptionModel.user_id == ClientUserModel.id, SubscriptionModel.status == "active", SubscriptionModel.is_deleted == False)
                .exists()
            )
        elif search.segment == "unsubscribed":
            stmt = stmt.where(
                ~select(SubscriptionModel.id)
                .where(SubscriptionModel.app_id == app_id, SubscriptionModel.user_id == ClientUserModel.id, SubscriptionModel.status == "active", SubscriptionModel.is_deleted == False)
                .exists()
            )
        elif search.segment == "expired":
            stmt = stmt.where(
                select(SubscriptionModel.id)
                .where(SubscriptionModel.app_id == app_id, SubscriptionModel.user_id == ClientUserModel.id, SubscriptionModel.status == "expired", SubscriptionModel.is_deleted == False)
                .exists()
            )
        elif search.segment == "low_credits":
            stmt = stmt.where(
                select(CreditAccountModel.id)
                .where(CreditAccountModel.app_id == app_id, CreditAccountModel.user_id == ClientUserModel.id, CreditAccountModel.available < 1000, CreditAccountModel.is_deleted == False)
                .exists()
            )
        elif search.segment == "high_usage":
            stmt = stmt.where(
                select(ModelUsageModel.user_id)
                .where(
                    ModelUsageModel.app_id == app_id,
                    ModelUsageModel.user_id == ClientUserModel.id,
                    ModelUsageModel.created_time >= now - timedelta(days=30),
                    ModelUsageModel.is_deleted == False,
                )
                .group_by(ModelUsageModel.user_id)
                .having(func.count(ModelUsageModel.id) >= 20)
                .exists()
            )
        elif search.segment == "tagged":
            stmt = stmt.where(
                select(ClientUserTagModel.id)
                .where(
                    ClientUserTagModel.app_id == app_id,
                    ClientUserTagModel.user_id == ClientUserModel.id,
                    ClientUserTagModel.status == "active",
                    ClientUserTagModel.is_deleted == False,
                )
                .exists()
            )
        return stmt

    async def _enrich(self, rows: list[ClientUserModel]) -> list[ClientUserOutSchema]:
        if not rows:
            return []
        user_ids = [row.id for row in rows]
        accounts = list(
            (
                await self.db.scalars(
                    select(CreditAccountModel).where(CreditAccountModel.app_id == self._require_app_id(), CreditAccountModel.user_id.in_(user_ids), CreditAccountModel.is_deleted == False)
                )
            ).all()
        )
        account_map = {item.user_id: item for item in accounts}
        subscriptions = list(
            (
                await self.db.scalars(
                    select(SubscriptionModel)
                    .where(SubscriptionModel.app_id == self._require_app_id(), SubscriptionModel.user_id.in_(user_ids), SubscriptionModel.is_deleted == False)
                    .order_by(SubscriptionModel.id.desc())
                )
            ).all()
        )
        subscription_map = {item.user_id: item for item in subscriptions}
        plan_ids = {item.catalog_plan_id for item in subscriptions}
        plans = [] if not plan_ids else list((await self.db.scalars(select(AppCatalogPlanModel).where(AppCatalogPlanModel.id.in_(plan_ids)))).all())
        plan_map = {item.id: item for item in plans}
        paid_rows = (
            await self.db.execute(
                select(PaymentOrderModel.user_id, func.coalesce(func.sum(PaymentOrderModel.amount_fen), 0))
                .where(
                    PaymentOrderModel.app_id == self._require_app_id(),
                    PaymentOrderModel.user_id.in_(user_ids),
                    PaymentOrderModel.status == "paid",
                    PaymentOrderModel.is_deleted == False,
                )
                .group_by(PaymentOrderModel.user_id)
            )
        ).all()
        paid_map = {user_id: int(amount) for user_id, amount in paid_rows}
        usage_rows = (
            await self.db.execute(
                select(
                    ModelUsageModel.user_id,
                    func.count(ModelUsageModel.id),
                    func.coalesce(func.sum(ModelUsageModel.input_tokens + ModelUsageModel.output_tokens), 0),
                    func.coalesce(func.sum(ModelUsageModel.charged_credits), 0),
                    func.coalesce(func.sum(case((ModelUsageModel.status == "failed", 1), else_=0)), 0),
                )
                .where(
                    ModelUsageModel.app_id == self._require_app_id(),
                    ModelUsageModel.user_id.in_(user_ids),
                    ModelUsageModel.is_deleted == False,
                )
                .group_by(ModelUsageModel.user_id)
            )
        ).all()
        usage_map = {user_id: (int(calls), int(tokens), int(credits), int(failed)) for user_id, calls, tokens, credits, failed in usage_rows}
        result: list[ClientUserOutSchema] = []
        from app.api.v1.module_growth.model import GrowthProfileModel

        profiles = list(await self.db.scalars(select(GrowthProfileModel).where(GrowthProfileModel.app_id == self._require_app_id(), GrowthProfileModel.user_id.in_(user_ids))))
        growth_map = {p.user_id: p for p in profiles}
        for row in rows:
            item = ClientUserOutSchema.model_validate(row)
            if profile := growth_map.get(row.id):
                item.usage_grade = profile.usage_grade
                item.promotion_grade = profile.promotion_grade
            account = account_map.get(row.id)
            subscription = subscription_map.get(row.id)
            if account:
                item.available_credits = account.available
                item.pending_credits = account.pending
                item.credit_usage = account.total_consumed
            if subscription:
                item.subscription_status = subscription.status
                item.subscription_expires_at = subscription.current_period_end
                plan = plan_map.get(subscription.catalog_plan_id) if subscription.status == "active" else None
                item.current_subscription = plan.name if plan else None
                item.current_subscription_tier = plan.tier_code if plan else None
            item.total_paid_fen = paid_map.get(row.id, 0)
            item.model_calls, item.token_usage, item.credit_usage, item.failed_calls = usage_map.get(row.id, (0, 0, item.credit_usage, 0))
            result.append(item)
        return result

    async def page(self, page_no: int, page_size: int, search: ClientUserQueryParam) -> PageResultSchema[ClientUserOutSchema]:
        await SubscriptionService(self.db).expire_due(self._require_app_id())
        stmt = self._list_stmt(search)
        count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
        total = int(await self.db.scalar(count_stmt) or 0)
        rows = list((await self.db.scalars(stmt.options(selectinload(ClientUserModel.tags)).order_by(ClientUserModel.id.desc()).offset((page_no - 1) * page_size).limit(page_size))).all())
        return PageResultSchema(
            page_no=page_no,
            page_size=page_size,
            total=total,
            has_next=page_no * page_size < total,
            items=await self._enrich(rows),
        )

    async def detail(self, user_id: int) -> ClientUserOutSchema:
        await SubscriptionService(self.db).expire_due(self._require_app_id())
        user = await self._get_user(user_id, with_tags=True)
        return (await self._enrich([user]))[0]

    async def activity(self, user_id: int) -> ClientUserActivitySchema:
        await SubscriptionService(self.db).expire_due(self._require_app_id())
        user = await self._get_user(user_id)
        from app.api.v1.module_client.app.model_policy import current_mode, get_model_policy
        app = await get_model_policy(self.db, self._require_app_id())
        app_id = self._require_app_id()
        subscription = await self.db.scalar(
            select(SubscriptionModel).where(
                SubscriptionModel.app_id == app_id,
                SubscriptionModel.user_id == user_id,
                SubscriptionModel.is_deleted == False,
            )
        )
        plan = None
        if subscription:
            plan = await self.db.scalar(select(AppCatalogPlanModel).where(AppCatalogPlanModel.id == subscription.catalog_plan_id))
        orders = list(
            (
                await self.db.scalars(
                    select(PaymentOrderModel)
                    .where(
                        PaymentOrderModel.app_id == app_id,
                        PaymentOrderModel.user_id == user_id,
                        PaymentOrderModel.is_deleted == False,
                    )
                    .order_by(PaymentOrderModel.id.desc())
                    .limit(50)
                )
            ).all()
        )
        ledger = list(
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
        usage = list(
            (
                await self.db.scalars(
                    select(ModelUsageModel)
                    .where(
                        ModelUsageModel.app_id == app_id,
                        ModelUsageModel.user_id == user_id,
                        ModelUsageModel.is_deleted == False,
                    )
                    .order_by(ModelUsageModel.id.desc())
                    .limit(100)
                )
            ).all()
        )
        security_events = list(
            (
                await self.db.scalars(
                    select(ClientAuthEventModel)
                    .where(
                        ClientAuthEventModel.app_id == app_id,
                        ClientAuthEventModel.user_id == user_id,
                        ClientAuthEventModel.is_deleted == False,
                    )
                    .order_by(ClientAuthEventModel.id.desc())
                    .limit(50)
                )
            ).all()
        )
        cycles = []
        if subscription:
            cycles = list(
                (
                    await self.db.scalars(
                        select(SubscriptionCycleModel)
                        .where(
                            SubscriptionCycleModel.app_id == app_id,
                            SubscriptionCycleModel.user_id == user_id,
                            SubscriptionCycleModel.subscription_id == subscription.id,
                            SubscriptionCycleModel.is_deleted == False,
                        )
                        .order_by(SubscriptionCycleModel.cycle_no.desc())
                        .limit(50)
                    )
                ).all()
            )
        now = datetime.now(UTC)
        expiring_credits = int(
            await self.db.scalar(
                select(func.coalesce(func.sum(CreditGrantModel.available), 0)).where(
                    CreditGrantModel.app_id == app_id,
                    CreditGrantModel.user_id == user_id,
                    CreditGrantModel.status == "released",
                    CreditGrantModel.available > 0,
                    CreditGrantModel.expires_at > now,
                    CreditGrantModel.expires_at <= now + timedelta(days=30),
                    CreditGrantModel.is_deleted == False,
                )
            )
            or 0
        )
        project_count = int(
            await self.db.scalar(
                select(func.count(func.distinct(TelemetryEventModel.project_ref))).where(
                    TelemetryEventModel.app_id == app_id,
                    TelemetryEventModel.user_id == user_id,
                    TelemetryEventModel.project_ref.is_not(None),
                    TelemetryEventModel.is_deleted == False,
                )
            )
            or 0
        )
        tickets = list(
            (
                await self.db.scalars(
                    select(ClientSupportTicketModel)
                    .where(
                        ClientSupportTicketModel.app_id == app_id,
                        ClientSupportTicketModel.user_id == user_id,
                        ClientSupportTicketModel.is_deleted == False,
                    )
                    .order_by(ClientSupportTicketModel.id.desc())
                    .limit(50)
                )
            ).all()
        )
        trend_rows = (
            await self.db.execute(
                select(
                    func.date(RequestCostUsage.completed_at),
                    func.count(RequestCostUsage.id),
                    func.coalesce(func.sum(RequestCostUsage.input_tokens + RequestCostUsage.output_tokens), 0),
                    func.coalesce(func.sum(RequestCostUsage.charged_credits), 0),
                    func.coalesce(func.sum(RequestCostUsage.provider_cost_yuan), 0),
                    func.sum(case((RequestCostUsage.provider_cost_yuan.is_(None), 1), else_=0)),
                )
                .where(
                    RequestCostUsage.app_id == app_id,
                    RequestCostUsage.user_id == user_id,
                    RequestCostUsage.completed_at >= now - timedelta(days=30),
                    RequestCostUsage.is_deleted == False,
                )
                .group_by(func.date(RequestCostUsage.completed_at))
                .order_by(func.date(RequestCostUsage.completed_at).asc())
            )
        ).all()
        telemetry_trend_rows = (
            await self.db.execute(
                select(
                    func.date(TelemetryEventModel.occurred_at),
                    func.count(TelemetryEventModel.id),
                )
                .where(
                    TelemetryEventModel.app_id == app_id,
                    TelemetryEventModel.user_id == user_id,
                    TelemetryEventModel.occurred_at >= now - timedelta(days=30),
                    TelemetryEventModel.is_deleted == False,
                )
                .group_by(func.date(TelemetryEventModel.occurred_at))
            )
        ).all()
        login_trend_rows = (
            await self.db.execute(
                select(
                    func.date(ClientAuthEventModel.created_time),
                    func.count(ClientAuthEventModel.id),
                )
                .where(
                    ClientAuthEventModel.app_id == app_id,
                    ClientAuthEventModel.user_id == user_id,
                    ClientAuthEventModel.success == True,
                    ClientAuthEventModel.created_time >= now - timedelta(days=30),
                    ClientAuthEventModel.is_deleted == False,
                )
                .group_by(func.date(ClientAuthEventModel.created_time))
            )
        ).all()
        usage_by_day = {
            str(day): {
                "calls": int(calls),
                "tokens": int(tokens),
                "credits": int(credits),
                "provider_cost_yuan": float(cost),
                "unknown_cost_calls": int(unknown or 0),
            }
            for day, calls, tokens, credits, cost, unknown in trend_rows
        }
        telemetry_by_day = {str(day): int(events) for day, events in telemetry_trend_rows}
        logins_by_day = {str(day): int(logins) for day, logins in login_trend_rows}
        activity_trend = []
        for offset in range(29, -1, -1):
            day = (now - timedelta(days=offset)).date().isoformat()
            usage_day = usage_by_day.get(day, {})
            activity_trend.append(
                {
                    "date": day,
                    "calls": int(usage_day.get("calls", 0)),
                    "tokens": int(usage_day.get("tokens", 0)),
                    "credits": int(usage_day.get("credits", 0)),
                    "provider_cost_yuan": float(usage_day.get("provider_cost_yuan", 0)),
                    "unknown_cost_calls": int(usage_day.get("unknown_cost_calls", 0)),
                    "events": telemetry_by_day.get(day, 0),
                    "logins": logins_by_day.get(day, 0),
                }
            )
        return ClientUserActivitySchema(active_billing_mode=current_mode(app, user), mode_version=user.mode_version,
            subscription=(
                {
                    "id": subscription.id,
                    "plan_name": plan.name if plan else None,
                    "status": subscription.status,
                    "auto_renew": subscription.auto_renew,
                    "current_period_start": subscription.current_period_start,
                    "current_period_end": subscription.current_period_end,
                }
                if subscription
                else None
            ),
            subscription_cycles=[
                {
                    "cycle_no": item.cycle_no,
                    "plan_name": item.plan_snapshot.get("name"),
                    "starts_at": item.starts_at,
                    "ends_at": item.ends_at,
                    "status": item.status,
                }
                for item in cycles
            ],
            orders=[
                {
                    "order_no": item.order_no,
                    "plan_name": item.plan_snapshot.get("name"),
                    "amount_fen": item.amount_fen,
                    "provider": item.provider,
                    "status": item.status,
                    "created_time": item.created_time,
                }
                for item in orders
            ],
            credit_ledger=[
                {
                    "id": item.id,
                    "entry_type": item.entry_type,
                    "amount": item.amount,
                    "balance_after": item.balance_after,
                    "reason": item.reason,
                    "created_time": item.created_time,
                }
                for item in ledger
            ],
            model_usage=[
                {
                    "request_id": item.request_id,
                    "business_code": item.business_code,
                    "provider_model_id": item.provider_model_id,
                    "input_tokens": item.input_tokens,
                    "output_tokens": item.output_tokens,
                    "charged_credits": item.charged_credits,
                    "provider_cost_yuan": float(item.provider_cost_yuan or 0),
                    "cost_precision": item.cost_precision,
                    "reconciliation_status": item.reconciliation_status,
                    "usage_detail": item.usage_detail,
                    "latency_ms": item.latency_ms,
                    "status": item.status,
                    "created_time": item.created_time,
                }
                for item in usage
            ],
            security_events=[
                {
                    "action": item.action,
                    "success": item.success,
                    "failure_reason": item.failure_reason,
                    "request_ip": item.request_ip,
                    "user_agent": item.user_agent,
                    "created_time": item.created_time,
                }
                for item in security_events
            ],
            expiring_credits=expiring_credits,
            project_count=project_count,
            risk_flags=await self._risk_flags(user_id, subscription, usage),
            support_tickets=[
                {
                    "id": item.id,
                    "ticket_no": item.ticket_no,
                    "kind": item.kind,
                    "category": item.category,
                    "subject": item.subject,
                    "priority": item.priority,
                    "status": item.status,
                    "adopted": item.adopted,
                    "created_time": item.created_time,
                }
                for item in tickets
            ],
            activity_trend=activity_trend,
            generated_at=datetime.now(UTC),
        )

    async def _risk_flags(self, user_id: int, subscription: SubscriptionModel | None, usage: list[ModelUsageModel]) -> list[dict]:
        user = await self.db.scalar(select(ClientUserModel).where(ClientUserModel.id == user_id))
        account = await self.db.scalar(
            select(CreditAccountModel).where(CreditAccountModel.app_id == self._require_app_id(), CreditAccountModel.user_id == user_id, CreditAccountModel.is_deleted == False)
        )
        now = datetime.now(UTC)
        flags: list[dict] = []
        last_active = user.last_active_at if user else None
        if last_active and last_active.tzinfo is None:
            last_active = last_active.replace(tzinfo=UTC)
        if not last_active or last_active < now - timedelta(days=30):
            flags.append({"code": "inactive_30d", "level": "high", "label": "超过30天未活跃"})
        if account and account.available < 1000:
            flags.append({"code": "low_credits", "level": "medium", "label": "可用积分不足1000"})
        if subscription:
            period_end = subscription.current_period_end
            if period_end.tzinfo is None:
                period_end = period_end.replace(tzinfo=UTC)
            if period_end <= now + timedelta(days=7):
                flags.append({"code": "subscription_expiring", "level": "medium", "label": "订阅将在7天内到期"})
        recent = [item for item in usage if item.created_time >= now - timedelta(days=30)]
        if len(recent) >= 5 and sum(1 for item in recent if item.status != "succeeded") / len(recent) >= 0.2:
            flags.append({"code": "model_failure", "level": "high", "label": "近30日模型失败率超过20%"})
        return flags

    async def update(self, user_id: int, data: ClientUserAdminUpdateSchema) -> ClientUserOutSchema:
        user = await ClientUserCRUD(self.auth, self.db).get_or_404(id=user_id, msg="客户端用户不存在")
        values = data.model_dump(exclude_unset=True)
        if "email" in values and values["email"]:
            values["email"] = str(values["email"])
        if "mobile" in values and values["mobile"] != user.mobile:
            values["mobile_verified_at"] = None
        if values.get("status") and values["status"] != user.status:
            values["auth_generation"] = user.auth_generation + 1
        await ClientUserCRUD(self.auth, self.db).update(user_id, values)
        return await self.detail(user_id)

    async def set_status(self, user_id: int, data: ClientUserStatusSchema) -> ClientUserOutSchema:
        user = await ClientUserCRUD(self.auth, self.db).get_or_404(id=user_id, msg="客户端用户不存在")
        await ClientUserCRUD(self.auth, self.db).update(
            user_id,
            {"status": data.status, "auth_generation": user.auth_generation + 1, "description": data.reason},
        )
        return await self.detail(user_id)

    async def reset_password(self, user_id: int) -> TemporaryPasswordOutSchema:
        user = await ClientUserCRUD(self.auth, self.db).get_or_404(id=user_id, msg="客户端用户不存在")
        temporary = PwdUtil.generate_strong_password()
        await ClientUserCRUD(self.auth, self.db).update(
            user_id,
            {
                "password_hash": PwdUtil.hash_password(temporary),
                "must_change_password": True,
                "auth_generation": user.auth_generation + 1,
            },
        )
        return TemporaryPasswordOutSchema(temporary_password=temporary)

    async def add_tag(self, user_id: int, data: ClientUserTagCreateSchema) -> ClientUserTagOutSchema:
        await ClientUserCRUD(self.auth, self.db).get_or_404(id=user_id, msg="客户端用户不存在")
        crud = ClientUserTagCRUD(self.auth, self.db)
        if await crud.get(user_id=user_id, name=data.name):
            raise CustomException(msg="该标签已存在")
        tag = await crud.create({"user_id": user_id, **data.model_dump()})
        return ClientUserTagOutSchema.model_validate(tag)

    async def remove_tag(self, user_id: int, tag_id: int) -> None:
        tag = await ClientUserTagCRUD(self.auth, self.db).get(id=tag_id, user_id=user_id)
        if not tag:
            raise CustomException(msg="标签不存在")
        await ClientUserTagCRUD(self.auth, self.db).delete([tag_id])


class UserLevelService:
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        if not auth.app_id:
            raise CustomException(msg="请先选择客户端", status_code=409)
        self.auth = auth
        self.db = db
        self.app_id = auth.app_id

    async def config(self) -> UserLevelConfigOutSchema:
        row = await self.db.scalar(select(ClientUserLevelConfigModel).where(ClientUserLevelConfigModel.app_id == self.app_id, ClientUserLevelConfigModel.is_deleted == False))
        if not row:
            row = ClientUserLevelConfigModel(app_id=self.app_id, version=1, rules=DEFAULT_LEVEL_RULES, status="active", created_id=self.auth.user.id or None, updated_id=self.auth.user.id or None)
            self.db.add(row)
            await self.db.flush()
        return UserLevelConfigOutSchema.model_validate(row)

    async def update_config(self, data: UserLevelConfigSchema) -> UserLevelConfigOutSchema:
        await self.config()
        row = await self.db.scalar(select(ClientUserLevelConfigModel).where(ClientUserLevelConfigModel.app_id == self.app_id, ClientUserLevelConfigModel.is_deleted == False).with_for_update())
        assert row
        row.rules = data.model_dump()
        row.version += 1
        row.updated_id = self.auth.user.id or None
        await self.db.flush()
        await self.recalculate()
        return UserLevelConfigOutSchema.model_validate(row)

    async def _metrics(self, user_id: int) -> dict:
        since = datetime.now(UTC) - timedelta(days=30)
        total_paid = int(
            await self.db.scalar(
                select(func.coalesce(func.sum(PaymentOrderModel.amount_fen), 0)).where(
                    PaymentOrderModel.app_id == self.app_id, PaymentOrderModel.user_id == user_id, PaymentOrderModel.status == "paid", PaymentOrderModel.is_deleted == False
                )
            )
            or 0
        )
        usage_row = (
            await self.db.execute(
                select(func.count(ModelUsageModel.id), func.coalesce(func.sum(ModelUsageModel.charged_credits), 0), func.count(func.distinct(func.date(ModelUsageModel.created_time)))).where(
                    ModelUsageModel.app_id == self.app_id, ModelUsageModel.user_id == user_id, ModelUsageModel.created_time >= since, ModelUsageModel.is_deleted == False
                )
            )
        ).one()
        feedback = int(
            await self.db.scalar(
                select(func.count())
                .select_from(ClientSupportTicketModel)
                .where(
                    ClientSupportTicketModel.app_id == self.app_id,
                    ClientSupportTicketModel.user_id == user_id,
                    ClientSupportTicketModel.kind == "feedback",
                    or_(ClientSupportTicketModel.adopted == True, ClientSupportTicketModel.status.in_(["resolved", "closed"])),
                    ClientSupportTicketModel.is_deleted == False,
                )
            )
            or 0
        )
        return {
            "total_paid_fen": total_paid,
            "active_days_30d": int(usage_row[2] or 0),
            "model_calls_30d": int(usage_row[0] or 0),
            "credits_used_30d": int(usage_row[1] or 0),
            "feedback_contribution": feedback,
        }

    @staticmethod
    def _score(metrics: dict, rules: dict) -> float:
        return round(sum(min(float(metrics.get(item["key"], 0)) / float(item["cap"]), 1) * float(item["weight"]) for item in rules["dimensions"]), 2)

    @staticmethod
    def _level(score: float, rules: dict) -> str:
        result = "LV1"
        for item in sorted(rules["levels"], key=lambda value: float(value["min_score"])):
            if score >= float(item["min_score"]):
                result = str(item["code"])
        return result

    async def recalculate(self) -> int:
        config = await self.db.scalar(select(ClientUserLevelConfigModel).where(ClientUserLevelConfigModel.app_id == self.app_id, ClientUserLevelConfigModel.is_deleted == False))
        if not config:
            await self.config()
            config = await self.db.scalar(select(ClientUserLevelConfigModel).where(ClientUserLevelConfigModel.app_id == self.app_id, ClientUserLevelConfigModel.is_deleted == False))
        assert config
        users = list((await self.db.scalars(select(ClientUserModel).where(ClientUserModel.app_id == self.app_id, ClientUserModel.is_deleted == False))).all())
        now = datetime.now(UTC)
        for user in users:
            metrics = await self._metrics(user.id)
            score = self._score(metrics, config.rules)
            level = self._level(score, config.rules)
            if user.level_code != level:
                self.db.add(ClientUserLevelHistoryModel(app_id=self.app_id, user_id=user.id, old_level=user.level_code, new_level=level, score=score, metrics=metrics, config_version=config.version))
            user.level_code = level
            user.level_score = score
            user.level_metrics = metrics
            user.level_evaluated_at = now
        await self.db.flush()
        return len(users)


class UserSegmentService:
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        if not auth.app_id:
            raise CustomException(msg="请先选择客户端", status_code=409)
        self.auth = auth
        self.db = db
        self.app_id = auth.app_id

    async def list(self) -> list[UserSegmentOutSchema]:
        rows = list(
            (
                await self.db.scalars(
                    select(ClientUserSegmentModel)
                    .where(ClientUserSegmentModel.app_id == self.app_id, ClientUserSegmentModel.is_deleted == False, ClientUserSegmentModel.status == "active")
                    .order_by(ClientUserSegmentModel.id.desc())
                )
            ).all()
        )
        results: list[UserSegmentOutSchema] = []
        for row in rows:
            filters = row.filters or {}
            stmt = select(func.count()).select_from(ClientUserModel).where(ClientUserModel.app_id == self.app_id, ClientUserModel.is_deleted == False)
            from app.api.v1.module_growth.filters import segment_conditions

            stmt = stmt.where(*segment_conditions(self.app_id, filters))
            item = UserSegmentOutSchema.model_validate(row)
            item.matched_count = int(await self.db.scalar(stmt) or 0)
            results.append(item)
        return results

    async def create(self, data: UserSegmentCreateSchema) -> UserSegmentOutSchema:
        duplicate = await self.db.scalar(
            select(ClientUserSegmentModel.id).where(ClientUserSegmentModel.app_id == self.app_id, ClientUserSegmentModel.name == data.name, ClientUserSegmentModel.is_deleted == False)
        )
        if duplicate:
            raise CustomException(msg="分群名称已存在")
        row = ClientUserSegmentModel(app_id=self.app_id, **data.model_dump(), status="active", created_id=self.auth.user.id, updated_id=self.auth.user.id)
        self.db.add(row)
        await self.db.flush()
        result = UserSegmentOutSchema.model_validate(row)
        result.matched_count = 0
        return result


async def run_user_level_evaluation() -> None:
    """Daily, replay-safe evaluation across explicit client scopes."""
    from app.api.v1.module_client.app.model import ClientAppModel

    async with async_db_session() as db, db.begin():
        app_ids = list((await db.scalars(select(ClientAppModel.id).where(ClientAppModel.is_deleted == False))).all())
        for app_id in app_ids:
            await UserLevelService(AuthSchema(app_id=app_id), db).recalculate()
