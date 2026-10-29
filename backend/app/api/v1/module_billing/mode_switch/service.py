"""Calculate the switch reminder and apply paid changes atomically."""

from datetime import UTC, datetime

from sqlalchemy import or_, select

from app.api.v1.module_billing.duration import utc
from app.api.v1.module_billing.model import AppCatalogPlanModel, SubscriptionCycleModel, SubscriptionModel
from app.api.v1.module_client.app.model_policy import allowed_modes, billing_user, current_mode, get_model_policy
from app.api.v1.module_finance.model import FinanceAuditModel
from app.api.v1.module_payment.order.model import PaymentOrderModel
from app.core.exceptions import CustomException

from .assets import remaining_assets, reset_assets
from .schema import ModeSwitchPreviewOut


async def preview_switch(db, auth, data):
    app = await get_model_policy(db, auth.app_id, lock=True)
    user = await billing_user(db, app, auth.user.id, lock=True)
    if user.mode_version != data.expected_mode_version:
        raise CustomException(msg="当前模式已变化，请刷新后重试", status_code=409)
    plan = await db.scalar(
        select(AppCatalogPlanModel).where(
            AppCatalogPlanModel.id == data.catalog_plan_id, AppCatalogPlanModel.app_id == app.id, AppCatalogPlanModel.is_deleted == False, AppCatalogPlanModel.status == "on_sale"
        )
    )
    now = datetime.now(UTC)
    if (
        not plan
        or plan.entitlement_kind != data.target_mode
        or data.target_mode not in allowed_modes(app)
        or (plan.effective_from and utc(plan.effective_from) > now)
        or (plan.effective_until and utc(plan.effective_until) <= now)
    ):
        raise CustomException(msg="该套餐当前不可购买，请刷新后重试", status_code=409)
    source = current_mode(app, user)
    if source != data.target_mode and plan.plan_type != "subscription":
        raise CustomException(msg="切换模式请选择订阅套餐，积分包不能用于切换模式", status_code=422)
    assets = await remaining_assets(db, app.id, user.id, source)
    summary, blocked = assets[:2]
    if source == data.target_mode:
        summary = {"available_credits_to_expire": 0, "pending_credits_to_expire": 0, "duration_seconds_to_expire": 0, "items": []}
    review = await db.scalar(
        select(PaymentOrderModel.id)
        .where(
            PaymentOrderModel.app_id == app.id,
            PaymentOrderModel.user_id == user.id,
            PaymentOrderModel.mode_switch["status"].as_string() == "requires_confirmation",
            or_(PaymentOrderModel.status == "paid", PaymentOrderModel.paid_at.is_not(None)),
            PaymentOrderModel.replaced_by_order_no.is_(None),
            PaymentOrderModel.is_deleted == False,
        )
        .limit(1)
    )
    if review:
        blocked = "存在已收款但权益待财务核对的订单，请先联系运营处理"
    return ModeSwitchPreviewOut(
        source_mode=source,
        target_mode=data.target_mode,
        policy_version=app.model_policy_version,
        mode_version=user.mode_version,
        can_switch=blocked is None,
        blocked_reason=blocked,
        requires_reset_confirmation=source is not None and source != data.target_mode,
        reset_summary=summary,
    )


async def confirm_for_order(db, app, user, plan, confirmation):
    source = current_mode(app, user)
    if source == plan.entitlement_kind:
        return None
    if plan.plan_type != "subscription":
        raise CustomException(msg="请先购买对应模式的订阅套餐", status_code=409)
    if confirmation is None:
        # New users choose their first mode through the selected subscription.
        if source is None:
            return None
        raise CustomException(msg="请先预览并确认旧模式剩余权益将被重置", status_code=409)
    if confirmation.expected_mode_version != user.mode_version:
        raise CustomException(msg="当前模式已变化，请刷新后重新确认", status_code=409)
    _, blocked, *_ = await remaining_assets(db, app.id, user.id, source)
    if blocked:
        raise CustomException(msg=blocked, status_code=409)
    return True


def needs_review(order, source, target, message):
    order.mode_switch = {**(order.mode_switch or {}), "id": order.order_no, "source_mode": source, "target_mode": target, "status": "requires_confirmation", "message": message}
    order.failure_reason = message


async def fulfill_paid_order(db, order):
    from app.api.v1.module_billing.service import SubscriptionService

    if order.status != "paid" or order.paid_at is None:
        raise CustomException(msg="订单尚未确认支付，不能变更订阅权益", status_code=409)
    if order.replaced_by_order_no:
        target = order.plan_snapshot.get("entitlement_kind", "credits")
        needs_review(order, (order.mode_switch or {}).get("source_mode", target), target, "已被替换的原订单收到付款，待财务核对或退款；不重复发放权益")
        return False
    if order.mode_switch and order.mode_switch.get("status") == "completed":
        return True
    if order.mode_switch and order.mode_switch.get("status") in {"requires_confirmation", "cancelled"}:
        return False
    app = await get_model_policy(db, order.app_id, lock=True)
    user = await billing_user(db, app, order.user_id, lock=True)
    source, target = current_mode(app, user), order.plan_snapshot.get("entitlement_kind", "credits")
    expected = order.plan_snapshot.get("mode_version")
    if target not in allowed_modes(app) or (expected is not None and expected != user.mode_version) or (app.service_mode == "user_choice" and expected is None):
        needs_review(order, source, target, "支付成功，服务模式或用户权益已变化，待财务核对或退款，请勿重复付款")
        return False
    if target == "credits" and order.plan_snapshot.get("plan_type") == "subscription":
        active = await db.scalar(
            select(SubscriptionModel).where(SubscriptionModel.app_id == app.id, SubscriptionModel.user_id == user.id, SubscriptionModel.status == "active", SubscriptionModel.is_deleted == False)
        )
        current_plan = await db.get(AppCatalogPlanModel, active.catalog_plan_id) if active else None
        already_fulfilled = await db.scalar(select(SubscriptionCycleModel.id).where(SubscriptionCycleModel.app_id == app.id, SubscriptionCycleModel.order_id == order.id).limit(1))
        if (
            active
            and active.entitlement_kind == "credits"
            and utc(active.current_period_end) > datetime.now(UTC)
            and current_plan
            and current_plan.id != order.catalog_plan_id
            and int(order.plan_snapshot.get("tier_order") or 0) <= current_plan.tier_order
            and not already_fulfilled
        ):
            needs_review(order, source, target, "原订单付款前已购买其他同等级或更高等级套餐，待财务核对或退款，不自动覆盖当前订阅")
            return False
    reset = None
    if source is not None and source != target:
        switch = order.mode_switch or {}
        assets = await remaining_assets(db, app.id, user.id, source)
        if (
            switch.get("reset_authorized") is not True
            or switch.get("source_mode") != source
            or switch.get("target_mode") != target
            or order.plan_snapshot.get("model_policy_version") != app.model_policy_version
            or assets[1]
        ):
            needs_review(order, source, target, "支付成功，模式已变化或权益尚未结算，待财务核对或退款，请勿重复付款")
            return False
        reset = await reset_assets(db, order, assets)
    before_version = user.mode_version
    changed = user.active_billing_mode != target
    if changed:
        user.active_billing_mode = target
        if source != target:
            user.mode_version += 1
    await db.flush()
    await SubscriptionService(db).activate_paid_order(
        app_id=order.app_id, user_id=order.user_id, order_id=order.id, catalog_plan_id=order.catalog_plan_id, plan_snapshot=order.plan_snapshot, auto_renew=order.auto_renew_requested
    )
    if changed or reset is not None:
        order.mode_switch = {
            **(order.mode_switch or {}),
            "id": order.order_no,
            "status": "completed",
            "source_mode": source,
            "target_mode": target,
            "result_mode_version": user.mode_version,
            "reset_result": reset,
            "message": "订阅模式已生效",
        }
        db.add(
            FinanceAuditModel(
                app_id=app.id,
                object_type="order",
                object_id=str(order.id),
                action="billing_mode_switch",
                reason="用户确认购买对应模式订阅；重置生效时旧模式的全部剩余权益",
                before={"mode": source, "mode_version": before_version},
                after={"mode": target, "mode_version": user.mode_version, "reset": reset},
            )
        )
    await db.flush()
    return True
