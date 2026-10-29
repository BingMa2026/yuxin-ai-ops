import csv
import io
from datetime import UTC, datetime, time, timedelta
from math import ceil
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, select

from app.api.v1.module_payment.order.model import PaymentOrderModel
from app.core.exceptions import CustomException

from .model import FinanceAuditModel

BUSINESS_TZ = ZoneInfo("Asia/Shanghai")


def formal_order_condition():
    """Exclude the explicitly identified legacy development seed, without changing its ledger.

    These three markers are written together by seed_dev_operations_demo.py.
    A free order is still a formal order; it simply has no channel receipt.
    """
    return ~and_(
        PaymentOrderModel.idempotency_key.startswith("dev-demo-order-"),
        PaymentOrderModel.order_no.startswith("DEV"),
        func.coalesce(PaymentOrderModel.provider_trade_no, "").startswith("DEVTRADE"),
    )


def channel_receipt_conditions():
    return [formal_order_condition(), PaymentOrderModel.amount_fen > 0, PaymentOrderModel.status == "paid"]


def require_scope(auth) -> int:
    if not auth.app_id:
        raise CustomException(msg="请先选择客户端", status_code=409)
    return auth.app_id


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def date_conditions(column, query):
    conditions = []
    if query.start_date:
        conditions.append(column >= datetime.combine(query.start_date, time.min, BUSINESS_TZ).astimezone(UTC))
    if query.end_date:
        conditions.append(column < datetime.combine(query.end_date + timedelta(days=1), time.min, BUSINESS_TZ).astimezone(UTC))
    return conditions


def audit(db, app_id: int, kind: str, object_id: int | str, action: str, operator: int | None, reason: str, before=None, after=None):
    db.add(FinanceAuditModel(app_id=app_id, object_type=kind, object_id=str(object_id), action=action, operator_id=operator, reason=reason, before=before or {}, after=after or {}))


def fields(row, names):
    return {name: getattr(row, name) for name in names}


async def paginate(db, stmt, query, mapper):
    total = int(await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)
    rows = (await db.execute(stmt.offset((query.page_no - 1) * query.page_size).limit(query.page_size))).all()
    return {
        "items": [mapper(row) for row in rows],
        "total": total,
        "page_no": query.page_no,
        "page_size": query.page_size,
        "has_next": query.page_no * query.page_size < total,
        "total_pages": ceil(total / query.page_size),
    }


def csv_chunk(rows) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    for row in rows:
        # Prevent spreadsheet formulas from untrusted names, remarks and identifiers.
        writer.writerow([("'" + str(v)) if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else ("" if v is None else v) for v in row])
    return buffer.getvalue()
