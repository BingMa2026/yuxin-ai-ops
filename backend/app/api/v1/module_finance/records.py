from sqlalchemy import and_, func, or_, select

from app.api.v1.module_client.user.model import ClientUserModel
from app.api.v1.module_growth.model import PayoutAttemptModel, WithdrawalModel
from app.api.v1.module_payment.order.model import PaymentOrderModel, PaymentRefundModel
from app.core.exceptions import CustomException

from .common import date_conditions, fields, paginate
from .model import FinanceAuditModel, FinanceBillEntryModel, FinanceBillModel, FinanceIssueModel, FinanceRefundRequestModel
from .refunds import get_refund
from .schema import BillEntryOut, BillOut, IssueOut, RefundLedgerOut, RefundListOut, RefundOut


def filtered(stmt, model, q, keywords=(), date_column=None):
    if q.status == "unresolved" and model is FinanceIssueModel:
        stmt = stmt.where(model.status.in_(("open", "processing")))
    elif q.status == "inflight" and model is WithdrawalModel:
        stmt = stmt.where(model.status.in_(("queued", "unknown", "processing", "confirming")))
    elif q.status:
        stmt = stmt.where(getattr(model, "status", getattr(model, "match_status", None)) == q.status)
    if q.provider and hasattr(model, "provider"):
        stmt = stmt.where(model.provider == q.provider)
    if q.user_id and hasattr(model, "user_id"):
        stmt = stmt.where(model.user_id == q.user_id)
    if q.keyword.strip() and keywords:
        term = "%" + q.keyword.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        stmt = stmt.where(or_(*(c.ilike(term, escape="\\") for c in keywords)))
    if hasattr(model, "amount_fen"):
        if q.min_amount_fen is not None:
            stmt = stmt.where(model.amount_fen >= q.min_amount_fen)
        if q.max_amount_fen is not None:
            stmt = stmt.where(model.amount_fen <= q.max_amount_fen)
    return stmt.where(*date_conditions(date_column if date_column is not None else model.created_time, q)).order_by(model.id.desc())


async def list_refunds(db, app_id, q):
    m = FinanceRefundRequestModel
    stmt = (
        select(m, PaymentOrderModel.order_no, ClientUserModel.username, ClientUserModel.display_name)
        .join(PaymentOrderModel, and_(PaymentOrderModel.id == m.order_id, PaymentOrderModel.app_id == app_id))
        .join(ClientUserModel, and_(ClientUserModel.id == m.user_id, ClientUserModel.app_id == app_id))
        .where(m.app_id == app_id)
    )
    stmt = filtered(stmt, m, q, (m.refund_no, m.provider_refund_no, PaymentOrderModel.order_no, ClientUserModel.username, ClientUserModel.display_name))
    result = await paginate(db, stmt, q, lambda r: RefundListOut(**RefundOut.model_validate(r[0]).model_dump(), order_no=r[1], username=r[2], display_name=r[3] or ""))
    source = stmt.order_by(None).subquery()
    result["summary"] = {"amount_fen": int(await db.scalar(select(func.coalesce(func.sum(source.c.amount_fen), 0))) or 0)}
    return result


async def refund_detail(db, app_id, request_id):
    row = await get_refund(db, app_id, request_id)
    return {"refund": RefundOut.model_validate(row), "audits": await audit_records(db, app_id, "refund", request_id)}


async def list_refund_ledger(db, app_id, q):
    q = q.model_copy(update={"status": None})
    m = PaymentRefundModel
    stmt = (
        select(m, PaymentOrderModel.order_no, ClientUserModel.username, ClientUserModel.display_name)
        .join(PaymentOrderModel, and_(PaymentOrderModel.id == m.order_id, PaymentOrderModel.app_id == app_id))
        .join(ClientUserModel, and_(ClientUserModel.id == m.user_id, ClientUserModel.app_id == app_id))
        .where(m.app_id == app_id, m.status == "succeeded")
    )
    stmt = filtered(stmt, m, q, (m.refund_no, m.provider_refund_no, PaymentOrderModel.order_no, ClientUserModel.username, ClientUserModel.display_name), m.refunded_at)

    def output(r):
        return RefundLedgerOut(
            **fields(r[0], ("id", "order_id", "user_id", "provider", "provider_refund_no", "refund_no", "amount_fen", "refunded_at", "reason", "status")),
            order_no=r[1],
            username=r[2],
            display_name=r[3] or "",
        )

    result = await paginate(db, stmt, q, output)
    source = stmt.order_by(None).subquery()
    result["summary"] = {"amount_fen": int(await db.scalar(select(func.coalesce(func.sum(source.c.amount_fen), 0))) or 0)}
    return result


async def audit_records(db, app_id, kind, object_id):
    rows = await db.scalars(
        select(FinanceAuditModel)
        .where(FinanceAuditModel.app_id == app_id, FinanceAuditModel.object_type == kind, FinanceAuditModel.object_id == str(object_id))
        .order_by(FinanceAuditModel.id.desc())
        .limit(200)
    )
    return [fields(row, ("id", "action", "operator_id", "reason", "before", "after", "created_time")) for row in rows]


async def list_bills(db, app_id, q):
    stmt = select(FinanceBillModel).where(FinanceBillModel.app_id == app_id)
    # Bill dates are calendar dates rather than timestamps.
    if q.start_date:
        stmt = stmt.where(FinanceBillModel.bill_date >= q.start_date)
    if q.end_date:
        stmt = stmt.where(FinanceBillModel.bill_date <= q.end_date)
    stmt = filtered(stmt, FinanceBillModel, q.model_copy(update={"start_date": None, "end_date": None}))
    return await paginate(db, stmt, q, lambda r: BillOut.model_validate(r[0]))


async def list_entries(db, app_id, bill_id, q):
    bill = await db.scalar(select(FinanceBillModel).where(FinanceBillModel.app_id == app_id, FinanceBillModel.id == bill_id))
    if not bill:
        raise CustomException(msg="账单不存在", status_code=404)
    stmt = filtered(
        select(FinanceBillEntryModel).where(FinanceBillEntryModel.app_id == app_id, FinanceBillEntryModel.bill_id == bill_id),
        FinanceBillEntryModel,
        q,
        (FinanceBillEntryModel.order_no, FinanceBillEntryModel.provider_trade_no, FinanceBillEntryModel.refund_no),
    )
    return await paginate(db, stmt, q, lambda r: BillEntryOut.model_validate(r[0]))


async def list_issues(db, app_id, q):
    stmt = filtered(select(FinanceIssueModel).where(FinanceIssueModel.app_id == app_id), FinanceIssueModel, q, (FinanceIssueModel.order_no, FinanceIssueModel.detail))
    return await paginate(db, stmt, q, lambda r: IssueOut.model_validate(r[0]))


async def list_payouts(db, app_id, q):
    m = WithdrawalModel
    attempts = (
        select(func.count())
        .select_from(PayoutAttemptModel)
        .where(PayoutAttemptModel.app_id == app_id, PayoutAttemptModel.withdrawal_id == m.id, PayoutAttemptModel.action.in_(("submit", "query")))
        .correlate(m)
        .scalar_subquery()
    )
    reviewed = (
        select(func.max(PayoutAttemptModel.created_time))
        .where(PayoutAttemptModel.app_id == app_id, PayoutAttemptModel.withdrawal_id == m.id, PayoutAttemptModel.action == "review")
        .correlate(m)
        .scalar_subquery()
    )
    stmt = (
        select(m, ClientUserModel.username, ClientUserModel.display_name, attempts, reviewed)
        .join(ClientUserModel, and_(ClientUserModel.id == m.user_id, ClientUserModel.app_id == app_id))
        .where(m.app_id == app_id)
    )
    stmt = filtered(stmt, m, q, (m.out_bill_no, ClientUserModel.username, ClientUserModel.display_name))

    def output(row):
        w, username, name, count, reviewed_at = row
        return {
            **fields(w, ("id", "out_bill_no", "user_id", "provider", "amount_fen", "status", "reason", "created_time", "completed_at", "next_attempt_at", "provider_bill_no")),
            "attempt_count": count,
            "reviewed_at": reviewed_at,
            "username": username,
            "display_name": name or "",
            "payee": w.policy_snapshot.get("masked_payee", "—"),
        }

    result = await paginate(db, stmt, q, output)
    source = stmt.order_by(None).subquery()
    result["summary"] = {"amount_fen": int(await db.scalar(select(func.coalesce(func.sum(source.c.amount_fen), 0))) or 0)}
    return result
