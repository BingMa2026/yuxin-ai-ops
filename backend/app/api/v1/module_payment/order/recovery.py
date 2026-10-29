"""支付通知丢失时按原商户订单号主动查单。"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select

from app.api.v1.module_growth.service import lock_app
from app.api.v1.module_payment.channel.model import PaymentChannelModel
from app.core.database import async_db_session
from app.core.logger import logger

from .cancellation import apply_query_result, close_unpaid_order
from .model import PaymentAttemptModel, PaymentOrderModel
from .providers import VerifiedPayment, query_alipay_order, query_wechat_order
from .service import PaymentOrderService


async def recover_order(app_id: int, order_id: int) -> None:
    async with async_db_session() as db:
        order = await db.scalar(select(PaymentOrderModel).where(PaymentOrderModel.app_id == app_id, PaymentOrderModel.id == order_id))
        if not order or order.status in {"paid", "closed"} or order.is_deleted:
            return
        order_no, provider = order.order_no, order.provider
        channel = await db.scalar(select(PaymentChannelModel).where(PaymentChannelModel.provider == provider, PaymentChannelModel.is_deleted == False))
        sandbox = bool(channel and channel.mode == "sandbox")

    try:
        paid = await (query_wechat_order(order_no, include_closed=True) if provider == "wechat" else query_alipay_order(order_no, sandbox=sandbox, include_closed=True))
        error = None
    except Exception as exc:
        paid, error = None, type(exc).__name__
        logger.warning("支付自动查单失败: app_id={} order_no={} exception_type={}", app_id, order_no, error)

    try:
        async with async_db_session() as db, db.begin():
            await lock_app(db, app_id)
            order = await db.scalar(select(PaymentOrderModel).where(PaymentOrderModel.app_id == app_id, PaymentOrderModel.id == order_id).with_for_update().execution_options(populate_existing=True))
            if not order:
                return
            now = datetime.now(UTC)
            if order.status == "paid" or (order.is_deleted and not isinstance(paid, VerifiedPayment)):
                return
            # A signed payment fetched before the lock must beat a concurrent close.
            if order.status == "closed" and not isinstance(paid, VerifiedPayment):
                return
            if not isinstance(paid, VerifiedPayment) and order.next_query_at and (order.next_query_at.replace(tzinfo=UTC) if order.next_query_at.tzinfo is None else order.next_query_at) > now:
                return
            attempt = PaymentAttemptModel(app_id=app_id, order_id=order.id, order_no=order_no, provider=provider, action="query", status="started")
            db.add(attempt)
            if not error and await apply_query_result(db, order, paid):
                attempt.status = order.status
            else:
                attempt.status = "failed" if error else "not_paid"
                attempt.error_message = "支付渠道查单请求异常" if error else None
                expires_at = order.expires_at.replace(tzinfo=UTC) if order.expires_at.tzinfo is None else order.expires_at
                if expires_at <= now or order.cancel_requested_at:
                    await close_unpaid_order(db, order)
                else:
                    PaymentOrderService._schedule_query(order, now)
            attempt.completed_at = now
    except Exception as exc:
        logger.warning("支付自动查单结果待核对: app_id={} order_no={} exception_type={}", app_id, order_no, type(exc).__name__)
        async with async_db_session() as db, db.begin():
            await lock_app(db, app_id)
            order = await db.scalar(select(PaymentOrderModel).where(PaymentOrderModel.app_id == app_id, PaymentOrderModel.id == order_id).with_for_update())
            if order and not order.is_deleted and order.status not in {"paid", "closed"}:
                db.add(
                    PaymentAttemptModel(
                        app_id=app_id,
                        order_id=order.id,
                        order_no=order.order_no,
                        provider=order.provider,
                        action="query",
                        status="failed",
                        error_message="查单结果与本地订单不一致，待人工核查",
                        completed_at=datetime.now(UTC),
                    )
                )
                PaymentOrderService._schedule_query(order, datetime.now(UTC))


async def recover_due_orders(app_id: int) -> int:
    now = datetime.now(UTC)
    async with async_db_session() as db:
        ids = list(
            await db.scalars(
                select(PaymentOrderModel.id)
                .where(
                    PaymentOrderModel.app_id == app_id,
                    PaymentOrderModel.amount_fen > 0,
                    PaymentOrderModel.provider.in_(("wechat", "alipay")),
                    PaymentOrderModel.status.in_(("created", "pending", "confirming", "failed")),
                    or_(PaymentOrderModel.next_query_at.is_(None), PaymentOrderModel.next_query_at <= now),
                    PaymentOrderModel.is_deleted == False,
                )
                .order_by(PaymentOrderModel.created_time.asc())
                .limit(20)
            )
        )
    for order_id in ids:
        await recover_order(app_id, order_id)
    # Deleted, uncertain orders retain a bounded, daily payment check without
    # recreating the discarded attempt/issue records or blocking active orders.
    async with async_db_session() as db:
        archived = list(
            await db.scalars(
                select(PaymentOrderModel.id)
                .where(PaymentOrderModel.app_id == app_id, PaymentOrderModel.is_deleted == True, PaymentOrderModel.status.not_in(("paid", "closed")), PaymentOrderModel.next_query_at <= now)
                .order_by(PaymentOrderModel.next_query_at.asc())
                .limit(5)
            )
        )
    for order_id in archived:
        await recover_archived_order(app_id, order_id)
    return len(ids) + len(archived)


async def recover_archived_order(app_id: int, order_id: int) -> None:
    async with async_db_session() as db:
        order = await db.scalar(select(PaymentOrderModel).where(PaymentOrderModel.app_id == app_id, PaymentOrderModel.id == order_id, PaymentOrderModel.is_deleted == True))
        if not order or order.status in {"paid", "closed"}:
            return
        try:
            result = await PaymentOrderService.query_provider(db, order)
        except Exception as exc:
            logger.warning("归档订单付款核验未完成: order_id={} exception_type={}", order_id, type(exc).__name__)
            result = None
    try:
        async with async_db_session() as db, db.begin():
            await lock_app(db, app_id)
            order = await db.scalar(select(PaymentOrderModel).where(PaymentOrderModel.app_id == app_id, PaymentOrderModel.id == order_id).with_for_update())
            if not order or not order.is_deleted or order.status in {"paid", "closed"}:
                return
            order.next_query_at = datetime.now(UTC) + timedelta(days=1)
            await apply_query_result(db, order, result)
    except Exception as exc:
        logger.warning("归档订单签名结果待财务核对: order_id={} exception_type={}", order_id, type(exc).__name__)
        async with async_db_session() as db, db.begin():
            await lock_app(db, app_id)
            order = await db.get(PaymentOrderModel, order_id)
            if order and order.app_id == app_id and order.is_deleted:
                order.next_query_at = datetime.now(UTC) + timedelta(days=1)
