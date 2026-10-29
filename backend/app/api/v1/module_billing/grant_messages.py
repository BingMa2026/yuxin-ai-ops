"""Credit receipts written in the same transaction as the grant and ledger."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.module_user_operations.model import ClientMessageDeliveryModel

from .model import CreditGrantModel


async def notify_credit_grant(db: AsyncSession, grant: CreditGrantModel, *, reason: str = "", offset: int = 0) -> None:
    # Callers hold the credit account lock. The grant ID is the stable receipt
    # identity; retries must not create another message, even after soft deletion.
    if grant.status != "released" or grant.amount <= 0:
        return
    await db.flush()
    existing = await db.scalar(
        select(ClientMessageDeliveryModel.id).where(
            ClientMessageDeliveryModel.app_id == grant.app_id,
            ClientMessageDeliveryModel.user_id == grant.user_id,
            ClientMessageDeliveryModel.resource_type == "credit_grant",
            ClientMessageDeliveryModel.resource_id == str(grant.id),
        )
    )
    if existing:
        return
    source = reason or {
        "subscription_cycle": "订阅积分发放",
        "credit_pack_order": "积分包到账",
        "growth_reward": "活动奖励",
        "manual": "运营赠送",
    }.get(grant.source_type, "积分发放")
    content = f"{source}：本次发放 {grant.amount:,} 积分。"
    if offset:
        content += f"其中 {offset:,} 积分抵扣历史退款追偿，实际到账 {grant.amount - offset:,} 积分。"
    content += "积分有效期及余额可在订阅与用量的积分明细中查看。"
    db.add(
        ClientMessageDeliveryModel(
            app_id=grant.app_id,
            user_id=grant.user_id,
            message_type="credit_grant",
            title="积分到账通知",
            content=content,
            content_type="plain_text",
            deep_link="/settings/usage",
            resource_type="credit_grant",
            resource_id=str(grant.id),
            delivered_at=datetime.now(UTC),
            status="delivered",
        )
    )
    await db.flush()
