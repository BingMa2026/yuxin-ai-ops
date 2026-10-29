from fastapi import APIRouter

from app.api.v1.module_payment.channel.controller import PaymentChannelRouter
from app.api.v1.module_payment.order.controller import PaymentCallbackRouter, PaymentOrderAdminRouter, PaymentOrderClientRouter

payment_router = APIRouter(prefix="/payment")
payment_router.include_router(PaymentChannelRouter)
payment_router.include_router(PaymentOrderAdminRouter)

payment_client_router = APIRouter(prefix="/client/payment")
payment_client_router.include_router(PaymentOrderClientRouter)

payment_callback_router = APIRouter(prefix="/payment/callback")
payment_callback_router.include_router(PaymentCallbackRouter)
