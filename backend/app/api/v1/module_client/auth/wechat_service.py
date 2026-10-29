"""Website-application WeChat QR login for client users.

The desktop/browser keeps a short-lived random flow key. WeChat returns only to
the public server callback; access and refresh tokens never enter that callback.
"""

import json
import secrets
from datetime import UTC, datetime
from urllib.parse import urlencode, urlsplit

import httpx
from redis.asyncio.client import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.module_client.auth.service import ClientAuthService
from app.api.v1.module_client.user.model import ClientUserModel
from app.api.v1.module_client.user.schema import ClientLoginOutSchema, ClientUserOutSchema, ClientUserRegisterSchema
from app.api.v1.module_growth.engine import BUSINESS_TZ
from app.api.v1.module_growth.reward_service import RewardService
from app.config.setting import settings
from app.core.exceptions import CustomException
from app.utils.password_util import PwdUtil

FLOW_TTL = 300
FLOW_PREFIX = "client:wechat:flow:"
STATE_PREFIX = "client:wechat:state:"


async def exchange_openid(app_id: str, secret: str, code: str) -> str:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            "https://api.weixin.qq.com/sns/oauth2/access_token",
            params={"appid": app_id, "secret": secret, "code": code, "grant_type": "authorization_code"},
        )
        response.raise_for_status()
        identity = response.json()
    openid = identity.get("openid") if isinstance(identity, dict) else None
    if not isinstance(openid, str) or not openid or len(openid) > 64:
        raise ValueError("invalid WeChat identity")
    return openid


class ClientWechatLoginService:
    def __init__(self, db: AsyncSession, redis: Redis) -> None:
        self.db = db
        self.redis = redis
        self.auth = ClientAuthService(db, redis)

    @staticmethod
    def _credentials() -> tuple[str, str, str]:
        app_id = settings.CLIENT_WECHAT_LOGIN_APP_ID.strip()
        secret = settings.CLIENT_WECHAT_LOGIN_APP_SECRET.strip()
        callback = settings.CLIENT_WECHAT_LOGIN_CALLBACK_URL.strip()
        parsed = urlsplit(callback)
        if (
            not app_id
            or not secret
            or parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or not parsed.path.endswith("/api/v1/client/auth/wechat/callback")
        ):
            raise CustomException(msg="微信扫码登录尚未配置", status_code=503)
        return app_id, secret, callback

    @staticmethod
    def _flow_key(flow_id: str) -> str:
        return f"{FLOW_PREFIX}{flow_id}"

    async def _flow(self, flow_id: str) -> dict:
        if len(flow_id) != 43:
            raise CustomException(msg="二维码已失效，请刷新", status_code=404)
        raw = await self.redis.get(self._flow_key(flow_id).encode())
        if not raw:
            raise CustomException(msg="二维码已失效，请刷新", status_code=404)
        return json.loads(raw)

    async def start(self, app_code: str, request_ip: str) -> dict:
        app_id, _, callback = self._credentials()
        await self.auth._rate_limit(scope="wechat-start", app_code=app_code, value=request_ip, limit=20, window=300)
        app = await self.auth._active_app(app_code)
        flow_id = secrets.token_urlsafe(32)
        state = secrets.token_urlsafe(32)
        await self.redis.set(self._flow_key(flow_id).encode(), json.dumps({"app_id": app.id, "app_code": app_code, "status": "pending"}), ex=FLOW_TTL)
        await self.redis.set(f"{STATE_PREFIX}{state}".encode(), flow_id, ex=FLOW_TTL)
        params = urlencode({"appid": app_id, "redirect_uri": callback, "response_type": "code", "scope": "snsapi_login", "state": state})
        return {"flow_id": flow_id, "authorize_url": f"https://open.weixin.qq.com/connect/qrconnect?{params}#wechat_redirect", "expires_in": FLOW_TTL}

    async def callback(self, state: str, code: str | None) -> bool:
        self._credentials()
        if len(state) != 43:
            return False
        raw_flow_id = await self.redis.getdel(f"{STATE_PREFIX}{state}".encode())
        if not raw_flow_id:
            return False
        flow_id = raw_flow_id.decode() if isinstance(raw_flow_id, bytes) else raw_flow_id
        try:
            flow = await self._flow(flow_id)
        except CustomException:
            return False
        if not code:
            flow["status"] = "cancelled"
        else:
            app_id, secret, _ = self._credentials()
            try:
                openid = await exchange_openid(app_id, secret, code)
            except (httpx.HTTPError, ValueError, json.JSONDecodeError):
                flow["status"] = "failed"
            else:
                flow["status"] = "ready"
                flow["openid"] = openid
        await self.redis.set(self._flow_key(flow_id).encode(), json.dumps(flow), ex=900 if flow["status"] == "ready" else FLOW_TTL)
        return flow["status"] == "ready"

    async def _bound_user(self, flow: dict) -> ClientUserModel | None:
        return await self.db.scalar(
            select(ClientUserModel)
            .options(selectinload(ClientUserModel.tags))
            .where(
                ClientUserModel.app_id == flow["app_id"],
                ClientUserModel.wechat_openid == flow["openid"],
                ClientUserModel.is_deleted == False,
            )
        )

    async def _finish(self, user: ClientUserModel, flow: dict, request_ip: str, user_agent: str) -> ClientLoginOutSchema:
        if user.status != "active":
            raise CustomException(msg="账号已停用", status_code=403)
        now = datetime.now(UTC)
        user.last_login_at = now
        user.last_active_at = now
        await RewardService(self.db, user.app_id).emit(user.id, "daily_login", f"daily:{user.id}:{now.astimezone(BUSINESS_TZ).date().isoformat()}", occurred_at=now)
        await self.auth._record_event(
            action="login", app_code=flow["app_code"], username=user.username, request_ip=request_ip, user_agent=user_agent, app_id=user.app_id, user_id=user.id, success=True
        )
        access, refresh = await self.auth._create_session(user)
        return ClientLoginOutSchema(
            access_token=access, refresh_token=refresh, expires_in=settings.ACCESS_TOKEN_EXPIRE_SECONDS, must_change_password=user.must_change_password, user=ClientUserOutSchema.model_validate(user)
        )

    async def poll(self, flow_id: str, request_ip: str, user_agent: str) -> dict:
        flow = await self._flow(flow_id)
        if flow["status"] != "ready":
            return {"status": flow["status"]}
        user = await self._bound_user(flow)
        if not user:
            return {"status": "bind_required"}
        claimed = await self.redis.getdel(self._flow_key(flow_id).encode())
        if not claimed:
            raise CustomException(msg="二维码已失效，请刷新", status_code=404)
        return {"status": "complete", "login": await self._finish(user, flow, request_ip, user_agent)}

    async def bind(
        self,
        flow_id: str,
        username: str | None,
        password: str | None,
        request_ip: str,
        user_agent: str,
        *,
        mobile: str | None = None,
        sms_code: str | None = None,
    ) -> ClientLoginOutSchema:
        flow = await self._flow(flow_id)
        if flow["status"] != "ready":
            raise CustomException(msg="请先完成微信扫码", status_code=409)
        await self.auth._rate_limit(scope="wechat-bind-ip", app_code=flow["app_code"], value=request_ip, limit=20, window=900)
        await self.auth._rate_limit(scope="wechat-bind-account", app_code=flow["app_code"], value=username or mobile or "", limit=10, window=900)
        if await self._bound_user(flow):
            raise CustomException(msg="该微信已绑定其他账号，请刷新二维码", status_code=409)
        if mobile and sms_code:
            from .sms_service import ClientSmsService

            await ClientSmsService(self.db, self.redis).verify(flow["app_id"], flow["app_code"], mobile, "wechat_bind", sms_code, request_ip)
            identity_match = (ClientUserModel.mobile == mobile) & ClientUserModel.mobile_verified_at.is_not(None)
        elif username and password:
            identifier = username.strip().lower()
            identity_match = (
                (ClientUserModel.mobile == identifier) & ClientUserModel.mobile_verified_at.is_not(None) if len(identifier) == 11 and identifier.isdigit() else ClientUserModel.username == identifier
            )
        else:
            raise CustomException(msg="请选择有效的绑定方式", status_code=400)
        user = await self.db.scalar(
            select(ClientUserModel)
            .options(selectinload(ClientUserModel.tags))
            .where(
                ClientUserModel.app_id == flow["app_id"],
                identity_match,
                ClientUserModel.is_deleted == False,
            )
            .with_for_update()
        )
        if not user or (password and not PwdUtil.verify_password(password, user.password_hash)):
            raise CustomException(msg="账号或密码错误", status_code=401)
        if user.status != "active" or (user.wechat_openid and user.wechat_openid != flow["openid"]):
            raise CustomException(msg="账号不可绑定该微信", status_code=409)
        user.wechat_openid = flow["openid"]
        await self.db.flush()
        claimed = await self.redis.getdel(self._flow_key(flow_id).encode())
        if not claimed:
            raise CustomException(msg="二维码已失效，请刷新", status_code=404)
        return await self._finish(user, flow, request_ip, user_agent)

    async def register(self, flow_id: str, data: ClientUserRegisterSchema, request_ip: str, user_agent: str) -> ClientLoginOutSchema:
        flow = await self._flow(flow_id)
        if flow["status"] != "ready" or flow["app_code"] != data.app_code:
            raise CustomException(msg="微信扫码流程已失效", status_code=409)
        if await self._bound_user(flow):
            raise CustomException(msg="该微信已绑定账号，请刷新二维码", status_code=409)
        await self.auth.register(data, request_ip=request_ip, user_agent=user_agent, wechat_openid=flow["openid"])
        user = await self.db.scalar(
            select(ClientUserModel)
            .options(selectinload(ClientUserModel.tags))
            .where(
                ClientUserModel.app_id == flow["app_id"],
                ClientUserModel.wechat_openid == flow["openid"],
                ClientUserModel.is_deleted == False,
            )
        )
        claimed = await self.redis.getdel(self._flow_key(flow_id).encode())
        if not claimed or not user:
            raise CustomException(msg="二维码已失效，请刷新", status_code=404)
        return await self._finish(user, flow, request_ip, user_agent)
