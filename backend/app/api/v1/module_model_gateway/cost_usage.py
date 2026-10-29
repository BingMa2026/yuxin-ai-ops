"""Read-only request cost ledger. Supplier bills are a separate comparison source.

Speech's terminal updated_time is its completion time; usage rows have no edit API.
Keep catalog joins unfiltered so retiring a model cannot erase historical costs.
The two source IDs are not globally unique and must never be used for mutations.
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import case, literal, select, union_all

from app.api.v1.module_speech.model import SpeechUsageModel

from .model import ModelCatalogModel, ModelUsageModel


def request_cost_usage():
    chat = select(
        ModelUsageModel.id,
        ModelUsageModel.app_id,
        ModelUsageModel.user_id,
        ModelUsageModel.provider_account_id,
        ModelUsageModel.provider_model_id,
        ModelUsageModel.completed_at,
        ModelUsageModel.created_time,
        ModelUsageModel.input_tokens,
        ModelUsageModel.output_tokens,
        ModelUsageModel.charged_credits,
        ModelUsageModel.provider_cost_yuan,
        ModelUsageModel.status,
        ModelUsageModel.cost_precision,
        ModelUsageModel.reconciliation_status,
        ModelUsageModel.is_deleted,
        literal("chat").label("usage_kind"),
        literal(0).label("duration_ms"),
    )
    speech = (
        select(
            SpeechUsageModel.id,
            SpeechUsageModel.app_id,
            SpeechUsageModel.user_id,
            ModelCatalogModel.provider_account_id,
            ModelCatalogModel.provider_model_id,
            SpeechUsageModel.updated_time,
            SpeechUsageModel.created_time,
            literal(0),
            literal(0),
            literal(0),
            SpeechUsageModel.estimated_cost_yuan,
            case((SpeechUsageModel.status == "empty", "succeeded"), else_=SpeechUsageModel.status),
            case((SpeechUsageModel.estimated_cost_yuan.is_not(None), "estimated_usage"), else_="unknown"),
            literal("unmatched"),
            SpeechUsageModel.is_deleted,
            literal("speech"),
            SpeechUsageModel.duration_ms,
        )
        .outerjoin(ModelCatalogModel, ModelCatalogModel.id == SpeechUsageModel.catalog_model_id)
        .where(SpeechUsageModel.status != "running")
    )
    return union_all(chat, speech).subquery("request_cost_usage").c


RequestCostUsage = request_cost_usage()


def bill_cost_in_period(amount: Decimal, bill_start: datetime, bill_end: datetime, start: datetime, end: datetime) -> Decimal:
    bill_start = bill_start.replace(tzinfo=UTC) if bill_start.tzinfo is None else bill_start
    bill_end = bill_end.replace(tzinfo=UTC) if bill_end.tzinfo is None else bill_end
    duration = (bill_end - bill_start).total_seconds()
    overlap = max((min(bill_end, end) - max(bill_start, start)).total_seconds(), 0)
    return Decimal(amount or 0) * Decimal(str(overlap)) / Decimal(str(duration)) if duration > 0 else Decimal(0)
