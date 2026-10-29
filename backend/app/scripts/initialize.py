import json
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.module_billing.model import (
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
from app.api.v1.module_client.app.model import ClientAppModel, StaffAppModel
from app.api.v1.module_client.user.model import (
    ClientUserLevelConfigModel,
    ClientUserLevelHistoryModel,
    ClientUserModel,
    ClientUserSegmentModel,
    ClientUserTagModel,
)
from app.api.v1.module_model_gateway.model import (
    AppModelBindingModel,
    AppModelRouteModel,
    ModelCatalogModel,
    ModelProviderAccountModel,
    ModelProviderTemplateModel,
    ModelUsageModel,
)
from app.api.v1.module_model_gateway.presets import PROVIDER_PRESETS
from app.api.v1.module_payment.channel.model import PaymentChannelModel
from app.api.v1.module_payment.order.model import PaymentCallbackModel, PaymentOrderModel
from app.api.v1.module_system.dept.model import DeptModel
from app.api.v1.module_system.dict.model import DictDataModel, DictTypeModel
from app.api.v1.module_system.menu.model import MenuModel
from app.api.v1.module_system.params.model import ParamsModel
from app.api.v1.module_system.role.model import RoleMenusModel, RoleModel
from app.api.v1.module_system.user.model import UserModel, UserRolesModel
from app.api.v1.module_system.versions.model import VersionModel
from app.api.v1.module_system.workspace.model import WorkspaceModuleModel
from app.api.v1.module_system.workspace.seed import (
    MODULE_SEEDS,
    WORKSPACE_ACTION_SEEDS,
    WORKSPACE_MENU_SEEDS,
)
from app.api.v1.module_telemetry.model import TelemetryEventModel
from app.api.v1.module_user_operations.model import (
    ClientMessageCampaignModel,
    ClientMessageDeliveryModel,
    ClientMessageTemplateModel,
    ClientSupportMessageModel,
    ClientSupportTicketModel,
)
from app.config.path_conf import SCRIPT_DIR
from app.core.database import async_db_session, check_db, create_tables
from app.core.logger import logger


class InitializeData:
    """初始化数据库和基础数据"""

    # 按依赖关系排序：先基础表，再关联表
    prepare_init_models: list[type] = [
        WorkspaceModuleModel,
        ClientAppModel,
        StaffAppModel,
        ClientUserModel,
        ClientUserTagModel,
        ClientUserLevelConfigModel,
        ClientUserLevelHistoryModel,
        ClientUserSegmentModel,
        PricingStandardVersionModel,
        PricingPlanTemplateModel,
        AppCatalogPlanModel,
        AppPricingStrategyModel,
        AppPricingStrategyItemModel,
        SubscriptionModel,
        SubscriptionCycleModel,
        CreditAccountModel,
        CreditGrantModel,
        CreditLedgerModel,
        CreditReservationModel,
        ModelProviderTemplateModel,
        ModelProviderAccountModel,
        ModelCatalogModel,
        AppModelBindingModel,
        AppModelRouteModel,
        ModelUsageModel,
        ClientSupportTicketModel,
        ClientSupportMessageModel,
        ClientMessageTemplateModel,
        ClientMessageCampaignModel,
        ClientMessageDeliveryModel,
        PaymentChannelModel,
        PaymentOrderModel,
        PaymentCallbackModel,
        TelemetryEventModel,
        MenuModel,
        DeptModel,
        ParamsModel,
        RoleModel,
        DictTypeModel,
        DictDataModel,
        UserModel,
        UserRolesModel,
        VersionModel,
    ]

    # 树形模型：JSON 含嵌套 children，需递归创建对象
    _RECURSIVE_TABLES: set[str] = {"sys_menu", "sys_dept"}

    async def init_db(self) -> None:
        """建表并导入种子数据"""
        await check_db()
        # await drop_tables()
        await create_tables()

        async with async_db_session() as session, session.begin():
            # 必须在导入种子前判断；包括软删除记录。已有账号的系统即使清空
            # 菜单也不能视为首次安装，否则部署/重启会恢复运营人员删除的入口。
            initialize_navigation = not await session.scalar(select(or_(select(UserModel.id).exists(), select(MenuModel.id).exists())))
            await self.__init_data(session, initialize_navigation=initialize_navigation)
            if initialize_navigation:
                await self.__remove_retired_features(session)
                await self.__initialize_template_menus(session)
            await self.__reconcile_template_configuration(session)
            await self.__reconcile_client_apps(session)
            await self.__reconcile_default_pricing(session)
            await self.__reconcile_model_provider_templates(session)
            await self.__reconcile_payment_channels(session)
            if initialize_navigation:
                await self.__initialize_workspace_configuration(session)
            else:
                logger.info("⏭️  保留已有菜单、工作台模块及授权；菜单版本变更由 Alembic 迁移处理")

    @staticmethod
    async def __reconcile_client_apps(db: AsyncSession) -> None:
        """建立首个正式客户端，并显式授权给现有超级管理员。"""
        app = await db.scalar(select(ClientAppModel).where(ClientAppModel.code == "bid_agent"))
        if not app:
            app = ClientAppModel(
                code="bid_agent",
                name="招投标智能体",
                logo="/web/logo.png",
                client_version="0.1.4",
                status="active",
                registration_enabled=True,
                order=1,
                description="投标文件编制、文档理解与智能审查客户端",
            )
            db.add(app)
            await db.flush()
        else:
            app.name = "招投标智能体"
            if not app.logo or app.logo == "/logo.png":
                app.logo = "/web/logo.png"
            if not app.client_version or app.client_version == "MVP":
                app.client_version = "0.1.4"
            app.order = 1
            app.status = "active"
            app.registration_enabled = True

        superuser_ids = list((await db.scalars(select(UserModel.id).where(UserModel.is_superuser == True, UserModel.is_deleted == False))).all())
        for staff_id in superuser_ids:
            binding = await db.scalar(
                select(StaffAppModel).where(
                    StaffAppModel.staff_id == staff_id,
                    StaffAppModel.app_id == app.id,
                    StaffAppModel.is_deleted == False,
                )
            )
            if not binding:
                db.add(StaffAppModel(staff_id=staff_id, app_id=app.id, is_default=True, status="active"))

    @staticmethod
    async def __reconcile_model_provider_templates(db: AsyncSession) -> None:
        """同步供应商表单模板，不创建任何密钥或虚构账号。"""
        for order, preset in enumerate(PROVIDER_PRESETS, start=1):
            template = await db.scalar(select(ModelProviderTemplateModel).where(ModelProviderTemplateModel.code == preset["code"]))
            values = {**preset, "order": order, "status": "active", "custom": False}
            if template:
                for key, value in values.items():
                    setattr(template, key, value)
            else:
                db.add(ModelProviderTemplateModel(**values))

    @staticmethod
    async def __reconcile_default_pricing(db: AsyncSession) -> None:
        """提供可编辑的首版价格模板；客户端刊例保持草稿，避免部署后误售。"""
        version = await db.scalar(select(PricingStandardVersionModel).where(PricingStandardVersionModel.version == "MVP-1"))
        if not version:
            version = PricingStandardVersionModel(
                version="MVP-1",
                name="首发价格体系",
                status="published",
                credit_unit_name="算力积分",
                margin_baseline=60,
                credits_per_yuan=1000,
                subscription_cycle_days=30,
                renewal_discount_rate=0.9,
                margin_floor=25,
                account_priority=["activity_reward", "current_cycle", "monthly_reserve", "traffic_pack", "enterprise_pool", "manual"],
                description="上线前请结合模型成本复核价格与积分释放量。",
            )
            db.add(version)
            await db.flush()
        templates = (
            {
                "code": "trial",
                "name": "体验版",
                "plan_type": "subscription",
                "tier_code": "free",
                "tier_order": 0,
                "billing_period_days": 7,
                "one_time_price_fen": 0,
                "recurring_price_fen": 0,
                "total_credits": 300,
                "release_plan": [{"offset_day": 0, "amount": 300, "account_type": "current_cycle"}],
                "credit_valid_days": 7,
                "renewal_rule": "体验权益不自动续费",
                "benefits": ["7天完整功能体验", "标准模型服务"],
                "order": 1,
            },
            {
                "code": "starter",
                "name": "基础版",
                "plan_type": "subscription",
                "tier_code": "starter",
                "tier_order": 10,
                "billing_period_days": 30,
                "one_time_price_fen": 5900,
                "recurring_price_fen": 4900,
                "total_credits": 5000,
                "release_plan": [{"offset_day": 0, "amount": 5000, "account_type": "current_cycle"}],
                "credit_valid_days": 30,
                "renewal_rule": "按月续费，积分在周期开始时一次释放",
                "benefits": ["个人项目管理", "标准模型服务"],
                "order": 2,
            },
            {
                "code": "professional",
                "name": "专业版",
                "plan_type": "subscription",
                "tier_code": "professional",
                "tier_order": 20,
                "billing_period_days": 30,
                "one_time_price_fen": 19900,
                "recurring_price_fen": 9900,
                "total_credits": 12000,
                "release_plan": [
                    {"offset_day": 0, "amount": 3000, "account_type": "current_cycle"},
                    {"offset_day": 7, "amount": 3000, "account_type": "current_cycle"},
                    {"offset_day": 14, "amount": 3000, "account_type": "current_cycle"},
                    {"offset_day": 21, "amount": 3000, "account_type": "current_cycle"},
                ],
                "credit_valid_days": 30,
                "renewal_rule": "按订阅周期续费，每周释放一次算力积分",
                "benefits": ["不限项目数量", "高性能模型服务", "优先工单支持"],
                "order": 3,
            },
            {
                "code": "enterprise",
                "name": "企业版",
                "plan_type": "subscription",
                "tier_code": "enterprise",
                "tier_order": 30,
                "billing_period_days": 30,
                "one_time_price_fen": 49900,
                "recurring_price_fen": 39900,
                "total_credits": 60000,
                "release_plan": [
                    {"offset_day": 0, "amount": 15000, "account_type": "current_cycle"},
                    {"offset_day": 7, "amount": 15000, "account_type": "current_cycle"},
                    {"offset_day": 14, "amount": 15000, "account_type": "current_cycle"},
                    {"offset_day": 21, "amount": 15000, "account_type": "current_cycle"},
                ],
                "credit_valid_days": 30,
                "renewal_rule": "按订阅周期续费，每周释放一次算力积分",
                "benefits": ["企业协作空间", "高性能模型服务", "专属运营支持"],
                "order": 4,
            },
            {
                "code": "credits_50k",
                "name": "轻量积分包",
                "plan_type": "credit_pack",
                "billing_period_days": 365,
                "one_time_price_fen": 9900,
                "recurring_price_fen": 9900,
                "total_credits": 50000,
                "release_plan": [{"offset_day": 0, "amount": 50000, "account_type": "traffic_pack"}],
                "credit_valid_days": 365,
                "renewal_rule": "单次购买，即时到账，不自动续费",
                "benefits": ["即时到账"],
                "requires_active_subscription": True,
                "order": 5,
            },
            {
                "code": "credits_150k",
                "name": "进阶积分包",
                "plan_type": "credit_pack",
                "billing_period_days": 365,
                "one_time_price_fen": 24900,
                "recurring_price_fen": 24900,
                "total_credits": 150000,
                "release_plan": [{"offset_day": 0, "amount": 150000, "account_type": "traffic_pack"}],
                "credit_valid_days": 365,
                "renewal_rule": "单次购买，即时到账，不自动续费",
                "benefits": ["即时到账"],
                "requires_active_subscription": True,
                "order": 6,
            },
            {
                "code": "credits_500k",
                "name": "企业积分包",
                "plan_type": "credit_pack",
                "billing_period_days": 365,
                "one_time_price_fen": 69900,
                "recurring_price_fen": 69900,
                "total_credits": 500000,
                "release_plan": [{"offset_day": 0, "amount": 500000, "account_type": "traffic_pack"}],
                "credit_valid_days": 365,
                "renewal_rule": "单次购买，即时到账，不自动续费",
                "benefits": ["即时到账"],
                "requires_active_subscription": True,
                "order": 7,
            },
        )
        template_rows: list[PricingPlanTemplateModel] = []
        for values in templates:
            template = await db.scalar(
                select(PricingPlanTemplateModel).where(
                    PricingPlanTemplateModel.version_id == version.id,
                    PricingPlanTemplateModel.code == values["code"],
                )
            )
            if not template:
                template = PricingPlanTemplateModel(version_id=version.id, status="active", **values)
                db.add(template)
                await db.flush()
            elif not template.benefits:
                template.benefits = values.get("benefits", [])
            template.tier_code = values.get("tier_code")
            template.tier_order = values.get("tier_order", 0)
            template.order = values["order"]
            template_rows.append(template)
        app = await db.scalar(select(ClientAppModel).where(ClientAppModel.code == "bid_agent"))
        if not app:
            return
        for template in template_rows:
            exists = await db.scalar(
                select(AppCatalogPlanModel.id).where(
                    AppCatalogPlanModel.app_id == app.id,
                    AppCatalogPlanModel.code == template.code,
                )
            )
            if not exists:
                db.add(
                    AppCatalogPlanModel(
                        app_id=app.id,
                        template_id=template.id,
                        pricing_version_id=version.id,
                        code=template.code,
                        name=template.name,
                        plan_type=template.plan_type,
                        tier_code=template.tier_code,
                        tier_order=template.tier_order,
                        one_time_price_fen=template.one_time_price_fen,
                        recurring_price_fen=template.recurring_price_fen,
                        benefit_period_days=template.billing_period_days,
                        total_credits=template.total_credits,
                        release_plan=template.release_plan,
                        credit_valid_days=template.credit_valid_days,
                        benefits=template.benefits,
                        requires_active_subscription=template.requires_active_subscription,
                        order=template.order,
                        status="draft",
                    )
                )
            else:
                plan = await db.scalar(select(AppCatalogPlanModel).where(AppCatalogPlanModel.id == exists))
                if plan:
                    plan.tier_code = template.tier_code
                    plan.tier_order = template.tier_order
                    plan.order = template.order

    @staticmethod
    async def __remove_retired_features(db: AsyncSession) -> None:
        """首次安装时清理种子数据中已下线功能的菜单与角色授权。"""
        retired_menu_ids = list(
            (
                await db.scalars(
                    select(MenuModel.id).where(
                        or_(
                            MenuModel.route_path == "/ai",
                            MenuModel.component_path.like("module_ai/%"),
                            MenuModel.permission.like("module_ai:%"),
                            MenuModel.permission == "module_monitor:dashboard:query",
                        )
                    )
                )
            ).all()
        )
        if not retired_menu_ids:
            return

        await db.execute(delete(RoleMenusModel).where(RoleMenusModel.menu_id.in_(retired_menu_ids)))
        await db.execute(delete(MenuModel).where(MenuModel.id.in_(retired_menu_ids)))
        logger.info(f"✅️ 已清理下线功能菜单及授权，共 {len(retired_menu_ids)} 项")

    @staticmethod
    async def __initialize_template_menus(db: AsyncSession) -> None:
        """仅首次安装时整理模板菜单的展示默认值。"""
        decorative_menu_names = (
            "系统管理",
            "参数管理",
            "工单管理",
            "版本管理",
            "监控管理",
            "代码管理",
            "任务管理",
        )
        await db.execute(update(MenuModel).where(MenuModel.name.in_(decorative_menu_names)).values(show_badge=False, show_text_badge=None))
        await db.execute(
            update(MenuModel)
            .where(
                MenuModel.name == "传输任务",
                MenuModel.permission == "module_storage:transfer:query",
            )
            .values(icon="ri:file-transfer-line")
        )

    @staticmethod
    async def __reconcile_template_configuration(db: AsyncSession) -> None:
        """将模板演示配置同步到存量数据库，避免升级后继续显示无效内容。"""
        await db.execute(
            update(ParamsModel)
            .where(
                ParamsModel.config_key == "logo_url",
                ParamsModel.config_value.in_(
                    (
                        "logo.png",
                        "/logo.png",
                        "yuxin-logo.png",
                        "/yuxin-logo.png",
                        "/web/yuxin-logo.png",
                    )
                ),
            )
            .values(config_value="/web/logo.png")
        )
        await db.execute(
            update(ParamsModel)
            .where(
                ParamsModel.config_key == "favicon",
                ParamsModel.config_value.in_(("favicon.ico", "/favicon.ico")),
            )
            .values(config_value="/web/favicon.ico")
        )
        await db.execute(
            update(ParamsModel)
            .where(
                ParamsModel.config_key == "keep_record",
                ParamsModel.config_value.in_(("陕ICP备2025069493号-1",)),
            )
            .values(config_value="鄂ICP备2025138716号")
        )

    @staticmethod
    async def reconcile_rule_menus(db: AsyncSession) -> int:
        """移除规则中心的六个旧占位入口及其权限，保留已落地的四个模块。"""
        roots = select(MenuModel.id).where(MenuModel.route_name == "RuleEngine")
        retired = ("TriggerRule", "CategoryRule", "PriorityRule", "ResponseRule", "SurveyRule", "TrackingRule")
        pending = set(await db.scalars(select(MenuModel.id).where(MenuModel.parent_id.in_(roots), MenuModel.route_name.in_(retired))))
        removed = set(pending)
        while pending:
            pending = set(await db.scalars(select(MenuModel.id).where(MenuModel.parent_id.in_(pending)))) - removed
            removed.update(pending)
        if removed:
            await db.execute(delete(RoleMenusModel).where(RoleMenusModel.menu_id.in_(removed)))
            await db.execute(delete(MenuModel).where(MenuModel.id.in_(removed)))
        for order, route_name in enumerate(("LevelRule", "PromotionGrade", "RightsRule", "IncentiveRule"), start=1):
            await db.execute(update(MenuModel).where(MenuModel.parent_id.in_(roots), MenuModel.route_name == route_name).values(order=order))
        return len(removed)

    @staticmethod
    async def __initialize_workspace_configuration(db: AsyncSession) -> None:
        """仅首次安装时写入工作台模块和默认菜单；存量变更使用 Alembic。"""
        await InitializeData.reconcile_rule_menus(db)
        duplicate_menu_ids = list((await db.scalars(select(MenuModel.id).where(MenuModel.route_name.in_(["ComplaintTicket", "FeedbackManagement"])))).all())
        if duplicate_menu_ids:
            child_ids = list((await db.scalars(select(MenuModel.id).where(MenuModel.parent_id.in_(duplicate_menu_ids)))).all())
            all_ids = [*duplicate_menu_ids, *child_ids]
            await db.execute(delete(RoleMenusModel).where(RoleMenusModel.menu_id.in_(all_ids)))
            if child_ids:
                await db.execute(delete(MenuModel).where(MenuModel.id.in_(child_ids)))
            await db.execute(delete(MenuModel).where(MenuModel.id.in_(duplicate_menu_ids)))

        retired_workspace_ids = list(
            (
                await db.scalars(
                    select(MenuModel.id).where(
                        or_(
                            MenuModel.route_name == "AllResources",
                            MenuModel.permission == "workspace:resource:all:list",
                        )
                    )
                )
            ).all()
        )
        if retired_workspace_ids:
            await db.execute(delete(RoleMenusModel).where(RoleMenusModel.menu_id.in_(retired_workspace_ids)))
            await db.execute(delete(MenuModel).where(MenuModel.id.in_(retired_workspace_ids)))

        legacy_user_menu = await db.scalar(
            select(MenuModel).where(
                or_(MenuModel.route_name == "UserSegmentation", MenuModel.permission == "workspace:user:segmentation:list"),
                MenuModel.is_deleted == False,
            )
        )
        if legacy_user_menu:
            legacy_user_menu.name = "用户管理"
            legacy_user_menu.title = "用户管理"
            legacy_user_menu.route_name = "ClientUserManagement"
            legacy_user_menu.route_path = "users"
            legacy_user_menu.permission = "workspace:user:management:list"
            legacy_user_menu.icon = "ri:user-settings-line"
            legacy_user_menu.component_path = "module_client/user/index"

        modules_by_code: dict[str, WorkspaceModuleModel] = {}
        for seed in MODULE_SEEDS:
            module = await db.scalar(select(WorkspaceModuleModel).where(WorkspaceModuleModel.code == seed["code"]))
            if not module:
                module = WorkspaceModuleModel(**seed)
                db.add(module)
                await db.flush()
            else:
                module.name = seed["name"]
                module.description = seed["description"]
                module.icon = seed["icon"]
                module.accent = seed["accent"]
                await db.flush()
            modules_by_code[module.code] = module

        platform_module = modules_by_code["platform"]
        await db.execute(
            update(MenuModel)
            .where(
                MenuModel.parent_id.is_(None),
                MenuModel.scope == "web",
                MenuModel.module_id.is_(None),
                MenuModel.is_deleted == False,
            )
            .values(module_id=platform_module.id)
        )

        async def ensure_menu(parent_id: int | None, values: dict[str, Any]) -> MenuModel:
            route_path = values.get("route_path")
            permission = values.get("permission")
            stmt = select(MenuModel).where(MenuModel.parent_id == parent_id, MenuModel.is_deleted == False)
            if route_path is not None:
                stmt = stmt.where(MenuModel.route_path == route_path)
            elif permission:
                stmt = stmt.where(MenuModel.permission == permission)
            else:
                stmt = stmt.where(MenuModel.name == values["name"])
            menu = await db.scalar(stmt)
            if menu:
                return menu
            menu = MenuModel(**values, parent_id=parent_id)
            db.add(menu)
            await db.flush()
            return menu

        for seed in WORKSPACE_MENU_SEEDS:
            module = modules_by_code[seed["module"]]
            root = await ensure_menu(
                None,
                {
                    "name": seed["name"],
                    "type": 1,
                    "icon": seed["icon"],
                    "order": seed["order"],
                    "permission": None,
                    "route_name": seed["route_name"],
                    "route_path": seed["route_path"],
                    "component_path": None,
                    "redirect": seed["redirect"],
                    "title": seed["name"],
                    "status": 0,
                    "scope": "web",
                    "always_show": True,
                    "description": "运营平台首期模块入口",
                    "module_id": module.id,
                },
            )
            root.name = seed["name"]
            root.title = seed["name"]
            root.icon = seed["icon"]
            root.order = seed["order"]
            root.redirect = seed["redirect"]
            root.module_id = module.id
            root.hidden = False
            for name, route_name, route_path, permission, icon, order in seed["children"]:
                description = "功能建设中"
                component_path = "workspace/placeholder/index"
                component_paths = {
                    "AgreementManagement": "module_agreement/index",
                    "FinanceOverview": "module_finance/overview/index",
                    "FinanceOrders": "module_finance/orders/index",
                    "FinanceRefunds": "module_finance/refunds/index",
                    "FinanceBills": "module_finance/bills/index",
                    "FinanceIssues": "module_finance/issues/index",
                    "LevelRule": "module_growth/usage/index",
                    "GrowthPayout": "module_growth/payout/index",
                    "PromotionGrade": "module_growth/promotion/index",
                    "RightsRule": "module_growth/rights/index",
                    "IncentiveRule": "module_growth/incentive/index",
                    "BudgetPriceSystem": "module_billing/pricing-standard/index",
                    "BudgetProductManagement": "module_client/app/index",
                    "BudgetProductRateCard": "module_billing/catalog/index",
                    "BudgetPricingStrategy": "module_billing/pricing-strategy/index",
                    "BudgetSubscriptions": "module_billing/subscription/index",
                    "ClientUserManagement": "module_client/user/index",
                    "SupportTickets": "module_user_operations/support/index",
                    "MessageTrigger": "module_user_operations/message/index",
                    "ModelManagement": "module_model_gateway/management/index",
                    "ClientModelConfiguration": "module_model_gateway/client/index",
                    "OpportunityResources": "module_operations/opportunity/index",
                    "OperationsOverview": "module_operations/overview/index",
                }
                component_path = component_paths.get(route_name, component_path)
                if route_name == "ModelManagement":
                    description = "统一管理模型厂家、API凭证、模型版本、成本与上下架状态"
                elif route_name == "BudgetProductManagement":
                    description = "维护独立运营与数据隔离的客户端应用，不配置动态能力和输出成果"
                elif route_name == "ClientUserManagement":
                    description = "按当前客户端管理最终用户、档案、标签、订阅、积分与模型用量"
                elif route_name == "PaymentChannelManagement":
                    description = "管理微信支付与支付宝渠道，敏感密钥仅从环境变量读取"
                    component_path = "module_payment/channel/index"
                child = await ensure_menu(
                    root.id,
                    {
                        "name": name,
                        "type": 2,
                        "icon": icon,
                        "order": order,
                        "permission": permission,
                        "route_name": route_name,
                        "route_path": route_path,
                        "component_path": component_path,
                        "redirect": None,
                        "title": name,
                        "status": 0,
                        "scope": "web",
                        "description": description,
                        "module_id": None,
                    },
                )
                if (
                    child.description
                    in {
                        "功能建设中",
                        "统一管理模型厂家、API凭证、模型版本、成本与上下架状态",
                        "维护独立运营与数据隔离的客户端应用，不配置动态能力和输出成果",
                        "管理微信支付与支付宝渠道，敏感密钥仅从环境变量读取",
                    }
                    or not child.title
                    or not child.icon
                ):
                    child.name = name
                    child.title = name
                    child.icon = icon
                    child.route_name = route_name
                    child.permission = permission
                    child.order = order
                    child.component_path = component_path
                    child.description = description
                # 已存在的菜单可能带有老板原型阶段的自定义说明，但已经落地的
                # 页面必须始终指向真实组件，不能继续停留在占位页。
                if route_name in component_paths or route_name == "PaymentChannelManagement":
                    child.component_path = component_path
                if route_name in {"ModelManagement", "ClientModelConfiguration"}:
                    child.order = order
                    child.name = name
                    child.title = name
                    child.icon = icon
                child.hidden = route_name == "OpportunityResources"
                for action_order, (action_name, action_permission) in enumerate(
                    WORKSPACE_ACTION_SEEDS.get(route_name, ()),
                    start=1,
                ):
                    await ensure_menu(
                        child.id,
                        {
                            "name": action_name,
                            "type": 3,
                            "icon": None,
                            "order": action_order,
                            "permission": action_permission,
                            "route_name": None,
                            "route_path": None,
                            "component_path": None,
                            "redirect": None,
                            "title": action_name,
                            "status": 0,
                            "scope": "web",
                            "description": f"{name}{action_name}权限",
                            "module_id": None,
                        },
                    )
                if route_name == "PaymentChannelManagement":
                    await ensure_menu(
                        child.id,
                        {
                            "name": "编辑",
                            "type": 3,
                            "icon": None,
                            "order": 1,
                            "permission": "module_payment:channel:edit",
                            "route_name": None,
                            "route_path": None,
                            "component_path": None,
                            "redirect": None,
                            "title": "编辑",
                            "status": 0,
                            "scope": "web",
                            "description": "支付渠道编辑与启停权限",
                            "module_id": None,
                        },
                    )

        system_root = await db.scalar(
            select(MenuModel).where(
                MenuModel.parent_id.is_(None),
                MenuModel.route_path == "/system",
                MenuModel.scope == "web",
                MenuModel.is_deleted == False,
            )
        )
        if system_root:
            await db.execute(
                update(MenuModel)
                .where(
                    MenuModel.parent_id == system_root.id,
                    MenuModel.permission == "module_system:user:query",
                    MenuModel.is_deleted == False,
                )
                .values(name="运营人员", title="运营人员")
            )
            module_menu = await ensure_menu(
                system_root.id,
                {
                    "name": "工作台管理",
                    "type": 2,
                    "icon": "ri:apps-2-line",
                    "order": 2,
                    "permission": "module_system:module:list",
                    "route_name": "WorkspaceModuleManagement",
                    "route_path": "module",
                    "component_path": "module_system/module/index",
                    "redirect": None,
                    "title": "工作台管理",
                    "status": 0,
                    "scope": "web",
                    "description": "工作台模块入口与状态管理",
                    "module_id": None,
                },
            )
            module_menu.name = "工作台管理"
            module_menu.title = "工作台管理"
            for order, (name, permission) in enumerate(
                (
                    ("新增", "module_system:module:add"),
                    ("编辑", "module_system:module:edit"),
                    ("删除", "module_system:module:delete"),
                ),
                start=1,
            ):
                await ensure_menu(
                    module_menu.id,
                    {
                        "name": name,
                        "type": 3,
                        "icon": None,
                        "order": order,
                        "permission": permission,
                        "route_name": None,
                        "route_path": None,
                        "component_path": None,
                        "redirect": None,
                        "title": name,
                        "status": 0,
                        "scope": "web",
                        "description": "模块管理操作权限",
                        "module_id": None,
                    },
                )

        logger.info("✅️ 工作台模块与默认菜单初始化完成")

    @staticmethod
    async def __reconcile_payment_channels(db: AsyncSession) -> None:
        """支付渠道默认值独立于菜单初始化，保留已有渠道配置。"""
        for values in (
            {
                "provider": "wechat",
                "name": "微信支付",
                "enabled": False,
                "mode": "production",
                "fee_rate": 0.6,
                "settlement_cycle": "T+1",
                "scenes": ["PC收银台", "二维码支付"],
                "description": "微信支付商户平台渠道",
                "order": 1,
                "status": 0,
            },
            {
                "provider": "alipay",
                "name": "支付宝",
                "enabled": False,
                "mode": "production",
                "fee_rate": 0.6,
                "settlement_cycle": "T+1",
                "scenes": ["PC收银台", "二维码支付"],
                "description": "支付宝开放平台渠道",
                "order": 2,
                "status": 0,
            },
        ):
            channel = await db.scalar(select(PaymentChannelModel).where(PaymentChannelModel.provider == values["provider"]))
            if not channel:
                db.add(PaymentChannelModel(**values))

    async def __init_data(self, db: AsyncSession, *, initialize_navigation: bool) -> None:
        """按依赖顺序初始化各表种子数据"""
        dict_type_mapping: dict[str, Any] = {}

        for model in self.prepare_init_models:
            table_name = model.__tablename__
            if not initialize_navigation and model in (MenuModel, WorkspaceModuleModel):
                continue

            data = await self.__load_json(table_name)
            if not data:
                logger.info(f"⏭️  跳过 {table_name} 表，无初始化数据")
                continue

            # 已有数据则跳过
            count = await db.execute(select(func.count()).select_from(model))
            if count.scalar():
                logger.info(f"⏭️  跳过 {table_name} 表数据初始化（表已有数据）")
                continue

            try:
                if table_name in self._RECURSIVE_TABLES:
                    objs = self.__create_objects_with_children(data, model)
                elif table_name == "sys_dict_type":
                    objs = []
                    for item in data:
                        obj = model(**item)
                        objs.append(obj)
                        dict_type_mapping[item["dict_type"]] = obj
                elif table_name == "sys_dict_data":
                    objs = []
                    for item in data:
                        dict_type_str = item.get("dict_type")
                        if dict_type_str not in dict_type_mapping:
                            logger.warning(f"⚠️  未找到字典类型 {dict_type_str}，跳过")
                            continue
                        item["dict_type_id"] = dict_type_mapping[dict_type_str].id
                        objs.append(model(**item))
                else:
                    objs = [model(**item) for item in data]

                if objs:
                    db.add_all(objs)
                    await db.flush()
                    logger.info(f"✅️ 已向 {table_name} 写入初始化数据")
                else:
                    logger.info(f"⏭️  跳过 {table_name} 表数据初始化（无有效数据）")

            except Exception:
                logger.error(f"❌️ 初始化 {table_name} 表数据失败")
                raise

    @staticmethod
    def __create_objects_with_children(data: list[dict], model_class: type) -> list:
        """递归创建树形模型实例，处理嵌套 children 并注入 parent_id"""

        def _create(obj_data: dict) -> Any:
            children_data = obj_data.pop("children", [])
            obj = model_class(**obj_data)

            # 子节点通过 relationship 自动设置 parent_id
            if children_data:
                obj.children = [_create(child) for child in children_data]

            return obj

        return [_create(item) for item in data]

    async def __load_json(self, filename: str) -> list[dict]:
        """读取并解析种子数据 JSON 文件"""
        json_path = SCRIPT_DIR / f"{filename}.json"
        if not json_path.exists():
            return []

        try:
            with open(json_path, encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"❌️ 解析 {json_path} 失败: {e!s}")
            raise
        except Exception as e:
            logger.error(f"❌️ 读取 {json_path} 失败: {e!s}")
            raise
