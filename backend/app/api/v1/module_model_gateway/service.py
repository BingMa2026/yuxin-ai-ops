from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx
from redis.asyncio.client import Redis
from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.module_speech.capabilities import speech_adapter, speech_endpoint
from app.api.v1.module_speech.official_prices import official_speech_price
from app.core.base_schema import AuthSchema, JWTPayloadSchema
from app.core.exceptions import CustomException
from app.core.redis_crud import RedisCURD
from app.core.security import create_access_token, decode_access_token

from .generation_policy import SUPPORTED_MODELS
from .model import (
    AppModelBindingModel,
    AppModelRouteModel,
    ModelCatalogModel,
    ModelProviderAccountModel,
    ModelProviderTemplateModel,
    ModelPurchasePriceVersionModel,
)
from .official_pricing import discovered_model_capabilities, official_model_pricing
from .schema import (
    AppModelBindingCreate,
    AppModelBindingOut,
    AppModelBindingUpdate,
    AppModelRouteCreate,
    AppModelRouteOut,
    ClientModelConfig,
    ClientModelOption,
    ClientModelRoute,
    CustomProviderTemplateCreate,
    DiscoveredModelOut,
    ModelCatalogCreate,
    ModelCatalogOut,
    ModelCatalogUpdate,
    ProviderAccountCreate,
    ProviderAccountOut,
    ProviderAccountUpdate,
    ProviderConnectionTest,
    ProviderTemplateOut,
    ResourceStatusUpdate,
    RuntimeTokenOut,
)
from .secret_codec import decrypt_settings, encrypt_settings

_MODEL_CONFIG_VERSION_KEY = "client:model-config:version:{app_id}"
_MODEL_CONFIG_CACHE_KEY = "client:model-config:v3:{app_id}:v{version}"
_MODEL_CONFIG_CACHE_TTL = 3600
_DEFAULT_BUSINESS_ROUTES = (
    ("chat_default", "默认聊天"),
    ("document_intelligence", "文档理解"),
    ("semantic_review", "语义审核"),
)


async def _model_config_version(redis: Redis | None, app_id: int) -> int:
    if redis is None:
        return 1
    raw = await RedisCURD(redis).get(_MODEL_CONFIG_VERSION_KEY.format(app_id=app_id))
    try:
        return max(int(raw or 1), 1)
    except (TypeError, ValueError):
        return 1


async def _invalidate_model_config(redis: Redis | None, app_ids: set[int]) -> None:
    if redis is None:
        return
    cache = RedisCURD(redis)
    for app_id in app_ids:
        old_version = await _model_config_version(redis, app_id)
        await cache.set(_MODEL_CONFIG_VERSION_KEY.format(app_id=app_id), str(old_version + 1))
        await cache.delete(_MODEL_CONFIG_CACHE_KEY.format(app_id=app_id, version=old_version))


def _masked(settings_data: dict) -> dict:
    result: dict = {}
    for key, value in settings_data.items():
        if not value:
            result[key] = ""
        elif any(marker in key.lower() for marker in ("key", "secret", "token", "account")):
            text = str(value)
            result[key] = f"••••{text[-4:]}" if len(text) >= 4 else "••••"
        else:
            result[key] = value
    return result


class ModelAdminService:
    def __init__(self, auth: AuthSchema, db: AsyncSession, redis: Redis | None = None) -> None:
        self.auth = auth
        self.db = db
        self.redis = redis

    def _app_id(self) -> int:
        if not self.auth.app_id:
            raise CustomException(msg="请先选择客户端", status_code=409)
        return self.auth.app_id

    async def templates(self) -> list[ProviderTemplateOut]:
        rows = list(
            (
                await self.db.scalars(
                    select(ModelProviderTemplateModel)
                    .where(ModelProviderTemplateModel.is_deleted == False, ModelProviderTemplateModel.status == "active")
                    .order_by(ModelProviderTemplateModel.order.asc())
                )
            ).all()
        )
        return [ProviderTemplateOut.model_validate(row) for row in rows]

    async def create_custom_template(self, data: CustomProviderTemplateCreate) -> ProviderTemplateOut:
        if await self.db.scalar(select(ModelProviderTemplateModel.id).where(ModelProviderTemplateModel.code == data.code, ModelProviderTemplateModel.is_deleted == False)):
            raise CustomException(msg="供应商编码已存在")
        item = ModelProviderTemplateModel(**data.model_dump(), protocol="openai_compatible", custom=True, status="active", order=999)
        self.db.add(item)
        await self.db.flush()
        return ProviderTemplateOut.model_validate(item)

    async def accounts(self) -> list[ProviderAccountOut]:
        rows = list((await self.db.scalars(select(ModelProviderAccountModel).where(ModelProviderAccountModel.is_deleted == False).order_by(ModelProviderAccountModel.id.desc()))).all())
        return [ProviderAccountOut.model_validate(row) for row in rows]

    async def create_account(self, data: ProviderAccountCreate) -> ProviderAccountOut:
        template = await self.db.scalar(
            select(ModelProviderTemplateModel).where(ModelProviderTemplateModel.id == data.template_id, ModelProviderTemplateModel.status == "active", ModelProviderTemplateModel.is_deleted == False)
        )
        if not template:
            raise CustomException(msg="供应商模板不存在")
        for field in template.field_schema:
            if field.get("required") and not data.settings.get(field["key"]):
                raise CustomException(msg=f"请填写{field.get('label') or field['key']}")
        if await self.db.scalar(select(ModelProviderAccountModel.id).where(ModelProviderAccountModel.code == data.code, ModelProviderAccountModel.is_deleted == False)):
            raise CustomException(msg="供应商账号编码已存在")
        account = ModelProviderAccountModel(
            **data.model_dump(exclude={"settings"}),
            settings_cipher=encrypt_settings(data.settings),
            masked_summary=_masked(data.settings),
            created_id=self.auth.user.id,
            updated_id=self.auth.user.id,
        )
        self.db.add(account)
        await self.db.flush()
        return ProviderAccountOut.model_validate(account)

    async def update_account(self, account_id: int, data: ProviderAccountUpdate) -> ProviderAccountOut:
        account = await self.db.scalar(
            select(ModelProviderAccountModel).where(
                ModelProviderAccountModel.id == account_id,
                ModelProviderAccountModel.is_deleted == False,
            )
        )
        if not account:
            raise CustomException(msg="供应商账号不存在", status_code=404)
        template = await self.db.scalar(select(ModelProviderTemplateModel).where(ModelProviderTemplateModel.id == account.template_id))
        if not template:
            raise CustomException(msg="供应商模板不存在", status_code=409)
        values = data.model_dump(exclude_unset=True, exclude={"settings"})
        for key, value in values.items():
            setattr(account, key, value)
        if "settings" in data.model_fields_set:
            current = decrypt_settings(account.settings_cipher)
            current.update({key: value for key, value in data.settings.items() if value not in (None, "")})
            for field in template.field_schema:
                if field.get("required") and not current.get(field["key"]):
                    raise CustomException(msg=f"请填写{field.get('label') or field['key']}")
            account.settings_cipher = encrypt_settings(current)
            account.masked_summary = _masked(current)
        account.connection_status = "untested"
        account.last_verified_at = None
        account.last_error = None
        account.updated_id = self.auth.user.id
        await self.db.flush()
        await _invalidate_model_config(self.redis, await self._app_ids_for_account(account_id))
        return ProviderAccountOut.model_validate(account)

    async def test_account(self, account_id: int) -> ProviderAccountOut:
        account = await self.db.scalar(select(ModelProviderAccountModel).where(ModelProviderAccountModel.id == account_id, ModelProviderAccountModel.is_deleted == False))
        if not account:
            raise CustomException(msg="供应商账号不存在")
        template = await self.db.scalar(select(ModelProviderTemplateModel).where(ModelProviderTemplateModel.id == account.template_id))
        if not template or not template.adapter_ready:
            raise CustomException(msg="该供应商适配器尚未启用")
        secrets = decrypt_settings(account.settings_cipher)
        try:
            await self._discover(account, template, secrets)
            account.connection_status = "healthy"
            account.last_error = None
        except CustomException:
            account.connection_status = "failed"
            account.last_error = "供应商返回错误，请检查地址、密钥和网络"
            raise
        except Exception as exc:
            account.connection_status = "failed"
            account.last_error = str(exc)[:500]
            raise CustomException(msg=f"连接失败：{exc!s}") from exc
        finally:
            account.last_verified_at = datetime.now(UTC)
            await self.db.flush()
        return ProviderAccountOut.model_validate(account)

    async def test_connection(self, data: ProviderConnectionTest) -> list[DiscoveredModelOut]:
        """Test unsaved credentials in memory so operators can verify before persisting."""
        template = await self.db.scalar(
            select(ModelProviderTemplateModel).where(
                ModelProviderTemplateModel.id == data.template_id,
                ModelProviderTemplateModel.status == "active",
                ModelProviderTemplateModel.is_deleted == False,
            )
        )
        if not template or not template.adapter_ready:
            raise CustomException(msg="该供应商适配器尚未启用")
        for field in template.field_schema:
            if field.get("required") and not data.settings.get(field["key"]):
                raise CustomException(msg=f"请填写{field.get('label') or field['key']}")
        if template.protocol != "bedrock" and len(data.endpoint.strip()) < 8:
            raise CustomException(msg="请填写有效的 API 地址")
        account = SimpleNamespace(endpoint=data.endpoint, timeout_seconds=data.timeout_seconds)
        try:
            discovered = await self._discover(account, template, data.settings)
        except CustomException:
            raise
        except Exception as exc:
            raise CustomException(msg=f"连接失败：{exc!s}") from exc
        return [
            DiscoveredModelOut(
                provider_model_id=str(item["id"]),
                display_name=str(item.get("name") or item["id"]),
                owned_by=item.get("owned_by"),
                already_synced=False,
            )
            for item in discovered
        ]

    async def discover_models(self, account_id: int, *, sync: bool = True) -> list[DiscoveredModelOut]:
        account = await self.db.scalar(
            select(ModelProviderAccountModel).where(
                ModelProviderAccountModel.id == account_id,
                ModelProviderAccountModel.is_deleted == False,
            )
        )
        if not account:
            raise CustomException(msg="供应商账号不存在", status_code=404)
        template = await self.db.scalar(select(ModelProviderTemplateModel).where(ModelProviderTemplateModel.id == account.template_id))
        if not template or not template.adapter_ready:
            raise CustomException(msg="该供应商适配器尚未启用")
        try:
            discovered = await self._discover(account, template, decrypt_settings(account.settings_cipher))
        except CustomException:
            account.connection_status = "failed"
            account.last_error = "供应商返回错误，请检查地址、密钥和网络"
            account.last_verified_at = datetime.now(UTC)
            await self.db.flush()
            raise
        except Exception as exc:
            account.connection_status = "failed"
            account.last_error = str(exc)[:500]
            account.last_verified_at = datetime.now(UTC)
            await self.db.flush()
            raise CustomException(msg=f"连接失败：{exc!s}") from exc

        account.connection_status = "healthy"
        account.last_error = None
        account.last_verified_at = datetime.now(UTC)
        existing = {
            item.provider_model_id: item
            for item in (
                await self.db.scalars(
                    select(ModelCatalogModel).where(
                        ModelCatalogModel.provider_account_id == account_id,
                        ModelCatalogModel.is_deleted == False,
                    )
                )
            ).all()
        }
        result: list[DiscoveredModelOut] = []
        for item in discovered:
            model_id = str(item["id"])
            present = model_id in existing
            capabilities = discovered_model_capabilities(template.code, model_id)
            official_pricing = official_model_pricing(template.code, model_id)
            if sync and not present:
                base_tier = official_pricing.tiers[0] if official_pricing else None
                model = ModelCatalogModel(
                    provider_account_id=account_id,
                    provider_model_id=model_id,
                    display_name=item.get("name") or model_id,
                    context_length=capabilities.context_length,
                    supports_stream=capabilities.supports_stream,
                    supports_vision=capabilities.supports_vision,
                    input_cost_per_million=(base_tier.input_cost_per_million if base_tier else 0),
                    output_cost_per_million=(base_tier.output_cost_per_million if base_tier else 0),
                    status="inactive",
                    created_id=self.auth.user.id,
                    updated_id=self.auth.user.id,
                )
                self.db.add(model)
                existing[model_id] = model
            elif sync and present:
                model = existing[model_id]
                if model.status == "inactive":
                    model.supports_stream = capabilities.supports_stream and not speech_adapter(model.provider_model_id, model.speech_protocol)
                    model.supports_vision = capabilities.supports_vision
                    if not model.context_length and capabilities.context_length:
                        model.context_length = capabilities.context_length
                    if official_pricing and (float(model.input_cost_per_million) <= 0 or float(model.output_cost_per_million) <= 0):
                        base_tier = official_pricing.tiers[0]
                        model.input_cost_per_million = base_tier.input_cost_per_million
                        model.output_cost_per_million = base_tier.output_cost_per_million
                        model.updated_id = self.auth.user.id
            result.append(
                DiscoveredModelOut(
                    provider_model_id=model_id,
                    display_name=item.get("name") or model_id,
                    owned_by=item.get("owned_by"),
                    already_synced=present,
                    price_matched=official_pricing is not None,
                    gateway_compatible=capabilities.supports_stream,
                )
            )
        await self.db.flush()
        if sync:
            for model in existing.values():
                model.speech_protocol = speech_adapter(model.provider_model_id, model.speech_protocol)
                if model.speech_protocol:
                    model.supports_stream = False
                if not model.speech_pricing:
                    model.speech_pricing = official_speech_price(model.provider_model_id, account.endpoint)
            await self._sync_official_prices(account_id, template.code, existing)
        return result

    async def _sync_official_prices(
        self,
        account_id: int,
        provider_code: str,
        catalog_by_model_id: dict[str, ModelCatalogModel],
    ) -> None:
        """Add exact provider-published prices without replacing operator data."""

        rows = list(
            (
                await self.db.scalars(
                    select(ModelPurchasePriceVersionModel).where(
                        ModelPurchasePriceVersionModel.provider_account_id == account_id,
                        ModelPurchasePriceVersionModel.status == "active",
                        ModelPurchasePriceVersionModel.effective_until.is_(None),
                        ModelPurchasePriceVersionModel.is_deleted == False,
                    )
                )
            ).all()
        )
        existing_tiers = {(row.catalog_model_id, row.context_min, row.context_max) for row in rows}
        now = datetime.now(UTC)
        for provider_model_id, catalog in catalog_by_model_id.items():
            pricing = official_model_pricing(provider_code, provider_model_id)
            if not pricing or not catalog.id:
                continue
            for tier in pricing.tiers:
                key = (catalog.id, tier.context_min, tier.context_max)
                if key in existing_tiers:
                    continue
                self.db.add(
                    ModelPurchasePriceVersionModel(
                        provider_account_id=account_id,
                        catalog_model_id=catalog.id,
                        provider_model_id=provider_model_id,
                        region=None,
                        service_tier="standard",
                        billing_mode="realtime",
                        context_min=tier.context_min,
                        context_max=tier.context_max,
                        currency="CNY",
                        exchange_rate_to_cny=1,
                        input_cost_per_million=tier.input_cost_per_million,
                        # DashScope implicit cache hits are generally billed at 20%;
                        # explicit cache creation is generally billed at 125%.
                        # This conservative default can be overridden per price version.
                        cache_read_cost_per_million=(tier.input_cost_per_million * Decimal("0.2")),
                        cache_write_cost_per_million=(tier.input_cost_per_million * Decimal("1.25")),
                        output_cost_per_million=tier.output_cost_per_million,
                        reasoning_cost_per_million=tier.output_cost_per_million,
                        source="official_price",
                        effective_from=now,
                        status="active",
                        created_id=self.auth.user.id,
                        updated_id=self.auth.user.id,
                    )
                )
                existing_tiers.add(key)
        await self.db.flush()

    @staticmethod
    async def _discover(
        account: ModelProviderAccountModel,
        template: ModelProviderTemplateModel,
        secrets: dict,
    ) -> list[dict[str, str | None]]:
        timeout = min(account.timeout_seconds, 30)
        endpoint = account.endpoint.rstrip("/")
        if template.protocol == "bedrock":
            import asyncio

            import boto3

            def list_bedrock() -> list[dict[str, str | None]]:
                client = boto3.client(
                    "bedrock",
                    region_name=secrets.get("region"),
                    aws_access_key_id=secrets.get("access_key"),
                    aws_secret_access_key=secrets.get("secret_key"),
                )
                return [
                    {"id": item["modelId"], "name": item.get("modelName") or item["modelId"], "owned_by": item.get("providerName")}
                    for item in client.list_foundation_models().get("modelSummaries", [])
                    if "TEXT" in item.get("outputModalities", [])
                ]

            return await asyncio.to_thread(list_bedrock)
        if template.protocol == "gemini":
            url = f"{endpoint}/v1beta/models"
            params = {"key": secrets.get("api_key", "")}
            headers: dict[str, str] = {}
        elif template.protocol == "anthropic":
            url = f"{endpoint}/v1/models"
            params = {}
            headers = {"x-api-key": str(secrets.get("api_key") or ""), "anthropic-version": "2023-06-01"}
        else:
            url = f"{endpoint}/models"
            params = {}
            headers = {"Authorization": f"Bearer {secrets.get('api_key', '')}"} if secrets.get("api_key") else {}
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers=headers, params=params)
        if response.status_code >= 400:
            raise CustomException(msg=f"连接失败（HTTP {response.status_code}）")
        body = response.json()
        source = body.get("models") if template.protocol == "gemini" else body.get("data")
        items = source or []
        result: list[dict[str, str | None]] = []
        for item in items:
            if template.protocol == "gemini":
                raw_id = str(item.get("name") or item.get("id") or "")
                model_id = raw_id.removeprefix("models/")
                display_name = item.get("displayName") or item.get("display_name") or model_id
            else:
                model_id = str(item.get("id") or item.get("name") or "")
                display_name = item.get("displayName") or item.get("display_name") or item.get("name") or model_id
            if model_id:
                result.append(
                    {
                        "id": model_id,
                        "name": str(display_name),
                        "owned_by": item.get("owned_by"),
                    }
                )
        return result

    async def set_account_status(self, account_id: int, data: ResourceStatusUpdate) -> ProviderAccountOut:
        account = await self.db.scalar(
            select(ModelProviderAccountModel).where(
                ModelProviderAccountModel.id == account_id,
                ModelProviderAccountModel.is_deleted == False,
            )
        )
        if not account:
            raise CustomException(msg="供应商账号不存在", status_code=404)
        if data.status == "active" and account.connection_status != "healthy":
            raise CustomException(msg="请先完成连接测试，再启用供应商账号")
        account.status = data.status
        account.updated_id = self.auth.user.id
        await self.db.flush()
        await _invalidate_model_config(self.redis, await self._app_ids_for_account(account_id))
        return ProviderAccountOut.model_validate(account)

    async def models(self) -> list[ModelCatalogOut]:
        rows = list(
            (
                await self.db.scalars(
                    select(ModelCatalogModel)
                    .where(ModelCatalogModel.is_deleted == False)
                    .order_by(
                        case((ModelCatalogModel.status == "active", 0), else_=1),
                        ModelCatalogModel.updated_time.desc(),
                        ModelCatalogModel.id.desc(),
                    )
                )
            ).all()
        )
        now = datetime.now(UTC)
        price_rows = (
            list(
                (
                    await self.db.scalars(
                        select(ModelPurchasePriceVersionModel)
                        .where(
                            ModelPurchasePriceVersionModel.catalog_model_id.in_([row.id for row in rows]),
                            ModelPurchasePriceVersionModel.context_min == 0,
                            ModelPurchasePriceVersionModel.region.is_(None),
                            ModelPurchasePriceVersionModel.service_tier == "standard",
                            ModelPurchasePriceVersionModel.billing_mode == "realtime",
                            ModelPurchasePriceVersionModel.status == "active",
                            ModelPurchasePriceVersionModel.effective_from <= now,
                            or_(
                                ModelPurchasePriceVersionModel.effective_until.is_(None),
                                ModelPurchasePriceVersionModel.effective_until > now,
                            ),
                            ModelPurchasePriceVersionModel.is_deleted == False,
                        )
                        .order_by(
                            ModelPurchasePriceVersionModel.effective_from.desc(),
                            ModelPurchasePriceVersionModel.id.desc(),
                        )
                    )
                ).all()
            )
            if rows
            else []
        )
        latest_prices: dict[int, ModelPurchasePriceVersionModel] = {}
        for price in price_rows:
            latest_prices.setdefault(price.catalog_model_id, price)

        result: list[ModelCatalogOut] = []
        for row in rows:
            item = ModelCatalogOut.model_validate(row)
            price = latest_prices.get(row.id)
            if price:
                exchange_rate = price.exchange_rate_to_cny
                item = item.model_copy(
                    update={
                        "input_cost_per_million": float(price.input_cost_per_million * exchange_rate),
                        "cache_read_cost_per_million": float(price.cache_read_cost_per_million * exchange_rate),
                        "cache_write_cost_per_million": float(price.cache_write_cost_per_million * exchange_rate),
                        "output_cost_per_million": float(price.output_cost_per_million * exchange_rate),
                        "reasoning_cost_per_million": float(price.reasoning_cost_per_million * exchange_rate),
                        "price_version_id": price.id,
                        "price_source": price.source,
                    }
                )
            result.append(item)
        return result

    async def create_model(self, data: ModelCatalogCreate) -> ModelCatalogOut:
        account = await self.db.scalar(select(ModelProviderAccountModel).where(ModelProviderAccountModel.id == data.provider_account_id, ModelProviderAccountModel.is_deleted == False))
        if not account:
            raise CustomException(msg="供应商账号不存在")
        if await self.db.scalar(
            select(ModelCatalogModel.id).where(
                ModelCatalogModel.provider_account_id == data.provider_account_id, ModelCatalogModel.provider_model_id == data.provider_model_id, ModelCatalogModel.is_deleted == False
            )
        ):
            raise CustomException(msg="该供应商账号下已存在相同模型ID")
        model = ModelCatalogModel(**data.model_dump(mode="json"), created_id=self.auth.user.id, updated_id=self.auth.user.id)
        model.speech_protocol = speech_adapter(model.provider_model_id, model.speech_protocol)
        if not model.speech_pricing:
            model.speech_pricing = official_speech_price(model.provider_model_id, account.endpoint)
        if model.speech_protocol:
            model.supports_stream = False
        self.db.add(model)
        await self.db.flush()
        return ModelCatalogOut.model_validate(model)

    async def update_model(self, model_id: int, data: ModelCatalogUpdate) -> ModelCatalogOut:
        model = await self.db.scalar(select(ModelCatalogModel).where(ModelCatalogModel.id == model_id, ModelCatalogModel.is_deleted == False))
        if not model:
            raise CustomException(msg="目录模型不存在", status_code=404)
        for key, value in data.model_dump(mode="json", exclude_unset=True).items():
            setattr(model, key, value)
        if speech_adapter(model.provider_model_id, model.speech_protocol):
            model.supports_stream = False
        model.updated_id = self.auth.user.id
        await self.db.flush()
        await _invalidate_model_config(self.redis, await self._app_ids_for_model(model_id))
        return ModelCatalogOut.model_validate(model)

    async def set_model_status(self, model_id: int, data: ResourceStatusUpdate) -> ModelCatalogOut:
        model = await self.db.scalar(select(ModelCatalogModel).where(ModelCatalogModel.id == model_id, ModelCatalogModel.is_deleted == False))
        if not model:
            raise CustomException(msg="目录模型不存在", status_code=404)
        if data.status == "active":
            is_speech = bool(speech_adapter(model.provider_model_id, model.speech_protocol))
            if is_speech:
                model.supports_stream = False
            if not is_speech and (float(model.input_cost_per_million) <= 0 or float(model.output_cost_per_million) <= 0):
                now = datetime.now(UTC)
                base_price = await self.db.scalar(
                    select(ModelPurchasePriceVersionModel)
                    .where(
                        ModelPurchasePriceVersionModel.catalog_model_id == model.id,
                        ModelPurchasePriceVersionModel.context_min == 0,
                        ModelPurchasePriceVersionModel.status == "active",
                        ModelPurchasePriceVersionModel.effective_from <= now,
                        or_(
                            ModelPurchasePriceVersionModel.effective_until.is_(None),
                            ModelPurchasePriceVersionModel.effective_until > now,
                        ),
                        ModelPurchasePriceVersionModel.input_cost_per_million > 0,
                        ModelPurchasePriceVersionModel.output_cost_per_million > 0,
                        ModelPurchasePriceVersionModel.is_deleted == False,
                    )
                    .order_by(ModelPurchasePriceVersionModel.effective_from.desc())
                )
                if not base_price:
                    raise CustomException(msg="请先配置该模型的真实输入、输出采购价格")
                model.input_cost_per_million = base_price.input_cost_per_million * base_price.exchange_rate_to_cny
                model.output_cost_per_million = base_price.output_cost_per_million * base_price.exchange_rate_to_cny
            account = await self.db.scalar(
                select(ModelProviderAccountModel).where(
                    ModelProviderAccountModel.id == model.provider_account_id,
                    ModelProviderAccountModel.is_deleted == False,
                )
            )
            if not account or account.connection_status != "healthy":
                raise CustomException(msg="请先完成供应商连接测试，再启用模型")
            if is_speech:
                speech_endpoint(account.endpoint, speech_adapter(model.provider_model_id, model.speech_protocol))
                if not model.speech_pricing:
                    raise CustomException(msg="请先配置语音采购价格，再启用模型")
            # A healthy provider is an implicit prerequisite of an enabled model.
            # Enabling both in one transaction avoids the confusing two-step flow
            # where a successful discovery still left every model unavailable.
            if account.status != "active":
                account.status = "active"
                account.updated_id = self.auth.user.id
        model.status = data.status
        model.updated_id = self.auth.user.id
        await self.db.flush()
        await _invalidate_model_config(self.redis, await self._app_ids_for_model(model_id))
        return ModelCatalogOut.model_validate(model)

    async def bindings(self) -> list[AppModelBindingOut]:
        rows = list(
            (
                await self.db.scalars(
                    select(AppModelBindingModel).where(AppModelBindingModel.app_id == self._app_id(), AppModelBindingModel.is_deleted == False).order_by(AppModelBindingModel.order.asc())
                )
            ).all()
        )
        return [AppModelBindingOut.model_validate(row) for row in rows]

    async def create_binding(self, data: AppModelBindingCreate) -> AppModelBindingOut:
        model = await self.db.scalar(
            select(ModelCatalogModel)
            .join(
                ModelProviderAccountModel,
                ModelProviderAccountModel.id == ModelCatalogModel.provider_account_id,
            )
            .where(
                ModelCatalogModel.id == data.catalog_model_id,
                ModelCatalogModel.status == "active",
                ModelCatalogModel.supports_stream == True,
                ModelCatalogModel.speech_protocol.is_(None),
                ModelCatalogModel.is_deleted == False,
                ModelProviderAccountModel.status == "active",
                ModelProviderAccountModel.connection_status == "healthy",
                ModelProviderAccountModel.is_deleted == False,
            )
        )
        if not model:
            raise CustomException(msg="只能授权连接正常、已启用且支持流式对话的模型")
        if data.is_default:
            await self.db.execute(AppModelBindingModel.__table__.update().where(AppModelBindingModel.app_id == self._app_id()).values(is_default=False))
        item = AppModelBindingModel(app_id=self._app_id(), **data.model_dump(), created_id=self.auth.user.id, updated_id=self.auth.user.id)
        self.db.add(item)
        await self.db.flush()
        await self._bootstrap_default_routes(item)
        await _invalidate_model_config(self.redis, {self._app_id()})
        return AppModelBindingOut.model_validate(item)

    async def _bootstrap_default_routes(self, binding: AppModelBindingModel) -> None:
        """Make the first active client authorization immediately usable.

        Operators can still edit every route afterwards.  This bootstrap only
        fills missing routes when the client has no route configuration yet,
        preventing the misleading "authorized but unavailable" state.
        """
        if binding.status != "active":
            return
        app_id = self._app_id()
        existing_codes = set(
            (
                await self.db.scalars(
                    select(AppModelRouteModel.business_code).where(
                        AppModelRouteModel.app_id == app_id,
                        AppModelRouteModel.is_deleted == False,
                    )
                )
            ).all()
        )
        if existing_codes:
            return
        existing_default = await self.db.scalar(
            select(AppModelBindingModel.id).where(
                AppModelBindingModel.app_id == app_id,
                AppModelBindingModel.id != binding.id,
                AppModelBindingModel.is_default == True,
                AppModelBindingModel.status == "active",
                AppModelBindingModel.is_deleted == False,
            )
        )
        if not existing_default:
            binding.is_default = True
        for business_code, name in _DEFAULT_BUSINESS_ROUTES:
            self.db.add(
                AppModelRouteModel(
                    app_id=app_id,
                    business_code=business_code,
                    name=name,
                    primary_binding_id=binding.id,
                    fallback_binding_ids=[],
                    timeout_seconds=120,
                    max_output_tokens=8192,
                    allow_tools=True,
                    allow_user_model=True,
                    status="active",
                    created_id=self.auth.user.id,
                    updated_id=self.auth.user.id,
                )
            )
        await self.db.flush()

    async def update_binding(self, binding_id: int, data: AppModelBindingUpdate) -> AppModelBindingOut:
        binding = await self.db.scalar(
            select(AppModelBindingModel).where(
                AppModelBindingModel.id == binding_id,
                AppModelBindingModel.app_id == self._app_id(),
                AppModelBindingModel.is_deleted == False,
            )
        )
        if not binding:
            raise CustomException(msg="客户端模型授权不存在", status_code=404)
        values = data.model_dump(exclude_unset=True)
        if values.get("is_default"):
            await self.db.execute(AppModelBindingModel.__table__.update().where(AppModelBindingModel.app_id == self._app_id()).values(is_default=False))
        for key, value in values.items():
            setattr(binding, key, value)
        binding.updated_id = self.auth.user.id
        await self.db.flush()
        await _invalidate_model_config(self.redis, {self._app_id()})
        return AppModelBindingOut.model_validate(binding)

    async def set_binding_status(self, binding_id: int, data: ResourceStatusUpdate) -> AppModelBindingOut:
        binding = await self.db.scalar(
            select(AppModelBindingModel).where(
                AppModelBindingModel.id == binding_id,
                AppModelBindingModel.app_id == self._app_id(),
                AppModelBindingModel.is_deleted == False,
            )
        )
        if not binding:
            raise CustomException(msg="客户端模型授权不存在", status_code=404)
        if data.status == "active":
            available = await self.db.scalar(
                select(ModelCatalogModel.id)
                .join(
                    ModelProviderAccountModel,
                    ModelProviderAccountModel.id == ModelCatalogModel.provider_account_id,
                )
                .where(
                    ModelCatalogModel.id == binding.catalog_model_id,
                    ModelCatalogModel.status == "active",
                    ModelCatalogModel.supports_stream == True,
                    ModelCatalogModel.speech_protocol.is_(None),
                    ModelCatalogModel.input_cost_per_million > 0,
                    ModelCatalogModel.output_cost_per_million > 0,
                    ModelCatalogModel.is_deleted == False,
                    ModelProviderAccountModel.status == "active",
                    ModelProviderAccountModel.connection_status == "healthy",
                    ModelProviderAccountModel.is_deleted == False,
                )
            )
            if not available:
                raise CustomException(msg="供应商或目录模型当前不可用，无法启用客户端授权")
        binding.status = data.status
        binding.updated_id = self.auth.user.id
        await self.db.flush()
        await _invalidate_model_config(self.redis, {self._app_id()})
        return AppModelBindingOut.model_validate(binding)

    async def routes(self) -> list[AppModelRouteOut]:
        rows = list(
            (await self.db.scalars(select(AppModelRouteModel).where(AppModelRouteModel.app_id == self._app_id(), AppModelRouteModel.is_deleted == False).order_by(AppModelRouteModel.id.asc()))).all()
        )
        return [AppModelRouteOut.model_validate(row) for row in rows]

    async def create_route(self, data: AppModelRouteCreate) -> AppModelRouteOut:
        from .generation_policy import GenerationSettings, validate_answer_budget, validate_candidate

        existing = await self.db.scalar(
            select(AppModelRouteModel).where(AppModelRouteModel.app_id == self._app_id(), AppModelRouteModel.business_code == data.business_code, AppModelRouteModel.is_deleted == False)
        )
        # An older operator form omits this new field. Only explicit null
        # disables an existing policy; ordinary route edits must not downgrade it.
        effective_policy = data.generation_settings
        try:
            if existing and "generation_settings" not in data.model_fields_set and existing.generation_settings is not None:
                effective_policy = GenerationSettings.model_validate(existing.generation_settings)
            validate_answer_budget(effective_policy, data.max_output_tokens)
        except ValueError:
            raise CustomException(msg="生成策略与答案上限不兼容，请显式检查当前配置", status_code=422) from None
        ids = [data.primary_binding_id, *data.fallback_binding_ids]
        available = set(
            (
                await self.db.scalars(
                    select(AppModelBindingModel.id).where(
                        AppModelBindingModel.app_id == self._app_id(), AppModelBindingModel.id.in_(ids), AppModelBindingModel.status == "active", AppModelBindingModel.is_deleted == False
                    )
                )
            ).all()
        )
        if available != set(ids):
            raise CustomException(msg="路由引用的模型未授权或未启用")
        route_models = list(
            (
                await self.db.scalars(
                    select(ModelCatalogModel)
                    .join(AppModelBindingModel, AppModelBindingModel.catalog_model_id == ModelCatalogModel.id)
                    .join(
                        ModelProviderAccountModel,
                        ModelProviderAccountModel.id == ModelCatalogModel.provider_account_id,
                    )
                    .where(
                        AppModelBindingModel.id.in_(ids),
                        AppModelBindingModel.app_id == self._app_id(),
                        ModelCatalogModel.status == "active",
                        ModelCatalogModel.is_deleted == False,
                        ModelProviderAccountModel.status == "active",
                        ModelProviderAccountModel.connection_status == "healthy",
                        ModelProviderAccountModel.is_deleted == False,
                    )
                )
            ).all()
        )
        if len(route_models) != len(set(ids)) or any(
            model.speech_protocol or not model.supports_stream or float(model.input_cost_per_million) <= 0 or float(model.output_cost_per_million) <= 0 for model in route_models
        ):
            raise CustomException(msg="路由模型必须支持流式调用并配置真实采购成本")
        for model in route_models:
            if effective_policy:
                protocol = await self.db.scalar(
                    select(ModelProviderTemplateModel.protocol)
                    .join(ModelProviderAccountModel, ModelProviderAccountModel.template_id == ModelProviderTemplateModel.id)
                    .where(ModelProviderAccountModel.id == model.provider_account_id, ModelProviderTemplateModel.status == "active", ModelProviderTemplateModel.is_deleted == False)
                )
                validate_candidate(effective_policy, model.provider_model_id, protocol)
        if existing:
            for key, value in data.model_dump().items():
                if key == "generation_settings" and key not in data.model_fields_set:
                    continue
                setattr(existing, key, value)
            existing.updated_id = self.auth.user.id
            item = existing
        else:
            item = AppModelRouteModel(app_id=self._app_id(), **data.model_dump(), created_id=self.auth.user.id, updated_id=self.auth.user.id)
            self.db.add(item)
        await self.db.flush()
        await _invalidate_model_config(self.redis, {self._app_id()})
        return AppModelRouteOut.model_validate(item)

    async def _app_ids_for_model(self, model_id: int) -> set[int]:
        return set(
            (
                await self.db.scalars(
                    select(AppModelBindingModel.app_id)
                    .where(
                        AppModelBindingModel.catalog_model_id == model_id,
                        AppModelBindingModel.is_deleted == False,
                    )
                    .distinct()
                )
            ).all()
        )

    async def _app_ids_for_account(self, account_id: int) -> set[int]:
        return set(
            (
                await self.db.scalars(
                    select(AppModelBindingModel.app_id)
                    .join(ModelCatalogModel, ModelCatalogModel.id == AppModelBindingModel.catalog_model_id)
                    .where(
                        ModelCatalogModel.provider_account_id == account_id,
                        ModelCatalogModel.is_deleted == False,
                        AppModelBindingModel.is_deleted == False,
                    )
                    .distinct()
                )
            ).all()
        )


class ClientModelService:
    def __init__(self, auth: AuthSchema, db: AsyncSession, redis: Redis | None = None) -> None:
        self.auth = auth
        self.db = db
        self.redis = redis

    async def config(self) -> ClientModelConfig:
        from app.api.v1.module_client.app.model_policy import allowed_modes, billing_user, current_mode, get_model_policy

        app = await get_model_policy(self.db, self.auth.app_id)
        mode = current_mode(app, await billing_user(self.db, app, self.auth.user.id))
        if mode != "credits" or "credits" not in allowed_modes(app):
            return ClientModelConfig(version=app.model_policy_version, platform_model_enabled=False, allow_custom_model=mode == "duration", service_status="unavailable", models=[], routes=[])
        app_id = self.auth.app_id or 0
        version = await _model_config_version(self.redis, app_id)
        cache_key = _MODEL_CONFIG_CACHE_KEY.format(app_id=app_id, version=version)
        if self.redis is not None:
            cached = await RedisCURD(self.redis).get(cache_key)
            if cached:
                try:
                    return ClientModelConfig.model_validate_json(cached)
                except (TypeError, ValueError):
                    await RedisCURD(self.redis).delete(cache_key)
        bindings = list(
            (
                await self.db.scalars(
                    select(AppModelBindingModel)
                    .where(
                        AppModelBindingModel.app_id == app_id,
                        AppModelBindingModel.status == "active",
                        AppModelBindingModel.is_deleted == False,
                    )
                    .order_by(AppModelBindingModel.order.asc())
                )
            ).all()
        )
        catalog_ids = [item.catalog_model_id for item in bindings]
        catalog = (
            []
            if not catalog_ids
            else list(
                (
                    await self.db.scalars(
                        select(ModelCatalogModel).where(
                            ModelCatalogModel.id.in_(catalog_ids),
                            ModelCatalogModel.status == "active",
                            ModelCatalogModel.is_deleted == False,
                        )
                    )
                ).all()
            )
        )
        catalog_map = {item.id: item for item in catalog}
        binding_map = {item.id: item for item in bindings if item.catalog_model_id in catalog_map}
        route_rows = list(
            (
                await self.db.scalars(
                    select(AppModelRouteModel).where(
                        AppModelRouteModel.app_id == app_id,
                        AppModelRouteModel.status == "active",
                        AppModelRouteModel.is_deleted == False,
                    )
                )
            ).all()
        )
        routes: list[ClientModelRoute] = []
        for route in route_rows:
            primary = binding_map.get(route.primary_binding_id)
            if not primary:
                continue
            fallbacks = [binding_map[binding_id].public_model_code for binding_id in route.fallback_binding_ids if binding_id in binding_map]
            routes.append(
                ClientModelRoute(
                    business_code=route.business_code,
                    name=route.name,
                    primary_model_code=primary.public_model_code,
                    primary_model_name=primary.client_display_name,
                    fallback_model_codes=fallbacks,
                    timeout_seconds=route.timeout_seconds,
                    max_output_tokens=route.max_output_tokens,
                    generation_settings=route.generation_settings,
                    generation_policy_status="GOVERNED" if route.generation_settings is not None else "LEGACY_UNMANAGED",
                    allow_tools=route.allow_tools,
                    allow_user_model=route.allow_user_model,
                )
            )
        models = [
            ClientModelOption(
                code=item.public_model_code,
                name=item.client_display_name,
                context_window=(catalog_map[item.catalog_model_id].context_length if (catalog_map[item.catalog_model_id].context_length or 0) > 0 else None),
                is_default=item.is_default,
                user_selectable=item.user_selectable,
                supports_tools=catalog_map[item.catalog_model_id].supports_tools,
                supports_vision=catalog_map[item.catalog_model_id].supports_vision,
                supports_pdf=catalog_map[item.catalog_model_id].supports_pdf,
                supports_thinking=catalog_map[item.catalog_model_id].provider_model_id in SUPPORTED_MODELS,
            )
            for item in bindings
            if item.catalog_model_id in catalog_map and item.visible
        ]
        updated = max((item.updated_time for item in [*bindings, *route_rows]), default=None)
        result = ClientModelConfig(
            version=version,
            service_status="available" if routes else "unavailable",
            updated_at=updated,
            models=models,
            routes=routes,
        )
        if self.redis is not None:
            await RedisCURD(self.redis).set(cache_key, result.model_dump_json(), expire=_MODEL_CONFIG_CACHE_TTL)
        return result

    @staticmethod
    def runtime_token(client_access_token: str, *, mode_version: int | None = None, policy_version: int | None = None) -> RuntimeTokenOut:
        payload = decode_access_token(client_access_token)
        if payload.actor_type != "client" or payload.is_refresh or not payload.app_id:
            raise CustomException(msg="客户端令牌无效", status_code=401)
        expires = 600
        token = create_access_token(
            JWTPayloadSchema(sub=payload.sub, actor_type="runtime", app_id=payload.app_id, mode_version=mode_version, policy_version=policy_version, exp=datetime.now(UTC) + timedelta(seconds=expires))
        )
        return RuntimeTokenOut(token=token, expires_in=expires)
