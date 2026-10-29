"""Close unpaid orders without losing payments racing with cancellation."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.module_payment.channel.model import PaymentChannelModel
from app.core.exceptions import CustomException
from app.core.logger import logger

from .model import PaymentAttemptModel, PaymentOrderModel
from .providers import VerifiedAbsentOrder, VerifiedClosedOrder, VerifiedPayment, close_alipay_order, close_wechat_order


def absent_order_deadline(order: PaymentOrderModel) -> datetime | None:
    session = (order.strategy_snapshot or {}).get("payment_session") or {}
    if order.provider != "alipay" or session.get("kind") != "alipay_precreate":
        return None
    try:
        expires_at = datetime.fromisoformat(session["qr_expires_at"])
    except (KeyError, TypeError, ValueError):
        return None
    if expires_at.tzinfo is None:
        return None
    # A successful precreate response arrives after QR creation. Its recorded
    # deadline plus a clock/propagation margin bounds any still-scannable QR.
    return expires_at.astimezone(UTC) + timedelta(minutes=1)


def mark_closed(order: PaymentOrderModel) -> None:
    order.status = "closed"
    order.closed_at = order.closed_at or datetime.now(UTC)
    order.next_query_at = None
    order.pay_url = None
    order.failure_reason = None
    if order.mode_switch:
        order.mode_switch = {**order.mode_switch, "status": "cancelled", "message": "原订单未付款并已关闭，原模式与权益保持不变"}


async def apply_query_result(db: AsyncSession, order: PaymentOrderModel, result: VerifiedPayment | VerifiedClosedOrder | VerifiedAbsentOrder | None) -> bool:
    from .service import PaymentCallbackService

    if isinstance(result, VerifiedPayment):
        await PaymentCallbackService(db).process(order.provider, result)
        return True
    if isinstance(result, VerifiedClosedOrder):
        if result.order_no != order.order_no or result.amount_fen != order.amount_fen:
            raise CustomException(msg="渠道关单结果与原订单不一致，待人工核查", status_code=409)
        if result.previously_paid:
            raise CustomException(msg="渠道订单曾付款后关闭，需核对退款与权益，不能作为未付款取消", status_code=409)
        if order.status != "paid" and order.paid_at is None:
            mark_closed(order)
        return True
    if isinstance(result, VerifiedAbsentOrder):
        if result.order_no != order.order_no or order.provider != "alipay":
            raise CustomException(msg="渠道未建单结果与原订单不一致，待人工核查", status_code=409)
        deadline = absent_order_deadline(order)
        if deadline and datetime.now(UTC) >= deadline and order.status != "paid" and not order.paid_at and not order.provider_trade_no:
            mark_closed(order)
            return True
    return False


async def close_unpaid_order(db: AsyncSession, order: PaymentOrderModel) -> None:
    from .service import PaymentOrderService

    if order.status in {"paid", "closed"} or order.paid_at is not None:
        return
    now = datetime.now(UTC)
    order.cancel_requested_at = order.cancel_requested_at or now
    order.pay_url = None
    attempt = PaymentAttemptModel(app_id=order.app_id, order_id=order.id, order_no=order.order_no, provider=order.provider, action="close", status="started")
    db.add(attempt)
    try:
        result = await PaymentOrderService.query_provider(db, order)
    except Exception as exc:
        logger.warning("关单前查单待核对: order_no={} exception_type={}", order.order_no, type(exc).__name__)
        result, query_failed = None, True
    else:
        query_failed = False
    if not query_failed and await apply_query_result(db, order, result):
        attempt.status = order.status
    elif not query_failed:
        channel = await db.scalar(select(PaymentChannelModel).where(PaymentChannelModel.provider == order.provider, PaymentChannelModel.is_deleted == False))
        try:
            if order.provider == "wechat":
                await close_wechat_order(order.order_no)
            elif order.provider == "alipay":
                await close_alipay_order(order.order_no, sandbox=bool(channel and channel.mode == "sandbox"))
            else:
                raise CustomException(msg="订单支付渠道不支持关单", status_code=422)
        except Exception as exc:
            logger.warning("支付关单结果待核对: order_no={} exception_type={}", order.order_no, type(exc).__name__)
            # The channel may have accepted payment or closure before timing out.
            try:
                result = await PaymentOrderService.query_provider(db, order)
            except Exception:
                result = None
            if await apply_query_result(db, order, result):
                attempt.status = order.status
        else:
            mark_closed(order)
            attempt.status = "closed"
    if attempt.status == "started":
        attempt.status = "unknown"
        attempt.error_message = "关单结果待核对，按原订单继续查单和重试"
        order.status = "confirming"
        order.failure_reason = attempt.error_message
        PaymentOrderService._schedule_query(order, datetime.now(UTC))
        if isinstance(result, VerifiedAbsentOrder) and (deadline := absent_order_deadline(order)):
            attempt.error_message = "支付宝预下单尚未生成交易，等待付款码失效后确认关闭"
            order.failure_reason = attempt.error_message
            # Do not let exponential backoff postpone cancellation past the QR
            # deadline; transport/business errors still retain the normal retry.
            order.next_query_at = min(order.next_query_at, max(deadline, datetime.now(UTC) + timedelta(seconds=30)))
    attempt.completed_at = datetime.now(UTC)
    await db.flush()
