"""Opt-in real PostgreSQL regression; only a disposable auth_lock_regression DB.

AUTH_LOCK_TEST_DSN must point to an isolated database, never dev/prod.
The ordinary suite skips this test when no dedicated PostgreSQL is provided.
"""

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from app.api.v1.module_client.app.model import ClientAppModel
from app.api.v1.module_client.auth.service import ClientAuthService
from app.api.v1.module_client.user.model import ClientAuthEventModel, ClientUserModel
from app.config.setting import settings
from app.core.base_model import MappedBase
from app.core.database import create_async_engine_and_session
from app.core.exceptions import CustomException


async def test_postgres_registration_failure_releases_agreement_lock(monkeypatch):
    dsn = os.getenv("AUTH_LOCK_TEST_DSN")
    if not dsn:
        pytest.skip("requires disposable PostgreSQL auth_lock_regression database")
    assert make_url(dsn).database == "auth_lock_regression", "Refuse to run against a business database"
    monkeypatch.setattr(settings, "DATABASE_TYPE", "postgres")
    engine, sessions = create_async_engine_and_session(dsn)
    monkeypatch.setattr("app.api.v1.module_client.auth.service.async_db_session", sessions)
    # All tables are created only in the explicitly named disposable test database.
    async with engine.begin() as connection:
        await connection.run_sync(MappedBase.metadata.create_all)
    code = f"lock_{uuid4().hex[:8]}"
    async with sessions() as db, db.begin():
        app = ClientAppModel(code=code, name="Lock regression", status="active", registration_enabled=True)
        db.add(app)
        await db.flush()
        app_id = app.id
        db.add(ClientUserModel(app_id=app_id, username="existing", password_hash="unused", status="active"))

    async with sessions() as db:
        assert await db.scalar(text("SHOW lock_timeout")) == "5s"
        assert await db.scalar(text("SHOW statement_timeout")) == "1min"
        assert await db.scalar(text("SHOW idle_in_transaction_session_timeout")) == "2min"

    from app.api.v1.module_client.user.schema import ClientUserRegisterSchema

    async def no_rate_limit(**kwargs):
        pass

    async with sessions() as db, db.begin():
        service = ClientAuthService(db, None)
        monkeypatch.setattr(service, "_rate_limit", no_rate_limit)
        # validate(auth) locks client_app before duplicate-account rejection.
        # Without rollback, the audit FK waits for that exact transaction.
        with pytest.raises(CustomException, match="该账号已注册"):
            async with asyncio.timeout(3):
                await service.register(ClientUserRegisterSchema(app_code=code, username="existing", password="Passw0rd!"))

    async with sessions() as db, db.begin():
        event = await db.scalar(select(ClientAuthEventModel).where(ClientAuthEventModel.app_id == app_id))
        assert event is not None and event.success is False and event.failure_reason == "该账号已注册"
        # A following request must acquire the same lock promptly.
        async with asyncio.timeout(1):
            assert await db.scalar(select(ClientAppModel.id).where(ClientAppModel.id == app_id).with_for_update()) == app_id
    await engine.dispose()
