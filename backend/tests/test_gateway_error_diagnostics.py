"""上游拒绝请求的离线回归测试，不连接真实供应商或数据库。"""

import gzip
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
from app.core.exceptions import CustomException


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize(
    "status,category,code",
    [
        (400, "upstream_request_rejected", 50201),
        (429, "upstream_rate_limited", 50302),
        (401, "upstream_auth_rejected", 50303),
        (503, "upstream_server_error", 50304),
    ],
)
async def test_legacy_errors_keep_category_without_resubmitting(monkeypatch, stream, compressed, status, category, code):
    from app.api.v1.module_model_gateway import upstream_diagnostics

    calls = []
    diagnostics = []
    monkeypatch.setattr(upstream_diagnostics.logger, "warning", lambda template, fields: diagnostics.append(fields))

    def upstream(req):
        calls.append(req)
        body = json.dumps({"error": {"code": "InvalidParameter", "message": "Invalid max_tokens: SECRET private document"}}).encode()
        headers = {"x-request-id": "supplier-request-1"}
        if compressed:
            body = gzip.compress(body)
            headers["content-encoding"] = "gzip"
        return httpx.Response(status, content=body, headers=headers)

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        monkeypatch.setattr(gateway_module, "get_provider_http_client", lambda: client)
        service = ModelGatewayService(SimpleNamespace(actor_type="runtime", app_id=1, user=SimpleNamespace(id=2)))
        service._resolve = AsyncMock(
            return_value=PreparedRequest(
                [_binding(), _binding()],
                100,
                200,
                20,
                Decimal("1"),
                True,
                time.perf_counter(),
            )
        )
        service._finalize = AsyncMock(return_value=0)
        data = RuntimeCompletionRequest(request_id="local-request-1", messages=[{"role": "user", "content": "private document"}])
        if stream:
            output = b"".join([part async for part in service.stream(data)]).decode()
            assert category.upper() in output
        else:
            with pytest.raises(CustomException) as caught:
                await service.complete(data)
            assert caught.value.code == code
            assert caught.value.data["upstream_diagnostic"]["fields"] == ["max_tokens"]
            assert "SECRET" not in json.dumps(caught.value.data)
            output = str(caught.value)
        assert "SECRET" not in output and "private document" not in output
        assert len(calls) == 1
        assert service._finalize.await_count == 1
        assert service._finalize.call_args.kwargs["error_category"] == category
        # 供应商通过 HTTP 拒绝请求时，没有可计费的生成用量。
        assert service._finalize.call_args.args[2] is None
        assert len(diagnostics) == 1
        assert '"upstream_status": ' + str(status) in diagnostics[0]
        assert "supplier-request-1" in diagnostics[0] and "local-request-1" in diagnostics[0]
        assert "SECRET" not in diagnostics[0] and "private document" not in diagnostics[0]


def test_diagnostic_retains_reason_and_correlation_without_supplier_echo():
    from app.api.v1.module_model_gateway.upstream_diagnostics import diagnostic_fields

    request = httpx.Request("POST", "https://secret.invalid/?api_key=SECRET")
    response = httpx.Response(
        400,
        request=request,
        headers={"x-request-id": "supplier-request-1"},
        json={
            "error": {"code": "InvalidParameter", "message": "Range of max_tokens should be [1, 8192]. private document SECRET", "param": "max_tokens"},
        },
    )
    fields = diagnostic_fields(httpx.HTTPStatusError("SECRET", request=request, response=response))
    assert fields["upstream_status"] == 400
    assert fields["upstream_request_id"] == "supplier-request-1"
    assert fields["error_code"] == "InvalidParameter"
    assert "max_tokens" in fields["fields"]
    assert fields["reason"] == "parameter_range"
    assert fields["limits"] == [1, 8192]
    assert "SECRET" not in str(fields) and "private document" not in str(fields)


@pytest.mark.parametrize("body", [[], "SECRET", {"error": "SECRET"}, {"error": {"code": "sk-secret-key", "message": "private document"}}])
def test_unrecognized_diagnostic_never_logs_arbitrary_body(body):
    from app.api.v1.module_model_gateway.upstream_diagnostics import diagnostic_fields

    request = httpx.Request("POST", "https://supplier.invalid")
    response = httpx.Response(400, request=request, json=body)
    fields = diagnostic_fields(httpx.HTTPStatusError("SECRET", request=request, response=response))
    assert fields["reason"] == "unclassified"
    assert "SECRET" not in str(fields) and "private document" not in str(fields) and "sk-secret" not in str(fields)


def test_supplier_arrearage_is_not_client_credit_shortage_or_request_configuration():
    from app.api.v1.module_model_gateway.generation_policy import error_details

    request = httpx.Request("POST", "https://supplier.invalid")
    response = httpx.Response(400, request=request, json={"error": {"code": "Arrearage", "message": "SECRET"}})
    category, message, status, code = error_details(httpx.HTTPStatusError("SECRET", request=request, response=response))
    assert (category, status, code) == ("upstream_billing_rejected", 503, 50305)
    assert "供应商" in message and "SECRET" not in message
