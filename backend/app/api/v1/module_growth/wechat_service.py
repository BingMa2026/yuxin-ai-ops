import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.setting import settings
from app.core.exceptions import CustomException

from .engine import utc
from .model import PayoutAccountModel, PayoutLinkModel, WithdrawalModel
from .payout_providers import capabilities
from .payout_service import PayoutService, decrypt_payee, encrypt_payee
from .service import lock_app


class WechatPayoutService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def issue(self, app_id: int, user_id: int, *, withdrawal_id: int | None = None) -> dict:
        await lock_app(self.db, app_id)
        if not any(c["provider"] == "wechat" and c["available"] for c in capabilities()):
            raise CustomException(msg="微信商户转账尚未就绪", status_code=409)
        if withdrawal_id:
            row = await self.db.scalar(
                select(WithdrawalModel).where(
                    WithdrawalModel.app_id == app_id,
                    WithdrawalModel.user_id == user_id,
                    WithdrawalModel.id == withdrawal_id,
                    WithdrawalModel.provider == "wechat",
                    WithdrawalModel.status == "confirming",
                )
            )
            if not row:
                raise CustomException(msg="该提现单无需确认收款", status_code=409)
        token = secrets.token_urlsafe(32)
        link = PayoutLinkModel(
            app_id=app_id,
            user_id=user_id,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            purpose="confirm" if withdrawal_id else "bind",
            withdrawal_id=withdrawal_id,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
        self.db.add(link)
        await self.db.flush()
        return {"id": link.id, "url": f"{settings.GROWTH_PUBLIC_BASE_URL.rstrip('/')}/payout/wechat#token={token}", "expires_at": link.expires_at}

    async def link(self, token: str) -> PayoutLinkModel:
        row = await self.db.scalar(select(PayoutLinkModel).where(PayoutLinkModel.token_hash == hashlib.sha256(token.encode()).hexdigest()))
        if not row or utc(row.expires_at) <= datetime.now(UTC) or row.status == "consumed":
            raise CustomException(msg="二维码已失效，请在客户端重新生成", status_code=410)
        return row

    async def authorize(self, token: str) -> dict:
        row = await self.link(token)
        redirect = f"{settings.GROWTH_PUBLIC_BASE_URL.rstrip('/')}/payout/wechat"
        params = {"appid": settings.GROWTH_WECHAT_APP_ID, "redirect_uri": redirect, "response_type": "code", "scope": "snsapi_base", "state": token}
        return {"url": "https://open.weixin.qq.com/connect/oauth2/authorize?" + urlencode(params) + "#wechat_redirect", "purpose": row.purpose}

    async def exchange(self, token: str, code: str, sdk_url: str = "", redis=None) -> dict:
        link = await self.link(token)
        # Exchange outside an application lock; consume atomically once the verified identity is available.
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                "https://api.weixin.qq.com/sns/oauth2/access_token",
                params={"appid": settings.GROWTH_WECHAT_APP_ID, "secret": settings.GROWTH_WECHAT_APP_SECRET, "code": code, "grant_type": "authorization_code"},
            )
        data = response.json()
        openid = data.get("openid")
        if response.status_code != 200 or not isinstance(openid, str) or not 8 <= len(openid) <= 128 or data.get("errcode"):
            raise CustomException(msg="微信授权失败，请返回客户端重新扫码", status_code=400)
        sdk = None
        if link.purpose == "confirm":
            from .wechat_sdk import sdk_signature

            sdk = await sdk_signature(redis, sdk_url, token)
        await lock_app(self.db, link.app_id)
        await self.db.refresh(link)
        if link.status != "pending" or utc(link.expires_at) <= datetime.now(UTC):
            raise CustomException(msg="该授权已处理或过期", status_code=409)
        link.encrypted_payload = encrypt_payee({"openid": openid, "appid": settings.GROWTH_WECHAT_APP_ID})
        link.status = "authorized"
        if link.purpose == "bind":
            await self.db.flush()
            return {"purpose": "bind", "status": "authorized", "message": "微信身份已验证，请返回客户端确认绑定"}
        withdrawal = await self.db.scalar(select(WithdrawalModel).where(WithdrawalModel.id == link.withdrawal_id, WithdrawalModel.app_id == link.app_id, WithdrawalModel.user_id == link.user_id))
        if not withdrawal or withdrawal.status != "confirming" or decrypt_payee(withdrawal.payee_snapshot).get("openid") != openid or not withdrawal.confirmation_package:
            raise CustomException(msg="请使用绑定的收款微信扫码", status_code=403)
        link.status = "consumed"
        return {"purpose": "confirm", "sdk": sdk, "mchId": settings.WECHAT_PAY_MCH_ID, "appId": settings.GROWTH_WECHAT_APP_ID, "package": decrypt_payee(withdrawal.confirmation_package)["package"]}

    async def status(self, app_id: int, user_id: int, link_id: int) -> dict:
        link = await self.db.scalar(select(PayoutLinkModel).where(PayoutLinkModel.id == link_id, PayoutLinkModel.app_id == app_id, PayoutLinkModel.user_id == user_id))
        if not link:
            raise CustomException(msg="绑定记录不存在", status_code=404)
        return {"id": link.id, "status": "expired" if utc(link.expires_at) <= datetime.now(UTC) else link.status, "expires_at": link.expires_at}

    async def confirm_binding(self, app_id: int, user_id: int, link_id: int, password: str) -> PayoutAccountModel:
        await lock_app(self.db, app_id)
        await PayoutService(self.db, app_id).password(user_id, password)
        link = await self.db.scalar(
            select(PayoutLinkModel).where(PayoutLinkModel.id == link_id, PayoutLinkModel.app_id == app_id, PayoutLinkModel.user_id == user_id, PayoutLinkModel.purpose == "bind")
        )
        if not link or link.status != "authorized" or utc(link.expires_at) <= datetime.now(UTC):
            raise CustomException(msg="请先通过微信扫码完成授权", status_code=409)
        account = await self.db.scalar(select(PayoutAccountModel).where(PayoutAccountModel.app_id == app_id, PayoutAccountModel.user_id == user_id, PayoutAccountModel.provider == "wechat"))
        if not account:
            account = PayoutAccountModel(app_id=app_id, user_id=user_id, provider="wechat")
            self.db.add(account)
        account.encrypted_details = link.encrypted_payload
        account.masked_label = "已验证的微信收款账户"
        account.status, link.status = "ready", "consumed"
        await self.db.flush()
        return account
