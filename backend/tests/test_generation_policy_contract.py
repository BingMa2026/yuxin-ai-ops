import importlib
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import StringIO

import httpx
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from test_generation_policy import settings

from app.api.v1.module_billing.service import CreditService
from app.api.v1.module_client.app.model import ClientAppModel
from app.api.v1.module_client.user.model import ClientUserModel
from app.api.v1.module_model_gateway import gateway as gateway_module
from app.api.v1.module_model_gateway.gateway import ModelGatewayService, _reservation_cost
from app.api.v1.module_model_gateway.model import (
    AppModelBindingModel,
    AppModelRouteModel,
    ModelCatalogModel,
    ModelProviderAccountModel,
    ModelProviderTemplateModel,
    ModelPurchasePriceVersionModel,
    ModelUsageModel,
)
from app.api.v1.module_model_gateway.schema import AppModelRouteCreate, RuntimeCompletionRequest
from app.api.v1.module_model_gateway.secret_codec import encrypt_settings
from app.api.v1.module_model_gateway.service import ClientModelService, ModelAdminService
from app.core.base_schema import AuthSchema, CoreUserSchema
from app.core.database import async_db_session
from app.core.exceptions import CustomException


async def seed_route(*, credits=10000, generation_settings=None, alternate_model=None):
    suffix = uuid.uuid4().hex[:10]
    async with async_db_session() as db, db.begin():
        app = ClientAppModel(service_mode="credits_only", code=f"policy_{suffix}", name="隔离策略测试", status="active")
        db.add(app)
        await db.flush()
        user = ClientUserModel(app_id=app.id, username=f"policy_{suffix}", password_hash="isolated-unused", status="active")
        template = await db.scalar(sa.select(ModelProviderTemplateModel).where(ModelProviderTemplateModel.protocol == "openai_compatible"))
        db.add(user)
        await db.flush()
        account = ModelProviderAccountModel(
            template_id=template.id,
            code=f"policy_{suffix}",
            name="隔离供应商",
            endpoint="https://models.invalid",
            settings_cipher=encrypt_settings({"api_key": "isolated-provider-secret"}),
            masked_summary={},
            timeout_seconds=120,
            status="active",
            connection_status="healthy",
        )
        db.add(account)
        await db.flush()
        binding_ids = []
        for index, model_id in enumerate(["qwen3.8-max", *([alternate_model] if alternate_model else [])]):
            model = ModelCatalogModel(
                provider_account_id=account.id,
                provider_model_id=model_id,
                display_name=model_id,
                context_length=1_000_000 if model_id == "qwen3.8-max" else None,
                supports_stream=True,
                input_cost_per_million=Decimal("1"),
                output_cost_per_million=Decimal("2"),
                status="active",
            )
            db.add(model)
            await db.flush()
            binding = AppModelBindingModel(
                app_id=app.id,
                catalog_model_id=model.id,
                public_model_code=f"policy_{index}",
                client_display_name="隔离模型",
                status="active",
                user_selectable=True,
                visible=True,
            )
            db.add(binding)
            db.add(
                ModelPurchasePriceVersionModel(
                    provider_account_id=account.id,
                    catalog_model_id=model.id,
                    provider_model_id=model_id,
                    input_cost_per_million=Decimal("1"),
                    output_cost_per_million=Decimal("2"),
                    reasoning_cost_per_million=Decimal("7"),
                    effective_from=datetime.now(UTC) - timedelta(days=1),
                    status="active",
                )
            )
            await db.flush()
            binding_ids.append(binding.id)
        admin = AuthSchema(user=CoreUserSchema(id=1, username="admin"), app_id=app.id)
        await ModelAdminService(admin, db).create_route(
            AppModelRouteCreate(
                business_code="document_intelligence",
                name="隔离提取",
                primary_binding_id=binding_ids[0],
                max_output_tokens=8192,
                generation_settings=generation_settings,
                status="active",
            )
        )
        await CreditService(db).adjust(app.id, user.id, credits, "隔离测试额度", operator_id=1)
        return AuthSchema(user=CoreUserSchema(id=user.id, username=user.username), actor_type="runtime", app_id=app.id), binding_ids


def request(**changes):
    return RuntimeCompletionRequest(
        **{
            "request_id": "policy:" + uuid.uuid4().hex,
            "business_code": "document_intelligence",
            "messages": [{"role": "user", "content": "请按 JSON 提取这段中文"}],
            "max_output_tokens": 200,
            **changes,
        }
    )


async def test_real_route_crud_reserve_payload_settlement_and_public_policy(test_client, monkeypatch):
    auth, _ = await seed_route(generation_settings=settings())
    service = ModelGatewayService(auth)
    data = request()
    prepared = await service.prepare_stream(data)
    assert prepared.generation_settings.model_dump() == settings()
    assert prepared.reserved_cost_yuan == _reservation_cost(prepared.candidates, prepared.input_tokens_estimate, 200, generation_settings=prepared.generation_settings)
    assert prepared.reserved_cost_yuan > Decimal("0.029072")  # includes thinking at its own price
    assert prepared.max_output_tokens == 200

    def upstream(req):
        payload = json.loads(req.content)
        assert payload["thinking_budget"] == 4096 and payload["max_tokens"] == 200
        chunks = [
            {"choices": [{"delta": {"reasoning_content": "思考"}}]},
            {"choices": [{"delta": {"content": "{}"}, "finish_reason": "stop"}]},
            {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 30, "completion_tokens_details": {"reasoning_tokens": 20}}},
        ]
        return httpx.Response(200, text="".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n")

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        monkeypatch.setattr(gateway_module, "get_provider_http_client", lambda: client)
        events = b"".join([part async for part in service.stream(data, prepared=prepared)])
        assert b"event: done" in events
    async with async_db_session() as db:
        usage = await db.scalar(sa.select(ModelUsageModel).where(ModelUsageModel.request_id == data.request_id))
        assert usage.provider_cost_yuan == Decimal("0.00017000")
        assert usage.execution_snapshot["generation_settings"] == settings()
        assert usage.execution_snapshot["usage_complete"] is True
        assert usage.execution_snapshot["budget_exceeded"] is False
        assert "isolated-provider-secret" not in json.dumps(usage.execution_snapshot)
        config = await ClientModelService(auth, db).config()
        assert config.routes[0].generation_settings.model_dump() == settings()
        assert config.routes[0].generation_policy_status == "GOVERNED"
        assert config.models[0].supports_thinking is True
        assert config.models[0].context_window == 1_000_000
        account = await CreditService(db).account(auth.app_id, auth.user.id)
        assert account.reserved == 0


async def test_governed_low_balance_does_not_shrink_thinking_or_json_answer(test_client):
    auth, _ = await seed_route(credits=1, generation_settings=settings())
    with pytest.raises(CustomException) as caught:
        await ModelGatewayService(auth).prepare_stream(request())
    assert caught.value.status_code == 402
    async with async_db_session() as db:
        account = await CreditService(db).account(auth.app_id, auth.user.id)
        assert account.available == 1 and account.reserved == 0


async def test_client_can_disable_but_not_enable_unapproved_thinking(test_client):
    auth, _ = await seed_route(generation_settings=settings())
    prepared = await ModelGatewayService(auth).prepare_stream(request(thinking=False))
    assert prepared.generation_settings.enable_thinking is False
    assert prepared.generation_settings.thinking_budget_tokens == 0

    locked_auth, _ = await seed_route(generation_settings=settings(enable_thinking=False, thinking_budget_tokens=0))
    with pytest.raises(CustomException) as caught:
        await ModelGatewayService(locked_auth).prepare_stream(request(thinking=True))
    assert caught.value.status_code == 422


async def test_legacy_business_thinking_preserves_visual_input_and_existing_billing(test_client):
    auth, _ = await seed_route(generation_settings=None)
    service = ModelGatewayService(auth)
    text_request = request(thinking=True)
    prepared = await service.prepare_stream(text_request)
    assert prepared.generation_settings is None
    payload = service._payload(
        text_request,
        prepared.candidates[0],
        stream=False,
        max_output_tokens=prepared.max_output_tokens,
        generation_settings=None,
    )
    assert payload["enable_thinking"] is True and "thinking_budget" not in payload

    visual_messages = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "https://example.invalid/page.png"}}]}]
    on_request = request(thinking=True, messages=visual_messages)
    visual_on_prepared = await service.prepare_stream(on_request)
    assert visual_on_prepared.generation_settings is None
    on_payload = service._payload(
        on_request,
        visual_on_prepared.candidates[0],
        stream=False,
        max_output_tokens=visual_on_prepared.max_output_tokens,
        generation_settings=None,
    )
    assert on_payload["enable_thinking"] is True
    assert on_payload["messages"] == [message.model_dump(exclude_none=True) for message in on_request.messages]
    await service._finalize(on_request, visual_on_prepared, visual_on_prepared.candidates[0], 20, 10, status="succeeded")
    off_request = request(thinking=False, messages=visual_messages)
    visual_prepared = await service.prepare_stream(off_request)
    assert visual_prepared.generation_settings is None
    off_payload = service._payload(
        off_request,
        visual_prepared.candidates[0],
        stream=False,
        max_output_tokens=visual_prepared.max_output_tokens,
        generation_settings=None,
    )
    assert off_payload["enable_thinking"] is False


async def test_runtime_and_admin_reject_unsupported_fallback_or_user_override(test_client):
    auth, ids = await seed_route(generation_settings=settings(), alternate_model="unrelated-model")
    with pytest.raises(CustomException) as caught:
        await ModelGatewayService(auth).prepare_stream(request(model="policy_1"))
    assert caught.value.status_code == 422
    async with async_db_session() as db, db.begin():
        admin = AuthSchema(user=CoreUserSchema(id=1, username="admin"), app_id=auth.app_id)
        with pytest.raises(CustomException):
            await ModelAdminService(admin, db).create_route(
                AppModelRouteCreate(
                    business_code="document_intelligence",
                    name="不兼容备用",
                    primary_binding_id=ids[0],
                    fallback_binding_ids=[ids[1]],
                    max_output_tokens=8192,
                    generation_settings=settings(),
                    status="active",
                )
            )
        current = await db.scalar(sa.select(AppModelRouteModel).where(AppModelRouteModel.app_id == auth.app_id))
        assert current.fallback_binding_ids == []


async def test_route_answer_upper_bound_guard_remains_before_reservation(test_client):
    auth, _ = await seed_route(generation_settings=settings())
    with pytest.raises(CustomException) as caught:
        await ModelGatewayService(auth).prepare_stream(request(max_output_tokens=8193))
    assert "8192" in caught.value.msg
    async with async_db_session() as db:
        assert (await CreditService(db).account(auth.app_id, auth.user.id)).reserved == 0


async def test_legacy_database_route_remains_unmanaged_and_has_no_thinking_payload(test_client):
    auth, _ = await seed_route()
    service = ModelGatewayService(auth)
    prepared = await service.prepare_stream(request())
    assert prepared.generation_settings is None
    payload = service._payload(request(), prepared.candidates[0], stream=False, max_output_tokens=prepared.max_output_tokens)
    assert not {"thinking_budget", "enable_thinking", "response_format"} & payload.keys()
    async with async_db_session() as db:
        config = await ClientModelService(auth, db).config()
        assert config.routes[0].generation_settings is None
        assert config.routes[0].generation_policy_status == "LEGACY_UNMANAGED"


async def test_older_route_form_omission_preserves_policy_but_explicit_null_disables_it(test_client):
    auth, ids = await seed_route(generation_settings=settings(), alternate_model="incompatible-model")
    async with async_db_session() as db, db.begin():
        admin = ModelAdminService(AuthSchema(user=CoreUserSchema(id=1, username="admin"), app_id=auth.app_id), db)
        values = {"business_code": "document_intelligence", "name": "改名称仍治理", "primary_binding_id": ids[0], "max_output_tokens": 8192, "status": "active"}
        output = await admin.create_route(AppModelRouteCreate(**values))
        assert output.generation_settings.model_dump() == settings()
        with pytest.raises(CustomException):
            await admin.create_route(AppModelRouteCreate(**{**values, "primary_binding_id": ids[1]}))
        with pytest.raises(CustomException):
            await admin.create_route(AppModelRouteCreate(**{**values, "max_output_tokens": None}))
        output = await admin.create_route(AppModelRouteCreate(**values, generation_settings=None))
        assert output.generation_settings is None


async def test_resolution_freezes_policy_before_later_route_edits_and_starts_clock_before_reserve(test_client, monkeypatch):
    auth, ids = await seed_route(generation_settings=settings())
    observed_reserve = []
    original = CreditService.reserve_cost

    async def reserve(self, *args, **kwargs):
        observed_reserve.append(time.perf_counter())
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(CreditService, "reserve_cost", reserve)
    prepared = await ModelGatewayService(auth).prepare_stream(request())
    assert prepared.started_at <= observed_reserve[0]
    async with async_db_session() as db, db.begin():
        admin = ModelAdminService(AuthSchema(user=CoreUserSchema(id=1, username="admin"), app_id=auth.app_id), db)
        await admin.create_route(
            AppModelRouteCreate(
                business_code="document_intelligence",
                name="新的生成配置",
                primary_binding_id=ids[0],
                max_output_tokens=8192,
                generation_settings=settings(thinking_budget_tokens=16384),
                status="active",
            )
        )
        current = await ClientModelService(auth, db).config()
        assert current.routes[0].generation_settings.thinking_budget_tokens == 16384
    assert prepared.generation_settings.thinking_budget_tokens == 4096


@pytest.mark.parametrize("actual, status, expected_state", [(True, "succeeded", "budget_exceeded"), (True, "failed", "usage_incomplete"), (False, "failed", "usage_incomplete")])
async def test_budget_drift_and_partial_usage_are_persisted_as_uncertain_not_refund_proof(test_client, actual, status, expected_state):
    auth, _ = await seed_route(generation_settings=settings())
    service = ModelGatewayService(auth)
    data = request()
    prepared = await service.prepare_stream(data)
    output = 5000 if status == "succeeded" else 30
    usage = {"input_tokens": 10, "uncached_input_tokens": 10, "cache_read_tokens": 0, "cache_write_tokens": 0, "output_tokens": output, "reasoning_tokens": output - 10}
    await service._finalize(data, prepared, prepared.candidates[0], 10, output, status=status, usage_detail=usage, usage_is_actual=actual)
    async with async_db_session() as db:
        row = await db.scalar(sa.select(ModelUsageModel).where(ModelUsageModel.request_id == data.request_id))
        assert row.reconciliation_status == expected_state
        assert row.execution_snapshot["usage_complete"] is (actual and status == "succeeded")
        assert row.execution_snapshot["usage_reported"] is actual
        if status == "failed" and actual:
            assert row.cost_precision == "observed_partial_usage"


def test_generation_migration_keeps_legacy_rows_null_and_preserves_evidence_on_downgrade():
    migration = importlib.import_module("app.alembic.versions.20260914_generation_policy")
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE app_model_route (id INTEGER PRIMARY KEY, name TEXT)")
        connection.exec_driver_sql("CREATE TABLE model_usage (id INTEGER PRIMARY KEY, request_id TEXT)")
        connection.exec_driver_sql("INSERT INTO app_model_route VALUES (1, 'legacy')")
        connection.exec_driver_sql("INSERT INTO model_usage VALUES (1, 'historical')")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()  # ORM-created/new empty environments are safe too.
            assert connection.exec_driver_sql("SELECT generation_settings FROM app_model_route").scalar() is None
            assert connection.exec_driver_sql("SELECT execution_snapshot FROM model_usage").scalar() is None
            connection.execute(sa.text("UPDATE model_usage SET execution_snapshot=:value"), {"value": '{"generation_policy_status":"GOVERNED"}'})
            with pytest.raises(RuntimeError, match="evidence"):
                migration.downgrade()
            assert connection.exec_driver_sql("SELECT request_id FROM model_usage").scalar() == "historical"
    output = StringIO()
    with Operations.context(MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})):
        migration.upgrade()
    assert "ALTER TABLE app_model_route ADD COLUMN generation_settings JSON" in output.getvalue()
    assert "ALTER TABLE model_usage ADD COLUMN execution_snapshot JSON" in output.getvalue()
    engine.dispose()
