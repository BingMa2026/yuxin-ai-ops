from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.api.v1.module_growth import refund_gateway
from app.core.exceptions import CustomException


def test_oauth_query_credentials_are_not_written_to_logs():
    from app.core.logger import redact_query_credentials

    line = "GET https://api.weixin.qq.com/sns/oauth2/access_token?appid=public-app&secret=private-secret&code=private-code&grant_type=authorization_code"
    masked = redact_query_credentials(line)
    assert "private-secret" not in masked and "private-code" not in masked
    assert "appid=public-app" in masked and "grant_type=authorization_code" in masked


@pytest.mark.asyncio
async def test_asset_password_confirmation_throttle_fails_closed():
    from app.api.v1.module_growth.security import sensitive_rate_limit

    redis = MagicMock()
    pipeline = MagicMock()
    redis.pipeline.return_value.__aenter__ = AsyncMock(return_value=pipeline)
    redis.pipeline.return_value.__aexit__ = AsyncMock(return_value=False)
    pipeline.execute = AsyncMock(return_value=[10, True])
    await sensitive_rate_limit(redis, 1, 2)
    pipeline.execute.return_value = [11, True]
    with pytest.raises(CustomException) as limited:
        await sensitive_rate_limit(redis, 1, 2)
    assert limited.value.status_code == 429
    with pytest.raises(CustomException) as unavailable:
        await sensitive_rate_limit(None, 1, 2)
    assert unavailable.value.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", [None, "out_trade_no", "transaction_id", "out_refund_no", "status", "total", "currency"])
async def test_refund_query_requires_matching_signed_success(monkeypatch, mismatch):
    order = SimpleNamespace(provider="wechat", order_no="ORDER1", provider_trade_no="TX1", amount_fen=10000)
    payload = {
        "out_trade_no": "ORDER1",
        "transaction_id": "TX1",
        "out_refund_no": "REF1",
        "refund_id": "WXREF1",
        "status": "SUCCESS",
        "success_time": "2026-09-07T10:00:00+08:00",
        "amount": {"total": 10000, "refund": 5000, "currency": "CNY"},
    }
    if mismatch in {"total", "currency"}:
        payload["amount"][mismatch] = "mismatch"
    elif mismatch:
        payload[mismatch] = "mismatch"
    client = AsyncMock()
    client.get.return_value = httpx.Response(200, json=payload)
    client.__aenter__.return_value = client
    monkeypatch.setattr(refund_gateway.httpx, "AsyncClient", lambda **kwargs: client)
    monkeypatch.setattr(refund_gateway, "_wechat_request_headers", lambda *args: {"Authorization": "signed"})
    verifier = MagicMock()
    monkeypatch.setattr(refund_gateway, "_verify_wechat_signed_message", verifier)
    if mismatch:
        with pytest.raises(CustomException):
            await refund_gateway.query_refund(order, "REF1")
    else:
        assert (await refund_gateway.query_refund(order, "REF1"))["amount"] == 5000
    verifier.assert_called_once()
    client.post.assert_not_called()
    verifier.side_effect = CustomException(msg="invalid signature", status_code=403)
    with pytest.raises(CustomException):
        await refund_gateway.query_refund(order, "REF1")
