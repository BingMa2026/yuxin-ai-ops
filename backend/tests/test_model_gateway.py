import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.v1.module_billing.service import CreditService
from app.api.v1.module_client.app.model import ClientAppModel
from app.api.v1.module_client.user.model import ClientUserModel
from app.api.v1.module_model_gateway import gateway as gateway_module
from app.api.v1.module_model_gateway.gateway import (
    ModelGatewayService,
    ResolvedBinding,
    _affordable_output_tokens,
    _normalized_usage,
    _provider_cost_original,
)
from app.api.v1.module_model_gateway.model import (
    AppModelBindingModel,
    AppModelRouteModel,
    ModelCatalogModel,
    ModelProviderAccountModel,
    ModelProviderTemplateModel,
    ModelUsageModel,
)
from app.api.v1.module_model_gateway.schema import RuntimeCompletionRequest
from app.api.v1.module_model_gateway.secret_codec import encrypt_settings
from app.core.base_schema import AuthSchema, CoreUserSchema
from app.core.database import async_db_session
from app.core.exceptions import CustomException
from app.utils.password_util import PwdUtil


class _FakeCompletionResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "choices": [{"message": {"content": "完成"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }


class _FakeStreamResponse:
    def raise_for_status(self) -> None:
        return None

    async def aiter_lines(self):
        yield 'data: {"choices":[{"delta":{"content":"完"}}]}'
        yield 'data: {"choices":[{"delta":{"content":"成"}}]}'
        yield 'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":5}}'
        yield "data: [DONE]"


class _FakeStreamContext:
    async def __aenter__(self):
        return _FakeStreamResponse()

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback


class _FakeAsyncClient:
    is_closed = False

    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback

    async def aclose(self) -> None:
        self.is_closed = True

    async def post(self, url: str, *, headers: dict, json: dict, timeout=None):
        del timeout
        assert url == "https://models.example.test/chat/completions"
        assert headers["Authorization"] == "Bearer provider-secret"
        assert json["stream"] is False
        return _FakeCompletionResponse()

    def stream(self, method: str, url: str, *, headers: dict, json: dict, timeout=None):
        del timeout
        assert method == "POST"
        assert url == "https://models.example.test/chat/completions"
        assert headers["Authorization"] == "Bearer provider-secret"
        assert json["stream"] is True
        return _FakeStreamContext()


def _binding(*, input_rate: int = 2, output_rate: int = 10) -> ResolvedBinding:
    return ResolvedBinding(
        binding_id=1,
        public_model_code="model",
        provider_account_id=1,
        catalog_model_id=1,
        provider_model_id="upstream-model",
        endpoint="https://models.example.test",
        api_key="provider-secret",
        protocol="openai_compatible",
        timeout_seconds=30,
        input_rate=input_rate,
        output_rate=output_rate,
        minimum_credits=1,
        input_cost_per_million=Decimal("1"),
        cache_read_cost_per_million=Decimal("1"),
        cache_write_cost_per_million=Decimal("1"),
        output_cost_per_million=Decimal("1"),
        reasoning_cost_per_million=Decimal("1"),
        price_version_id=None,
        price_currency="CNY",
        exchange_rate_to_cny=Decimal("1"),
        price_source="test",
    )


def test_gateway_reduces_output_budget_to_available_credits() -> None:
    binding = _binding(input_rate=0, output_rate=10)
    assert _affordable_output_tokens([binding], 10, 1000, 3) == 300
    assert _affordable_output_tokens([binding], 10, 1000, 0) == 0

    request = RuntimeCompletionRequest(
        request_id="request-payload",
        business_code="chat_default",
        messages=[{"role": "user", "content": "test"}],
    )
    payload = ModelGatewayService._payload(
        request,
        binding,
        stream=True,
        max_output_tokens=300,
    )
    assert payload["max_tokens"] == 300


def test_qwen_cached_tokens_are_not_double_charged() -> None:
    binding = _binding()
    usage, actual = _normalized_usage(
        {
            "prompt_tokens": 1000,
            "completion_tokens": 200,
            "prompt_tokens_details": {"cached_tokens": 400},
        },
        input_fallback=0,
        output_fallback=0,
    )
    assert actual is True
    assert usage["uncached_input_tokens"] == 600
    assert usage["cache_read_tokens"] == 400
    assert _provider_cost_original(binding, usage) == Decimal("0.0012000000")


def test_provider_http_pool_reuses_client(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway_module._provider_http_client = None
    monkeypatch.setattr(gateway_module.httpx, "AsyncClient", _FakeAsyncClient)

    first = gateway_module.get_provider_http_client()
    second = gateway_module.get_provider_http_client()

    assert first is second
    gateway_module._provider_http_client = None


@pytest.mark.asyncio
async def test_model_gateway_settles_credits_and_snapshots_provider_cost(
    test_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del test_client
    suffix = uuid.uuid4().hex[:8]
    async with async_db_session() as db, db.begin():
        app = await db.scalar(select(ClientAppModel).where(ClientAppModel.code == "bid_agent"))
        template = await db.scalar(select(ModelProviderTemplateModel).where(ModelProviderTemplateModel.protocol == "openai_compatible"))
        assert app is not None and template is not None
        user = ClientUserModel(
            app_id=app.id,
            username=f"gateway_{suffix}",
            password_hash=PwdUtil.hash_password("Passw0rd!"),
            status="active",
        )
        db.add(user)
        await db.flush()
        account = ModelProviderAccountModel(
            template_id=template.id,
            code=f"gateway_{suffix}",
            name="网关测试账号",
            endpoint="https://models.example.test",
            settings_cipher=encrypt_settings({"api_key": "provider-secret"}),
            masked_summary={"api_key": "••••cret"},
            timeout_seconds=30,
            retry_count=0,
            status="active",
            connection_status="healthy",
        )
        db.add(account)
        await db.flush()
        catalog = ModelCatalogModel(
            provider_account_id=account.id,
            provider_model_id="example-chat",
            display_name="示例模型",
            supports_stream=True,
            input_cost_per_million=Decimal("10"),
            output_cost_per_million=Decimal("20"),
            input_credits_per_1k=2,
            output_credits_per_1k=4,
            minimum_credits=1,
            status="active",
        )
        db.add(catalog)
        await db.flush()
        binding = AppModelBindingModel(
            app_id=app.id,
            catalog_model_id=catalog.id,
            public_model_code="default-chat",
            client_display_name="默认模型",
            visible=True,
            user_selectable=True,
            is_default=True,
            status="active",
        )
        db.add(binding)
        await db.flush()
        db.add(
            AppModelRouteModel(
                app_id=app.id,
                business_code="chat_default",
                name="默认对话",
                primary_binding_id=binding.id,
                fallback_binding_ids=[],
                timeout_seconds=30,
                max_output_tokens=100,
                allow_tools=True,
                allow_user_model=True,
                status="active",
            )
        )
        await CreditService(db).adjust(
            app.id,
            user.id,
            100,
            "模型网关测试积分",
            operator_id=1,
        )
        await CreditService(db).adjust(
            app.id,
            user.id,
            10,
            "同一运营人员再次赠送",
            operator_id=1,
        )
        app_id = app.id
        user_id = user.id
        username = user.username

    monkeypatch.setattr(gateway_module.httpx, "AsyncClient", _FakeAsyncClient)
    gateway_module._provider_http_client = None
    auth = AuthSchema(
        user=CoreUserSchema(id=user_id, username=username),
        actor_type="runtime",
        app_id=app_id,
    )
    request_id = f"gateway:{uuid.uuid4().hex}"
    service = ModelGatewayService(auth)
    finalize = service._finalize

    async def lost_commit_ack(*args, **kwargs):
        await finalize(*args, **kwargs)
        raise TimeoutError("commit acknowledgement lost")

    service._finalize = lost_commit_ack
    request = RuntimeCompletionRequest(
        request_id=request_id,
        business_code="chat_default",
        messages=[{"role": "user", "content": "请完成测试"}],
        max_output_tokens=20,
    )
    pending = await service.complete(request)
    assert pending.content == "完成" and pending.settlement_status == "PENDING"
    service._finalize = finalize
    response = await service.complete(
        RuntimeCompletionRequest(
            request_id=request_id,
            business_code="chat_default",
            messages=[{"role": "user", "content": "请完成测试"}],
            max_output_tokens=20,
        )
    )

    assert response.content == "完成"
    # Provider cost is 0.0002 yuan and the default entitlement snapshot is
    # 2500 credits/yuan, rounded up to one indivisible credit.
    assert response.charged_credits == 1
    async with async_db_session() as db:
        credit_account = await CreditService(db).account(app_id, user_id)
        usage = await db.scalar(
            select(ModelUsageModel).where(
                ModelUsageModel.app_id == app_id,
                ModelUsageModel.request_id == request_id,
            )
        )
        assert usage is not None
        assert credit_account.available == 109
        assert credit_account.reserved == 0
        assert usage.provider_cost_yuan == Decimal("0.00020000")
        assert usage.input_tokens == 10 and usage.output_tokens == 5
        rows = (await db.scalars(select(ModelUsageModel).where(ModelUsageModel.app_id == app_id, ModelUsageModel.request_id == request_id))).all()
        assert len(rows) == 1  # 已提交但回执丢失的结算仍须保持幂等。

    with pytest.raises(CustomException):
        await ModelGatewayService(auth).complete(
            RuntimeCompletionRequest(
                request_id=request_id,
                business_code="chat_default",
                messages=[{"role": "user", "content": "重复请求"}],
            )
        )

    stream_request_id = f"gateway:{uuid.uuid4().hex}"
    events = b"".join(
        [
            event
            async for event in ModelGatewayService(auth).stream(
                RuntimeCompletionRequest(
                    request_id=stream_request_id,
                    business_code="chat_default",
                    messages=[{"role": "user", "content": "请流式完成测试"}],
                    max_output_tokens=20,
                )
            )
        ]
    )
    assert b"event: text_delta" in events
    assert b"event: usage" in events
    assert b"event: done" in events
    async with async_db_session() as db:
        stream_usage = await db.scalar(select(ModelUsageModel).where(ModelUsageModel.request_id == stream_request_id))
        stream_account = await CreditService(db).account(app_id, user_id)
        assert stream_usage is not None
        assert stream_usage.provider_cost_yuan == Decimal("0.00020000")
        assert stream_usage.charged_credits == 1
        assert stream_account.available == 108
        assert stream_account.reserved == 0
    gateway_module._provider_http_client = None
