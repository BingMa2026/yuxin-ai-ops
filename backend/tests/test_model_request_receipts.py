"""Client receipts disclose accounting evidence, never recover missing model output."""

import hashlib
import importlib
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from app.api.v1.module_billing.model import CreditReservationModel
from app.api.v1.module_billing.service import CreditService
from app.api.v1.module_client.app.model import ClientAppModel
from app.api.v1.module_client.user.model import ClientUserModel
from app.api.v1.module_model_gateway.model import ModelUsageModel
from app.core.base_schema import AuthSchema, CoreUserSchema
from app.core.client_dependencies import get_current_client_user
from app.core.database import async_db_session
from app.core.exceptions import CustomException


def receipt_service():
    return importlib.import_module("app.api.v1.module_model_gateway.request_receipts").ModelRequestReceiptService


async def owner(*, app_id=None):
    suffix = uuid.uuid4().hex
    async with async_db_session() as db, db.begin():
        if app_id is None:
            app = ClientAppModel(service_mode="credits_only", code=f"receipt_{suffix[:16]}", name="回执隔离测试", status="active")
            db.add(app)
            await db.flush()
            app_id = app.id
        user = ClientUserModel(app_id=app_id, username=f"receipt_{suffix[:16]}", password_hash="isolated-unused", status="active")
        db.add(user)
        await db.flush()
        return AuthSchema(actor_type="client", app_id=app_id, user=CoreUserSchema(id=user.id, username=user.username))


async def records(auth, *, usage=None, reservation=None, request_id=None):
    request_id = request_id or f"receipt:{uuid.uuid4().hex}"
    async with async_db_session() as db, db.begin():
        if usage is not None:
            db.add(ModelUsageModel(app_id=auth.app_id, user_id=auth.user.id, request_id=request_id, business_code="document_intelligence", **usage))
        if reservation is not None:
            db.add(CreditReservationModel(app_id=auth.app_id, user_id=auth.user.id, request_id=request_id, **reservation))
    return request_id


async def read(auth, request_id):
    async with async_db_session() as db:
        return (await receipt_service()(auth, db).get(request_id)).model_dump(mode="json")


PUBLIC_KEYS = {
    "schema_version",
    "request_id",
    "execution_status",
    "settlement_status",
    "reserved_credits",
    "charged_credits",
    "reported_charged_credits",
    "input_tokens",
    "output_tokens",
    "usage_complete",
    "usage_basis",
    "error_code",
    "reservation_created_at",
    "completed_at",
    "settled_at",
    "server_content_available",
    "receipt_sha256",
}


async def test_settled_receipt_is_finite_stable_and_does_not_assert_content_recovery(test_client):
    auth = await owner()
    now = datetime.now(UTC)
    request_id = await records(
        auth,
        usage={
            "status": "succeeded",
            "input_tokens": 100,
            "output_tokens": 20,
            "charged_credits": 7,
            "cost_precision": "actual_usage",
            "completed_at": now,
            "execution_snapshot": {"usage_complete": True, "provider_secret": "must-not-leak", "generation_settings": {"private": "must-not-leak"}},
            "usage_detail": {"private": "must-not-leak"},
            "upstream_request_id": "must-not-leak",
            "provider_model_id": "must-not-leak",
        },
        reservation={"estimated": 30, "actual": 7, "status": "settled", "settled_at": now},
    )
    first, second = await read(auth, request_id), await read(auth, request_id)
    assert first == second and first.keys() == PUBLIC_KEYS
    assert first["schema_version"] == "model-request-receipt/v1"
    assert first["execution_status"] == "SUCCEEDED" and first["settlement_status"] == "SETTLED"
    assert first["charged_credits"] == first["reported_charged_credits"] == 7
    assert first["usage_complete"] is True and first["usage_basis"] == "REPORTED"
    assert first["server_content_available"] is False
    assert first["completed_at"].endswith("Z")
    payload = {key: value for key, value in first.items() if key != "receipt_sha256"}
    assert first["receipt_sha256"] == hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert "must-not-leak" not in json.dumps(first)


@pytest.mark.parametrize("status,actual,expected", [("reserved", None, "RESERVED"), ("cancelled", 0, "RELEASED")])
async def test_reservation_without_usage_cannot_prove_execution_or_no_call(test_client, monkeypatch, status, actual, expected):
    auth = await owner()
    request_id = await records(auth, reservation={"estimated": 50, "actual": actual, "status": status, "created_time": datetime.now(UTC) - timedelta(minutes=30)})

    async def forbidden_release(*args, **kwargs):
        raise AssertionError("receipt GET cannot release credits")

    monkeypatch.setattr(CreditService, "release_due", forbidden_release)
    result = await read(auth, request_id)
    assert result["execution_status"] == "UNKNOWN" and result["settlement_status"] == expected
    assert result["charged_credits"] == actual and result["reported_charged_credits"] is None
    assert result["input_tokens"] is result["output_tokens"] is result["usage_complete"] is None
    assert result["usage_basis"] == "UNKNOWN"
    async with async_db_session() as db:
        row = await db.scalar(sa.select(CreditReservationModel).where(CreditReservationModel.request_id == request_id))
        assert row.status == status and row.actual == actual


@pytest.mark.parametrize(
    "snapshot,precision,basis",
    [(None, "actual_usage", "REPORTED"), ({"usage_complete": False}, "observed_partial_usage", "OBSERVED_PARTIAL"), ({"usage_complete": "true"}, "estimated_usage", "ESTIMATED")],
)
async def test_legacy_or_partial_usage_keeps_unknown_completeness_and_settlement(test_client, snapshot, precision, basis):
    auth = await owner()
    request_id = await records(auth, usage={"status": "succeeded", "charged_credits": 9, "execution_snapshot": snapshot, "cost_precision": precision})
    result = await read(auth, request_id)
    assert result["execution_status"] == "SUCCEEDED" and result["settlement_status"] == "UNKNOWN"
    assert result["charged_credits"] is None and result["reported_charged_credits"] == 9
    assert result["usage_complete"] is (False if snapshot == {"usage_complete": False} else None)
    assert result["usage_basis"] == basis


@pytest.mark.parametrize("value", [1, 0, "false", "not-a-boolean", None])
async def test_metadata_numbers_and_strings_are_not_invented_as_complete_usage(test_client, value):
    auth = await owner()
    key = await records(auth, usage={"status": "succeeded", "execution_snapshot": {"usage_complete": value}})
    assert (await read(auth, key))["usage_complete"] is None


@pytest.mark.parametrize("record_type", ["usage", "reservation"])
async def test_same_app_other_user_other_app_and_absent_receipts_are_uniform_404(test_client, record_type):
    own = await owner()
    sibling, foreign = await owner(app_id=own.app_id), await owner()
    kwargs = {record_type: {"status": "failed"} if record_type == "usage" else {"estimated": 8}}
    request_id = await records(own, **kwargs)
    errors = []
    for auth, key in [(sibling, request_id), (foreign, request_id), (own, "missing:000000")]:
        with pytest.raises(CustomException) as caught:
            await read(auth, key)
        errors.append((caught.value.status_code, caught.value.code, caught.value.msg))
    assert errors[0] == errors[1] == errors[2] and errors[0][0] == 404


async def test_join_cannot_mix_other_user_reservation_with_owned_usage(test_client):
    own = await owner()
    sibling = await owner(app_id=own.app_id)
    key = await records(own, usage={"status": "failed", "charged_credits": 4})
    await records(sibling, request_id=key, reservation={"estimated": 100, "actual": 87, "status": "settled"})
    result = await read(own, key)
    assert result["reported_charged_credits"] == 4
    assert result["settlement_status"] == "UNKNOWN" and result["charged_credits"] is None


@pytest.mark.parametrize("record_type", ["usage", "reservation"])
async def test_deleted_receipts_are_unavailable(test_client, record_type):
    auth = await owner()
    values = {"status": "succeeded", "is_deleted": True} if record_type == "usage" else {"estimated": 5, "is_deleted": True}
    key = await records(auth, **{record_type: values})
    with pytest.raises(CustomException) as caught:
        await read(auth, key)
    assert caught.value.status_code == 404


@pytest.mark.parametrize(
    "status,error,expected_status,expected_error",
    [
        ("failed", "upstream_total_timeout", "FAILED", "UPSTREAM_TOTAL_TIMEOUT"),
        ("cancelled", "client_cancelled", "CANCELLED", "CLIENT_CANCELLED"),
        ("future_status", "https://private.invalid?secret=secret", "UNKNOWN", "UNKNOWN_ERROR"),
    ],
)
async def test_error_and_future_status_are_safe_finite_values(test_client, status, error, expected_status, expected_error):
    auth = await owner()
    key = await records(auth, usage={"status": status, "error_category": error})
    result = await read(auth, key)
    assert result["execution_status"] == expected_status and result["error_code"] == expected_error
    assert "private.invalid" not in json.dumps(result)


async def test_receipt_read_uses_one_snapshot_without_autoflush_or_row_lock(test_client):
    auth = await owner()
    key = await records(auth, usage={"status": "succeeded"})
    async with async_db_session() as db:
        connection = await db.connection()
        statements = []

        def record_statement(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        sa.event.listen(connection.sync_connection, "before_cursor_execute", record_statement)
        pending = CreditReservationModel(app_id=auth.app_id, user_id=auth.user.id, request_id=key, estimated=80)
        db.add(pending)
        try:
            result = await receipt_service()(auth, db).get(key)
            assert result.settlement_status == "UNKNOWN"
            assert len(statements) == 1 and statements[0].lstrip().upper().startswith("SELECT")
            assert "FOR UPDATE" not in statements[0].upper()
            assert pending in db.new
        finally:
            sa.event.remove(connection.sync_connection, "before_cursor_execute", record_statement)
            await db.rollback()


async def test_http_receipt_uses_existing_client_auth_and_validated_contract(test_client):
    auth = await owner()
    key = await records(auth, usage={"status": "succeeded"})
    url = f"/api/v1/client/model/requests/{key}/receipt"
    assert test_client.get(url).status_code == 401
    test_client.app.dependency_overrides[get_current_client_user] = lambda: auth
    try:
        response = test_client.get(url)
        assert response.status_code == 200, response.text
        result = response.json()["data"]
        assert response.headers["cache-control"] == "no-store"
        assert result.keys() == PUBLIC_KEYS and result == await read(auth, key)
        assert test_client.get("/api/v1/client/model/requests/bad!/receipt").status_code == 422
        sibling = await owner(app_id=auth.app_id)
        test_client.app.dependency_overrides[get_current_client_user] = lambda: sibling
        assert test_client.get(url).status_code == 404
    finally:
        test_client.app.dependency_overrides.pop(get_current_client_user, None)


@pytest.mark.parametrize("actor_type", ["runtime", "staff"])
async def test_service_requires_client_actor_even_with_valid_ids(test_client, actor_type):
    auth = await owner()
    key = await records(auth, usage={"status": "succeeded"})
    with pytest.raises(CustomException) as caught:
        await read(auth.model_copy(update={"actor_type": actor_type}), key)
    assert caught.value.status_code == 403
