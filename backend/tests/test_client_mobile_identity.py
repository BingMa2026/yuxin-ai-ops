from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.v1.module_client.app.model import ClientAppModel
from app.api.v1.module_client.auth import sms_service, wechat_service
from app.api.v1.module_client.user.model import ClientUserModel
from app.config.setting import settings
from app.core.database import async_db_session
from app.utils.password_util import PwdUtil


def _sms(monkeypatch):
    sent: dict[tuple[str, str], str] = {}
    for name in ("SECRET_ID", "SECRET_KEY", "APP_ID", "SIGN_NAME", "TEMPLATE_LOGIN", "TEMPLATE_REGISTER", "TEMPLATE_BIND"):
        monkeypatch.setattr(settings, f"TENCENT_SMS_{name}", f"test-{name}")

    async def capture(mobile: str, code: str, purpose: str) -> None:
        sent[(mobile, purpose)] = code

    monkeypatch.setattr(sms_service, "_send_tencent", capture)
    return sent


def _send(client: TestClient, sent: dict, mobile: str, purpose: str, flow_id: str | None = None) -> str:
    payload = {"app_code": "bid_agent", "mobile": mobile, "purpose": purpose}
    if flow_id:
        payload["flow_id"] = flow_id
    response = client.post("/client/auth/sms/send", json=payload)
    assert response.status_code == 200, response.text
    return sent[(mobile, purpose)]


def _ready_flow(client: TestClient, monkeypatch, openid: str) -> str:
    monkeypatch.setattr(settings, "CLIENT_WECHAT_LOGIN_APP_ID", "wx-test-site")
    monkeypatch.setattr(settings, "CLIENT_WECHAT_LOGIN_APP_SECRET", "test-secret")
    monkeypatch.setattr(settings, "CLIENT_WECHAT_LOGIN_CALLBACK_URL", "https://example.com/api/v1/client/auth/wechat/callback")

    async def exchange(_app_id: str, _secret: str, _code: str) -> str:
        return openid

    monkeypatch.setattr(wechat_service, "exchange_openid", exchange)
    flow = client.post("/client/auth/wechat/start", json={"app_code": "bid_agent"}).json()["data"]
    state = parse_qs(urlsplit(flow["authorize_url"]).query)["state"][0]
    assert client.get("/client/auth/wechat/callback", params={"state": state, "code": "test"}).status_code == 200
    assert client.post("/client/auth/wechat/poll", json={"flow_id": flow["flow_id"]}).json()["data"]["status"] == "bind_required"
    return flow["flow_id"]


def test_verified_mobile_registration_and_login(test_client: TestClient, monkeypatch) -> None:
    sent = _sms(monkeypatch)
    unique = uuid4().hex[:8]
    mobile = "13" + str(int(unique, 16)).zfill(9)[-9:]
    username = f"phone_{unique}"
    base = {"app_code": "bid_agent", "username": username, "password": "Secret123!"}
    assert test_client.post("/client/auth/register", json=base).status_code == 422
    code = _send(test_client, sent, mobile, "register")
    registered = test_client.post("/client/auth/register", json={**base, "mobile": mobile, "sms_code": code})
    assert registered.status_code == 200, registered.text
    assert test_client.post("/client/auth/login", json={"app_code": "bid_agent", "username": mobile, "password": base["password"]}).status_code == 200
    login_code = _send(test_client, sent, mobile, "login")
    login = test_client.post("/client/auth/sms/login", json={"app_code": "bid_agent", "mobile": mobile, "sms_code": login_code})
    assert login.status_code == 200, login.text
    assert login.json()["data"]["user"]["username"] == username
    assert test_client.post("/client/auth/sms/login", json={"app_code": "bid_agent", "mobile": mobile, "sms_code": login_code}).status_code == 400
    headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}
    assert test_client.patch("/client/user/me", headers=headers, json={"mobile": "13900139000"}).status_code == 409


def test_sms_send_requires_provider_configuration(test_client: TestClient, monkeypatch) -> None:
    for name in ("SECRET_ID", "SECRET_KEY", "APP_ID", "SIGN_NAME", "TEMPLATE_REGISTER"):
        monkeypatch.setattr(settings, f"TENCENT_SMS_{name}", "")
    response = test_client.post(
        "/client/auth/sms/send",
        json={
            "app_code": "bid_agent",
            "mobile": "13800138000",
            "purpose": "register",
        },
    )
    assert response.status_code == 503
    assert "短信服务尚未开通" in response.text


async def test_auth_capabilities_are_scoped_to_client_app(test_client: TestClient, monkeypatch) -> None:
    _sms(monkeypatch)
    monkeypatch.setattr(settings, "CLIENT_WECHAT_LOGIN_APP_ID", "wx-test-site")
    monkeypatch.setattr(settings, "CLIENT_WECHAT_LOGIN_APP_SECRET", "test-secret")
    monkeypatch.setattr(settings, "CLIENT_WECHAT_LOGIN_CALLBACK_URL", "https://example.com/api/v1/client/auth/wechat/callback")
    code = "sms_" + uuid4().hex[:8]
    async with async_db_session() as db:
        db.add(ClientAppModel(code=code, name="Second client", status="active", registration_enabled=False))
        await db.commit()

    response = test_client.get(f"/client/auth/capabilities/{code}")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["app_code"] == code
    assert data["registration_enabled"] is False
    assert data["sms_registration_configured"] is False
    assert data["sms_login_configured"] is True
    assert data["sms_bind_configured"] is True
    assert data["wechat_login_configured"] is True
    assert data["sms_code_length"] == 6
    assert data["sms_expires_in"] == 300
    assert data["sms_retry_after"] == 60
    assert response.headers["cache-control"] == "no-store"
    assert test_client.get("/client/auth/capabilities/not_found_app").status_code == 404


async def test_legacy_unverified_profile_mobile_can_verify_after_password_login(test_client: TestClient, monkeypatch) -> None:
    username = "legacy_" + uuid4().hex[:8]
    mobile = "17" + str(int(uuid4().hex[:8], 16)).zfill(9)[-9:]
    async with async_db_session() as db:
        app = await db.scalar(select(ClientAppModel).where(ClientAppModel.code == "bid_agent"))
        db.add(ClientUserModel(app_id=app.id, username=username, password_hash=PwdUtil.hash_password("Secret123!"), mobile=mobile, status="active", registration_source="self", tags=[]))
        await db.commit()
    assert test_client.post("/client/auth/login", json={"app_code": "bid_agent", "username": mobile, "password": "Secret123!"}).status_code == 401
    login = test_client.post("/client/auth/login", json={"app_code": "bid_agent", "username": username, "password": "Secret123!"})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}
    sent = _sms(monkeypatch)
    response = test_client.post("/client/user/me/mobile/send", headers=headers, json={"mobile": mobile})
    assert response.status_code == 200, response.text
    verified = test_client.post(
        "/client/user/me/mobile/verify",
        headers=headers,
        json={
            "mobile": mobile,
            "sms_code": sent[(mobile, "verify_mobile")],
        },
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["data"]["mobile_verified_at"]
    assert test_client.post("/client/auth/login", json={"app_code": "bid_agent", "username": mobile, "password": "Secret123!"}).status_code == 200


def test_wechat_can_register_with_mobile_or_bind_verified_phone(test_client: TestClient, monkeypatch) -> None:
    sent = _sms(monkeypatch)
    unique = uuid4().hex[:8]
    mobile = "15" + str(int(unique, 16)).zfill(9)[-9:]
    username = f"wechat_{unique}"
    flow_id = _ready_flow(test_client, monkeypatch, "wx-" + unique)
    code = _send(test_client, sent, mobile, "wechat_register", flow_id)
    created = test_client.post(
        "/client/auth/wechat/register",
        json={
            "flow_id": flow_id,
            "app_code": "bid_agent",
            "username": username,
            "password": "Secret123!",
            "mobile": mobile,
            "sms_code": code,
        },
    )
    assert created.status_code == 200, created.text
    assert created.json()["data"]["user"]["username"] == username
    assert test_client.post("/client/auth/wechat/poll", json={"flow_id": flow_id}).status_code == 404

    second = test_client.post("/client/auth/wechat/start", json={"app_code": "bid_agent"}).json()["data"]
    state = parse_qs(urlsplit(second["authorize_url"]).query)["state"][0]
    test_client.get("/client/auth/wechat/callback", params={"state": state, "code": "test"})
    assert test_client.post("/client/auth/wechat/poll", json={"flow_id": second["flow_id"]}).json()["data"]["status"] == "complete"

    third_flow = _ready_flow(test_client, monkeypatch, "wx-another-" + unique)
    bind_code = _send(test_client, sent, mobile, "wechat_bind", third_flow)
    duplicate = test_client.post("/client/auth/wechat/bind", json={"flow_id": third_flow, "mobile": mobile, "sms_code": bind_code})
    assert duplicate.status_code == 409

    other_mobile = "16" + str(int(uuid4().hex[:8], 16)).zfill(9)[-9:]
    other_username = "bound_" + uuid4().hex[:8]
    register_code = _send(test_client, sent, other_mobile, "register")
    assert (
        test_client.post(
            "/client/auth/register",
            json={
                "app_code": "bid_agent",
                "username": other_username,
                "password": "Secret123!",
                "mobile": other_mobile,
                "sms_code": register_code,
            },
        ).status_code
        == 200
    )
    fourth_flow = _ready_flow(test_client, monkeypatch, "wx-bind-" + unique)
    phone_code = _send(test_client, sent, other_mobile, "wechat_bind", fourth_flow)
    bound = test_client.post("/client/auth/wechat/bind", json={"flow_id": fourth_flow, "mobile": other_mobile, "sms_code": phone_code})
    assert bound.status_code == 200, bound.text
    assert bound.json()["data"]["user"]["username"] == other_username
