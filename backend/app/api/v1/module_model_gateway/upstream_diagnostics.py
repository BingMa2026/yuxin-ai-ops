"""仅在服务端记录有边界的诊断信息，不原样记录供应商返回内容。"""

import asyncio
import hashlib
import json
import re

import httpx

from app.core.logger import logger

from .generation_deadline import bounded_lines

_FIELDS = (
    "max_tokens",
    "max_completion_tokens",
    "thinking_budget",
    "enable_thinking",
    "reasoning_content",
    "tool_calls",
    "tool_call_id",
    "tool_choice",
    "tools",
    "parallel_tool_calls",
    "response_format",
    "messages",
    "temperature",
    "model",
)
_CODES = {
    "InvalidParameter",
    "InvalidParameterValue",
    "InvalidInput",
    "BadRequest",
    "invalid_parameter_error",
    "invalid_request_error",
    "context_length_exceeded",
    "InternalError.Algo.InvalidParameter",
    "DataInspectionFailed",
    "Arrearage",
    "Throttling",
    "Throttling.RateQuota",
    "Throttling.AllocationQuota",
    "AccessDenied",
    "InvalidApiKey",
    "UnsupportedOperation",
    "ModelNotFound",
}


def _identifier(value: object) -> str | None:
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value):
        if not value.lower().startswith(("sk-", "bearer", "eyj")):
            return value
    return None


def diagnostic_fields(exc: Exception) -> dict:
    """只提取白名单内的事实，不记录可能包含客户数据的原始消息。"""
    result = {"exception_type": type(exc).__name__, "reason": "unclassified"}
    if not isinstance(exc, httpx.HTTPStatusError):
        return result
    response = exc.response
    result["upstream_status"] = response.status_code
    result["upstream_request_id"] = _identifier(response.headers.get("x-request-id"))
    try:
        raw = response.content
    except httpx.ResponseNotRead:
        result["body_state"] = "not_read"
        return result
    result["body_sha256"] = hashlib.sha256(raw).hexdigest()
    if len(raw) > 32768:
        result["body_state"] = "too_large"
        return result
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeError):
        result["body_state"] = "not_json"
        return result
    if not isinstance(body, dict):
        return result
    error = body.get("error", body)
    if not isinstance(error, dict):
        return result
    result["upstream_request_id"] = result["upstream_request_id"] or _identifier(body.get("request_id"))
    code = error.get("code")
    if isinstance(code, str):
        result["error_code"] = code if code in _CODES else "unrecognized"
        result["error_code_sha256"] = hashlib.sha256(code.encode()).hexdigest()
    message = error.get("message")
    detail = message.casefold() if isinstance(message, str) else ""
    param = error.get("param")
    result["fields"] = [name for name in _FIELDS if name == param or re.search(r"\b" + name + r"\b", detail)]
    if code == "Arrearage":
        result["reason"] = "supplier_account_billing"
    elif any(term in detail for term in ("context_length_exceeded", "maximum context", "context window", "input too long")):
        result["reason"] = "context_limit"
    elif "range" in detail or "must be between" in detail:
        result["reason"] = "parameter_range"
        bounds = re.search(r"\[\s*(\d{1,7})\s*,\s*(\d{1,7})\s*\]", detail)
        if bounds:
            result["limits"] = [int(bounds[1]), int(bounds[2])]
    elif any(term in detail for term in ("not support", "unsupported", "not allowed", "incompatible")):
        result["reason"] = "unsupported_parameter_or_combination"
    elif any(term in detail for term in ("required", "missing", "must be followed", "must have")):
        result["reason"] = "missing_field_or_message"
    elif any(term in detail for term in ("invalid", "not valid")):
        result["reason"] = "invalid_parameter_or_message"
    elif any(term in detail for term in ("inappropriate", "inspection", "content policy")):
        result["reason"] = "content_rejected"
    return result


def log_upstream_failure(exc: Exception, *, request_id: str, app_id: int, binding_id: int) -> None:
    fields = diagnostic_fields(exc)
    fields.update(request_id=_identifier(request_id), app_id=app_id, binding_id=binding_id, detail_policy="ALLOWLISTED_FACTS_NO_RAW_BODY")
    logger.warning("model_upstream_failure {}", json.dumps(fields, ensure_ascii=False, sort_keys=True))


def public_diagnostic(exc: Exception) -> dict:
    """Expose finite recovery facts; never return raw messages or response bodies."""
    facts = diagnostic_fields(exc)
    return {key: facts[key] for key in ("reason", "fields", "error_code") if key in facts}


async def read_error_response(response: httpx.Response, prepared) -> httpx.Response:
    """被拒绝的 SSE 请求可能返回 JSON；限制读取量并保留状态码。"""
    chunks = bytearray()
    try:
        async with asyncio.timeout(5):
            async for chunk in bounded_lines(response.aiter_bytes(), prepared):
                chunks.extend(chunk[: 32769 - len(chunks)])
                if len(chunks) > 32768:
                    break
    except (httpx.HTTPError, TimeoutError):
        chunks.clear()
    # aiter_bytes 已解码 gzip/br，复制响应时不要再次解码。
    headers = {key: value for key, value in response.headers.items() if key.lower() not in {"content-encoding", "content-length", "transfer-encoding"}}
    return httpx.Response(response.status_code, headers=headers, content=bytes(chunks), request=response.request)
