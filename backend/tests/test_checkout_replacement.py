"""Unpaid checkout choices are independent; replacement never grants twice."""

import importlib
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, func, inspect, select
from test_payment_cancellation import payment, purchase  # noqa: F401

from app.api.v1.module_billing.mode_switch.schema import ModeSwitchConfirmation, ModeSwitchPreviewIn
from app.api.v1.module_billing.mode_switch.service import preview_switch
from app.api.v1.module_billing.model import AppCatalogPlanModel, CreditGrantModel
from app.api.v1.module_client.user.model import ClientUserModel
from app.api.v1.module_payment.channel.model import AppPaymentChannelModel, PaymentChannelModel
from app.api.v1.module_payment.channel.service import PaymentChannelService
from app.api.v1.module_payment.order import service
from app.api.v1.module_payment.order.model import PaymentOrderModel
from app.api.v1.module_payment.order.schema import PaymentOrderCreate
from app.api.v1.module_payment.order.service import PaymentCallbackService, PaymentOrderService
from app.core.base_model import MappedBase
from app.core.base_schema import CoreUserSchema
from app.core.exceptions import CustomException


@pytest.fixture
async def checkout(purchase, monkeypatch):  # noqa: F811
    p = purchase
    p.app.service_mode = "user_choice"
    p.order.mode_switch = {"status": "pending_payment", "source_mode": "credits", "target_mode": "credits"}
    for channel in await p.db.scalars(select(PaymentChannelModel)):
        channel.enabled, channel.mode = True, "production"
        binding = await p.db.scalar(select(AppPaymentChannelModel).where(AppPaymentChannelModel.app_id == p.app.id, AppPaymentChannelModel.channel_id == channel.id))
        if binding:
            binding.enabled = True
        else:
            p.db.add(AppPaymentChannelModel(app_id=p.app.id, channel_id=channel.id, enabled=True))
    duration = AppCatalogPlanModel(
        app_id=p.app.id,
        pricing_version_id=p.plan.pricing_version_id,
        code=uuid4().hex,
        name="自备模型套餐",
        entitlement_kind="duration",
        plan_type="subscription",
        one_time_price_fen=1200,
        recurring_price_fen=1200,
        benefit_period_days=7,
        total_credits=0,
        release_plan=[],
        credit_valid_days=7,
        benefits=[],
        status="on_sale",
    )
    p.db.add(duration)
    await p.db.flush()
    p.duration = duration
    monkeypatch.setattr(PaymentChannelService, "_to_schema", lambda *_: type("Ready", (), {"configured": True})())
    monkeypatch.setattr(service, "create_wechat_native_order", AsyncMock(return_value="weixin://replacement"))
    monkeypatch.setattr(service, "create_alipay_qr_order", AsyncMock(return_value="https://qr.alipay.com/replacement"))
    return p


@pytest.mark.parametrize("provider", ["wechat", "alipay"])
@pytest.mark.parametrize("mode", ["credits", "duration"])
async def test_old_unpaid_orders_do_not_block_other_plans_channels_or_modes(checkout, provider, mode):
    p = checkout
    plan = p.plan if mode == "credits" else p.duration
    preview = await preview_switch(p.db, p.auth, ModeSwitchPreviewIn(target_mode=mode, catalog_plan_id=plan.id, expected_mode_version=p.user.mode_version))
    assert preview.can_switch
    request = PaymentOrderCreate(
        catalog_plan_id=plan.id,
        provider=provider,
        idempotency_key=uuid4().hex,
        mode_switch_confirmation=ModeSwitchConfirmation(expected_mode_version=p.user.mode_version, accept_reset=True) if mode == "duration" else None,
    )
    result = await PaymentOrderService(p.auth, p.db).create(request)
    assert result.status == "pending" and result.order_no != p.order.order_no
    assert p.order.status == "pending" and p.order.replaced_by_order_no is None and p.order.pay_url
    assert (await PaymentOrderService(p.auth, p.db).create(request)).order_no == result.order_no


async def test_channel_replacement_retains_receipts_and_only_latest_order_gets_rights(checkout):
    p = checkout
    request = PaymentOrderCreate(catalog_plan_id=p.plan.id, provider="alipay", idempotency_key=uuid4().hex, replaces_order_no=p.order.order_no)
    result = await PaymentOrderService(p.auth, p.db).create(request)
    assert result.replaces_order_no == p.order.order_no and p.order.replaced_by_order_no == result.order_no
    assert p.order.pay_url is None and p.order.cancel_requested_at and p.order.next_query_at
    assert p.close.await_count == 0  # New payment does not wait on provider closure.
    assert (await PaymentOrderService(p.auth, p.db).create(request)).id == result.id
    await PaymentCallbackService(p.db).process("wechat", payment(p.order))
    assert p.order.status == "paid" and p.order.mode_switch["status"] == "requires_confirmation"
    assert (await preview_switch(p.db, p.auth, ModeSwitchPreviewIn(target_mode="credits", catalog_plan_id=p.plan.id, expected_mode_version=p.user.mode_version))).can_switch
    assert await p.db.scalar(select(func.count()).select_from(CreditGrantModel).where(CreditGrantModel.source_id == p.order.id)) == 0
    new = await p.db.get(PaymentOrderModel, result.id)
    receipt = payment(new)
    await PaymentCallbackService(p.db).process("alipay", receipt)
    await PaymentCallbackService(p.db).process("alipay", receipt)
    assert new.status == "paid" and p.user.active_billing_mode == "credits"
    assert await p.db.scalar(select(func.count()).select_from(CreditGrantModel).where(CreditGrantModel.source_id == new.id)) == 1


async def test_replacement_binding_is_scoped_idempotent_and_rejects_stale_source(checkout):
    p = checkout
    request = PaymentOrderCreate(catalog_plan_id=p.plan.id, provider="alipay", idempotency_key=uuid4().hex, replaces_order_no=p.order.order_no)
    other_user = ClientUserModel(app_id=p.app.id, username=uuid4().hex, password_hash="test-only", status="active", active_billing_mode="credits")
    p.db.add(other_user)
    await p.db.flush()
    other = p.auth.model_copy(update={"user": CoreUserSchema(id=other_user.id, username=other_user.username)})
    with pytest.raises(CustomException, match="本人原订单"):
        await PaymentOrderService(other, p.db).create(request)
    result = await PaymentOrderService(p.auth, p.db).create(request)
    with pytest.raises(CustomException, match="不同的套餐或支付方式"):
        await PaymentOrderService(p.auth, p.db).create(request.model_copy(update={"replaces_order_no": None}))
    with pytest.raises(CustomException, match="已被更换"):
        await PaymentOrderService(p.auth, p.db).create(request.model_copy(update={"idempotency_key": uuid4().hex}))
    assert result.replaces_order_no == p.order.order_no


async def test_failed_new_creation_keeps_original_payment_usable(checkout, monkeypatch):
    p = checkout
    monkeypatch.setattr(service, "create_alipay_qr_order", AsyncMock(side_effect=CustomException(msg="明确拒绝下单", status_code=422)))
    result = await PaymentOrderService(p.auth, p.db).create(PaymentOrderCreate(catalog_plan_id=p.plan.id, provider="alipay", idempotency_key=uuid4().hex, replaces_order_no=p.order.order_no))
    assert result.status == "failed" and p.order.replaced_by_order_no is None and p.order.pay_url
    assert p.order.cancel_requested_at is None


async def test_paid_original_cannot_be_replaced_and_unsettled_payment_still_blocks(checkout):
    p = checkout
    p.order.status, p.order.paid_at = "paid", datetime.now(UTC)
    p.order.mode_switch = None
    await p.db.flush()
    request = PaymentOrderCreate(catalog_plan_id=p.plan.id, provider="alipay", idempotency_key=uuid4().hex, replaces_order_no=p.order.order_no)
    with pytest.raises(CustomException, match="原订单已收款"):
        await PaymentOrderService(p.auth, p.db).create(request)
    p.order.mode_switch = {"status": "requires_confirmation"}
    await p.db.flush()
    with pytest.raises(CustomException, match="已收款但权益待财务核对"):
        await PaymentOrderService(p.auth, p.db).create(request.model_copy(update={"replaces_order_no": None}))


async def test_unlinked_old_quote_cannot_overwrite_a_later_paid_upgrade(checkout):
    p = checkout
    p.plan.plan_type, p.plan.tier_order = "subscription", 1
    p.order.plan_snapshot = {**p.order.plan_snapshot, "plan_type": "subscription", "tier_order": 1, "mode_version": p.user.mode_version, "model_policy_version": p.app.model_policy_version}
    higher = AppCatalogPlanModel(
        app_id=p.app.id,
        pricing_version_id=p.plan.pricing_version_id,
        code=uuid4().hex,
        name="更高套餐",
        entitlement_kind="credits",
        plan_type="subscription",
        tier_order=2,
        one_time_price_fen=1200,
        recurring_price_fen=1200,
        benefit_period_days=30,
        total_credits=200,
        release_plan=[{"offset_day": 0, "amount": 200}],
        credit_valid_days=30,
        benefits=[],
        status="on_sale",
    )
    p.db.add(higher)
    await p.db.flush()
    result = await PaymentOrderService(p.auth, p.db).create(PaymentOrderCreate(catalog_plan_id=higher.id, provider="alipay", idempotency_key=uuid4().hex))
    new = await p.db.get(PaymentOrderModel, result.id)
    await PaymentCallbackService(p.db).process("alipay", payment(new))
    await PaymentCallbackService(p.db).process("wechat", payment(p.order))
    assert p.order.status == "paid" and p.order.mode_switch["status"] == "requires_confirmation"
    assert "不自动覆盖" in p.order.failure_reason


def test_replacement_migration_roundtrip(test_client):
    del test_client
    migration = importlib.import_module("app.alembic.versions.20261019_checkout_replacement")
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        MappedBase.metadata.create_all(connection)
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            assert "replaced_by_order_no" not in {c["name"] for c in inspect(connection).get_columns("payment_order")}
            migration.upgrade()
        assert {"replaces_order_no", "replaced_by_order_no"} <= {c["name"] for c in inspect(connection).get_columns("payment_order")}
    engine.dispose()
