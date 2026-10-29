from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import RET
from app.config.setting import settings
from app.core.base_schema import AuthSchema
from app.core.exceptions import CustomException

from .crud import PaymentChannelCRUD
from .model import AppPaymentChannelModel, PaymentChannelModel
from .schema import PaymentChannelOutSchema, PaymentChannelUpdateSchema, PaymentProvider


class PaymentChannelService:
    """支付渠道运营配置与环境密钥就绪状态。"""

    ENVIRONMENT_FIELDS: dict[str, list[str]] = {
        "wechat": [
            "WECHAT_PAY_APP_ID",
            "WECHAT_PAY_MCH_ID",
            "WECHAT_PAY_MERCHANT_SERIAL_NO",
            "WECHAT_PAY_PRIVATE_KEY_PATH",
            "WECHAT_PAY_PLATFORM_CERT_PATH",
            "WECHAT_PAY_API_V3_KEY",
            "PAYMENT_PUBLIC_BASE_URL",
        ],
        "alipay": [
            "ALIPAY_APP_ID",
            "ALIPAY_SELLER_ID",
            "ALIPAY_PRIVATE_KEY_PATH",
            "ALIPAY_PUBLIC_KEY_PATH",
            "PAYMENT_PUBLIC_BASE_URL",
        ],
    }
    PATH_FIELDS = {
        "WECHAT_PAY_PRIVATE_KEY_PATH",
        "WECHAT_PAY_PLATFORM_CERT_PATH",
        "WECHAT_PAY_PUBLIC_KEY_PATH",
        "ALIPAY_PRIVATE_KEY_PATH",
        "ALIPAY_PUBLIC_KEY_PATH",
    }

    @staticmethod
    def _is_valid_http_url(value: str, *, require_https: bool = False) -> bool:
        try:
            parsed = urlsplit(value.strip())
        except ValueError:
            return False
        if parsed.scheme not in {"http", "https"} or parsed.username is not None or parsed.password is not None:
            return False
        if require_https and parsed.scheme != "https":
            return False
        hostname = (parsed.hostname or "").rstrip(".").lower()
        if not hostname or hostname == "localhost" or hostname.endswith(".local"):
            return False
        try:
            return ip_address(hostname).is_global
        except ValueError:
            return "." in hostname

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db
        self.crud = PaymentChannelCRUD(auth, db)

    @staticmethod
    def _masked(value: str) -> str | None:
        value = value.strip()
        if not value:
            return None
        if len(value) <= 8:
            return f"{value[:2]}***{value[-2:]}"
        return f"{value[:4]}****{value[-4:]}"

    @classmethod
    def _runtime_status(cls, provider: str, mode: str = "production") -> tuple[list[str], str | None, bool]:
        fields = cls.ENVIRONMENT_FIELDS[provider]
        require_https = mode == "production"
        missing: list[str] = []
        for field in fields:
            value = str(getattr(settings, field, "") or "").strip()
            if not value:
                missing.append(field)
            elif field == "PAYMENT_PUBLIC_BASE_URL" and not cls._is_valid_http_url(
                value,
                require_https=require_https,
            ):
                missing.append(field)
            elif field in cls.PATH_FIELDS and not Path(value).is_file():
                missing.append(field)
        if provider == "wechat":
            if settings.WECHAT_PAY_API_V3_KEY and len(settings.WECHAT_PAY_API_V3_KEY) != 32:
                missing.append("WECHAT_PAY_API_V3_KEY")
            platform_cert_ready = bool(settings.WECHAT_PAY_PLATFORM_CERT_PATH) and Path(settings.WECHAT_PAY_PLATFORM_CERT_PATH).is_file()
            public_key_ready = bool(settings.WECHAT_PAY_PUBLIC_KEY_ID) and bool(settings.WECHAT_PAY_PUBLIC_KEY_PATH) and Path(settings.WECHAT_PAY_PUBLIC_KEY_PATH).is_file()
            if public_key_ready:
                missing = [field for field in missing if field != "WECHAT_PAY_PLATFORM_CERT_PATH"]
            elif not platform_cert_ready:
                missing.append("WECHAT_PAY_PLATFORM_CERT_PATH")

        identity_value = settings.WECHAT_PAY_MCH_ID if provider == "wechat" else settings.ALIPAY_APP_ID
        notify_url = settings.PAYMENT_PUBLIC_BASE_URL
        return (
            list(dict.fromkeys(missing)),
            cls._masked(identity_value),
            cls._is_valid_http_url(notify_url, require_https=require_https),
        )

    def _to_schema(self, channel: PaymentChannelModel, *, app_enabled: bool = False) -> PaymentChannelOutSchema:
        missing, identity, notify_configured = self._runtime_status(channel.provider, channel.mode)
        base = PaymentChannelOutSchema.model_validate(channel)
        return base.model_copy(
            update={
                "configured": not missing,
                "missing_fields": missing,
                "merchant_identity": identity,
                "notify_url_configured": notify_configured,
                "environment_fields": self.ENVIRONMENT_FIELDS[channel.provider],
                # Contract deduction is deliberately not exposed in the MVP;
                # environment flags alone do not constitute a renewal flow.
                "supports_auto_renew": False,
                "app_enabled": app_enabled,
            }
        )

    async def _app_bindings(self) -> dict[int, bool]:
        if not self.auth or not self.auth.app_id:
            return {}
        rows = list(
            (
                await self.db.scalars(
                    select(AppPaymentChannelModel).where(
                        AppPaymentChannelModel.app_id == self.auth.app_id,
                        AppPaymentChannelModel.is_deleted == False,
                    )
                )
            ).all()
        )
        return {row.channel_id: row.enabled for row in rows}

    async def list(self) -> list[PaymentChannelOutSchema]:
        channels = await self.crud.get_list(
            search={"provider": ("in", ["wechat", "alipay"])},
            order_by=[{"order": "asc"}, {"id": "asc"}],
        )
        bindings = await self._app_bindings()
        return [self._to_schema(channel, app_enabled=bindings.get(channel.id, False)) for channel in channels]

    async def detail(self, provider: PaymentProvider) -> PaymentChannelOutSchema:
        channel = await self.crud.get_or_404(provider=provider, msg="支付渠道不存在")
        bindings = await self._app_bindings()
        return self._to_schema(channel, app_enabled=bindings.get(channel.id, False))

    async def update(self, provider: PaymentProvider, data: PaymentChannelUpdateSchema) -> PaymentChannelOutSchema:
        channel = await self.crud.get_or_404(provider=provider, msg="支付渠道不存在")
        updated = await self.crud.update(id=channel.id, data=data)
        bindings = await self._app_bindings()
        return self._to_schema(updated, app_enabled=bindings.get(channel.id, False))

    async def toggle(self, provider: PaymentProvider, enabled: bool) -> PaymentChannelOutSchema:
        channel = await self.crud.get_or_404(provider=provider, msg="支付渠道不存在")
        if enabled:
            missing, _, _ = self._runtime_status(provider, channel.mode)
            if missing:
                raise CustomException(
                    msg="环境配置未就绪，不能启用该支付渠道",
                    code=RET.BAD_REQUEST.code,
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
        updated = await self.crud.update(id=channel.id, data={"enabled": enabled})
        bindings = await self._app_bindings()
        return self._to_schema(updated, app_enabled=bindings.get(channel.id, False))

    async def bind_app(self, provider: PaymentProvider, enabled: bool) -> PaymentChannelOutSchema:
        if not self.auth.app_id:
            raise CustomException(msg="请先选择客户端", status_code=409)
        channel = await self.crud.get_or_404(provider=provider, msg="支付渠道不存在")
        if enabled:
            if not channel.enabled:
                raise CustomException(msg="请先启用平台支付渠道")
            missing, _, _ = self._runtime_status(provider, channel.mode)
            if missing:
                raise CustomException(msg="支付渠道环境配置未就绪")
        binding = await self.db.scalar(
            select(AppPaymentChannelModel).where(
                AppPaymentChannelModel.app_id == self.auth.app_id,
                AppPaymentChannelModel.channel_id == channel.id,
                AppPaymentChannelModel.is_deleted == False,
            )
        )
        if binding:
            binding.enabled = enabled
        else:
            binding = AppPaymentChannelModel(
                app_id=self.auth.app_id,
                channel_id=channel.id,
                enabled=enabled,
            )
            self.db.add(binding)
        await self.db.flush()
        return self._to_schema(channel, app_enabled=enabled)
