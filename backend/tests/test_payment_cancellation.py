"""订单取消必须由渠道确认，不能把未知付款结果当作关闭。"""

import importlib
import json
from datetime import UTC, datetime, timedelta
from io import StringIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, func, inspect, select

from app.api.v1.module_billing.model import AppCatalogPlanModel, CreditGrantModel, PricingStandardVersionModel
from app.api.v1.module_client.app.model import ClientAppModel
from app.api.v1.module_client.user.model import ClientUserModel
from app.api.v1.module_payment.order import cancellation, recovery
from app.api.v1.module_payment.order.controller import cancel_payment_order, cancellation_response
from app.api.v1.module_payment.order.model import PaymentAttemptModel, PaymentOrderModel
from app.api.v1.module_payment.order.providers import VerifiedAbsentOrder, VerifiedClosedOrder, VerifiedPayment
from app.api.v1.module_payment.order.service import PaymentCallbackService, PaymentOrderService
from app.core.base_model import MappedBase
from app.core.base_schema import AuthSchema, CoreUserSchema
from app.core.database import async_db_session
from app.core.exceptions import CustomException


@pytest.fixture
async def purchase(test_client, monkeypatch):
    del test_client
    async with async_db_session() as db:
        app = await db.scalar(select(ClientAppModel).where(ClientAppModel.code == "bid_agent"))
        version = await db.scalar(select(PricingStandardVersionModel).where(PricingStandardVersionModel.status == "published"))
        user = ClientUserModel(app_id=app.id, username=f"cancel_{uuid4().hex[:8]}", password_hash="test-only", status="active", active_billing_mode="credits")
        plan = AppCatalogPlanModel(
            app_id=app.id,
            pricing_version_id=version.id,
            code=uuid4().hex,
            name="取消订单测试",
            plan_type="credit_pack",
            one_time_price_fen=1200,
            recurring_price_fen=1200,
            benefit_period_days=30,
            total_credits=100,
            release_plan=[{"offset_day": 0, "amount": 100}],
            credit_valid_days=30,
            benefits=[],
            status="on_sale",
        )
        db.add_all((user, plan))
        await db.flush()
        auth = AuthSchema(user=CoreUserSchema(id=user.id, username=user.username), actor_type="client", app_id=app.id)
        order = PaymentOrderModel(
            app_id=app.id,
            user_id=user.id,
            order_no=f"YXCANCEL{uuid4().hex[:20].upper()}",
            idempotency_key=uuid4().hex,
            catalog_plan_id=plan.id,
            purchase_type="first",
            provider="wechat",
            amount_fen=1200,
            status="pending",
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
            next_query_at=datetime.now(UTC) - timedelta(seconds=1),
            pay_url="weixin://test",
            auto_renew_requested=False,
            plan_snapshot={
                "id": plan.id,
                "code": plan.code,
                "name": plan.name,
                "plan_type": "credit_pack",
                "entitlement_kind": "credits",
                "benefit_period_days": 30,
                "total_credits": 100,
                "release_plan": [{"offset_day": 0, "amount": 100}],
                "credit_valid_days": 30,
                "benefits": [],
            },
        )
        db.add(order)
        await db.flush()
        query = AsyncMock(return_value=None)
        monkeypatch.setattr(PaymentOrderService, "query_provider", query)
        close = AsyncMock(return_value=None)
        monkeypatch.setattr(cancellation, "close_wechat_order", close)
        monkeypatch.setattr(cancellation, "close_alipay_order", close)
        try:
            yield SimpleNamespace(db=db, app=app, user=user, plan=plan, auth=auth, order=order, query=query, close=close)
        finally:
            await db.rollback()


def payment(order):
    trade = f"wx-{uuid4().hex}"
    return VerifiedPayment(f"query:{trade}", order.order_no, trade, 1200, datetime.now(UTC), "a" * 64)


def test_cancel_route_requires_client_authentication(test_client):
    response = test_client.post("/client/payment/orders/YXCANCEL001/cancel")
    assert response.status_code == 401


def test_operator_close_route_requires_staff_authentication(test_client):
    response = test_client.post("/finance/orders/1/close", json={"reason": "运营关单"})
    assert response.status_code == 401


@pytest.mark.parametrize("provider", ["wechat", "alipay"])
async def test_cancel_is_idempotent_and_preserves_original_rights(purchase, provider):
    p = purchase
    p.order.provider = provider
    p.order.mode_switch = {"status": "pending_payment", "source_mode": "credits", "target_mode": "duration"}
    await p.db.flush()
    service = PaymentOrderService(p.auth, p.db)
    first = await service.cancel(p.order.order_no)
    second = await service.cancel(p.order.order_no)
    assert first.status == second.status == "closed" and first.closed_at.replace(tzinfo=UTC) == second.closed_at.replace(tzinfo=UTC)
    assert first.cancel_requested_at and first.pay_url is None and p.order.next_query_at is None
    assert p.order.mode_switch["status"] == "cancelled" and p.user.active_billing_mode == "credits"
    assert p.close.await_count == 1
    assert await p.db.scalar(select(func.count()).select_from(CreditGrantModel).where(CreditGrantModel.source_id == p.order.id)) == 0


async def test_cannot_cancel_another_users_or_applications_order(purchase):
    p = purchase
    other = p.auth.model_copy(update={"user": CoreUserSchema(id=p.user.id + 1000, username="other")})
    with pytest.raises(CustomException, match="订单不存在"):
        await PaymentOrderService(other, p.db).cancel(p.order.order_no)
    app = ClientAppModel(code=uuid4().hex, name="隔离测试")
    p.db.add(app)
    await p.db.flush()
    with pytest.raises(CustomException, match="订单不存在"):
        await PaymentOrderService(p.auth.model_copy(update={"app_id": app.id}), p.db).cancel(p.order.order_no)
    assert p.close.await_count == p.query.await_count == 0 and p.order.status == "pending"


async def test_paid_order_is_not_closed_or_refunded(purchase):
    p = purchase
    p.order.status, p.order.paid_at = "paid", datetime.now(UTC)
    await p.db.flush()
    result = await PaymentOrderService(p.auth, p.db).cancel(p.order.order_no)
    response = cancellation_response(result)
    assert response.status_code == 409 and json.loads(response.body)["data"]["status"] == "paid"
    assert p.close.await_count == p.query.await_count == 0 and p.order.cancel_requested_at is None


async def test_close_timeout_retains_cancellation_intent_for_background_retry(purchase, monkeypatch):
    p = purchase
    p.close.side_effect = TimeoutError("unknown")
    result = await PaymentOrderService(p.auth, p.db).cancel(p.order.order_no)
    assert result.status == "confirming" and result.cancel_requested_at and result.closed_at is None
    assert cancellation_response(result).status_code == 202 and p.order.next_query_at
    await p.db.commit()
    p.close.side_effect = None
    p.order.next_query_at = datetime.now(UTC) - timedelta(seconds=1)
    await p.db.commit()
    monkeypatch.setattr(recovery, "query_wechat_order", AsyncMock(return_value=None))
    await recovery.recover_order(p.app.id, p.order.id)
    await p.db.refresh(p.order)
    assert p.order.status == "closed" and p.order.next_query_at is None
    assert p.order.expires_at.replace(tzinfo=UTC) > datetime.now(UTC)


async def test_payment_winning_close_race_is_settled_once(purchase):
    p = purchase
    receipt = payment(p.order)
    p.query.side_effect = [None, receipt]
    p.close.side_effect = TimeoutError("payment won race")
    result = await PaymentOrderService(p.auth, p.db).cancel(p.order.order_no)
    assert result.status == "paid" and result.closed_at is None and cancellation_response(result).status_code == 409
    await PaymentCallbackService(p.db).process("wechat", receipt)
    assert await p.db.scalar(select(func.count()).select_from(CreditGrantModel).where(CreditGrantModel.source_id == p.order.id)) == 1


async def test_expired_order_is_closed_only_after_channel_confirmation(purchase):
    p = purchase
    p.order.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await p.db.flush()
    result = await PaymentOrderService(p.auth, p.db).get(p.order.order_no)
    assert result.status == "closed" and result.closed_at and p.close.await_count == 1


async def test_verified_channel_closure_does_not_require_another_close_request(purchase):
    p = purchase
    p.query.return_value = VerifiedClosedOrder(p.order.order_no, p.order.amount_fen)
    result = await PaymentOrderService(p.auth, p.db).get(p.order.order_no)
    assert result.status == "closed" and result.closed_at and p.close.await_count == 0


async def test_channel_mismatch_or_paid_then_refunded_is_not_unpaid_cancellation(purchase):
    p = purchase
    for result in (VerifiedClosedOrder(p.order.order_no, 999), VerifiedClosedOrder(p.order.order_no, 1200, previously_paid=True)):
        p.query.return_value = result
        with pytest.raises(CustomException):
            await PaymentOrderService(p.auth, p.db).cancel(p.order.order_no)
        assert p.order.status == "pending" and p.close.await_count == 0


async def test_late_signed_payment_after_closure_is_not_lost(purchase):
    p = purchase
    await PaymentOrderService(p.auth, p.db).cancel(p.order.order_no)
    await PaymentCallbackService(p.db).process("wechat", payment(p.order))
    assert p.order.status == "paid" and p.order.closed_at is None
    assert await p.db.scalar(select(func.count()).select_from(CreditGrantModel).where(CreditGrantModel.source_id == p.order.id)) == 1


async def test_client_controller_returns_complete_order_on_confirmed_cancel(purchase):
    p = purchase
    response = await cancel_payment_order(p.auth, p.db, p.order.order_no)
    body = json.loads(response.body)
    assert response.status_code == 200 and body["success"]
    assert body["data"]["status"] == "closed" and body["data"]["order_no"] == p.order.order_no
    assert body["data"]["closed_at"] and body["data"]["cancel_requested_at"]


async def test_cancelled_mode_switch_late_payment_requires_finance_review(purchase):
    p = purchase
    p.order.mode_switch = {"status": "pending_payment", "source_mode": "credits", "target_mode": "duration"}
    await p.db.flush()
    await PaymentOrderService(p.auth, p.db).cancel(p.order.order_no)
    await PaymentCallbackService(p.db).process("wechat", payment(p.order))
    assert p.order.status == "paid" and p.order.mode_switch["status"] == "requires_confirmation"
    assert p.user.active_billing_mode == "credits"
    assert await p.db.scalar(select(func.count()).select_from(CreditGrantModel).where(CreditGrantModel.source_id == p.order.id)) == 0


async def test_signed_recovery_payment_beats_concurrent_local_closure(purchase, monkeypatch):
    p = purchase
    receipt = payment(p.order)
    order_id, app_id = p.order.id, p.app.id
    await p.db.commit()

    async def query_with_race(_order_no, **_kwargs):
        async with async_db_session() as db, db.begin():
            result = await PaymentOrderService(p.auth, db).cancel(receipt.order_no)
            assert result.status == "closed"
        return receipt

    monkeypatch.setattr(recovery, "query_wechat_order", query_with_race)
    await recovery.recover_order(app_id, order_id)
    await p.db.refresh(p.order)
    assert p.order.status == "paid" and p.order.closed_at is None
    assert await p.db.scalar(select(func.count()).select_from(CreditGrantModel).where(CreditGrantModel.source_id == order_id)) == 1


def test_cancellation_migration_roundtrip_and_postgres_ddl(test_client):
    del test_client
    migration = importlib.import_module("app.alembic.versions.20261014_payment_cancel")
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        MappedBase.metadata.create_all(connection)
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            assert "cancel_requested_at" not in {column["name"] for column in inspect(connection).get_columns("payment_order")}
            migration.upgrade()
        assert "cancel_requested_at" in {column["name"] for column in inspect(connection).get_columns("payment_order")}
    engine.dispose()
    output = StringIO()
    with Operations.context(MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})):
        migration.upgrade()
    assert "TIMESTAMP WITH TIME ZONE" in output.getvalue() and "ADD COLUMN cancel_requested_at" in output.getvalue()


async def test_delete_unpaid_cleans_associations_and_stops_recovery(purchase):
    from app.api.v1.module_agreement.model import AgreementAcceptanceModel
    from app.api.v1.module_finance.deletion import delete_unpaid_order
    from app.api.v1.module_finance.model import FinanceAuditModel
    from app.api.v1.module_finance.orders import list_orders
    from app.api.v1.module_finance.schema import FinanceQuery

    p = purchase
    p.db.add(PaymentAttemptModel(app_id=p.app.id, order_id=p.order.id, order_no=p.order.order_no, provider="wechat", action="query", status="not_paid"))
    p.db.add(AgreementAcceptanceModel(app_id=p.app.id, user_id=p.user.id, scene_code="membership_purchase", scene_revision=1, version_ids=[], business_ref=f"order:{p.order.order_no}"))
    await p.db.flush()
    result = await delete_unpaid_order(p.db, p.app.id, p.order.id, "清理未支付订单", 1, close_channel=False)
    assert result["deleted"] and result["removed"]["payment_attempts"] == 1 and result["removed"]["agreement_acceptances"] == 1
    assert p.order.is_deleted and p.order.next_query_at.replace(tzinfo=UTC) > datetime.now(UTC) and p.order.pay_url is None
    assert (await list_orders(p.db, p.app.id, FinanceQuery(user_id=p.user.id)))["total"] == 0
    assert await p.db.scalar(select(func.count()).select_from(PaymentAttemptModel).where(PaymentAttemptModel.order_id == p.order.id)) == 0
    assert (
        await p.db.scalar(
            select(func.count()).select_from(FinanceAuditModel).where(FinanceAuditModel.app_id == p.app.id, FinanceAuditModel.object_id == str(p.order.id), FinanceAuditModel.action == "delete_unpaid")
        )
        == 1
    )
    assert (await delete_unpaid_order(p.db, p.app.id, p.order.id, "重复清理", 1))["removed"] == {}


async def test_delete_refuses_paid_or_funded_records_and_other_scopes(purchase):
    from app.api.v1.module_finance.deletion import delete_unpaid_order

    p = purchase
    p.order.status, p.order.paid_at = "paid", datetime.now(UTC)
    await p.db.flush()
    with pytest.raises(CustomException, match="不能删除"):
        await delete_unpaid_order(p.db, p.app.id, p.order.id, "测试删除保护", 1)
    p.order.status, p.order.paid_at = "pending", None
    p.db.add(
        CreditGrantModel(
            app_id=p.app.id,
            user_id=p.user.id,
            source_type="credit_pack_order",
            source_id=p.order.id,
            release_index=0,
            amount=100,
            available=100,
            release_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(days=30),
            status="released",
        )
    )
    await p.db.flush()
    with pytest.raises(CustomException, match="账本关联"):
        await delete_unpaid_order(p.db, p.app.id, p.order.id, "测试权益保护", 1)
    other = ClientAppModel(code=uuid4().hex, name="删除隔离测试")
    p.db.add(other)
    await p.db.flush()
    with pytest.raises(CustomException, match="未找到"):
        await delete_unpaid_order(p.db, other.id, p.order.id, "测试隔离", 1)
    assert not p.order.is_deleted and p.close.await_count == 0


async def test_deletion_payment_race_commits_receipt_without_deleting(purchase):
    from app.api.v1.module_finance.controller import delete_order
    from app.api.v1.module_finance.schema import ReasonIn

    p = purchase
    p.query.return_value = payment(p.order)
    response = await delete_order(p.order.id, ReasonIn(reason="清理未支付订单"), p.auth, p.db)
    assert response.status_code == 409 and not json.loads(response.body)["data"]["deleted"]
    assert p.order.status == "paid" and not p.order.is_deleted
    assert await p.db.scalar(select(func.count()).select_from(CreditGrantModel).where(CreditGrantModel.source_id == p.order.id)) == 1


async def test_deleted_order_late_payment_restores_and_old_purchase_key_is_rejected(purchase):
    from app.api.v1.module_finance.deletion import delete_unpaid_order
    from app.api.v1.module_payment.order.schema import PaymentOrderCreate

    p = purchase
    await delete_unpaid_order(p.db, p.app.id, p.order.id, "测试归档", 1, close_channel=False)
    request = PaymentOrderCreate(catalog_plan_id=p.order.catalog_plan_id, provider=p.order.provider, idempotency_key=p.order.idempotency_key)
    with pytest.raises(CustomException, match="新的购买编号"):
        await PaymentOrderService(p.auth, p.db).create(request)
    await PaymentCallbackService(p.db).process("wechat", payment(p.order))
    assert not p.order.is_deleted and p.order.deleted_time is None and p.order.status == "paid"


async def test_archived_order_check_recovers_missed_payment_without_old_query_logs(purchase):
    from app.api.v1.module_finance.deletion import delete_unpaid_order

    p = purchase
    await delete_unpaid_order(p.db, p.app.id, p.order.id, "归档核验测试", 1, close_channel=False)
    p.query.return_value = payment(p.order)
    app_id, order_id = p.app.id, p.order.id
    await p.db.commit()
    await recovery.recover_archived_order(app_id, order_id)
    await p.db.refresh(p.order)
    assert not p.order.is_deleted and p.order.status == "paid"
    assert await p.db.scalar(select(func.count()).select_from(PaymentAttemptModel).where(PaymentAttemptModel.order_id == order_id)) == 0


def test_operator_delete_route_requires_authentication(test_client):
    response = test_client.request("DELETE", "/finance/orders/1", json={"reason": "清理未支付订单"})
    assert response.status_code == 401


@pytest.mark.parametrize("closed", [True, False])
async def test_archived_due_queue_stops_confirmed_closure_or_defers_unknown(purchase, closed):
    from app.api.v1.module_finance.deletion import delete_unpaid_order

    p = purchase
    await delete_unpaid_order(p.db, p.app.id, p.order.id, "归档调度测试", 1, close_channel=False)
    p.order.next_query_at = datetime.now(UTC) - timedelta(minutes=1)
    p.query.return_value = VerifiedClosedOrder(p.order.order_no, p.order.amount_fen) if closed else None
    app_id, order_id = p.app.id, p.order.id
    await p.db.commit()
    assert await recovery.recover_due_orders(app_id) == 1
    await p.db.refresh(p.order)
    assert p.order.is_deleted
    if closed:
        assert p.order.status == "closed" and p.order.next_query_at is None
    else:
        assert p.order.next_query_at.replace(tzinfo=UTC) > datetime.now(UTC) + timedelta(hours=23)
    assert await p.db.scalar(select(func.count()).select_from(PaymentAttemptModel).where(PaymentAttemptModel.order_id == order_id)) == 0


@pytest.mark.parametrize("case", ["expired", "live", "no_evidence", "transport_error", "wrong_order"])
async def test_alipay_absent_precreate_requires_expired_qr_evidence(purchase, case):
    p = purchase
    p.order.provider = "alipay"
    p.order.mode_switch = {"status": "pending_payment", "source_mode": "credits", "target_mode": "duration"}
    qr_expiry = datetime.now(UTC) + (timedelta(minutes=5) if case == "live" else -timedelta(minutes=2))
    p.order.strategy_snapshot = {"payment_session": {"kind": "alipay_precreate", "qr_expires_at": qr_expiry.isoformat()}} if case != "no_evidence" else {}
    p.query.return_value = VerifiedAbsentOrder("OTHER" if case == "wrong_order" else p.order.order_no)
    p.close.side_effect = CustomException(msg="支付宝关单返回交易不存在", status_code=502)
    if case == "transport_error":
        p.query.side_effect = TimeoutError()
    await p.db.flush()
    if case == "wrong_order":
        with pytest.raises(CustomException, match="原订单不一致"):
            await PaymentOrderService(p.auth, p.db).cancel(p.order.order_no)
        assert p.order.status == "pending"
        return
    result = await PaymentOrderService(p.auth, p.db).cancel(p.order.order_no)
    if case == "expired":
        assert result.status == "closed" and result.closed_at and result.pay_url is None
        assert p.close.await_count == 0 and p.order.next_query_at is None
        assert p.order.mode_switch["status"] == "cancelled"
        # A subsequent signed receipt still overrides local expiry.
        await PaymentCallbackService(p.db).process("alipay", payment(p.order))
        assert p.order.status == "paid" and p.order.mode_switch["status"] == "requires_confirmation"
    else:
        assert result.status == "confirming" and result.closed_at is None
        if case == "live":
            assert "尚未生成交易" in result.failure_reason
            assert p.order.next_query_at <= qr_expiry + timedelta(minutes=1)


async def test_due_alipay_absent_order_closes_without_locking_mode_preview(purchase, monkeypatch):
    from app.api.v1.module_billing.mode_switch import service as switches
    from app.api.v1.module_billing.mode_switch.schema import ModeSwitchPreviewIn

    p = purchase
    p.order.provider = "alipay"
    p.order.expires_at = datetime.now(UTC) - timedelta(minutes=2)
    p.order.strategy_snapshot = {"payment_session": {"kind": "alipay_precreate", "qr_expires_at": p.order.expires_at.isoformat()}}
    p.plan.plan_type = "subscription"
    p.plan.entitlement_kind = "credits"
    await p.db.flush()
    request = ModeSwitchPreviewIn(target_mode="credits", catalog_plan_id=p.plan.id, expected_mode_version=p.user.mode_version)
    assert (await switches.preview_switch(p.db, p.auth, request)).can_switch
    app_id, order_id = p.app.id, p.order.id
    await p.db.commit()
    monkeypatch.setattr(recovery, "query_alipay_order", AsyncMock(return_value=VerifiedAbsentOrder(p.order.order_no)))
    await recovery.recover_order(app_id, order_id)
    await p.db.refresh(p.order)
    assert p.order.status == "closed"
    assert (await switches.preview_switch(p.db, p.auth, request)).can_switch


async def test_successful_alipay_creation_records_verified_qr_validity(purchase, monkeypatch):
    from app.api.v1.module_payment.channel.model import AppPaymentChannelModel, PaymentChannelModel
    from app.api.v1.module_payment.channel.service import PaymentChannelService
    from app.api.v1.module_payment.order import service
    from app.api.v1.module_payment.order.schema import PaymentOrderCreate

    p = purchase
    channel = await p.db.scalar(select(PaymentChannelModel).where(PaymentChannelModel.provider == "alipay"))
    channel.enabled = True
    binding = await p.db.scalar(select(AppPaymentChannelModel).where(AppPaymentChannelModel.app_id == p.app.id, AppPaymentChannelModel.channel_id == channel.id))
    if binding:
        binding.enabled = True
    else:
        p.db.add(AppPaymentChannelModel(app_id=p.app.id, channel_id=channel.id, enabled=True))
    await p.db.flush()
    monkeypatch.setattr(PaymentChannelService, "_to_schema", lambda *_: SimpleNamespace(configured=True))
    monkeypatch.setattr(service, "create_alipay_qr_order", AsyncMock(return_value="https://qr.alipay.com/test"))
    before = datetime.now(UTC)
    result = await PaymentOrderService(p.auth, p.db).create(PaymentOrderCreate(catalog_plan_id=p.plan.id, provider="alipay", idempotency_key=uuid4().hex))
    order = await p.db.get(PaymentOrderModel, result.id)
    evidence = order.strategy_snapshot["payment_session"]
    assert result.status == "pending" and evidence["kind"] == "alipay_precreate"
    assert before + timedelta(minutes=15) <= datetime.fromisoformat(evidence["qr_expires_at"]) <= datetime.now(UTC) + timedelta(minutes=15)
