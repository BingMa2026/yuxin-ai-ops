import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.setting import settings
from app.core.database import async_db_session
from app.core.exceptions import CustomException
from app.utils.password_util import PwdUtil

from .engine import BUSINESS_TZ, utc
from .gift_service import GiftService
from .model import CashLedgerModel, PayoutAccountModel, PayoutAttemptModel, WithdrawalModel
from .payout_providers import PayoutResult, merchant_identity, transfer
from .reward_service import cash_account
from .schema import AlipayAccountIn, WithdrawalIn
from .service import client_user, lock_app


def encrypt_payee(data: dict) -> str:
    try:
        return Fernet(settings.GROWTH_PAYOUT_ENCRYPTION_KEY.encode()).encrypt(json.dumps(data).encode()).decode()
    except (ValueError, TypeError) as exc:
        raise CustomException(msg="收款资料加密服务尚未配置", status_code=409) from exc


def decrypt_payee(value: str) -> dict:
    try:
        return json.loads(Fernet(settings.GROWTH_PAYOUT_ENCRYPTION_KEY.encode()).decrypt(value.encode()))
    except Exception as exc:
        raise CustomException(msg="收款资料暂无法解密，请联系管理员核查密钥", status_code=409) from exc


class PayoutService:
    def __init__(self, db: AsyncSession, app_id: int):
        self.db, self.app_id = db, app_id

    async def password(self, user_id: int, password: str) -> None:
        user = await client_user(self.db, self.app_id, user_id)
        if user.status != "active" or not PwdUtil.verify_password(password, user.password_hash):
            raise CustomException(msg="账号状态或密码不正确", status_code=403)

    async def account(self, user_id: int, data: AlipayAccountIn) -> PayoutAccountModel:
        await lock_app(self.db, self.app_id)
        await self.password(user_id, data.password)
        account = await self.db.scalar(select(PayoutAccountModel).where(PayoutAccountModel.app_id == self.app_id, PayoutAccountModel.user_id == user_id, PayoutAccountModel.provider == "alipay"))
        if not account:
            account = PayoutAccountModel(app_id=self.app_id, user_id=user_id, provider="alipay")
            self.db.add(account)
        account.encrypted_details = encrypt_payee({"account": data.account.strip(), "name": data.name.strip()})
        account.masked_label = f"{data.name[0]}** · {data.account[:2]}***{data.account[-2:]}"
        account.status = "ready"
        await self.db.flush()
        return account

    async def withdraw(self, user_id: int, data: WithdrawalIn) -> WithdrawalModel:
        await lock_app(self.db, self.app_id)
        await self.password(user_id, data.password)
        prior = await self.db.scalar(select(WithdrawalModel).where(WithdrawalModel.app_id == self.app_id, WithdrawalModel.user_id == user_id, WithdrawalModel.idempotency_key == data.idempotency_key))
        if prior:
            if prior.amount_fen != data.amount_fen or prior.account_id != data.account_id:
                raise CustomException(msg="该请求编号已用于另一笔提现", status_code=409)
            return prior
        account = await self.db.scalar(
            select(PayoutAccountModel).where(
                PayoutAccountModel.app_id == self.app_id, PayoutAccountModel.user_id == user_id, PayoutAccountModel.id == data.account_id, PayoutAccountModel.status == "ready"
            )
        )
        if not account:
            raise CustomException(msg="请先完成收款账户绑定", status_code=409)
        from app.api.v1.module_finance.channels import payout_capabilities

        if not any(c["provider"] == account.provider and c["available"] for c in await payout_capabilities(self.db, self.app_id)):
            raise CustomException(msg="商户转账能力尚未就绪", status_code=409)
        if account.provider == "wechat" and data.amount_fen >= 200000:
            raise CustomException(msg="当前微信通道单次提现需低于2000元", status_code=422)
        _, policy = await GiftService(self.db, self.app_id).rights()
        if not policy.withdrawal_enabled:
            raise CustomException(msg="提现尚未开放", status_code=409)
        if not policy.withdrawal_min_fen <= data.amount_fen <= policy.withdrawal_max_fen:
            raise CustomException(msg="提现金额不符合单次限额", status_code=422)
        day = datetime.now(UTC).astimezone(BUSINESS_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
        month = day.replace(day=1)
        rows = list(
            await self.db.scalars(
                select(WithdrawalModel).where(
                    WithdrawalModel.app_id == self.app_id, WithdrawalModel.user_id == user_id, WithdrawalModel.created_time >= month, WithdrawalModel.status.not_in(["rejected", "failed"])
                )
            )
        )
        daily = [r for r in rows if utc(r.created_time) >= day]
        if (
            len(daily) >= policy.withdrawal_daily_count
            or sum(r.amount_fen for r in daily) + data.amount_fen > policy.withdrawal_daily_fen
            or sum(r.amount_fen for r in rows) + data.amount_fen > policy.withdrawal_monthly_fen
        ):
            raise CustomException(msg="已超出提现次数或金额限额", status_code=409)
        cash = await cash_account(self.db, self.app_id, user_id)
        if cash.debt or cash.available < data.amount_fen:
            raise CustomException(msg="可提现余额不足或存在待处理退款追偿", status_code=409)
        withdrawal = WithdrawalModel(
            app_id=self.app_id,
            user_id=user_id,
            account_id=account.id,
            provider=account.provider,
            out_bill_no="GX" + uuid4().hex[:30],
            idempotency_key=data.idempotency_key,
            amount_fen=data.amount_fen,
            status="review",
            policy_snapshot={"rights": policy.model_dump(mode="json"), "merchant": merchant_identity(account.provider), "masked_payee": account.masked_label},
            payee_snapshot=account.encrypted_details,
        )
        self.db.add(withdrawal)
        await self.db.flush()
        cash.available -= data.amount_fen
        cash.frozen += data.amount_fen
        self.db.add(
            CashLedgerModel(
                app_id=self.app_id,
                user_id=user_id,
                entry_key=f"withdrawal:{withdrawal.id}:freeze",
                entry_type="withdrawal_freeze",
                amount=-data.amount_fen,
                frozen_delta=data.amount_fen,
                balance_after=cash.available,
                reference_id=withdrawal.id,
            )
        )
        return withdrawal

    async def get(self, withdrawal_id: int) -> WithdrawalModel:
        row = await self.db.scalar(select(WithdrawalModel).where(WithdrawalModel.id == withdrawal_id, WithdrawalModel.app_id == self.app_id).execution_options(populate_existing=True))
        if not row:
            raise CustomException(msg="提现单不存在", status_code=404)
        return row

    async def review(self, withdrawal_id: int, approved: bool, reason: str, operator_id: int) -> WithdrawalModel:
        await lock_app(self.db, self.app_id)
        row = await self.get(withdrawal_id)
        if row.status != "review":
            raise CustomException(msg="提现单已经处理", status_code=409)
        row.reason = reason
        if approved:
            cash = await cash_account(self.db, self.app_id, row.user_id)
            if cash.debt:
                raise CustomException(msg="该用户存在退款追偿，请先处理后审核", status_code=409)
            row.status, row.next_attempt_at = "queued", datetime.now(UTC)
        else:
            await self.apply(row, PayoutResult("failed", reason=reason))
            row.status = "rejected"
        self.db.add(PayoutAttemptModel(app_id=self.app_id, withdrawal_id=row.id, action="review", status=row.status, detail=f"审核人员{operator_id}：{reason}"[:500]))
        await self.db.flush()
        return row

    async def apply(self, row: WithdrawalModel, result: PayoutResult) -> None:
        if row.status in {"succeeded", "failed", "rejected"}:
            return
        if result.state in {"succeeded", "failed"}:
            cash = await cash_account(self.db, self.app_id, row.user_id)
            if cash.frozen < row.amount_fen:
                raise CustomException(msg="冻结余额与提现单不一致", status_code=409)
            cash.frozen -= row.amount_fen
            returned, offset = 0, 0
            if result.state == "failed":
                offset = min(cash.debt, row.amount_fen)
                cash.debt -= offset
                returned = row.amount_fen - offset
                cash.available += returned
            self.db.add(
                CashLedgerModel(
                    app_id=self.app_id,
                    user_id=row.user_id,
                    entry_key=f"withdrawal:{row.id}:settle",
                    entry_type=f"withdrawal_{result.state}",
                    amount=returned,
                    frozen_delta=-row.amount_fen,
                    debt_delta=-offset,
                    balance_after=cash.available,
                    reference_id=row.id,
                )
            )
            row.completed_at = datetime.now(UTC)
        row.status = result.state
        row.provider_bill_no = result.bill_no or row.provider_bill_no
        row.confirmation_package = encrypt_payee({"package": result.package}) if result.package else row.confirmation_package
        row.reason = result.reason or None
        row.next_attempt_at = datetime.now(UTC) + timedelta(minutes=2)
        await self.db.flush()


async def dispatch_payout(app_id: int, withdrawal_id: int) -> None:
    """Claim in one transaction, send outside it, persist in another. Never resubmit unknown bills."""
    async with async_db_session() as db, db.begin():
        await lock_app(db, app_id)
        row = await PayoutService(db, app_id).get(withdrawal_id)
        if row.status not in {"queued", "unknown", "processing", "confirming"} or (row.next_attempt_at and utc(row.next_attempt_at) > datetime.now(UTC)):
            return
        from app.api.v1.module_finance.channels import payout_capabilities

        if row.status == "queued" and not any(c["provider"] == row.provider and c["available"] for c in await payout_capabilities(db, app_id)):
            row.next_attempt_at = datetime.now(UTC) + timedelta(minutes=30)
            row.reason = "商户通道暂不可用，保留冻结款项等待配置恢复"
            return
        if row.policy_snapshot["merchant"] != merchant_identity(row.provider):
            row.next_attempt_at = datetime.now(UTC) + timedelta(minutes=30)
            row.reason = "商户配置发生变化，保留冻结款项等待原商户核对"
            return
        if row.status == "queued":
            cash = await cash_account(db, app_id, row.user_id)
            if cash.debt:
                row.status, row.reason = "review", "发生退款追偿，退回财务重新审核"
                return
        query = row.status != "queued"
        payee = decrypt_payee(row.payee_snapshot)
        provider, bill, amount = row.provider, row.out_bill_no, row.amount_fen
        row.status = "unknown"
        row.next_attempt_at = datetime.now(UTC) + timedelta(minutes=5)
        db.add(PayoutAttemptModel(app_id=app_id, withdrawal_id=row.id, action="query" if query else "submit", status="started", detail="按原商户单号处理"))
    try:
        result = await transfer(provider, bill, amount, payee, query=query)
    except Exception:
        result = PayoutResult("unknown", reason="渠道结果暂不明确，款项继续冻结并自动查单")
    async with async_db_session() as db, db.begin():
        await lock_app(db, app_id)
        service = PayoutService(db, app_id)
        row = await service.get(withdrawal_id)
        await service.apply(row, result)
        db.add(PayoutAttemptModel(app_id=app_id, withdrawal_id=row.id, action="query" if query else "submit", status=result.state, detail=result.reason or "已收到渠道核验结果"))
