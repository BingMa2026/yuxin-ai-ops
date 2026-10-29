import uuid
from datetime import UTC, date, datetime

from auth_helpers import register_with_sms
from fastapi.testclient import TestClient

from app.api.v1.module_operations.service import resolve_overview_range


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_operations_overview_and_user_activity_use_persisted_events(test_client: TestClient) -> None:
    staff = test_client.post(
        "/system/auth/login",
        data={"username": "admin", "password": "admin123"},
    ).json()["data"]
    staff_headers = _headers(staff["access_token"])
    info = test_client.get("/system/user/current/info", headers=staff_headers)
    assert info.status_code == 200, info.text
    app_code = info.json()["data"]["current_app"]["code"]

    suffix = uuid.uuid4().hex[:8]
    username = f"overview_{suffix}"
    password = "Passw0rd!"
    registered = register_with_sms(
        test_client,
        {
            "app_code": app_code,
            "username": username,
            "password": password,
            "display_name": "经营总览测试用户",
        },
    )
    assert registered.status_code == 200, registered.text
    login = test_client.post(
        "/client/auth/login",
        json={"app_code": app_code, "username": username, "password": password},
    )
    assert login.status_code == 200, login.text
    client_headers = _headers(login.json()["data"]["access_token"])
    event_id = uuid.uuid4().hex
    telemetry = test_client.post(
        "/client/telemetry/events:batch",
        headers=client_headers,
        json={
            "events": [
                {
                    "event_id": event_id,
                    "event_type": "bid.project_created",
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "source": "openworker",
                    "project_ref": f"project-{suffix}",
                    "critical": True,
                    "metadata": {"feature": "bid_project", "success": True},
                }
            ]
        },
    )
    assert telemetry.status_code == 200, telemetry.text

    overview = test_client.get(
        "/operations/overview",
        headers=staff_headers,
        params={"period_days": 30},
    )
    assert overview.status_code == 200, overview.text
    data = overview.json()["data"]
    assert data["period_days"] == 30
    assert len(data["daily"]) == 30
    assert data["summary"]["total_users"] >= 1
    assert data["summary"]["active_users"] >= 1
    assert data["data_quality"]["telemetry_events"] >= 1
    assert "客户端运营事件" in data["data_quality"]["sources"]
    assert "target" not in data["summary"]

    users = test_client.get(
        "/operations/client-users/list",
        headers=staff_headers,
        params={"keyword": username},
    )
    assert users.status_code == 200, users.text
    user_id = users.json()["data"]["items"][0]["id"]
    activity = test_client.get(
        f"/operations/client-users/{user_id}/activity",
        headers=staff_headers,
    )
    assert activity.status_code == 200, activity.text
    trend = activity.json()["data"]["activity_trend"]
    assert len(trend) == 30
    assert sum(item["events"] for item in trend) >= 1
    assert sum(item["logins"] for item in trend) >= 1


def test_operations_overview_rejects_unsupported_period(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    response = test_client.get(
        "/operations/overview",
        headers=auth_headers,
        params={"period_days": 14},
    )
    assert response.status_code == 422


def test_overview_range_uses_business_presets_and_automatic_grain() -> None:
    now = datetime(2026, 9, 4, 8, 0, tzinfo=UTC)
    month = resolve_overview_range(preset="this_month", now=now)
    year = resolve_overview_range(preset="this_year", now=now)
    custom = resolve_overview_range(
        preset="custom",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 8, 31),
        now=now,
    )
    assert month.label == "本月"
    assert month.grain == "day"
    assert year.grain == "month"
    assert custom.days == 243
    assert custom.grain == "month"
    assert custom.previous_end == custom.start
