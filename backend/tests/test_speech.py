import io
import wave
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api.v1.module_speech import provider
from app.api.v1.module_speech.capabilities import speech_adapter, speech_endpoint
from app.api.v1.module_speech.official_prices import PRICES, duration_rate, official_speech_price
from app.core.exceptions import CustomException


def wav(seconds=1, rate=16000):
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        writer.writeframes(b"\0\0" * int(seconds * rate))
    return output.getvalue()


@pytest.mark.parametrize("audio", [b"not audio", wav(0.05), wav(61), wav(rate=44100), wav()[:-3]], ids=["not-audio", "short", "long", "sample-rate", "truncated"])
def test_invalid_recordings_rejected(audio):
    with pytest.raises(CustomException):
        provider.inspect_audio(audio, 60)


def test_protocols_accept_new_model_names_and_prices_do_not_guess_future_rates():
    assert speech_adapter("vendor-future-2030", "openai_transcriptions") == "openai_transcriptions"
    assert speech_adapter("qwen3-asr-flash-realtime-2030-01-01") == "qwen_realtime"
    assert speech_adapter("qwen-audio-3.0-asr-flash") == "dashscope_asr"
    assert speech_adapter("fun-asr-flash-2026-06-15") == "dashscope_asr"
    assert speech_adapter("paraformer-realtime-8k-v2") == "dashscope_realtime"
    assert speech_adapter("qwen3-tts-flash") is None
    assert official_speech_price("qwen3-asr-flash-2030-01-01", "https://dashscope.aliyuncs.com") is None
    assert official_speech_price("qwen3-asr-flash", "https://dashscope-intl.aliyuncs.com") is None
    assert duration_rate(PRICES["qwen3-asr-flash"]) == Decimal("0.0132")
    assert duration_rate(PRICES["qwen3.5-omni-plus"]) is None


@pytest.mark.parametrize(
    "endpoint", ["https://dashscope.aliyuncs.com.attacker.test", "http://dashscope.aliyuncs.com", "https://user:password@dashscope.aliyuncs.com", "https://dashscope.aliyuncs.com:wrong"]
)
def test_provider_endpoint_rejects_bad_addresses(endpoint):
    with pytest.raises(CustomException):
        speech_endpoint(endpoint)


@pytest.fixture
async def speech_setup(test_client):
    from app.api.v1.module_client.app.model import ClientAppModel
    from app.api.v1.module_client.user.model import ClientUserModel
    from app.api.v1.module_model_gateway.model import ModelCatalogModel, ModelProviderAccountModel, ModelProviderTemplateModel
    from app.api.v1.module_model_gateway.secret_codec import encrypt_settings
    from app.core.base_schema import AuthSchema, CoreUserSchema
    from app.core.database import async_db_session

    async with async_db_session() as db:
        app = ClientAppModel(service_mode="credits_only", code=f"speech_{uuid4().hex}", name="语音测试", status="active")
        template = ModelProviderTemplateModel(code=f"speech_{uuid4().hex}", name="语音供应商", protocol="openai_compatible", status="active")
        db.add_all([app, template])
        await db.flush()
        user = ClientUserModel(app_id=app.id, username="speech_user", password_hash="test-only", status="active")
        account = ModelProviderAccountModel(
            template_id=template.id,
            code=uuid4().hex,
            name="语音测试账号",
            endpoint="https://dashscope.aliyuncs.com/compatible-mode/v1",
            settings_cipher=encrypt_settings({"api_key": "test-only-secret"}),
            status="active",
            connection_status="healthy",
        )
        db.add_all([user, account])
        await db.flush()
        model = ModelCatalogModel(provider_account_id=account.id, provider_model_id="qwen3-asr-flash", display_name="转写", speech_pricing=PRICES["qwen3-asr-flash"], status="inactive")
        db.add(model)
        await db.flush()
        auth = AuthSchema(app_id=app.id, user=CoreUserSchema(id=user.id, username=user.username), actor_type="client")
        yield db, auth, model, account
        await db.rollback()


async def test_enable_asr_without_fake_chat_prices_and_reject_unpriced(speech_setup):
    from app.api.v1.module_model_gateway.schema import AppModelBindingCreate, ResourceStatusUpdate
    from app.api.v1.module_model_gateway.service import ModelAdminService

    db, auth, model, _ = speech_setup
    service = ModelAdminService(auth, db)
    await service.set_model_status(model.id, ResourceStatusUpdate(status="active"))
    assert model.status == "active" and not model.supports_stream
    assert model.input_cost_per_million == model.output_cost_per_million == 0
    with pytest.raises(CustomException):
        await service.create_binding(AppModelBindingCreate(catalog_model_id=model.id, public_model_code="voice", client_display_name="错误对话绑定"))
    model.speech_pricing = None
    with pytest.raises(CustomException, match="语音采购价格"):
        await service.set_model_status(model.id, ResourceStatusUpdate(status="active"))


async def test_config_scope_revision_transcription_quota_and_no_content_storage(speech_setup, monkeypatch):
    from app.api.v1.module_speech.model import SpeechUsageModel
    from app.api.v1.module_speech.schema import SpeechConfigInput
    from app.api.v1.module_speech.service import SpeechService

    db, auth, model, _ = speech_setup
    model.status = "active"
    await db.flush()
    service = SpeechService(auth, db)
    assert not (await service.capability()).available
    saved = await service.save(SpeechConfigInput(catalog_model_id=model.id, status="active", daily_limit_seconds=60))
    assert saved.revision == 1
    with pytest.raises(CustomException, match="已被修改"):
        await service.save(SpeechConfigInput(catalog_model_id=model.id, status="active"))
    with pytest.raises(CustomException):
        SpeechService(auth.model_copy(update={"app_id": None}), db)
    other = SpeechService(auth.model_copy(update={"app_id": 999999}), db)
    assert not (await other.capability()).available
    upstream = AsyncMock(return_value="请分析招标文件")
    monkeypatch.setattr(provider, "transcribe", upstream)
    request_id = uuid4().hex
    result = await service.transcribe(wav(), request_id)
    assert result.text == "请分析招标文件"
    usage = await db.scalar(select(SpeechUsageModel).where(SpeechUsageModel.request_id == request_id))
    assert usage.status == "succeeded" and usage.estimated_cost_yuan == Decimal("0.00022000")
    assert not any("audio" in key or "transcript" in key or key == "text" for key in usage.__table__.columns.keys())
    with pytest.raises(CustomException, match="重复识别"):
        await service.transcribe(wav(), request_id)
    with pytest.raises(CustomException, match="时长已用完"):
        await service.transcribe(wav(60), uuid4().hex)
    upstream.assert_awaited_once()
    upstream.side_effect = RuntimeError("secret transcript supplier-key")
    with pytest.raises(CustomException, match="语音识别未完成") as error:
        await service.transcribe(wav(), uuid4().hex)
    assert "supplier-key" not in str(error.value)
    assert (await db.scalars(select(SpeechUsageModel).where(SpeechUsageModel.app_id == auth.app_id, SpeechUsageModel.status == "failed"))).one().error_category == "upstream_error"


def test_speech_routes_require_correct_identity_and_validate_scope(test_client):
    assert test_client.get("/client/speech/capability").status_code in (401, 403)
    login = test_client.post("/system/auth/login", data={"username": "admin", "password": "admin123"}).json()["data"]
    staff = {"Authorization": f"Bearer {login['access_token']}"}
    assert test_client.get("/client/speech/capability", headers=staff).status_code in (401, 403)
    assert test_client.get("/operations/models/speech/config", headers=staff).status_code == 200
    assert test_client.put("/operations/models/speech/config", headers=staff, json={"app_id": 42}).status_code == 422
