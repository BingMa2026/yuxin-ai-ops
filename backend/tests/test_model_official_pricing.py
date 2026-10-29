import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.v1.module_client.app.model import ClientAppModel
from app.api.v1.module_model_gateway.finance_service import ModelFinanceService
from app.api.v1.module_model_gateway.model import (
    AppModelRouteModel,
    ModelCatalogModel,
    ModelProviderAccountModel,
    ModelProviderTemplateModel,
    ModelPurchasePriceVersionModel,
)
from app.api.v1.module_model_gateway.official_pricing import (
    discovered_model_capabilities,
    official_model_pricing,
)
from app.api.v1.module_model_gateway.schema import AppModelBindingCreate, PurchasePriceCreate, ResourceStatusUpdate
from app.api.v1.module_model_gateway.secret_codec import encrypt_settings
from app.api.v1.module_model_gateway.service import ModelAdminService
from app.core.base_schema import AuthSchema, CoreUserSchema
from app.core.database import async_db_session


def test_qwen_official_pricing_uses_exact_versioned_tiers() -> None:
    pricing = official_model_pricing("qwen", "qwen3-max")

    assert pricing is not None
    assert pricing.context_length == 262_144
    assert len(pricing.tiers) == 3
    assert pricing.tiers[0].input_cost_per_million == Decimal("2.5")
    assert pricing.tiers[0].output_cost_per_million == Decimal("10")
    assert pricing.tiers[-1].context_min == 131_073
    assert pricing.tiers[-1].output_cost_per_million == Decimal("28")


def test_unknown_model_does_not_receive_a_guessed_price() -> None:
    assert official_model_pricing("qwen", "qwen-future-unknown") is None
    assert official_model_pricing("openai", "qwen3-max") is None


def test_discovery_marks_non_chat_resources_conservatively() -> None:
    assert discovered_model_capabilities("qwen", "qwen3.7-max").supports_stream is True
    assert discovered_model_capabilities("qwen", "qwen-vl-max").supports_vision is True
    assert discovered_model_capabilities("qwen", "qwen3-tts-flash").supports_stream is False
    assert discovered_model_capabilities("qwen", "text-embedding-v4").supports_stream is False
    assert discovered_model_capabilities("qwen", "wan2.6-t2v").supports_stream is False


@pytest.mark.asyncio
async def test_discovery_syncs_exact_prices_and_keeps_context_tiers(
    test_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del test_client

    async def fake_discover(*_args, **_kwargs):
        return [
            {"id": "qwen3-max", "name": "Qwen3 Max", "owned_by": "qwen"},
            {"id": "qwen3-tts-flash", "name": "Qwen TTS", "owned_by": "qwen"},
        ]

    monkeypatch.setattr(ModelAdminService, "_discover", staticmethod(fake_discover))
    auth = AuthSchema(user=CoreUserSchema(id=1, username="admin"), actor_type="staff")
    suffix = uuid.uuid4().hex[:8]

    async with async_db_session() as db, db.begin():
        template = await db.scalar(select(ModelProviderTemplateModel).where(ModelProviderTemplateModel.code == "qwen"))
        assert template is not None
        account = ModelProviderAccountModel(
            template_id=template.id,
            code=f"qwen_price_{suffix}",
            name="千问价格同步测试",
            endpoint=template.default_endpoint or "https://dashscope.aliyuncs.com/compatible-mode/v1",
            settings_cipher=encrypt_settings({"api_key": "test-only"}),
            masked_summary={"api_key": "••••only"},
            status="inactive",
            connection_status="untested",
        )
        db.add(account)
        await db.flush()

        service = ModelAdminService(auth, db)
        discovered = await service.discover_models(account.id)
        assert account.connection_status == "healthy"
        assert sum(item.price_matched for item in discovered) == 1

        chat_model = await db.scalar(
            select(ModelCatalogModel).where(
                ModelCatalogModel.provider_account_id == account.id,
                ModelCatalogModel.provider_model_id == "qwen3-max",
            )
        )
        tts_model = await db.scalar(
            select(ModelCatalogModel).where(
                ModelCatalogModel.provider_account_id == account.id,
                ModelCatalogModel.provider_model_id == "qwen3-tts-flash",
            )
        )
        assert chat_model is not None and tts_model is not None
        assert Decimal(str(chat_model.input_cost_per_million)) == Decimal("2.5")
        assert Decimal(str(chat_model.output_cost_per_million)) == Decimal("10")
        assert tts_model.supports_stream is False

        await service.discover_models(account.id)
        price_count = await db.scalar(
            select(func.count(ModelPurchasePriceVersionModel.id)).where(
                ModelPurchasePriceVersionModel.catalog_model_id == chat_model.id,
                ModelPurchasePriceVersionModel.status == "active",
            )
        )
        assert price_count == 3

        await ModelFinanceService(auth, db).create_price(
            account.id,
            PurchasePriceCreate(
                catalog_model_id=chat_model.id,
                context_max=32_768,
                input_cost_per_million=3,
                output_cost_per_million=12,
                effective_from=chat_model.updated_time,
            ),
        )
        active_prices = list(
            (
                await db.scalars(
                    select(ModelPurchasePriceVersionModel).where(
                        ModelPurchasePriceVersionModel.catalog_model_id == chat_model.id,
                        ModelPurchasePriceVersionModel.status == "active",
                    )
                )
            ).all()
        )
        assert len(active_prices) == 3
        assert Decimal(str(chat_model.input_cost_per_million)) == Decimal("3")
        assert Decimal(str(chat_model.output_cost_per_million)) == Decimal("12")

        enabled = await service.set_model_status(
            chat_model.id,
            ResourceStatusUpdate(status="active"),
        )
        assert enabled.status == "active"
        assert account.status == "active"

        catalog_rows = await service.models()
        catalog_item = next(item for item in catalog_rows if item.id == chat_model.id)
        assert catalog_item.price_source == "manual"
        assert catalog_item.price_version_id is not None
        assert catalog_item.input_cost_per_million == 3
        assert catalog_item.cache_read_cost_per_million == 0
        assert catalog_item.cache_write_cost_per_million == 0
        assert catalog_item.output_cost_per_million == 12

        app = ClientAppModel(service_mode="credits_only",
            code=f"route_app_{suffix}",
            name="路由初始化测试客户端",
            status="active",
        )
        db.add(app)
        await db.flush()
        app_auth = AuthSchema(
            user=CoreUserSchema(id=1, username="admin"),
            actor_type="staff",
            app_id=app.id,
        )
        binding = await ModelAdminService(app_auth, db).create_binding(
            AppModelBindingCreate(
                catalog_model_id=chat_model.id,
                public_model_code=f"qwen-{suffix}",
                client_display_name="千问默认模型",
                status="active",
            )
        )
        routes = list(
            (
                await db.scalars(
                    select(AppModelRouteModel).where(
                        AppModelRouteModel.app_id == app.id,
                        AppModelRouteModel.primary_binding_id == binding.id,
                    )
                )
            ).all()
        )
        assert binding.is_default is True
        assert {route.business_code for route in routes} == {
            "chat_default",
            "document_intelligence",
            "semantic_review",
        }
