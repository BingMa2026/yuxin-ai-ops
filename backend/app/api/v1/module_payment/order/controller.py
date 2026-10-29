from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, Path, Request, Security, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ErrorResponse, ResponseSchema, SuccessResponse
from app.core.base_schema import AuthSchema
from app.core.client_dependencies import get_current_client_user
from app.core.database import async_db_session
from app.core.dependencies import AuthPermission, db_getter
from app.core.router_class import OperationLogRoute

from .providers import verify_alipay_callback, verify_wechat_callback
from .schema import PaymentCapability, PaymentOrderCancel, PaymentOrderCreate, PaymentOrderOut
from .service import PaymentCallbackService, PaymentOrderService

PaymentOrderAdminRouter = APIRouter(route_class=OperationLogRoute, prefix="/orders", tags=["支付订单"])
PaymentOrderClientRouter = APIRouter(tags=["客户端支付"])
PaymentCallbackRouter = APIRouter(tags=["支付回调"])


@PaymentOrderAdminRouter.get("", response_model=ResponseSchema[list[PaymentOrderOut]])
async def admin_orders(
    auth: Annotated[AuthSchema, Security(AuthPermission(["workspace:budget:subscription:list"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    entitlement_kind: Literal["credits", "duration"] | None = None,
) -> JSONResponse:
    return SuccessResponse(data=await PaymentOrderService(auth, db).list_admin(entitlement_kind))


@PaymentOrderClientRouter.get("/capabilities", response_model=ResponseSchema[list[PaymentCapability]])
async def payment_capabilities(
    auth: Annotated[AuthSchema, Depends(get_current_client_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
) -> JSONResponse:
    return SuccessResponse(data=await PaymentOrderService(auth, db).capabilities())


@PaymentOrderClientRouter.post("/orders", response_model=ResponseSchema[PaymentOrderOut], status_code=status.HTTP_201_CREATED)
async def create_payment_order(
    auth: Annotated[AuthSchema, Depends(get_current_client_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[PaymentOrderCreate, Body()],
) -> JSONResponse:
    order = await PaymentOrderService(auth, db).create(data)
    if order.status == "failed":
        return ErrorResponse(data=order, msg="支付渠道下单失败，请重新发起支付", status_code=status.HTTP_502_BAD_GATEWAY)
    if order.status == "confirming":
        return ErrorResponse(data=order, msg="支付结果待确认，请通过订单号查单", status_code=status.HTTP_202_ACCEPTED)
    return SuccessResponse(
        data=order,
        msg="订单创建成功",
        status_code=status.HTTP_201_CREATED,
    )


@PaymentOrderClientRouter.get("/orders/{order_no}", response_model=ResponseSchema[PaymentOrderOut])
async def payment_order_status(
    auth: Annotated[AuthSchema, Depends(get_current_client_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    order_no: Annotated[str, Path(min_length=8, max_length=64)],
) -> JSONResponse:
    return SuccessResponse(data=await PaymentOrderService(auth, db).get(order_no))


def cancellation_response(order: PaymentOrderOut) -> JSONResponse:
    if order.status == "paid" or order.paid_at is not None:
        return ErrorResponse(data=order, msg="订单已付款，不能取消；如需退款请联系运营", status_code=status.HTTP_409_CONFLICT)
    if order.status != "closed":
        return ErrorResponse(data=order, msg="关单结果待确认，请保留原订单号继续查询", status_code=status.HTTP_202_ACCEPTED)
    return SuccessResponse(data=order, msg="订单已确认关闭")


@PaymentOrderClientRouter.post("/orders/{order_no}/cancel", response_model=ResponseSchema[PaymentOrderOut])
async def cancel_payment_order(
    auth: Annotated[AuthSchema, Depends(get_current_client_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    order_no: Annotated[str, Path(min_length=8, max_length=64, pattern=r"^[a-zA-Z0-9_.:-]+$")],
    data: Annotated[PaymentOrderCancel | None, Body()] = None,
) -> JSONResponse:
    return cancellation_response(await PaymentOrderService(auth, db).cancel(order_no, (data or PaymentOrderCancel()).reason))


@PaymentCallbackRouter.post("/wechat", response_class=PlainTextResponse)
async def wechat_payment_callback(request: Request) -> PlainTextResponse:
    raw = await request.body()
    paid = verify_wechat_callback({key.lower(): value for key, value in request.headers.items()}, raw)
    async with async_db_session() as db, db.begin():
        await PaymentCallbackService(db).process("wechat", paid)
    return PlainTextResponse("", status_code=status.HTTP_204_NO_CONTENT)


@PaymentCallbackRouter.post("/alipay", response_class=PlainTextResponse)
async def alipay_payment_callback(request: Request) -> PlainTextResponse:
    form = await request.form()
    paid = verify_alipay_callback({key: str(value) for key, value in form.items()})
    async with async_db_session() as db, db.begin():
        await PaymentCallbackService(db).process("alipay", paid)
    return PlainTextResponse("success")
