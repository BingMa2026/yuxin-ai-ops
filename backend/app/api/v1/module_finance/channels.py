import asyncio
from datetime import UTC, datetime
from pathlib import Path

from cryptography import x509
from sqlalchemy import select

from app.api.v1.module_growth.payout_providers import capabilities
from app.api.v1.module_growth.service import lock_app
from app.api.v1.module_payment.channel.service import PaymentChannelService
from app.config.setting import settings
from app.core.exceptions import CustomException

from .common import audit
from .model import FinanceControlModel


async def enabled(db, app_id: int, provider: str, action: str) -> bool:
    row = await db.scalar(select(FinanceControlModel).where(FinanceControlModel.app_id == app_id, FinanceControlModel.provider == provider))
    return bool(getattr(row, action + "_enabled")) if row else True


async def payout_capabilities(db, app_id: int):
    result = capabilities()
    for item in result:
        if not await enabled(db, app_id, item["provider"], "payout"):
            item["available"], item["reason"] = False, "当前客户端已暂停该渠道提现"
    return result


def certificate_status(provider: str):
    paths = [("应用证书", settings.ALIPAY_APP_CERT_PATH), ("支付宝公钥证书", settings.ALIPAY_PUBLIC_KEY_PATH)] if provider == "alipay" else [("微信平台证书", settings.WECHAT_PAY_PLATFORM_CERT_PATH)]
    rows = []
    for label, path in paths:
        if not path:
            continue
        try:
            cert = x509.load_pem_x509_certificate(Path(path).read_bytes())
            days = (cert.not_valid_after_utc - datetime.now(UTC)).days
            rows.append({"name": label, "expires_at": cert.not_valid_after_utc, "days_left": days, "status": "expired" if days < 0 else "expiring" if days <= 30 else "valid"})
        except (OSError, ValueError):
            rows.append({"name": label, "expires_at": None, "days_left": None, "status": "unavailable"})
    return rows


async def list_channels(db, auth):
    rows = await PaymentChannelService(auth, db).list()
    payout = {c["provider"]: c for c in capabilities()}
    controls = {c.provider: c for c in await db.scalars(select(FinanceControlModel).where(FinanceControlModel.app_id == auth.app_id))}
    result = []
    for channel in rows:
        c = controls.get(channel.provider)
        item = channel.model_dump()
        item.update(
            payout_enabled=c.payout_enabled if c else True,
            refund_enabled=c.refund_enabled if c else True,
            payout_ready=payout[channel.provider]["available"],
            payout_reason=payout[channel.provider]["reason"],
            certificates=await asyncio.to_thread(certificate_status, channel.provider),
            checked_at=datetime.now(UTC),
            last_changed_at=c.updated_time if c else None,
        )
        result.append(item)
    return result


async def update_channel(db, auth, provider, data):
    await lock_app(db, auth.app_id)
    service = PaymentChannelService(auth, db)
    before = next(c for c in await list_channels(db, auth) if c["provider"] == provider)
    if data.payout_enabled and not before["payout_ready"] and not before["payout_enabled"]:
        raise CustomException(msg=before["payout_reason"] or "商户转账配置尚未就绪", status_code=409)
    if data.refund_enabled and not before["configured"] and not before["refund_enabled"]:
        raise CustomException(msg="支付渠道配置尚未就绪，不能启用退款", status_code=409)
    if data.collection_enabled != before["app_enabled"]:
        await service.bind_app(provider, data.collection_enabled)
    row = await db.scalar(select(FinanceControlModel).where(FinanceControlModel.app_id == auth.app_id, FinanceControlModel.provider == provider))
    if not row:
        row = FinanceControlModel(app_id=auth.app_id, provider=provider)
        db.add(row)
    row.payout_enabled, row.refund_enabled, row.updated_by, row.reason = data.payout_enabled, data.refund_enabled, auth.user.id, data.reason
    audit(
        db, auth.app_id, "channel", provider, "configure", auth.user.id, data.reason, {k: before[k] for k in ("app_enabled", "payout_enabled", "refund_enabled")}, data.model_dump(exclude={"reason"})
    )
    await db.flush()
    return next(c for c in await list_channels(db, auth) if c["provider"] == provider)
