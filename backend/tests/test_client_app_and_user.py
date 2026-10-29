import uuid

from auth_helpers import register_with_sms
from fastapi.testclient import TestClient


def _staff_login(client: TestClient) -> dict[str, str]:
    response = client.post("/system/auth/login", data={"username": "admin", "password": "admin123"})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def test_disabled_app_blocks_login_registration_session_and_refresh(test_client: TestClient) -> None:
    staff_headers = _headers(_staff_login(test_client)["access_token"])
    code = f"disabled_{uuid.uuid4().hex[:8]}"
    created = test_client.post(
        "/operations/client-apps",
        headers=staff_headers,
        json={"name": "停用验证客户端", "code": code, "status": "active", "registration_enabled": True},
    )
    assert created.status_code == 201, created.text
    app_id = created.json()["data"]["id"]
    credentials = {"app_code": code, "username": "disable_member", "password": "Passw0rd!"}
    assert register_with_sms(test_client, credentials).status_code == 200
    login = test_client.post("/client/auth/login", json=credentials)
    assert login.status_code == 200, login.text
    tokens = login.json()["data"]
    headers = _headers(tokens["access_token"])
    assert test_client.get("/client/user/me", headers=headers).status_code == 200

    disabled = test_client.put(f"/operations/client-apps/{app_id}", headers=staff_headers, json={"status": "inactive"})
    assert disabled.status_code == 200, disabled.text
    assert test_client.get(f"/operations/client-apps/{app_id}", headers=staff_headers).json()["data"]["status"] == "inactive"
    assert test_client.post("/client/auth/login", json=credentials).status_code == 403
    assert test_client.post("/client/auth/register", json={**credentials, "username": "new_member", "mobile": "13800138000", "sms_code": "123456"}).status_code == 403
    assert test_client.get("/client/user/me", headers=headers).status_code == 401
    refreshed = test_client.post("/client/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 401, refreshed.text

    enabled = test_client.put(f"/operations/client-apps/{app_id}", headers=staff_headers, json={"status": "active"})
    assert enabled.status_code == 200, enabled.text
    assert test_client.post("/client/auth/login", json=credentials).status_code == 200


def test_app_switch_rotates_token_and_client_users_are_isolated(test_client: TestClient) -> None:
    staff_tokens = _staff_login(test_client)
    staff_headers = _headers(staff_tokens["access_token"])

    info = test_client.get("/system/user/current/info", headers=staff_headers)
    assert info.status_code == 200, info.text
    current_app = info.json()["data"]["current_app"]
    assert current_app["code"] == "bid_agent"

    suffix = uuid.uuid4().hex[:8]
    second_code = f"test_app_{suffix}"
    created = test_client.post(
        "/operations/client-apps",
        headers=staff_headers,
        json={
            "name": f"隔离测试客户端{suffix}",
            "code": second_code,
            "status": "active",
            "registration_enabled": True,
        },
    )
    assert created.status_code == 201, created.text
    second_app_id = created.json()["data"]["id"]

    staff_options = test_client.get(
        f"/operations/client-apps/{second_app_id}/staff",
        headers=staff_headers,
    )
    assert staff_options.status_code == 200, staff_options.text
    admin_option = next(item for item in staff_options.json()["data"] if item["username"] == "admin")
    assert admin_option["selected"] is True
    updated_staff = test_client.put(
        f"/operations/client-apps/{second_app_id}/staff",
        headers=staff_headers,
        json={"staff_ids": [admin_option["id"]]},
    )
    assert updated_staff.status_code == 200, updated_staff.text

    switched = test_client.post(
        "/system/auth/select-app",
        headers=staff_headers,
        json={"app_id": second_app_id},
    )
    assert switched.status_code == 200, switched.text
    second_staff_tokens = switched.json()["data"]

    old_token_response = test_client.get("/operations/client-users/list", headers=staff_headers)
    assert old_token_response.status_code == 401

    username = f"member_{suffix}"
    password = "Passw0rd!"
    for app_code in ("bid_agent", second_code):
        registered = register_with_sms(test_client, {"app_code": app_code, "username": username, "password": password, "display_name": "同名测试用户"})
        assert registered.status_code == 200, registered.text

    second_login = test_client.post(
        "/client/auth/login",
        json={"app_code": second_code, "username": username, "password": password},
    )
    assert second_login.status_code == 200, second_login.text
    second_client_token = second_login.json()["data"]["access_token"]
    second_me = test_client.get("/client/user/me", headers=_headers(second_client_token))
    assert second_me.status_code == 200, second_me.text
    assert second_me.json()["data"]["app_id"] == second_app_id

    second_staff_headers = _headers(second_staff_tokens["access_token"])
    second_users = test_client.get(
        "/operations/client-users/list",
        headers=second_staff_headers,
        params={"keyword": username},
    )
    assert second_users.status_code == 200, second_users.text
    assert second_users.json()["data"]["total"] == 1
    second_user_id = second_users.json()["data"]["items"][0]["id"]

    back_to_first = test_client.post(
        "/system/auth/select-app",
        headers=second_staff_headers,
        json={"app_id": current_app["id"]},
    )
    assert back_to_first.status_code == 200, back_to_first.text
    first_staff_headers = _headers(back_to_first.json()["data"]["access_token"])
    first_users = test_client.get(
        "/operations/client-users/list",
        headers=first_staff_headers,
        params={"keyword": username},
    )
    assert first_users.status_code == 200, first_users.text
    assert first_users.json()["data"]["total"] == 1
    assert first_users.json()["data"]["items"][0]["app_id"] == current_app["id"]

    back_to_second = test_client.post(
        "/system/auth/select-app",
        headers=first_staff_headers,
        json={"app_id": second_app_id},
    )
    second_staff_headers = _headers(back_to_second.json()["data"]["access_token"])
    disabled = test_client.patch(
        f"/operations/client-users/{second_user_id}/status",
        headers=second_staff_headers,
        json={"status": "disabled", "reason": "自动化隔离测试"},
    )
    assert disabled.status_code == 200, disabled.text
    assert test_client.get("/client/user/me", headers=_headers(second_client_token)).status_code == 401


def test_temporary_password_requires_change(test_client: TestClient) -> None:
    staff_tokens = _staff_login(test_client)
    staff_headers = _headers(staff_tokens["access_token"])
    info = test_client.get("/system/user/current/info", headers=staff_headers).json()["data"]
    app = info["current_app"]
    suffix = uuid.uuid4().hex[:8]
    username = f"reset_{suffix}"
    registered = register_with_sms(test_client, {"app_code": app["code"], "username": username, "password": "Passw0rd!"})
    assert registered.status_code == 200, registered.text
    user_id = registered.json()["data"]["id"]

    reset = test_client.post(f"/operations/client-users/{user_id}/temporary-password", headers=staff_headers)
    assert reset.status_code == 200, reset.text
    temporary_password = reset.json()["data"]["temporary_password"]

    login = test_client.post(
        "/client/auth/login",
        json={"app_code": app["code"], "username": username, "password": temporary_password},
    )
    assert login.status_code == 200, login.text
    assert login.json()["data"]["must_change_password"] is True


def test_client_apps_are_sorted_and_login_selects_the_first_one(test_client: TestClient) -> None:
    staff_tokens = _staff_login(test_client)
    staff_headers = _headers(staff_tokens["access_token"])
    current_info = test_client.get("/system/user/current/info", headers=staff_headers)
    assert current_info.status_code == 200, current_info.text
    current_app_id = current_info.json()["data"]["current_app"]["id"]
    suffix = uuid.uuid4().hex[:8]

    created = test_client.post(
        "/operations/client-apps",
        headers=staff_headers,
        json={
            "name": f"首选客户端{suffix}",
            "code": f"first_app_{suffix}",
            "status": "active",
            "registration_enabled": True,
            "order": 1,
        },
    )
    assert created.status_code == 201, created.text
    first_app = created.json()["data"]

    moved_current = test_client.put(
        f"/operations/client-apps/{current_app_id}",
        headers=staff_headers,
        json={"order": 10},
    )
    assert moved_current.status_code == 200, moved_current.text

    listing = test_client.get("/operations/client-apps/list", headers=staff_headers)
    assert listing.status_code == 200, listing.text
    assert listing.json()["data"]["items"][0]["id"] == first_app["id"]

    new_login = _staff_login(test_client)
    info = test_client.get(
        "/system/user/current/info",
        headers=_headers(new_login["access_token"]),
    )
    assert info.status_code == 200, info.text
    assert info.json()["data"]["current_app"]["id"] == first_app["id"]
