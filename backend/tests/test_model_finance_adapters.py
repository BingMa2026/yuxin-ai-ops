from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.api.v1.module_model_gateway import finance_service
from app.api.v1.module_model_gateway.finance_service import (
    AlibabaFinanceAdapter,
    AnthropicFinanceAdapter,
    DeepSeekFinanceAdapter,
    OpenAIFinanceAdapter,
)
from app.api.v1.module_model_gateway.model import (
    ModelCatalogModel,
    ModelProviderBalanceSnapshotModel,
    ModelProviderBillItemModel,
    ModelProviderResourcePackageSnapshotModel,
    ModelUsageModel,
)
from app.api.v1.module_speech.model import SpeechUsageModel
from app.core.exceptions import CustomException


class _Response:
    def __init__(self, body: dict) -> None:
        self.body = body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.body


class _Client:
    def __init__(self, responses: dict[str, dict]) -> None:
        self.responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    async def get(self, url: str, **_kwargs) -> _Response:
        return _Response(self.responses[url])


@pytest.mark.asyncio
async def test_deepseek_balance_uses_configured_exchange_rate(monkeypatch) -> None:
    body = {
        "is_available": True,
        "balance_infos": [{"currency": "USD", "total_balance": "2.5", "topped_up_balance": "2", "granted_balance": ".5"}],
    }
    monkeypatch.setattr(
        finance_service.httpx,
        "AsyncClient",
        lambda **_kwargs: _Client({"https://api.deepseek.com/user/balance": body}),
    )
    rows = await DeepSeekFinanceAdapter({"api_key": "secret", "exchange_rate_to_cny": "7.2"}).fetch_balance()
    assert rows[0]["amount_yuan"] == Decimal("18.00")
    assert rows[0]["raw_summary"] == {"is_available": True}


@pytest.mark.asyncio
async def test_openai_cost_report_is_normalized_to_cny(monkeypatch) -> None:
    start = datetime(2026, 9, 1, tzinfo=UTC)
    end = datetime(2026, 9, 2, tzinfo=UTC)
    body = {
        "data": [
            {
                "start_time": int(start.timestamp()),
                "end_time": int(end.timestamp()),
                "results": [
                    {
                        "amount": {"value": "1.25", "currency": "usd"},
                        "line_item": "Responses API",
                        "project_id": "project-1",
                    }
                ],
            }
        ],
        "next_page": None,
    }
    monkeypatch.setattr(
        finance_service.httpx,
        "AsyncClient",
        lambda **_kwargs: _Client({"https://api.openai.com/v1/organization/costs": body}),
    )
    rows = await OpenAIFinanceAdapter({"admin_key": "secret", "exchange_rate_to_cny": 7}).fetch_bills(start, end)
    assert rows[0]["amount_original"] == Decimal("1.25")
    assert rows[0]["amount_yuan"] == Decimal("8.75")
    assert rows[0]["source"] == "openai_costs_api"


@pytest.mark.asyncio
async def test_anthropic_cost_report_converts_minor_units(monkeypatch) -> None:
    start = datetime(2026, 9, 1, tzinfo=UTC)
    end = datetime(2026, 9, 2, tzinfo=UTC)
    body = {
        "data": [
            {
                "starting_at": "2026-09-01T00:00:00Z",
                "ending_at": "2026-09-02T00:00:00Z",
                "results": [{"amount": "250", "currency": "USD", "description": "tokens"}],
            }
        ]
    }
    monkeypatch.setattr(
        finance_service.httpx,
        "AsyncClient",
        lambda **_kwargs: _Client({"https://api.anthropic.com/v1/organizations/cost_report": body}),
    )
    rows = await AnthropicFinanceAdapter({"admin_key": "secret", "exchange_rate_to_cny": 7}).fetch_bills(start, end)
    assert rows[0]["amount_original"] == Decimal("2.5")
    assert rows[0]["amount_yuan"] == Decimal("17.5")


@pytest.mark.asyncio
async def test_alibaba_balance_is_account_wide(monkeypatch) -> None:
    adapter = AlibabaFinanceAdapter({"access_key_id": "id", "access_key_secret": "secret"})

    async def fake_rpc(_action: str, _extra=None) -> dict:
        return {"Code": "200", "Success": True, "Data": {"AvailableAmount": "88.50", "AvailableCashAmount": "80", "CreditAmount": "8.50", "Currency": "CNY"}}

    monkeypatch.setattr(adapter, "_rpc", fake_rpc)
    rows = await adapter.fetch_balance()
    assert rows[0]["amount_yuan"] == Decimal("88.50")
    assert rows[0]["raw_summary"]["account_scope"] == "aliyun_account"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,body,expected",
    [
        (400, {"Code": "AuthSiteFail", "Message": "auth site failed", "RequestId": "req-test"}, "AuthSiteFail"),
        (403, {"Code": "Forbidden", "Message": "denied"}, "Forbidden"),
        (200, {"Success": False, "Message": "failed"}, "failed"),
        (502, None, "HTTP 502"),
    ],
)
async def test_alibaba_errors_preserve_reason_without_signed_url(monkeypatch, status, body, expected) -> None:
    request = httpx.Request("GET", "https://business.aliyuncs.com/?AccessKeyId=test-id&Signature=test-signature")
    response = httpx.Response(status, json=body, request=request) if body is not None else httpx.Response(status, text="upstream unavailable", request=request)

    class Client(_Client):
        async def get(self, *_args, **_kwargs):
            return response

    monkeypatch.setattr(finance_service.httpx, "AsyncClient", lambda **_kwargs: Client({}))
    with pytest.raises(CustomException) as error:
        await AlibabaFinanceAdapter({"access_key_id": "test-id", "access_key_secret": "test-secret"}).fetch_balance()
    message = str(error.value)
    assert expected in message
    assert "Signature" not in message
    assert "test-id" not in message


@pytest.mark.asyncio
async def test_alibaba_missing_balance_is_not_reported_as_zero(monkeypatch) -> None:
    adapter = AlibabaFinanceAdapter({})

    async def fake_rpc(*_args):
        return {"Success": True, "Data": {}}

    monkeypatch.setattr(adapter, "_rpc", fake_rpc)
    with pytest.raises(CustomException, match="余额"):
        await adapter.fetch_balance()


@pytest.mark.asyncio
async def test_finance_summary_distinguishes_no_usage_from_zero_cost(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            for model in (ModelCatalogModel, SpeechUsageModel, ModelUsageModel, ModelProviderBalanceSnapshotModel, ModelProviderBillItemModel, ModelProviderResourcePackageSnapshotModel):
                await conn.run_sync(model.__table__.create)
        async with AsyncSession(engine) as db:
            service = finance_service.ModelFinanceService(None, db)
            monkeypatch.setattr(service, "profile", AsyncMock(return_value=None))
            now = datetime.now(UTC)
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            for request_id, provider, completed, deleted in (
                ("unattributed", None, month_start, False),
                ("other-provider", 2, month_start, False),
                ("previous-month", 1, month_start - timedelta(seconds=1), False),
                ("future", 1, now + timedelta(days=32), False),
                ("deleted", 1, month_start, True),
            ):
                db.add(
                    ModelUsageModel(
                        app_id=1, user_id=1, request_id=request_id, business_code="test", provider_account_id=provider, completed_at=completed, is_deleted=deleted, provider_cost_yuan=Decimal("99")
                    )
                )
            await db.flush()
            empty = await service.summary(1)
            assert empty.month_request_count == 0
            assert empty.request_cost_yuan == 0
            db.add(ModelUsageModel(app_id=1, user_id=1, request_id="zero-cost", business_code="test", provider_account_id=1, completed_at=month_start, provider_cost_yuan=0))
            await db.flush()
            free = await service.summary(1)
            assert free.month_request_count == 1
            assert free.request_cost_yuan == 0
            db.add(
                ModelUsageModel(
                    app_id=1, user_id=1, request_id="paid", business_code="test", provider_account_id=1, completed_at=month_start, provider_cost_yuan=Decimal("2.5"), reconciliation_status="reconciled"
                )
            )
            await db.flush()
            paid = await service.summary(1)
            assert paid.month_request_count == 2
            assert paid.request_cost_yuan == 2.5
            assert paid.reconciliation_coverage_rate == 100
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_alibaba_resource_package_snapshot(monkeypatch) -> None:
    adapter = AlibabaFinanceAdapter({"access_key_id": "id", "access_key_secret": "secret"})

    async def fake_rpc(_action: str, _extra=None) -> dict:
        return {
            "Data": {
                "TotalCount": 1,
                "Instances": {
                    "Instance": [
                        {
                            "InstanceId": "TOKEN-PACK-1",
                            "Remark": "千问 Token 资源包",
                            "PackageType": "dashscope_token",
                            "TotalAmount": "1000000",
                            "RemainingAmount": "420000",
                            "RemainingAmountUnit": "Token",
                            "Status": "Available",
                            "EffectiveTime": "2026-09-01T00:00:00Z",
                            "ExpiryTime": "2026-10-01T00:00:00Z",
                            "ApplicableProducts": {"Product": ["dashscope"]},
                        }
                    ]
                },
            }
        }

    monkeypatch.setattr(adapter, "_rpc", fake_rpc)
    rows = await adapter.fetch_resource_packages()
    assert rows[0]["remaining_amount"] == Decimal("420000")
    assert rows[0]["unit"] == "Token"
    assert rows[0]["expires_at"] == datetime(2026, 10, 1, tzinfo=UTC)
