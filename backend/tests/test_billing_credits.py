import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.v1.module_billing.model import (
    AppCatalogPlanModel,
    AppPricingStrategyModel,
    CreditGrantModel,
    CreditLedgerModel,
    PricingStandardVersionModel,
    SubscriptionCycleModel,
    SubscriptionModel,
)
from app.api.v1.module_billing.schema import (
    CatalogPlanOutSchema,
    PricingStrategyCreateSchema,
    PricingVersionCreateSchema,
    PricingVersionUpdateSchema,
    SubscriptionStatusSchema,
)
from app.api.v1.module_billing.service import CatalogService, CreditService, PricingService, SubscriptionService
from app.api.v1.module_client.app.model import ClientAppModel
from app.api.v1.module_client.user.model import ClientUserModel
from app.api.v1.module_payment.channel.model import PaymentChannelModel
from app.api.v1.module_payment.channel.service import PaymentChannelService
from app.api.v1.module_payment.order import service as payment_service_module
from app.api.v1.module_payment.order.model import (
    PaymentAttemptModel,
    PaymentCallbackModel,
    PaymentOrderModel,
)
from app.api.v1.module_payment.order.providers import VerifiedPayment
from app.api.v1.module_payment.order.schema import PaymentOrderCreate
from app.api.v1.module_payment.order.service import PaymentOrderService
from app.core.base_schema import AuthSchema, CoreUserSchema
from app.core.database import async_db_session
from app.core.exceptions import CustomException
from app.utils.password_util import PwdUtil


def _pricing_version_payload(version: str, price: int):
    return {
        "version": version,
        "name": f"测试价格体系 {version}",
        "margin_baseline": 20,
        "description": "测试草稿",
        "templates": [
            {
                "code": "starter",
                "name": "入门套餐",
                "billing_period_days": 30,
                "one_time_price_fen": price,
                "recurring_price_fen": price,
                "total_credits": 1000,
                "release_plan": [
                    {"offset_day": 0, "amount": 500},
                    {"offset_day": 15, "amount": 500},
                ],
                "credit_valid_days": 30,
                "renewal_rule": "手动续费",
                "order": 1,
            }
        ],
    }


async def test_pricing_versions_remain_editable_without_replacing_catalog_templates(
    test_client: TestClient,
) -> None:
    del test_client
    async with async_db_session() as db:
        transaction = await db.begin()
        try:
            auth = AuthSchema(
                user=CoreUserSchema(id=1, username="admin", is_superuser=True),
                actor_type="staff",
                app_id=1,
            )
            service = PricingService(auth, db)
            version_code = f"test-{uuid.uuid4().hex[:8]}"
            created = await service.create_version(PricingVersionCreateSchema(**_pricing_version_payload(version_code, 1000)))
            updated = await service.update_version(
                created.id,
                PricingVersionUpdateSchema(**_pricing_version_payload(version_code, 1200)),
            )
            assert updated.template_count == 1
            templates = await service.templates(created.id)
            assert templates[0].one_time_price_fen == 1200

            await service.publish(created.id)
            plan = AppCatalogPlanModel(
                app_id=1,
                template_id=templates[0].id,
                pricing_version_id=created.id,
                code=f"test-{uuid.uuid4().hex[:8]}",
                name="已有刊例",
                one_time_price_fen=1200,
                recurring_price_fen=1200,
                total_credits=1000,
                release_plan=[{"offset_day": 0, "amount": 1000}],
            )
            db.add(plan)
            await db.flush()
            updated = await service.update_version(created.id, PricingVersionUpdateSchema(**_pricing_version_payload(version_code, 1300)))
            current = await service.templates(created.id)
            assert updated.status == "published"
            assert current[0].id == templates[0].id
            assert current[0].one_time_price_fen == 1300
            await db.refresh(plan)
            assert plan.template_id == current[0].id and plan.one_time_price_fen == 1200
            with pytest.raises(CustomException, match="已发布.*不能删除"):
                await service.delete_version(created.id)
            version = await db.get(PricingStandardVersionModel, created.id)
            version.status = "archived"
            await db.flush()
            with pytest.raises(CustomException, match="关联"):
                await service.delete_version(created.id)
        finally:
            await transaction.rollback()


@pytest.mark.parametrize("status", ["draft", "archived"])
async def test_delete_unpublished_pricing_version(test_client, status):
    del test_client
    async with async_db_session() as db:
        transaction = await db.begin()
        try:
            service = PricingService(AuthSchema(user=CoreUserSchema(id=1, username="admin", is_superuser=True), actor_type="staff", app_id=1), db)
            payload = _pricing_version_payload(f"test-{uuid.uuid4().hex[:8]}", 1000)
            created = await service.create_version(PricingVersionCreateSchema(**payload))
            version = await db.get(PricingStandardVersionModel, created.id)
            version.status = status
            await db.flush()
            await service.delete_version(created.id)
            assert created.id not in [v.id for v in await service.versions()]
            with pytest.raises(CustomException, match="不存在"):
                await service.templates(created.id)
            with pytest.raises(CustomException, match="不存在"):
                await service.publish(created.id)
            with pytest.raises(CustomException, match="不存在"):
                await service.update_version(created.id, PricingVersionUpdateSchema(**payload))
            with pytest.raises(CustomException, match="版本已存在"):
                await service.create_version(PricingVersionCreateSchema(**payload))
        finally:
            await transaction.rollback()


def test_pricing_delete_requires_authentication(test_client):
    assert test_client.delete("/operations/billing/pricing/versions/1").status_code == 401


async def test_republish_archived_version_switches_the_published_version(test_client):
    del test_client
    async with async_db_session() as db:
        transaction = await db.begin()
        try:
            service = PricingService(AuthSchema(user=CoreUserSchema(id=1, username="admin", is_superuser=True), actor_type="staff", app_id=1), db)
            first = await service.create_version(PricingVersionCreateSchema(**_pricing_version_payload(f"test-{uuid.uuid4().hex[:8]}", 1000)))
            second = await service.create_version(PricingVersionCreateSchema(**_pricing_version_payload(f"test-{uuid.uuid4().hex[:8]}", 2000)))
            await service.publish(first.id)
            await service.publish(second.id)
            assert next(v for v in await service.versions() if v.id == first.id).status == "archived"
            await service.publish(first.id)
            versions = await service.versions()
            assert [v.id for v in versions if v.status == "published"] == [first.id]
            assert next(v for v in versions if v.id == second.id).status == "archived"
        finally:
            await transaction.rollback()


async def test_payment_channel_requires_current_app_binding(test_client: TestClient, monkeypatch) -> None:
    del test_client
    async with async_db_session() as db:
        transaction = await db.begin()
        try:
            app = await db.scalar(select(ClientAppModel).where(ClientAppModel.code == "bid_agent"))
            channel = await db.scalar(select(PaymentChannelModel).where(PaymentChannelModel.provider == "wechat"))
            assert app is not None and channel is not None
            channel.enabled = True
            auth = AuthSchema(
                user=CoreUserSchema(id=1, username="admin", is_superuser=True),
                actor_type="staff",
                app_id=app.id,
            )
            service = PaymentChannelService(auth, db)
            monkeypatch.setattr(service, "_runtime_status", lambda *_args: ([], "1900****0001", True))

            before = await service.list()
            assert next(item for item in before if item.provider == "wechat").app_enabled is False
            bound = await service.bind_app("wechat", True)
            assert bound.app_enabled is True

            capabilities = await PaymentOrderService(auth, db).capabilities()
            assert next(item for item in capabilities if item.provider == "wechat").enabled is True
        finally:
            await transaction.rollback()


async def test_credit_reservation_settlement_and_stale_recovery(
    test_client: TestClient,
) -> None:
    del test_client  # Its session-scoped fixture initializes the isolated SQLite database.
    async with async_db_session() as db, db.begin():
        app = await db.scalar(select(ClientAppModel).where(ClientAppModel.code == "bid_agent"))
        assert app is not None
        user = ClientUserModel(
            app_id=app.id,
            username=f"credits_{uuid.uuid4().hex[:8]}",
            password_hash=PwdUtil.hash_password("Passw0rd!"),
            status="active",
        )
        db.add(user)
        await db.flush()
        service = CreditService(db)
        await service.adjust(app.id, user.id, 100, "测试积分", 1)

        await service.reserve(app.id, user.id, "request-settle", 60)
        account = await service.account(app.id, user.id)
        assert (account.available, account.reserved) == (40, 60)

        settled = await service.settle(app.id, user.id, "request-settle", 25)
        assert settled.status == "settled"
        assert (account.available, account.reserved, account.total_consumed) == (75, 0, 25)
        await service.settle(app.id, user.id, "request-settle", 25)
        ledger_count = await db.scalar(select(func.count()).select_from(CreditLedgerModel).where(CreditLedgerModel.idempotency_key == f"settle:{app.id}:request-settle"))
        assert ledger_count == 1

        with pytest.raises(CustomException):
            await service.reserve(app.id, user.id, "request-settle", 10)
        with pytest.raises(CustomException):
            await service.settle(app.id, user.id, "request-settle", -1)

        stale = await service.reserve(app.id, user.id, "request-stale", 50)
        stale.created_time = datetime.now(UTC) - timedelta(minutes=20)
        await db.flush()
        assert await service.release_due(app_id=app.id, user_id=user.id) == 0
        assert stale.status == "reserved"
        stale.created_time = datetime.now(UTC) - timedelta(minutes=36)
        await db.flush()
        assert await service.release_due(app_id=app.id, user_id=user.id) == 1
        assert stale.status == "cancelled"
        assert (account.available, account.reserved) == (75, 0)


async def test_zero_price_order_is_idempotent_and_releases_scheduled_credits(
    test_client: TestClient,
) -> None:
    del test_client
    async with async_db_session() as db, db.begin():
        app = await db.scalar(select(ClientAppModel).where(ClientAppModel.code == "bid_agent"))
        version = await db.scalar(select(PricingStandardVersionModel).where(PricingStandardVersionModel.status == "published"))
        assert app is not None and version is not None
        user = ClientUserModel(
            app_id=app.id,
            username=f"order_{uuid.uuid4().hex[:8]}",
            password_hash=PwdUtil.hash_password("Passw0rd!"),
            status="active",
        )
        db.add(user)
        await db.flush()
        plan = AppCatalogPlanModel(
            app_id=app.id,
            pricing_version_id=version.id,
            code=f"free_{uuid.uuid4().hex[:8]}",
            name="零元体验测试",
            one_time_price_fen=0,
            recurring_price_fen=100,
            benefit_period_days=30,
            total_credits=100,
            release_plan=[{"offset_day": 0, "amount": 20}, {"offset_day": 7, "amount": 80}],
            credit_valid_days=30,
            benefits=[],
            status="on_sale",
        )
        db.add(plan)
        await db.flush()
        auth = AuthSchema(
            user=CoreUserSchema(id=user.id, username=user.username),
            actor_type="client",
            app_id=app.id,
        )
        service = PaymentOrderService(auth, db)
        request = PaymentOrderCreate(
            catalog_plan_id=plan.id,
            provider="wechat",
            idempotency_key=f"free-order-{uuid.uuid4().hex}",
        )

        first = await service.create(request)
        second = await service.create(request)
        account = await CreditService(db).account(app.id, user.id)
        cycles = await db.scalar(select(func.count()).select_from(SubscriptionCycleModel).where(SubscriptionCycleModel.user_id == user.id))
        grants = await db.scalar(select(func.count()).select_from(CreditGrantModel).where(CreditGrantModel.user_id == user.id))

        assert first.id == second.id
        assert first.status == "paid"
        assert cycles == 1 and grants == 2
        assert (account.available, account.pending) == (20, 80)
        subscription = await SubscriptionService(db).current_for_client(app.id, user.id)
        ledger = await SubscriptionService(db).ledger_for_client(app.id, user.id)
        assert subscription is not None and subscription.plan_name == plan.name
        assert ledger and ledger[0].entry_type == "subscription_release"
        subscription_id = await db.scalar(select(SubscriptionCycleModel.subscription_id).where(SubscriptionCycleModel.user_id == user.id))
        assert subscription_id is not None
        corrected = await SubscriptionService(db).set_status(
            app.id,
            subscription_id,
            SubscriptionStatusSchema(status="cancelled", reason="人工核验测试"),
        )
        assert corrected.status == "cancelled"

        expired_at = datetime.now(UTC) - timedelta(minutes=1)
        subscription_row = await db.get(SubscriptionModel, subscription_id)
        cycle_row = await db.scalar(select(SubscriptionCycleModel).where(SubscriptionCycleModel.subscription_id == subscription_id))
        assert subscription_row is not None and cycle_row is not None
        subscription_row.status = "active"
        subscription_row.current_period_end = expired_at
        cycle_row.status = "active"
        cycle_row.ends_at = expired_at
        cycle_id = cycle_row.id
        refreshed = await SubscriptionService(db).current_for_client(app.id, user.id)
        assert refreshed is not None and refreshed.status == "expired"
        cycle_status = await db.scalar(select(SubscriptionCycleModel.status).where(SubscriptionCycleModel.id == cycle_id))
        assert cycle_status == "expired"


async def test_pending_order_uses_provider_query_to_reconcile_missed_callback(
    test_client: TestClient,
    monkeypatch,
) -> None:
    del test_client
    async with async_db_session() as db, db.begin():
        app = await db.scalar(select(ClientAppModel).where(ClientAppModel.code == "bid_agent"))
        version = await db.scalar(select(PricingStandardVersionModel).where(PricingStandardVersionModel.status == "published"))
        assert app is not None and version is not None
        user = ClientUserModel(
            app_id=app.id,
            username=f"reconcile_{uuid.uuid4().hex[:8]}",
            password_hash=PwdUtil.hash_password("Passw0rd!"),
            status="active",
        )
        db.add(user)
        await db.flush()
        plan = AppCatalogPlanModel(
            app_id=app.id,
            pricing_version_id=version.id,
            code=f"reconcile_{uuid.uuid4().hex[:8]}",
            name="漏回调补偿测试",
            one_time_price_fen=1234,
            recurring_price_fen=1234,
            benefit_period_days=30,
            total_credits=100,
            release_plan=[{"offset_day": 0, "amount": 100}],
            credit_valid_days=30,
            benefits=[],
            status="on_sale",
        )
        db.add(plan)
        await db.flush()
        now = datetime.now(UTC)
        order = PaymentOrderModel(
            app_id=app.id,
            user_id=user.id,
            order_no=f"YXRECONCILE{uuid.uuid4().hex[:16].upper()}",
            idempotency_key=f"reconcile-{uuid.uuid4().hex}",
            catalog_plan_id=plan.id,
            purchase_type="first",
            provider="wechat",
            amount_fen=1234,
            plan_snapshot={
                "id": plan.id,
                "code": plan.code,
                "name": plan.name,
                "benefit_period_days": plan.benefit_period_days,
                "total_credits": plan.total_credits,
                "release_plan": plan.release_plan,
                "credit_valid_days": plan.credit_valid_days,
                "benefits": plan.benefits,
                "base_price_fen": 1234,
            },
            status="pending",
            pay_url="weixin://wxpay/test",
            expires_at=now + timedelta(minutes=10),
            updated_time=now - timedelta(seconds=20),
            auto_renew_requested=False,
        )
        db.add(order)
        await db.flush()
        query_count = 0

        async def fake_query(order_no: str, *, include_closed: bool = False) -> VerifiedPayment:
            nonlocal query_count
            assert include_closed
            query_count += 1
            return VerifiedPayment(
                callback_id="query:wx-trade-reconcile",
                order_no=order_no,
                provider_trade_no="wx-trade-reconcile",
                amount_fen=1234,
                paid_at=now,
                payload_digest="a" * 64,
            )

        monkeypatch.setattr(payment_service_module, "query_wechat_order", fake_query)
        auth = AuthSchema(
            user=CoreUserSchema(id=user.id, username=user.username),
            actor_type="client",
            app_id=app.id,
        )
        service = PaymentOrderService(auth, db)

        reconciled = await service.get(order.order_no)
        repeated = await service.get(order.order_no)
        attempts = await db.scalar(select(func.count()).select_from(PaymentAttemptModel).where(PaymentAttemptModel.order_id == order.id))
        callbacks = await db.scalar(select(func.count()).select_from(PaymentCallbackModel).where(PaymentCallbackModel.order_no == order.order_no))
        cycles = await db.scalar(select(func.count()).select_from(SubscriptionCycleModel).where(SubscriptionCycleModel.user_id == user.id))
        account = await CreditService(db).account(app.id, user.id)

        assert reconciled.status == repeated.status == "paid"
        assert query_count == 1
        assert attempts == callbacks == cycles == 1
        assert account.available == 100


async def test_publishing_strategy_deactivates_previous_version(
    test_client: TestClient,
) -> None:
    del test_client
    async with async_db_session() as db, db.begin():
        app = await db.scalar(select(ClientAppModel).where(ClientAppModel.code == "bid_agent"))
        version = await db.scalar(select(PricingStandardVersionModel).where(PricingStandardVersionModel.status == "published"))
        assert app is not None and version is not None
        operator = CoreUserSchema(id=1, username="admin")
        auth = AuthSchema(user=operator, actor_type="staff", app_id=app.id)
        plan = AppCatalogPlanModel(
            app_id=app.id,
            pricing_version_id=version.id,
            code=f"strategy_{uuid.uuid4().hex[:8]}",
            name="定价策略测试",
            one_time_price_fen=1000,
            recurring_price_fen=800,
            benefit_period_days=30,
            total_credits=100,
            release_plan=[{"offset_day": 0, "amount": 100}],
            credit_valid_days=30,
            benefits=[],
            status="on_sale",
        )
        db.add(plan)
        await db.flush()
        service = CatalogService(auth, db)
        starts_at = datetime.now(UTC) - timedelta(minutes=1)
        ends_at = starts_at + timedelta(days=1)
        specific = await service.create_strategy(
            PricingStrategyCreateSchema(
                catalog_plan_id=plan.id,
                name="首购价",
                purchase_type="first",
                fixed_price_fen=700,
                starts_at=starts_at,
                ends_at=ends_at,
                status="active",
            )
        )
        broad = await service.create_strategy(
            PricingStrategyCreateSchema(
                catalog_plan_id=plan.id,
                name="全场价",
                purchase_type="all",
                fixed_price_fen=900,
                starts_at=starts_at,
                ends_at=ends_at,
                status="active",
            )
        )
        assert specific.fixed_price_fen == 700
        assert broad.status == "active"
        assert await db.scalar(select(AppPricingStrategyModel.status).where(AppPricingStrategyModel.id == specific.id)) == "inactive"
        assert await service.effective_price(CatalogPlanOutSchema.model_validate(plan), "first") == 900


async def test_strategy_cost_formula_matches_business_acceptance_example(
    test_client: TestClient,
) -> None:
    del test_client
    async with async_db_session() as db, db.begin():
        app = await db.scalar(select(ClientAppModel).where(ClientAppModel.code == "bid_agent"))
        version = await db.scalar(select(PricingStandardVersionModel).where(PricingStandardVersionModel.status == "published"))
        assert app is not None and version is not None
        auth = AuthSchema(user=CoreUserSchema(id=1, username="admin"), actor_type="staff", app_id=app.id)
        plan = AppCatalogPlanModel(
            app_id=app.id,
            pricing_version_id=version.id,
            code=f"formula_{uuid.uuid4().hex[:8]}",
            name="公式验收套餐",
            one_time_price_fen=1000,
            recurring_price_fen=1000,
            benefit_period_days=30,
            total_credits=10_000,
            release_plan=[{"offset_day": 0, "amount": 10_000}],
            credit_valid_days=30,
            benefits=[],
            status="on_sale",
        )
        db.add(plan)
        await db.flush()
        now = datetime.now(UTC)
        strategy = await CatalogService(auth, db).create_strategy(
            PricingStrategyCreateSchema(
                catalog_plan_id=plan.id,
                name="业务公式验收",
                starts_at=now,
                ends_at=now + timedelta(days=30),
                items=[
                    {
                        "catalog_plan_id": plan.id,
                        "purchase_type": "all",
                        "discount_rate": 1,
                        "margin_rate": 60,
                    }
                ],
            )
        )
        assert len(strategy.items) == 2
        for item in strategy.items:
            assert item.execution_price_fen == 1000
            assert item.allowed_cost_yuan == 4
            assert item.credits_per_cost_yuan == 2500
            assert 0.4 * 10 * item.credits_per_cost_yuan == 10_000
