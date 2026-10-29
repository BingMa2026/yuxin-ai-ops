from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Security
from fastapi import Query as QueryParams
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.module_payment.order.controller import cancellation_response
from app.api.v1.module_payment.order.schema import PaymentOrderOut
from app.api.v1.module_payment.order.service import PaymentOrderService
from app.common.response import ErrorResponse, ResponseSchema, SuccessResponse
from app.core.base_schema import AuthSchema
from app.core.client_dependencies import get_current_client_user
from app.core.dependencies import AuthPermission, db_getter
from app.core.exceptions import CustomException
from app.core.router_class import OperationLogRoute

from . import bills, channels, issues, orders, overview, records, refunds
from .common import audit, csv_chunk, require_scope
from .deletion import delete_unpaid_order
from .schema import (
    BillBatchCreate,
    BillCreate,
    BillEntryOut,
    BillOut,
    ChannelOut,
    ControlUpdate,
    FinanceQuery,
    IssueAction,
    IssueOut,
    OrderPage,
    OverviewOut,
    OverviewQuery,
    PageOut,
    PayoutOut,
    Provider,
    ReasonIn,
    RefundCreate,
    RefundLedgerOut,
    RefundListOut,
    RefundOut,
    RefundPreviewOut,
    RefundReview,
    RefundSync,
)

finance_router = APIRouter(prefix="/finance", tags=["财务运营"], route_class=OperationLogRoute)
finance_client_router = APIRouter(prefix="/client/finance", tags=["客户端交易记录"])
DB = Annotated[AsyncSession, Depends(db_getter)]
Query = Annotated[FinanceQuery, QueryParams()]
Client = Annotated[AuthSchema, Depends(get_current_client_user)]
OverviewRead = Annotated[AuthSchema, Security(AuthPermission(["workspace:finance:overview:list"]))]
OrderRead = Annotated[AuthSchema, Security(AuthPermission(["workspace:finance:order:list"]))]
OrderWrite = Annotated[AuthSchema, Security(AuthPermission(["workspace:finance:order:query"]))]
OrderExport = Annotated[AuthSchema, Security(AuthPermission(["workspace:finance:order:export"]))]
RefundRead = Annotated[AuthSchema, Security(AuthPermission(["workspace:finance:refund:list"]))]
RefundWrite = Annotated[AuthSchema, Security(AuthPermission(["workspace:finance:refund:create"]))]
RefundReviewAuth = Annotated[AuthSchema, Security(AuthPermission(["workspace:finance:refund:review"]))]
BillRead = Annotated[AuthSchema, Security(AuthPermission(["workspace:finance:bill:list"]))]
BillWrite = Annotated[AuthSchema, Security(AuthPermission(["workspace:finance:bill:manage"]))]
IssueRead = Annotated[AuthSchema, Security(AuthPermission(["workspace:finance:issue:list"]))]
IssueWrite = Annotated[AuthSchema, Security(AuthPermission(["workspace:finance:issue:manage"]))]
ChannelRead = Annotated[AuthSchema, Security(AuthPermission(["module_payment:channel:list"]))]
ChannelWrite = Annotated[AuthSchema, Security(AuthPermission(["workspace:finance:channel:configure"]))]
PayoutRead = Annotated[AuthSchema, Security(AuthPermission(["workspace:finance:payout:list"]))]


def respond(data, msg="操作成功"):
    return SuccessResponse(data=jsonable_encoder(data), msg=msg)


@finance_router.get("/overview", response_model=ResponseSchema[OverviewOut])
async def get_overview(auth: OverviewRead, db: DB, q: Annotated[OverviewQuery, QueryParams()]):
    return respond(OverviewOut.model_validate(await overview.overview(db, require_scope(auth), q.start_date, q.end_date)))


@finance_router.get("/orders", response_model=ResponseSchema[OrderPage])
async def get_orders(auth: OrderRead, db: DB, q: Query):
    return respond(await orders.list_orders(db, require_scope(auth), q))


@finance_router.get("/orders/export")
async def export_orders(auth: OrderExport, db: DB, q: Query):
    scope = require_scope(auth)
    result = await orders.list_orders(db, scope, q.model_copy(update={"page_no": 1, "page_size": 1}))
    if result["total"] > 20000:
        raise CustomException(msg="单次导出上限为20000条，请缩小筛选范围", status_code=422)
    data = [orders.order_row(row) for row in (await db.execute(orders.order_statement(scope, q))).all()]
    body = "\ufeff" + csv_chunk(
        [["商户订单号", "渠道交易号", "用户ID", "用户名", "商品", "权益类型", "切换状态", "渠道", "订单金额(分)", "已退金额(分)", "退款占用(分)", "状态", "退款状态", "创建时间", "支付时间"]]
        + [
            [
                r.order_no,
                r.provider_trade_no,
                r.user_id,
                r.username,
                r.product_name,
                "token 自费" if r.entitlement_kind == "duration" else "含 token 费用",
                (r.mode_switch or {}).get("status", ""),
                r.provider,
                r.amount_fen,
                r.refunded_fen,
                r.refund_reserved_fen,
                r.status,
                r.refund_status,
                r.created_time.isoformat(),
                r.paid_at.isoformat() if r.paid_at else "",
            ]
            for r in data
        ]
    )
    audit(db, scope, "order", "export", "export", auth.user.id, "按当前筛选条件导出交易流水", after={"count": len(data), "filters": q.model_dump(mode="json")})
    return Response(body, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="finance-orders.csv"'})


@finance_router.get("/orders/{order_id}", response_model=ResponseSchema[dict])
async def get_order(order_id: int, auth: OrderRead, db: DB):
    return respond(await orders.order_detail(db, require_scope(auth), order_id))


@finance_router.post("/orders/{order_id}/query", response_model=ResponseSchema[dict])
async def query_order(order_id: int, data: ReasonIn, auth: OrderWrite, db: DB):
    return respond(await orders.verify_order(db, require_scope(auth), order_id, auth.user.id, data.reason))


@finance_router.post("/orders/{order_id}/close", response_model=ResponseSchema[PaymentOrderOut])
async def close_order(order_id: int, data: ReasonIn, auth: OrderWrite, db: DB):
    order = await orders.get_order(db, require_scope(auth), order_id)
    return cancellation_response(await PaymentOrderService(auth, db).cancel(order.order_no, data.reason))


@finance_router.delete("/orders/{order_id}", response_model=ResponseSchema[dict])
async def delete_order(order_id: int, data: ReasonIn, auth: OrderWrite, db: DB):
    result = await delete_unpaid_order(db, require_scope(auth), order_id, data.reason, auth.user.id)
    if not result["deleted"]:
        return ErrorResponse(data=result, msg="渠道已确认付款，订单未删除，请刷新后核对", status_code=409)
    return respond(result, "未支付订单及未入账关联数据已删除，支付核验档案已保留")


@finance_router.get("/refunds", response_model=ResponseSchema[PageOut[RefundListOut]])
async def get_refunds(auth: RefundRead, db: DB, q: Query):
    return respond(await records.list_refunds(db, require_scope(auth), q))


@finance_router.post("/refunds", response_model=ResponseSchema[RefundOut])
async def create_refund(data: RefundCreate, auth: RefundWrite, db: DB):
    return respond(RefundOut.model_validate(await refunds.create_refund(db, require_scope(auth), auth.user.id, data)), "退款申请已提交审核")


@finance_router.get("/orders/{order_id}/refund-preview", response_model=ResponseSchema[RefundPreviewOut])
async def refund_preview(order_id: int, action: Literal["retain", "terminate"], auth: RefundWrite, db: DB):
    return respond(await refunds.preview_refund(db, require_scope(auth), order_id, action))


@finance_router.get("/refunds/{request_id}/preview", response_model=ResponseSchema[RefundPreviewOut])
async def refund_review_preview(request_id: int, auth: RefundReviewAuth, db: DB):
    scope = require_scope(auth)
    row = await refunds.get_refund(db, scope, request_id)
    return respond(await refunds.preview_refund(db, scope, row.order_id, row.entitlement_action))


@finance_router.post("/refunds/synchronize", response_model=ResponseSchema[dict])
async def synchronize_refund(data: RefundSync, auth: RefundReviewAuth, db: DB):
    from app.api.v1.module_growth.refund_gateway import synchronize_refund as synchronize

    scope = require_scope(auth)
    result = await synchronize(db, scope, data.order_no.strip(), data.refund_no.strip())
    from sqlalchemy import select

    from app.api.v1.module_payment.order.model import PaymentOrderModel

    order_id = await db.scalar(select(PaymentOrderModel.id).where(PaymentOrderModel.app_id == scope, PaymentOrderModel.order_no == data.order_no.strip()))
    audit(db, scope, "order", order_id, "external_refund_verified", auth.user.id, data.reason, after={"refund_no": data.refund_no})
    return respond(result, "渠道退款已核验，款项与推广奖励已同步；原订阅和积分权益保留")


@finance_router.get("/refunds/{request_id}", response_model=ResponseSchema[dict])
async def get_refund(request_id: int, auth: RefundRead, db: DB):
    return respond(await records.refund_detail(db, require_scope(auth), request_id))


@finance_router.get("/refund-ledger", response_model=ResponseSchema[PageOut[RefundLedgerOut]])
async def get_refund_ledger(auth: RefundRead, db: DB, q: Query):
    return respond(await records.list_refund_ledger(db, require_scope(auth), q))


@finance_router.post("/refunds/{request_id}/review", response_model=ResponseSchema[RefundOut])
async def review_refund(request_id: int, data: RefundReview, auth: RefundReviewAuth, db: DB):
    return respond(RefundOut.model_validate(await refunds.review_refund(db, require_scope(auth), request_id, auth.user.id, data)))


@finance_router.post("/refunds/{request_id}/query", response_model=ResponseSchema[RefundOut])
async def query_refund(request_id: int, data: ReasonIn, auth: RefundReviewAuth, db: DB):
    from app.api.v1.module_growth.service import lock_app

    scope = require_scope(auth)
    await lock_app(db, scope)
    row = await refunds.get_refund(db, scope, request_id)
    if row.status not in ("unknown", "processing"):
        raise CustomException(msg="只有结果未明或处理中的退款可查单", status_code=409)
    row.next_attempt_at = datetime.now(UTC)
    audit(db, scope, "refund", row.id, "query_requested", auth.user.id, data.reason)
    return respond(RefundOut.model_validate(row), "已安排原退款单号查单")


@finance_router.get("/bills", response_model=ResponseSchema[PageOut[BillOut]])
async def get_bills(auth: BillRead, db: DB, q: Query):
    return respond(await records.list_bills(db, require_scope(auth), q))


@finance_router.post("/refunds/{request_id}/retry", response_model=ResponseSchema[RefundOut])
async def retry_refund(request_id: int, data: ReasonIn, auth: RefundReviewAuth, db: DB):
    from app.api.v1.module_growth.service import lock_app

    scope = require_scope(auth)
    await lock_app(db, scope)
    row = await refunds.get_refund(db, scope, request_id)
    if row.status != "unknown":
        raise CustomException(msg="仅结果未明的退款可按原单重提；已成功或明确失败的申请不能重提", status_code=409)
    row.status, row.next_attempt_at = "queued", datetime.now(UTC)
    audit(db, scope, "refund", row.id, "retry", auth.user.id, data.reason, before={"status": "unknown"}, after={"status": "queued", "refund_no": row.refund_no})
    await db.flush()
    return respond(RefundOut.model_validate(row), "已安排按原退款号与原金额重提")


@finance_router.post("/bills", response_model=ResponseSchema[BillOut])
async def request_bill(data: BillCreate, auth: BillWrite, db: DB):
    return respond(BillOut.model_validate(await bills.request_bill(db, require_scope(auth), auth.user.id, data)), "账单任务已登记")


@finance_router.post("/bills/batch", response_model=ResponseSchema[list[BillOut]])
async def request_bill_batch(data: BillBatchCreate, auth: BillWrite, db: DB):
    rows = await bills.request_bill_batch(db, require_scope(auth), auth.user.id, data)
    return respond([BillOut.model_validate(row) for row in rows], "已按日期登记对账任务，已有任务自动复用")


@finance_router.get("/bill-automation", response_model=ResponseSchema[dict])
async def bill_automation(auth: BillRead):
    from app.config.setting import settings

    require_scope(auth)
    return respond({"enabled": settings.FINANCE_AUTO_RECONCILE, "hour": settings.FINANCE_RECONCILE_HOUR, "timezone": "Asia/Shanghai"})


@finance_router.get("/bills/{bill_id}/entries", response_model=ResponseSchema[PageOut[BillEntryOut]])
async def bill_entries(bill_id: int, auth: BillRead, db: DB, q: Query):
    return respond(await records.list_entries(db, require_scope(auth), bill_id, q))


@finance_router.post("/bill-entries/{entry_id}/resolve", response_model=ResponseSchema[BillEntryOut])
async def resolve_entry(entry_id: int, data: ReasonIn, auth: BillWrite, db: DB):
    return respond(BillEntryOut.model_validate(await bills.resolve_entry(db, require_scope(auth), entry_id, auth.user.id, data.reason)))


@finance_router.get("/issues", response_model=ResponseSchema[PageOut[IssueOut]])
async def get_issues(auth: IssueRead, db: DB, q: Query):
    return respond(await records.list_issues(db, require_scope(auth), q))


@finance_router.post("/issues/refresh", response_model=ResponseSchema[dict])
async def refresh_issues(auth: IssueWrite, db: DB):
    await issues.refresh_issues(db, require_scope(auth))
    return respond({}, "已重新核验待办来源")


@finance_router.post("/issues/{issue_id}/action", response_model=ResponseSchema[IssueOut])
async def issue_action(issue_id: int, data: IssueAction, auth: IssueWrite, db: DB):
    return respond(IssueOut.model_validate(await issues.issue_action(db, require_scope(auth), issue_id, auth.user.id, data)))


@finance_router.get("/channels", response_model=ResponseSchema[list[ChannelOut]])
async def get_channels(auth: ChannelRead, db: DB):
    require_scope(auth)
    return respond([ChannelOut.model_validate(row) for row in await channels.list_channels(db, auth)])


@finance_router.put("/channels/{provider}", response_model=ResponseSchema[ChannelOut])
async def update_channel(provider: Provider, data: ControlUpdate, auth: ChannelWrite, db: DB):
    require_scope(auth)
    return respond(ChannelOut.model_validate(await channels.update_channel(db, auth, provider, data)))


@finance_router.get("/withdrawals", response_model=ResponseSchema[PageOut[PayoutOut]])
async def get_withdrawals(auth: PayoutRead, db: DB, q: Query):
    return respond(PageOut[PayoutOut].model_validate(await records.list_payouts(db, require_scope(auth), q)))


@finance_client_router.get("/orders", response_model=ResponseSchema[OrderPage])
async def client_orders(auth: Client, db: DB, q: Query):
    return respond(await orders.list_orders(db, require_scope(auth), q.model_copy(update={"user_id": auth.user.id})))


@finance_client_router.get("/orders/{order_id}", response_model=ResponseSchema[dict])
async def client_order(order_id: int, auth: Client, db: DB):
    scope = require_scope(auth)
    row = await orders.get_order(db, scope, order_id)
    if row.user_id != auth.user.id:
        raise CustomException(msg="订单不存在", status_code=404)
    detail = await orders.order_detail(db, scope, order_id)
    from sqlalchemy import select

    from .model import FinanceRefundRequestModel

    requests = list(
        await db.scalars(
            select(FinanceRefundRequestModel)
            .where(FinanceRefundRequestModel.app_id == scope, FinanceRefundRequestModel.order_id == order_id, FinanceRefundRequestModel.user_id == auth.user.id)
            .order_by(FinanceRefundRequestModel.id.desc())
        )
    )
    return respond(
        {
            **{key: detail[key] for key in ("order", "cycles", "credits")},
            "refunds": [{key: r[key] for key in ("id", "refund_no", "amount_fen", "status", "refunded_at")} for r in detail["refunds"]],
            "refund_requests": [
                {
                    "id": r.id,
                    "refund_no": r.refund_no,
                    "amount_fen": r.amount_fen,
                    "status": r.status,
                    "entitlement_action": r.entitlement_action,
                    "created_time": r.created_time,
                    "completed_at": r.completed_at,
                }
                for r in requests
            ],
        }
    )
