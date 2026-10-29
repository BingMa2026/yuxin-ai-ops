import json

from fastapi import Depends
from redis.asyncio.client import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.module_client.user.model import ClientUserModel
from app.common.enums import RET
from app.core.base_schema import AuthSchema, CoreUserSchema
from app.core.dependencies import db_getter, redis_getter
from app.core.exceptions import CustomException
from app.core.redis_crud import RedisCURD
from app.core.security import OAuth2Schema, decode_access_token


async def get_current_client_user(
    db: AsyncSession = Depends(db_getter),
    redis: Redis = Depends(redis_getter),
    token: str = Depends(OAuth2Schema),
) -> AuthSchema:
    """只接受客户端用户令牌，并在每次请求校验账号与应用状态。"""
    payload = decode_access_token(token, verify_exp=True)
    if payload.is_refresh or payload.actor_type != "client" or not payload.app_id:
        raise CustomException(msg="客户端认证无效", code=RET.UNAUTHORIZED.code, status_code=401)

    session_key = f"client:session:{payload.sub}"
    raw = await RedisCURD(redis).get(session_key)
    stored_access = await RedisCURD(redis).get(f"client:access:{payload.sub}")
    if isinstance(stored_access, bytes):
        stored_access = stored_access.decode("utf-8")
    if not raw or stored_access != token:
        raise CustomException(msg="客户端登录已失效", code=RET.UNAUTHORIZED.code, status_code=401)
    session = json.loads(raw)
    if session.get("actor_type") != "client" or session.get("app_id") != payload.app_id:
        raise CustomException(msg="客户端认证上下文无效", code=RET.UNAUTHORIZED.code, status_code=401)

    user = await db.scalar(
        select(ClientUserModel).where(
            ClientUserModel.id == session.get("user_id"),
            ClientUserModel.app_id == payload.app_id,
            ClientUserModel.is_deleted == False,
        )
    )
    if not user or user.status != "active" or user.auth_generation != session.get("auth_generation"):
        raise CustomException(msg="账号已停用或登录已失效", code=RET.UNAUTHORIZED.code, status_code=401)

    from app.api.v1.module_client.app.model import ClientAppModel

    app = await db.scalar(
        select(ClientAppModel).where(
            ClientAppModel.id == payload.app_id,
            ClientAppModel.status == "active",
            ClientAppModel.is_deleted == False,
        )
    )
    if not app:
        raise CustomException(msg="客户端已停用", code=RET.UNAUTHORIZED.code, status_code=401)

    return AuthSchema(
        user=CoreUserSchema(id=user.id, username=user.username, name=user.display_name),
        actor_type="client",
        app_id=payload.app_id,
    )


async def get_current_runtime_user(
    db: AsyncSession = Depends(db_getter),
    redis: Redis = Depends(redis_getter),
    token: str = Depends(OAuth2Schema),
) -> AuthSchema:
    """校验短时模型运行令牌，并复核其来源客户端会话仍然有效。"""
    payload = decode_access_token(token, verify_exp=True)
    if payload.is_refresh or payload.actor_type != "runtime" or not payload.app_id:
        raise CustomException(msg="模型运行认证无效", code=RET.UNAUTHORIZED.code, status_code=401)

    raw = await RedisCURD(redis).get(f"client:session:{payload.sub}")
    if not raw:
        raise CustomException(msg="客户端登录已失效", code=RET.UNAUTHORIZED.code, status_code=401)
    session = json.loads(raw)
    if session.get("actor_type") != "client" or session.get("app_id") != payload.app_id:
        raise CustomException(msg="模型运行上下文无效", code=RET.UNAUTHORIZED.code, status_code=401)

    user = await db.scalar(
        select(ClientUserModel).where(
            ClientUserModel.id == session.get("user_id"),
            ClientUserModel.app_id == payload.app_id,
            ClientUserModel.status == "active",
            ClientUserModel.is_deleted == False,
        )
    )
    if not user or user.auth_generation != session.get("auth_generation"):
        raise CustomException(msg="账号已停用或登录已失效", code=RET.UNAUTHORIZED.code, status_code=401)

    from app.api.v1.module_client.app.model import ClientAppModel

    app_exists = await db.scalar(
        select(ClientAppModel.id).where(
            ClientAppModel.id == payload.app_id,
            ClientAppModel.status == "active",
            ClientAppModel.is_deleted == False,
        )
    )
    if not app_exists:
        raise CustomException(msg="客户端已停用", code=RET.UNAUTHORIZED.code, status_code=401)
    from app.api.v1.module_client.app.model_policy import require_platform_model

    app = await require_platform_model(db, payload.app_id, user_id=user.id)
    if (payload.mode_version is not None and payload.mode_version != user.mode_version) or (payload.policy_version is not None and payload.policy_version != app.model_policy_version) or (app.service_mode == "user_choice" and (payload.mode_version is None or payload.policy_version is None)):
        raise CustomException(msg="订阅模式已更新，请刷新使用权限后重试", status_code=401)
    auth = AuthSchema(
        user=CoreUserSchema(id=user.id, username=user.username, name=user.display_name),
        actor_type="runtime",
        app_id=payload.app_id,
    )
    # 鉴权读取已完成；生成模型内容前释放连接，避免依赖清理时提交过期事务。
    await db.rollback()
    return auth
