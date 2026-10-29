"""后台补结算任务，支持服务重启后恢复。"""

import asyncio

from app.core.base_schema import AuthSchema, CoreUserSchema
from app.core.logger import logger

from .result_journal import ResultJournal
from .settlement_recovery import settle_saved


async def recover_once():
    from .gateway import ModelGatewayService

    journal = ResultJournal()
    for key in await asyncio.to_thread(journal.due):
        auth = AuthSchema(actor_type="runtime", app_id=key[0], user=CoreUserSchema(id=key[1], username="settlement-recovery"))
        # 领取任务和结算都由 settle_saved 完成，避免重复领取。
        try:
            with_payload = await asyncio.to_thread(journal.read, key)
            if with_payload:
                await settle_saved(ModelGatewayService(auth), key, with_payload)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # 单条损坏记录不能阻塞其他待结算请求。
            logger.warning("model_settlement_record_deferred app_id={} exception_type={}", key[0], type(exc).__name__)
            await asyncio.to_thread(journal.defer, key)
    await asyncio.to_thread(journal.prune)


async def settlement_loop():
    while True:
        try:
            await recover_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("model_settlement_recovery_deferred exception_type={}", type(exc).__name__)
        await asyncio.sleep(30)
