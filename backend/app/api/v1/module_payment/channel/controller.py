from typing import Annotated

from fastapi import APIRouter, Body, Depends, Path, Security
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.base_schema import AuthSchema
from app.core.dependencies import AuthPermission, db_getter
from app.core.router_class import OperationLogRoute

from .schema import PaymentChannelOutSchema, PaymentChannelToggleSchema, PaymentChannelUpdateSchema, PaymentProvider
from .service import PaymentChannelService

PaymentChannelRouter = APIRouter(route_class=OperationLogRoute, prefix="/channel", tags=["支付渠道"])


@PaymentChannelRouter.get("/list", summary="查询支付渠道", response_model=ResponseSchema[list[PaymentChannelOutSchema]])
async def get_payment_channels_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_payment:channel:list"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
) -> JSONResponse:
    result = await PaymentChannelService(auth, db).list()
    return SuccessResponse(data=result, msg="查询支付渠道成功")


@PaymentChannelRouter.get("/detail/{provider}", summary="查询支付渠道详情", response_model=ResponseSchema[PaymentChannelOutSchema])
async def get_payment_channel_detail_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_payment:channel:list"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    provider: Annotated[PaymentProvider, Path(description="渠道标识")],
) -> JSONResponse:
    result = await PaymentChannelService(auth, db).detail(provider)
    return SuccessResponse(data=result, msg="查询支付渠道详情成功")


@PaymentChannelRouter.put("/update/{provider}", summary="修改支付渠道", response_model=ResponseSchema[PaymentChannelOutSchema])
async def update_payment_channel_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_payment:channel:edit"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    provider: Annotated[PaymentProvider, Path(description="渠道标识")],
    data: Annotated[PaymentChannelUpdateSchema, Body()],
) -> JSONResponse:
    result = await PaymentChannelService(auth, db).update(provider, data)
    return SuccessResponse(data=result, msg="修改支付渠道成功")


@PaymentChannelRouter.put("/toggle/{provider}", summary="启停支付渠道", response_model=ResponseSchema[PaymentChannelOutSchema])
async def toggle_payment_channel_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_payment:channel:edit"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    provider: Annotated[PaymentProvider, Path(description="渠道标识")],
    data: Annotated[PaymentChannelToggleSchema, Body()],
) -> JSONResponse:
    result = await PaymentChannelService(auth, db).toggle(provider, data.enabled)
    return SuccessResponse(data=result, msg="支付渠道状态已更新")


@PaymentChannelRouter.put("/bind/{provider}", summary="配置当前客户端支付渠道", response_model=ResponseSchema[PaymentChannelOutSchema])
async def bind_payment_channel_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_payment:channel:edit"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    provider: Annotated[PaymentProvider, Path(description="渠道标识")],
    data: Annotated[PaymentChannelToggleSchema, Body()],
) -> JSONResponse:
    result = await PaymentChannelService(auth, db).bind_app(provider, data.enabled)
    return SuccessResponse(data=result, msg="当前客户端支付渠道已更新")
