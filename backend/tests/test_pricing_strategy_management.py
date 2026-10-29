import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.api.v1.module_billing.model import AppCatalogPlanModel, PricingStandardVersionModel, SubscriptionModel
from app.api.v1.module_billing.schema import PricingStrategyCreateSchema, PricingStrategyItemCreateSchema, PricingStrategyStatusSchema
from app.api.v1.module_billing.service import CatalogService
from app.api.v1.module_client.app.model import ClientAppModel
from app.api.v1.module_client.user.model import ClientUserModel
from app.api.v1.module_payment.channel.model import AppPaymentChannelModel, PaymentChannelModel
from app.api.v1.module_payment.channel.service import PaymentChannelService
from app.api.v1.module_payment.order import service as payment_module
from app.api.v1.module_payment.order.schema import PaymentOrderCreate
from app.api.v1.module_payment.order.service import PaymentOrderService
from app.core.base_schema import AuthSchema, CoreUserSchema
from app.core.database import async_db_session
from app.core.exceptions import CustomException


@pytest.fixture
async def pricing_case(test_client):
    async with async_db_session() as db:
        async with db.begin():
            app = await db.scalar(select(ClientAppModel).where(ClientAppModel.code == "bid_agent"))
            version = await db.scalar(select(PricingStandardVersionModel).where(PricingStandardVersionModel.status == "published"))
            auth = AuthSchema(user=CoreUserSchema(id=1, username="admin"), actor_type="staff", app_id=app.id)
            plan = AppCatalogPlanModel(
                app_id=app.id,
                pricing_version_id=version.id,
                code=f"free_{uuid.uuid4().hex[:8]}",
                name="体验版",
                one_time_price_fen=0,
                recurring_price_fen=0,
                benefit_period_days=30,
                total_credits=1000,
                release_plan=[{"offset_day": 0, "amount": 1000}],
                credit_valid_days=30,
                benefits=[],
                status="on_sale",
                cost_budget_yuan=2,
            )
            db.add(plan)
            await db.flush()
            now = datetime.now(UTC)
            data = PricingStrategyCreateSchema(
                catalog_plan_id=plan.id,
                pricing_version_id=version.id,
                name="体验策略",
                version=uuid.uuid4().hex,
                starts_at=now,
                ends_at=now + timedelta(days=30),
                items=[{"catalog_plan_id": plan.id, "purchase_type": "all", "discount_rate": 1, "margin_rate": 60}],
            )
            yield CatalogService(auth, db), plan, data
            await db.rollback()


async def test_zero_price_uses_catalog_budget(pricing_case):
    service, _, data = pricing_case
    result = await service.create_strategy(data)
    assert len(result.items) == 2
    assert all(item.allowed_cost_yuan == 2 and item.credits_per_cost_yuan == 500 for item in result.items)


async def test_zero_price_accepts_strategy_budget_without_catalog_budget(pricing_case):
    service, plan, data = pricing_case
    plan.cost_budget_yuan = None
    data.items[0].allowed_cost_yuan = 4
    result = await service.create_strategy(data)
    assert all(item.allowed_cost_yuan == 4 and item.credits_per_cost_yuan == 250 for item in result.items)


async def test_zero_price_missing_budget_has_actionable_error(pricing_case):
    service, plan, data = pricing_case
    plan.cost_budget_yuan = None
    with pytest.raises(CustomException, match="填写大于 0 的允许模型成本"):
        await service.create_strategy(data)


async def test_paid_strategy_ignores_cost_override(pricing_case):
    service, plan, data = pricing_case
    plan.one_time_price_fen = plan.recurring_price_fen = 1000
    data.items[0].allowed_cost_yuan = 100
    result = await service.create_strategy(data)
    assert all(item.allowed_cost_yuan == 4 for item in result.items)


async def test_edit_remove_restore_and_delete_strategy(pricing_case):
    service, _, data = pricing_case
    created = await service.create_strategy(data)
    assert (await service.strategy(created.id)).id == created.id
    data.name = "修改体验策略"
    data.items[0].purchase_type = "first"
    data.items[0].allowed_cost_yuan = 5
    edited = await service.update_strategy(created.id, data)
    assert edited.id == created.id and edited.name == data.name
    assert len(edited.items) == 1 and edited.items[0].allowed_cost_yuan == 5
    await service.set_strategy_status(created.id, PricingStrategyStatusSchema(status="active"))
    await service.set_strategy_status(created.id, PricingStrategyStatusSchema(status="inactive"))
    data.items[0].purchase_type = "all"
    restored = await service.update_strategy(created.id, data)
    assert len(restored.items) == 2
    assert {item.id for item in restored.items} == {item.id for item in created.items}
    await service.set_strategy_status(created.id, PricingStrategyStatusSchema(status="active"))
    with pytest.raises(CustomException, match="先下架"):
        await service.update_strategy(created.id, data)
    with pytest.raises(CustomException, match="先下架"):
        await service.delete_strategy(created.id)
    await service.set_strategy_status(created.id, PricingStrategyStatusSchema(status="inactive"))
    await service.delete_strategy(created.id)
    assert all(row.id != created.id for row in await service.strategies())
    with pytest.raises(CustomException):
        await service.strategy(created.id)


async def test_strategy_management_rejects_other_client(pricing_case):
    service, _, data = pricing_case
    created = await service.create_strategy(data)
    other = CatalogService(service.auth.model_copy(update={"app_id": 999999}), service.db)
    for action in (lambda: other.strategy(created.id), lambda: other.update_strategy(created.id, data), lambda: other.delete_strategy(created.id)):
        with pytest.raises(CustomException) as error:
            await action()
        assert error.value.status_code == 404


@pytest.mark.parametrize("budget", [0, -1, float("nan"), float("inf")])
def test_cost_budget_rejects_invalid_values(budget):
    with pytest.raises(ValidationError):
        PricingStrategyItemCreateSchema(catalog_plan_id=1, margin_rate=60, allowed_cost_yuan=budget)


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_strategy_management_requires_authentication(test_client, method):
    response = getattr(test_client, method)("/operations/billing/catalog/strategies/1")
    assert response.status_code == 401


@pytest.mark.parametrize("provider", ["wechat", "alipay"])
async def test_upgrade_quote_matches_admin_preview_and_uses_first_purchase_discount(pricing_case, monkeypatch, provider):
    service, plan, data = pricing_case
    plan.one_time_price_fen, plan.recurring_price_fen, plan.tier_order = 49900, 39900, 100
    data.items[0].purchase_type = "first"
    data.items[0].discount_rate = 0.9
    data.starts_at = datetime.now(UTC) - timedelta(minutes=1)
    data.status = "active"
    await service.create_strategy(data)
    user = ClientUserModel(app_id=plan.app_id, username=f"quote_{uuid.uuid4().hex[:8]}", password_hash="test-only", status="active")
    service.db.add(user)
    await service.db.flush()
    previous_plan = await service.db.scalar(select(AppCatalogPlanModel).where(AppCatalogPlanModel.app_id == plan.app_id, AppCatalogPlanModel.id != plan.id))
    subscription = SubscriptionModel(
        app_id=plan.app_id, user_id=user.id, catalog_plan_id=previous_plan.id, status="active", auto_renew=False, current_period_start=data.starts_at, current_period_end=data.ends_at
    )
    service.db.add(subscription)
    await service.db.flush()
    client = CatalogService(AuthSchema(user=CoreUserSchema(id=user.id, username=user.username), actor_type="client", app_id=plan.app_id), service.db)
    quote = next(row for row in await client.list_plans(public_only=True) if row.id == plan.id)
    preview = next(row for row in await service.list_plans(public_only=True, user_id=user.id) if row.id == plan.id)
    assert quote.model_dump() == preview.model_dump()
    assert quote.purchase_type == "first"
    assert quote.base_price_fen == 49900 and quote.effective_price_fen == 44910 and quote.discount_amount_fen == 4990
    channel = await service.db.scalar(select(PaymentChannelModel).where(PaymentChannelModel.provider == provider))
    channel.enabled, channel.mode = True, "production"
    binding = await service.db.scalar(select(AppPaymentChannelModel).where(AppPaymentChannelModel.app_id == plan.app_id, AppPaymentChannelModel.channel_id == channel.id))
    if binding:
        binding.enabled = True
    else:
        service.db.add(AppPaymentChannelModel(app_id=plan.app_id, channel_id=channel.id, enabled=True))
    await service.db.flush()
    monkeypatch.setattr(PaymentChannelService, "_to_schema", lambda *_: SimpleNamespace(configured=True))
    pay_url = "weixin://wxpay/bizpayurl?pr=test" if provider == "wechat" else "https://qr.alipay.com/test-order"
    payment_mock = AsyncMock(return_value=pay_url)
    monkeypatch.setattr(payment_module, "create_wechat_native_order" if provider == "wechat" else "create_alipay_qr_order", payment_mock)
    order = await PaymentOrderService(client.auth, service.db).create(PaymentOrderCreate(catalog_plan_id=plan.id, provider=provider, idempotency_key=uuid.uuid4().hex))
    assert order.amount_fen == quote.effective_price_fen and order.purchase_type == "first"
    assert order.status == "pending"
    assert order.pay_url == pay_url
    payment_mock.assert_awaited_once()
    assert payment_mock.call_args.args[1] == 44910
    # Order creation uses this same per-plan decision (even if the user has another subscription).
    assert service.purchase_type_for_plan(plan, subscription) == "first"
    subscription.catalog_plan_id = plan.id
    subscription.status = "expired"
    quote = next(row for row in await client.list_plans(public_only=True) if row.id == plan.id)
    assert quote.purchase_type == "renewal" and quote.effective_price_fen == 39900
    assert service.purchase_type_for_plan(plan, subscription) == "renewal"


async def test_live_quote_tracks_catalog_changes_and_strategy_status(pricing_case):
    service, plan, data = pricing_case
    plan.one_time_price_fen = 49900
    data.items[0].discount_rate = 0.9
    data.items[0].purchase_type = "first"
    data.starts_at = datetime.now(UTC) - timedelta(minutes=1)
    data.status = "active"
    strategy = await service.create_strategy(data)
    assert (await service.resolve_pricing(plan.id, "first"))["execution_price_fen"] == 44910
    plan.one_time_price_fen = 59900
    quote = await service.resolve_pricing(plan.id, "first")
    assert quote["execution_price_fen"] == 53910
    assert strategy.items[0].execution_price_fen == 44910
    await service.set_strategy_status(strategy.id, PricingStrategyStatusSchema(status="inactive"))
    assert (await service.resolve_pricing(plan.id, "first"))["execution_price_fen"] == 59900


async def test_preview_rejects_user_outside_current_client(pricing_case):
    service, _, _ = pricing_case
    with pytest.raises(CustomException) as error:
        await service.list_plans(public_only=True, user_id=999999)
    assert error.value.status_code == 404
