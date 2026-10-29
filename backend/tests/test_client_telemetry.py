import uuid
from datetime import UTC, datetime

from auth_helpers import register_with_sms
from fastapi.testclient import TestClient


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_client_telemetry_is_idempotent_and_rejects_sensitive_fields(test_client: TestClient) -> None:
    staff = test_client.post(
        "/system/auth/login",
        data={"username": "admin", "password": "admin123"},
    ).json()["data"]
    info = test_client.get("/system/user/current/info", headers=_headers(staff["access_token"])).json()["data"]
    suffix = uuid.uuid4().hex[:8]
    username = f"telemetry_{suffix}"
    password = "Passw0rd!"
    registered = register_with_sms(
        test_client,
        {
            "app_code": info["current_app"]["code"],
            "username": username,
            "password": password,
        },
    )
    assert registered.status_code == 200, registered.text
    login = test_client.post(
        "/client/auth/login",
        json={
            "app_code": info["current_app"]["code"],
            "username": username,
            "password": password,
        },
    )
    assert login.status_code == 200, login.text
    headers = _headers(login.json()["data"]["access_token"])
    payload = {
        "events": [
            {
                "event_id": uuid.uuid4().hex,
                "event_type": "bid.project_created",
                "occurred_at": datetime.now(UTC).isoformat(),
                "source": "openworker",
                "project_ref": "project-test",
                "critical": True,
                "metadata": {"feature": "bid_project", "success": True},
            }
        ]
    }

    first = test_client.post("/client/telemetry/events:batch", headers=headers, json=payload)
    second = test_client.post("/client/telemetry/events:batch", headers=headers, json=payload)
    rejected = test_client.post(
        "/client/telemetry/events:batch",
        headers=headers,
        json={
            "events": [
                {
                    **payload["events"][0],
                    "event_id": uuid.uuid4().hex,
                    "metadata": {"prompt": "sensitive content"},
                }
            ]
        },
    )

    assert first.status_code == 200, first.text
    assert first.json()["data"] == {"accepted": 1, "duplicated": 0}
    assert second.status_code == 200, second.text
    assert second.json()["data"] == {"accepted": 0, "duplicated": 1}
    assert rejected.status_code == 422

    diagnostics = test_client.get(
        "/operations/telemetry/diagnostics",
        headers=_headers(staff["access_token"]),
    )
    assert diagnostics.status_code == 200, diagnostics.text
    diagnostic_data = diagnostics.json()["data"]
    assert diagnostic_data["total_events"] >= 1
    assert any(item["event_type"] == "bid.project_created" for item in diagnostic_data["event_types"])

    event = test_client.get(
        f"/operations/telemetry/events/{payload['events'][0]['event_id']}",
        headers=_headers(staff["access_token"]),
    )
    assert event.status_code == 200, event.text
    assert event.json()["data"]["user_id"] == login.json()["data"]["user"]["id"]
