from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from auth_helpers import register_with_sms
from fastapi.testclient import TestClient

from app.api.v1.module_client.auth.service import ClientAuthService
from app.config.setting import settings
from app.core.security import decode_access_token


@pytest.mark.parametrize("refresh_seconds", [7 * 86400, 30 * 86400])
async def test_client_tokens_and_redis_session_have_separate_lifetimes(monkeypatch: pytest.MonkeyPatch, refresh_seconds: int) -> None:
    monkeypatch.setattr(settings, "ACCESS_TOKEN_EXPIRE_SECONDS", 3600)
    monkeypatch.setattr(settings, "REFRESH_TOKEN_EXPIRE_SECONDS", 3600)
    monkeypatch.setattr(settings, "CLIENT_REFRESH_TOKEN_EXPIRE_SECONDS", refresh_seconds)
    redis = AsyncMock()
    service = ClientAuthService(db=None, redis=redis)  # type: ignore[arg-type]
    session = {"session_id": "lifetime-test", "actor_type": "client", "app_id": 1, "user_id": 1, "auth_generation": 0}
    access, refresh = await service._write_tokens("lifetime-test", session)

    access_payload = decode_access_token(access)
    refresh_payload = decode_access_token(refresh)
    assert refresh_payload.exp - access_payload.exp == refresh_seconds - 3600
    assert access_payload.is_refresh is False
    assert refresh_payload.is_refresh is True
    expirations = {call.kwargs["name"]: call.kwargs["ex"] for call in redis.set.await_args_list}
    assert expirations == {
        "client:session:lifetime-test": refresh_seconds,
        "client:access:lifetime-test": 3600,
        "client:refresh:lifetime-test": refresh_seconds,
    }


def test_expired_access_can_refresh_after_idle_and_logout_revokes_session(test_client: TestClient) -> None:
    credentials = {"app_code": "bid_agent", "username": f"idle_{uuid4().hex[:8]}", "password": "TestPass9!"}
    assert register_with_sms(test_client, credentials).status_code == 200

    class PreviousDay(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(UTC) - timedelta(seconds=settings.ACCESS_TOKEN_EXPIRE_SECONDS + 60)

    with patch("app.api.v1.module_client.auth.service.datetime", PreviousDay):
        login = test_client.post("/client/auth/login", json=credentials)
    assert login.status_code == 200
    old_tokens = login.json()["data"]
    assert test_client.get("/client/user/me", headers={"Authorization": f"Bearer {old_tokens['access_token']}"}).status_code == 401

    refreshed = test_client.post("/client/auth/refresh", json={"refresh_token": old_tokens["refresh_token"]})
    assert refreshed.status_code == 200
    new_tokens = refreshed.json()["data"]
    headers = {"Authorization": f"Bearer {new_tokens['access_token']}"}
    assert test_client.get("/client/user/me", headers=headers).status_code == 200
    assert test_client.post("/client/auth/refresh", json={"refresh_token": old_tokens["refresh_token"]}).status_code == 401

    assert test_client.post("/client/auth/logout", headers=headers).status_code == 200
    assert test_client.post("/client/auth/refresh", json={"refresh_token": new_tokens["refresh_token"]}).status_code == 401


def test_refresh_after_client_session_window_requires_login(test_client: TestClient) -> None:
    credentials = {"app_code": "bid_agent", "username": f"expired_{uuid4().hex[:8]}", "password": "TestPass9!"}
    assert register_with_sms(test_client, credentials).status_code == 200

    class ExpiredSessionTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(UTC) - timedelta(seconds=settings.CLIENT_REFRESH_TOKEN_EXPIRE_SECONDS + 60)

    with patch("app.api.v1.module_client.auth.service.datetime", ExpiredSessionTime):
        login = test_client.post("/client/auth/login", json=credentials)
    assert login.status_code == 200
    refreshed = test_client.post("/client/auth/refresh", json={"refresh_token": login.json()["data"]["refresh_token"]})
    assert refreshed.status_code == 401
