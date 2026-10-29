"""Application scope and user billing mode are separate authorization decisions."""

from datetime import UTC, datetime

from sqlalchemy import func, select

from app.core.exceptions import CustomException

from .model import ClientAppModel


def allowed_modes(app):
    mode = app.service_mode
    if mode == "user_choice":
        return ["credits", "duration"]
    if mode in {"credits_only", "duration_only"}:
        return ["credits" if mode == "credits_only" else "duration"]
    raise CustomException(msg="服务模式配置异常，请联系管理员", status_code=409)


async def get_model_policy(db, app_id, *, lock=False):
    if not app_id:
        raise CustomException(msg="请先选择客户端", status_code=409)
    stmt = select(ClientAppModel).where(ClientAppModel.id == app_id, ClientAppModel.is_deleted == False).execution_options(populate_existing=True)
    if lock:
        stmt = stmt.with_for_update()
    app = await db.scalar(stmt)
    if not app:
        raise CustomException(msg="客户端不存在", status_code=404)
    return app


async def billing_user(db, app, user_id, *, lock=False):
    from app.api.v1.module_client.user.model import ClientUserModel

    stmt = select(ClientUserModel).where(ClientUserModel.app_id == app.id, ClientUserModel.id == user_id, ClientUserModel.is_deleted == False).execution_options(populate_existing=True)
    if lock:
        stmt = stmt.with_for_update()
    user = await db.scalar(stmt)
    if not user:
        raise CustomException(msg="当前客户端下不存在该用户", status_code=404)
    return user


def current_mode(app, user):
    if user.active_billing_mode not in {None, "credits", "duration"}:
        raise CustomException(msg="用户订阅模式异常，请联系运营核对", status_code=409)
    # Single-mode applications retain the original onboarding behavior.
    return user.active_billing_mode or (allowed_modes(app)[0] if app.service_mode != "user_choice" else None)


async def require_platform_model(db, app_id, *, user_id=None, lock=False):
    app = await get_model_policy(db, app_id, lock=lock)
    if "credits" not in allowed_modes(app):
        raise CustomException(msg="当前客户端不支持平台模型或新增积分操作", status_code=403)
    if user_id is not None:
        user = await billing_user(db, app, user_id, lock=lock)
        if current_mode(app, user) != "credits":
            raise CustomException(msg="用户当前未使用含 token 费用模式，请先完成订阅模式选择", status_code=403)
    return app


async def order_matches_model_policy(db, app_id, snapshot):
    app = await get_model_policy(db, app_id, lock=True)
    return snapshot.get("entitlement_kind", "credits") in allowed_modes(app)


async def change_model_policy(db, app, enabled, expected_version):
    from app.api.v1.module_billing.model import AppCatalogPlanModel, CreditAccountModel, SubscriptionCycleModel, SubscriptionModel
    from app.api.v1.module_client.user.model import ClientUserModel
    from app.api.v1.module_payment.order.model import PaymentOrderModel

    target = ("credits_only" if enabled else "duration_only") if isinstance(enabled, bool) else enabled
    if target not in {"credits_only", "duration_only", "user_choice"}:
        raise CustomException(msg="服务模式无效", status_code=422)
    if expected_version is not None and expected_version != app.model_policy_version:
        raise CustomException(msg="客户端配置已更新，请刷新后重试", status_code=409)
    if target == app.service_mode:
        return
    if target != "user_choice":
        kind = "credits" if target == "credits_only" else "duration"
        active = await db.scalar(
            select(SubscriptionModel.id)
            .where(
                SubscriptionModel.app_id == app.id,
                SubscriptionModel.is_deleted == False,
                SubscriptionModel.entitlement_kind != kind,
                SubscriptionModel.status == "active",
                SubscriptionModel.current_period_end > datetime.now(UTC),
            )
            .limit(1)
        )
        cycles = await db.scalar(
            select(SubscriptionCycleModel.id)
            .where(
                SubscriptionCycleModel.app_id == app.id,
                SubscriptionCycleModel.is_deleted == False,
                SubscriptionCycleModel.status == "active",
                SubscriptionCycleModel.ends_at > datetime.now(UTC),
                func.coalesce(SubscriptionCycleModel.plan_snapshot["entitlement_kind"].as_string(), "credits") != kind,
            )
            .limit(1)
        )
        unfinished = await db.scalar(
            select(PaymentOrderModel.id).where(PaymentOrderModel.app_id == app.id, PaymentOrderModel.is_deleted == False, PaymentOrderModel.status.in_(["created", "pending", "confirming"])).limit(1)
        )
        review = await db.scalar(
            select(PaymentOrderModel.id).where(PaymentOrderModel.app_id == app.id, PaymentOrderModel.mode_switch["status"].as_string().in_(["processing", "requires_confirmation"])).limit(1)
        )
        credits = None
        if kind == "duration":
            credits = await db.scalar(
                select(CreditAccountModel.id)
                .where(CreditAccountModel.app_id == app.id, CreditAccountModel.is_deleted == False, (CreditAccountModel.available + CreditAccountModel.pending + CreditAccountModel.reserved) > 0)
                .limit(1)
            )
        if active or cycles or unfinished or review or credits:
            raise CustomException(msg="存在未结束的订阅权益、积分或待处理订单，请先核对或退款后再缩小服务模式范围", status_code=409)
        plans = await db.scalars(
            select(AppCatalogPlanModel).where(
                AppCatalogPlanModel.app_id == app.id, AppCatalogPlanModel.is_deleted == False, AppCatalogPlanModel.status == "on_sale", AppCatalogPlanModel.entitlement_kind != kind
            )
        )
        for plan in plans:
            plan.status = "off_sale"
        # Do not silently change a user's selected mode; incompatible users must
        # explicitly purchase/confirm the new mode. Runtime fails closed meanwhile.
    else:
        # Preserve single-mode users when expanding application scope.
        from sqlalchemy import update

        old = allowed_modes(app)[0]
        await db.execute(update(ClientUserModel).where(ClientUserModel.app_id == app.id, ClientUserModel.active_billing_mode.is_(None)).values(active_billing_mode=old))
    app.service_mode = target
    app.platform_model_enabled = target != "duration_only"
    app.model_policy_version += 1
