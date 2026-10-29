"""Local mode is time-based, isolated, and never an unlimited gateway account."""

import importlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from auth_helpers import register_with_sms
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select, text

from app.api.v1.module_billing.duration import utc
from app.api.v1.module_billing.model import AppCatalogPlanModel, CreditGrantModel, CreditLedgerModel, PricingStandardVersionModel, SubscriptionCycleModel
from app.api.v1.module_billing.schema import CatalogPlanCreateSchema, CatalogPlanUpdateSchema, PricingStrategyCreateSchema, PricingTemplateSchema
from app.api.v1.module_billing.service import CatalogService, CreditService, SubscriptionService
from app.api.v1.module_client.app.model import ClientAppModel
from app.api.v1.module_client.app.model_policy import change_model_policy, require_platform_model
from app.api.v1.module_client.app.schema import ClientAppUpdateSchema
from app.api.v1.module_client.app.service import ClientAppService
from app.api.v1.module_client.runtime_config import runtime_config
from app.api.v1.module_client.user.model import ClientUserModel
from app.api.v1.module_finance.entitlements import preview_order_entitlements, terminate_order_entitlements
from app.api.v1.module_payment.channel.model import AppPaymentChannelModel, PaymentChannelModel
from app.api.v1.module_payment.channel.service import PaymentChannelService
from app.api.v1.module_payment.order import service as payment_module
from app.api.v1.module_payment.order.model import PaymentOrderModel
from app.api.v1.module_payment.order.providers import VerifiedPayment
from app.api.v1.module_payment.order.schema import PaymentOrderCreate
from app.api.v1.module_payment.order.service import PaymentCallbackService, PaymentOrderService
from app.core.base_schema import AuthSchema, CoreUserSchema
from app.core.database import async_db_session
from app.core.exceptions import CustomException


def plan_payload(version_id, days=30, **overrides):
    return dict(
        pricing_version_id=version_id,
        code=f"days_{uuid4().hex[:8]}",
        name=f"客户端使用{days}天",
        entitlement_kind="duration",
        plan_type="subscription",
        benefit_period_days=days,
        one_time_price_fen=1000,
        recurring_price_fen=900,
        total_credits=0,
        release_plan=[],
        status="on_sale",
        **overrides,
    )


async def scope(db, enabled=False):
    app = ClientAppModel(code=f"local_{uuid4().hex[:8]}", name="时长验证客户端", status="active", platform_model_enabled=enabled)
    db.add(app)
    await db.flush()
    user = ClientUserModel(app_id=app.id, username=f"member_{uuid4().hex[:8]}", password_hash="test-only", status="active")
    db.add(user)
    await db.flush()
    version = await db.scalar(select(PricingStandardVersionModel).where(PricingStandardVersionModel.status == "published"))
    client = AuthSchema(app_id=app.id, actor_type="client", user=CoreUserSchema(id=user.id, username=user.username))
    staff = AuthSchema(app_id=app.id, actor_type="staff", user=CoreUserSchema(id=1, username="admin", is_superuser=True))
    return app, user, version, client, staff


async def paid_order(db, app, user, plan):
    snapshot = {"name": plan.name, "plan_type": "subscription", "entitlement_kind": "duration", "benefit_period_days": plan.benefit_period_days, "total_credits": 0, "release_plan": []}
    order = PaymentOrderModel(
        app_id=app.id,
        user_id=user.id,
        catalog_plan_id=plan.id,
        order_no=uuid4().hex,
        idempotency_key=uuid4().hex,
        provider="wechat",
        purchase_type="first",
        amount_fen=1000,
        plan_snapshot=snapshot,
        status="paid",
        paid_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )
    db.add(order)
    await db.flush()
    sub = await SubscriptionService(db).activate_paid_order(app_id=app.id, user_id=user.id, order_id=order.id, catalog_plan_id=plan.id, plan_snapshot=snapshot, auto_renew=False)
    return order, sub


@pytest.mark.parametrize("days", [7, 30, 90])
def test_duration_schema_and_credit_constraints(days):
    payload = plan_payload(1, days)
    assert CatalogPlanCreateSchema(**payload).total_credits == 0
    template = {k: v for k, v in payload.items() if k not in {"pricing_version_id", "benefit_period_days", "status"}}
    assert PricingTemplateSchema(**template, billing_period_days=days).release_plan == []
    for changes in ({"entitlement_kind": "credits"}, {"total_credits": 1}, {"plan_type": "credit_pack"}, {"requires_active_subscription": True}, {"benefit_period_days": 0}):
        with pytest.raises(ValidationError):
            CatalogPlanCreateSchema(**{**payload, **changes})


async def test_duration_stacks_different_products_and_refund_preserves_other_orders(test_client):
    del test_client
    async with async_db_session() as db:
        try:
            app, user, version, client, staff = await scope(db)
            catalog = CatalogService(staff, db)
            first = await catalog.create(CatalogPlanCreateSchema(**plan_payload(version.id, 7)))
            second = await catalog.create(CatalogPlanCreateSchema(**plan_payload(version.id, 30)))
            before = await runtime_config(db, client)
            assert before.allow_custom_model and not before.authorization.can_start_task
            order1, sub = await paid_order(db, app, user, first)
            first_end = utc(sub.current_period_end)
            order2, sub = await paid_order(db, app, user, second)
            assert utc(sub.current_period_end) == first_end + timedelta(days=30)
            end = utc(sub.current_period_end)
            await SubscriptionService(db).activate_paid_order(app_id=app.id, user_id=user.id, order_id=order2.id, catalog_plan_id=second.id, plan_snapshot=order2.plan_snapshot, auto_renew=False)
            assert utc(sub.current_period_end) == end
            assert await db.scalar(select(func.count()).select_from(CreditGrantModel).where(CreditGrantModel.app_id == app.id)) == 0
            assert await db.scalar(select(func.count()).select_from(CreditLedgerModel).where(CreditLedgerModel.app_id == app.id)) == 0
            config = await runtime_config(db, client)
            assert config.billing_mode == "duration" and config.authorization.can_start_task
            plans = await CatalogService(client, db).list_plans(public_only=True)
            assert len(plans) == 2 and all(p.eligible and p.purchase_type == "renewal" for p in plans)
            preview = await preview_order_entitlements(db, order1, "terminate")
            assert 29.99 < (preview["after"]["ends_at"] - datetime.now(UTC)).total_seconds() / 86400 <= 30
            await terminate_order_entitlements(db, order1, "test-refund")
            assert 29.99 < (utc(sub.current_period_end) - datetime.now(UTC)).total_seconds() / 86400 <= 30
            after = utc(sub.current_period_end)
            await terminate_order_entitlements(db, order1, "test-refund")
            assert utc(sub.current_period_end) == after
        finally:
            await db.rollback()


async def test_mode_scope_switch_guards_and_catalog_validation(test_client):
    del test_client
    async with async_db_session() as db:
        try:
            app, user, version, client, staff = await scope(db)
            catalog = CatalogService(staff, db)
            plan = await catalog.create(CatalogPlanCreateSchema(**plan_payload(version.id)))
            with pytest.raises(CustomException, match="不支持平台"):
                await require_platform_model(db, app.id)
            with pytest.raises(CustomException, match="不支持平台"):
                await CreditService(db).adjust(app.id, user.id, 100, "不应发放", 1)
            with pytest.raises(CustomException):
                await catalog.update(plan.id, CatalogPlanUpdateSchema(total_credits=100))
            with pytest.raises(CustomException, match="不能变更"):
                await catalog.update(plan.id, CatalogPlanUpdateSchema(entitlement_kind="credits"))
            other, _, _, _, other_staff = await scope(db, enabled=True)
            with pytest.raises(CustomException, match="不存在"):
                await CatalogService(other_staff, db).update(plan.id, CatalogPlanUpdateSchema(name="越权修改"))
            with pytest.raises(CustomException, match="不一致"):
                await CatalogService(other_staff, db).create(CatalogPlanCreateSchema(**plan_payload(version.id)))
            await ClientAppService(staff, db).update(app.id, ClientAppUpdateSchema(platform_model_enabled=True, expected_policy_version=1))
            assert app.platform_model_enabled and app.model_policy_version == 2
            assert (await db.get(AppCatalogPlanModel, plan.id)).status == "off_sale"
            assert other.platform_model_enabled
            with pytest.raises(CustomException, match="刷新"):
                await change_model_policy(db, app, False, 1)
            await change_model_policy(db, app, False, 2)
            order, _ = await paid_order(db, app, user, plan)
            with pytest.raises(CustomException, match="权益"):
                await change_model_policy(db, app, True, 3)
            order.status = "pending"
            await db.flush()
            with pytest.raises(CustomException, match="权益"):
                await change_model_policy(db, app, True, 3)
        finally:
            await db.rollback()


async def test_real_checkout_callback_snapshot_and_no_credit_release(test_client, monkeypatch):
    del test_client
    async with async_db_session() as db:
        try:
            app, user, version, client, staff = await scope(db)
            plan = await CatalogService(staff, db).create(CatalogPlanCreateSchema(**plan_payload(version.id, 90)))
            channel = await db.scalar(select(PaymentChannelModel).where(PaymentChannelModel.provider == "wechat"))
            channel.enabled, channel.mode = True, "production"
            db.add(AppPaymentChannelModel(app_id=app.id, channel_id=channel.id, enabled=True))
            await db.flush()
            monkeypatch.setattr(PaymentChannelService, "_to_schema", lambda *_: SimpleNamespace(configured=True))

            async def checkout(*_):
                return "weixin://test-only"

            monkeypatch.setattr(payment_module, "create_wechat_native_order", checkout)
            data = PaymentOrderCreate(catalog_plan_id=plan.id, provider="wechat", idempotency_key=uuid4().hex)
            order = await PaymentOrderService(client, db).create(data)
            assert order.plan_snapshot["entitlement_kind"] == "duration"
            assert order.plan_snapshot["platform_model_enabled"] is False
            # Catalog edits after checkout cannot shorten this purchased duration.
            await CatalogService(staff, db).update(plan.id, CatalogPlanUpdateSchema(benefit_period_days=7))
            payment = VerifiedPayment(callback_id=uuid4().hex, order_no=order.order_no, provider_trade_no=uuid4().hex, amount_fen=1000, paid_at=datetime.now(UTC), payload_digest="a" * 64)
            await PaymentCallbackService(db).process("wechat", payment)
            await PaymentCallbackService(db).process("wechat", payment)
            config = await runtime_config(db, client)
            assert 89 * 86400 < config.authorization.remaining_seconds <= 90 * 86400
            assert await db.scalar(select(func.count()).select_from(SubscriptionCycleModel).where(SubscriptionCycleModel.app_id == app.id)) == 1
            assert await db.scalar(select(func.count()).select_from(CreditGrantModel).where(CreditGrantModel.app_id == app.id)) == 0
        finally:
            await db.rollback()


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("status", ["created", "pending", "confirming", "failed"])
async def test_unfinished_order_blocks_narrowing_and_failed_late_payment_preserves_new_subscription(test_client, monkeypatch, enabled, status):
    del test_client
    async with async_db_session() as db:
        try:
            app, user, version, _, staff = await scope(db, enabled=enabled)

            async def make_order(credits):
                payload = plan_payload(version.id, 30)
                if credits:
                    payload.update(entitlement_kind="credits", total_credits=100, release_plan=[{"offset_day": 0, "amount": 100}])
                plan = await CatalogService(staff, db).create(CatalogPlanCreateSchema(**payload))
                snapshot = {**payload, "credit_valid_days": 30}
                # Older credit orders predate the entitlement_kind field.
                if credits:
                    snapshot.pop("entitlement_kind")
                order = PaymentOrderModel(
                    app_id=app.id,
                    user_id=user.id,
                    catalog_plan_id=plan.id,
                    order_no=uuid4().hex,
                    idempotency_key=uuid4().hex,
                    provider="wechat",
                    purchase_type="first",
                    amount_fen=1000,
                    plan_snapshot=snapshot,
                    status=status,
                    expires_at=datetime.now(UTC) + timedelta(minutes=15),
                )
                db.add(order)
                await db.flush()
                return order

            old_order = await make_order(enabled)
            old_snapshot = dict(old_order.plan_snapshot)
            if status in {"created", "pending", "confirming"}:
                with pytest.raises(CustomException, match="待处理订单"):
                    await ClientAppService(staff, db).update(app.id, ClientAppUpdateSchema(platform_model_enabled=not enabled, expected_policy_version=1))
                assert app.model_policy_version == 1
                assert old_order.status == status and old_order.plan_snapshot == old_snapshot
                return
            await ClientAppService(staff, db).update(app.id, ClientAppUpdateSchema(platform_model_enabled=not enabled, expected_policy_version=1))
            assert app.platform_model_enabled is not enabled
            assert app.model_policy_version == 2
            assert old_order.status == status and old_order.plan_snapshot == old_snapshot
            assert (await db.get(AppCatalogPlanModel, old_order.catalog_plan_id)).status == "off_sale"

            new_order = await make_order(not enabled)
            subscription = await SubscriptionService(db).activate_paid_order(
                app_id=app.id,
                user_id=user.id,
                order_id=new_order.id,
                catalog_plan_id=new_order.catalog_plan_id,
                plan_snapshot=new_order.plan_snapshot,
                auto_renew=False,
            )
            original = (subscription.entitlement_kind, subscription.catalog_plan_id, subscription.current_period_end)
            payment = VerifiedPayment(callback_id=uuid4().hex, order_no=old_order.order_no, provider_trade_no=uuid4().hex, amount_fen=1000, paid_at=datetime.now(UTC), payload_digest="a" * 64)
            await PaymentCallbackService(db).process("wechat", payment)
            await PaymentCallbackService(db).process("wechat", payment)
            await db.refresh(subscription)
            assert old_order.status == "paid" and old_order.provider_trade_no == payment.provider_trade_no
            assert "待财务" in old_order.failure_reason
            assert (subscription.entitlement_kind, subscription.catalog_plan_id, utc(subscription.current_period_end)) == (*original[:2], utc(original[2]))
            assert await db.scalar(select(func.count()).select_from(SubscriptionCycleModel).where(SubscriptionCycleModel.order_id == old_order.id)) == 0
            assert await db.scalar(select(func.count()).select_from(CreditGrantModel).where(CreditGrantModel.app_id == app.id)) == (0 if enabled else 1)
            with pytest.raises(CustomException, match="当前模型模式不一致"):
                await SubscriptionService(db).activate_paid_order(
                    app_id=app.id,
                    user_id=user.id,
                    order_id=old_order.id,
                    catalog_plan_id=old_order.catalog_plan_id,
                    plan_snapshot=old_order.plan_snapshot,
                    auto_renew=False,
                )
            from app.api.v1.module_finance import orders as finance_orders

            async def query_payment(*_, include_closed=False):
                assert include_closed
                return payment

            monkeypatch.setattr(finance_orders, "query_wechat_order", query_payment)
            detail = await finance_orders.verify_order(db, app.id, old_order.id, 1, "跨模式旧订单核查")
            assert detail["order"].status == "paid"
            assert detail["order"].fulfillment_status == "missing"
        finally:
            await db.rollback()


async def test_duration_strategy_uses_discount_without_model_cost(test_client):
    del test_client
    async with async_db_session() as db:
        try:
            _, _, version, _, staff = await scope(db)
            catalog = CatalogService(staff, db)
            plan = await catalog.create(CatalogPlanCreateSchema(**plan_payload(version.id)))
            now = datetime.now(UTC)
            await catalog.create_strategy(
                PricingStrategyCreateSchema(
                    catalog_plan_id=plan.id,
                    pricing_version_id=version.id,
                    name="时长优惠",
                    starts_at=now - timedelta(days=1),
                    ends_at=now + timedelta(days=1),
                    status="active",
                    items=[{"catalog_plan_id": plan.id, "purchase_type": "all", "discount_rate": 0.8, "margin_rate": 0}],
                )
            )
            price = await catalog.resolve_pricing(plan.id, "first")
            assert price["execution_price_fen"] == 800
            assert price["allowed_cost_yuan"] == price["credits_per_cost_yuan"] == 0
        finally:
            await db.rollback()


def test_runtime_config_is_authenticated_and_returns_off_switch(test_client):
    assert test_client.get("/client/runtime-config").status_code in (401, 403)
    token = test_client.post("/system/auth/login", data={"username": "admin", "password": "admin123"}).json()["data"]["access_token"]
    code = f"duration_{uuid4().hex[:8]}"
    created = test_client.post(
        "/operations/client-apps",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "自配模型", "code": code, "status": "active", "registration_enabled": True, "platform_model_enabled": False},
    )
    assert created.status_code == 201, created.text
    credentials = {"app_code": code, "username": "duration_member", "password": "Passw0rd!"}
    assert register_with_sms(test_client, credentials).status_code == 200
    login = test_client.post("/client/auth/login", json=credentials).json()["data"]
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    response = test_client.get("/client/runtime-config", headers=headers)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json()["data"]["platform_model_enabled"] is False
    assert response.json()["data"]["refresh_after_seconds"] == 3600
    assert response.json()["data"]["authorization"]["status"] == "not_purchased"
    assert test_client.post("/client/runtime/token", headers=headers).status_code == 403
    model = test_client.get("/client/model/config", headers=headers)
    assert model.json()["data"]["allow_custom_model"] is True


def test_migration_keeps_old_apps_and_products_in_credit_mode():
    migration = importlib.import_module("app.alembic.versions.20261008_model_mode")
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        for table in ("client_app", "pricing_plan_template", "app_catalog_plan", "subscription"):
            conn.execute(text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))
            conn.execute(text(f"INSERT INTO {table} VALUES (1)"))
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        assert conn.execute(text("SELECT platform_model_enabled, model_policy_version FROM client_app")).one() == (1, 1)
        assert conn.execute(text("SELECT entitlement_kind FROM subscription")).scalar() == "credits"
    engine.dispose()


async def test_duration_refund_confirmation_uses_stable_rights_and_detects_renewal(test_client):
    from app.api.v1.module_finance import refunds
    from app.api.v1.module_finance.gateway import RefundResult
    from app.api.v1.module_finance.schema import RefundCreate, RefundReview

    del test_client
    async with async_db_session() as db:
        try:
            app, user, version, _, staff = await scope(db)
            plan = await CatalogService(staff, db).create(CatalogPlanCreateSchema(**plan_payload(version.id, 30)))
            order, sub = await paid_order(db, app, user, plan)
            order.provider_trade_no = uuid4().hex
            await paid_order(db, app, user, plan)
            preview = await refunds.preview_refund(db, app.id, order.id, "terminate")
            later = await refunds.preview_refund(db, app.id, order.id, "terminate")
            assert preview["preview_token"] == later["preview_token"]
            assert later["after"]["ends_at"] != preview["after"]["ends_at"]
            await paid_order(db, app, user, plan)
            changed = await refunds.preview_refund(db, app.id, order.id, "terminate")
            with pytest.raises(CustomException, match="刷新"):
                refunds.check_preview(changed, preview["preview_token"])
            request = await refunds.create_refund(
                db,
                app.id,
                1,
                RefundCreate(
                    order_id=order.id,
                    amount_fen=500,
                    reason="退还剩余时长",
                    entitlement_action="terminate",
                    idempotency_key=uuid4().hex,
                    preview_token=changed["preview_token"],
                ),
            )
            current = await refunds.preview_refund(db, app.id, order.id, "terminate")
            await refunds.review_refund(db, app.id, request.id, 1, RefundReview(approved=True, reason="同意申请", preview_token=current["preview_token"]))
            result = RefundResult("succeeded", uuid4().hex, datetime.now(UTC))
            await refunds.apply_refund(db, request, result)
            assert request.entitlement_result["entitlement_kind"] == "duration"
            assert 59.99 < (utc(sub.current_period_end) - datetime.now(UTC)).total_seconds() / 86400 <= 60
            end = sub.current_period_end
            await refunds.apply_refund(db, request, result)
            assert sub.current_period_end == end
        finally:
            await db.rollback()


async def test_duration_expiry_suspension_and_repurchase_from_now(test_client):
    del test_client
    async with async_db_session() as db:
        try:
            app, user, version, client, staff = await scope(db)
            plan = await CatalogService(staff, db).create(CatalogPlanCreateSchema(**plan_payload(version.id, 7)))
            order, sub = await paid_order(db, app, user, plan)
            sub.status = "cancelled"
            assert (await runtime_config(db, client)).authorization.status == "suspended"
            sub.status = "active"
            cycle = await db.scalar(select(SubscriptionCycleModel).where(SubscriptionCycleModel.order_id == order.id))
            cycle.starts_at = sub.current_period_start = datetime.now(UTC) - timedelta(days=8)
            cycle.ends_at = sub.current_period_end = datetime.now(UTC) - timedelta(days=1)
            config = await runtime_config(db, client)
            assert config.authorization.status == "expired" and not config.authorization.can_start_task
            assert config.authorization.remaining_seconds == 0
            _, sub = await paid_order(db, app, user, plan)
            assert 6.99 < (utc(sub.current_period_end) - datetime.now(UTC)).total_seconds() / 86400 <= 7
            assert (await runtime_config(db, client)).authorization.can_start_task
            sub.current_period_start = datetime.now(UTC) + timedelta(days=1)
            assert not (await runtime_config(db, client)).authorization.can_start_task
        finally:
            await db.rollback()


async def test_runtime_token_issued_before_switch_cannot_access_platform(monkeypatch):
    import json
    from unittest.mock import AsyncMock

    from app.core import client_dependencies

    db = SimpleNamespace(
        scalar=AsyncMock(
            side_effect=[
                SimpleNamespace(id=2, username="member", display_name="member", auth_generation=1),
                1,
                SimpleNamespace(platform_model_enabled=False, service_mode="duration_only"),
            ]
        ),
        rollback=AsyncMock(),
    )
    payload = SimpleNamespace(is_refresh=False, actor_type="runtime", app_id=1, sub="session")
    monkeypatch.setattr(client_dependencies, "decode_access_token", lambda *_a, **_k: payload)
    monkeypatch.setattr(client_dependencies.RedisCURD, "get", AsyncMock(return_value=json.dumps({"actor_type": "client", "app_id": 1, "user_id": 2, "auth_generation": 1})))
    with pytest.raises(CustomException, match="不支持平台"):
        await client_dependencies.get_current_runtime_user(db=db, redis=SimpleNamespace(), token="old-runtime-token")


@pytest.mark.parametrize("field", ["total_credits", "release_plan", "benefit_period_days", "recurring_price_fen", "entitlement_kind"])
def test_patch_does_not_allow_null_required_entitlements(field):
    with pytest.raises(ValidationError):
        CatalogPlanUpdateSchema(**{field: None})


def test_model_mode_migration_postgres_sql():
    from io import StringIO

    migration = importlib.import_module("app.alembic.versions.20261008_model_mode")
    output = StringIO()
    with Operations.context(MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})):
        migration.upgrade()
    sql = output.getvalue()
    assert "BOOLEAN DEFAULT true NOT NULL" in sql
    assert sql.count("DEFAULT 'credits' NOT NULL") == 3
    assert "DROP" not in sql


async def test_local_mode_rejects_platform_speech_before_provider_call(test_client, monkeypatch):
    from unittest.mock import AsyncMock

    from app.api.v1.module_speech import provider
    from app.api.v1.module_speech.service import SpeechService

    del test_client
    upstream = AsyncMock()
    monkeypatch.setattr(provider, "transcribe", upstream)
    async with async_db_session() as db:
        try:
            _, _, _, client, _ = await scope(db)
            service = SpeechService(client, db)
            assert not (await service.capability()).available
            with pytest.raises(CustomException, match="不支持平台"):
                await service.transcribe(b"test", uuid4().hex)
            upstream.assert_not_awaited()
        finally:
            await db.rollback()


async def test_duration_recharge_and_refund_do_not_remove_operator_suspension(test_client):
    del test_client
    async with async_db_session() as db:
        try:
            app, user, version, client, staff = await scope(db)
            plan = await CatalogService(staff, db).create(CatalogPlanCreateSchema(**plan_payload(version.id, 30)))
            first, sub = await paid_order(db, app, user, plan)
            old_end = utc(sub.current_period_end)
            sub.status = "cancelled"
            await paid_order(db, app, user, plan)
            assert sub.status == "cancelled" and utc(sub.current_period_end) == old_end + timedelta(days=30)
            assert not (await runtime_config(db, client)).authorization.can_start_task
            await terminate_order_entitlements(db, first, uuid4().hex)
            assert sub.status == "cancelled"
            assert 29.99 < (utc(sub.current_period_end) - datetime.now(UTC)).total_seconds() / 86400 <= 30
            assert not (await runtime_config(db, client)).authorization.can_start_task
        finally:
            await db.rollback()
