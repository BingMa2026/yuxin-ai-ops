"""Three-mode authorization and destructive switch confirmation regressions."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from test_local_model_duration import paid_order, plan_payload, scope

from app.api.v1.module_billing.mode_switch.schema import ModeSwitchConfirmation, ModeSwitchPreviewIn
from app.api.v1.module_billing.mode_switch.service import confirm_for_order, fulfill_paid_order, preview_switch
from app.api.v1.module_billing.model import AppCatalogPlanModel, CreditLedgerModel, SubscriptionCycleModel
from app.api.v1.module_billing.schema import CatalogPlanCreateSchema
from app.api.v1.module_billing.service import CatalogService, CreditService
from app.api.v1.module_client.app.model import ClientAppModel
from app.api.v1.module_client.app.model_policy import change_model_policy, require_platform_model
from app.api.v1.module_client.app.schema import ClientAppCreateSchema
from app.api.v1.module_client.runtime_config import runtime_config
from app.api.v1.module_payment.order.model import PaymentOrderModel
from app.core.database import async_db_session
from app.core.exceptions import CustomException


async def setup_scope(db, enabled=True):
    app, user, version, client, staff = await scope(db, enabled=enabled)
    await change_model_policy(db, app, "user_choice", 1)
    await db.flush()
    await db.refresh(user)
    duration = await CatalogService(staff, db).create(CatalogPlanCreateSchema(**plan_payload(version.id)))
    credit_data = plan_payload(version.id)
    credit_data.update(entitlement_kind="credits", total_credits=100, release_plan=[{"offset_day": 0, "amount": 100}])
    credit = await CatalogService(staff, db).create(CatalogPlanCreateSchema(**credit_data))
    return app, user, client, staff, await db.get(AppCatalogPlanModel, duration.id), await db.get(AppCatalogPlanModel, credit.id)


async def switch_order(db, app, user, client, plan):
    preview = await preview_switch(db, client, ModeSwitchPreviewIn(target_mode=plan.entitlement_kind, catalog_plan_id=plan.id, expected_mode_version=user.mode_version))
    assert preview.can_switch
    authorized = await confirm_for_order(db, app, user, plan, ModeSwitchConfirmation(expected_mode_version=user.mode_version, accept_reset=True))
    order = PaymentOrderModel(
        app_id=app.id,
        user_id=user.id,
        catalog_plan_id=plan.id,
        order_no=uuid4().hex,
        idempotency_key=uuid4().hex,
        provider="alipay",
        purchase_type="first",
        amount_fen=1000,
        status="pending",
        plan_snapshot={
            "name": plan.name,
            "entitlement_kind": plan.entitlement_kind,
            "mode_version": user.mode_version,
            "model_policy_version": app.model_policy_version,
            "plan_type": "subscription",
            "benefit_period_days": 30,
            "total_credits": plan.total_credits,
            "release_plan": plan.release_plan,
            "credit_valid_days": 30,
        },
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
        mode_switch={"reset_authorized": authorized, "source_mode": user.active_billing_mode, "target_mode": plan.entitlement_kind, "status": "pending_payment"},
    )
    db.add(order)
    await db.flush()
    return order, preview


def test_new_app_defaults_and_legacy_request():
    assert ClientAppCreateSchema(name="test", code="test").service_mode == "user_choice"
    assert ClientAppCreateSchema(name="test", code="test", platform_model_enabled=False).service_mode == "duration_only"
    assert ClientAppCreateSchema(name="test", code="test", service_mode="duration_only").platform_model_enabled is False


async def test_first_selection_and_runtime_versions(test_client):
    async with async_db_session() as db:
        try:
            app, user, client, staff, duration, credit = await setup_scope(db)
            user.active_billing_mode = None
            await db.flush()
            config = await runtime_config(db, client, 2)
            assert config.active_billing_mode is None and config.authorization.status == "mode_required"
            assert not config.platform_model_enabled and not config.allow_custom_model
            with pytest.raises(CustomException, match="升级"):
                await runtime_config(db, client)
            with pytest.raises(CustomException):
                await require_platform_model(db, app.id, user_id=user.id)
            assert {p.entitlement_kind for p in await CatalogService(client, db).list_plans(public_only=True)} == {"credits", "duration"}
            assert all(p.entitlement_kind == "duration" for p in await CatalogService(staff, db).list_plans(entitlement_kind="duration"))
            app2 = ClientAppModel(name="default", code=uuid4().hex)
            db.add(app2)
            await db.flush()
            assert app2.service_mode == "user_choice"
        finally:
            await db.rollback()


async def test_single_mode_rejects_opposite_catalog_draft(test_client):
    async with async_db_session() as db:
        try:
            app, user, version, client, staff = await scope(db, enabled=True)
            payload = plan_payload(version.id)
            payload["status"] = "draft"
            with pytest.raises(CustomException, match="权益类型"):
                await CatalogService(staff, db).create(CatalogPlanCreateSchema(**payload))
        finally:
            await db.rollback()


async def test_confirmed_credit_reset_is_atomic_and_replay_safe(test_client):
    async with async_db_session() as db:
        try:
            app, user, client, staff, duration, _ = await setup_scope(db)
            await CreditService(db).adjust(app.id, user.id, 200, "人工赠送测试", 1)
            order, preview = await switch_order(db, app, user, client, duration)
            assert preview.reset_summary.available_credits_to_expire == 200
            assert (await CreditService(db).account(app.id, user.id)).available == 200
            assert user.active_billing_mode == "credits"
            order.status, order.paid_at = "paid", datetime.now(UTC)
            assert await fulfill_paid_order(db, order)
            assert user.active_billing_mode == "duration"
            assert order.mode_switch["status"] == "completed"
            assert (await CreditService(db).account(app.id, user.id)).available == 0
            version = user.mode_version
            assert await fulfill_paid_order(db, order)
            assert user.mode_version == version
            entries = list(await db.scalars(select(CreditLedgerModel).where(CreditLedgerModel.app_id == app.id, CreditLedgerModel.entry_type == "mode_reset")))
            assert len(entries) == 1 and entries[0].amount == -200
            with pytest.raises(CustomException):
                await require_platform_model(db, app.id, user_id=user.id)
            with pytest.raises(CustomException):
                await CreditService(db).adjust(app.id, user.id, 10, "不应发放", 1)
        finally:
            await db.rollback()


async def test_switch_resets_all_remaining_assets_at_payment(test_client):
    async with async_db_session() as db:
        try:
            app, user, client, staff, duration, _ = await setup_scope(db)
            await CreditService(db).adjust(app.id, user.id, 200, "原有权益", 1)
            order, _ = await switch_order(db, app, user, client, duration)
            await CreditService(db).adjust(app.id, user.id, 50, "新增权益", 1)
            order.status, order.paid_at = "paid", datetime.now(UTC)
            assert await fulfill_paid_order(db, order)
            assert order.mode_switch["status"] == "completed"
            assert user.active_billing_mode == "duration"
            assert (await CreditService(db).account(app.id, user.id)).available == 0
            assert order.mode_switch["reset_result"]["available_credits_to_expire"] == 250
            assert await fulfill_paid_order(db, order)
        finally:
            await db.rollback()


async def test_duration_switch_terminates_periods_and_grants_credits(test_client):
    async with async_db_session() as db:
        try:
            app, user, client, staff, duration, credit = await setup_scope(db, enabled=False)
            old_order, sub = await paid_order(db, app, user, duration)
            order, preview = await switch_order(db, app, user, client, credit)
            assert preview.reset_summary.duration_seconds_to_expire > 0
            order.status, order.paid_at = "paid", datetime.now(UTC)
            assert await fulfill_paid_order(db, order)
            assert user.active_billing_mode == "credits"
            assert (await CreditService(db).account(app.id, user.id)).available == 100
            old_cycle = await db.scalar(select(SubscriptionCycleModel).where(SubscriptionCycleModel.order_id == old_order.id))
            assert old_cycle.status == "mode_reset"
            config = await runtime_config(db, client, 2)
            assert config.platform_model_enabled and not config.allow_custom_model
        finally:
            await db.rollback()


async def test_reminder_version_and_reserved_balance(test_client):
    async with async_db_session() as db:
        try:
            app, user, client, staff, duration, credit = await setup_scope(db)
            await CreditService(db).adjust(app.id, user.id, 100, "预占测试", 1)
            await CreditService(db).reserve(app.id, user.id, uuid4().hex, 20)
            preview = await preview_switch(db, client, ModeSwitchPreviewIn(target_mode="duration", catalog_plan_id=duration.id, expected_mode_version=user.mode_version))
            assert not preview.can_switch
            with pytest.raises(CustomException):
                await confirm_for_order(db, app, user, duration, ModeSwitchConfirmation(expected_mode_version=user.mode_version, accept_reset=True))
            with pytest.raises(CustomException, match="当前模式已变化"):
                await confirm_for_order(db, app, user, duration, ModeSwitchConfirmation(expected_mode_version=user.mode_version + 1, accept_reset=True))
            with pytest.raises(CustomException, match="确认"):
                await confirm_for_order(db, app, user, duration, None)
        finally:
            await db.rollback()


async def test_callback_replay_and_late_old_mode_order(test_client):
    from app.api.v1.module_payment.order.providers import VerifiedPayment
    from app.api.v1.module_payment.order.service import PaymentCallbackService

    async with async_db_session() as db:
        try:
            app, user, client, staff, duration, credit = await setup_scope(db)
            await CreditService(db).adjust(app.id, user.id, 75, "回调验证", 1)
            order, _ = await switch_order(db, app, user, client, duration)
            payment = VerifiedPayment(callback_id=uuid4().hex, order_no=order.order_no, provider_trade_no=uuid4().hex, amount_fen=order.amount_fen, paid_at=datetime.now(UTC), payload_digest="a" * 64)
            await PaymentCallbackService(db).process("alipay", payment)
            await PaymentCallbackService(db).process("alipay", payment)
            assert order.status == "paid" and order.mode_switch["status"] == "completed"
            cycles = list(await db.scalars(select(SubscriptionCycleModel).where(SubscriptionCycleModel.order_id == order.id)))
            assert len(cycles) == 1
            late = PaymentOrderModel(
                app_id=app.id,
                user_id=user.id,
                catalog_plan_id=credit.id,
                order_no=uuid4().hex,
                idempotency_key=uuid4().hex,
                provider="alipay",
                purchase_type="first",
                amount_fen=1000,
                status="pending",
                plan_snapshot={"entitlement_kind": "credits", "mode_version": user.mode_version - 1},
                expires_at=datetime.now(UTC),
            )
            db.add(late)
            await db.flush()
            payment2 = VerifiedPayment(callback_id=uuid4().hex, order_no=late.order_no, provider_trade_no=uuid4().hex, amount_fen=1000, paid_at=datetime.now(UTC), payload_digest="b" * 64)
            await PaymentCallbackService(db).process("alipay", payment2)
            assert late.status == "paid" and late.mode_switch["status"] == "requires_confirmation"
            assert user.active_billing_mode == "duration"
            assert (await CreditService(db).account(app.id, user.id)).available == 0
        finally:
            await db.rollback()


async def test_failed_fulfillment_rolls_back_reset_and_mode(test_client, monkeypatch):
    from unittest.mock import AsyncMock

    from app.api.v1.module_billing.service import SubscriptionService

    async with async_db_session() as db:
        try:
            app, user, client, staff, duration, credit = await setup_scope(db)
            await CreditService(db).adjust(app.id, user.id, 120, "事务回滚", 1)
            order, _ = await switch_order(db, app, user, client, duration)
            order.status, order.paid_at = "paid", datetime.now(UTC)
            await db.flush()
            monkeypatch.setattr(SubscriptionService, "activate_paid_order", AsyncMock(side_effect=RuntimeError("injected failure")))
            with pytest.raises(RuntimeError):
                async with db.begin_nested():
                    await fulfill_paid_order(db, order)
            await db.refresh(user)
            assert user.active_billing_mode == "credits"
            account = await CreditService(db).account(app.id, user.id)
            await db.refresh(account)
            assert account.available == 120
        finally:
            await db.rollback()


def test_service_mode_migration_backfills_without_changing_existing_mode():
    import importlib

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect, text

    migration = importlib.import_module("app.alembic.versions.20261013_service_modes")
    with create_engine("sqlite:///:memory:").begin() as connection:
        connection.execute(text("CREATE TABLE client_app (id INTEGER PRIMARY KEY, platform_model_enabled BOOLEAN NOT NULL DEFAULT 1)"))
        connection.execute(text("CREATE TABLE client_user (id INTEGER PRIMARY KEY, app_id INTEGER)"))
        connection.execute(text("CREATE TABLE payment_order (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE app_catalog_plan (id INTEGER PRIMARY KEY)"))
        connection.execute(text("INSERT INTO client_app (id, platform_model_enabled) VALUES (1, 1), (2, 0)"))
        connection.execute(text("INSERT INTO client_user (id, app_id) VALUES (1, 1), (2, 2)"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert "billing_mode_preview" not in inspect(connection).get_table_names()
        assert connection.execute(text("SELECT service_mode FROM client_app ORDER BY id")).scalars().all() == ["credits_only", "duration_only"]
        assert connection.execute(text("SELECT active_billing_mode FROM client_user ORDER BY id")).scalars().all() == ["credits", "duration"]
        connection.execute(text("INSERT INTO client_app (id) VALUES (3)"))
        assert connection.execute(text("SELECT service_mode FROM client_app WHERE id=3")).scalar() == "user_choice"
