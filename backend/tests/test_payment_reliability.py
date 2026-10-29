"""支付下单结果、自动补查和交易关联的回归测试。"""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.api.v1.module_billing.model import AppCatalogPlanModel, CreditGrantModel, CreditLedgerModel, PricingStandardVersionModel
from app.api.v1.module_billing.service import CreditService
from app.api.v1.module_client.app.model import ClientAppModel
from app.api.v1.module_client.user.model import ClientUserModel
from app.api.v1.module_finance import repairs
from app.api.v1.module_finance.model import FinanceBillEntryModel, FinanceBillModel
from app.api.v1.module_finance.repairs import repair_due_differences
from app.api.v1.module_payment.channel.model import AppPaymentChannelModel, PaymentChannelModel
from app.api.v1.module_payment.channel.service import PaymentChannelService
from app.api.v1.module_payment.order import recovery
from app.api.v1.module_payment.order import service as payment_service
from app.api.v1.module_payment.order.controller import create_payment_order
from app.api.v1.module_payment.order.model import PaymentAttemptModel, PaymentCallbackModel, PaymentOrderModel
from app.api.v1.module_payment.order.providers import VerifiedPayment
from app.api.v1.module_payment.order.schema import PaymentOrderCreate
from app.api.v1.module_payment.order.service import PaymentCallbackService, PaymentOrderService
from app.core.base_schema import AuthSchema, CoreUserSchema
from app.core.database import async_db_session
from app.core.exceptions import CustomException


async def _scope(db):
    app = await db.scalar(select(ClientAppModel).where(ClientAppModel.code == "bid_agent"))
    version = await db.scalar(select(PricingStandardVersionModel).where(PricingStandardVersionModel.status == "published"))
    user = ClientUserModel(app_id=app.id, username=f"pay_{uuid4().hex[:8]}", password_hash="test-only", status="active")
    db.add(user)
    await db.flush()
    plan = AppCatalogPlanModel(
        app_id=app.id,
        pricing_version_id=version.id,
        code=f"pay_{uuid4().hex[:8]}",
        name="支付可靠性测试套餐",
        one_time_price_fen=1200,
        recurring_price_fen=1200,
        benefit_period_days=30,
        total_credits=100,
        release_plan=[{"offset_day": 0, "amount": 100}],
        credit_valid_days=30,
        benefits=[],
        status="on_sale",
    )
    db.add(plan)
    await db.flush()
    auth = AuthSchema(user=CoreUserSchema(id=user.id, username=user.username), actor_type="client", app_id=app.id)
    return app, user, plan, auth


def _snapshot(plan):
    return {
        "id": plan.id,
        "code": plan.code,
        "name": plan.name,
        "plan_type": "credit_pack",
        "benefit_period_days": 30,
        "total_credits": 100,
        "release_plan": [{"offset_day": 0, "amount": 100}],
        "credit_valid_days": 30,
        "benefits": [],
        "base_price_fen": 1200,
    }


def _verified(order_no, trade_no="wx-trade-123"):
    return VerifiedPayment(
        callback_id=f"query:{trade_no}",
        order_no=order_no,
        provider_trade_no=trade_no,
        amount_fen=1200,
        paid_at=datetime.now(UTC),
        payload_digest="a" * 64,
    )


async def test_checkout_failure_is_not_success_and_idempotency_parameters_are_bound(test_client, monkeypatch):
    del test_client
    async with async_db_session() as db, db.begin():
        app, user, plan, auth = await _scope(db)
        channel = await db.scalar(select(PaymentChannelModel).where(PaymentChannelModel.provider == "wechat"))
        original_enabled, original_mode = channel.enabled, channel.mode
        channel.enabled, channel.mode = True, "production"
        binding = await db.scalar(select(AppPaymentChannelModel).where(AppPaymentChannelModel.app_id == app.id, AppPaymentChannelModel.channel_id == channel.id))
        original_binding_enabled = binding.enabled if binding else None
        if binding:
            binding.enabled = True
        else:
            binding = AppPaymentChannelModel(app_id=app.id, channel_id=channel.id, enabled=True)
            db.add(binding)
        await db.flush()
        monkeypatch.setattr(PaymentChannelService, "_to_schema", lambda *_: SimpleNamespace(configured=True))

        async def unknown(*_args):
            raise TimeoutError("渠道请求超时")

        monkeypatch.setattr(payment_service, "create_wechat_native_order", unknown)
        request = PaymentOrderCreate(catalog_plan_id=plan.id, provider="wechat", idempotency_key=uuid4().hex)
        response = await create_payment_order(auth, db, request)
        body = json.loads(response.body)
        assert response.status_code == 202 and body["success"] is False
        assert body["data"]["status"] == "confirming" and body["data"]["pay_url"] is None
        assert (await PaymentOrderService(auth, db).create(request)).order_no == body["data"]["order_no"]
        with pytest.raises(CustomException, match="不同的套餐或支付方式"):
            await PaymentOrderService(auth, db).create(request.model_copy(update={"provider": "alipay"}))

        async def rejected(*_args):
            raise CustomException(msg="渠道明确拒绝", status_code=409)

        monkeypatch.setattr(payment_service, "create_wechat_native_order", rejected)
        failed = await create_payment_order(auth, db, request.model_copy(update={"idempotency_key": uuid4().hex}))
        assert failed.status_code == 502
        assert json.loads(failed.body)["data"]["status"] == "failed"
        assert json.loads(failed.body)["success"] is False
        assert await db.scalar(select(func.count()).select_from(PaymentOrderModel).where(PaymentOrderModel.app_id == app.id, PaymentOrderModel.user_id == user.id)) == 2
        channel.enabled, channel.mode = original_enabled, original_mode
        if original_binding_enabled is None:
            await db.delete(binding)
        else:
            binding.enabled = original_binding_enabled


async def test_recovery_repairs_missed_callback_and_bill_difference(test_client, monkeypatch):
    del test_client
    async with async_db_session() as db, db.begin():
        app, user, plan, _ = await _scope(db)
        now = datetime.now(UTC)
        order = PaymentOrderModel(
            app_id=app.id,
            user_id=user.id,
            order_no=f"YXREC{uuid4().hex[:20].upper()}",
            idempotency_key=uuid4().hex,
            catalog_plan_id=plan.id,
            purchase_type="first",
            provider="wechat",
            amount_fen=1200,
            plan_snapshot=_snapshot(plan),
            status="pending",
            expires_at=now - timedelta(minutes=1),
            next_query_at=now - timedelta(seconds=1),
            auto_renew_requested=False,
        )
        db.add(order)
        await db.flush()
        bill = FinanceBillModel(app_id=app.id, provider="wechat", bill_date=(now - timedelta(days=120)).date(), status="completed", merchant_identity="test", requested_by=1)
        db.add(bill)
        await db.flush()
        entry = FinanceBillEntryModel(
            app_id=app.id,
            bill_id=bill.id,
            entry_key=uuid4().hex,
            order_id=order.id,
            order_no=order.order_no,
            provider_trade_no="wx-trade-recovery",
            entry_type="payment",
            channel_amount_fen=1200,
            system_amount_fen=0,
            match_status="payment_missing",
        )
        db.add(entry)
        await db.flush()
        app_id, user_id, order_id, entry_id, bill_id = app.id, user.id, order.id, entry.id, bill.id

    async def paid_query(order_no, **_kwargs):
        return _verified(order_no, "wx-trade-recovery") if order_no == order.order_no else None

    monkeypatch.setattr(recovery, "query_wechat_order", paid_query)
    assert await recovery.recover_due_orders(app_id) >= 1
    await repair_due_differences(app_id)
    async with async_db_session() as db:
        order = await db.get(PaymentOrderModel, order_id)
        entry = await db.get(FinanceBillEntryModel, entry_id)
        bill = await db.get(FinanceBillModel, bill_id)
        assert order.status == "paid" and order.provider_trade_no == "wx-trade-recovery"
        assert order.next_query_at is None
        assert entry.match_status == "matched" and entry.system_amount_fen == 1200
        assert bill.summary["matched"] == 1 and bill.summary["differences"] == 0
        assert await db.scalar(select(func.count()).select_from(CreditGrantModel).where(CreditGrantModel.user_id == user_id, CreditGrantModel.source_id == order_id)) == 1
        assert await db.scalar(select(func.count()).select_from(PaymentAttemptModel).where(PaymentAttemptModel.order_id == order_id, PaymentAttemptModel.status == "paid")) == 1


async def test_one_channel_trade_cannot_credit_two_orders(test_client):
    del test_client
    async with async_db_session() as db, db.begin():
        app, user, plan, _ = await _scope(db)
        first = PaymentOrderModel(
            app_id=app.id,
            user_id=user.id,
            order_no=uuid4().hex,
            idempotency_key=uuid4().hex,
            catalog_plan_id=plan.id,
            purchase_type="first",
            provider="wechat",
            amount_fen=1200,
            plan_snapshot=_snapshot(plan),
            status="paid",
            provider_trade_no="one-trade",
            paid_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
            auto_renew_requested=False,
        )
        second = PaymentOrderModel(
            app_id=app.id,
            user_id=user.id,
            order_no=uuid4().hex,
            idempotency_key=uuid4().hex,
            catalog_plan_id=plan.id,
            purchase_type="first",
            provider="wechat",
            amount_fen=1200,
            plan_snapshot=_snapshot(plan),
            status="paid",
            paid_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
            auto_renew_requested=False,
        )
        db.add_all((first, second))
        await db.flush()
        with pytest.raises(CustomException, match="已关联其他订单"):
            await PaymentCallbackService(db).process("wechat", _verified(second.order_no, "one-trade"))
        assert second.provider_trade_no is None


async def test_replayed_callback_id_cannot_change_transaction(test_client):
    del test_client
    callback_id = uuid4().hex
    async with async_db_session() as db, db.begin():
        db.add(
            PaymentCallbackModel(
                provider="wechat",
                callback_id=callback_id,
                order_no="original-order",
                provider_trade_no="original-trade",
                amount_fen=1200,
                status="processed",
            )
        )
        await db.flush()
        paid = VerifiedPayment(
            callback_id=callback_id,
            order_no="another-order",
            provider_trade_no="another-trade",
            amount_fen=1200,
            paid_at=datetime.now(UTC),
            payload_digest="a" * 64,
        )
        with pytest.raises(CustomException, match="通知编号关联了不同交易"):
            await PaymentCallbackService(db).process("wechat", paid)


async def test_paid_order_missing_entitlement_is_repaired_once(test_client, monkeypatch):
    del test_client
    async with async_db_session() as db, db.begin():
        app, user, plan, _ = await _scope(db)
        order = PaymentOrderModel(
            app_id=app.id,
            user_id=user.id,
            order_no=uuid4().hex,
            idempotency_key=uuid4().hex,
            catalog_plan_id=plan.id,
            purchase_type="first",
            provider="wechat",
            amount_fen=1200,
            plan_snapshot=_snapshot(plan),
            status="paid",
            provider_trade_no=f"wx-{uuid4().hex}",
            paid_at=datetime.now(UTC) - timedelta(minutes=20),
            expires_at=datetime.now(UTC) - timedelta(minutes=5),
            auto_renew_requested=False,
        )
        db.add(order)
        await db.flush()
        app_id, order_id, user_id = app.id, order.id, user.id

    async def signed_query(_provider, order_no, _sandbox):
        return _verified(order_no, order.provider_trade_no)

    monkeypatch.setattr(repairs, "_query", signed_query)
    await repairs.repair_missing_entitlement(app_id, order_id)
    await repairs.repair_missing_entitlement(app_id, order_id)
    async with async_db_session() as db:
        assert await db.scalar(select(func.count()).select_from(CreditGrantModel).where(CreditGrantModel.user_id == user_id, CreditGrantModel.source_id == order_id)) == 1


async def test_manual_credit_adjustment_replay_is_not_applied_twice(test_client):
    del test_client
    async with async_db_session() as db, db.begin():
        app, user, _, _ = await _scope(db)
        credit = CreditService(db)
        first = await credit.adjust(app.id, user.id, 100, "运营补发", 1, 30, "manual-retry-123")
        replay = await credit.adjust(app.id, user.id, 100, "运营补发", 1, 30, "manual-retry-123")
        assert first.available == replay.available == 100
        assert await db.scalar(select(func.count()).select_from(CreditLedgerModel).where(CreditLedgerModel.user_id == user.id, CreditLedgerModel.entry_type == "manual_grant")) == 1
        with pytest.raises(CustomException, match="不同的积分调整"):
            await credit.adjust(app.id, user.id, 200, "运营补发", 1, 30, "manual-retry-123")
