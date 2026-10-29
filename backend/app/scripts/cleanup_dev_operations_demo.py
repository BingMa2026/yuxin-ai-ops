"""Preview or remove additive records created by ``seed_dev_operations_demo``.

The default mode is read-only. Pass ``--execute`` only after checking the JSON
preview. Shared records that the seed enriches (the user profile, price plans,
subscription and credit account) are deliberately retained because their
pre-seed values cannot be reconstructed safely.
"""

from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy import delete, func, select

from app.api.v1.module_billing.model import (
    AppPricingStrategyItemModel,
    AppPricingStrategyModel,
    CreditGrantModel,
    CreditLedgerModel,
    SubscriptionCycleModel,
    SubscriptionModel,
)
from app.api.v1.module_client.app.model import ClientAppModel
from app.api.v1.module_client.user.model import ClientUserModel, ClientUserSegmentModel, ClientUserTagModel
from app.api.v1.module_model_gateway.model import ModelUsageModel
from app.api.v1.module_payment.order.model import PaymentOrderModel
from app.api.v1.module_telemetry.model import TelemetryEventModel
from app.api.v1.module_user_operations.model import (
    ClientMessageCampaignModel,
    ClientMessageDeliveryModel,
    ClientMessageTemplateModel,
    ClientSupportMessageModel,
    ClientSupportTicketModel,
)
from app.config.setting import settings
from app.core.database import async_db_session
from app.core.exceptions import CustomException

DEMO_TEMPLATE_NAMES = (
    "订阅权益到账通知",
    "订阅到期提醒",
    "重点用户新功能邀请",
    "服务维护完成通知",
)
DEMO_CAMPAIGN_NAMES = (
    "九月专业版权益到账",
    "九月订阅到期提醒",
    "投标策略复核灰度邀请",
    "九月模型服务维护完成通知",
)
DEMO_TAG_NAMES = ("首批共创", "高频模型用户", "续费稳定")
DEMO_SEGMENT_NAMES = ("核心活跃用户", "订阅续费关注")


async def _ids(db, model, *conditions) -> list[int]:
    return list((await db.scalars(select(model.id).where(*conditions))).all())


async def _count(db, model, *conditions) -> int:
    return int(await db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0)


async def cleanup(*, execute: bool) -> dict:
    environment = getattr(settings.ENVIRONMENT, "value", settings.ENVIRONMENT)
    if execute and environment != "dev":
        raise CustomException(msg="生产环境仅允许预览验证数据，禁止直接执行清理")

    async with async_db_session.begin() as db:
        app = await db.scalar(select(ClientAppModel).where(ClientAppModel.code == "bid_agent"))
        if not app:
            raise CustomException(msg="未找到 bid_agent 客户端")
        user = await db.scalar(
            select(ClientUserModel).where(
                ClientUserModel.app_id == app.id,
                ClientUserModel.username == "client_test",
                ClientUserModel.is_deleted == False,
            )
        )
        if not user:
            raise CustomException(msg="未找到 client_test")

        order_ids = await _ids(
            db,
            PaymentOrderModel,
            PaymentOrderModel.app_id == app.id,
            PaymentOrderModel.user_id == user.id,
            PaymentOrderModel.idempotency_key.like("dev-demo-order-%"),
        )
        cycle_ids = (
            await _ids(
                db,
                SubscriptionCycleModel,
                SubscriptionCycleModel.app_id == app.id,
                SubscriptionCycleModel.order_id.in_(order_ids),
            )
            if order_ids
            else []
        )
        grant_ids = (
            await _ids(
                db,
                CreditGrantModel,
                CreditGrantModel.app_id == app.id,
                CreditGrantModel.source_type == "subscription_cycle",
                CreditGrantModel.source_id.in_(cycle_ids),
            )
            if cycle_ids
            else []
        )
        ticket_ids = await _ids(
            db,
            ClientSupportTicketModel,
            ClientSupportTicketModel.app_id == app.id,
            ClientSupportTicketModel.ticket_no.like("TK20260904DEMO%"),
        )
        campaign_ids = await _ids(
            db,
            ClientMessageCampaignModel,
            ClientMessageCampaignModel.app_id == app.id,
            ClientMessageCampaignModel.name.in_(DEMO_CAMPAIGN_NAMES),
        )
        template_ids = await _ids(
            db,
            ClientMessageTemplateModel,
            ClientMessageTemplateModel.app_id == app.id,
            ClientMessageTemplateModel.name.in_(DEMO_TEMPLATE_NAMES),
        )
        strategy_ids = await _ids(
            db,
            AppPricingStrategyModel,
            AppPricingStrategyModel.app_id == app.id,
            AppPricingStrategyModel.version == "BASE-2026.09",
        )

        preview = {
            "mode": "execute" if execute else "preview",
            "app_id": app.id,
            "user_id": user.id,
            "will_delete": {
                "orders": len(order_ids),
                "subscription_cycles": len(cycle_ids),
                "credit_grants": len(grant_ids),
                "credit_ledgers": await _count(
                    db,
                    CreditLedgerModel,
                    CreditLedgerModel.app_id == app.id,
                    CreditLedgerModel.idempotency_key.like("dev-demo-ledger-%"),
                ),
                "model_usage": await _count(
                    db,
                    ModelUsageModel,
                    ModelUsageModel.app_id == app.id,
                    ModelUsageModel.request_id.like("dev-demo-usage-%"),
                ),
                "telemetry": await _count(
                    db,
                    TelemetryEventModel,
                    TelemetryEventModel.app_id == app.id,
                    TelemetryEventModel.event_id.like("dev-demo-event-%"),
                ),
                "tickets": len(ticket_ids),
                "ticket_messages": (
                    await _count(db, ClientSupportMessageModel, ClientSupportMessageModel.ticket_id.in_(ticket_ids))
                    if ticket_ids
                    else 0
                ),
                "message_deliveries": await _count(
                    db,
                    ClientMessageDeliveryModel,
                    ClientMessageDeliveryModel.app_id == app.id,
                    (ClientMessageDeliveryModel.campaign_id.in_(campaign_ids))
                    | (
                        (ClientMessageDeliveryModel.resource_type == "support_ticket")
                        & ClientMessageDeliveryModel.resource_id.in_([str(item) for item in ticket_ids])
                    ),
                ),
                "message_campaigns": len(campaign_ids),
                "message_templates": len(template_ids),
                "pricing_strategies": len(strategy_ids),
                "user_tags": await _count(
                    db,
                    ClientUserTagModel,
                    ClientUserTagModel.app_id == app.id,
                    ClientUserTagModel.user_id == user.id,
                    ClientUserTagModel.name.in_(DEMO_TAG_NAMES),
                ),
                "user_segments": await _count(
                    db,
                    ClientUserSegmentModel,
                    ClientUserSegmentModel.app_id == app.id,
                    ClientUserSegmentModel.name.in_(DEMO_SEGMENT_NAMES),
                ),
            },
            "retained_shared_records": {
                "user_profile": 1,
                "subscription": await _count(
                    db,
                    SubscriptionModel,
                    SubscriptionModel.app_id == app.id,
                    SubscriptionModel.user_id == user.id,
                ),
                "credit_account": 1,
                "catalog_plans": "retained",
            },
        }
        if not execute:
            return preview

        if campaign_ids or ticket_ids:
            await db.execute(
                delete(ClientMessageDeliveryModel).where(
                    ClientMessageDeliveryModel.app_id == app.id,
                    (ClientMessageDeliveryModel.campaign_id.in_(campaign_ids))
                    | (
                        (ClientMessageDeliveryModel.resource_type == "support_ticket")
                        & ClientMessageDeliveryModel.resource_id.in_([str(item) for item in ticket_ids])
                    ),
                )
            )
        if ticket_ids:
            await db.execute(delete(ClientSupportMessageModel).where(ClientSupportMessageModel.ticket_id.in_(ticket_ids)))
            await db.execute(delete(ClientSupportTicketModel).where(ClientSupportTicketModel.id.in_(ticket_ids)))
        if campaign_ids:
            await db.execute(delete(ClientMessageCampaignModel).where(ClientMessageCampaignModel.id.in_(campaign_ids)))
        if template_ids:
            await db.execute(delete(ClientMessageTemplateModel).where(ClientMessageTemplateModel.id.in_(template_ids)))
        await db.execute(
            delete(ModelUsageModel).where(
                ModelUsageModel.app_id == app.id,
                ModelUsageModel.request_id.like("dev-demo-usage-%"),
            )
        )
        await db.execute(
            delete(TelemetryEventModel).where(
                TelemetryEventModel.app_id == app.id,
                TelemetryEventModel.event_id.like("dev-demo-event-%"),
            )
        )
        await db.execute(
            delete(CreditLedgerModel).where(
                CreditLedgerModel.app_id == app.id,
                CreditLedgerModel.idempotency_key.like("dev-demo-ledger-%"),
            )
        )
        if grant_ids:
            await db.execute(delete(CreditGrantModel).where(CreditGrantModel.id.in_(grant_ids)))
        if cycle_ids:
            await db.execute(delete(SubscriptionCycleModel).where(SubscriptionCycleModel.id.in_(cycle_ids)))
        if order_ids:
            await db.execute(delete(PaymentOrderModel).where(PaymentOrderModel.id.in_(order_ids)))
        if strategy_ids:
            await db.execute(
                delete(AppPricingStrategyItemModel).where(AppPricingStrategyItemModel.strategy_id.in_(strategy_ids))
            )
            await db.execute(delete(AppPricingStrategyModel).where(AppPricingStrategyModel.id.in_(strategy_ids)))
        await db.execute(
            delete(ClientUserTagModel).where(
                ClientUserTagModel.app_id == app.id,
                ClientUserTagModel.user_id == user.id,
                ClientUserTagModel.name.in_(DEMO_TAG_NAMES),
            )
        )
        await db.execute(
            delete(ClientUserSegmentModel).where(
                ClientUserSegmentModel.app_id == app.id,
                ClientUserSegmentModel.name.in_(DEMO_SEGMENT_NAMES),
            )
        )
        return preview


def main() -> None:
    parser = argparse.ArgumentParser(description="预览或清理运营验证数据")
    parser.add_argument("--execute", action="store_true", help="执行清理；默认仅预览")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(cleanup(execute=args.execute)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
