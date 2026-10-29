from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.api.v1.module_client.app.model import ClientAppModel
from app.api.v1.module_client.user.model import ClientUserModel
from app.api.v1.module_growth.defaults import default_drafts
from app.api.v1.module_growth.model import CashLedgerModel, GrowthEventModel, GrowthPolicyModel, PayoutAccountModel, ReferralModel, RewardModel, WithdrawalModel
from app.api.v1.module_growth.payout_providers import PayoutResult
from app.api.v1.module_growth.payout_service import PayoutService
from app.api.v1.module_growth.referral_service import ReferralService
from app.api.v1.module_growth.reward_service import RewardService, cash_account
from app.api.v1.module_growth.schema import RuleDraftIn, TaskClaimIn, TaskCompleteIn
from app.api.v1.module_growth.service import PolicyService
from app.api.v1.module_growth.task_service import TaskService
from app.core.database import async_db_session
from app.core.exceptions import CustomException


async def setup_scope(db):
    app = ClientAppModel(service_mode="credits_only", code=uuid4().hex, name="Growth test", status="active", registration_enabled=True)
    db.add(app)
    await db.flush()
    users = [ClientUserModel(app_id=app.id, username=uuid4().hex[:20], password_hash="not-used") for _ in range(3)]
    db.add_all(users)
    await db.flush()
    return app.id, users


async def published(db, app_id, draft, **config):
    data = draft.model_dump(mode="json")
    data["config"].update(config)
    row = await PolicyService(db, app_id).save(RuleDraftIn.model_validate(data))
    await PolicyService(db, app_id).publish(row["id"], datetime.now(UTC))
    return await db.get(GrowthPolicyModel, row["id"])


async def payment(db, scope, user_id, amount=10000):
    from app.api.v1.module_billing.model import AppCatalogPlanModel, PricingStandardVersionModel
    from app.api.v1.module_payment.order.model import PaymentOrderModel

    version = PricingStandardVersionModel(version=uuid4().hex, name="test", status="published")
    db.add(version)
    await db.flush()
    plan = AppCatalogPlanModel(
        app_id=scope, pricing_version_id=version.id, code=uuid4().hex, name="test", plan_type="credit_pack", one_time_price_fen=amount, recurring_price_fen=0, total_credits=50000
    )
    db.add(plan)
    await db.flush()
    row = PaymentOrderModel(
        app_id=scope,
        user_id=user_id,
        order_no=uuid4().hex,
        idempotency_key=uuid4().hex,
        catalog_plan_id=plan.id,
        purchase_type="first",
        provider="alipay",
        amount_fen=amount,
        plan_snapshot={"plan_type": "credit_pack"},
        status="paid",
        paid_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(row)
    await db.flush()
    return row


@pytest.mark.asyncio
async def test_budget_is_atomic_for_two_recipients_and_duplicate_events(test_client):
    async with async_db_session() as db:
        try:
            scope, users = await setup_scope(db)
            inviter, invitee, next_user = users
            db.add(ReferralModel(app_id=scope, inviter_id=inviter.id, invitee_id=invitee.id, source="registration", bound_at=datetime.now(UTC), risk_status="passed"))
            await db.flush()
            drafts = default_drafts()
            await published(db, scope, drafts[2])
            rule = await published(db, scope, next(d for d in drafts if d.key == "first_task"), mode="auto", budget_credits=4000)
            service = RewardService(db, scope)
            first = await service.emit(invitee.id, "first_task", f"first:{invitee.id}")
            duplicate = await service.emit(invitee.id, "first_task", f"first:{invitee.id}")
            assert first.id == duplicate.id
            rewards = list(await db.scalars(select(RewardModel).where(RewardModel.app_id == scope)))
            assert len(rewards) == 2 and sum(r.amount for r in rewards) == rule.used_credits == 4000
            await service.emit(next_user.id, "first_task", f"first:{next_user.id}")
            assert await db.scalar(select(func.count()).select_from(RewardModel).where(RewardModel.app_id == scope)) == 2
            # Stopping prevents future events without changing old pending obligations.
            await PolicyService(db, scope).stop(rule.id)
            assert await PolicyService(db, scope).active("incentive") == []
            assert all(r.status == "pending" for r in rewards)
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_task_claims_are_owner_scoped_and_duplicate_artifacts_do_not_reward(test_client):
    async with async_db_session() as db:
        try:
            scope, users = await setup_scope(db)
            tasks = TaskService(db, scope)
            claim = TaskClaimIn(local_task_id="local-task-one", project_ref="project-one", kind="full_review")
            task = await tasks.claim(users[0].id, claim)
            assert (await tasks.claim(users[0].id, claim)).id == task.id
            with pytest.raises(CustomException):
                await tasks.complete(task.id, users[1].id, TaskCompleteIn(result="completed", artifact_ref="artifact-one"))
            await tasks.complete(task.id, users[0].id, TaskCompleteIn(result="failed"))
            await tasks.claim(users[0].id, claim)
            await tasks.complete(task.id, users[0].id, TaskCompleteIn(result="completed", artifact_ref="artifact-one"))
            assert task.status == "review"
            await tasks.review(task.id, True, "已核对业务成果")
            other = await tasks.claim(users[0].id, claim.model_copy(update={"local_task_id": "local-task-two"}))
            await tasks.complete(other.id, users[0].id, TaskCompleteIn(result="completed", artifact_ref="artifact-one"))
            await tasks.review(other.id, True, "重复提交成果")
            assert other.status == "rejected"
            assert await db.scalar(select(func.count()).select_from(GrowthEventModel).where(GrowthEventModel.app_id == scope, GrowthEventModel.kind == "first_task")) == 1
            eligibility = await ReferralService(db, scope).eligibility(users[0].id)
            assert not eligibility["eligible"]
            users[2].registered_at = datetime.now(UTC) - timedelta(hours=72, seconds=1)
            await db.flush()
            assert not (await ReferralService(db, scope).eligibility(users[2].id))["eligible"]
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_payout_unknown_keeps_frozen_and_terminal_replays_are_idempotent(test_client):
    async with async_db_session() as db:
        try:
            scope, users = await setup_scope(db)
            uid = users[0].id
            account = await cash_account(db, scope, uid)
            account.available, account.frozen, account.debt = 20, 10000, 2000
            payee = PayoutAccountModel(app_id=scope, user_id=uid, provider="alipay", encrypted_details="test", masked_label="masked", status="ready")
            db.add(payee)
            await db.flush()
            withdrawal = WithdrawalModel(
                app_id=scope,
                user_id=uid,
                account_id=payee.id,
                provider="alipay",
                out_bill_no=uuid4().hex,
                idempotency_key=uuid4().hex,
                amount_fen=10000,
                status="unknown",
                policy_snapshot={},
                payee_snapshot="test",
            )
            db.add(withdrawal)
            await db.flush()
            service = PayoutService(db, scope)
            await service.apply(withdrawal, PayoutResult("unknown"))
            assert (account.available, account.frozen, account.debt) == (20, 10000, 2000)
            await service.apply(withdrawal, PayoutResult("failed"))
            assert (account.available, account.frozen, account.debt) == (8020, 0, 0)
            await service.apply(withdrawal, PayoutResult("failed"))
            await service.apply(withdrawal, PayoutResult("succeeded"))
            assert withdrawal.status == "failed"
            ledger = list(await db.scalars(select(CashLedgerModel).where(CashLedgerModel.app_id == scope)))
            assert len(ledger) == 1
            assert (ledger[0].amount, ledger[0].frozen_delta, ledger[0].debt_delta) == (8000, -10000, -2000)
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_partial_refunds_recover_only_once_and_keep_original_beneficiary_debt(test_client):
    from app.api.v1.module_growth.refund_service import reconcile_order_rewards
    from app.api.v1.module_payment.order.model import PaymentRefundModel

    async with async_db_session() as db:
        try:
            scope, users = await setup_scope(db)
            await published(db, scope, default_drafts()[2])
            draft = next(d for d in default_drafts() if d.key == "first_traffic")
            rule = await published(db, scope, draft, mode="auto", observe_days=0, budget_cash_fen=10000, actions=[{"recipient": "actor", "asset": "cash", "calculation": "paid_percent", "percent": 3}])
            order = await payment(db, scope, users[0].id)
            service = RewardService(db, scope)
            await service.paid_order(order)
            reward = await db.scalar(select(RewardModel).where(RewardModel.app_id == scope))
            assert reward.amount == 300
            await service.post(reward)
            account = await cash_account(db, scope, users[0].id)
            account.available = 50  # 250 cents were already spent/withdrawn.
            for index, expected_debt in [(1, 100), (2, 250)]:
                db.add(
                    PaymentRefundModel(
                        app_id=scope, user_id=users[0].id, order_id=order.id, refund_no=uuid4().hex, provider="alipay", amount_fen=5000, status="succeeded", refunded_at=datetime.now(UTC)
                    )
                )
                await db.flush()
                await reconcile_order_rewards(db, scope, order.id)
                await reconcile_order_rewards(db, scope, order.id)
                assert account.available == 0 and account.debt == expected_debt
                assert reward.reversed_amount == 150 * index
            assert reward.status == "reversed" and rule.used_cash_fen == 0
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_gift_month_opening_excludes_free_credits_and_preserves_expiry(test_client):
    from app.api.v1.module_billing.model import CreditGrantModel, CreditLedgerModel
    from app.api.v1.module_billing.service import CreditService
    from app.api.v1.module_growth.engine import BUSINESS_TZ
    from app.api.v1.module_growth.gift_service import GiftService
    from app.api.v1.module_growth.schema import TransferIn
    from app.utils.password_util import PwdUtil

    async with async_db_session() as db:
        try:
            scope, users = await setup_scope(db)
            users[0].password_hash = PwdUtil.hash_password("TestPass123!")
            await published(db, scope, default_drafts()[2], gift_enabled=True, gift_requires_subscription=False)
            account = await CreditService(db).account(scope, users[0].id, lock=True)
            account.available = 100000
            opening = datetime.now(UTC).astimezone(BUSINESS_TZ).replace(day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
            expiry = datetime.now(UTC) + timedelta(days=90)
            for price in [10000, 0]:
                order = await payment(db, scope, users[0].id, price)
                grant = CreditGrantModel(
                    app_id=scope,
                    user_id=users[0].id,
                    source_type="credit_pack_order",
                    source_id=order.id,
                    account_type="traffic_package",
                    amount=50000,
                    available=50000,
                    release_at=opening,
                    expires_at=expiry,
                    created_time=opening,
                    status="released",
                    pricing_snapshot={},
                    credits_per_cost_yuan=2500,
                )
                db.add(grant)
                await db.flush()
                db.add(
                    CreditLedgerModel(app_id=scope, user_id=users[0].id, grant_id=grant.id, entry_type="release", amount=50000, balance_after=100000, idempotency_key=uuid4().hex, created_time=opening)
                )
            await db.flush()
            gift_service = GiftService(db, scope)
            summary = await gift_service.summary(users[0].id)
            assert summary["giftable"] == 10000
            recipient = await ReferralService(db, scope).profile(users[1].id)
            data = TransferIn(recipient_code=recipient.invite_code, amount=10000, password="TestPass123!", idempotency_key=uuid4().hex)
            sent = await gift_service.transfer(users[0].id, data)
            assert (await gift_service.transfer(users[0].id, data)).id == sent.id
            assert account.available == 90000
            received = await db.scalar(select(CreditGrantModel).where(CreditGrantModel.app_id == scope, CreditGrantModel.user_id == users[1].id))
            assert received.source_type == "growth_gift" and received.available == 10000
            assert received.expires_at.replace(tzinfo=UTC) == expiry
            assert (await gift_service.summary(users[1].id))["giftable"] == 0
            with pytest.raises(CustomException):
                await gift_service.transfer(users[0].id, data.model_copy(update={"idempotency_key": uuid4().hex}))
        finally:
            await db.rollback()
