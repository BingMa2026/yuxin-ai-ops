from types import SimpleNamespace

import httpx
import pytest

from app.api.v1.module_model_gateway import service as service_module
from app.api.v1.module_model_gateway.service import ModelAdminService


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("protocol", "item", "expected_id", "expected_name"),
    [
        ("openai_compatible", {"id": "hy4-preview", "name": "Hy4 preview"}, "hy4-preview", "Hy4 preview"),
        ("anthropic", {"id": "claude-example", "name": "Friendly name", "display_name": "Claude Example"}, "claude-example", "Claude Example"),
        ("gemini", {"name": "models/gemini-example", "id": "different-id", "displayName": "Gemini Example"}, "gemini-example", "Gemini Example"),
        ("gemini", {"name": "models/gemini-example"}, "gemini-example", "gemini-example"),
        ("openai_compatible", {"id": "models/opaque-id", "name": "Display Name"}, "models/opaque-id", "Display Name"),
        ("openai_compatible", {"id": "id-only"}, "id-only", "id-only"),
        ("openai_compatible", {"name": "legacy-name-only"}, "legacy-name-only", "legacy-name-only"),
    ],
)
async def test_discovery_keeps_provider_ids_separate_from_display_names(
    monkeypatch: pytest.MonkeyPatch,
    protocol: str,
    item: dict,
    expected_id: str,
    expected_name: str,
) -> None:
    client_type = httpx.AsyncClient

    def respond(request: httpx.Request) -> httpx.Response:
        if protocol == "gemini":
            assert request.url.path == "/v1beta/models"
            assert request.url.params["key"] == "test-only"
        elif protocol == "anthropic":
            assert request.url.path == "/v1/models"
        else:
            assert request.url.path == "/models"
        return httpx.Response(200, json={"models" if protocol == "gemini" else "data": [item, {}]})

    monkeypatch.setattr(service_module.httpx, "AsyncClient", lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs))

    models = await ModelAdminService._discover(
        SimpleNamespace(endpoint="https://models.example.test", timeout_seconds=30),
        SimpleNamespace(protocol=protocol),
        {"api_key": "test-only"},
    )

    assert models == [{"id": expected_id, "name": expected_name, "owned_by": None}]
