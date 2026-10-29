import uuid

from auth_helpers import register_with_sms
from fastapi.testclient import TestClient


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_feedback_reply_and_operations_message_delivery_loop(test_client: TestClient) -> None:
    staff_login = test_client.post("/system/auth/login", data={"username": "admin", "password": "admin123"})
    assert staff_login.status_code == 200, staff_login.text
    staff_headers = _headers(staff_login.json()["data"]["access_token"])
    app = test_client.get("/system/user/current/info", headers=staff_headers).json()["data"]["current_app"]

    suffix = uuid.uuid4().hex[:8]
    username = f"feedback_{suffix}"
    password = "Passw0rd!"
    registered = register_with_sms(test_client, {"app_code": app["code"], "username": username, "password": password})
    assert registered.status_code == 200, registered.text
    user_id = registered.json()["data"]["id"]
    client_login = test_client.post(
        "/client/auth/login",
        json={"app_code": app["code"], "username": username, "password": password},
    )
    assert client_login.status_code == 200, client_login.text
    client_headers = _headers(client_login.json()["data"]["access_token"])

    created = test_client.post(
        "/client/user-operations/tickets",
        headers=client_headers,
        json={
            "kind": "feedback",
            "category": "ai_quality",
            "subject": "生成结果需要改进",
            "content": "希望保留更多原文依据。",
            "priority": "normal",
            "attachments": [],
        },
    )
    assert created.status_code == 201, created.text
    ticket = created.json()["data"]

    internal = test_client.post(
        f"/operations/user-operations/tickets/{ticket['id']}/messages",
        headers=staff_headers,
        json={"content": "内部排查记录", "attachments": [], "internal": True},
    )
    assert internal.status_code == 200, internal.text
    public_reply = test_client.post(
        f"/operations/user-operations/tickets/{ticket['id']}/messages",
        headers=staff_headers,
        json={"content": "已经收到，我们正在处理。", "attachments": [], "internal": False},
    )
    assert public_reply.status_code == 200, public_reply.text

    client_detail = test_client.get(f"/client/user-operations/tickets/{ticket['id']}", headers=client_headers)
    assert client_detail.status_code == 200, client_detail.text
    messages = client_detail.json()["data"]["messages"]
    assert [item["content"] for item in messages] == ["已经收到，我们正在处理。"]

    campaign = test_client.post(
        "/operations/user-operations/campaigns",
        headers=staff_headers,
        json={
            "name": f"指定用户触达{suffix}",
            "title": "权益使用提醒",
            "content": "您的积分权益可以继续使用。",
            "audience_type": "users",
            "audience_value": {"user_ids": [user_id]},
            "send_now": True,
        },
    )
    assert campaign.status_code == 201, campaign.text
    assert campaign.json()["data"]["target_count"] == 1

    inbox = test_client.get("/client/user-operations/messages", headers=client_headers)
    assert inbox.status_code == 200, inbox.text
    delivered = inbox.json()["data"]
    assert {item["message_type"] for item in delivered} >= {"ticket_reply", "campaign"}
    ticket_message = next(item for item in delivered if item["message_type"] == "ticket_reply")
    marked = test_client.patch(f"/client/user-operations/messages/{ticket_message['id']}/read", headers=client_headers)
    assert marked.status_code == 200, marked.text
    assert marked.json()["data"]["read_at"] is not None

    supplemented = test_client.post(
        f"/client/user-operations/tickets/{ticket['id']}/messages",
        headers=client_headers,
        json={"content": "补充：问题在长文档中出现。", "attachments": []},
    )
    assert supplemented.status_code == 200, supplemented.text
    updated = test_client.get(f"/client/user-operations/tickets/{ticket['id']}", headers=client_headers)
    assert updated.json()["data"]["status"] == "processing"
