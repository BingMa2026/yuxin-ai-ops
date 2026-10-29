import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.module_client.app.model import ClientAppModel
from app.api.v1.module_client.app.model_policy import allowed_modes, billing_user, current_mode, get_model_policy, require_platform_model
from app.api.v1.module_client.user.model import ClientUserModel
from app.api.v1.module_model_gateway.model import ModelCatalogModel, ModelProviderAccountModel, ModelProviderTemplateModel
from app.api.v1.module_model_gateway.secret_codec import decrypt_settings
from app.core.base_schema import AuthSchema
from app.core.exceptions import CustomException

from . import provider
from .capabilities import speech_adapter, speech_endpoint
from .model import AppSpeechConfigModel, SpeechUsageModel
from .official_prices import duration_rate
from .schema import SpeechCapability, SpeechConfigInput, SpeechConfigOut, SpeechModelOption, SpeechResult


class SpeechService:
    def __init__(self, auth: AuthSchema, db: AsyncSession):
        if not auth.app_id:
            raise CustomException(msg="请先选择客户端", status_code=409)
        self.auth, self.db, self.app_id = auth, db, auth.app_id

    async def config_row(self):
        return await self.db.scalar(select(AppSpeechConfigModel).where(AppSpeechConfigModel.app_id == self.app_id, AppSpeechConfigModel.is_deleted == False))

    async def config(self):
        row = await self.config_row()
        return SpeechConfigOut.model_validate(row) if row else SpeechConfigOut()

    async def model_pair(self, model_id: int):
        pair = (
            await self.db.execute(
                select(ModelCatalogModel, ModelProviderAccountModel)
                .join(ModelProviderAccountModel, ModelProviderAccountModel.id == ModelCatalogModel.provider_account_id)
                .join(ModelProviderTemplateModel, ModelProviderTemplateModel.id == ModelProviderAccountModel.template_id)
                .where(
                    ModelCatalogModel.id == model_id,
                    ModelCatalogModel.status == "active",
                    ModelCatalogModel.is_deleted == False,
                    ModelProviderAccountModel.status == "active",
                    ModelProviderAccountModel.connection_status == "healthy",
                    ModelProviderAccountModel.is_deleted == False,
                    ModelProviderTemplateModel.status == "active",
                    ModelProviderTemplateModel.is_deleted == False,
                )
            )
        ).first()
        if not pair or not speech_adapter(pair[0].provider_model_id, pair[0].speech_protocol):
            raise CustomException(msg="语音识别模型不可用，请联系运营人员", status_code=503)
        speech_endpoint(pair[1].endpoint, speech_adapter(pair[0].provider_model_id, pair[0].speech_protocol))
        if not pair[0].speech_pricing:
            raise CustomException(msg="语音模型采购价格尚未配置", status_code=503)
        return pair

    async def options(self):
        rows = (
            await self.db.execute(
                select(ModelCatalogModel, ModelProviderAccountModel)
                .join(ModelProviderAccountModel, ModelProviderAccountModel.id == ModelCatalogModel.provider_account_id)
                .where(ModelCatalogModel.is_deleted == False, ModelProviderAccountModel.is_deleted == False)
            )
        ).all()
        return [
            SpeechModelOption(
                id=model.id,
                name=model.display_name,
                provider_name=account.name,
                provider_model_id=model.provider_model_id,
                status="active" if model.status == account.status == "active" and account.connection_status == "healthy" else "inactive",
            )
            for model, account in rows
            if speech_adapter(model.provider_model_id, model.speech_protocol)
        ]

    async def save(self, data: SpeechConfigInput):
        await self.db.scalar(select(ClientAppModel.id).where(ClientAppModel.id == self.app_id).with_for_update())
        row = await self.config_row()
        if (row.revision if row else 0) != data.revision:
            raise CustomException(msg="语音配置已被修改，请刷新后重试", status_code=409)
        if data.status == "active":
            await self.model_pair(data.catalog_model_id)
        if row is None:
            row = AppSpeechConfigModel(app_id=self.app_id)
            self.db.add(row)
        for key, value in data.model_dump(exclude={"revision"}).items():
            setattr(row, key, value)
        row.revision = data.revision + 1
        await self.db.flush()
        return SpeechConfigOut.model_validate(row)

    async def capability(self):
        row = await self.config_row()
        if not row or row.status != "active" or not row.catalog_model_id:
            return SpeechCapability(available=False, reason="当前客户端尚未开通语音输入")
        app = await get_model_policy(self.db, self.app_id)
        user = await billing_user(self.db, app, self.auth.user.id)
        if "credits" not in allowed_modes(app) or current_mode(app, user) != "credits":
            return SpeechCapability(available=False, reason="当前客户端使用自配模型，平台语音服务未启用")
        try:
            await self.model_pair(row.catalog_model_id)
        except CustomException:
            return SpeechCapability(available=False, reason="语音输入暂不可用，请稍后重试")
        return SpeechCapability(available=True, max_duration_seconds=row.max_duration_seconds, daily_limit_seconds=row.daily_limit_seconds)

    async def transcribe(self, audio: bytes, request_id: str):
        await require_platform_model(self.db, self.app_id, user_id=self.auth.user.id, lock=True)
        config = await self.config_row()
        if not config or config.status != "active" or not config.catalog_model_id:
            raise CustomException(msg="当前客户端尚未开通语音输入", status_code=503)
        model, account = await self.model_pair(config.catalog_model_id)
        pcm, duration_ms = provider.inspect_audio(audio, config.max_duration_seconds)
        # Serialize only reservation, never hold a database lock during recognition.
        await self.db.scalar(select(ClientUserModel.id).where(ClientUserModel.id == self.auth.user.id, ClientUserModel.app_id == self.app_id).with_for_update())
        scope = (SpeechUsageModel.app_id == self.app_id, SpeechUsageModel.user_id == self.auth.user.id)
        if await self.db.scalar(select(SpeechUsageModel.id).where(*scope, SpeechUsageModel.request_id == request_id)):
            raise CustomException(msg="这段录音已提交，请勿重复识别", status_code=409)
        now = datetime.now(UTC)
        running = await self.db.scalar(select(SpeechUsageModel.id).where(*scope, SpeechUsageModel.status == "running", SpeechUsageModel.created_time > now - timedelta(seconds=90)))
        recent = await self.db.scalar(select(func.count()).select_from(SpeechUsageModel).where(*scope, SpeechUsageModel.created_time > now - timedelta(minutes=1)))
        if running or recent >= 8:
            raise CustomException(msg="语音识别请求较频繁，请稍后重试", status_code=429)
        # Beijing calendar day; every submitted recording consumes the safety quota,
        # including failed calls that may have incurred upstream usage.
        day_start = (now + timedelta(hours=8)).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=8)
        used = await self.db.scalar(select(func.coalesce(func.sum(SpeechUsageModel.duration_ms), 0)).where(*scope, SpeechUsageModel.created_time >= day_start))
        if used + duration_ms > config.daily_limit_seconds * 1000:
            raise CustomException(msg="今天的语音输入时长已用完，请使用键盘输入", status_code=429)
        usage = SpeechUsageModel(
            app_id=self.app_id,
            user_id=self.auth.user.id,
            catalog_model_id=model.id,
            request_id=request_id,
            duration_ms=duration_ms,
            cost_per_minute=duration_rate(model.speech_pricing),
            status="running",
        )
        self.db.add(usage)
        endpoint, model_id = account.endpoint, model.provider_model_id
        protocol = speech_adapter(model_id, model.speech_protocol)
        key = str(decrypt_settings(account.settings_cipher).get("api_key") or "")
        await self.db.commit()
        try:
            transcript = await provider.transcribe(endpoint, model_id, key, audio, pcm, protocol)
            if len(transcript) > 20000:
                raise ValueError("oversized transcription")
            usage.status = "succeeded" if transcript else "empty"
            if usage.cost_per_minute is not None:
                billed_seconds = (duration_ms + 999) // 1000
                usage.estimated_cost_yuan = usage.cost_per_minute * Decimal(billed_seconds) / Decimal(60)
            await self.db.commit()
            return SpeechResult(text=transcript, duration_ms=duration_ms)
        except asyncio.CancelledError:
            usage.status, usage.error_category = "cancelled", "cancelled"
            await self.db.commit()
            raise
        except Exception as exc:
            usage.status = "failed"
            usage.error_category = "timeout" if isinstance(exc, TimeoutError) else "upstream_error"
            await self.db.commit()
            raise CustomException(msg="语音识别未完成，请重试或使用键盘输入", status_code=502) from None
