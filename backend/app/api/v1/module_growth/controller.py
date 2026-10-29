from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response, Security
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.base_schema import AuthSchema, PaginationQueryParam
from app.core.client_dependencies import get_current_client_user
from app.core.dependencies import AuthPermission, db_getter
from app.core.exceptions import CustomException
from app.core.router_class import OperationLogRoute

from .gift_service import GiftService
from .grade_service import GradeService
from .model import GrowthEventModel, GrowthTaskModel, PayoutAccountModel, PayoutAttemptModel, ReferralModel, RewardModel, TaskEvidenceModel, WithdrawalModel
from .payout_service import PayoutService, decrypt_payee
from .referral_service import ReferralService, public_invitation
from .reward_service import RewardService, cash_account
from .schema import (
    AlipayAccountIn,
    BindInviteIn,
    PasswordIn,
    PublishIn,
    RefundSyncIn,
    ReviewIn,
    RuleDraftIn,
    TaskClaimIn,
    TaskCompleteIn,
    TransferIn,
    WechatAuthorizeIn,
    WechatExchangeIn,
    WithdrawalIn,
)
from .service import PolicyService, client_user, lock_app, public_row
from .task_service import TaskService
from .wechat_service import WechatPayoutService

growth_admin_router = APIRouter(prefix="/growth", tags=["等级与激励规则"], route_class=OperationLogRoute)
growth_client_router = APIRouter(prefix="/client/growth", tags=["客户端邀请与奖励"])
growth_public_router = APIRouter(prefix="/public/growth", tags=["公开邀请"])
DB = Annotated[AsyncSession, Depends(db_getter)]
Client = Annotated[AuthSchema, Depends(get_current_client_user)]
Read = Annotated[AuthSchema, Security(AuthPermission(["workspace:rule:level:list", "workspace:rule:promotion:list", "workspace:rule:rights:list", "workspace:rule:incentive:list"]))]
Write = Annotated[AuthSchema, Security(AuthPermission(["workspace:rule:manage"]))]
UserRead = Annotated[AuthSchema, Security(AuthPermission(["workspace:user:management:list"]))]
IncentiveRead = Annotated[AuthSchema, Security(AuthPermission(["workspace:rule:incentive:list"]))]
GradeRead = Annotated[AuthSchema, Security(AuthPermission(["workspace:rule:level:list", "workspace:rule:promotion:list"]))]
UsageRead = Annotated[AuthSchema, Security(AuthPermission(["workspace:rule:level:list"]))]
FinanceRead = Annotated[AuthSchema, Security(AuthPermission(["workspace:finance:payout:list"]))]
FinanceWrite = Annotated[AuthSchema, Security(AuthPermission(["workspace:finance:payout:review"]))]
Page = Annotated[PaginationQueryParam, Depends()]


async def sensitive_client(request: Request, auth: Client) -> AuthSchema:
    from .security import sensitive_rate_limit

    await sensitive_rate_limit(getattr(request.app.state, "redis", None), app_id(auth), auth.user.id)
    return auth


SensitiveClient = Annotated[AuthSchema, Depends(sensitive_client)]


def app_id(auth: AuthSchema) -> int:
    if not auth.app_id:
        raise CustomException(msg="请先选择客户端", status_code=409)
    return auth.app_id


@growth_admin_router.get("/rules", response_model=ResponseSchema[list[dict]])
async def rules(auth: Read, db: DB, kind: Literal["usage", "promotion", "rights", "incentive"] | None = None):
    permissions = {"usage": "level", "promotion": "promotion", "rights": "rights", "incentive": "incentive"}
    allowed = {k for k, v in permissions.items() if auth.user.is_superuser or f"workspace:rule:{v}:list" in auth.permissions}
    if kind and kind not in allowed:
        raise CustomException(msg="无权查看该类规则", status_code=403)
    rows = await PolicyService(db, app_id(auth)).list(kind)
    return SuccessResponse(data=[r for r in rows if r["kind"] in allowed])


@growth_admin_router.post("/rules/defaults", response_model=ResponseSchema[list[dict]])
async def defaults(auth: Write, db: DB):
    return SuccessResponse(data=await PolicyService(db, app_id(auth), auth.user.id).seed(), msg="初始草案已建立，尚未发布")


@growth_admin_router.post("/rules", response_model=ResponseSchema[dict])
async def save_rule(auth: Write, db: DB, data: RuleDraftIn):
    return SuccessResponse(data=await PolicyService(db, app_id(auth), auth.user.id).save(data), msg="已保存为新草稿")


@growth_admin_router.post("/rules/save-and-publish", response_model=ResponseSchema[dict])
async def save_and_publish_rule(auth: Write, db: DB, data: RuleDraftIn):
    return SuccessResponse(data=await PolicyService(db, app_id(auth), auth.user.id).save_and_publish(data), msg="规则已发布")


@growth_admin_router.post("/rules/{rule_id}/publish", response_model=ResponseSchema[dict])
async def publish_rule(auth: Write, db: DB, rule_id: int, data: PublishIn):
    return SuccessResponse(data=await PolicyService(db, app_id(auth), auth.user.id).publish(rule_id, data.effective_at), msg="规则已发布")


@growth_admin_router.post("/rules/{rule_id}/stop", response_model=ResponseSchema[dict])
async def stop_rule(auth: Write, db: DB, rule_id: int):
    return SuccessResponse(data=await PolicyService(db, app_id(auth), auth.user.id).stop(rule_id), msg="规则已停用")


@growth_admin_router.get("/legacy-references", response_model=ResponseSchema[list[dict]])
async def legacy_references(auth: UsageRead, db: DB):
    return SuccessResponse(data=await PolicyService(db, app_id(auth)).legacy_references())


@growth_admin_router.get("/rules/{rule_id}/preview", response_model=ResponseSchema[dict])
async def preview_rule(auth: GradeRead, db: DB, rule_id: int, page: Page):
    row = await PolicyService(db, app_id(auth)).get(rule_id)
    permission = "level" if row.kind == "usage" else "promotion"
    if row.kind not in {"usage", "promotion"} or (not auth.user.is_superuser and f"workspace:rule:{permission}:list" not in auth.permissions):
        raise CustomException(msg="无权查看该类评估", status_code=403)
    return SuccessResponse(data=await GradeService(db, app_id(auth)).preview(rule_id, page.page_no, page.page_size))


@growth_admin_router.post("/rules/{rule_id}/evaluate", response_model=ResponseSchema[dict])
async def evaluate_rule(auth: Write, db: DB, rule_id: int):
    service = GradeService(db, app_id(auth))
    count, page = 0, 1
    while True:
        result = await service.preview(rule_id, page, 100, persist=True)
        count += len(result["items"])
        if not result["has_next"]:
            break
        page += 1
    return SuccessResponse(data={"evaluated": count}, msg="等级评估已完成")


@growth_client_router.get("/me", response_model=ResponseSchema[dict])
async def client_growth(auth: Client, db: DB):
    result = await ReferralService(db, app_id(auth)).summary(auth.user.id)
    cash = await cash_account(db, app_id(auth), auth.user.id)
    result["cash"] = public_row(cash, ("available", "frozen", "debt"))
    pending = (
        await db.execute(
            select(RewardModel.asset, func.sum(RewardModel.amount))
            .where(RewardModel.app_id == auth.app_id, RewardModel.user_id == auth.user.id, RewardModel.status.in_(["review", "pending"]))
            .group_by(RewardModel.asset)
        )
    ).all()
    result["pending_rewards"] = dict(pending)
    return SuccessResponse(data=result)


@growth_client_router.post("/bind", response_model=ResponseSchema[dict])
async def bind_referral(auth: Client, db: DB, data: BindInviteIn):
    return SuccessResponse(data=await ReferralService(db, app_id(auth)).bind(auth.user.id, data.code), msg="邀请关系已绑定")


@growth_client_router.get("/referrals", response_model=ResponseSchema[dict])
async def my_referrals(auth: Client, db: DB, page: Page):
    return SuccessResponse(data=await ReferralService(db, app_id(auth)).records(auth.user.id, page.page_no, page.page_size))


@growth_public_router.get("/invitations/{code}", response_model=ResponseSchema[dict])
async def invitation(code: str, db: DB):
    return SuccessResponse(data=await public_invitation(db, code))


@growth_admin_router.get("/users/{user_id}", response_model=ResponseSchema[dict])
async def user_growth(user_id: int, auth: UserRead, db: DB):
    await client_user(db, app_id(auth), user_id)
    return SuccessResponse(data=await ReferralService(db, app_id(auth)).summary(user_id))


@growth_admin_router.get("/users/{user_id}/referrals", response_model=ResponseSchema[dict])
async def user_referrals(user_id: int, auth: UserRead, db: DB, page: Page):
    await client_user(db, app_id(auth), user_id)
    return SuccessResponse(data=await ReferralService(db, app_id(auth)).records(user_id, page.page_no, page.page_size, admin=True))


@growth_admin_router.post("/referrals/{referral_id}/review", response_model=ResponseSchema[dict])
async def review_referral(referral_id: int, data: ReviewIn, auth: Write, db: DB):
    await lock_app(db, app_id(auth))
    relation = await db.scalar(select(ReferralModel).where(ReferralModel.id == referral_id, ReferralModel.app_id == auth.app_id))
    if not relation:
        raise CustomException(msg="邀请关系不存在", status_code=404)
    relation.risk_status, relation.risk_reason = ("passed" if data.approved else "rejected"), data.reason
    await db.flush()
    return SuccessResponse(data={"id": relation.id, "risk_status": relation.risk_status})


async def page_records(db: AsyncSession, model, scope: int, page: PaginationQueryParam, fields: tuple[str, ...], user_id: int | None = None) -> dict:
    stmt = select(model).where(model.app_id == scope)
    if user_id is not None:
        stmt = stmt.where(model.user_id == user_id)
    total = int(await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = (await db.scalars(stmt.order_by(model.id.desc()).offset((page.page_no - 1) * page.page_size).limit(page.page_size))).all()
    return {"page_no": page.page_no, "page_size": page.page_size, "total": total, "has_next": page.page_no * page.page_size < total, "items": [public_row(r, fields) for r in rows]}


REWARD_FIELDS = ("id", "user_id", "event_id", "policy_id", "asset", "amount", "reversed_amount", "status", "reason", "release_at", "posted_at", "created_time", "snapshot")


@growth_admin_router.get("/rewards", response_model=ResponseSchema[dict])
async def rewards(auth: IncentiveRead, db: DB, page: Page):
    return SuccessResponse(data=await page_records(db, RewardModel, app_id(auth), page, REWARD_FIELDS))


@growth_client_router.get("/rewards", response_model=ResponseSchema[dict])
async def my_rewards(auth: Client, db: DB, page: Page):
    result = await page_records(db, RewardModel, app_id(auth), page, REWARD_FIELDS, auth.user.id)
    for item in result["items"]:
        item["name"] = item.pop("snapshot")["name"]
    return SuccessResponse(data=result)


@growth_admin_router.post("/rewards/{reward_id}/review", response_model=ResponseSchema[dict])
async def review_reward(reward_id: int, data: ReviewIn, auth: Write, db: DB):
    reward = await RewardService(db, app_id(auth)).review(reward_id, data.approved, data.reason)
    return SuccessResponse(data=public_row(reward, REWARD_FIELDS), msg="奖励审核已处理")


@growth_admin_router.get("/events", response_model=ResponseSchema[dict])
async def events(auth: IncentiveRead, db: DB, page: Page):
    return SuccessResponse(data=await page_records(db, GrowthEventModel, app_id(auth), page, ("id", "user_id", "kind", "event_key", "status", "reason", "occurred_at", "facts")))


TASK_FIELDS = ("id", "user_id", "local_task_id", "project_ref", "kind", "status", "artifact_ref", "completed_at", "verified_at", "review_reason")


@growth_client_router.get("/gifts/summary", response_model=ResponseSchema[dict])
async def gift_summary(auth: Client, db: DB):
    return SuccessResponse(data=await GiftService(db, app_id(auth)).summary(auth.user.id))


@growth_client_router.post("/gifts", response_model=ResponseSchema[dict])
async def gift(data: TransferIn, auth: SensitiveClient, db: DB):
    result = await GiftService(db, app_id(auth)).transfer(auth.user.id, data)
    return SuccessResponse(data=public_row(result, ("id", "amount", "recipient_id", "created_time")), msg="积分已转赠")


@growth_client_router.get("/gifts/recipient/{code}", response_model=ResponseSchema[dict])
async def gift_recipient(code: str, auth: Client, db: DB):
    profile = await ReferralService(db, app_id(auth)).resolve(code)
    user = await client_user(db, auth.app_id, profile.user_id)
    return SuccessResponse(data={"code": profile.invite_code, "name": (user.display_name or user.username)[:1] + "***"})


@growth_client_router.post("/tasks", response_model=ResponseSchema[dict])
async def claim_task(data: TaskClaimIn, auth: Client, db: DB):
    return SuccessResponse(data=public_row(await TaskService(db, app_id(auth)).claim(auth.user.id, data), TASK_FIELDS))


@growth_client_router.post("/tasks/{task_id}/complete", response_model=ResponseSchema[dict])
async def complete_task(task_id: int, data: TaskCompleteIn, auth: Client, db: DB):
    return SuccessResponse(data=public_row(await TaskService(db, app_id(auth)).complete(task_id, auth.user.id, data), TASK_FIELDS))


@growth_admin_router.get("/tasks", response_model=ResponseSchema[dict])
async def tasks(auth: IncentiveRead, db: DB, page: Page):
    result = await page_records(db, GrowthTaskModel, app_id(auth), page, TASK_FIELDS)
    ids = [r["id"] for r in result["items"]]
    counts = dict(
        (
            await db.execute(
                select(TaskEvidenceModel.task_id, func.count())
                .where(TaskEvidenceModel.app_id == auth.app_id, TaskEvidenceModel.task_id.in_(ids), TaskEvidenceModel.status == "succeeded", TaskEvidenceModel.output_tokens > 0)
                .group_by(TaskEvidenceModel.task_id)
            )
        ).all()
    )
    for item in result["items"]:
        item["verified_model_calls"] = counts.get(item["id"], 0)
    return SuccessResponse(data=result)


@growth_admin_router.post("/tasks/{task_id}/review", response_model=ResponseSchema[dict])
async def review_task(task_id: int, data: ReviewIn, auth: Write, db: DB):
    return SuccessResponse(data=public_row(await TaskService(db, app_id(auth)).review(task_id, data.approved, data.reason), TASK_FIELDS))


WITHDRAWAL_FIELDS = ("id", "user_id", "provider", "amount_fen", "status", "out_bill_no", "reason", "created_time", "completed_at", "provider_bill_no")
ACCOUNT_FIELDS = ("id", "provider", "masked_label", "status")


@growth_client_router.get("/payout/capabilities", response_model=ResponseSchema[list[dict]])
async def payout_capabilities(auth: Client, db: DB):
    rules = await PolicyService(db, app_id(auth)).active("rights")
    policy = rules[0].config if rules else {}
    from app.api.v1.module_finance.channels import payout_capabilities as scoped_capabilities

    result = await scoped_capabilities(db, app_id(auth))
    for row in result:
        if not policy.get("withdrawal_enabled"):
            row["available"], row["reason"] = False, "平台尚未开放提现"
        row["minimum"] = policy.get("withdrawal_min_fen", 10000)
        row["maximum"] = policy.get("withdrawal_max_fen", 100000)
    return SuccessResponse(data=result)


@growth_admin_router.get("/payout/capabilities", response_model=ResponseSchema[list[dict]])
async def admin_payout_capabilities(auth: FinanceRead, db: DB):
    from app.api.v1.module_finance.channels import payout_capabilities as scoped_capabilities

    return SuccessResponse(data=await scoped_capabilities(db, app_id(auth)))


@growth_client_router.get("/payout/accounts", response_model=ResponseSchema[list[dict]])
async def payout_accounts(auth: Client, db: DB):
    rows = await db.scalars(select(PayoutAccountModel).where(PayoutAccountModel.app_id == app_id(auth), PayoutAccountModel.user_id == auth.user.id))
    return SuccessResponse(data=[public_row(row, ACCOUNT_FIELDS) for row in rows])


@growth_client_router.post("/payout/accounts/alipay", response_model=ResponseSchema[dict])
async def alipay_account(data: AlipayAccountIn, auth: SensitiveClient, db: DB):
    row = await PayoutService(db, app_id(auth)).account(auth.user.id, data)
    return SuccessResponse(data=public_row(row, ACCOUNT_FIELDS), msg="收款账户已保存")


@growth_client_router.post("/withdrawals", response_model=ResponseSchema[dict])
async def withdraw(data: WithdrawalIn, auth: SensitiveClient, db: DB):
    row = await PayoutService(db, app_id(auth)).withdraw(auth.user.id, data)
    return SuccessResponse(data=public_row(row, WITHDRAWAL_FIELDS), msg="提现申请已提交，等待财务审核")


@growth_client_router.get("/withdrawals", response_model=ResponseSchema[dict])
async def my_withdrawals(auth: Client, db: DB, page: Page):
    return SuccessResponse(data=await page_records(db, WithdrawalModel, app_id(auth), page, WITHDRAWAL_FIELDS, auth.user.id))


@growth_admin_router.get("/withdrawals", response_model=ResponseSchema[dict])
async def withdrawals(auth: FinanceRead, db: DB, page: Page):
    result = await page_records(db, WithdrawalModel, app_id(auth), page, WITHDRAWAL_FIELDS + ("policy_snapshot",))
    for row in result["items"]:
        row["payee"] = row.pop("policy_snapshot").get("masked_payee", "—")
    return SuccessResponse(data=result)


@growth_admin_router.post("/withdrawals/{withdrawal_id}/review", response_model=ResponseSchema[dict])
async def review_withdrawal(withdrawal_id: int, data: ReviewIn, auth: FinanceWrite, db: DB):
    row = await PayoutService(db, app_id(auth)).review(withdrawal_id, data.approved, data.reason, auth.user.id)
    return SuccessResponse(data=public_row(row, WITHDRAWAL_FIELDS), msg="提现审核已处理")


@growth_admin_router.get("/withdrawals/{withdrawal_id}/attempts", response_model=ResponseSchema[list[dict]])
async def payout_attempts(withdrawal_id: int, auth: FinanceRead, db: DB):
    await PayoutService(db, app_id(auth)).get(withdrawal_id)
    rows = await db.scalars(
        select(PayoutAttemptModel).where(PayoutAttemptModel.app_id == auth.app_id, PayoutAttemptModel.withdrawal_id == withdrawal_id).order_by(PayoutAttemptModel.id.desc()).limit(100)
    )
    return SuccessResponse(data=[public_row(row, ("id", "action", "status", "detail", "created_time")) for row in rows])


@growth_admin_router.post("/withdrawals/{withdrawal_id}/query", response_model=ResponseSchema[dict])
async def query_payout(withdrawal_id: int, auth: FinanceWrite, db: DB):
    from datetime import UTC, datetime

    await lock_app(db, app_id(auth))
    row = await PayoutService(db, auth.app_id).get(withdrawal_id)
    if row.status not in {"unknown", "processing", "confirming"}:
        raise CustomException(msg="仅渠道处理中或结果未明的提现单可查单", status_code=409)
    row.next_attempt_at = datetime.now(UTC)
    return SuccessResponse(data={"id": row.id}, msg="已安排原商户单号查单")


@growth_client_router.post("/payout/wechat/link", response_model=ResponseSchema[dict])
async def wechat_binding_link(auth: Client, db: DB):
    return SuccessResponse(data=await WechatPayoutService(db).issue(app_id(auth), auth.user.id))


@growth_client_router.get("/payout/wechat/links/{link_id}", response_model=ResponseSchema[dict])
async def wechat_link_status(link_id: int, auth: Client, db: DB):
    return SuccessResponse(data=await WechatPayoutService(db).status(app_id(auth), auth.user.id, link_id))


@growth_client_router.post("/payout/wechat/links/{link_id}/confirm", response_model=ResponseSchema[dict])
async def wechat_confirm_binding(link_id: int, data: PasswordIn, auth: SensitiveClient, db: DB):
    account = await WechatPayoutService(db).confirm_binding(app_id(auth), auth.user.id, link_id, data.password)
    return SuccessResponse(data=public_row(account, ACCOUNT_FIELDS), msg="微信收款账户已绑定")


@growth_client_router.post("/withdrawals/{withdrawal_id}/confirmation", response_model=ResponseSchema[dict])
async def wechat_confirmation_link(withdrawal_id: int, auth: Client, db: DB):
    return SuccessResponse(data=await WechatPayoutService(db).issue(app_id(auth), auth.user.id, withdrawal_id=withdrawal_id))


@growth_public_router.post("/payout/wechat/authorize", response_model=ResponseSchema[dict])
async def wechat_authorize(data: WechatAuthorizeIn, db: DB):
    return SuccessResponse(data=await WechatPayoutService(db).authorize(data.token))


@growth_public_router.post("/payout/wechat/exchange", response_model=ResponseSchema[dict])
async def wechat_exchange(data: WechatExchangeIn, db: DB, request: Request):
    return SuccessResponse(data=await WechatPayoutService(db).exchange(data.token, data.code, data.sdk_url, getattr(request.app.state, "redis", None)))


@growth_public_router.post("/payout/wechat/callback", response_class=Response)
async def wechat_payout_callback(request: Request, db: DB):
    import base64
    import json
    from datetime import UTC, datetime

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    from app.api.v1.module_payment.order.providers import _verify_wechat_signed_message
    from app.config.setting import settings

    raw = await request.body()
    if len(raw) > 65536:
        raise CustomException(msg="回调过大", status_code=413)
    _verify_wechat_signed_message({k.lower(): v for k, v in request.headers.items()}, raw)
    try:
        envelope = json.loads(raw)
        if envelope.get("event_type") != "MCHTRANSFER.BILL.FINISHED":
            raise ValueError()
        resource = envelope["resource"]
        data = json.loads(AESGCM(settings.WECHAT_PAY_API_V3_KEY.encode()).decrypt(resource["nonce"].encode(), base64.b64decode(resource["ciphertext"]), resource.get("associated_data", "").encode()))
    except Exception as exc:
        raise CustomException(msg="回调格式或密文无效", status_code=400) from exc
    row = await db.scalar(select(WithdrawalModel).where(WithdrawalModel.out_bill_no == data.get("out_bill_no"), WithdrawalModel.provider == "wechat"))
    if not row or data.get("mch_id") != settings.WECHAT_PAY_MCH_ID or data.get("transfer_amount") != row.amount_fen or data.get("openid") != decrypt_payee(row.payee_snapshot).get("openid"):
        raise CustomException(msg="回调与提现单不匹配", status_code=400)
    await lock_app(db, row.app_id)
    await db.refresh(row)
    if row.status in {"unknown", "processing", "confirming"}:
        row.next_attempt_at = datetime.now(UTC)
    return Response(status_code=204)


@growth_admin_router.post("/refunds/synchronize", response_model=ResponseSchema[dict])
async def synchronize_refund(data: RefundSyncIn, auth: FinanceWrite, db: DB):
    from .refund_gateway import synchronize_refund as synchronize

    return SuccessResponse(data=await synchronize(db, app_id(auth), data.order_no, data.refund_no), msg="渠道退款已核验，相关奖励已对账")


@growth_admin_router.post("/legacy-segments/{segment_id}/archive", response_model=ResponseSchema[dict])
async def archive_legacy_segment(segment_id: int, auth: Write, db: DB):
    from app.api.v1.module_billing.model import AppPricingStrategyModel
    from app.api.v1.module_client.user.model import ClientUserSegmentModel
    from app.api.v1.module_user_operations.model import ClientMessageCampaignModel

    await lock_app(db, app_id(auth))
    segment = await db.scalar(select(ClientUserSegmentModel).where(ClientUserSegmentModel.app_id == auth.app_id, ClientUserSegmentModel.id == segment_id, ClientUserSegmentModel.is_deleted == False))
    if not segment or not (segment.filters or {}).get("level_code"):
        raise CustomException(msg="未找到旧等级分群", status_code=404)
    price = await db.scalar(
        select(AppPricingStrategyModel.id)
        .where(
            AppPricingStrategyModel.app_id == auth.app_id,
            AppPricingStrategyModel.status == "active",
            AppPricingStrategyModel.scope_type == "segment",
            AppPricingStrategyModel.scope_value["segment_id"].as_integer() == segment_id,
            AppPricingStrategyModel.is_deleted == False,
        )
        .limit(1)
    )
    campaign = await db.scalar(
        select(ClientMessageCampaignModel.id)
        .where(
            ClientMessageCampaignModel.app_id == auth.app_id,
            ClientMessageCampaignModel.status.in_(["draft", "scheduled", "sending"]),
            ClientMessageCampaignModel.audience_type == "segment",
            ClientMessageCampaignModel.audience_value["segment_id"].as_integer() == segment_id,
            ClientMessageCampaignModel.is_deleted == False,
        )
        .limit(1)
    )
    if price or campaign:
        raise CustomException(msg="该分群仍被定价策略或消息任务引用，请先切换引用", status_code=409)
    segment.status, segment.updated_id = "inactive", auth.user.id
    return SuccessResponse(data={"id": segment.id}, msg="旧分群已归档，历史记录保留")
