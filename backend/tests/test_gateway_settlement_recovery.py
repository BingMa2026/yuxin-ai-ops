"""生成与结算分离、持久化重放契约的离线测试。"""

import asyncio
import json
import time
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from test_model_gateway import _binding

from app.api.v1.module_model_gateway import gateway as gateway_module
from app.api.v1.module_model_gateway.gateway import ModelGatewayService, PreparedRequest
from app.api.v1.module_model_gateway.result_journal import ResultJournal
from app.api.v1.module_model_gateway.schema import RuntimeCompletionRequest
from app.api.v1.module_model_gateway.settlement_worker import recover_once
from app.config.setting import settings
from app.core.exceptions import CustomException


async def test_successful_generation_survives_settlement_timeout_and_replays(monkeypatch):
    calls = []

    def upstream(request):
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "保存这个结果"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        monkeypatch.setattr(gateway_module, "get_provider_http_client", lambda: client)
        auth = SimpleNamespace(actor_type="runtime", app_id=1, user=SimpleNamespace(id=2))
        service = ModelGatewayService(auth)
        service._resolve = AsyncMock(return_value=PreparedRequest([_binding()], 100, 200, 20, Decimal("1"), True, time.perf_counter()))
        service._finalize = AsyncMock(side_effect=TimeoutError())
        data = RuntimeCompletionRequest(request_id="settlement-recovery-1", messages=[{"role": "user", "content": "private prompt"}])
        result = await service.complete(data)
        assert result.content == "保存这个结果"
        assert result.settlement_status == "PENDING" and result.charged_credits is None
        assert service._finalize.await_count == 1
        assert service._finalize.call_args.kwargs["status"] == "succeeded"

        # 新服务实例读取持久化结果，不重新生成或预占。
        recovered = ModelGatewayService(auth)
        recovered._resolve = AsyncMock(side_effect=AssertionError("must not generate again"))
        recovered._finalize = AsyncMock(return_value=3)
        replay = await recovered.complete(data)
        assert replay.content == result.content
        assert replay.settlement_status == "SETTLED" and replay.charged_credits == 3
        assert len(calls) == 1


@pytest.mark.parametrize("stream", [False, True])
async def test_restart_worker_recovers_without_model_and_replays_tools(monkeypatch, stream):
    count = 0

    def upstream(request):
        nonlocal count
        count += 1
        call = {"id": "call-1", "type": "function", "function": {"name": "read", "arguments": '{"page":1}'}}
        if stream:
            chunks = [
                {"choices": [{"delta": {"content": "持久结果", "reasoning_content": "理由", "tool_calls": [dict(call, index=0)]}}]},
                {"choices": [{"delta": {}, "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}},
            ]
            return httpx.Response(200, text="".join("data: " + json.dumps(c) + "\n\n" for c in chunks) + "data: [DONE]\n\n")
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "持久结果", "reasoning_content": "理由", "tool_calls": [call]}, "finish_reason": "tool_calls"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    auth = SimpleNamespace(actor_type="runtime", app_id=1, user=SimpleNamespace(id=2))
    request = RuntimeCompletionRequest(request_id="worker-recovery-1", messages=[{"role": "user", "content": "private prompt"}])
    service = ModelGatewayService(auth)
    service._resolve = AsyncMock(return_value=PreparedRequest([_binding()], 100, 200, 20, Decimal("1"), True, time.perf_counter()))
    service._finalize = AsyncMock(side_effect=TimeoutError())
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        monkeypatch.setattr(gateway_module, "get_provider_http_client", lambda: client)
        if stream:
            events = b"".join([event async for event in service.stream(request)]).decode()
            assert "event: done" in events and "event: error" not in events and '"PENDING"' in events
        else:
            assert (await service.complete(request)).settlement_status == "PENDING"

        # 新工作进程从持久化状态恢复，不依赖内存对象。
        from app.api.v1.module_model_gateway import result_journal

        future = time.time() + 61
        monkeypatch.setattr(result_journal, "time", SimpleNamespace(time=lambda: future))
        finalize = AsyncMock(return_value=4)
        monkeypatch.setattr(ModelGatewayService, "_finalize", finalize)
        monkeypatch.setattr(ModelGatewayService, "_resolve", AsyncMock(side_effect=AssertionError("no regeneration")))
        await recover_once()
        await recover_once()
        assert finalize.await_count == 1
        result = await ModelGatewayService(auth).complete(request)
        assert result.content == "持久结果" and result.reasoning_content == "理由"
        assert result.tool_calls[0]["function"]["arguments"] == '{"page":1}'
        assert result.finish_reason == "tool_calls" and result.charged_credits == 4
        assert result.settlement_status == "SETTLED" and count == 1
        events = b"".join([event async for event in ModelGatewayService(auth).stream(request)]).decode()
        assert "持久结果" in events and "call-1" in events and "event: done" in events
        assert count == 1


async def test_cancel_during_settlement_never_finalizes_generation_as_cancelled(monkeypatch):
    service = ModelGatewayService(SimpleNamespace(actor_type="runtime", app_id=1, user=SimpleNamespace(id=2)))
    service._resolve = AsyncMock(return_value=PreparedRequest([_binding()], 100, 200, 20, Decimal("1"), True, time.perf_counter()))
    service._finalize = AsyncMock(side_effect=asyncio.CancelledError())
    request = RuntimeCompletionRequest(request_id="cancel-after-generation", messages=[{"role": "user", "content": "test"}])
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"choices": [{"message": {"content": "结果"}, "finish_reason": "stop"}]}))) as client:
        monkeypatch.setattr(gateway_module, "get_provider_http_client", lambda: client)
        with pytest.raises(asyncio.CancelledError):
            await service.complete(request)
    assert service._finalize.await_count == 1 and service._finalize.call_args.kwargs["status"] == "succeeded"
    assert ResultJournal().read((1, 2, request.request_id))["result"]["content"] == "结果"


async def test_journal_failure_prevents_paid_generation(monkeypatch):
    service = ModelGatewayService(SimpleNamespace(actor_type="runtime", app_id=1, user=SimpleNamespace(id=2)))
    service._resolve = AsyncMock()
    monkeypatch.setattr(ResultJournal, "claim", lambda *args: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(CustomException) as caught:
        await service.complete(RuntimeCompletionRequest(request_id="disk-unavailable", messages=[{"role": "user", "content": "test"}]))
    assert caught.value.code == 50306
    service._resolve.assert_not_awaited()


async def test_success_persistence_failure_does_not_enter_provider_fallback(monkeypatch):
    calls = []

    def upstream(request):
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "result"}, "finish_reason": "stop"}]})

    service = ModelGatewayService(SimpleNamespace(actor_type="runtime", app_id=1, user=SimpleNamespace(id=2)))
    service._resolve = AsyncMock(return_value=PreparedRequest([_binding(), _binding()], 100, 200, 20, Decimal("1"), True, time.perf_counter()))
    service._finalize = AsyncMock()
    request = RuntimeCompletionRequest(request_id="disk-fails-after-generation", messages=[{"role": "user", "content": "test"}])
    monkeypatch.setattr(ResultJournal, "save", lambda *args: (_ for _ in ()).throw(OSError("disk full")))
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        monkeypatch.setattr(gateway_module, "get_provider_http_client", lambda: client)
        with pytest.raises(CustomException) as caught:
            await service.complete(request)
        assert caught.value.code == 50306
        with pytest.raises(CustomException) as replay:
            await service.complete(request)
        assert replay.value.code == 40906
    assert len(calls) == 1
    service._finalize.assert_not_awaited()


async def test_settlement_wait_limit_returns_durable_result(monkeypatch):
    service = ModelGatewayService(SimpleNamespace(actor_type="runtime", app_id=1, user=SimpleNamespace(id=2)))
    service._resolve = AsyncMock(return_value=PreparedRequest([_binding()], 100, 200, 20, Decimal("1"), True, time.perf_counter()))

    async def slow_finalize(*args, **kwargs):
        await asyncio.sleep(10)
        raise AssertionError("must time out locally")

    service._finalize = AsyncMock(side_effect=slow_finalize)
    monkeypatch.setattr(settings, "MODEL_SETTLEMENT_TIMEOUT_SECONDS", 0.01)
    request = RuntimeCompletionRequest(request_id="bounded-accounting-wait", messages=[{"role": "user", "content": "test"}])
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"choices": [{"message": {"content": "saved"}, "finish_reason": "stop"}]}))) as client:
        monkeypatch.setattr(gateway_module, "get_provider_http_client", lambda: client)
        result = await service.complete(request)
    assert result.content == "saved" and result.settlement_status == "PENDING"
    assert ResultJournal().read((1, 2, request.request_id))["result"]["content"] == "saved"
    assert service._finalize.await_count == 1


async def test_runtime_auth_releases_transaction_before_generation(monkeypatch):
    from app.core import client_dependencies

    db = SimpleNamespace(
        scalar=AsyncMock(side_effect=[SimpleNamespace(id=2, username="test", display_name="test", auth_generation=1, mode_version=1), 1, SimpleNamespace(id=1, platform_model_enabled=True, service_mode="credits_only", model_policy_version=1), SimpleNamespace(active_billing_mode="credits")]),
        rollback=AsyncMock(),
    )
    payload = SimpleNamespace(is_refresh=False, actor_type="runtime", app_id=1, sub="test-session", mode_version=1, policy_version=1)
    monkeypatch.setattr(client_dependencies, "decode_access_token", lambda *args, **kwargs: payload)
    monkeypatch.setattr(client_dependencies.RedisCURD, "get", AsyncMock(return_value=json.dumps({"actor_type": "client", "app_id": 1, "user_id": 2, "auth_generation": 1})))
    auth = await client_dependencies.get_current_runtime_user(db=db, redis=SimpleNamespace(), token="test")
    assert auth.user.id == 2 and auth.app_id == 1
    db.rollback.assert_awaited_once()


async def test_concurrent_claims_have_one_owner_and_scope_is_checked():
    key = (1, 2, "concurrent-request")

    def claim():
        try:
            return ResultJournal().claim(key, "hash")
        except CustomException as exc:
            return exc.status_code

    results = await asyncio.gather(*[asyncio.to_thread(claim) for _ in range(8)])
    assert results.count(None) == 1 and results.count(409) == 7
    for invalid_key, invalid_hash in [((1, 3, key[2]), "hash"), (key, "different")]:
        with pytest.raises(CustomException):
            ResultJournal().claim(invalid_key, invalid_hash)
    assert ResultJournal().claim((2, 2, key[2]), "hash") is None


def test_journal_encryption_retention_retry_bound_and_lease(monkeypatch):
    from app.api.v1.module_model_gateway import result_journal

    clock = [time.time()]
    monkeypatch.setattr(result_journal, "time", SimpleNamespace(time=lambda: clock[0]))
    journal = ResultJournal()
    key = (1, 2, "journal-contract")
    payload = {"result": {"content": "sensitive-success-output", "charged_credits": None, "settlement_status": "PENDING"}}
    journal.claim(key, "hash")
    journal.save(key, "hash", payload)
    assert b"sensitive-success-output" not in journal.path.read_bytes()
    for _ in range(12):
        assert journal.take(key) == payload
        assert journal.take(key, force=True) is None
        journal.defer(key)
        assert journal.take(key) is None
        clock[0] += 61
    assert journal.take(key, force=True) is None and journal.due() == []
    # 待结算结果超过输出保留期后仍需保留。
    clock[0] += settings.MODEL_RESULT_RETENTION_DAYS * 86400 + 1
    journal.prune()
    assert journal.read(key) == payload
    journal.finish(key, 3)
    clock[0] += settings.MODEL_RESULT_RETENTION_DAYS * 86400 + 1
    journal.prune()
    with pytest.raises(CustomException):
        journal.claim(key, "hash")


def test_crashed_worker_lease_expires_and_saved_result_is_immutable(monkeypatch):
    from app.api.v1.module_model_gateway import result_journal

    clock = [time.time()]
    monkeypatch.setattr(result_journal, "time", SimpleNamespace(time=lambda: clock[0]))
    journal = ResultJournal()
    key = (1, 2, "lease-recovery")
    payload = {"result": {"content": "first"}}
    journal.claim(key, "hash")
    journal.save(key, "hash", payload)
    assert journal.take(key) == payload
    journal.save(key, "hash", {"result": {"content": "incorrect-second"}})
    assert ResultJournal().read(key) == payload
    assert ResultJournal().take(key) is None
    clock[0] += 301
    assert ResultJournal().take(key) == payload
