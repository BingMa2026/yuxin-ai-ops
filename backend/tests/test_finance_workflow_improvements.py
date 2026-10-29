from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api.v1.module_billing.model import AppCatalogPlanModel, CreditGrantModel, SubscriptionCycleModel
from app.api.v1.module_billing.service import SubscriptionService
from app.api.v1.module_billing.subscription_periods import project_subscription, utc
from app.api.v1.module_finance import bills, refunds
from app.api.v1.module_finance.common import BUSINESS_TZ
from app.api.v1.module_finance.entitlements import terminate_order_entitlements
from app.api.v1.module_finance.schema import BillBatchCreate, RefundCreate, RefundReview
from app.core.database import async_db_session
from app.core.exceptions import CustomException
from tests.test_growth_accounting import payment, setup_scope


async def subscription_order(db, scope, user, name, rank, *, plan_id=None):
    order = await payment(db, scope, user)
    if plan_id:
        order.catalog_plan_id = plan_id
    plan = await db.get(AppCatalogPlanModel, order.catalog_plan_id)
    plan.name, plan.plan_type, plan.tier_order = name, "subscription", rank
    order.plan_snapshot = {
        "name": name,
        "tier_order": rank,
        "plan_type": "subscription",
        "benefit_period_days": 30,
        "credit_valid_days": 30,
        "release_plan": [{"offset_day": 0, "amount": 100}, {"offset_day": 15, "amount": 50}],
    }
    order.provider_trade_no = "TEST" + uuid4().hex
    await db.flush()
    subscription = await SubscriptionService(db).activate_paid_order(
        app_id=scope,
        user_id=user,
        order_id=order.id,
        catalog_plan_id=order.catalog_plan_id,
        plan_snapshot=order.plan_snapshot,
        auto_renew=False,
    )
    cycle = await db.scalar(select(SubscriptionCycleModel).where(SubscriptionCycleModel.order_id == order.id))
    return order, subscription, cycle


@pytest.mark.asyncio
async def test_upgrade_immediate_renewal_sequential_and_refund_restores_original_period(test_client):
    async with async_db_session() as db:
        scope, users = await setup_scope(db)
        pro, subscription, pro_cycle = await subscription_order(db, scope, users[0].id, "专业版", 20)
        original_end = utc(pro_cycle.ends_at)
        now = datetime.now(UTC)
        enterprise, _, enterprise_cycle = await subscription_order(db, scope, users[0].id, "企业版", 30)
        assert now <= utc(enterprise_cycle.starts_at) < now + timedelta(seconds=5)
        assert subscription.catalog_plan_id == enterprise.catalog_plan_id
        assert utc(subscription.current_period_start) == utc(enterprise_cycle.starts_at)
        preview = await refunds.preview_refund(db, scope, enterprise.id, "terminate")
        assert preview["before"]["plan_name"] == "企业版"
        assert preview["after"]["plan_name"] == "专业版"
        assert preview["revoked_available"] == 100 and preview["cancelled_pending"] == 50
        retain = await refunds.preview_refund(db, scope, enterprise.id, "retain")
        assert retain["after"]["plan_name"] == "企业版" and retain["revoked_available"] == 0
        result = await terminate_order_entitlements(db, enterprise, "test-refund")
        assert result["subscription_after"] == "专业版"
        assert subscription.catalog_plan_id == pro.catalog_plan_id
        assert utc(subscription.current_period_end) == original_end
        renewal, _, renewal_cycle = await subscription_order(db, scope, users[0].id, "专业版", 20, plan_id=pro.catalog_plan_id)
        assert utc(renewal_cycle.starts_at) == original_end
        assert utc(subscription.current_period_start) == utc(pro_cycle.starts_at)
        assert utc(subscription.current_period_end) == original_end + timedelta(days=30)
        await terminate_order_entitlements(db, renewal, "test-renewal-refund")
        assert utc(subscription.current_period_end) == original_end
        await db.rollback()


@pytest.mark.asyncio
async def test_refund_expired_original_does_not_activate_future_renewal(test_client):
    async with async_db_session() as db:
        scope, users = await setup_scope(db)
        pro, subscription, pro_cycle = await subscription_order(db, scope, users[0].id, "专业版", 20)
        pro_cycle.starts_at = datetime.now(UTC) - timedelta(days=40)
        pro_cycle.ends_at = subscription.current_period_end = datetime.now(UTC) - timedelta(days=10)
        enterprise, _, enterprise_cycle = await subscription_order(db, scope, users[0].id, "企业版", 30)
        renewal, _, renewal_cycle = await subscription_order(db, scope, users[0].id, "企业版", 30, plan_id=enterprise.catalog_plan_id)
        await terminate_order_entitlements(db, enterprise, "refund-enterprise")
        assert subscription.status != "active"
        assert (await project_subscription(db, subscription))["plan_name"] == "无有效订阅"
        future = await project_subscription(db, subscription, now=utc(renewal_cycle.starts_at) + timedelta(seconds=1))
        assert future["catalog_plan_id"] == renewal.catalog_plan_id
        assert future["status"] == "active"
        await db.rollback()


@pytest.mark.asyncio
async def test_expiry_falls_back_to_still_valid_original_plan(test_client):
    async with async_db_session() as db:
        scope, users = await setup_scope(db)
        pro, subscription, pro_cycle = await subscription_order(db, scope, users[0].id, "专业版", 20)
        enterprise, _, enterprise_cycle = await subscription_order(db, scope, users[0].id, "企业版", 30)
        enterprise_cycle.ends_at = subscription.current_period_end = datetime.now(UTC) - timedelta(seconds=1)
        await SubscriptionService(db).expire_due(scope)
        assert subscription.status == "active"
        assert subscription.catalog_plan_id == pro.catalog_plan_id
        assert utc(subscription.current_period_end) == utc(pro_cycle.ends_at)
        current = await SubscriptionService(db).current_for_client(scope, users[0].id)
        assert current.status == "active" and current.catalog_plan_id == pro.catalog_plan_id
        await db.rollback()


@pytest.mark.asyncio
async def test_refund_preview_scope_and_stale_approval_rejected(test_client):
    async with async_db_session() as db:
        scope, users = await setup_scope(db)
        other, _ = await setup_scope(db)
        order, _, cycle = await subscription_order(db, scope, users[0].id, "专业版", 20)
        with pytest.raises(CustomException):
            await refunds.preview_refund(db, other, order.id, "terminate")
        preview = await refunds.preview_refund(db, scope, order.id, "terminate")
        data = RefundCreate(order_id=order.id, amount_fen=10000, reason="测试退款", entitlement_action="terminate", idempotency_key=uuid4().hex, preview_token=preview["preview_token"])
        row = await refunds.create_refund(db, scope, 1, data)
        grant = await db.scalar(select(CreditGrantModel).where(CreditGrantModel.source_type == "subscription_cycle", CreditGrantModel.source_id == cycle.id, CreditGrantModel.status == "released"))
        grant.available -= 1
        await db.flush()
        with pytest.raises(CustomException, match="用户订阅或积分已变化"):
            await refunds.review_refund(db, scope, row.id, 2, RefundReview(approved=True, reason="同意退款", preview_token=preview["preview_token"]))
        assert row.status == "review"
        fresh = await refunds.preview_refund(db, scope, order.id, "terminate")
        await refunds.review_refund(db, scope, row.id, 2, RefundReview(approved=True, reason="重新核对", preview_token=fresh["preview_token"]))
        assert row.status == "queued"
        await db.rollback()


@pytest.mark.asyncio
async def test_batch_bill_dates_idempotency_retry_and_scope(test_client):
    async with async_db_session() as db:
        scope, _ = await setup_scope(db)
        other, _ = await setup_scope(db)
        end = datetime.now(BUSINESS_TZ).date() - timedelta(days=1)
        data = BillBatchCreate(provider="alipay", start_date=end - timedelta(days=2), end_date=end)
        rows = await bills.request_bill_batch(db, scope, 1, data)
        assert len(rows) == 3
        rows[0].status = "completed"
        rows[1].status = "failed"
        await db.flush()
        again = await bills.request_bill_batch(db, scope, 1, data)
        assert [r.id for r in rows] == [r.id for r in again]
        assert [r.status for r in again] == ["completed", "queued", "queued"]
        foreign = await bills.request_bill_batch(db, other, 1, data)
        assert {r.id for r in rows}.isdisjoint(r.id for r in foreign)
        with pytest.raises(CustomException):
            await bills.request_bill_batch(db, scope, 1, data.model_copy(update={"end_date": end + timedelta(days=1)}))
        await db.rollback()
    with pytest.raises(ValueError):
        BillBatchCreate(provider="alipay", start_date=end, end_date=end - timedelta(days=1))
    with pytest.raises(ValueError):
        BillBatchCreate(provider="alipay", start_date=end - timedelta(days=31), end_date=end)


@pytest.mark.asyncio
async def test_daily_bills_respect_time_configuration_scope_and_do_not_retry_failed_forever(test_client, monkeypatch):
    from app.api.v1.module_payment.channel.model import AppPaymentChannelModel, PaymentChannelModel
    from app.api.v1.module_payment.channel.service import PaymentChannelService
    from app.config.setting import settings

    monkeypatch.setattr(settings, "FINANCE_AUTO_RECONCILE", True)
    monkeypatch.setattr(settings, "FINANCE_RECONCILE_HOUR", 10)
    monkeypatch.setattr(PaymentChannelService, "_runtime_status", lambda *args: ([], None, True))
    now = datetime.now(BUSINESS_TZ).replace(hour=10, minute=0)
    async with async_db_session() as db:
        scope, _ = await setup_scope(db)
        other, _ = await setup_scope(db)
        channel = await db.scalar(select(PaymentChannelModel).where(PaymentChannelModel.provider == "alipay"))
        if not channel:
            channel = PaymentChannelModel(provider="alipay", name="支付宝", enabled=True, mode="production")
            db.add(channel)
            await db.flush()
        channel.enabled, channel.mode = True, "production"
        db.add(AppPaymentChannelModel(app_id=scope, channel_id=channel.id, enabled=True))
        await db.flush()
        assert await bills.schedule_daily_bills(db, scope, now=now.replace(hour=9)) == []
        assert await bills.schedule_daily_bills(db, other, now=now) == []
        rows = await bills.schedule_daily_bills(db, scope, now=now)
        assert len(rows) == 1 and rows[0].requested_by == 0
        assert rows[0].bill_date == now.date() - timedelta(days=1)
        rows[0].status = "failed"
        await db.flush()
        assert await bills.schedule_daily_bills(db, scope, now=now) == []
        assert rows[0].status == "failed"
        monkeypatch.setattr(settings, "FINANCE_AUTO_RECONCILE", False)
        assert await bills.schedule_daily_bills(db, scope, now=now + timedelta(days=1)) == []
        monkeypatch.setattr(settings, "FINANCE_AUTO_RECONCILE", True)
        monkeypatch.setattr(PaymentChannelService, "_runtime_status", lambda *args: (["missing"], None, False))
        assert await bills.schedule_daily_bills(db, scope, now=now + timedelta(days=1)) == []
        await db.rollback()
