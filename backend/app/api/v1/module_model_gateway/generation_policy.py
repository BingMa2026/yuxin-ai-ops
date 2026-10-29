"""Explicit, versioned provider policy; NULL routes retain legacy semantics.

This adapter covers the documented Qwen 3.8 commercial text models only. It
does not infer model capabilities from a public alias or arbitrary extra_body.
"""

import hashlib
import json
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.v1.module_billing.reservation_policy import MAX_MODEL_REQUEST_SECONDS, RESERVATION_STALE_SECONDS
from app.core.exceptions import CustomException

POLICY_VERSION = "qwen3.8-bounded-v1"
SUPPORTED_MODELS = frozenset({"qwen3.8-max", "qwen3.8-max-0902", "qwen3.8-flash"})
MAX_INPUT_RESERVATION_TOKENS = 131072
MAX_ANSWER_TOKENS = 131072
RESERVATION_TTL_SECONDS = RESERVATION_STALE_SECONDS
MAX_TOTAL_TIMEOUT_SECONDS = MAX_MODEL_REQUEST_SECONDS


class GenerationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    policy_version: Literal["qwen3.8-bounded-v1"]
    enable_thinking: bool
    thinking_budget_tokens: int = Field(ge=0, le=262144)
    total_timeout_seconds: int = Field(ge=1, le=MAX_TOTAL_TIMEOUT_SECONDS)
    response_format: Literal["text", "json_object"]

    @model_validator(mode="after")
    def coherent_thinking_budget(self):
        if self.enable_thinking != (self.thinking_budget_tokens > 0):
            raise ValueError("开启思考须配置正数预算；关闭思考须将预算设为零")
        return self


def validate_candidate(settings: GenerationSettings | None, provider_model_id: str, protocol: str = "openai_compatible") -> None:
    if settings and (provider_model_id not in SUPPORTED_MODELS or protocol != "openai_compatible"):
        raise CustomException(msg="路由生成策略不支持该实际模型，请检查主模型、备用模型和用户所选模型", status_code=422)


def validate_answer_budget(settings: GenerationSettings | None, max_output_tokens: int | None) -> None:
    if settings and (max_output_tokens is None or not 1 <= max_output_tokens <= MAX_ANSWER_TOKENS):
        raise ValueError("显式生成策略须配置 1～131072 的答案上限")


def effective_thinking_settings(
    settings: GenerationSettings | None,
    thinking: bool | None,
    *,
    allow_legacy_business: bool = False,
) -> GenerationSettings | None:
    """保持旧版路由语义；客户端不能扩大运营端设置的生成预算。"""
    if thinking is None:
        return settings
    if settings is None:
        if thinking is False or allow_legacy_business:
            return None
        raise CustomException(msg="当前业务未开放可控思考模式", status_code=422)
    if thinking and not settings.enable_thinking:
        raise CustomException(msg="当前业务未开放思考模式", status_code=422)
    if not thinking and settings.enable_thinking:
        return settings.model_copy(update={"enable_thinking": False, "thinking_budget_tokens": 0})
    return settings


def estimate_text_input(data) -> int:
    """A capped conservative reservation estimate, never an actual usage claim.

    One token per UTF-8 byte plus message framing allowance avoids the legacy
    len/4 underestimate for Chinese. Multimodal billing cannot use URL length.
    Reject oversize rather than clipping the estimate and under-reserving.
    """
    for message in data.messages:
        if isinstance(message.content, list) and any(item.get("type") != "text" or not isinstance(item.get("text"), str) or set(item) - {"type", "text"} for item in message.content):
            raise CustomException(msg="该生成策略当前仅支持可估算的文本输入", status_code=422)
    value = {"messages": [message.model_dump(exclude_none=True) for message in data.messages], "tools": data.tools}
    serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    estimate = len(serialized.encode("utf-8")) + 128 * len(data.messages) + 256
    if estimate > MAX_INPUT_RESERVATION_TOKENS:
        raise CustomException(msg="本次文本输入超过生成策略预占上限，请缩小输入范围", status_code=422)
    return max(estimate, 1)


def validate_request(settings: GenerationSettings | None, data) -> None:
    if not settings:
        return
    if settings.response_format == "json_object":
        texts = []
        for message in data.messages:
            if message.role in {"system", "user"}:
                texts.extend([message.content] if isinstance(message.content, str) else [item.get("text", "") for item in (message.content or [])])
        if not any("json" in text.lower() for text in texts):
            raise CustomException(msg="JSON 输出策略要求系统或用户提示明确包含 JSON 指令", status_code=422)


def payload_fields(settings: GenerationSettings | None, provider_model_id: str, *, protocol: str = "openai_compatible") -> dict:
    validate_candidate(settings, provider_model_id, protocol)
    if not settings:
        return {}
    return {
        "enable_thinking": settings.enable_thinking,
        "thinking_budget": settings.thinking_budget_tokens,
        "response_format": {"type": settings.response_format},
    }


def complete_usage_report(settings: GenerationSettings | None, usage: dict) -> bool:
    if not any(usage.get(key) is not None for key in ("prompt_tokens", "input_tokens")):
        return False
    output = next((usage[key] for key in ("completion_tokens", "output_tokens") if usage.get(key) is not None), None)
    if output is None:
        return False
    if settings and settings.enable_thinking and int(output) > 0:
        details = usage.get("completion_tokens_details") or usage.get("output_tokens_details") or {}
        return details.get("reasoning_tokens") is not None or usage.get("reasoning_tokens") is not None
    return True


def execution_snapshot(prepared, binding, normalized_usage: dict, *, usage_is_actual: bool, usage_is_complete: bool | None = None) -> dict:
    settings = prepared.generation_settings
    if settings is None:
        return {"generation_policy_status": "LEGACY_UNMANAGED", "generation_settings": None}
    snapshot = {
        "generation_policy_status": "GOVERNED",
        "generation_settings": settings.model_dump(),
        "answer_budget_tokens": prepared.max_output_tokens,
        "thinking_budget_tokens": settings.thinking_budget_tokens,
        "input_reservation_tokens": prepared.input_tokens_estimate,
        "input_estimate_method": "utf8-bytes-framing-v1",
        "reservation_ttl_seconds": RESERVATION_TTL_SECONDS,
        "settlement_margin_seconds": RESERVATION_TTL_SECONDS - settings.total_timeout_seconds,
        "budget_basis": "provider_documented_limits_and_estimated_input",
        "usage_complete": usage_is_actual if usage_is_complete is None else usage_is_complete,
        "usage_reported": usage_is_actual,
        "candidate_bindings": [
            {
                "binding_id": item.binding_id,
                "catalog_model_id": item.catalog_model_id,
                "provider_account_id": item.provider_account_id,
                "provider_model_id": item.provider_model_id,
                "idle_timeout_seconds": item.timeout_seconds,
            }
            for item in prepared.candidates
        ],
        "effective_binding_id": binding.binding_id if binding else None,
    }
    snapshot["identity_sha256"] = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    snapshot["budget_exceeded"] = bool(
        usage_is_actual
        and (
            normalized_usage["input_tokens"] > prepared.input_tokens_estimate
            or normalized_usage["reasoning_tokens"] > settings.thinking_budget_tokens
            or normalized_usage["output_tokens"] - normalized_usage["reasoning_tokens"] > prepared.max_output_tokens
        )
    )
    return snapshot


def error_details(exc: Exception) -> tuple[str, str, int, int]:
    """Finite public errors. Never include str(exc), upstream body, URL or key."""
    if isinstance(exc, TimeoutError):
        return "upstream_total_timeout", "模型调用达到整次时限，请保留任务并稍后重试", 504, 50401
    if isinstance(exc, (httpx.ReadTimeout, httpx.WriteTimeout)):
        return "upstream_idle_timeout", "模型服务响应等待超时，请稍后重试", 504, 50402
    if isinstance(exc, (httpx.ConnectTimeout, httpx.PoolTimeout)):
        return "upstream_connect_timeout", "连接模型服务超时，请稍后重试", 504, 50403
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        try:
            body = exc.response.json()
        except (ValueError, httpx.ResponseNotRead):
            body = {}
        error = body.get("error", body) if isinstance(body, dict) else {}
        if isinstance(error, dict) and error.get("code") == "Arrearage":
            return "upstream_billing_rejected", "模型供应商账户计费异常，请联系运营人员检查供应商账户", 503, 50305
        if status == 429:
            return "upstream_rate_limited", "模型服务繁忙，请稍后重试", 503, 50302
        if status in {401, 403}:
            return "upstream_auth_rejected", "模型服务授权异常，请联系运营人员", 503, 50303
        if 400 <= status < 500:
            return "upstream_request_rejected", "模型服务拒绝当前请求，请检查生成策略", 502, 50201
        return "upstream_server_error", "模型供应商服务异常，请稍后重试", 503, 50304
    if isinstance(exc, (ValueError, KeyError, httpx.RemoteProtocolError)):
        return "upstream_protocol_error", "模型响应格式或结束标记异常，请重试", 502, 50202
    return "upstream_unavailable", "模型服务暂时不可用，请稍后重试", 503, 50301


def safe_to_fallback(exc: Exception) -> bool:
    # After writes/response/read timeout, acceptance and billing are uncertain.
    # A second paid generation would not fit a max(candidate) reservation.
    return isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout))
