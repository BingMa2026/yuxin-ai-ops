"""Register a test client through the public phone-proof contract."""

from unittest.mock import patch
from uuid import uuid4

from app.api.v1.module_client.auth import sms_service
from app.config.setting import settings


def register_with_sms(client, payload: dict, *, mobile: str | None = None):
    mobile = mobile or "18" + str(int(uuid4().hex[:8], 16)).zfill(9)[-9:]
    sent: list[str] = []

    async def capture(_mobile: str, code: str, _purpose: str) -> None:
        sent.append(code)

    fields = ("SECRET_ID", "SECRET_KEY", "APP_ID", "SIGN_NAME", "TEMPLATE_REGISTER")
    patches = [patch.object(settings, f"TENCENT_SMS_{field}", "test") for field in fields]
    for setting in patches:
        setting.start()
    try:
        with patch.object(sms_service, "_send_tencent", capture):
            response = client.post("/client/auth/sms/send", json={"app_code": payload["app_code"], "mobile": mobile, "purpose": "register"})
        assert response.status_code == 200, response.text
        return client.post("/client/auth/register", json={**payload, "mobile": mobile, "sms_code": sent[0]})
    finally:
        for setting in reversed(patches):
            setting.stop()
