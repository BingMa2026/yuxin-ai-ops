from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, File, Path, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field, model_validator
from redis.asyncio.client import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.module_client.app.model import ClientAppModel
from app.api.v1.module_client.user.schema import (
    ClientLoginOutSchema,
    ClientPasswordChangeSchema,
    ClientRefreshSchema,
    ClientSmsLoginSchema,
    ClientUserLoginSchema,
    ClientUserOutSchema,
    ClientUserRegisterSchema,
    ClientUserUpdateSchema,
)
from app.api.v1.module_common.file.service import FileService
from app.common.response import ResponseSchema, SuccessResponse
from app.config.setting import settings
from app.core.base_schema import AuthSchema, JWTOutSchema, UploadResponseSchema
from app.core.client_dependencies import get_current_client_user
from app.core.dependencies import db_getter, redis_getter
from app.core.exceptions import CustomException
from app.core.security import OAuth2Schema
from app.utils.ip_local_util import get_client_ip

from .service import ClientAuthService, ClientSelfService
from .sms_service import CODE_TTL, ClientSmsService, sms_configured
from .wechat_service import FLOW_TTL, ClientWechatLoginService

ClientAuthRouter = APIRouter(prefix="/auth", tags=["客户端认证"])
ClientSelfRouter = APIRouter(prefix="/user", tags=["客户端个人资料"])


class WechatStartInput(BaseModel):
    app_code: str = Field(min_length=2, max_length=64)


class WechatFlowInput(BaseModel):
    flow_id: str = Field(min_length=43, max_length=43)


class WechatBindInput(WechatFlowInput):
    username: str | None = Field(default=None, min_length=3, max_length=32)
    password: str | None = Field(default=None, min_length=6, max_length=128)
    mobile: str | None = Field(default=None, pattern=r"^1[3-9]\d{9}$")
    sms_code: str | None = Field(default=None, pattern=r"^\d{6}$")

    @model_validator(mode="after")
    def exactly_one_method(self):
        account_method = self.username is not None and self.password is not None
        phone_method = self.mobile is not None and self.sms_code is not None
        if account_method == phone_method or (account_method and (self.mobile is not None or self.sms_code is not None)) or (phone_method and (self.username is not None or self.password is not None)):
            raise ValueError("请选择账号密码或手机号验证码中的一种绑定方式")
        return self


class WechatRegisterInput(ClientUserRegisterSchema):
    flow_id: str = Field(min_length=43, max_length=43)


class SmsSendInput(BaseModel):
    app_code: str = Field(min_length=2, max_length=64)
    mobile: str = Field(pattern=r"^1[3-9]\d{9}$")
    purpose: Literal["register", "login", "wechat_register", "wechat_bind"]
    flow_id: str | None = Field(default=None, min_length=43, max_length=43)


class MobileSendInput(BaseModel):
    mobile: str = Field(pattern=r"^1[3-9]\d{9}$")


class MobileVerifyInput(MobileSendInput):
    sms_code: str = Field(pattern=r"^\d{6}$")


class ClientAuthCapabilities(BaseModel):
    app_code: str
    registration_enabled: bool
    password_login_enabled: bool
    sms_login_configured: bool
    sms_registration_configured: bool
    sms_bind_configured: bool
    wechat_login_configured: bool
    sms_code_length: int
    sms_expires_in: int
    sms_retry_after: int
    wechat_qr_expires_in: int


@ClientAuthRouter.get("/capabilities/{app_code}", response_model=ResponseSchema[ClientAuthCapabilities], summary="查询客户端登录能力")
async def get_client_auth_capabilities(
    db: Annotated[AsyncSession, Depends(db_getter)],
    app_code: Annotated[str, Path(min_length=2, max_length=64)],
) -> JSONResponse:
    code = app_code.strip().lower()
    app = await db.scalar(select(ClientAppModel).where(ClientAppModel.code == code, ClientAppModel.status == "active", ClientAppModel.is_deleted == False))
    if not app:
        raise CustomException(msg="客户端不存在或已停用", status_code=404)
    try:
        ClientWechatLoginService._credentials()
        wechat_configured = True
    except CustomException:
        wechat_configured = False
    result = ClientAuthCapabilities(
        app_code=app.code,
        registration_enabled=app.registration_enabled,
        password_login_enabled=True,
        sms_login_configured=sms_configured("login"),
        sms_registration_configured=app.registration_enabled and sms_configured("register"),
        sms_bind_configured=sms_configured("wechat_bind"),
        wechat_login_configured=wechat_configured,
        sms_code_length=6,
        sms_expires_in=CODE_TTL,
        sms_retry_after=60,
        wechat_qr_expires_in=FLOW_TTL,
    )
    response = SuccessResponse(data=result)
    response.headers["Cache-Control"] = "no-store"
    return response


@ClientAuthRouter.post("/wechat/start", response_model=ResponseSchema[dict], summary="创建客户端微信扫码登录")
async def start_client_wechat_login(
    request: Request,
    db: Annotated[AsyncSession, Depends(db_getter)],
    redis: Annotated[Redis, Depends(redis_getter)],
    data: Annotated[WechatStartInput, Body()],
) -> JSONResponse:
    result = await ClientWechatLoginService(db, redis).start(data.app_code.strip().lower(), get_client_ip(request))
    return SuccessResponse(data=result)


@ClientAuthRouter.get("/wechat/callback", response_class=HTMLResponse, summary="微信网站应用登录回调")
async def client_wechat_callback(
    db: Annotated[AsyncSession, Depends(db_getter)],
    redis: Annotated[Redis, Depends(redis_getter)],
    state: str = "",
    code: str | None = None,
) -> HTMLResponse:
    successful = await ClientWechatLoginService(db, redis).callback(state, code)
    message = "微信身份已确认，请返回喻信AI客户端。" if successful else "扫码未完成或二维码已失效，请返回客户端重试。"
    return HTMLResponse(
        f"<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>喻信AI微信登录</title><body><main><h1>{message}</h1></main></body></html>", headers={"Cache-Control": "no-store"}
    )


@ClientAuthRouter.post("/wechat/poll", response_model=ResponseSchema[dict], summary="查询微信扫码登录状态")
async def poll_client_wechat_login(
    request: Request,
    db: Annotated[AsyncSession, Depends(db_getter)],
    redis: Annotated[Redis, Depends(redis_getter)],
    data: Annotated[WechatFlowInput, Body()],
) -> JSONResponse:
    result = await ClientWechatLoginService(db, redis).poll(data.flow_id, get_client_ip(request), request.headers.get("user-agent", ""))
    return SuccessResponse(data=result)


@ClientAuthRouter.post("/wechat/bind", response_model=ResponseSchema[ClientLoginOutSchema], summary="验证已有账号并绑定微信")
async def bind_client_wechat_login(
    request: Request,
    db: Annotated[AsyncSession, Depends(db_getter)],
    redis: Annotated[Redis, Depends(redis_getter)],
    data: Annotated[WechatBindInput, Body()],
) -> JSONResponse:
    result = await ClientWechatLoginService(db, redis).bind(
        data.flow_id,
        data.username,
        data.password,
        get_client_ip(request),
        request.headers.get("user-agent", ""),
        mobile=data.mobile,
        sms_code=data.sms_code,
    )
    return SuccessResponse(data=result)


@ClientAuthRouter.post("/wechat/register", response_model=ResponseSchema[ClientLoginOutSchema], summary="首次微信扫码创建客户端账号")
async def register_client_wechat_login(
    request: Request,
    db: Annotated[AsyncSession, Depends(db_getter)],
    redis: Annotated[Redis, Depends(redis_getter)],
    data: Annotated[WechatRegisterInput, Body()],
) -> JSONResponse:
    result = await ClientWechatLoginService(db, redis).register(
        data.flow_id,
        data,
        get_client_ip(request),
        request.headers.get("user-agent", ""),
    )
    return SuccessResponse(data=result)


@ClientAuthRouter.post("/sms/send", response_model=ResponseSchema[dict], summary="发送客户端手机验证码")
async def send_client_sms(
    request: Request,
    db: Annotated[AsyncSession, Depends(db_getter)],
    redis: Annotated[Redis, Depends(redis_getter)],
    data: Annotated[SmsSendInput, Body()],
) -> JSONResponse:
    result = await ClientSmsService(db, redis).send(data.app_code.strip().lower(), data.mobile, data.purpose, get_client_ip(request), flow_id=data.flow_id)
    return SuccessResponse(data=result, msg="如手机号符合条件，验证码将发送")


@ClientAuthRouter.post("/sms/login", response_model=ResponseSchema[ClientLoginOutSchema], summary="手机号验证码登录")
async def login_client_sms(
    request: Request,
    db: Annotated[AsyncSession, Depends(db_getter)],
    redis: Annotated[Redis, Depends(redis_getter)],
    data: Annotated[ClientSmsLoginSchema, Body()],
) -> JSONResponse:
    result = await ClientAuthService(db, redis).login_sms(data, get_client_ip(request), request.headers.get("user-agent", ""))
    return SuccessResponse(data=result)


@ClientAuthRouter.post("/register", response_model=ResponseSchema[ClientUserOutSchema], summary="客户端账号注册")
async def register_client_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(db_getter)],
    redis: Annotated[Redis, Depends(redis_getter)],
    data: Annotated[ClientUserRegisterSchema, Body()],
) -> JSONResponse:
    return SuccessResponse(
        data=await ClientAuthService(db, redis).register(
            data,
            request_ip=get_client_ip(request),
            user_agent=request.headers.get("user-agent", ""),
        ),
        msg="注册成功",
    )


@ClientAuthRouter.post("/login", response_model=ResponseSchema[ClientLoginOutSchema], summary="客户端账号登录")
async def login_client_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(db_getter)],
    redis: Annotated[Redis, Depends(redis_getter)],
    data: Annotated[ClientUserLoginSchema, Body()],
) -> JSONResponse:
    return SuccessResponse(
        data=await ClientAuthService(db, redis).login(
            data,
            request_ip=get_client_ip(request),
            user_agent=request.headers.get("user-agent", ""),
        ),
        msg="登录成功",
    )


@ClientAuthRouter.post("/refresh", response_model=ResponseSchema[JWTOutSchema], summary="刷新客户端令牌")
async def refresh_client_token(
    db: Annotated[AsyncSession, Depends(db_getter)],
    redis: Annotated[Redis, Depends(redis_getter)],
    data: Annotated[ClientRefreshSchema, Body()],
) -> JSONResponse:
    access, refresh = await ClientAuthService(db, redis).refresh(data.refresh_token)
    return SuccessResponse(
        data=JWTOutSchema(access_token=access, refresh_token=refresh, expires_in=settings.ACCESS_TOKEN_EXPIRE_SECONDS),
        msg="刷新成功",
    )


@ClientAuthRouter.post("/logout", response_model=ResponseSchema[None], summary="退出客户端登录")
async def logout_client_user(
    _: Annotated[AuthSchema, Depends(get_current_client_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    redis: Annotated[Redis, Depends(redis_getter)],
    token: Annotated[str, Depends(OAuth2Schema)],
) -> JSONResponse:
    await ClientAuthService(db, redis).logout(token)
    return SuccessResponse(msg="退出成功")


@ClientSelfRouter.get("/me", response_model=ResponseSchema[ClientUserOutSchema], summary="客户端当前用户")
async def get_client_me(
    auth: Annotated[AuthSchema, Depends(get_current_client_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
) -> JSONResponse:
    return SuccessResponse(data=await ClientSelfService(auth, db).me())


@ClientSelfRouter.patch("/me", response_model=ResponseSchema[ClientUserOutSchema], summary="更新客户端当前用户")
async def update_client_me(
    auth: Annotated[AuthSchema, Depends(get_current_client_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[ClientUserUpdateSchema, Body()],
) -> JSONResponse:
    return SuccessResponse(data=await ClientSelfService(auth, db).update(data), msg="个人资料更新成功")


@ClientSelfRouter.post("/me/mobile/send", response_model=ResponseSchema[dict], summary="发送本人手机号验证短信")
async def send_client_mobile_verification(
    request: Request,
    auth: Annotated[AuthSchema, Depends(get_current_client_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    redis: Annotated[Redis, Depends(redis_getter)],
    data: Annotated[MobileSendInput, Body()],
) -> JSONResponse:
    result = await ClientSelfService(auth, db).send_mobile_code(data.mobile, redis, get_client_ip(request))
    return SuccessResponse(data=result, msg="验证码已发送")


@ClientSelfRouter.post("/me/mobile/verify", response_model=ResponseSchema[ClientUserOutSchema], summary="验证并绑定本人手机号")
async def verify_client_mobile(
    request: Request,
    auth: Annotated[AuthSchema, Depends(get_current_client_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    redis: Annotated[Redis, Depends(redis_getter)],
    data: Annotated[MobileVerifyInput, Body()],
) -> JSONResponse:
    result = await ClientSelfService(auth, db).verify_mobile(data.mobile, data.sms_code, redis, get_client_ip(request))
    return SuccessResponse(data=result, msg="手机号验证成功")


@ClientSelfRouter.post("/avatar", response_model=ResponseSchema[UploadResponseSchema], summary="上传客户端用户头像")
async def upload_client_avatar(
    request: Request,
    auth: Annotated[AuthSchema, Depends(get_current_client_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    file: Annotated[UploadFile, File(description="头像图片")],
) -> JSONResponse:
    filename = file.filename or ""
    extension = f".{filename.rsplit('.', 1)[-1].lower()}" if "." in filename else ""
    if extension not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise CustomException(msg="头像仅支持 JPG、PNG 或 WebP 图片")
    result = await FileService.upload_service(
        base_url=str(request.base_url),
        file=file,
        upload_type="avatar",
    )
    await ClientSelfService(auth, db).update(ClientUserUpdateSchema(avatar=result.file_url))
    return SuccessResponse(data=result, msg="头像更新成功")


@ClientSelfRouter.post("/change-password", response_model=ResponseSchema[None], summary="修改客户端密码")
async def change_client_password(
    auth: Annotated[AuthSchema, Depends(get_current_client_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[ClientPasswordChangeSchema, Body()],
) -> JSONResponse:
    await ClientSelfService(auth, db).change_password(data)
    return SuccessResponse(msg="密码修改成功，请重新登录")
