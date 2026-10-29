from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.api.v1.module_billing.grant_messages import notify_credit_grant
from app.api.v1.module_billing.model import CreditGrantModel, CreditLedgerModel
from app.api.v1.module_billing.service import CreditService, SubscriptionService
from app.api.v1.module_finance.entitlements import terminate_order_entitlements
from app.api.v1.module_user_operations.model import ClientMessageDeliveryModel
from app.api.v1.module_user_operations.service import MessagingService
from app.core.base_schema import AuthSchema, CoreUserSchema
from app.core.database import async_db_session
from app.core.exceptions import CustomException
from tests.test_finance_workflow_improvements import subscription_order
from tests.test_growth_accounting import setup_scope


@pytest.mark.asyncio
async def test_upgrade_keeps_issued_credits_stops_old_schedule_and_replay(test_client):
    async with async_db_session() as db:
        scope, users = await setup_scope(db)
        uid = users[0].id
        pro, sub, pro_cycle = await subscription_order(db, scope, uid, "专业版", 20)
        enterprise, _, enterprise_cycle = await subscription_order(db, scope, uid, "企业版", 30)
        credit = CreditService(db)
        account = await credit.account(scope, uid)
        assert (account.available, account.pending) == (200, 50)
        old = list(await db.scalars(select(CreditGrantModel).where(CreditGrantModel.source_type == "subscription_cycle", CreditGrantModel.source_id == pro_cycle.id)))
        assert [(g.status, g.available) for g in old] == [("released", 100), ("superseded", 0)]
        await SubscriptionService(db).activate_paid_order(
            app_id=scope, user_id=uid, order_id=enterprise.id, catalog_plan_id=enterprise.catalog_plan_id, plan_snapshot=enterprise.plan_snapshot, auto_renew=False
        )
        assert (account.available, account.pending) == (200, 50)
        new_pending = await db.scalar(
            select(CreditGrantModel).where(CreditGrantModel.source_type == "subscription_cycle", CreditGrantModel.source_id == enterprise_cycle.id, CreditGrantModel.status == "pending")
        )
        new_pending.release_at = old[1].release_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.flush()
        await credit.release_due(app_id=scope, user_id=uid)
        await credit.release_due(app_id=scope, user_id=uid)
        assert (account.available, account.pending) == (250, 0)
        receipts = list(await db.scalars(select(ClientMessageDeliveryModel).where(ClientMessageDeliveryModel.app_id == scope)))
        assert len(receipts) == 3
        assert all(m.message_type == "credit_grant" and m.deep_link == "/settings/usage" for m in receipts)
        outcome = await terminate_order_entitlements(db, enterprise, "refund-once")
        assert outcome["revoked_available"] == 150
        assert account.available == 100 and account.pending == 0
        assert sub.catalog_plan_id == pro.catalog_plan_id
        await terminate_order_entitlements(db, enterprise, "refund-replay")
        assert account.available == 100
        assert old[1].status == "superseded"
        await db.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["retain", "terminate"])
async def test_refund_waits_for_confirmed_success_and_never_revokes_twice(test_client, action):
    from uuid import uuid4

    from app.api.v1.module_finance import refunds
    from app.api.v1.module_finance.gateway import RefundResult
    from app.api.v1.module_finance.schema import RefundCreate, RefundReview

    async with async_db_session() as db:
        scope, users = await setup_scope(db)
        order, subscription, _ = await subscription_order(db, scope, users[0].id, "基础版", 10)
        account = await CreditService(db).account(scope, users[0].id)
        row = await refunds.create_refund(db, scope, 1, RefundCreate(order_id=order.id, amount_fen=order.amount_fen, entitlement_action=action, reason="测试退款链路", idempotency_key=uuid4().hex))
        await refunds.review_refund(db, scope, row.id, 2, RefundReview(approved=True, reason="核对通过"))
        await refunds.apply_refund(db, row, RefundResult("unknown", reason="渠道超时"))
        assert subscription.status == "active" and (account.available, account.pending) == (100, 50)
        success = RefundResult("succeeded", "rf-" + uuid4().hex, datetime.now(UTC))
        await refunds.apply_refund(db, row, success)
        await refunds.apply_refund(db, row, success)
        assert row.status == "succeeded"
        assert (account.available, account.pending) == ((100, 50) if action == "retain" else (0, 0))
        assert subscription.status == ("active" if action == "retain" else "cancelled")
        await db.rollback()


@pytest.mark.asyncio
async def test_daily_login_receipt_only_after_posting_and_reports_debt_offset(test_client):
    from app.api.v1.module_growth.defaults import default_drafts
    from app.api.v1.module_growth.model import RewardModel
    from app.api.v1.module_growth.referral_service import ReferralService
    from app.api.v1.module_growth.reward_service import RewardService
    from tests.test_growth_accounting import published

    async with async_db_session() as db:
        scope, users = await setup_scope(db)
        await published(db, scope, default_drafts()[2])
        await published(db, scope, next(d for d in default_drafts() if d.key == "daily_login"), require_subscription=False, observe_days=0, budget_credits=10000)
        profile = await ReferralService(db, scope).profile(users[0].id)
        profile.credit_debt = 40
        await db.flush()
        rewards = RewardService(db, scope)
        await rewards.emit(users[0].id, "daily_login", "login:test-day")
        reward = await db.scalar(select(RewardModel).where(RewardModel.app_id == scope))
        assert reward is not None
        assert not await db.scalar(select(ClientMessageDeliveryModel.id).where(ClientMessageDeliveryModel.app_id == scope))
        await rewards.post(reward)
        await rewards.post(reward)
        await rewards.emit(users[0].id, "daily_login", "login:test-day")
        receipts = list(await db.scalars(select(ClientMessageDeliveryModel).where(ClientMessageDeliveryModel.app_id == scope)))
        assert len(receipts) == 1
        assert "每日登录奖励" in receipts[0].content
        assert "40" in receipts[0].content and "实际到账 60" in receipts[0].content
        assert (await CreditService(db).account(scope, users[0].id)).available == 60
        await db.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("due", [True, False])
async def test_legacy_pending_upgrade_is_suppressed_before_release(test_client, due):
    async with async_db_session() as db:
        scope, users = await setup_scope(db)
        _, _, old_cycle = await subscription_order(db, scope, users[0].id, "专业版", 20)
        await subscription_order(db, scope, users[0].id, "企业版", 30)
        account = await CreditService(db).account(scope, users[0].id)
        old = await db.scalar(select(CreditGrantModel).where(CreditGrantModel.source_id == old_cycle.id, CreditGrantModel.source_type == "subscription_cycle", CreditGrantModel.status == "superseded"))
        # Recreate a pre-fix upgrade; no cancellation ledger or state exists yet.
        ledger = await db.scalar(select(CreditLedgerModel).where(CreditLedgerModel.idempotency_key == f"supersede:{scope}:{old.id}"))
        await db.delete(ledger)
        old.status = "pending"
        old.release_at = datetime.now(UTC) + timedelta(seconds=-1 if due else 3600)
        account.pending += old.amount
        await db.flush()
        await CreditService(db).account_out(scope, users[0].id)
        assert old.status == "superseded"
        assert (account.available, account.pending) == (200, 50)
        await db.rollback()


@pytest.mark.asyncio
async def test_receipts_share_transaction_are_deduplicated_and_scope_read_states(test_client):
    async with async_db_session() as db:
        scope, users = await setup_scope(db)
        other_scope, other_users = await setup_scope(db)
        await CreditService(db).adjust(scope, users[0].id, 500, "每日登录奖励", 1)
        grant = await db.scalar(select(CreditGrantModel).where(CreditGrantModel.app_id == scope))
        await notify_credit_grant(db, grant, reason="重复发放")
        auth = AuthSchema(app_id=scope, user=CoreUserSchema(id=users[0].id, username="test", is_superuser=False), actor_type="client")
        messages = MessagingService(auth, db)
        inbox = await messages.inbox()
        assert len(inbox) == 1 and "500" in inbox[0].content and "每日登录奖励" in inbox[0].content
        page = await messages.deliveries(1, 20, message_type="credit_grant", read_status="unread")
        assert page.total == 1 and page.items[0].user_id == users[0].id
        foreign = MessagingService(auth.model_copy(update={"app_id": other_scope, "user": CoreUserSchema(id=other_users[0].id, username="other", is_superuser=False)}), db)
        assert not await foreign.inbox()
        assert (await foreign.deliveries(1, 20)).total == 0
        with pytest.raises(CustomException):
            await foreign.read(inbox[0].id)
        await messages.read(inbox[0].id)
        assert (await messages.deliveries(1, 20, read_status="unread")).total == 0
        assert (await messages.deliveries(1, 20, read_status="read")).total == 1
        async with db.begin_nested() as savepoint:
            await CreditService(db).adjust(scope, users[0].id, 250, "回滚发放", 1)
            await savepoint.rollback()
        assert await db.scalar(select(func.count()).select_from(ClientMessageDeliveryModel).where(ClientMessageDeliveryModel.app_id == scope)) == 1
        await db.rollback()
