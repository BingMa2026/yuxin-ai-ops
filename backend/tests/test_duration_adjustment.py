"""Manual duration is an audited entitlement, isolated from payment and credits."""

import importlib
import io
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from sqlalchemy import create_engine, func, inspect, select, text

from app.api.v1.module_billing.duration import utc
from app.api.v1.module_billing.duration_adjustment import DurationAdjustmentService
from app.api.v1.module_billing.duration_controller import adjust_duration, duration_state
from app.api.v1.module_billing.duration_schema import DurationAdjustSchema
from app.api.v1.module_billing.model import CreditGrantModel, CreditLedgerModel, DurationAdjustmentModel, SubscriptionCycleModel
from app.api.v1.module_billing.schema import CatalogPlanCreateSchema
from app.api.v1.module_billing.service import CatalogService
from app.api.v1.module_billing.subscription_periods import project_subscription
from app.api.v1.module_client.app.model_policy import change_model_policy
from app.api.v1.module_client.runtime_config import runtime_config
from app.api.v1.module_finance.entitlements import terminate_order_entitlements
from app.api.v1.module_payment.order.model import PaymentOrderModel
from app.core.database import async_db_session
from app.core.dependencies import AuthPermission
from app.core.exceptions import CustomException
from tests.test_local_model_duration import paid_order, plan_payload, scope


def request(plan_id=None, **changes):
    return DurationAdjustSchema(**{"direction": "grant", "days": 30, "catalog_plan_id": plan_id, "reason": "人工开通测试", "idempotency_key": uuid4().hex, **changes})


@pytest.fixture
async def context(test_client):
    del test_client
    async with async_db_session() as db:
        try:
            app, user, version, client, staff = await scope(db)
            plan = await CatalogService(staff, db).create(CatalogPlanCreateSchema(**plan_payload(version.id, 7)))
            yield db, app, user, client, staff, plan, DurationAdjustmentService(db, staff)
        finally:
            await db.rollback()


async def test_new_grant_retry_audit_and_client_authorization(context):
    db, app, user, client, _, plan, service = context
    data = request(plan.id)
    result = await service.adjust(user.id, data)
    assert (await service.adjust(user.id, data)).id == result.id
    assert result.before_expires_at is None and result.seconds_delta == 30 * 86400
    config = await runtime_config(db, client)
    assert config.authorization.can_start_task
    assert 29 * 86400 < config.authorization.remaining_seconds <= 30 * 86400
    state = await service.state(user.id)
    assert state.status == "active" and len(state.records) == 1
    assert state.records[0].operator_name == "admin"
    for model in (PaymentOrderModel, CreditGrantModel, CreditLedgerModel):
        assert await db.scalar(select(func.count()).select_from(model).where(model.app_id == app.id)) == 0
    with pytest.raises(CustomException, match="标识已使用"):
        await service.adjust(user.id, data.model_copy(update={"days": 31}))


async def test_existing_paid_duration_stacks_and_refund_preserves_manual_time(context):
    db, app, user, client, _, plan, service = context
    order, sub = await paid_order(db, app, user, plan)
    original = utc(sub.current_period_end)
    result = await service.adjust(user.id, request(plan.id, expected_expires_at=original))
    assert utc(result.after_expires_at) == original + timedelta(days=30)
    await terminate_order_entitlements(db, order, "manual-refund-test")
    config = await runtime_config(db, client)
    assert config.authorization.can_start_task
    assert 29 * 86400 < config.authorization.remaining_seconds <= 30 * 86400
    end = utc(sub.current_period_end)
    _, sub = await paid_order(db, app, user, plan)
    assert utc(sub.current_period_end) == end + timedelta(days=7)
    assert (await project_subscription(db, sub))["ends_at"] == utc(sub.current_period_end)


async def test_deduct_crosses_periods_then_expires_and_can_reopen(context):
    db, app, user, client, _, plan, service = context
    _, sub = await paid_order(db, app, user, plan)
    paid_end = utc(sub.current_period_end)
    result = await service.adjust(user.id, request(plan.id, days=5, expected_expires_at=paid_end))
    result = await service.adjust(user.id, request(direction="deduct", days=8, expected_expires_at=result.after_expires_at))
    assert utc(result.after_expires_at) == paid_end - timedelta(days=3)
    assert result.seconds_delta == -8 * 86400
    result = await service.adjust(user.id, request(direction="deduct", days=100, expected_expires_at=result.after_expires_at))
    assert -(4 * 86400) <= result.seconds_delta < 0
    assert not (await runtime_config(db, client)).authorization.can_start_task
    assert utc(result.after_expires_at) <= datetime.now(UTC)
    result = await service.adjust(user.id, request(plan.id, days=1, expected_expires_at=result.after_expires_at))
    assert (await runtime_config(db, client)).authorization.can_start_task
    assert 0 < (utc(result.after_expires_at) - datetime.now(UTC)).total_seconds() <= 86400


async def test_expired_restart_and_suspension_is_preserved(context):
    db, app, user, client, _, plan, service = context
    _, sub = await paid_order(db, app, user, plan)
    cycle = await db.scalar(select(SubscriptionCycleModel).where(SubscriptionCycleModel.subscription_id == sub.id))
    cycle.starts_at = datetime.now(UTC) - timedelta(days=10)
    cycle.ends_at = datetime.now(UTC) - timedelta(days=3)
    sub.current_period_start, sub.current_period_end = cycle.starts_at, cycle.ends_at
    sub.status = "expired"
    await db.flush()
    result = await service.adjust(user.id, request(plan.id, days=2, expected_expires_at=sub.current_period_end))
    assert 86400 < (utc(result.after_expires_at) - datetime.now(UTC)).total_seconds() <= 2 * 86400
    sub.status = "cancelled"
    await db.flush()
    result = await service.adjust(user.id, request(plan.id, days=3, expected_expires_at=result.after_expires_at))
    assert sub.status == "cancelled"
    assert not (await runtime_config(db, client)).authorization.can_start_task
    await service.adjust(user.id, request(direction="deduct", days=1, expected_expires_at=result.after_expires_at))
    assert sub.status == "cancelled"


async def test_stale_expiry_rejects_without_extra_period(context):
    db, app, user, _, _, plan, service = context
    await service.adjust(user.id, request(plan.id))
    with pytest.raises(CustomException, match="订阅已变化"):
        await service.adjust(user.id, request(plan.id))
    assert await db.scalar(select(func.count()).select_from(DurationAdjustmentModel).where(DurationAdjustmentModel.app_id == app.id)) == 1
    assert await db.scalar(select(func.count()).select_from(SubscriptionCycleModel).where(SubscriptionCycleModel.app_id == app.id)) == 1


async def test_response_roundtrip_preserves_expiry_precision(context):
    db, _, user, _, staff, plan, service = context
    first = await service.adjust(user.id, request(plan.id))
    response = await duration_state(staff, db, user.id)
    state = json.loads(response.body)["data"]
    assert datetime.fromisoformat(state["expires_at"]) == utc(first.after_expires_at)
    assert datetime.fromisoformat(state["server_time"]).tzinfo is not None
    response = await adjust_duration(staff, db, user.id, request(plan.id, expected_expires_at=state["expires_at"]))
    result = json.loads(response.body)["data"]
    assert datetime.fromisoformat(result["after_expires_at"]) == utc(first.after_expires_at) + timedelta(days=30)


async def test_missing_plan_and_no_time_to_deduct(context):
    _, _, user, _, _, _, service = context
    with pytest.raises(CustomException, match="请选择"):
        await service.adjust(user.id, request())
    with pytest.raises(CustomException, match="没有可扣减"):
        await service.adjust(user.id, request(direction="deduct"))


async def test_actor_mode_and_app_scope(context):
    db, app, user, client, staff, plan, service = context
    with pytest.raises(CustomException, match="仅运营"):
        await DurationAdjustmentService(db, client).adjust(user.id, request(plan.id))
    _, foreign_user, _, _, _ = await scope(db)
    with pytest.raises(CustomException, match="不存在该用户"):
        await service.state(foreign_user.id)
    with pytest.raises(CustomException, match="不存在该用户"):
        await service.adjust(foreign_user.id, request(plan.id))
    app.platform_model_enabled = True
    app.service_mode = "credits_only"
    await db.flush()
    with pytest.raises(CustomException, match="积分模式"):
        await service.adjust(user.id, request(plan.id))
    denied = staff.model_copy(update={"user": staff.user.model_copy(update={"is_superuser": False}), "permissions": []})
    with pytest.raises(CustomException):
        await AuthPermission(["workspace:user:management:duration"])(denied, db)


async def test_manual_time_blocks_mode_change(context):
    db, app, user, _, _, plan, service = context
    await service.adjust(user.id, request(plan.id))
    with pytest.raises(CustomException):
        await change_model_policy(db, app, True, expected_version=1)


@pytest.mark.parametrize("changes", [{"days": 0}, {"days": 3651}, {"days": 1.5}, {"days": True}, {"reason": "  "}, {"idempotency_key": "short"}, {"app_id": 99}, {"direction": "set"}])
def test_input_validation(changes):
    with pytest.raises(ValidationError):
        request(1, **changes)


def test_migration_creates_audit_schema_and_existing_install_permission(test_client):
    del test_client
    from app.api.v1.module_system.menu.model import MenuModel

    module = importlib.import_module("app.alembic.versions.20261010_duration_adjustment")
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        MenuModel.__table__.create(connection)
        connection.execute(MenuModel.__table__.insert().values(name="用户管理", permission="workspace:user:management:list"))
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
        assert {c.name for c in DurationAdjustmentModel.__table__.columns} == {c["name"] for c in inspect(connection).get_columns("duration_adjustment")}
        assert connection.scalar(text("SELECT COUNT(*) FROM sys_menu WHERE permission='workspace:user:management:duration'")) == 1
        assert {i.name for i in DurationAdjustmentModel.__table__.indexes} == {i["name"] for i in inspect(connection).get_indexes("duration_adjustment")}


def test_duration_routes_require_auth(test_client):
    path = "/api/v1/operations/billing/subscriptions/users/1/duration"
    for method in ("get", "post"):
        response = getattr(test_client, method)(path)
        assert response.status_code in (401, 403)


def test_migration_compiles_postgresql_without_database():
    output = io.StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "literal_binds": True, "output_buffer": output})
    module = importlib.import_module("app.alembic.versions.20261010_duration_adjustment")
    with Operations.context(context):
        module.upgrade()
    sql = output.getvalue()
    assert "CREATE TABLE duration_adjustment" in sql
    assert "TIMESTAMP WITH TIME ZONE" in sql
    assert "workspace:user:management:duration" in sql
    assert ":permission" not in sql
