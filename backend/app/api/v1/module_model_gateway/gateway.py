import asyncio
import json
import math
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

import httpx
from sqlalchemy import select

from app.api.v1.module_billing.service import CreditService
from app.core.base_schema import AuthSchema
from app.core.database import async_db_session
from app.core.exceptions import CustomException

from .generation_deadline import bounded_lines, bounded_stream, within_deadline
from .generation_policy import (
    SUPPORTED_MODELS,
    GenerationSettings,
    complete_usage_report,
    effective_thinking_settings,
    error_details,
    estimate_text_input,
    execution_snapshot,
    payload_fields,
    safe_to_fallback,
    validate_answer_budget,
    validate_candidate,
    validate_request,
)
from .image_reservation import estimate_qwen38_image_request
from .model import (
    AppModelBindingModel,
    AppModelRouteModel,
    ModelCatalogModel,
    ModelProviderAccountModel,
    ModelProviderTemplateModel,
    ModelPurchasePriceVersionModel,
    ModelUsageModel,
)
from .schema import RuntimeCompletionOut, RuntimeCompletionRequest
from .secret_codec import decrypt_settings
from .upstream_diagnostics import log_upstream_failure, read_error_response

_provider_http_client: httpx.AsyncClient | None = None


def get_provider_http_client() -> httpx.AsyncClient:
    """Return the process-wide upstream client so TLS connections are reused."""
    global _provider_http_client
    if _provider_http_client is None or getattr(_provider_http_client, "is_closed", False):
        _provider_http_client = httpx.AsyncClient(
            timeout=None,
            limits=httpx.Limits(max_connections=200, max_keepalive_connections=50, keepalive_expiry=30),
        )
    return _provider_http_client


async def close_provider_http_client() -> None:
    global _provider_http_client
    if _provider_http_client is not None and not getattr(_provider_http_client, "is_closed", False):
        await _provider_http_client.aclose()
    _provider_http_client = None


@dataclass(frozen=True, slots=True)
class ResolvedBinding:
    binding_id: int
    public_model_code: str
    provider_account_id: int
    catalog_model_id: int
    provider_model_id: str
    endpoint: str
    api_key: str
    protocol: str
    timeout_seconds: int
    input_rate: int
    output_rate: int
    minimum_credits: int
    input_cost_per_million: Decimal
    cache_read_cost_per_million: Decimal
    cache_write_cost_per_million: Decimal
    output_cost_per_million: Decimal
    reasoning_cost_per_million: Decimal
    price_version_id: int | None
    price_currency: str
    exchange_rate_to_cny: Decimal
    price_source: str


@dataclass(frozen=True, slots=True)
class PreparedRequest:
    candidates: list[ResolvedBinding]
    input_tokens_estimate: int
    max_output_tokens: int
    reserved_credits: int
    reserved_cost_yuan: Decimal
    cost_billing: bool
    started_at: float
    generation_settings: GenerationSettings | None = None
    replay_payload: dict | None = None


def _estimate_tokens(value: object) -> int:
    serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return max(1, math.ceil(len(serialized) / 4))


def _finish_reason(choice: dict) -> str | None:
    value = choice.get("finish_reason")
    if isinstance(value, str) and 0 < len(value.strip()) <= 64:
        return value.strip().lower()
    return None


def _invalid_image_url_error(exc: Exception) -> bool:
    """识别供应商对图片地址的拒绝，不暴露原始响应正文。"""

    if not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code not in {400, 422}:
        return False
    try:
        detail = exc.response.text[:2048].casefold()
    except httpx.ResponseNotRead:
        return False
    invalid_parameter = "invalid_parameter_error" in detail or "internalerror.algo.invalidparameter" in detail
    invalid_url = "provided url" in detail or "url does not appear to be valid" in detail or ("invalid" in detail and "url" in detail)
    return invalid_parameter and invalid_url


def _credits(binding: ResolvedBinding, input_tokens: int, output_tokens: int) -> int:
    usage = math.ceil(input_tokens * binding.input_rate / 1000) + math.ceil(output_tokens * binding.output_rate / 1000)
    return max(binding.minimum_credits, usage)


def _normalized_usage(usage: dict, *, input_fallback: int, output_fallback: int) -> tuple[dict, bool]:
    """Normalize OpenAI-compatible usage without double charging cached tokens."""
    if not isinstance(usage, dict):
        raise ValueError("Invalid usage envelope")
    prompt_details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    completion_details = usage.get("completion_tokens_details") or usage.get("output_tokens_details") or {}
    if not isinstance(prompt_details, dict) or not isinstance(completion_details, dict):
        raise ValueError("Invalid usage details")
    has_actual = bool(usage) and any(key in usage for key in ("prompt_tokens", "completion_tokens", "input_tokens", "output_tokens"))
    input_tokens = int(next((usage[key] for key in ("prompt_tokens", "input_tokens") if usage.get(key) is not None), input_fallback))
    output_tokens = int(next((usage[key] for key in ("completion_tokens", "output_tokens") if usage.get(key) is not None), output_fallback))
    cache_read = int(prompt_details.get("cached_tokens") or usage.get("cache_read_input_tokens") or 0)
    cache_write = int(prompt_details.get("cache_write_tokens") or usage.get("cache_creation_input_tokens") or 0)
    reasoning = int(completion_details.get("reasoning_tokens") or usage.get("reasoning_tokens") or 0)
    cache_read = min(max(cache_read, 0), max(input_tokens, 0))
    cache_write = min(max(cache_write, 0), max(input_tokens - cache_read, 0))
    return (
        {
            "input_tokens": max(input_tokens, 0),
            "uncached_input_tokens": max(input_tokens - cache_read - cache_write, 0),
            "cache_read_tokens": cache_read,
            "cache_write_tokens": cache_write,
            "output_tokens": max(output_tokens, 0),
            "reasoning_tokens": min(max(reasoning, 0), max(output_tokens, 0)),
        },
        has_actual,
    )


def _provider_cost_original(binding: ResolvedBinding, usage: dict) -> Decimal:
    output_without_reasoning = max(int(usage.get("output_tokens") or 0) - int(usage.get("reasoning_tokens") or 0), 0)
    cost = (
        Decimal(int(usage.get("uncached_input_tokens") or 0)) * binding.input_cost_per_million
        + Decimal(int(usage.get("cache_read_tokens") or 0)) * binding.cache_read_cost_per_million
        + Decimal(int(usage.get("cache_write_tokens") or 0)) * binding.cache_write_cost_per_million
        + Decimal(output_without_reasoning) * binding.output_cost_per_million
        + Decimal(int(usage.get("reasoning_tokens") or 0)) * (binding.reasoning_cost_per_million or binding.output_cost_per_million)
    ) / Decimal(1_000_000)
    return cost.quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)


def _provider_cost_yuan(binding: ResolvedBinding, input_tokens: int, output_tokens: int) -> Decimal:
    usage, _ = _normalized_usage({}, input_fallback=input_tokens, output_fallback=output_tokens)
    return (_provider_cost_original(binding, usage) * binding.exchange_rate_to_cny).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)


def _price_snapshot(binding: ResolvedBinding) -> dict:
    return {
        "price_version_id": binding.price_version_id,
        "currency": binding.price_currency,
        "exchange_rate_to_cny": str(binding.exchange_rate_to_cny),
        "input_cost_per_million": str(binding.input_cost_per_million),
        "cache_read_cost_per_million": str(binding.cache_read_cost_per_million),
        "cache_write_cost_per_million": str(binding.cache_write_cost_per_million),
        "output_cost_per_million": str(binding.output_cost_per_million),
        "reasoning_cost_per_million": str(binding.reasoning_cost_per_million),
        "source": binding.price_source,
    }


def _reservation_credits(candidates: list[ResolvedBinding], input_tokens: int, output_tokens: int, *, generation_settings: GenerationSettings | None = None) -> int:
    thinking = generation_settings.thinking_budget_tokens if generation_settings else 0
    return max(_credits(item, input_tokens, output_tokens + thinking) for item in candidates)


def _reservation_cost(candidates: list[ResolvedBinding], input_tokens: int, output_tokens: int, *, generation_settings: GenerationSettings | None = None) -> Decimal:
    if generation_settings:
        thinking = generation_settings.thinking_budget_tokens
        return max(
            (
                (
                    Decimal(input_tokens) * max(item.input_cost_per_million, item.cache_read_cost_per_million, item.cache_write_cost_per_million)
                    + Decimal(output_tokens) * item.output_cost_per_million
                    + Decimal(thinking) * (item.reasoning_cost_per_million or item.output_cost_per_million)
                )
                / Decimal(1_000_000)
                * item.exchange_rate_to_cny
            ).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
            for item in candidates
        )
    return max(_provider_cost_yuan(item, input_tokens, output_tokens) for item in candidates)


def _affordable_output_tokens(
    candidates: list[ResolvedBinding],
    input_tokens: int,
    requested_output_tokens: int,
    available_credits: int,
) -> int:
    """Largest output budget affordable even if routing falls back to the priciest candidate."""
    if _reservation_credits(candidates, input_tokens, 1) > available_credits:
        return 0
    low, high = 1, requested_output_tokens
    while low < high:
        middle = (low + high + 1) // 2
        if _reservation_credits(candidates, input_tokens, middle) <= available_credits:
            low = middle
        else:
            high = middle - 1
    return low


def _affordable_output_tokens_by_cost(
    candidates: list[ResolvedBinding],
    input_tokens: int,
    requested_output_tokens: int,
    cost_capacity: Decimal,
) -> int:
    if _reservation_cost(candidates, input_tokens, 1) > cost_capacity:
        return 0
    low, high = 1, requested_output_tokens
    while low < high:
        middle = (low + high + 1) // 2
        if _reservation_cost(candidates, input_tokens, middle) <= cost_capacity:
            low = middle
        else:
            high = middle - 1
    return low


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n".encode()


class ModelGatewayService:
    """受控模型网关：用量入账，成功输出另存加密恢复日志。"""

    def __init__(self, auth: AuthSchema) -> None:
        if auth.actor_type != "runtime" or not auth.app_id:
            raise CustomException(msg="仅模型运行令牌可调用网关", status_code=401)
        self.auth = auth

    async def _resolve(self, data: RuntimeCompletionRequest) -> PreparedRequest:
        started_at = time.perf_counter()
        now = datetime.now(UTC)
        input_estimate = _estimate_tokens(
            {
                "messages": [message.model_dump(exclude_none=True) for message in data.messages],
                "tools": data.tools,
            }
        )
        async with async_db_session() as db, db.begin():
            from app.api.v1.module_client.app.model_policy import require_platform_model

            await require_platform_model(db, self.auth.app_id, user_id=self.auth.user.id)
            if data.cloud_task_id:
                from app.api.v1.module_growth.task_service import TaskService

                task = await TaskService(db, self.auth.app_id).get(data.cloud_task_id, self.auth.user.id)
                expected = {"document_intelligence"} if task.kind == "tender_analysis" else {"document_intelligence", "semantic_review"}
                if task.status != "started" or data.business_code not in expected:
                    raise CustomException(msg="任务状态或业务模型不匹配", status_code=409)
            route = await db.scalar(
                select(AppModelRouteModel).where(
                    AppModelRouteModel.app_id == self.auth.app_id,
                    AppModelRouteModel.business_code == data.business_code,
                    AppModelRouteModel.status == "active",
                    AppModelRouteModel.is_deleted == False,
                )
            )
            if not route:
                raise CustomException(msg="当前业务暂未配置可用模型", status_code=503)
            if data.tools and not route.allow_tools:
                raise CustomException(msg="当前业务不允许工具调用", status_code=403)
            if route.max_output_tokens and data.max_output_tokens and data.max_output_tokens > route.max_output_tokens:
                raise CustomException(msg=f"当前业务最多输出 {route.max_output_tokens} tokens")
            try:
                generation_settings = GenerationSettings.model_validate(route.generation_settings) if route.generation_settings is not None else None
                validate_answer_budget(generation_settings, route.max_output_tokens)
            except ValueError:
                raise CustomException(msg="路由生成策略配置无效，请联系运营人员", status_code=422) from None
            generation_settings = effective_thinking_settings(
                generation_settings,
                data.thinking,
                allow_legacy_business=data.business_code in {"document_intelligence", "semantic_review"},
            )
            validate_request(generation_settings, data)
            if generation_settings:
                input_estimate = estimate_text_input(data)

            binding_ids: list[int]
            if data.model:
                if not route.allow_user_model:
                    raise CustomException(msg="当前业务不允许用户选择模型", status_code=403)
                selected = await db.scalar(
                    select(AppModelBindingModel).where(
                        AppModelBindingModel.app_id == self.auth.app_id,
                        AppModelBindingModel.public_model_code == data.model,
                        AppModelBindingModel.user_selectable == True,
                        AppModelBindingModel.status == "active",
                        AppModelBindingModel.is_deleted == False,
                    )
                )
                if not selected:
                    raise CustomException(msg="所选模型不可用", status_code=404)
                binding_ids = [selected.id]
                if selected.fallback_binding_id:
                    binding_ids.append(selected.fallback_binding_id)
                binding_ids.extend(route.fallback_binding_ids)
            else:
                binding_ids = [route.primary_binding_id, *route.fallback_binding_ids]
            binding_ids = list(dict.fromkeys(binding_ids))

            candidates: list[ResolvedBinding] = []
            for binding_id in binding_ids:
                binding = await db.scalar(
                    select(AppModelBindingModel).where(
                        AppModelBindingModel.id == binding_id,
                        AppModelBindingModel.app_id == self.auth.app_id,
                        AppModelBindingModel.status == "active",
                        AppModelBindingModel.is_deleted == False,
                    )
                )
                if not binding:
                    continue
                if binding.effective_from and binding.effective_from > now:
                    continue
                if binding.effective_until and binding.effective_until <= now:
                    continue
                catalog = await db.scalar(
                    select(ModelCatalogModel).where(
                        ModelCatalogModel.id == binding.catalog_model_id,
                        ModelCatalogModel.status == "active",
                        ModelCatalogModel.is_deleted == False,
                    )
                )
                if not catalog or catalog.speech_protocol or not catalog.supports_stream:
                    continue
                validate_candidate(generation_settings, catalog.provider_model_id)
                if (
                    generation_settings
                    and catalog.context_length
                    and input_estimate + generation_settings.thinking_budget_tokens + (data.max_output_tokens or route.max_output_tokens) > catalog.context_length
                ):
                    raise CustomException(msg="本次输入、思考和答案预算超过所选模型的上下文容量", status_code=422)
                account = await db.scalar(
                    select(ModelProviderAccountModel).where(
                        ModelProviderAccountModel.id == catalog.provider_account_id,
                        ModelProviderAccountModel.status == "active",
                        ModelProviderAccountModel.is_deleted == False,
                    )
                )
                if not account:
                    continue
                template = await db.scalar(
                    select(ModelProviderTemplateModel).where(
                        ModelProviderTemplateModel.id == account.template_id,
                        ModelProviderTemplateModel.status == "active",
                        ModelProviderTemplateModel.is_deleted == False,
                    )
                )
                if not template or template.protocol != "openai_compatible":
                    if generation_settings:
                        raise CustomException(msg="生成策略要求支持的模型供应商协议", status_code=422)
                    continue
                secrets = decrypt_settings(account.settings_cipher)
                price = await db.scalar(
                    select(ModelPurchasePriceVersionModel)
                    .where(
                        ModelPurchasePriceVersionModel.catalog_model_id == catalog.id,
                        ModelPurchasePriceVersionModel.status == "active",
                        ModelPurchasePriceVersionModel.effective_from <= now,
                        (ModelPurchasePriceVersionModel.effective_until.is_(None)) | (ModelPurchasePriceVersionModel.effective_until > now),
                        ModelPurchasePriceVersionModel.context_min <= input_estimate,
                        (ModelPurchasePriceVersionModel.context_max.is_(None)) | (ModelPurchasePriceVersionModel.context_max >= input_estimate),
                        ModelPurchasePriceVersionModel.is_deleted == False,
                    )
                    .order_by(
                        ModelPurchasePriceVersionModel.context_min.desc(),
                        ModelPurchasePriceVersionModel.effective_from.desc(),
                    )
                )
                input_cost = Decimal(str(price.input_cost_per_million if price else catalog.input_cost_per_million))
                output_cost = Decimal(str(price.output_cost_per_million if price else catalog.output_cost_per_million))
                candidates.append(
                    ResolvedBinding(
                        binding_id=binding.id,
                        public_model_code=binding.public_model_code,
                        provider_account_id=account.id,
                        catalog_model_id=catalog.id,
                        provider_model_id=catalog.provider_model_id,
                        endpoint=account.endpoint.rstrip("/"),
                        api_key=str(secrets.get("api_key") or ""),
                        protocol=template.protocol,
                        timeout_seconds=min(route.timeout_seconds, account.timeout_seconds),
                        input_rate=binding.input_credits_per_1k if binding.input_credits_per_1k is not None else catalog.input_credits_per_1k,
                        output_rate=binding.output_credits_per_1k if binding.output_credits_per_1k is not None else catalog.output_credits_per_1k,
                        minimum_credits=catalog.minimum_credits,
                        input_cost_per_million=input_cost,
                        cache_read_cost_per_million=Decimal(str(price.cache_read_cost_per_million if price else input_cost)),
                        cache_write_cost_per_million=Decimal(str(price.cache_write_cost_per_million if price else input_cost)),
                        output_cost_per_million=output_cost,
                        reasoning_cost_per_million=Decimal(str(price.reasoning_cost_per_million if price else output_cost)),
                        price_version_id=price.id if price else None,
                        price_currency=price.currency if price else "CNY",
                        exchange_rate_to_cny=Decimal(str(price.exchange_rate_to_cny if price else 1)),
                        price_source=price.source if price else "catalog_fallback",
                    )
                )
            if not candidates:
                raise CustomException(msg="当前业务没有可用的模型路由", status_code=503)

            if all(item.provider_model_id in SUPPORTED_MODELS for item in candidates):
                image_estimate = estimate_qwen38_image_request(data)
                if image_estimate is not None:
                    input_estimate = image_estimate

            max_output = data.max_output_tokens or route.max_output_tokens or 2048
            reserved_cost = _reservation_cost(candidates, input_estimate, max_output, generation_settings=generation_settings)
            cost_billing = reserved_cost > 0
            reserved = _reservation_credits(candidates, input_estimate, max_output, generation_settings=generation_settings)
            existing = await db.scalar(
                select(ModelUsageModel.id).where(
                    ModelUsageModel.app_id == self.auth.app_id,
                    ModelUsageModel.request_id == data.request_id,
                )
            )
            if existing:
                raise CustomException(msg="request_id 已使用，请勿重复提交", status_code=409)
            credit_service = CreditService(db)
            await credit_service.release_due(app_id=self.auth.app_id, user_id=self.auth.user.id)
            account = await credit_service.account(self.auth.app_id, self.auth.user.id)
            if cost_billing:
                capacity = await credit_service.cost_capacity_yuan(self.auth.app_id, self.auth.user.id)
                if capacity < reserved_cost:
                    if generation_settings:
                        raise CustomException(msg="算力积分不足以预占本次输入、思考和完整答案预算", status_code=402)
                    max_output = _affordable_output_tokens_by_cost(candidates, input_estimate, max_output, capacity)
                    if max_output <= 0:
                        raise CustomException(msg="算力积分不足", status_code=402)
                    reserved_cost = _reservation_cost(candidates, input_estimate, max_output)
                reservation = await credit_service.reserve_cost(self.auth.app_id, self.auth.user.id, data.request_id, reserved_cost)
                reserved = reservation.estimated
            else:
                if account.available < reserved:
                    if generation_settings:
                        raise CustomException(msg="算力积分不足以预占本次输入、思考和完整答案预算", status_code=402)
                    max_output = _affordable_output_tokens(candidates, input_estimate, max_output, account.available)
                    if max_output <= 0:
                        raise CustomException(msg="算力积分不足", status_code=402)
                    reserved = _reservation_credits(candidates, input_estimate, max_output)
                await credit_service.reserve(self.auth.app_id, self.auth.user.id, data.request_id, reserved)
        return PreparedRequest(candidates, input_estimate, max_output, reserved, reserved_cost, cost_billing, started_at if generation_settings else time.perf_counter(), generation_settings)

    @staticmethod
    def _payload(
        data: RuntimeCompletionRequest,
        binding: ResolvedBinding,
        *,
        stream: bool,
        max_output_tokens: int,
        generation_settings: GenerationSettings | None = None,
    ) -> dict:
        payload: dict = {
            "model": binding.provider_model_id,
            "messages": [message.model_dump(exclude_none=True) for message in data.messages],
            "stream": stream,
            "max_tokens": max_output_tokens,
        }
        if data.temperature is not None:
            payload["temperature"] = data.temperature
        if data.tools:
            payload["tools"] = data.tools
            if data.tool_choice is not None:
                payload["tool_choice"] = data.tool_choice
            if data.parallel_tool_calls is not None:
                payload["parallel_tool_calls"] = data.parallel_tool_calls
        if data.response_format is not None:
            payload["response_format"] = data.response_format
        if stream:
            payload["stream_options"] = {"include_usage": True}
        validate_request(generation_settings, data)
        payload.update(payload_fields(generation_settings, binding.provider_model_id, protocol=binding.protocol))
        if generation_settings is None and data.thinking is not None and binding.provider_model_id in SUPPORTED_MODELS and binding.protocol == "openai_compatible":
            payload["enable_thinking"] = data.thinking
            if data.thinking and data.thinking_budget_tokens is not None:
                payload["thinking_budget"] = data.thinking_budget_tokens
        return {key: value for key, value in payload.items() if value is not None}

    @staticmethod
    def _headers(binding: ResolvedBinding) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if binding.api_key:
            headers["Authorization"] = f"Bearer {binding.api_key}"
        return headers

    async def _finalize(
        self,
        data: RuntimeCompletionRequest,
        prepared: PreparedRequest,
        binding: ResolvedBinding | None,
        input_tokens: int,
        output_tokens: int,
        *,
        status: str,
        error_category: str | None = None,
        first_token_ms: int | None = None,
        usage_detail: dict | None = None,
        usage_is_actual: bool = False,
        usage_report_complete: bool | None = None,
        upstream_request_id: str | None = None,
    ) -> int:
        normalized_usage = usage_detail or _normalized_usage({}, input_fallback=input_tokens, output_fallback=output_tokens)[0]
        usage_is_complete = usage_is_actual and status == "succeeded" and usage_report_complete is not False
        policy_snapshot = execution_snapshot(prepared, binding, normalized_usage, usage_is_actual=usage_is_actual, usage_is_complete=usage_is_complete)
        original_cost = _provider_cost_original(binding, normalized_usage) if binding else Decimal("0")
        provider_cost = (original_cost * binding.exchange_rate_to_cny if binding else Decimal("0")).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
        actual = 0 if binding is None else min(prepared.reserved_credits, _credits(binding, input_tokens, output_tokens))
        async with async_db_session() as db, db.begin():
            # 使用同一积分账户锁串行化结算；提交回执丢失也不能产生第二条用量。
            await CreditService(db).account(self.auth.app_id or 0, self.auth.user.id, lock=True)
            existing = await db.scalar(
                select(ModelUsageModel).where(
                    ModelUsageModel.app_id == self.auth.app_id,
                    ModelUsageModel.request_id == data.request_id,
                )
            )
            if existing is not None:
                if existing.user_id != self.auth.user.id or (status == "succeeded" and existing.status != "succeeded"):
                    raise CustomException(msg="请求已有不同的结算记录，生成结果保留待核对", code=40907, status_code=409)
                return int(existing.charged_credits or 0)
            if prepared.cost_billing:
                reservation = await CreditService(db).settle_cost(self.auth.app_id or 0, self.auth.user.id, data.request_id, provider_cost)
                actual = int(reservation.actual or 0)
            else:
                reservation = await CreditService(db).settle(self.auth.app_id or 0, self.auth.user.id, data.request_id, actual)
                actual = int(reservation.actual or 0)
            if status == "succeeded" and reservation.status == "cancelled":
                raise CustomException(msg="费用预占已释放，生成结果保留待核对", code=40907, status_code=409)
            db.add(
                ModelUsageModel(
                    app_id=self.auth.app_id,
                    user_id=self.auth.user.id,
                    request_id=data.request_id,
                    business_code=data.business_code,
                    binding_id=binding.binding_id if binding else None,
                    provider_account_id=binding.provider_account_id if binding else None,
                    provider_model_id=binding.provider_model_id if binding else None,
                    upstream_request_id=upstream_request_id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    usage_detail=normalized_usage,
                    execution_snapshot=policy_snapshot,
                    price_version_id=binding.price_version_id if binding else None,
                    price_snapshot=_price_snapshot(binding) if binding else {},
                    provider_cost_original=original_cost,
                    provider_currency=binding.price_currency if binding else "CNY",
                    exchange_rate_to_cny=binding.exchange_rate_to_cny if binding else Decimal("1"),
                    charged_credits=actual,
                    provider_cost_yuan=provider_cost,
                    cost_precision="observed_partial_usage" if prepared.generation_settings and usage_is_actual and not usage_is_complete else "actual_usage" if usage_is_actual else "estimated_usage",
                    reconciliation_status="budget_exceeded"
                    if policy_snapshot.get("budget_exceeded")
                    else "usage_incomplete"
                    if prepared.generation_settings and not usage_is_complete
                    else "unreconciled",
                    latency_ms=round((time.perf_counter() - prepared.started_at) * 1000),
                    first_token_ms=first_token_ms,
                    status=status,
                    error_category=error_category,
                    completed_at=datetime.now(UTC),
                )
            )
            if data.cloud_task_id:
                from app.api.v1.module_growth.model import TaskEvidenceModel

                db.add(
                    TaskEvidenceModel(
                        app_id=self.auth.app_id,
                        user_id=self.auth.user.id,
                        task_id=data.cloud_task_id,
                        request_id=data.request_id,
                        business_code=data.business_code,
                        status=status,
                        output_tokens=output_tokens,
                    )
                )
        return actual

    async def complete(self, data: RuntimeCompletionRequest) -> RuntimeCompletionOut:
        from .result_journal import ResultJournal, fingerprint, identity
        from .settlement_recovery import settle_saved

        key = identity(self.auth, data.request_id)
        journal = ResultJournal()
        try:
            saved = await asyncio.to_thread(journal.claim, key, fingerprint(data))
        except CustomException:
            raise
        except Exception:
            raise CustomException(msg="模型结果保存服务暂不可用，请稍后重试", code=50306, status_code=503) from None
        if saved is not None:
            return await settle_saved(self, key, saved, force=True)
        try:
            return await self._complete_once(data)
        except BaseException:
            # 已生成或已结算的记录不能在这里降级。
            try:
                await asyncio.to_thread(journal.fail, key)
            except Exception:
                pass  # 已有占用记录仍可阻止重复生成。
            raise

    async def _complete_once(self, data: RuntimeCompletionRequest) -> RuntimeCompletionOut:
        prepared = await self._resolve(data)
        last_error: Exception | None = None
        client = get_provider_http_client()
        for binding in prepared.candidates:
            try:
                timeout = httpx.Timeout(binding.timeout_seconds)
                response = await within_deadline(
                    lambda binding=binding, timeout=timeout: client.post(
                        f"{binding.endpoint}/chat/completions",
                        headers=self._headers(binding),
                        json=self._payload(
                            data,
                            binding,
                            stream=False,
                            max_output_tokens=prepared.max_output_tokens,
                            generation_settings=prepared.generation_settings,
                        ),
                        timeout=timeout,
                    ),
                    prepared,
                )
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict) or not isinstance(body.get("choices"), list) or not body["choices"] or not isinstance(body["choices"][0], dict):
                    raise ValueError("Invalid completion envelope")
                choice = (body.get("choices") or [{}])[0]
                message = choice.get("message") or {}
                usage = body.get("usage") or {}
                if not isinstance(message, dict) or not isinstance(usage, dict):
                    raise ValueError("Invalid completion message or usage")
                normalized_usage, usage_is_actual = _normalized_usage(
                    usage,
                    input_fallback=prepared.input_tokens_estimate,
                    output_fallback=_estimate_tokens(message),
                )
                if prepared.generation_settings and not usage_is_actual and message.get("reasoning_content"):
                    normalized_usage["reasoning_tokens"] = min(normalized_usage["output_tokens"], _estimate_tokens(message["reasoning_content"]))
                input_tokens = int(normalized_usage["input_tokens"])
                output_tokens = int(normalized_usage["output_tokens"])
                result = RuntimeCompletionOut(
                    request_id=data.request_id,
                    model=binding.public_model_code,
                    content=str(message.get("content") or ""),
                    reasoning_content=str(message.get("reasoning_content") or ""),
                    tool_calls=message.get("tool_calls") or [],
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    finish_reason=_finish_reason(choice),
                    effective_max_output_tokens=prepared.max_output_tokens,
                    generation_settings=prepared.generation_settings,
                    generation_policy_status="GOVERNED" if prepared.generation_settings else "LEGACY_UNMANAGED",
                )
            except asyncio.CancelledError:
                await self._finalize(data, prepared, binding, prepared.input_tokens_estimate, 0, status="cancelled", error_category="client_cancelled")
                raise
            except (httpx.HTTPError, ValueError, KeyError, TimeoutError) as exc:
                last_error = exc
                log_upstream_failure(exc, request_id=data.request_id, app_id=self.auth.app_id, binding_id=binding.binding_id)
                if _invalid_image_url_error(exc):
                    await self._finalize(data, prepared, None, prepared.input_tokens_estimate, 0, status="failed", error_category="invalid_image_url")
                    raise CustomException(msg="模型图片地址无效，请使用兼容图片格式重试", status_code=422) from None
                if not safe_to_fallback(exc):
                    category, message, status_code, code = error_details(exc)
                    # 已拒绝的请求没有可计费的生成结果；旧版请求没有实际流式用量时不扣费。
                    effective_binding = None if (isinstance(exc, httpx.HTTPStatusError) or not prepared.generation_settings or getattr(exc, "before_await", False)) else binding
                    await self._finalize(data, prepared, effective_binding, prepared.input_tokens_estimate, 0, status="failed", error_category=category)
                    from .upstream_diagnostics import public_diagnostic

                    raise CustomException(msg=message, status_code=status_code, code=code, data={"upstream_diagnostic": public_diagnostic(exc)}) from None
                if isinstance(exc, (httpx.ReadTimeout, httpx.WriteTimeout, TimeoutError)):
                    # 供应商是否接收请求尚不确定，不能再次提交付费生成。
                    break
            else:
                from .settlement_recovery import save_success

                return await save_success(
                    self,
                    data,
                    prepared,
                    binding,
                    result,
                    status="succeeded",
                    usage_detail=normalized_usage,
                    usage_is_actual=usage_is_actual,
                    usage_report_complete=complete_usage_report(prepared.generation_settings, usage),
                    upstream_request_id=str(body.get("id") or "") or None,
                )
        if last_error is not None:
            category, message, status_code, code = error_details(last_error)
            await self._finalize(data, prepared, None, prepared.input_tokens_estimate, 0, status="failed", error_category=category)
            raise CustomException(msg=message, status_code=status_code, code=code) from None
        await self._finalize(data, prepared, None, prepared.input_tokens_estimate, 0, status="failed", error_category="upstream_unavailable")
        raise CustomException(msg="模型服务暂时不可用，请稍后重试", status_code=503) from last_error

    async def prepare_stream(self, data: RuntimeCompletionRequest) -> PreparedRequest:
        """发送 SSE 响应头前完成请求占用、校验和积分预占。"""
        from dataclasses import replace

        from .result_journal import ResultJournal, fingerprint, identity
        from .settlement_recovery import restore

        key = identity(self.auth, data.request_id)
        try:
            saved = await asyncio.to_thread(ResultJournal().claim, key, fingerprint(data))
        except CustomException:
            raise
        except Exception:
            raise CustomException(msg="模型结果保存服务暂不可用，请稍后重试", code=50306, status_code=503) from None
        if saved:
            _, restored, _ = restore(saved)
            return replace(restored, replay_payload=saved)
        return await self._resolve(data)

    async def stream(
        self,
        data: RuntimeCompletionRequest,
        prepared: PreparedRequest | None = None,
    ) -> AsyncIterator[bytes]:
        from .result_journal import identity
        from .settlement_recovery import save_success, settle_saved
        from .stream_result import StreamResult, result_events

        prepared = prepared or await self.prepare_stream(data)
        if prepared.replay_payload is not None:
            result = await settle_saved(self, identity(self.auth, data.request_id), prepared.replay_payload, force=True)
            for event in result_events(result, replay=True):
                yield event
            return
        last_error: Exception | None = None
        client = get_provider_http_client()
        for binding in prepared.candidates:
            emitted = False
            collected = StreamResult()
            input_tokens = prepared.input_tokens_estimate
            output_tokens = 0
            reasoning_tokens_estimate = 0
            first_token_ms: int | None = None
            final_usage: dict = {}
            upstream_request_id: str | None = None
            finish_reason: str | None = None
            terminal_observed = False
            response_started = False
            finalized = False
            try:
                timeout = httpx.Timeout(binding.timeout_seconds)
                async with bounded_stream(
                    client.stream(
                        "POST",
                        f"{binding.endpoint}/chat/completions",
                        headers=self._headers(binding),
                        json=self._payload(
                            data,
                            binding,
                            stream=True,
                            max_output_tokens=prepared.max_output_tokens,
                            generation_settings=prepared.generation_settings,
                        ),
                        timeout=timeout,
                    ),
                    prepared,
                ) as response:
                    response_started = True
                    if isinstance(response, httpx.Response) and response.is_error:
                        response = await read_error_response(response, prepared)
                    response.raise_for_status()
                    async for line in bounded_lines(response.aiter_lines(), prepared):
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if raw == "[DONE]":
                            terminal_observed = True
                            break
                        if not raw:
                            continue
                        chunk = json.loads(raw)
                        if not isinstance(chunk, dict):
                            raise ValueError("Invalid stream envelope")
                        upstream_request_id = upstream_request_id or (str(chunk.get("id")) if chunk.get("id") else None)
                        usage = chunk.get("usage") or {}
                        if usage:
                            normalized, _ = _normalized_usage(usage, input_fallback=input_tokens, output_fallback=output_tokens)
                            final_usage = usage
                            input_tokens = int(normalized["input_tokens"])
                            output_tokens = int(normalized["output_tokens"])
                        choices = chunk.get("choices") or [{}]
                        if not isinstance(choices, list) or not isinstance(choices[0], dict):
                            raise ValueError("Invalid stream choices")
                        choice = choices[0]
                        if observed_reason := _finish_reason(choice):
                            finish_reason = observed_reason
                            terminal_observed = True
                        delta = choice.get("delta") or {}
                        if not isinstance(delta, dict):
                            raise ValueError("Invalid stream delta")
                        content = delta.get("content")
                        reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                        tool_calls = delta.get("tool_calls") or []
                        collected.append(content, reasoning, tool_calls)
                        if content:
                            emitted = True
                            first_token_ms = first_token_ms or round((time.perf_counter() - prepared.started_at) * 1000)
                            output_tokens += _estimate_tokens(content) if not usage else 0
                            yield _sse("text_delta", {"delta": content})
                        if reasoning:
                            emitted = True
                            first_token_ms = first_token_ms or round((time.perf_counter() - prepared.started_at) * 1000)
                            output_tokens += _estimate_tokens(reasoning) if not usage else 0
                            reasoning_tokens_estimate += _estimate_tokens(reasoning)
                            yield _sse("reasoning_delta", {"delta": reasoning})
                        if tool_calls:
                            emitted = True
                            first_token_ms = first_token_ms or round((time.perf_counter() - prepared.started_at) * 1000)
                            output_tokens += _estimate_tokens(tool_calls) if not usage else 0
                            yield _sse("tool_call", {"tool_calls": tool_calls})
                if not terminal_observed:
                    raise httpx.RemoteProtocolError("Upstream stream ended without terminal evidence")
                normalized_usage, usage_is_actual = _normalized_usage(
                    final_usage,
                    input_fallback=input_tokens,
                    output_fallback=output_tokens,
                )
                if prepared.generation_settings and not usage_is_actual:
                    normalized_usage["reasoning_tokens"] = min(normalized_usage["output_tokens"], reasoning_tokens_estimate)
            except asyncio.CancelledError:
                if not finalized:
                    await self._finalize(
                        data,
                        prepared,
                        binding,
                        input_tokens,
                        output_tokens,
                        status="cancelled",
                        error_category="client_cancelled",
                        first_token_ms=first_token_ms,
                    )
                raise
            except (httpx.HTTPError, ValueError, KeyError, TimeoutError) as exc:
                last_error = exc
                log_upstream_failure(exc, request_id=data.request_id, app_id=self.auth.app_id, binding_id=binding.binding_id)
                if (prepared.generation_settings and emitted) or not safe_to_fallback(exc):
                    category, message, _, _ = error_details(exc)
                    normalized_usage, usage_is_actual = _normalized_usage(final_usage, input_fallback=input_tokens, output_fallback=output_tokens)
                    if not usage_is_actual:
                        normalized_usage["reasoning_tokens"] = min(normalized_usage["output_tokens"], reasoning_tokens_estimate)
                    effective_binding = (
                        None
                        if (isinstance(exc, httpx.HTTPStatusError) or (not prepared.generation_settings and not emitted) or (getattr(exc, "before_await", False) and not response_started))
                        else binding
                    )
                    await self._finalize(
                        data,
                        prepared,
                        effective_binding,
                        input_tokens,
                        output_tokens,
                        status="failed",
                        error_category=category,
                        first_token_ms=first_token_ms,
                        usage_detail=normalized_usage,
                        usage_is_actual=usage_is_actual,
                        upstream_request_id=upstream_request_id,
                    )
                    yield _sse("error", {"code": category.upper(), "message": message})
                    return
                if emitted:
                    await self._finalize(
                        data,
                        prepared,
                        binding,
                        input_tokens,
                        output_tokens,
                        status="failed",
                        error_category="upstream_interrupted",
                        first_token_ms=first_token_ms,
                        usage_detail=_normalized_usage(
                            final_usage,
                            input_fallback=input_tokens,
                            output_fallback=output_tokens,
                        )[0],
                        usage_is_actual=bool(final_usage),
                        upstream_request_id=upstream_request_id,
                    )
                    yield _sse("error", {"code": "UPSTREAM_INTERRUPTED", "message": "模型输出中断，请重试"})
                    return
                if isinstance(exc, (httpx.ReadTimeout, httpx.WriteTimeout, TimeoutError)):
                    break
            else:
                # 上游已成功结束；持久化或结算错误不能进入供应商失败及切换分支。
                result = collected.result(
                    request_id=data.request_id,
                    model=binding.public_model_code,
                    input_tokens=int(normalized_usage["input_tokens"]),
                    output_tokens=int(normalized_usage["output_tokens"]),
                    finish_reason=finish_reason,
                    effective_max_output_tokens=prepared.max_output_tokens,
                    generation_settings=prepared.generation_settings,
                    generation_policy_status="GOVERNED" if prepared.generation_settings else "LEGACY_UNMANAGED",
                )
                try:
                    result = await save_success(
                        self,
                        data,
                        prepared,
                        binding,
                        result,
                        status="succeeded",
                        first_token_ms=first_token_ms,
                        usage_detail=normalized_usage,
                        usage_is_actual=usage_is_actual,
                        usage_report_complete=complete_usage_report(prepared.generation_settings, final_usage),
                        upstream_request_id=upstream_request_id,
                    )
                except CustomException as exc:
                    yield _sse("error", {"code": "RESULT_PERSISTENCE_PENDING", "message": exc.msg})
                    return
                for event in result_events(result):
                    yield event
                return
        if last_error is not None:
            category, message, _, _ = error_details(last_error)
            await self._finalize(data, prepared, None, prepared.input_tokens_estimate, 0, status="failed", error_category=category)
            yield _sse("error", {"code": category.upper(), "message": message})
            return
        await self._finalize(data, prepared, None, prepared.input_tokens_estimate, 0, status="failed", error_category="upstream_unavailable")
        yield _sse("error", {"code": "UPSTREAM_UNAVAILABLE", "message": "模型服务暂时不可用，请稍后重试"})
        if last_error:
            return
