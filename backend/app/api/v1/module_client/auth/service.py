import asyncio
import hashlib
import inspect
import json
import uuid
from datetime import UTC, datetime, timedelta

from redis.asyncio.client import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.module_client.app.model import ClientAppModel
from app.api.v1.module_client.user.model import ClientAuthEventModel, ClientUserModel
from app.api.v1.module_client.user.schema import (
    ClientLoginOutSchema,
    ClientPasswordChangeSchema,
    ClientSmsLoginSchema,
    ClientUserLoginSchema,
    ClientUserOutSchema,
    ClientUserRegisterSchema,
    ClientUserUpdateSchema,
)
from app.api.v1.module_client.user.service import ClientUserService
from app.config.setting import settings
from app.core.base_schema import AuthSchema, JWTPayloadSchema
from app.core.database import async_db_session
from app.core.exceptions import CustomException
from app.core.logger import logger
from app.core.redis_crud import RedisCURD
from app.core.security import create_access_token, decode_access_token
from app.utils.password_util import PwdUtil


class ClientAuthService:
    def __init__(self, db: AsyncSession, redis: Redis) -> None:
        self.db = db
        self.redis = redis

    @staticmethod
    def _limit_key(*parts: str) -> str:
        digest = hashlib.sha256("\x1f".join(parts).encode()).hexdigest()
        return f"client:auth-limit:{digest}"

    async def _rate_limit(self, *, scope: str, app_code: str, value: str, limit: int, window: int) -> None:
        key = self._limit_key(scope, app_code, value or "unknown")
        try:
            pipeline = self.redis.pipeline(transaction=True)
            if inspect.isawaitable(pipeline):
                pipeline = await pipeline
            increment = pipeline.incr(key)
            if inspect.isawaitable(increment):
                await increment
            expiration = pipeline.expire(key, window)
            if inspect.isawaitable(expiration):
                await expiration
            count, _ = await pipeline.execute()
        except Exception:
            # Redis短暂不可用时不应把所有真实用户锁在门外；数据库安全事件仍会留痕。
            logger.exception("客户端认证限流存储不可用: scope={}", scope)
            return
        if int(count) > limit:
            raise CustomException(msg="请求过于频繁，请稍后再试", status_code=429)

    async def _record_event(
        self,
        *,
        action: str,
        app_code: str,
        username: str,
        request_ip: str,
        user_agent: str,
        app_id: int | None = None,
        user_id: int | None = None,
        success: bool,
        failure_reason: str | None = None,
        independent: bool = False,
    ) -> None:
        values = {
            "app_id": app_id,
            "user_id": user_id,
            "app_code": app_code,
            "username": username,
            "action": action,
            "success": success,
            "failure_reason": failure_reason[:255] if failure_reason else None,
            "request_ip": request_ip[:50] or None,
            "user_agent": user_agent[:255] or None,
        }
        if independent:
            # Snapshot values above before rollback expires ORM objects. A failed
            # request must release its row locks before the audit FK checks run
            # on a second connection; otherwise each transaction waits on the other.
            if self.db is not None:
                await self.db.rollback()
            try:
                async with asyncio.timeout(5):
                    async with async_db_session() as event_db, event_db.begin():
                        event_db.add(ClientAuthEventModel(**values))
            except Exception as exc:
                # Audit failure must not replace the original authentication error.
                # Do not log exception text: SQL parameters can contain personal data.
                logger.error("客户端认证失败事件写入失败: action={} type={}", action, type(exc).__name__)
            return
        self.db.add(ClientAuthEventModel(**values))
        await self.db.flush()

    async def _active_app(self, app_code: str, *, registration: bool = False) -> ClientAppModel:
        app = await self.db.scalar(
            select(ClientAppModel).where(
                ClientAppModel.code == app_code,
                ClientAppModel.status == "active",
                ClientAppModel.is_deleted == False,
            )
        )
        if not app:
            raise CustomException(msg="客户端不存在或已停用", status_code=403)
        if registration and not app.registration_enabled:
            raise CustomException(msg="该客户端暂未开放注册", status_code=403)
        return app

    async def register(
        self,
        data: ClientUserRegisterSchema,
        *,
        request_ip: str = "",
        user_agent: str = "",
        wechat_openid: str | None = None,
    ) -> ClientUserOutSchema:
        app: ClientAppModel | None = None
        try:
            await self._rate_limit(
                scope="register-ip",
                app_code=data.app_code,
                value=request_ip,
                limit=60,
                window=600,
            )
            await self._rate_limit(
                scope="register-account",
                app_code=data.app_code,
                value=data.username,
                limit=5,
                window=3600,
            )
            app = await self._active_app(data.app_code, registration=True)
            from app.api.v1.module_agreement.public_service import PublicAgreementService

            agreements = PublicAgreementService(self.db, app.id)
            agreement_scene = await agreements.validate("auth", data.agreement_acceptance)
            exists = await self.db.scalar(
                select(ClientUserModel.id).where(
                    ClientUserModel.app_id == app.id,
                    ClientUserModel.username == data.username,
                    ClientUserModel.is_deleted == False,
                )
            )
            if exists:
                raise CustomException(msg="该账号已注册", status_code=409)
            mobile_exists = await self.db.scalar(
                select(ClientUserModel.id).where(
                    ClientUserModel.app_id == app.id,
                    ClientUserModel.mobile == data.mobile,
                    ClientUserModel.mobile_verified_at.is_not(None),
                    ClientUserModel.is_deleted == False,
                )
            )
            if mobile_exists:
                raise CustomException(msg="该手机号已绑定其他账号，请选择绑定已有账号", status_code=409)
            if password_error := PwdUtil.check_password_strength(data.password):
                raise CustomException(msg=password_error, status_code=400)
            from .sms_service import ClientSmsService

            await ClientSmsService(self.db, self.redis).verify(
                app.id,
                data.app_code,
                data.mobile,
                "wechat_register" if wechat_openid else "register",
                data.sms_code,
                request_ip,
            )
            user = ClientUserModel(
                app_id=app.id,
                username=data.username,
                password_hash=PwdUtil.hash_password(data.password),
                display_name=data.display_name or data.username,
                company_name=data.company_name,
                mobile=data.mobile,
                mobile_verified_at=datetime.now(UTC),
                wechat_openid=wechat_openid,
                email=str(data.email) if data.email else None,
                status="active",
                registration_source="wechat" if wechat_openid else "self",
                tags=[],
            )
            self.db.add(user)
            await self.db.flush()
            await agreements.record(agreement_scene, user.id, f"registration:{user.id}", data.agreement_acceptance)
            from app.api.v1.module_growth.referral_service import ReferralService

            referrals = ReferralService(self.db, app.id)
            await referrals.profile(user.id)
            if data.invite_code:
                await referrals.bind(user.id, data.invite_code, source="registration")
            await self._record_event(
                action="register",
                app_code=data.app_code,
                username=data.username,
                request_ip=request_ip,
                user_agent=user_agent,
                app_id=app.id,
                user_id=user.id,
                success=True,
            )
            return ClientUserOutSchema.model_validate(user)
        except CustomException as exc:
            await self._record_event(
                action="register",
                app_code=data.app_code,
                username=data.username,
                request_ip=request_ip,
                user_agent=user_agent,
                app_id=app.id if app else None,
                success=False,
                failure_reason=exc.msg,
                independent=True,
            )
            raise

    async def login(
        self,
        data: ClientUserLoginSchema,
        *,
        request_ip: str = "",
        user_agent: str = "",
    ) -> ClientLoginOutSchema:
        app: ClientAppModel | None = None
        user: ClientUserModel | None = None
        account_limit_key = self._limit_key("login-account", data.app_code, data.username)
        try:
            await self._rate_limit(
                scope="login-ip",
                app_code=data.app_code,
                value=request_ip,
                limit=120,
                window=300,
            )
            await self._rate_limit(
                scope="login-account",
                app_code=data.app_code,
                value=data.username,
                limit=10,
                window=900,
            )
            app = await self._active_app(data.app_code)
            identity_match = (
                (ClientUserModel.mobile == data.username) & ClientUserModel.mobile_verified_at.is_not(None)
                if len(data.username) == 11 and data.username.isdigit()
                else ClientUserModel.username == data.username
            )
            user = await self.db.scalar(
                select(ClientUserModel)
                .options(selectinload(ClientUserModel.tags))
                .where(
                    ClientUserModel.app_id == app.id,
                    identity_match,
                    ClientUserModel.is_deleted == False,
                )
            )
            if not user or not PwdUtil.verify_password(data.password, user.password_hash):
                raise CustomException(msg="账号或密码错误", status_code=401)
            if user.status != "active":
                raise CustomException(msg="账号已停用", status_code=403)
            now = datetime.now(UTC)
            user.last_login_at = now
            user.last_active_at = now
            from app.api.v1.module_growth.engine import BUSINESS_TZ
            from app.api.v1.module_growth.reward_service import RewardService

            await RewardService(self.db, app.id).emit(user.id, "daily_login", f"daily:{user.id}:{now.astimezone(BUSINESS_TZ).date().isoformat()}", occurred_at=now)
            await self.db.flush()
            await self._record_event(
                action="login",
                app_code=data.app_code,
                username=data.username,
                request_ip=request_ip,
                user_agent=user_agent,
                app_id=app.id,
                user_id=user.id,
                success=True,
            )
            access_token, refresh_token = await self._create_session(user)
            await RedisCURD(self.redis).delete(account_limit_key)
            return ClientLoginOutSchema(
                access_token=access_token,
                refresh_token=refresh_token,
                expires_in=settings.ACCESS_TOKEN_EXPIRE_SECONDS,
                must_change_password=user.must_change_password,
                user=ClientUserOutSchema.model_validate(user),
            )
        except CustomException as exc:
            await self._record_event(
                action="login",
                app_code=data.app_code,
                username=data.username,
                request_ip=request_ip,
                user_agent=user_agent,
                app_id=app.id if app else None,
                user_id=user.id if user else None,
                success=False,
                failure_reason=exc.msg,
                independent=True,
            )
            raise

    async def login_sms(self, data: ClientSmsLoginSchema, request_ip: str, user_agent: str) -> ClientLoginOutSchema:
        app = await self._active_app(data.app_code.strip().lower())
        from .sms_service import ClientSmsService

        await ClientSmsService(self.db, self.redis).verify(app.id, app.code, data.mobile, "login", data.sms_code, request_ip)
        user = await self.db.scalar(
            select(ClientUserModel)
            .options(selectinload(ClientUserModel.tags))
            .where(
                ClientUserModel.app_id == app.id,
                ClientUserModel.mobile == data.mobile,
                ClientUserModel.mobile_verified_at.is_not(None),
                ClientUserModel.is_deleted == False,
            )
        )
        if not user or user.status != "active":
            raise CustomException(msg="账号不可登录", status_code=403)
        from .wechat_service import ClientWechatLoginService

        return await ClientWechatLoginService(self.db, self.redis)._finish(
            user,
            {"app_code": app.code},
            request_ip,
            user_agent,
        )

    async def _create_session(self, user: ClientUserModel) -> tuple[str, str]:
        session_id = str(uuid.uuid4())
        session = {
            "session_id": session_id,
            "actor_type": "client",
            "app_id": user.app_id,
            "user_id": user.id,
            "auth_generation": user.auth_generation,
        }
        return await self._write_tokens(session_id, session)

    async def _write_tokens(self, session_id: str, session: dict) -> tuple[str, str]:
        now = datetime.now(UTC)
        access_delta = timedelta(seconds=settings.ACCESS_TOKEN_EXPIRE_SECONDS)
        refresh_delta = timedelta(seconds=settings.CLIENT_REFRESH_TOKEN_EXPIRE_SECONDS)
        app_id = int(session["app_id"])
        access_token = create_access_token(JWTPayloadSchema(sub=session_id, is_refresh=False, actor_type="client", app_id=app_id, exp=now + access_delta))
        refresh_token = create_access_token(JWTPayloadSchema(sub=session_id, is_refresh=True, actor_type="client", app_id=app_id, exp=now + refresh_delta))
        cache = RedisCURD(self.redis)
        await cache.set(f"client:session:{session_id}", json.dumps(session), expire=int(refresh_delta.total_seconds()))
        await cache.set(f"client:access:{session_id}", access_token, expire=int(access_delta.total_seconds()))
        await cache.set(f"client:refresh:{session_id}", refresh_token, expire=int(refresh_delta.total_seconds()))
        return access_token, refresh_token

    async def refresh(self, refresh_token: str) -> tuple[str, str]:
        payload = decode_access_token(refresh_token)
        if not payload.is_refresh or payload.actor_type != "client" or not payload.app_id:
            raise CustomException(msg="非法刷新令牌", status_code=401)
        cache = RedisCURD(self.redis)
        raw = await cache.get(f"client:session:{payload.sub}")
        stored = await cache.get(f"client:refresh:{payload.sub}")
        if isinstance(stored, bytes):
            stored = stored.decode("utf-8")
        if not raw or stored != refresh_token:
            raise CustomException(msg="刷新令牌已失效", status_code=401)
        session = json.loads(raw)
        if session.get("app_id") != payload.app_id:
            raise CustomException(msg="刷新令牌上下文无效", status_code=401)
        user = await self.db.scalar(
            select(ClientUserModel).where(
                ClientUserModel.id == session.get("user_id"),
                ClientUserModel.app_id == payload.app_id,
                ClientUserModel.status == "active",
                ClientUserModel.is_deleted == False,
            )
        )
        if not user or user.auth_generation != session.get("auth_generation"):
            raise CustomException(msg="账号已停用或登录已失效", status_code=401)
        app = await self.db.scalar(
            select(ClientAppModel.id).where(
                ClientAppModel.id == payload.app_id,
                ClientAppModel.status == "active",
                ClientAppModel.is_deleted == False,
            )
        )
        if not app:
            raise CustomException(msg="客户端已停用", status_code=401)
        return await self._write_tokens(payload.sub, session)

    async def logout(self, access_token: str) -> None:
        payload = decode_access_token(access_token)
        cache = RedisCURD(self.redis)
        await cache.delete(f"client:access:{payload.sub}", f"client:refresh:{payload.sub}", f"client:session:{payload.sub}")


class ClientSelfService:
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db

    async def _user(self, *, with_tags: bool = True) -> ClientUserModel:
        stmt = select(ClientUserModel).where(
            ClientUserModel.id == self.auth.user.id,
            ClientUserModel.app_id == self.auth.app_id,
            ClientUserModel.is_deleted == False,
        )
        if with_tags:
            stmt = stmt.options(selectinload(ClientUserModel.tags))
        user = await self.db.scalar(stmt)
        if not user:
            raise CustomException(msg="用户不存在", status_code=404)
        return user

    async def me(self) -> ClientUserOutSchema:
        return await ClientUserService(self.auth, self.db).detail(self.auth.user.id)

    async def _available_mobile(self, mobile: str) -> ClientUserModel:
        user = await self._user()
        owner = await self.db.scalar(
            select(ClientUserModel.id).where(
                ClientUserModel.app_id == self.auth.app_id,
                ClientUserModel.mobile == mobile,
                ClientUserModel.mobile_verified_at.is_not(None),
                ClientUserModel.is_deleted == False,
                ClientUserModel.id != user.id,
            )
        )
        if owner:
            raise CustomException(msg="该手机号已绑定其他账号", status_code=409)
        if user.mobile == mobile and user.mobile_verified_at is not None:
            raise CustomException(msg="该手机号已完成验证", status_code=409)
        return user

    async def send_mobile_code(self, mobile: str, redis: Redis, request_ip: str) -> dict:
        await self._available_mobile(mobile)
        app_code = await self.db.scalar(select(ClientAppModel.code).where(ClientAppModel.id == self.auth.app_id))
        if not app_code:
            raise CustomException(msg="客户端不存在", status_code=404)
        from .sms_service import ClientSmsService

        return await ClientSmsService(self.db, redis).send(app_code, mobile, "verify_mobile", request_ip)

    async def verify_mobile(self, mobile: str, sms_code: str, redis: Redis, request_ip: str) -> ClientUserOutSchema:
        user = await self._available_mobile(mobile)
        app_code = await self.db.scalar(select(ClientAppModel.code).where(ClientAppModel.id == self.auth.app_id))
        if not app_code:
            raise CustomException(msg="客户端不存在", status_code=404)
        from .sms_service import ClientSmsService

        await ClientSmsService(self.db, redis).verify(self.auth.app_id, app_code, mobile, "verify_mobile", sms_code, request_ip)
        user.mobile = mobile
        user.mobile_verified_at = datetime.now(UTC)
        await self.db.flush()
        return await ClientUserService(self.auth, self.db).detail(user.id)

    async def update(self, data: ClientUserUpdateSchema) -> ClientUserOutSchema:
        user = await self._user()
        for key, value in data.model_dump(exclude_unset=True).items():
            if key == "mobile" and value != user.mobile:
                if user.mobile_verified_at is not None:
                    raise CustomException(msg="已验证手机号不能在个人资料中直接修改，请联系运营人员处理", status_code=409)
                user.mobile_verified_at = None
            setattr(user, key, str(value) if key == "email" and value else value)
        await self.db.flush()
        return await ClientUserService(self.auth, self.db).detail(user.id)

    async def change_password(self, data: ClientPasswordChangeSchema) -> None:
        user = await self._user(with_tags=False)
        if not PwdUtil.verify_password(data.old_password, user.password_hash):
            raise CustomException(msg="原密码错误", status_code=400)
        if error := PwdUtil.check_password_strength(data.new_password):
            raise CustomException(msg=error, status_code=400)
        user.password_hash = PwdUtil.hash_password(data.new_password)
        user.must_change_password = False
        user.auth_generation += 1
        await self.db.flush()
