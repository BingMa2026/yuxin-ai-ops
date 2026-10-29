from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.api.v1.module_client.app.model import ClientAppModel
from app.api.v1.module_client.user.model import ClientUserModel
from app.api.v1.module_model_gateway.finance_service import ModelFinanceService
from app.api.v1.module_model_gateway.model import ModelCostReconciliationModel, ModelProviderBillItemModel, ModelUsageModel
from app.api.v1.module_operations.service import OperationsOverviewService
from app.api.v1.module_speech.model import SpeechUsageModel
from tests.test_speech import speech_setup as _speech_setup

speech_setup = _speech_setup


def speech_row(app_id, user_id, model_id, when, cost, **extra):
    return SpeechUsageModel(
        app_id=app_id,
        user_id=user_id,
        catalog_model_id=model_id,
        request_id=uuid4().hex,
        duration_ms=60000,
        status="succeeded",
        estimated_cost_yuan=cost,
        created_time=when,
        updated_time=when,
        **extra,
    )


async def test_shared_cost_reporting_includes_speech_without_credits_or_double_counting(speech_setup):
    db, auth, model, account = speech_setup
    when = datetime.now(UTC) - timedelta(minutes=2)
    start = datetime.combine(when.astimezone(ZoneInfo("Asia/Shanghai")).date(), time.min, tzinfo=ZoneInfo("Asia/Shanghai")).astimezone(UTC)
    end = start + timedelta(days=1)
    other_app = ClientAppModel(service_mode="credits_only", code=uuid4().hex, name="other", status="active")
    db.add(other_app)
    await db.flush()
    other_user = ClientUserModel(app_id=other_app.id, username=uuid4().hex, password_hash="test")
    db.add(other_user)
    await db.flush()
    db.add_all(
        [
            ModelUsageModel(
                app_id=auth.app_id,
                user_id=auth.user.id,
                provider_account_id=account.id,
                provider_model_id="chat-test",
                request_id=uuid4().hex,
                business_code="chat",
                status="succeeded",
                input_tokens=100,
                output_tokens=20,
                charged_credits=5,
                provider_cost_yuan=Decimal("2"),
                cost_precision="actual_usage",
                reconciliation_status="reconciled",
                completed_at=when,
            ),
            speech_row(auth.app_id, auth.user.id, model.id, when, Decimal("0.0132")),
            speech_row(other_app.id, other_user.id, model.id, when, Decimal("0.04")),
            ModelProviderBillItemModel(
                provider_account_id=account.id,
                external_id=uuid4().hex,
                service_start_at=start,
                service_end_at=end,
                amount_yuan=Decimal("4"),
                amount_original=Decimal("4"),
                currency="CNY",
                source="manual",
            ),
        ]
    )
    await db.flush()
    service = OperationsOverviewService(auth, db)
    summary, daily = await service._period_metrics(auth.app_id, start, end, 1, "day")
    assert summary.provider_cost_yuan == pytest.approx(2.0132)
    assert summary.speech_cost_yuan == pytest.approx(0.0132)
    assert summary.direct_margin_yuan == -2.01
    assert summary.credits_consumed == 5 and summary.total_tokens == 120
    assert summary.model_calls == 2 and summary.speech_calls == 1
    assert summary.cost_status == "partial"
    assert summary.supplier_billed_cost_yuan == pytest.approx(round(4 * 2.0132 / 2.0532, 4))
    assert daily[0].speech_cost_yuan == summary.speech_cost_yuan
    ranking = await service._model_distribution(auth.app_id, start, end)
    assert [(item.usage_kind, item.cost_yuan) for item in ranking] == [("chat", 2), ("speech", 0.0132)]
    assert ranking[1].duration_ms == 60000 and ranking[1].tokens == 0
    finance = await ModelFinanceService(auth, db).summary(account.id)
    assert finance.request_cost_yuan == pytest.approx(2.0532)
    assert finance.speech_cost_yuan == pytest.approx(0.0532)
    assert finance.month_request_count == 3
    await ModelFinanceService(auth, db)._reconcile(account.id, start, end)
    await db.flush()
    reconciliations = list((await db.scalars(select(ModelCostReconciliationModel).where(ModelCostReconciliationModel.provider_account_id == account.id))).all())
    assert sum(item.request_count for item in reconciliations) == 3
    assert sum(item.supplier_cost_yuan for item in reconciliations) == pytest.approx(Decimal("4"))
    # Changing price or retiring a model must not reprice or hide historical usage.
    model.speech_pricing = {}
    model.is_deleted = True
    await db.flush()
    again, _ = await service._period_metrics(auth.app_id, start, end, 1, "day")
    assert again == summary
    other, _ = await service._period_metrics(other_app.id, start, end, 1, "day")
    assert other.provider_cost_yuan == 0.04 and other.credits_consumed == 0


async def test_unknown_speech_cost_and_completion_boundaries_are_not_free(speech_setup):
    db, auth, model, _ = speech_setup
    start = datetime(2026, 9, 12, 16, tzinfo=UTC)  # September 13 in Shanghai.
    end = start + timedelta(days=1)
    known = speech_row(auth.app_id, auth.user.id, model.id, start, Decimal("0.0132"))
    known.created_time = start - timedelta(seconds=30)
    failed = speech_row(auth.app_id, auth.user.id, model.id, start, None)
    failed.status = "failed"
    empty = speech_row(auth.app_id, auth.user.id, model.id, start, Decimal("0.00022"))
    empty.status = "empty"
    running = speech_row(auth.app_id, auth.user.id, model.id, start, Decimal("100"))
    running.status = "running"
    db.add_all(
        [
            known,
            failed,
            empty,
            running,
            speech_row(auth.app_id, auth.user.id, model.id, end, Decimal("100")),
            speech_row(auth.app_id, auth.user.id, model.id, start - timedelta(microseconds=1), Decimal("100")),
            speech_row(auth.app_id, auth.user.id, model.id, start, Decimal("100"), is_deleted=True),
        ]
    )
    await db.flush()
    service = OperationsOverviewService(auth, db)
    summary, daily = await service._period_metrics(auth.app_id, start, end, 1, "day")
    assert summary.provider_cost_yuan == pytest.approx(0.0134)
    assert summary.unknown_cost_calls == 1 and summary.cost_status == "incomplete"
    assert summary.model_calls == 3 and summary.model_success_rate == pytest.approx(66.67)
    assert summary.total_tokens == summary.credits_consumed == 0
    assert daily[0].date == "2026-09-13" and daily[0].unknown_cost_calls == 1
    ranking = await service._model_distribution(auth.app_id, start, end)
    assert len(ranking) == 1 and ranking[0].unknown_cost_calls == 1


async def test_partial_bill_period_is_prorated_and_never_added_to_request_cost(speech_setup):
    db, auth, model, account = speech_setup
    start = datetime(2026, 9, 12, 16, tzinfo=UTC)
    end = start + timedelta(days=1)
    db.add_all(
        [
            speech_row(auth.app_id, auth.user.id, model.id, start, Decimal("0.0132")),
            ModelProviderBillItemModel(
                provider_account_id=account.id,
                external_id=uuid4().hex,
                service_start_at=start - timedelta(days=1),
                service_end_at=end,
                amount_yuan=Decimal("10"),
                amount_original=Decimal("10"),
                currency="CNY",
                source="manual",
            ),
        ]
    )
    await db.flush()
    summary, _ = await OperationsOverviewService(auth, db)._period_metrics(auth.app_id, start, end, 1, "day")
    assert summary.supplier_billed_cost_yuan == 5
    assert summary.provider_cost_yuan == 0.0132
