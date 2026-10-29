from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.api.v1.module_growth.model import WithdrawalModel
from app.api.v1.module_growth.service import lock_app
from app.api.v1.module_payment.order.model import PaymentOrderModel
from app.core.exceptions import CustomException

from .common import audit, formal_order_condition
from .model import FinanceBillEntryModel, FinanceIssueModel, FinanceRefundRequestModel
from .orders import fulfilled_expression


async def refresh_issues(db, app_id: int):
    await lock_app(db, app_id)
    now = datetime.now(UTC)
    detected = {}
    specs = [
        (PaymentOrderModel, "order", "fulfillment_missing", "high", [PaymentOrderModel.paid_at.is_not(None), ~fulfilled_expression()], "支付已确认，但未找到该订单的订阅周期或积分批次"),
        (PaymentOrderModel, "order", "payment_failed", "medium", [PaymentOrderModel.status == "failed"], "支付下单失败，请核对渠道配置及下单记录"),
        (
            FinanceRefundRequestModel,
            "refund",
            "refund_unknown",
            "high",
            [FinanceRefundRequestModel.status == "unknown", FinanceRefundRequestModel.submitted_at < now - timedelta(minutes=10)],
            "退款结果尚未确认，金额保留占用，请按原退款号查单",
        ),
        (
            WithdrawalModel,
            "payout",
            "payout_unknown",
            "high",
            [WithdrawalModel.status == "unknown", WithdrawalModel.created_time < now - timedelta(minutes=10)],
            "提现结果尚未确认，资金继续冻结，请按原提现单号查单",
        ),
        (
            FinanceBillEntryModel,
            "bill_entry",
            "reconciliation_difference",
            "high",
            [FinanceBillEntryModel.match_status != "matched", FinanceBillEntryModel.resolved_at.is_(None)],
            "渠道账单与系统流水存在差异",
        ),
    ]
    for model, kind, code, severity, conditions, detail in specs:
        if model is PaymentOrderModel:
            conditions = [*conditions, formal_order_condition()]
        rows = await db.scalars(select(model).where(model.app_id == app_id, model.is_deleted == False, *conditions))
        for row in rows:
            key = f"{code}:{row.id}"
            detected[key] = {
                "kind": code,
                "severity": severity,
                "object_type": kind,
                "object_id": row.id,
                "order_no": getattr(row, "order_no", None) or getattr(row, "refund_no", None) or getattr(row, "out_bill_no", None),
                "amount_fen": getattr(row, "amount_fen", None),
                "provider": getattr(row, "provider", None),
                "detail": detail,
            }
    existing = {r.issue_key: r for r in await db.scalars(select(FinanceIssueModel).where(FinanceIssueModel.app_id == app_id))}
    for key, values in detected.items():
        row = existing.get(key)
        if not row:
            row = FinanceIssueModel(app_id=app_id, issue_key=key, status="open", last_seen_at=now, **values)
            db.add(row)
        else:
            row.last_seen_at = now
            if row.status == "resolved" and row.kind != "payment_failed":
                row.status, row.resolved_at = "open", None
    for key, row in existing.items():
        if key not in detected and row.status != "resolved":
            row.status, row.resolved_at, row.resolution = "resolved", now, "原业务状态已恢复，系统核验关闭"
            audit(db, app_id, "issue", row.id, "auto_resolve", None, row.resolution)
    await db.flush()
    return len(detected)


async def issue_action(db, app_id, issue_id, operator, data):
    await lock_app(db, app_id)
    row = await db.scalar(select(FinanceIssueModel).where(FinanceIssueModel.app_id == app_id, FinanceIssueModel.id == issue_id))
    if not row:
        raise CustomException(msg="异常记录不存在", status_code=404)
    before = row.status
    if data.action == "claim":
        if row.status == "resolved":
            raise CustomException(msg="该异常已恢复", status_code=409)
        row.status, row.assigned_to = "processing", operator
    elif data.action == "resolve":
        await refresh_issues(db, app_id)
        if row.kind == "payment_failed":
            # A terminal failed checkout cannot turn into a successful order. Its
            # investigation may be closed with an audited explanation; a new failed
            # checkout has a different issue key and is still detected.
            row.status, row.resolved_at = "resolved", datetime.now(UTC)
        if row.status != "resolved":
            raise CustomException(msg="原业务异常仍存在，请先查单或处理差异后再核验关闭", status_code=409)
    else:
        row.status, row.resolved_at = "open", None
    row.resolution = data.reason
    audit(db, app_id, "issue", row.id, data.action, operator, data.reason, {"status": before}, {"status": row.status})
    await db.flush()
    return row
