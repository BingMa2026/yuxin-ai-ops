from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.v1.module_client.app.model import ClientAppModel
from app.api.v1.module_client.auth.service import ClientAuthService
from app.api.v1.module_client.user.model import ClientAuthEventModel
from app.core.database import async_db_session
from app.core.exceptions import CustomException


class _Pipeline:
    def __init__(self, redis, key: str | None = None) -> None:
        self.redis = redis
        self.key = key

    def incr(self, key: str):
        self.key = key
        return self

    def expire(self, _key: str, _window: int):
        return self

    async def execute(self):
        assert self.key is not None
        self.redis.values[self.key] = self.redis.values.get(self.key, 0) + 1
        return [self.redis.values[self.key], True]


class _Redis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}

    def pipeline(self, transaction: bool = True):
        assert transaction is True
        return _Pipeline(self)


async def test_client_auth_rate_limit_is_scoped_and_enforced() -> None:
    service = ClientAuthService(db=None, redis=_Redis())  # type: ignore[arg-type]
    for _ in range(2):
        await service._rate_limit(
            scope="login-account",
            app_code="bid_agent",
            value="member",
            limit=2,
            window=60,
        )
    with pytest.raises(CustomException, match="请求过于频繁"):
        await service._rate_limit(
            scope="login-account",
            app_code="bid_agent",
            value="member",
            limit=2,
            window=60,
        )

    # 同名账号在另一个客户端拥有独立计数器。
    await service._rate_limit(
        scope="login-account",
        app_code="another_app",
        value="member",
        limit=2,
        window=60,
    )


def test_client_auth_event_has_no_password_or_token_columns() -> None:
    columns = set(ClientAuthEventModel.__table__.columns.keys())
    assert not columns.intersection({"password", "password_hash", "access_token", "refresh_token"})


async def test_failed_auth_event_uses_independent_transaction(test_client: TestClient) -> None:
    del test_client
    service = ClientAuthService(db=None, redis=_Redis())  # type: ignore[arg-type]
    await service._record_event(
        action="login",
        app_code="missing_app",
        username="missing_user",
        request_ip="127.0.0.1",
        user_agent="pytest",
        success=False,
        failure_reason="账号或密码错误",
        independent=True,
    )
    async with async_db_session() as db:
        event = await db.scalar(
            select(ClientAuthEventModel).where(
                ClientAuthEventModel.app_code == "missing_app",
                ClientAuthEventModel.username == "missing_user",
            )
        )
        assert event is not None
        assert event.success is False
        assert event.failure_reason == "账号或密码错误"


async def test_login_failures_are_logged_and_then_rate_limited(test_client: TestClient) -> None:
    username = f"missing_{uuid4().hex[:8]}"
    payload = {"app_code": "bid_agent", "username": username, "password": "WrongPass1!"}
    for _ in range(10):
        response = test_client.post("/client/auth/login", json=payload)
        assert response.status_code == 401
        assert response.json()["msg"] == "账号或密码错误"
        assert response.json()["success"] is False
    limited = test_client.post("/client/auth/login", json=payload)
    assert limited.status_code == 429

    async with async_db_session() as db:
        events = list(
            (
                await db.scalars(
                    select(ClientAuthEventModel).where(
                        ClientAuthEventModel.app_code == "bid_agent",
                        ClientAuthEventModel.username == username,
                    )
                )
            ).all()
        )
        assert len(events) == 11
        assert events[-1].failure_reason == "请求过于频繁，请稍后再试"


async def test_failed_auth_rolls_back_business_writes_before_audit(test_client: TestClient) -> None:
    del test_client
    username = f"rollback_{uuid4().hex[:8]}"
    async with async_db_session() as db, db.begin():
        app = await db.scalar(select(ClientAppModel).where(ClientAppModel.code == "bid_agent"))
        app_id, original = app.id, app.description
        app.description = username
        await db.flush()
        await ClientAuthService(db, _Redis())._record_event(
            action="register",
            app_code="bid_agent",
            app_id=app_id,
            username=username,
            request_ip="",
            user_agent="pytest",
            success=False,
            failure_reason="该账号已注册",
            independent=True,
        )
    async with async_db_session() as db:
        app = await db.get(ClientAppModel, app_id)
        assert app.description == original
        event = await db.scalar(select(ClientAuthEventModel).where(ClientAuthEventModel.username == username))
        assert event is not None and event.success is False


def test_audit_outage_preserves_authentication_error(test_client: TestClient, monkeypatch) -> None:
    def unavailable():
        raise RuntimeError("audit connection unavailable")

    monkeypatch.setattr("app.api.v1.module_client.auth.service.async_db_session", unavailable)
    response = test_client.post("/client/auth/login", json={"app_code": "bid_agent", "username": f"absent_{uuid4().hex[:8]}", "password": "WrongPass1!"})
    assert response.status_code == 401
    assert response.json()["msg"] == "账号或密码错误"
