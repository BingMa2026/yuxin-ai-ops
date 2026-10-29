from datetime import UTC, datetime

from sqlalchemy import inspect, or_, select

from app.api.v1.module_client.app.model import ClientAppModel
from app.api.v1.module_payment.order.recovery import recover_due_orders
from app.core.database import async_db_session
from app.core.logger import logger

from .bills import dispatch_bill, schedule_daily_bills
from .issues import refresh_issues
from .model import FinanceBillModel, FinanceRefundRequestModel
from .refunds import dispatch_refund
from .repairs import repair_due_differences


async def run_finance_maintenance():
    async with async_db_session() as db:
        connection = await db.connection()
        ready = await connection.run_sync(lambda conn: inspect(conn).has_table("finance_refund_request"))
        if not ready:
            # An old schema may still be present during a rolling release.
            return
        scopes = list(await db.scalars(select(ClientAppModel.id).where(ClientAppModel.is_deleted == False)))
    for app_id in scopes:
        try:
            await recover_due_orders(app_id)
        except Exception:
            logger.exception("支付订单自动补查失败: app_id={}", app_id)
        try:
            async with async_db_session() as db, db.begin():
                await schedule_daily_bills(db, app_id)
        except Exception:
            logger.exception("自动创建对账任务失败: app_id={}", app_id)
        for model, states, dispatch in ((FinanceRefundRequestModel, ("queued", "processing", "unknown"), dispatch_refund), (FinanceBillModel, ("queued", "downloading"), dispatch_bill)):
            async with async_db_session() as db:
                ids = list(
                    await db.scalars(
                        select(model.id)
                        .where(model.app_id == app_id, model.status.in_(states), or_(model.next_attempt_at.is_(None), model.next_attempt_at <= datetime.now(UTC)))
                        .order_by(model.id)
                        .limit(50)
                    )
                )
            for row_id in ids:
                try:
                    await dispatch(app_id, row_id)
                except Exception:
                    logger.exception("财务任务失败: app_id={} type={} id={}", app_id, model.__tablename__, row_id)
        try:
            await repair_due_differences(app_id)
        except Exception:
            logger.exception("支付对账自动修复失败: app_id={}", app_id)
        try:
            async with async_db_session() as db, db.begin():
                await refresh_issues(db, app_id)
        except Exception:
            logger.exception("财务异常核验失败: app_id={}", app_id)
