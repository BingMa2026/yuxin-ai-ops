import asyncio
import importlib
import time
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from test_model_gateway import _binding

from app.api.v1.module_model_gateway import gateway as gateway_module
from app.api.v1.module_model_gateway.gateway import ModelGatewayService, PreparedRequest
from app.api.v1.module_model_gateway.schema import AppModelRouteCreate, ProviderAccountUpdate, RuntimeCompletionRequest
from app.core.exceptions import CustomException


def test_gateway_classifies_only_supplier_image_url_rejections() -> None:
    request = httpx.Request("POST", "https://supplier.invalid/chat/completions")
    rejected = httpx.Response(400, request=request, json={"error": {"code": "invalid_parameter_error", "message": "The provided URL does not appear to be valid"}})
    other = httpx.Response(400, request=request, json={"error": {"code": "invalid_parameter_error", "message": "Invalid model parameter"}})
    assert gateway_module._invalid_image_url_error(httpx.HTTPStatusError("rejected", request=request, response=rejected))
    assert not gateway_module._invalid_image_url_error(httpx.HTTPStatusError("other", request=request, response=other))


def settings(**changes):
    return {
        "policy_version": "qwen3.8-bounded-v1",
        "enable_thinking": True,
        "thinking_budget_tokens": 4096,
        "total_timeout_seconds": 600,
        "response_format": "json_object",
        **changes,
    }


def route(**changes):
    return AppModelRouteCreate(**{"business_code": "document_intelligence", "name": "文档提取", "primary_binding_id": 1, "max_output_tokens": 8192, "generation_settings": settings(), **changes})


def policy(**changes):
    module = importlib.import_module("app.api.v1.module_model_gateway.generation_policy")
    return module.GenerationSettings.model_validate(settings(**changes))


def request():
    return RuntimeCompletionRequest(request_id="governed-request-test", messages=[{"role": "user", "content": "请输出 JSON"}])


@pytest.mark.parametrize(
    "changes",
    [
        {"thinking_budget_tokens": -1},
        {"thinking_budget_tokens": 262145},
        {"enable_thinking": False},
        {"thinking_budget_tokens": 0},
        {"total_timeout_seconds": 1801},
        {"total_timeout_seconds": 0},
        {"reasoning_effort": "xhigh"},
        {"extra_body": {"enable_search": True}},
        {"response_format": "json_schema"},
        {"policy_version": "guessed-v2"},
    ],
)
def test_route_rejects_ungoverned_or_conflicting_generation_fields(changes):
    with pytest.raises(ValidationError):
        route(generation_settings=settings(**changes))


def test_governed_route_requires_an_explicit_answer_upper_bound():
    with pytest.raises(ValidationError):
        route(max_output_tokens=None)


def test_thirty_minute_timeout_fits_within_credit_reservation_lifetime():
    from app.api.v1.module_billing.reservation_policy import RESERVATION_STALE_SECONDS

    configured = route(timeout_seconds=1800, generation_settings=settings(total_timeout_seconds=1800))
    assert configured.timeout_seconds == configured.generation_settings.total_timeout_seconds == 1800
    assert ProviderAccountUpdate(timeout_seconds=1800).timeout_seconds == 1800
    assert RESERVATION_STALE_SECONDS > 1800
    with pytest.raises(ValidationError):
        ProviderAccountUpdate(timeout_seconds=1801)


def test_route_round_trips_policy_and_keeps_unconfigured_routes_legacy():
    assert route().model_dump()["generation_settings"] == settings()
    assert route(generation_settings=None).model_dump()["generation_settings"] is None
    assert route(generation_settings=settings(enable_thinking=False, thinking_budget_tokens=0)).generation_settings.enable_thinking is False


def test_client_thinking_override_can_only_reduce_operator_budget():
    module = importlib.import_module("app.api.v1.module_model_gateway.generation_policy")
    approved = policy()
    assert module.effective_thinking_settings(approved, None) == approved
    assert module.effective_thinking_settings(approved, True) == approved
    off = module.effective_thinking_settings(approved, False)
    assert off.enable_thinking is False and off.thinking_budget_tokens == 0
    assert off.total_timeout_seconds == approved.total_timeout_seconds
    with pytest.raises(CustomException):
        module.effective_thinking_settings(None, True)
    with pytest.raises(CustomException):
        module.effective_thinking_settings(policy(enable_thinking=False, thinking_budget_tokens=0), True)
    assert module.effective_thinking_settings(None, True, allow_legacy_business=True) is None


def test_qwen_payload_consumes_actual_independent_answer_and_thinking_limits():
    binding = replace(_binding(), provider_model_id="qwen3.8-max")
    payload = ModelGatewayService._payload(request(), binding, stream=True, max_output_tokens=200, generation_settings=policy())
    assert payload["max_tokens"] == 200
    assert payload["thinking_budget"] == 4096
    assert payload["enable_thinking"] is True
    assert payload["response_format"] == {"type": "json_object"}
    assert not {"reasoning_effort", "max_completion_tokens", "extra_body"} & payload.keys()


def test_legacy_gateway_preserves_engine_tool_and_json_options():
    tool = {"type": "function", "function": {"name": "finish_matters", "parameters": {"type": "object"}}}
    request_data = RuntimeCompletionRequest(
        request_id="engine-options-test",
        business_code="document_intelligence",
        messages=[{"role": "user", "content": "请输出 JSON"}],
        tools=[tool],
        tool_choice={"type": "function", "function": {"name": "finish_matters"}},
        parallel_tool_calls=False,
        response_format={"type": "json_object"},
        thinking=True,
        thinking_budget_tokens=4096,
    )
    binding = replace(_binding(), provider_model_id="qwen3.8-max")
    payload = ModelGatewayService._payload(request_data, binding, stream=False, max_output_tokens=8192)
    assert payload["tool_choice"] == request_data.tool_choice
    assert payload["parallel_tool_calls"] is False
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["enable_thinking"] is True
    assert payload["thinking_budget"] == 4096


def test_runtime_rejects_forced_tool_outside_offered_tools():
    with pytest.raises(ValidationError):
        RuntimeCompletionRequest(
            request_id="invalid-tool-test",
            messages=[{"role": "user", "content": "继续"}],
            tools=[{"type": "function", "function": {"name": "read_source"}}],
            tool_choice={"type": "function", "function": {"name": "finish_matters"}},
        )


@pytest.mark.parametrize("model", ["qwen3.7-max", "qwen3.8-27b", "qwen3.8-max-guessed", "gpt-any"])
def test_policy_rejects_unsupported_models_in_the_actual_payload_path(model):
    with pytest.raises(CustomException):
        ModelGatewayService._payload(request(), replace(_binding(), provider_model_id=model), stream=False, max_output_tokens=200, generation_settings=policy())


def test_reservation_separates_thinking_price_and_output_price():
    binding = replace(_binding(), output_cost_per_million=Decimal("2"), reasoning_cost_per_million=Decimal("7"))
    value = gateway_module._reservation_cost([binding], 100, 200, generation_settings=policy())
    assert value == Decimal("0.02917200")  # 100*1 + 200*2 + 4096*7, per million
    fallback = replace(binding, reasoning_cost_per_million=Decimal("0"))
    assert gateway_module._reservation_cost([fallback], 100, 200, generation_settings=policy()) == Decimal("0.00869200")
    assert gateway_module._reservation_credits([binding], 100, 200, generation_settings=policy()) == 44


def test_input_reservation_is_explicitly_bounded_and_does_not_count_url_as_image_tokens():
    module = importlib.import_module("app.api.v1.module_model_gateway.generation_policy")
    assert module.estimate_text_input(request()) >= len("请输出 JSON".encode())
    oversized = request().model_copy(update={"messages": request().messages * 200})
    assert module.estimate_text_input(oversized) <= module.MAX_INPUT_RESERVATION_TOKENS
    multimodal = RuntimeCompletionRequest(request_id="image-unsupported-test", messages=[{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "https://images.invalid/p.png"}}]}])
    with pytest.raises(CustomException):
        module.estimate_text_input(multimodal)
    over_limit = RuntimeCompletionRequest(request_id="text-too-large-test", messages=[{"role": "user", "content": "字" * module.MAX_INPUT_RESERVATION_TOKENS}])
    with pytest.raises(CustomException):
        module.estimate_text_input(over_limit)


def test_cache_creation_cost_is_reserved_and_zero_actual_usage_is_not_replaced_by_estimate():
    binding = replace(_binding(), cache_write_cost_per_million=Decimal("9"))
    assert gateway_module._reservation_cost([binding], 100, 200, generation_settings=policy()) == Decimal("0.00519600")
    normalized, actual = gateway_module._normalized_usage({"prompt_tokens": 0, "completion_tokens": 0}, input_fallback=999, output_fallback=888)
    assert actual and normalized["input_tokens"] == 0 and normalized["output_tokens"] == 0


def test_missing_reasoning_breakdown_is_not_a_complete_priced_usage_report():
    module = importlib.import_module("app.api.v1.module_model_gateway.generation_policy")
    assert module.complete_usage_report(policy(), {"completion_tokens": 20}) is False
    assert module.complete_usage_report(policy(), {"prompt_tokens": 10, "completion_tokens": 20}) is False
    assert module.complete_usage_report(policy(), {"prompt_tokens": 10, "completion_tokens": 20, "completion_tokens_details": {"reasoning_tokens": 0}}) is True


@pytest.mark.parametrize("stream", [False, True])
async def test_total_deadline_is_from_preparation_and_does_not_reset_for_candidate(monkeypatch, stream):
    calls = []

    def upstream(req):
        calls.append(req)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]})

    prepared = PreparedRequest(
        [replace(_binding(), provider_model_id="qwen3.8-max")],
        100,
        200,
        20,
        Decimal("1"),
        True,
        time.perf_counter() - 5,
        generation_settings=policy(total_timeout_seconds=1),
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        monkeypatch.setattr(gateway_module, "get_provider_http_client", lambda: client)
        service = ModelGatewayService(SimpleNamespace(actor_type="runtime", app_id=1, user=SimpleNamespace(id=2)))
        service._resolve = AsyncMock(return_value=prepared)
        service._finalize = AsyncMock(return_value=0)
        if stream:
            events = b"".join([chunk async for chunk in service.stream(request())]).decode()
            assert "UPSTREAM_TOTAL_TIMEOUT" in events and "event: done" not in events
        else:
            with pytest.raises(CustomException) as caught:
                await service.complete(request())
            assert caught.value.status_code == 504
        assert not calls
        assert service._finalize.await_count == 1
        assert service._finalize.call_args.kwargs["error_category"] == "upstream_total_timeout"
        assert service._finalize.call_args.args[2] is None  # No upstream request was started; no estimated input charge.


async def test_active_reasoning_cannot_extend_governed_total_deadline(monkeypatch):
    class ReasoningStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(100):
                await asyncio.sleep(0.01)
                yield b'data: {"choices":[{"delta":{"reasoning_content":"think"}}]}\n\n'

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, stream=ReasoningStream()))) as client:
        monkeypatch.setattr(gateway_module, "get_provider_http_client", lambda: client)
        service = ModelGatewayService(SimpleNamespace(actor_type="runtime", app_id=1, user=SimpleNamespace(id=2)))
        service._resolve = AsyncMock(
            return_value=PreparedRequest(
                [replace(_binding(), provider_model_id="qwen3.8-max")],
                100,
                200,
                20,
                Decimal("1"),
                True,
                time.perf_counter() - 0.9,
                generation_settings=policy(total_timeout_seconds=1),
            )
        )
        service._finalize = AsyncMock(return_value=0)
        events = b"".join([chunk async for chunk in service.stream(request())]).decode()
        assert "reasoning_delta" in events
        assert "UPSTREAM_TOTAL_TIMEOUT" in events and "event: done" not in events
        assert service._finalize.await_count == 1
        assert service._finalize.call_args.kwargs["status"] == "failed"


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("governed", [False, True])
async def test_read_timeout_is_classified_without_body_or_key_and_does_not_retry_paid_work(monkeypatch, stream, governed):
    calls = []

    def upstream(req):
        calls.append(req)
        raise httpx.ReadTimeout("SECRET-KEY upstream private body", request=req)

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        monkeypatch.setattr(gateway_module, "get_provider_http_client", lambda: client)
        service = ModelGatewayService(SimpleNamespace(actor_type="runtime", app_id=1, user=SimpleNamespace(id=2)))
        binding = replace(_binding(), provider_model_id="qwen3.8-max")
        service._resolve = AsyncMock(return_value=PreparedRequest([binding, binding], 100, 200, 20, Decimal("1"), True, time.perf_counter(), generation_settings=policy() if governed else None))
        service._finalize = AsyncMock(return_value=0)
        if stream:
            output = b"".join([chunk async for chunk in service.stream(request())]).decode()
            assert "UPSTREAM_IDLE_TIMEOUT" in output
        else:
            with pytest.raises(CustomException) as caught:
                await service.complete(request())
            assert caught.value.status_code == 504
            output = str(caught.value)
        assert "SECRET" not in output
        assert len(calls) == 1
        assert service._finalize.call_args.kwargs["error_category"] == "upstream_idle_timeout"


async def test_malformed_usage_does_not_fail_again_while_recording_protocol_failure(monkeypatch):
    body = (
        'data: {"choices":[{"delta":{"reasoning_content":"think"}}]}\n\n'
        'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":30,"completion_tokens_details":"invalid"}}\n\n'
        "data: [DONE]\n\n"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, text=body))) as client:
        monkeypatch.setattr(gateway_module, "get_provider_http_client", lambda: client)
        service = ModelGatewayService(SimpleNamespace(actor_type="runtime", app_id=1, user=SimpleNamespace(id=2)))
        service._resolve = AsyncMock(
            return_value=PreparedRequest(
                [replace(_binding(), provider_model_id="qwen3.8-max")],
                100,
                200,
                20,
                Decimal("1"),
                True,
                time.perf_counter(),
                generation_settings=policy(),
            )
        )
        service._finalize = AsyncMock(return_value=0)
        events = b"".join([chunk async for chunk in service.stream(request())]).decode()
        assert "UPSTREAM_PROTOCOL_ERROR" in events and "event: done" not in events
        assert service._finalize.await_count == 1
        assert service._finalize.call_args.kwargs["status"] == "failed"


@pytest.mark.parametrize("stream", [False, True])
async def test_safe_connection_fallback_shares_original_total_deadline(monkeypatch, stream):
    deadline = importlib.import_module("app.api.v1.module_model_gateway.generation_deadline")
    clock = [0.0]
    monkeypatch.setattr(deadline, "time", SimpleNamespace(perf_counter=lambda: clock[0]))
    calls = []

    def upstream(req):
        calls.append(req)
        clock[0] = 2.0  # Connection consumed the original one-second allowance.
        raise httpx.ConnectError("connection failed before sending request", request=req)

    binding = replace(_binding(), provider_model_id="qwen3.8-max")
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        monkeypatch.setattr(gateway_module, "get_provider_http_client", lambda: client)
        service = ModelGatewayService(SimpleNamespace(actor_type="runtime", app_id=1, user=SimpleNamespace(id=2)))
        service._resolve = AsyncMock(return_value=PreparedRequest([binding, binding], 100, 200, 20, Decimal("1"), True, 0.0, generation_settings=policy(total_timeout_seconds=1)))
        service._finalize = AsyncMock(return_value=0)
        if stream:
            events = b"".join([part async for part in service.stream(request())]).decode()
            assert "UPSTREAM_TOTAL_TIMEOUT" in events and "event: done" not in events
        else:
            with pytest.raises(CustomException) as caught:
                await service.complete(request())
            assert caught.value.code == 50401
        assert len(calls) == 1  # No fresh allowance for the next candidate.
        assert service._finalize.call_args.args[2] is None
