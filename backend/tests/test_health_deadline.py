import asyncio
from unittest.mock import AsyncMock, MagicMock

from app.api.v1.module_common.health import controller


async def test_readiness_database_wait_is_bounded_and_session_closes(monkeypatch):
    async def blocked(*args):
        await asyncio.Event().wait()

    session = MagicMock()
    session.execute = blocked
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(controller, "async_db_session", lambda: session)
    timeout = asyncio.timeout
    monkeypatch.setattr(controller.asyncio, "timeout", lambda seconds: timeout(0.01))
    result = await controller._check_database()
    assert result.status == 0
    session.__aexit__.assert_awaited_once()
