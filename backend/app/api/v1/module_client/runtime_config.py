"""Authenticated runtime policy, deliberately separate from provider credentials."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.module_billing.duration import utc
from app.api.v1.module_billing.model import SubscriptionModel
from app.api.v1.module_client.app.model_policy import allowed_modes, billing_user, current_mode, get_model_policy
from app.common.response import ResponseSchema, SuccessResponse
from app.core.base_schema import AuthSchema
from app.core.client_dependencies import get_current_client_user
from app.core.dependencies import db_getter
from app.core.exceptions import CustomException


class RuntimeAuthorization(BaseModel):
    status: Literal["active", "not_purchased", "expired", "suspended", "platform", "mode_required"]
    can_start_task: bool
    expires_at: datetime | None = None
    remaining_seconds: int = 0


class ClientRuntimeConfig(BaseModel):
    schema_version: int = 1
    app_id: int
    user_id: int
    platform_model_enabled: bool
    allow_custom_model: bool
    billing_mode: Literal["credits", "duration"] | None
    policy_version: int
    server_time: datetime
    refresh_after_seconds: int = 3600
    authorization: RuntimeAuthorization


class ClientRuntimeConfigV2(ClientRuntimeConfig):
    schema_version: int = 2
    service_mode: Literal["credits_only", "duration_only", "user_choice"]
    allowed_billing_modes: list[Literal["credits", "duration"]]
    active_billing_mode: Literal["credits", "duration"] | None
    mode_version: int


async def runtime_config(db, auth, schema_version=1):
    app = await get_model_policy(db, auth.app_id)
    if schema_version == 1 and app.service_mode == "user_choice":
        raise CustomException(msg="当前服务支持选择订阅模式，请升级客户端后继续使用", status_code=409)
    user = await billing_user(db, app, auth.user.id)
    mode = current_mode(app, user)
    now = datetime.now(UTC)
    authorization = RuntimeAuthorization(status="platform", can_start_task=True)
    if mode == "duration":
        subscription = await db.scalar(
            select(SubscriptionModel).where(
                SubscriptionModel.app_id == auth.app_id,
                SubscriptionModel.user_id == auth.user.id,
                SubscriptionModel.entitlement_kind == "duration",
                SubscriptionModel.is_deleted == False,
            )
        )
        end = utc(subscription.current_period_end) if subscription else None
        status = "not_purchased"
        if subscription:
            status = "suspended" if subscription.status == "cancelled" else "active" if subscription.status == "active" and utc(subscription.current_period_start) <= now < end else "expired"
        authorization = RuntimeAuthorization(status=status, can_start_task=status == "active", expires_at=end, remaining_seconds=max(0, int((end - now).total_seconds())) if end else 0)
    if mode is None:
        authorization = RuntimeAuthorization(status="mode_required", can_start_task=False)
    elif mode not in allowed_modes(app):
        authorization = RuntimeAuthorization(status="suspended", can_start_task=False)
    extra = {"service_mode": app.service_mode, "allowed_billing_modes": allowed_modes(app), "active_billing_mode": mode, "mode_version": user.mode_version} if schema_version == 2 else {}
    return (ClientRuntimeConfigV2 if schema_version == 2 else ClientRuntimeConfig)(
        **extra,
        app_id=app.id,
        user_id=auth.user.id,
        platform_model_enabled=mode == "credits" and mode in allowed_modes(app),
        allow_custom_model=mode == "duration" and mode in allowed_modes(app),
        billing_mode=mode,
        policy_version=app.model_policy_version,
        server_time=now,
        authorization=authorization,
    )


ClientRuntimeConfigRouter = APIRouter()


@ClientRuntimeConfigRouter.get("/runtime-config", response_model=ResponseSchema[ClientRuntimeConfigV2 | ClientRuntimeConfig], summary="客户端模型模式与使用期限")
async def get_runtime_config(auth: Annotated[AuthSchema, Depends(get_current_client_user)], db: Annotated[AsyncSession, Depends(db_getter)], schema_version: Annotated[int, Query(ge=1, le=2)] = 1):
    response = SuccessResponse(data=(await runtime_config(db, auth, schema_version)).model_dump(mode="json"))
    response.headers["Cache-Control"] = "no-store"
    return response
