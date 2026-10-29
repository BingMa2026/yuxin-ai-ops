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
from app.api.v1.module_model_gateway.schema import RuntimeCompletionRequest


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("finish_reason", ["length", "stop", "content_filter", None])
async def test_gateway_returns_observed_finish_and_actual_reserved_output_budget(monkeypatch, stream, finish_reason):
    def upstream(request):
        payload = json.loads(request.content)
        assert payload["max_tokens"] == 300
        choice = {"finish_reason": finish_reason}
        if not stream:
            return httpx.Response(200, json={"choices": [{**choice, "message": {"content": "{}"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 12}})
        chunks = [{"choices": [{"delta": {"content": "{}"}}]}, {"choices": [{**choice, "delta": {}}]}, {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 12}}]
        body = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        monkeypatch.setattr(gateway_module, "get_provider_http_client", lambda: client)
        service = ModelGatewayService(SimpleNamespace(actor_type="runtime", app_id=1, user=SimpleNamespace(id=2)))
        service._resolve = AsyncMock(return_value=PreparedRequest([_binding()], 10, 300, 7, Decimal("1"), False, time.perf_counter()))
        service._finalize = AsyncMock(return_value=7)
        request = RuntimeCompletionRequest(request_id="completion-contract-test", max_output_tokens=8192, messages=[{"role": "user", "content": "test"}])
        if stream:
            events = [part.decode() async for part in service.stream(request)]
            response = json.loads(next(event.split("data: ", 1)[1] for event in events if event.startswith("event: done")))
        else:
            response = (await service.complete(request)).model_dump()
        assert response.get("finish_reason") == finish_reason
        assert response.get("effective_max_output_tokens") == 300
        assert service._finalize.await_count == 1
        assert service._finalize.call_args.kwargs["status"] == "succeeded"


async def test_upstream_eof_without_terminal_evidence_is_not_a_done_response(monkeypatch):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text='data: {"choices":[{"delta":{"content":"{\\"conclusion\\":\\"PASS\\"}"}}]}\n\n',
                headers={"content-type": "text/event-stream"},
            )
        )
    ) as client:
        monkeypatch.setattr(gateway_module, "get_provider_http_client", lambda: client)
        service = ModelGatewayService(SimpleNamespace(actor_type="runtime", app_id=1, user=SimpleNamespace(id=2)))
        service._resolve = AsyncMock(return_value=PreparedRequest([_binding()], 10, 300, 7, Decimal("1"), False, time.perf_counter()))
        service._finalize = AsyncMock(return_value=7)
        request = RuntimeCompletionRequest(request_id="interrupted-contract-test", messages=[{"role": "user", "content": "test"}])
        events = [part.decode() async for part in service.stream(request)]
        assert any(event.startswith("event: error") for event in events)
        assert not any(event.startswith("event: done") for event in events)
        assert service._finalize.await_count == 1
        assert service._finalize.call_args.kwargs["status"] == "failed"
