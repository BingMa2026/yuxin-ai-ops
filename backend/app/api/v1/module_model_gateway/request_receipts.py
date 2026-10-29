"""Read one client's accounting evidence without changing credits or execution."""

import hashlib
import json
import re
from datetime import UTC, datetime

from sqlalchemy import and_, case, func, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.module_billing.model import CreditReservationModel
from app.core.base_schema import AuthSchema
from app.core.exceptions import CustomException

from .model import ModelUsageModel
from .schema import ClientModelRequestReceipt

_EXECUTION = {"succeeded": "SUCCEEDED", "failed": "FAILED", "cancelled": "CANCELLED"}
_SETTLEMENT = {"reserved": "RESERVED", "settled": "SETTLED", "cancelled": "RELEASED"}
_USAGE_BASIS = {"actual_usage": "REPORTED", "observed_partial_usage": "OBSERVED_PARTIAL", "estimated_usage": "ESTIMATED"}
_ERROR_CODES = frozenset(
    {
        "UPSTREAM_TOTAL_TIMEOUT",
        "UPSTREAM_IDLE_TIMEOUT",
        "UPSTREAM_CONNECT_TIMEOUT",
        "UPSTREAM_RATE_LIMITED",
        "UPSTREAM_AUTH_REJECTED",
        "UPSTREAM_REQUEST_REJECTED",
        "UPSTREAM_SERVER_ERROR",
        "UPSTREAM_PROTOCOL_ERROR",
        "UPSTREAM_UNAVAILABLE",
        "UPSTREAM_INTERRUPTED",
        "CLIENT_CANCELLED",
    }
)


def _utc(value: datetime | None) -> datetime | None:
    # The ORM stores UTC. SQLite fixtures lose timezone information on read.
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value.astimezone(UTC) if value is not None else None


def _safe_error(value: str | None) -> str | None:
    if not value:
        return None
    return value.upper() if value.upper() in _ERROR_CODES else "UNKNOWN_ERROR"


def _usage_complete_column(dialect: str):
    snapshot = ModelUsageModel.execution_snapshot
    value = snapshot["usage_complete"]
    # SQLite extracts JSON booleans as integers. Check the JSON type before
    # Boolean conversion, which otherwise also accepts numbers/strings. CASE
    # also prevents PostgreSQL from casting malformed string metadata to bool.
    if dialect == "sqlite":
        is_boolean = func.json_type(snapshot, "$.usage_complete").in_(("true", "false"))
    elif dialect == "postgresql":
        is_boolean = func.json_typeof(value) == "boolean"
    else:  # Framework MySQL compatibility; JSON_TYPE uses uppercase type names.
        is_boolean = func.json_type(value) == "BOOLEAN"
    return case((is_boolean, value.as_boolean()), else_=None).label("usage_complete")


class ModelRequestReceiptService:
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db

    async def get(self, request_id: str) -> ClientModelRequestReceipt:
        if self.auth.actor_type != "client" or not self.auth.app_id or not self.auth.user or not self.auth.user.id:
            raise CustomException(msg="请使用客户端本人账号核对请求", code=403, status_code=403)
        if re.fullmatch(r"[a-zA-Z0-9_.:-]{8,128}", request_id) is None:
            raise CustomException(msg="请求编号格式不正确", code=422, status_code=422)

        usage, reservation = ModelUsageModel, CreditReservationModel

        def scope(model):
            return and_(model.app_id == self.auth.app_id, model.user_id == self.auth.user.id, model.request_id == request_id, model.is_deleted.is_(False))

        # One SQL statement gives a consistent READ COMMITTED snapshot on PostgreSQL.
        # Scope both the key union and each join: a corrupt cross-user pair must not
        # join on request_id alone. No release_due, account load, locks or autoflush.
        keys = union(select(usage.request_id).where(scope(usage)), select(reservation.request_id).where(scope(reservation))).subquery()
        statement = (
            select(
                usage.id.label("usage_id"),
                usage.status.label("execution_status"),
                usage.input_tokens,
                usage.output_tokens,
                usage.charged_credits.label("reported_charged_credits"),
                usage.cost_precision,
                usage.error_category,
                usage.completed_at,
                _usage_complete_column(self.db.get_bind().dialect.name),
                reservation.id.label("reservation_id"),
                reservation.status.label("settlement_status"),
                reservation.estimated,
                reservation.actual,
                reservation.created_time.label("reservation_created_at"),
                reservation.settled_at,
            )
            .select_from(keys)
            .outerjoin(usage, and_(usage.request_id == keys.c.request_id, scope(usage)))
            .outerjoin(reservation, and_(reservation.request_id == keys.c.request_id, scope(reservation)))
            .execution_options(autoflush=False)
        )
        row = (await self.db.execute(statement)).mappings().one_or_none()
        if row is None:
            # The same answer for unknown, deleted, another user, or another app.
            raise CustomException(msg="未找到可核对的本人请求记录", code=404, status_code=404)

        has_usage, has_reservation = row["usage_id"] is not None, row["reservation_id"] is not None
        settlement = _SETTLEMENT.get(row["settlement_status"], "UNKNOWN")
        receipt = ClientModelRequestReceipt(
            request_id=request_id,
            execution_status=_EXECUTION.get(row["execution_status"], "UNKNOWN"),
            settlement_status=settlement,
            reserved_credits=row["estimated"] if has_reservation else None,
            charged_credits=row["actual"] if has_reservation and settlement in {"SETTLED", "RELEASED"} else None,
            reported_charged_credits=row["reported_charged_credits"] if has_usage else None,
            input_tokens=row["input_tokens"] if has_usage else None,
            output_tokens=row["output_tokens"] if has_usage else None,
            usage_complete=row["usage_complete"] if type(row["usage_complete"]) is bool else None,
            usage_basis=_USAGE_BASIS.get(row["cost_precision"], "UNKNOWN"),
            error_code=_safe_error(row["error_category"]),
            reservation_created_at=_utc(row["reservation_created_at"]),
            completed_at=_utc(row["completed_at"]),
            settled_at=_utc(row["settled_at"]),
            receipt_sha256="0" * 64,
        )
        payload = receipt.model_dump(mode="json", exclude={"receipt_sha256"})
        digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        return receipt.model_copy(update={"receipt_sha256": digest})
