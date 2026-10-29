"""Idempotent development data for the real ``bid_agent/client_test`` account.

This module is intentionally excluded from normal initialization. It refuses to
run outside the development environment and never creates another client or user.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.api.v1.module_billing.model import (
    AppCatalogPlanModel,
    AppPricingStrategyItemModel,
    AppPricingStrategyModel,
    CreditAccountModel,
    CreditGrantModel,
    CreditLedgerModel,
    SubscriptionCycleModel,
    SubscriptionModel,
)
from app.api.v1.module_client.app.model import ClientAppModel
from app.api.v1.module_client.user.model import (
    ClientUserLevelConfigModel,
    ClientUserModel,
    ClientUserSegmentModel,
    ClientUserTagModel,
)
from app.api.v1.module_client.user.service import DEFAULT_LEVEL_RULES
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


async def _get_or_create(db, model, filters: dict, values: dict):
    row = await db.scalar(select(model).filter_by(**filters))
    if row:
        return row
    row = model(**filters, **values)
    db.add(row)
    await db.flush()
    return row


async def seed() -> dict[str, int]:
    if getattr(settings.ENVIRONMENT, "value", settings.ENVIRONMENT) != "dev":
        raise CustomException(msg="演示数据脚本只能在开发环境执行")

    now = datetime.now(UTC)
    async with async_db_session.begin() as db:
        app = await db.scalar(select(ClientAppModel).where(ClientAppModel.code == "bid_agent"))
        if not app:
            raise CustomException(msg="未找到 bid_agent 客户端，请先执行基础数据初始化")
        user = await db.scalar(
            select(ClientUserModel).where(
                ClientUserModel.app_id == app.id,
                ClientUserModel.username == "client_test",
                ClientUserModel.is_deleted == False,
            )
        )
        if not user:
            raise CustomException(msg="未找到 client_test，请先创建测试账号")

        user.display_name = "张明轩"
        user.company_name = "喻信数字科技有限公司"
        user.mobile = "13800138888"
        user.email = "client_test@yuxin.example"
        user.description = "招投标智能体首批共创用户，关注招标文件分析、评分点提取与投标方案生成。"
        user.last_login_at = now - timedelta(hours=2)
        user.last_active_at = now - timedelta(minutes=18)
        user.level_code = "LV4"
        user.level_score = 65.6
        user.level_evaluated_at = now
        user.level_metrics = {
            "total_paid_fen": 59500,
            "active_days_30d": 20,
            "model_calls_30d": 120,
            "credits_used_30d": 78000,
            "feedback_contribution": 5,
        }

        for name, color in (("首批共创", "primary"), ("高频模型用户", "success"), ("续费稳定", "warning")):
            await _get_or_create(
                db,
                ClientUserTagModel,
                {"app_id": app.id, "user_id": user.id, "name": name},
                {"color": color, "status": "active"},
            )

        config = await db.scalar(
            select(ClientUserLevelConfigModel).where(
                ClientUserLevelConfigModel.app_id == app.id,
                ClientUserLevelConfigModel.is_deleted == False,
            )
        )
        if config:
            config.rules = DEFAULT_LEVEL_RULES
        else:
            db.add(
                ClientUserLevelConfigModel(
                    app_id=app.id,
                    version=1,
                    rules=DEFAULT_LEVEL_RULES,
                    status="active",
                )
            )

        for name, description, filters in (
            ("核心活跃用户", "LV4-LV5高价值活跃用户", {"level_code": "LV4", "status": "active"}),
            ("订阅续费关注", "订阅中且需要重点维护的用户", {"status": "active"}),
        ):
            await _get_or_create(
                db,
                ClientUserSegmentModel,
                {"app_id": app.id, "name": name},
                {"description": description, "filters": filters, "status": "active"},
            )

        plans = list(
            (
                await db.scalars(
                    select(AppCatalogPlanModel).where(
                        AppCatalogPlanModel.app_id == app.id,
                        AppCatalogPlanModel.is_deleted == False,
                    )
                )
            ).all()
        )
        for plan in plans:
            plan.status = "on_sale"
            if not plan.benefits:
                plan.benefits = ["招标文件智能分析", "模型服务", "算力积分按规则释放"]
            if plan.code == "trial":
                plan.cost_budget_yuan = Decimal("0.12")
        professional = next((item for item in plans if item.code == "professional"), None)
        if not professional:
            raise CustomException(msg="未找到 professional 刊例，请重新执行初始化")

        strategy = await _get_or_create(
            db,
            AppPricingStrategyModel,
            {"app_id": app.id, "version": "BASE-2026.09"},
            {
                "pricing_version_id": professional.pricing_version_id,
                "catalog_plan_id": professional.id,
                "name": "首发标准定价",
                "purchase_type": "all",
                "discount_rate": Decimal("1"),
                "starts_at": now - timedelta(days=30),
                "ends_at": now + timedelta(days=3650),
                "status": "active",
                "description": "覆盖当前全部刊例的首发标准策略，按目标毛利率核算模型成本与积分扣减。",
                "scope_type": "all",
                "scope_value": {},
                "published_at": now,
            },
        )
        strategy.pricing_version_id = professional.pricing_version_id
        strategy.catalog_plan_id = professional.id
        strategy.name = "首发标准定价"
        strategy.purchase_type = "all"
        strategy.discount_rate = Decimal("1")
        strategy.starts_at = now - timedelta(days=30)
        strategy.ends_at = now + timedelta(days=3650)
        strategy.status = "active"
        strategy.scope_type = "all"
        strategy.scope_value = {}
        strategy.published_at = strategy.published_at or now

        for plan in plans:
            execution_price_fen = plan.one_time_price_fen
            allowed_cost_yuan = (
                Decimal(str(plan.cost_budget_yuan or "0.12"))
                if execution_price_fen == 0
                else Decimal(execution_price_fen) / Decimal(100) * Decimal("0.4")
            )
            credits_per_cost_yuan = Decimal(plan.total_credits) / allowed_cost_yuan
            strategy_item = await _get_or_create(
                db,
                AppPricingStrategyItemModel,
                {
                    "app_id": app.id,
                    "strategy_id": strategy.id,
                    "catalog_plan_id": plan.id,
                    "purchase_type": "all",
                },
                {
                    "discount_rate": Decimal("1"),
                    "execution_price_fen": execution_price_fen,
                    "margin_rate": Decimal("60"),
                    "allowed_cost_yuan": allowed_cost_yuan,
                    "credits_per_cost_yuan": credits_per_cost_yuan,
                    "remark": "首发标准价格",
                },
            )
            strategy_item.discount_rate = Decimal("1")
            strategy_item.execution_price_fen = execution_price_fen
            strategy_item.margin_rate = Decimal("60")
            strategy_item.allowed_cost_yuan = allowed_cost_yuan
            strategy_item.credits_per_cost_yuan = credits_per_cost_yuan
            strategy_item.remark = "首发标准价格"

        subscription = await _get_or_create(
            db,
            SubscriptionModel,
            {"app_id": app.id, "user_id": user.id},
            {
                "catalog_plan_id": professional.id,
                "status": "active",
                "auto_renew": True,
                "current_period_start": now - timedelta(days=12),
                "current_period_end": now + timedelta(days=18),
                "next_renewal_at": now + timedelta(days=18),
            },
        )
        subscription.catalog_plan_id = professional.id
        subscription.status = "active"
        subscription.auto_renew = True
        subscription.current_period_start = now - timedelta(days=12)
        subscription.current_period_end = now + timedelta(days=18)
        subscription.next_renewal_at = now + timedelta(days=18)

        plan_snapshot = {
            "plan_name": professional.name,
            "plan_code": professional.code,
            "total_credits": professional.total_credits,
            "execution_price_fen": professional.recurring_price_fen,
            "margin_rate": "60",
            "credits_per_cost_yuan": "2500",
        }
        cycle = await _get_or_create(
            db,
            SubscriptionCycleModel,
            {"app_id": app.id, "subscription_id": subscription.id, "cycle_no": 5},
            {
                "user_id": user.id,
                "order_id": None,
                "starts_at": subscription.current_period_start,
                "ends_at": subscription.current_period_end,
                "plan_snapshot": plan_snapshot,
                "status": "active",
            },
        )

        account = await _get_or_create(
            db,
            CreditAccountModel,
            {"app_id": app.id, "user_id": user.id},
            {"available": 42800, "reserved": 0, "pending": 12000, "total_granted": 132800, "total_consumed": 78000, "status": "active"},
        )
        account.available = 42800
        account.reserved = 0
        account.pending = 12000
        account.total_granted = 132800
        account.total_consumed = 78000

        grant = await _get_or_create(
            db,
            CreditGrantModel,
            {"app_id": app.id, "source_type": "subscription_cycle", "source_id": cycle.id, "release_index": 0},
            {
                "user_id": user.id,
                "account_type": "current_cycle",
                "amount": 12000,
                "available": 8800,
                "reserved": 0,
                "release_at": now - timedelta(days=12),
                "expires_at": now + timedelta(days=18),
                "status": "released",
                "credits_per_cost_yuan": Decimal("2500"),
                "pricing_snapshot": plan_snapshot,
            },
        )
        for index, (amount, reason, days) in enumerate(
            ((12000, "专业版订阅权益到账", 12), (-8600, "模型调用实际结算", 10), (25000, "共创用户运营赠送", 8), (-18400, "模型调用实际结算", 5), (12800, "积分包即时到账", 2))
        ):
            await _get_or_create(
                db,
                CreditLedgerModel,
                {"app_id": app.id, "idempotency_key": f"dev-demo-ledger-{index}"},
                {
                    "user_id": user.id,
                    "grant_id": grant.id if amount < 0 else None,
                    "entry_type": "consume" if amount < 0 else "grant",
                    "amount": amount,
                    "balance_after": 18000 + sum(value for value, _, _ in ((12000, "", 0), (-8600, "", 0), (25000, "", 0), (-18400, "", 0), (12800, "", 0))[: index + 1]),
                    "reference_type": "demo",
                    "reference_id": str(index),
                    "reason": reason,
                    "status": "posted",
                    "created_time": now - timedelta(days=days),
                },
            )

        paid_amounts = (19900, 9900, 9900, 9900, 9900)
        for index, amount in enumerate(paid_amounts, 1):
            paid_at = now - timedelta(days=30 * (len(paid_amounts) - index) + 12)
            order = await _get_or_create(
                db,
                PaymentOrderModel,
                {"app_id": app.id, "user_id": user.id, "idempotency_key": f"dev-demo-order-{index}"},
                {
                    "order_no": f"DEV{app.id:03d}{user.id:05d}{index:02d}",
                    "catalog_plan_id": professional.id,
                    "purchase_type": "first" if index == 1 else "renewal",
                    "provider": "wechat",
                    "amount_fen": amount,
                    "currency": "CNY",
                    "plan_snapshot": plan_snapshot,
                    "strategy_snapshot": {"version": "DEV-2026.09", "discount_rate": "1", "margin_rate": "60"},
                    "status": "paid",
                    "expires_at": paid_at + timedelta(minutes=30),
                    "paid_at": paid_at,
                    "provider_trade_no": f"DEVTRADE{index:04d}",
                    "created_time": paid_at,
                },
            )
            if index == len(paid_amounts):
                cycle.order_id = order.id

        for index in range(120):
            age = index % 20
            created = now - timedelta(days=age, hours=index % 11)
            charged = 480 + (index % 7) * 40
            await _get_or_create(
                db,
                ModelUsageModel,
                {"app_id": app.id, "request_id": f"dev-demo-usage-{index:03d}"},
                {
                    "user_id": user.id,
                    "business_code": ("bid_analysis", "document_generate", "knowledge_qa")[index % 3],
                    "provider_model_id": ("qwen-plus", "deepseek-chat", "glm-4-plus")[index % 3],
                    "input_tokens": 1800 + index * 3,
                    "output_tokens": 620 + index * 2,
                    "charged_credits": charged,
                    "provider_cost_yuan": Decimal(charged) / Decimal(2500),
                    "latency_ms": 980 + (index % 13) * 83,
                    "first_token_ms": 210 + (index % 7) * 19,
                    "status": "failed" if index in {37, 83} else "succeeded",
                    "error_category": "upstream_timeout" if index in {37, 83} else None,
                    "completed_at": created + timedelta(seconds=2),
                    "created_time": created,
                },
            )

        for index in range(20):
            await _get_or_create(
                db,
                TelemetryEventModel,
                {"app_id": app.id, "event_id": f"dev-demo-event-{index:03d}"},
                {
                    "user_id": user.id,
                    "event_type": "project_opened",
                    "occurred_at": now - timedelta(days=index),
                    "source": "desktop",
                    "client_version": "1.8.0",
                    "session_ref": f"demo-session-{index // 3}",
                    "project_ref": f"demo-project-{index % 7}",
                    "critical": False,
                    "event_metadata": {"source": "development_seed"},
                },
            )

        ticket_specs = (
            ("feedback", "feature", "希望支持招标评分点批量导出", "high", "processing", True),
            ("feedback", "ai_quality", "长文档评分点识别需要提升稳定性", "normal", "waiting_user", True),
            ("complaint", "billing", "积分扣减记录与任务时间需要更好对应", "urgent", "resolved", False),
            ("feedback", "experience", "生成结果页希望增加版本对比", "normal", "pending", False),
            ("feedback", "feature", "建议支持企业模板库共享", "low", "closed", True),
            ("complaint", "bug", "大型附件偶尔上传失败", "high", "processing", False),
            ("feedback", "other", "希望增加每月使用报告", "low", "resolved", True),
        )
        for index, (kind, category, subject, priority, status, adopted) in enumerate(ticket_specs, 1):
            ticket = await _get_or_create(
                db,
                ClientSupportTicketModel,
                {"app_id": app.id, "ticket_no": f"TK20260904DEMO{index:02d}"},
                {
                    "user_id": user.id,
                    "kind": kind,
                    "category": category,
                    "subject": subject,
                    "content": f"在日常使用招投标智能体时发现：{subject}。希望产品团队评估并给出处理进度。",
                    "attachments": [],
                    "priority": priority,
                    "status": status,
                    "sla_due_at": now + timedelta(hours={"urgent": 4, "high": 24, "normal": 48, "low": 72}[priority]),
                    "last_replied_at": now - timedelta(hours=index),
                    "resolved_at": now - timedelta(hours=index) if status in {"resolved", "closed"} else None,
                    "adopted": adopted,
                    "created_time": now - timedelta(days=index * 2),
                },
            )
            if index <= 4:
                existing_message = await db.scalar(
                    select(ClientSupportMessageModel).where(
                        ClientSupportMessageModel.app_id == app.id,
                        ClientSupportMessageModel.ticket_id == ticket.id,
                        ClientSupportMessageModel.sender_type == "staff",
                    )
                )
                if not existing_message:
                    reply = "我们已完成问题复现并进入处理队列，后续进展会通过站内消息同步。" if status not in {"resolved", "closed"} else "该问题已处理完成，相关记录已核对并修复，感谢你的反馈。"
                    db.add(
                        ClientSupportMessageModel(
                            app_id=app.id, ticket_id=ticket.id, sender_type="staff", sender_id=1, content=reply, attachments=[], internal=False, created_time=now - timedelta(hours=index)
                        )
                    )
                    db.add(
                        ClientMessageDeliveryModel(
                            app_id=app.id,
                            campaign_id=None,
                            user_id=user.id,
                            message_type="ticket_reply",
                            title=f"工单 {ticket.ticket_no} 有新回复",
                            content=reply,
                            content_type="plain_text",
                            deep_link=f"/settings/support?ticketId={ticket.id}",
                            resource_type="support_ticket",
                            resource_id=str(ticket.id),
                            delivered_at=now - timedelta(hours=index),
                            status="delivered",
                        )
                    )

        template = await _get_or_create(
            db,
            ClientMessageTemplateModel,
            {"app_id": app.id, "name": "订阅权益到账通知"},
            {
                "title": "专业版权益已到账",
                "content": "<h3>专业版权益已到账</h3><p>本周期算力积分已按计划释放，你可以继续使用招标文件分析、评分点提取和投标方案生成。</p><p><strong>当前可用积分：42,800</strong></p>",
                "content_type": "rich_text",
                "status": "active",
            },
        )
        campaign = await _get_or_create(
            db,
            ClientMessageCampaignModel,
            {"app_id": app.id, "name": "九月专业版权益到账"},
            {
                "template_id": template.id,
                "title": template.title,
                "content": template.content,
                "content_type": "rich_text",
                "audience_type": "users",
                "audience_value": {"user_ids": [user.id]},
                "scheduled_at": None,
                "timezone": "Asia/Shanghai",
                "sent_at": now - timedelta(days=2),
                "status": "sent",
                "target_count": 1,
                "delivered_count": 1,
                "read_count": 0,
                "failed_count": 0,
            },
        )
        await _get_or_create(
            db,
            ClientMessageDeliveryModel,
            {"campaign_id": campaign.id, "user_id": user.id},
            {
                "app_id": app.id,
                "message_type": "campaign",
                "title": campaign.title,
                "content": campaign.content,
                "content_type": "rich_text",
                "deep_link": "/settings/billing",
                "resource_type": "subscription",
                "resource_id": str(subscription.id),
                "delivered_at": now - timedelta(days=2),
                "status": "delivered",
            },
        )

        renewal_template = await _get_or_create(
            db,
            ClientMessageTemplateModel,
            {"app_id": app.id, "name": "订阅到期提醒"},
            {
                "title": "专业版订阅将在7天后到期",
                "content": "<h3>订阅到期提醒</h3><p>你的专业版订阅将在 <strong>7天后</strong> 到期。续费后，当前工作空间、历史项目和剩余积分都不会受到影响。</p><p>建议提前完成续费，避免正在进行的标书任务中断。</p>",
                "content_type": "rich_text",
                "status": "active",
            },
        )
        await _get_or_create(
            db,
            ClientMessageCampaignModel,
            {"app_id": app.id, "name": "九月订阅到期提醒"},
            {
                "template_id": renewal_template.id,
                "title": renewal_template.title,
                "content": renewal_template.content,
                "content_type": "rich_text",
                "audience_type": "users",
                "audience_value": {"user_ids": [user.id]},
                "scheduled_at": now + timedelta(days=3),
                "timezone": "Asia/Shanghai",
                "sent_at": None,
                "status": "scheduled",
                "target_count": 1,
                "delivered_count": 0,
                "read_count": 0,
                "failed_count": 0,
            },
        )

        feature_template = await _get_or_create(
            db,
            ClientMessageTemplateModel,
            {"app_id": app.id, "name": "重点用户新功能邀请"},
            {
                "title": "邀请体验投标策略复核功能",
                "content": "<h3>共创用户专属邀请</h3><p>我们正在小范围开放投标策略复核功能，可自动检查评分点覆盖、响应偏离和高风险条款。</p><p><strong>本次仅邀请 LV4–LV5 用户。</strong>体验反馈将直接进入产品优化清单。</p>",
                "content_type": "rich_text",
                "status": "active",
            },
        )
        feature_campaign = await _get_or_create(
            db,
            ClientMessageCampaignModel,
            {"app_id": app.id, "name": "投标策略复核灰度邀请"},
            {
                "template_id": feature_template.id,
                "title": feature_template.title,
                "content": feature_template.content,
                "content_type": "rich_text",
                "audience_type": "level",
                "audience_value": {"level_codes": ["LV4", "LV5"]},
                "scheduled_at": None,
                "timezone": "Asia/Shanghai",
                "sent_at": None,
                "status": "draft",
                "target_count": 1,
                "delivered_count": 0,
                "read_count": 0,
                "failed_count": 0,
            },
        )
        feature_campaign.audience_type = "level"
        feature_campaign.audience_value = {"level_codes": ["LV4", "LV5"]}

        service_template = await _get_or_create(
            db,
            ClientMessageTemplateModel,
            {"app_id": app.id, "name": "服务维护完成通知"},
            {
                "title": "模型服务维护已完成",
                "content": "<h3>服务已恢复</h3><p>模型网关维护已完成，文件解析、智能问答和内容生成均已恢复正常。</p><p>如仍遇到异常，可在“问题反馈”中直接提交，我们会持续跟进。</p>",
                "content_type": "rich_text",
                "status": "active",
            },
        )
        maintenance_campaign = await _get_or_create(
            db,
            ClientMessageCampaignModel,
            {"app_id": app.id, "name": "九月模型服务维护完成通知"},
            {
                "template_id": service_template.id,
                "title": service_template.title,
                "content": service_template.content,
                "content_type": "rich_text",
                "audience_type": "all",
                "audience_value": {},
                "scheduled_at": None,
                "timezone": "Asia/Shanghai",
                "sent_at": now - timedelta(days=5),
                "status": "sent",
                "target_count": 1,
                "delivered_count": 1,
                "read_count": 1,
                "failed_count": 0,
            },
        )
        await _get_or_create(
            db,
            ClientMessageDeliveryModel,
            {"campaign_id": maintenance_campaign.id, "user_id": user.id},
            {
                "app_id": app.id,
                "message_type": "campaign",
                "title": maintenance_campaign.title,
                "content": maintenance_campaign.content,
                "content_type": "rich_text",
                "deep_link": "/dashboard",
                "resource_type": "service_notice",
                "resource_id": "model-gateway-maintenance-202609",
                "delivered_at": now - timedelta(days=5),
                "read_at": now - timedelta(days=4, hours=20),
                "status": "read",
            },
        )

    return {"user_id": user.id, "plans": len(plans), "model_usage": 120, "tickets": len(ticket_specs)}


if __name__ == "__main__":
    print(asyncio.run(seed()))
