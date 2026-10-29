from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.api.v1.module_finance import bills, channels, issues, orders, overview, records, refunds
from app.api.v1.module_finance.bill_gateway import BillLine, parse_csv
from app.api.v1.module_finance.common import BUSINESS_TZ, csv_chunk
from app.api.v1.module_finance.gateway import RefundResult
from app.api.v1.module_finance.model import FinanceBillEntryModel, FinanceControlModel
from app.api.v1.module_finance.schema import BillCreate, FinanceQuery, RefundCreate, RefundReview
from app.api.v1.module_payment.order.model import PaymentRefundModel
from app.core.database import async_db_session
from app.core.exceptions import CustomException
from tests.test_growth_accounting import payment, setup_scope


@pytest.mark.asyncio
async def test_refund_reservation_review_success_idempotency_and_scope(test_client):
    async with async_db_session() as db:
        scope, users = await setup_scope(db)
        other, _ = await setup_scope(db)
        order = await payment(db, scope, users[0].id)
        order.provider_trade_no = "provider-" + order.order_no
        data = RefundCreate(order_id=order.id, amount_fen=4000, reason="用户申请部分补偿", entitlement_action="retain", idempotency_key=uuid4().hex)
        row = await refunds.create_refund(db, scope, 1, data)
        assert (await refunds.create_refund(db, scope, 1, data)).id == row.id
        with pytest.raises(CustomException):
            await refunds.create_refund(db, scope, 1, data.model_copy(update={"idempotency_key": uuid4().hex, "amount_fen": 7000}))
        with pytest.raises(CustomException):
            await refunds.get_refund(db, other, row.id)
        found = await orders.list_orders(db, scope, FinanceQuery())
        assert found["items"][0].refund_reserved_fen == 4000
        assert found["items"][0].refundable_fen == 6000
        assert (await orders.list_orders(db, other, FinanceQuery()))["total"] == 0
        await refunds.review_refund(db, scope, row.id, 2, RefundReview(approved=True, reason="按补偿政策审核"))
        result = RefundResult("succeeded", "refund-" + uuid4().hex, datetime.now(UTC))
        await refunds.apply_refund(db, row, result)
        await refunds.apply_refund(db, row, result)
        assert await db.scalar(select(func.count()).select_from(PaymentRefundModel).where(PaymentRefundModel.order_id == order.id)) == 1
        found = await orders.list_orders(db, scope, FinanceQuery(status="partially_refunded"))
        assert found["items"][0].refunded_fen == 4000
        assert found["items"][0].refund_reserved_fen == 0
        assert found["items"][0].refundable_fen == 6000
        detail = await orders.order_detail(db, scope, order.id)
        assert detail["refunds"][0]["amount_fen"] == 4000
        assert (await records.list_refunds(db, scope, FinanceQuery()))["items"][0].order_no == order.order_no
        await db.rollback()


@pytest.mark.asyncio
async def test_rejected_and_unknown_refunds_have_different_reservations(test_client):
    async with async_db_session() as db:
        scope, users = await setup_scope(db)
        order = await payment(db, scope, users[0].id)
        order.provider_trade_no = "provider-" + order.order_no
        data = RefundCreate(order_id=order.id, amount_fen=10000, reason="申请退款", entitlement_action="retain", idempotency_key=uuid4().hex)
        row = await refunds.create_refund(db, scope, 1, data)
        await refunds.review_refund(db, scope, row.id, 2, RefundReview(approved=False, reason="不符合退款条件"))
        assert (await orders.list_orders(db, scope, FinanceQuery()))["items"][0].refundable_fen == 10000
        row2 = await refunds.create_refund(db, scope, 1, data.model_copy(update={"idempotency_key": uuid4().hex}))
        await refunds.apply_refund(db, row2, RefundResult("unknown", reason="超时"))
        assert (await orders.list_orders(db, scope, FinanceQuery()))["items"][0].refundable_fen == 0
        db.add(FinanceControlModel(app_id=scope, provider="alipay", payout_enabled=False, refund_enabled=False))
        await db.flush()
        assert not await channels.enabled(db, scope, "alipay", "refund")
        with pytest.raises(CustomException):
            await refunds.create_refund(db, scope, 1, data.model_copy(update={"idempotency_key": uuid4().hex}))
        await db.rollback()


@pytest.mark.asyncio
async def test_reconciliation_matches_only_current_app_and_keeps_differences(test_client):
    async with async_db_session() as db:
        scope, users = await setup_scope(db)
        other, other_users = await setup_scope(db)
        order = await payment(db, scope, users[0].id)
        foreign_order = await payment(db, other, other_users[0].id)
        day = datetime.now(BUSINESS_TZ).date() - timedelta(days=1)
        order.provider_trade_no = "ALI123"
        order.paid_at = datetime.combine(day, datetime.min.time(), BUSINESS_TZ) + timedelta(hours=12)
        bill = await bills.request_bill(db, scope, 1, BillCreate(provider="alipay", bill_date=day))
        await bills.reconcile_bill(db, bill, [BillLine(order.order_no, "ALI123", "", "payment", 9900, 59), BillLine(foreign_order.order_no, "ALI_OTHER", "", "payment", 10000, 60)])
        await db.flush()
        assert bill.summary["excluded_merchant_rows"] == 1
        assert bill.summary["differences"] == 1
        entries = await records.list_entries(db, scope, bill.id, FinanceQuery())
        assert entries["total"] == 1
        assert entries["items"][0].match_status == "amount_mismatch"
        assert entries["items"][0].system_amount_fen == 10000
        with pytest.raises(CustomException):
            await records.list_entries(db, other, bill.id, FinanceQuery())
        await issues.refresh_issues(db, scope)
        assert (await records.list_issues(db, scope, FinanceQuery()))["total"] >= 1
        await bills.resolve_entry(db, scope, entries["items"][0].id, 1, "商户优惠差异已人工核验，附件记录于工单123")
        assert (await db.get(FinanceBillEntryModel, entries["items"][0].id)).resolved_at
        data = await overview.overview(db, scope, day, day)
        assert data["current"]["received_fen"] == 10000
        await db.rollback()


def test_official_bill_formats_and_formula_export():
    ali = "#账单\n支付宝交易号,商户订单号,业务类型,订单金额（元）,服务费（元）,退款批次号\nALI1,YX1,交易,10.01,0.06,\nALI1,YX1,退款,-2.01,-0.01,RF1\n#结束"
    rows = parse_csv(ali.encode("gb18030"), "alipay")
    assert [(r.kind, r.amount, r.fee) for r in rows] == [("payment", 1001, 6), ("refund", 201, -1)]
    wechat = "交易时间,微信订单号,商户订单号,交易状态,订单金额,商户退款单号,申请退款金额,手续费\n`2026-09-09 12:00:00,`WX1,`YX1,`SUCCESS,`10.01,`0,`0.00,`0.06\n总交易单数,总金额\n`1,`10.01"
    assert parse_csv(wechat.encode(), "wechat")[0].amount == 1001
    with pytest.raises(CustomException):
        parse_csv("错误字段\n1".encode(), "alipay")
    assert "'=HYPERLINK" in csv_chunk([["=HYPERLINK(1)", "安全名称", 100]])


@pytest.mark.asyncio
async def test_lists_empty_and_date_amount_validation(test_client):
    async with async_db_session() as db:
        scope, _ = await setup_scope(db)
        assert (await records.list_payouts(db, scope, FinanceQuery()))["total"] == 0
        assert (await records.list_bills(db, scope, FinanceQuery()))["total"] == 0
        assert (await orders.list_orders(db, scope, FinanceQuery()))["summary"]["amount_fen"] == 0
        await db.rollback()
    with pytest.raises(ValueError):
        FinanceQuery(min_amount_fen=100, max_amount_fen=50)


@pytest.mark.asyncio
@pytest.mark.parametrize("cost_mode", [False, True])
async def test_terminated_order_never_releases_reserved_or_pending_credits_again(test_client, cost_mode):
    from app.api.v1.module_billing.model import CreditGrantModel
    from app.api.v1.module_billing.service import CreditService
    from app.api.v1.module_finance.entitlements import terminate_order_entitlements

    async with async_db_session() as db:
        scope, users = await setup_scope(db)
        order = await payment(db, scope, users[0].id)
        service = CreditService(db)
        account = await service.account(scope, users[0].id, lock=True)
        account.available, account.pending = 1100, 500
        now = datetime.now(UTC)
        grants = [
            CreditGrantModel(
                app_id=scope,
                user_id=users[0].id,
                source_type="credit_pack_order",
                source_id=order.id,
                release_index=0,
                amount=1000,
                available=1000,
                release_at=now,
                expires_at=now + timedelta(days=30),
                status="released",
            ),
            CreditGrantModel(
                app_id=scope,
                user_id=users[0].id,
                source_type="credit_pack_order",
                source_id=order.id,
                release_index=1,
                amount=500,
                available=0,
                release_at=now + timedelta(days=1),
                expires_at=now + timedelta(days=30),
                status="pending",
            ),
            CreditGrantModel(
                app_id=scope, user_id=users[0].id, source_type="manual", source_id=987654, amount=100, available=100, release_at=now, expires_at=now + timedelta(days=60), status="released"
            ),
        ]
        db.add_all(grants)
        await db.flush()
        reservation = await service.reserve_cost(scope, users[0].id, "finance-reservation", Decimal("0.08")) if cost_mode else await service.reserve(scope, users[0].id, "finance-reservation", 200)
        assert reservation.estimated == 200
        result = await terminate_order_entitlements(db, order, "RF-test")
        assert result["revoked_available"] == 800
        assert result["cancelled_pending"] == 500
        assert account.available == 100 and account.pending == 0
        if cost_mode:
            await service.settle_cost(scope, users[0].id, "finance-reservation", Decimal("0"))
        else:
            await service.settle(scope, users[0].id, "finance-reservation", 0)
        await service.release_due(app_id=scope, user_id=users[0].id)
        assert account.available == 100 and account.reserved == 0
        await terminate_order_entitlements(db, order, "RF-test-again")
        assert account.available == 100
        await db.rollback()


def test_finance_api_permission_and_scope_are_not_optional(test_client):
    from app.core.base_schema import AuthSchema, CoreUserSchema
    from app.core.dependencies import get_current_user

    auth = AuthSchema(user=CoreUserSchema(id=99, username="finance-read", is_superuser=False), permissions=["workspace:finance:order:list"], app_id=1)
    test_client.app.dependency_overrides[get_current_user] = lambda: auth
    try:
        assert test_client.get("/finance/orders").status_code == 200
        assert test_client.get("/finance/orders?start_date=2026-09-10&end_date=2026-09-01").status_code == 422
        assert test_client.get("/finance/orders?min_amount_fen=500&max_amount_fen=200").status_code == 422
        assert test_client.post("/finance/refunds", json={"order_id": 1, "amount_fen": 100, "reason": "test", "entitlement_action": "retain", "idempotency_key": "test123456"}).status_code == 403
        assert test_client.get("/finance/orders/export").status_code == 403
        auth.app_id = None
        auth.user.is_superuser = True
        assert test_client.get("/finance/orders").status_code == 409
    finally:
        test_client.app.dependency_overrides.pop(get_current_user, None)


def test_finance_migration_matches_models_and_postgres_ddl(test_client):
    import importlib
    from io import StringIO

    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine

    from app.core.base_model import MappedBase

    migration = importlib.import_module("app.alembic.versions.20260910_finance_center")
    engine = create_engine("sqlite:///:memory:")
    metadata = MappedBase.metadata
    tables = [table for table in metadata.sorted_tables if table.name.startswith("finance_")]
    with engine.begin() as connection:
        metadata.create_all(connection)
        metadata.drop_all(connection, tables=tables)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()
        ctx = MigrationContext.configure(connection, opts={"include_object": lambda obj, name, kind, reflected, compare: name.startswith("finance_") if kind == "table" else True})
        assert compare_metadata(ctx, metadata) == []
    engine.dispose()
    output = StringIO()
    with Operations.context(MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})):
        migration.upgrade()
    assert output.getvalue().count("CREATE TABLE finance_") == 6


@pytest.mark.asyncio
async def test_beijing_midnight_matches_overview_daily_and_order_filter(test_client):
    async with async_db_session() as db:
        scope, users = await setup_scope(db)
        for at, amount in [
            (datetime(2026, 9, 8, 15, 59, tzinfo=UTC), 100),
            (datetime(2026, 9, 8, 16, 0, tzinfo=UTC), 200),
            (datetime(2026, 9, 9, 15, 59, tzinfo=UTC), 300),
            (datetime(2026, 9, 9, 16, 0, tzinfo=UTC), 400),
        ]:
            row = await payment(db, scope, users[0].id, amount)
            row.paid_at = at
        await db.flush()
        day = date(2026, 9, 9)
        result = await overview.overview(db, scope, day, day)
        assert result["current"]["received_fen"] == result["daily"][0]["received_fen"] == 500
        found = await orders.list_orders(db, scope, FinanceQuery(start_date=day, end_date=day, time_field="paid_at"))
        assert found["total"] == 2
        await db.rollback()


@pytest.mark.asyncio
async def test_failed_checkout_issue_can_be_closed_without_hiding_new_failures(test_client):
    from app.api.v1.module_finance.schema import IssueAction

    async with async_db_session() as db:
        scope, users = await setup_scope(db)
        row = await payment(db, scope, users[0].id)
        row.status, row.paid_at = "failed", None
        await db.flush()
        await issues.refresh_issues(db, scope)
        issue = (await records.list_issues(db, scope, FinanceQuery()))["items"][0]
        await issues.issue_action(db, scope, issue.id, 1, IssueAction(action="resolve", reason="已修正渠道配置，该未支付订单关闭处理"))
        await issues.refresh_issues(db, scope)
        assert (await records.list_issues(db, scope, FinanceQuery(status="unresolved")))["total"] == 0
        another = await payment(db, scope, users[0].id)
        another.status, another.paid_at = "failed", None
        await db.flush()
        await issues.refresh_issues(db, scope)
        assert (await records.list_issues(db, scope, FinanceQuery(status="unresolved")))["total"] == 1
        await db.rollback()


@pytest.mark.asyncio
async def test_verified_paid_missing_rights_repair_is_idempotent(test_client, monkeypatch):
    from unittest.mock import AsyncMock

    from app.api.v1.module_billing.model import CreditGrantModel
    from app.api.v1.module_payment.order.providers import VerifiedPayment

    async with async_db_session() as db:
        scope, users = await setup_scope(db)
        row = await payment(db, scope, users[0].id)
        row.provider_trade_no = "ALI-REPAIR"
        row.plan_snapshot = {"plan_type": "credit_pack", "total_credits": 5000, "credit_valid_days": 365}
        await db.flush()
        verified = VerifiedPayment(uuid4().hex, row.order_no, row.provider_trade_no, row.amount_fen, row.paid_at, "test")
        monkeypatch.setattr(orders, "query_alipay_order", AsyncMock(return_value=verified))
        for _ in range(2):
            result = await orders.verify_order(db, scope, row.id, 1, "客户反馈权益未到账，经渠道核验补发")
            assert result["order"].fulfillment_status == "fulfilled"
        assert await db.scalar(select(func.count()).select_from(CreditGrantModel).where(CreditGrantModel.app_id == scope)) == 1
        await db.rollback()


@pytest.mark.asyncio
async def test_refund_gateway_rejects_amount_or_identifier_mismatch(monkeypatch):
    from unittest.mock import AsyncMock

    from app.api.v1.module_finance import gateway

    ali = {
        "code": "10000",
        "out_trade_no": "ORDER",
        "trade_no": "ALI1",
        "out_request_no": "RF1",
        "refund_amount": "1.01",
        "total_amount": "2.00",
        "refund_status": "REFUND_SUCCESS",
        "gmt_refund_pay": "2026-09-09 12:00:00",
    }
    monkeypatch.setattr(gateway, "alipay_request", AsyncMock(return_value=ali))
    with pytest.raises(CustomException):
        await gateway.refund_request("alipay", "ORDER", "ALI1", "RF1", 100, 200, "test", query=True)
    ali["refund_amount"] = "1.00"
    assert (await gateway.refund_request("alipay", "ORDER", "ALI1", "RF1", 100, 200, "test", query=True)).status == "succeeded"
    wx = {"out_trade_no": "ORDER", "transaction_id": "WX1", "out_refund_no": "FOREIGN", "amount": {"refund": 100, "total": 200, "currency": "CNY"}, "status": "SUCCESS"}
    monkeypatch.setattr(gateway, "wechat_request", AsyncMock(return_value=(200, wx)))
    with pytest.raises(CustomException):
        await gateway.refund_request("wechat", "ORDER", "WX1", "RF1", 100, 200, "test", query=True)


@pytest.mark.asyncio
async def test_client_history_never_returns_another_users_order(test_client):
    from app.api.v1.module_finance.controller import client_order, client_orders
    from app.core.base_schema import AuthSchema, CoreUserSchema

    async with async_db_session() as db:
        scope, users = await setup_scope(db)
        mine = await payment(db, scope, users[0].id)
        foreign = await payment(db, scope, users[1].id)
        auth = AuthSchema(user=CoreUserSchema(id=users[0].id, username=users[0].username, is_superuser=False), app_id=scope)
        with pytest.raises(CustomException) as error:
            await client_order(foreign.id, auth, db)
        assert error.value.status_code == 404
        response = await client_orders(auth, db, FinanceQuery(user_id=users[1].id))
        import json

        body = json.loads(response.body)
        assert [r["id"] for r in body["data"]["items"]] == [mine.id]
        detail = json.loads((await client_order(mine.id, auth, db)).body)["data"]
        assert not {"audits", "attempts", "callbacks", "rewards", "strategy_snapshot"} & detail.keys()
        await db.rollback()


@pytest.mark.asyncio
async def test_external_refund_is_in_confirmed_ledger_and_reconciles(test_client, monkeypatch):
    from unittest.mock import AsyncMock

    from app.api.v1.module_growth import refund_gateway

    async with async_db_session() as db:
        scope, users = await setup_scope(db)
        order = await payment(db, scope, users[0].id)
        order.provider_trade_no = "ALI-EXT"
        at = datetime.now(UTC) - timedelta(days=1)
        day = at.astimezone(BUSINESS_TZ).date()
        order.paid_at = at
        monkeypatch.setattr(refund_gateway, "query_refund", AsyncMock(return_value={"amount": 1000, "provider_no": "verified_external_refund", "at": at}))
        for _ in range(2):
            await refund_gateway.synchronize_refund(db, scope, order.order_no, "EXTERNAL-RF1")
        ledger = await records.list_refund_ledger(db, scope, FinanceQuery())
        assert ledger["total"] == 1 and ledger["summary"]["amount_fen"] == 1000
        bill = await bills.request_bill(db, scope, 1, BillCreate(provider="alipay", bill_date=day))
        await bills.reconcile_bill(db, bill, [BillLine(order.order_no, "ALI-EXT", "", "payment", order.amount_fen, 60), BillLine(order.order_no, "ALI-EXT", "EXTERNAL-RF1", "refund", 1000, -6)])
        assert bill.summary["entries"] == 2 and bill.summary["differences"] == 0
        await db.rollback()


@pytest.mark.asyncio
async def test_refund_retry_keeps_original_identity_and_reserved_amount(test_client):
    from app.api.v1.module_finance.controller import retry_refund
    from app.api.v1.module_finance.schema import ReasonIn
    from app.core.base_schema import AuthSchema, CoreUserSchema

    async with async_db_session() as db:
        scope, users = await setup_scope(db)
        order = await payment(db, scope, users[0].id)
        order.provider_trade_no = "ALI-RETRY"
        row = await refunds.create_refund(db, scope, 1, RefundCreate(order_id=order.id, amount_fen=2500, reason="退未使用部分", entitlement_action="retain", idempotency_key=uuid4().hex))
        await refunds.review_refund(db, scope, row.id, 1, RefundReview(approved=True, reason="同意退款"))
        row.status = "unknown"
        row.submitted_at = datetime.now(UTC)
        await db.flush()
        original = row.refund_no
        auth = AuthSchema(user=CoreUserSchema(id=1, username="admin", is_superuser=True), app_id=scope)
        await retry_refund(row.id, ReasonIn(reason="已核对商户平台记录，按原单重提"), auth, db)
        assert row.refund_no == original and row.status == "queued"
        assert (await orders.list_orders(db, scope, FinanceQuery()))["items"][0].refund_reserved_fen == 2500
        with pytest.raises(CustomException):
            await retry_refund(row.id, ReasonIn(reason="重复点击"), auth, db)
        await db.rollback()


@pytest.mark.asyncio
async def test_finance_excludes_legacy_demo_and_counts_only_positive_channel_receipts(test_client):
    async with async_db_session() as db:
        scope, users = await setup_scope(db)
        real = await payment(db, scope, users[0].id, 1)
        real.provider = "alipay"
        free = await payment(db, scope, users[0].id, 0)
        free.provider = "wechat"
        demo = await payment(db, scope, users[0].id, 9900)
        demo.provider = "wechat"
        demo.order_no = "DEV0010000105"
        demo.idempotency_key = "dev-demo-order-5"
        demo.provider_trade_no = "DEVTRADE0005"
        await db.flush()
        day = datetime.now(BUSINESS_TZ).date()
        result = await overview.overview(db, scope, day, day)
        assert result["current"]["received_fen"] == 1
        assert result["current"]["paid_orders"] == 1
        assert result["current"]["average_order_fen"] == 1
        assert result["daily"][0]["received_fen"] == 1
        assert result["daily"][0]["paid_orders"] == 1
        by_provider = {r["provider"]: r for r in result["channels"]}
        assert by_provider["alipay"]["received_fen"] == 1
        assert by_provider["wechat"]["received_fen"] == 0
        assert by_provider["wechat"]["paid_orders"] == 0
        assert by_provider["wechat"]["created_orders"] == 0
        history = await orders.list_orders(db, scope, FinanceQuery(user_id=users[0].id))
        assert {r.id for r in history["items"]} == {real.id, free.id}
        with pytest.raises(CustomException):
            await orders.get_order(db, scope, demo.id)
        # A real channel trade must not be hidden merely because a caller used a similar key.
        demo.provider_trade_no = "202609102200000001"
        await db.flush()
        assert (await orders.list_orders(db, scope, FinanceQuery()))["total"] == 3
        await db.rollback()
