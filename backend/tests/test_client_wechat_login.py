from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.v1.module_client.app.model import ClientAppModel
from app.api.v1.module_client.auth import wechat_service
from app.api.v1.module_client.user.model import ClientUserModel
from app.config.setting import settings
from app.core.database import async_db_session
from app.utils.password_util import PwdUtil


@pytest.mark.asyncio
async def test_client_wechat_scan_bind_and_single_use_login(test_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "CLIENT_WECHAT_LOGIN_APP_ID", "wx-test-site")
    monkeypatch.setattr(settings, "CLIENT_WECHAT_LOGIN_APP_SECRET", "test-secret")
    monkeypatch.setattr(settings, "CLIENT_WECHAT_LOGIN_CALLBACK_URL", "https://example.com/api/v1/client/auth/wechat/callback")

    async def fake_exchange(app_id: str, secret: str, code: str) -> str:
        assert (app_id, secret, code) == ("wx-test-site", "test-secret", "one-time-code")
        return "openid-test-" + username

    monkeypatch.setattr(wechat_service, "exchange_openid", fake_exchange)
    username = "wx" + uuid4().hex[:12]
    async with async_db_session() as db:
        app = await db.scalar(select(ClientAppModel).where(ClientAppModel.code == "bid_agent"))
        db.add(ClientUserModel(app_id=app.id, username=username, password_hash=PwdUtil.hash_password("Secret123!"), display_name=username, status="active", registration_source="self", tags=[]))
        await db.commit()

    start = test_client.post("/client/auth/wechat/start", json={"app_code": "bid_agent"})
    assert start.status_code == 200
    flow = start.json()["data"]
    url = urlsplit(flow["authorize_url"])
    assert url.hostname == "open.weixin.qq.com"
    assert parse_qs(url.query)["scope"] == ["snsapi_login"]
    state = parse_qs(url.query)["state"][0]
    assert test_client.post("/client/auth/wechat/poll", json={"flow_id": flow["flow_id"]}).json()["data"]["status"] == "pending"

    callback = test_client.get("/client/auth/wechat/callback", params={"state": state, "code": "one-time-code"})
    assert callback.status_code == 200
    assert "已确认" in callback.text
    assert test_client.get("/client/auth/wechat/callback", params={"state": state, "code": "one-time-code"}).text.find("已失效") >= 0
    assert test_client.post("/client/auth/wechat/poll", json={"flow_id": flow["flow_id"]}).json()["data"]["status"] == "bind_required"

    wrong = test_client.post("/client/auth/wechat/bind", json={"flow_id": flow["flow_id"], "username": username, "password": "Wrong123!"})
    assert wrong.status_code == 401
    bound = test_client.post("/client/auth/wechat/bind", json={"flow_id": flow["flow_id"], "username": username, "password": "Secret123!"})
    assert bound.status_code == 200
    assert bound.json()["data"]["user"]["username"] == username
    assert test_client.post("/client/auth/wechat/poll", json={"flow_id": flow["flow_id"]}).status_code == 404

    second = test_client.post("/client/auth/wechat/start", json={"app_code": "bid_agent"}).json()["data"]
    second_state = parse_qs(urlsplit(second["authorize_url"]).query)["state"][0]
    test_client.get("/client/auth/wechat/callback", params={"state": second_state, "code": "one-time-code"})
    completed = test_client.post("/client/auth/wechat/poll", json={"flow_id": second["flow_id"]})
    assert completed.status_code == 200
    assert completed.json()["data"]["status"] == "complete"
    assert completed.json()["data"]["login"]["user"]["username"] == username
    assert test_client.post("/client/auth/wechat/poll", json={"flow_id": second["flow_id"]}).status_code == 404
