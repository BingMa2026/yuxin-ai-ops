"""One-time client phone proof via Tencent Cloud SMS. Codes never leave the server."""

import hashlib
import hmac
import json
import secrets
import time
from datetime import UTC, datetime
from typing import Literal

import httpx
from redis.asyncio.client import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.module_client.auth.service import ClientAuthService
from app.api.v1.module_client.user.model import ClientUserModel
from app.config.setting import settings
from app.core.exceptions import CustomException
from app.core.logger import logger

SmsPurpose = Literal["register", "login", "wechat_register", "wechat_bind", "verify_mobile"]
CODE_TTL = 300


def _key(app_id: int, mobile: str, purpose: SmsPurpose) -> bytes:
    digest = hashlib.sha256(f"{app_id}:{mobile}:{purpose}".encode()).hexdigest()
    return f"client:sms:code:{digest}".encode()


def _digest(mobile: str, purpose: SmsPurpose, nonce: str, code: str) -> str:
    value = f"{mobile}:{purpose}:{nonce}:{code}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), value, hashlib.sha256).hexdigest()


def _template(purpose: SmsPurpose) -> str:
    return {
        "register": settings.TENCENT_SMS_TEMPLATE_REGISTER,
        "wechat_register": settings.TENCENT_SMS_TEMPLATE_REGISTER,
        "login": settings.TENCENT_SMS_TEMPLATE_LOGIN,
        "wechat_bind": settings.TENCENT_SMS_TEMPLATE_BIND,
        "verify_mobile": settings.TENCENT_SMS_TEMPLATE_BIND,
    }[purpose].strip()


def _sms_config(purpose: SmsPurpose) -> tuple[str, str, str, str, str]:
    values = (
        settings.TENCENT_SMS_SECRET_ID.strip(),
        settings.TENCENT_SMS_SECRET_KEY.strip(),
        settings.TENCENT_SMS_APP_ID.strip(),
        settings.TENCENT_SMS_SIGN_NAME.strip(),
        _template(purpose),
    )
    if not all(values):
        raise CustomException(msg="短信服务尚未开通", status_code=503)
    return values


def sms_configured(purpose: SmsPurpose) -> bool:
    try:
        _sms_config(purpose)
    except CustomException:
        return False
    return True


def _tc3_headers(secret_id: str, secret_key: str, payload: bytes, timestamp: int) -> dict[str, str]:
    host = "sms.tencentcloudapi.com"
    content_type = "application/json; charset=utf-8"
    day = datetime.fromtimestamp(timestamp, UTC).strftime("%Y-%m-%d")
    scope = f"{day}/sms/tc3_request"
    canonical = "\n".join(("POST", "/", "", f"content-type:{content_type}\nhost:{host}\n", "content-type;host", hashlib.sha256(payload).hexdigest()))
    string_to_sign = "\n".join(("TC3-HMAC-SHA256", str(timestamp), scope, hashlib.sha256(canonical.encode()).hexdigest()))
    secret_date = hmac.new(("TC3" + secret_key).encode(), day.encode(), hashlib.sha256).digest()
    secret_service = hmac.new(secret_date, b"sms", hashlib.sha256).digest()
    signing_key = hmac.new(secret_service, b"tc3_request", hashlib.sha256).digest()
    signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
    return {
        "Host": host,
        "Content-Type": content_type,
        "X-TC-Action": "SendSms",
        "X-TC-Version": "2021-01-11",
        "X-TC-Region": settings.TENCENT_SMS_REGION,
        "X-TC-Timestamp": str(timestamp),
        "Authorization": f"TC3-HMAC-SHA256 Credential={secret_id}/{scope}, SignedHeaders=content-type;host, Signature={signature}",
    }


async def _send_tencent(mobile: str, code: str, purpose: SmsPurpose) -> None:
    secret_id, secret_key, app_id, sign, template = _sms_config(purpose)
    payload = json.dumps(
        {
            "PhoneNumberSet": [f"+86{mobile}"],
            "SmsSdkAppId": app_id,
            "SignName": sign,
            "TemplateId": template,
            "TemplateParamSet": [code],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                "https://sms.tencentcloudapi.com/",
                content=payload,
                headers=_tc3_headers(secret_id, secret_key, payload, int(time.time())),
            )
        response.raise_for_status()
        result = response.json().get("Response", {})
        statuses = result.get("SendStatusSet") or []
        if result.get("Error") or len(statuses) != 1 or statuses[0].get("Code") != "Ok":
            provider_code = (result.get("Error") or (statuses[0] if statuses else {})).get("Code", "unknown")
            if isinstance(provider_code, str) and provider_code.replace(".", "").isalnum():
                logger.warning("客户端短信发送被服务商拒绝: code={}", provider_code)
            raise ValueError("SMS provider rejected request")
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        # Provider diagnostics may contain personal data. Never echo them to the client or logs.
        raise CustomException(msg="验证码发送失败，请稍后再试", status_code=502) from exc


class ClientSmsService:
    def __init__(self, db: AsyncSession, redis: Redis) -> None:
        self.db = db
        self.redis = redis
        self.auth = ClientAuthService(db, redis)

    async def send(self, app_code: str, mobile: str, purpose: SmsPurpose, request_ip: str, *, flow_id: str | None = None) -> dict:
        _sms_config(purpose)
        app = await self.auth._active_app(app_code, registration=purpose in {"register", "wechat_register"})
        if purpose.startswith("wechat_"):
            from .wechat_service import ClientWechatLoginService

            if not flow_id:
                raise CustomException(msg="请先完成微信扫码", status_code=409)
            flow = await ClientWechatLoginService(self.db, self.redis)._flow(flow_id)
            if flow["status"] != "ready" or flow["app_id"] != app.id:
                raise CustomException(msg="微信扫码流程已失效", status_code=409)
        await self.auth._rate_limit(scope="sms-ip", app_code=app_code, value=request_ip, limit=20, window=3600)
        await self.auth._rate_limit(scope="sms-mobile", app_code=app_code, value=mobile, limit=5, window=3600)
        if purpose in {"login", "wechat_bind"}:
            known = await self.db.scalar(
                select(ClientUserModel.id).where(
                    ClientUserModel.app_id == app.id,
                    ClientUserModel.mobile == mobile,
                    ClientUserModel.mobile_verified_at.is_not(None),
                    ClientUserModel.status == "active",
                    ClientUserModel.is_deleted == False,
                )
            )
            if not known:
                return {"expires_in": CODE_TTL, "retry_after": 60}
        key = _key(app.id, mobile, purpose)
        cooldown = key + b":cooldown"
        if not await self.redis.set(cooldown, b"1", ex=60, nx=True):
            raise CustomException(msg="请稍后再获取验证码", status_code=429)
        code = f"{secrets.randbelow(1_000_000):06d}"
        nonce = secrets.token_hex(16)
        try:
            await _send_tencent(mobile, code, purpose)
            await self.redis.set(key, json.dumps({"nonce": nonce, "digest": _digest(mobile, purpose, nonce, code)}), ex=CODE_TTL)
        except Exception:
            await self.redis.delete(cooldown)
            raise
        return {"expires_in": CODE_TTL, "retry_after": 60}

    async def verify(self, app_id: int, app_code: str, mobile: str, purpose: SmsPurpose, code: str, request_ip: str) -> None:
        await self.auth._rate_limit(scope="sms-check-ip", app_code=app_code, value=request_ip, limit=30, window=900)
        await self.auth._rate_limit(scope="sms-check-mobile", app_code=app_code, value=mobile, limit=10, window=900)
        key = _key(app_id, mobile, purpose)
        raw = await self.redis.get(key)
        if not raw:
            raise CustomException(msg="验证码错误或已过期", status_code=400)
        stored = json.loads(raw)
        if not hmac.compare_digest(stored["digest"], _digest(mobile, purpose, stored["nonce"], code)):
            raise CustomException(msg="验证码错误或已过期", status_code=400)
        if await self.redis.getdel(key) != raw:
            raise CustomException(msg="验证码已使用", status_code=409)
