"""根据已保存的成功结果恢复结算，不再次调用模型供应商。"""

import asyncio
import time
from dataclasses import asdict
from decimal import Decimal

from app.config.setting import settings
from app.core.exceptions import CustomException
from app.core.logger import logger

from .result_journal import ResultJournal, fingerprint, identity
from .schema import RuntimeCompletionOut, RuntimeCompletionRequest


def snapshot(data, prepared, binding, result, kwargs):
    binding_data = asdict(binding)
    binding_data.pop("api_key")
    binding_data.pop("endpoint")
    binding_data = {k: str(v) if isinstance(v, Decimal) else v for k, v in binding_data.items()}
    return {
        "result": result.model_copy(update={"charged_credits": None, "settlement_status": "PENDING"}).model_dump(mode="json"),
        "request": {"request_id": data.request_id, "business_code": data.business_code, "cloud_task_id": data.cloud_task_id},
        "binding": binding_data,
        "prepared": {
            "input_tokens_estimate": prepared.input_tokens_estimate,
            "max_output_tokens": prepared.max_output_tokens,
            "reserved_credits": prepared.reserved_credits,
            "reserved_cost_yuan": str(prepared.reserved_cost_yuan),
            "cost_billing": prepared.cost_billing,
            "elapsed_seconds": max(0, time.perf_counter() - prepared.started_at),
            "generation_settings": prepared.generation_settings.model_dump() if prepared.generation_settings else None,
        },
        "finalize": kwargs,
    }


def restore(payload):
    from .gateway import PreparedRequest, ResolvedBinding
    from .generation_policy import GenerationSettings

    binding_data = dict(payload["binding"])
    for name in ("input_cost_per_million", "cache_read_cost_per_million", "cache_write_cost_per_million", "output_cost_per_million", "reasoning_cost_per_million", "exchange_rate_to_cny"):
        binding_data[name] = Decimal(binding_data[name])
    binding = ResolvedBinding(**binding_data, api_key="", endpoint="")
    prepared_data = dict(payload["prepared"])
    elapsed = prepared_data.pop("elapsed_seconds")
    prepared_data["reserved_cost_yuan"] = Decimal(prepared_data["reserved_cost_yuan"])
    prepared_data["generation_settings"] = GenerationSettings.model_validate(prepared_data["generation_settings"]) if prepared_data["generation_settings"] else None
    prepared = PreparedRequest(candidates=[binding], started_at=time.perf_counter() - elapsed, **prepared_data)
    # 结算只需要请求身份和业务范围，不需要原始提示词。
    data = RuntimeCompletionRequest(**payload["request"], messages=[{"role": "user", "content": "settlement recovery"}])
    return data, prepared, binding


async def settle_saved(service, key, payload, *, force=False):
    journal = ResultJournal()
    result = RuntimeCompletionOut.model_validate(payload["result"])
    try:
        claimed = await asyncio.to_thread(journal.take, key, force=force)
        if claimed is None:
            latest = await asyncio.to_thread(journal.read, key)
            return RuntimeCompletionOut.model_validate(latest["result"]) if latest else result
        data, prepared, binding = restore(claimed)
        async with asyncio.timeout(settings.MODEL_SETTLEMENT_TIMEOUT_SECONDS):
            charged = await service._finalize(data, prepared, binding, result.input_tokens, result.output_tokens, **claimed["finalize"])
        await asyncio.to_thread(journal.finish, key, charged)
        return result.model_copy(update={"charged_credits": charged, "settlement_status": "SETTLED"})
    except asyncio.CancelledError:
        # 请求取消或进程退出后，已保存的结果仍可恢复。
        raise
    except Exception as exc:
        logger.warning("model_settlement_pending app_id={} request_id={} exception_type={}", key[0], key[2], type(exc).__name__)
        try:
            await asyncio.to_thread(journal.defer, key)
        except Exception as journal_error:
            logger.warning("model_settlement_journal_deferred exception_type={}", type(journal_error).__name__)
        return result  # 结算失败不能触发供应商重新生成。


async def save_success(service, data, prepared, binding, result, **kwargs):
    key = identity(service.auth, data.request_id)
    try:
        payload = snapshot(data, prepared, binding, result, kwargs)
        await asyncio.to_thread(ResultJournal().save, key, fingerprint(data), payload)
    except Exception as exc:
        logger.error("model_result_persistence_failed app_id={} exception_type={}", key[0], type(exc).__name__)
        raise CustomException(msg="模型已返回，结果暂未能可靠保存，请保留原请求编号并联系运营核查，勿重复生成", code=50306, status_code=503) from None
    return await settle_saved(service, key, payload)
