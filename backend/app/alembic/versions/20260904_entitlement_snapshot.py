"""Backfill entitlement snapshots and complete campaign delivery metrics.

Revision ID: 20260904_entitlement_snapshot
Revises: 20260904_operations_complete
"""

from __future__ import annotations

import json
from decimal import Decimal

import sqlalchemy as sa
from alembic import op

revision: str = "20260904_entitlement_snapshot"
down_revision: str | None = "20260904_operations_complete"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _json(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def upgrade() -> None:
    if "failed_count" not in _columns("client_message_campaign"):
        op.add_column(
            "client_message_campaign",
            sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        )
    if "cancelled_at" not in _columns("client_message_campaign"):
        op.add_column(
            "client_message_campaign",
            sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        )

    connection = op.get_bind()
    grant_table = sa.Table("credit_grant", sa.MetaData(), autoload_with=connection)
    margin = connection.execute(
        sa.text(
            "SELECT margin_baseline FROM pricing_standard_version "
            "WHERE status = 'published' AND is_deleted = false ORDER BY id DESC"
        )
    ).scalar()
    default_margin = Decimal(str(margin if margin is not None else 60))
    rows = connection.execute(
        sa.text(
            "SELECT g.id, g.source_type, g.source_id, c.plan_snapshot "
            "FROM credit_grant g LEFT JOIN subscription_cycle c "
            "ON g.source_type = 'subscription_cycle' AND g.source_id = c.id"
        )
    ).mappings()
    for row in rows:
        snapshot = _json(row["plan_snapshot"])
        rate = snapshot.get("credits_per_cost_yuan")
        if not rate and snapshot:
            credits = Decimal(str(snapshot.get("total_credits") or 0))
            price_fen = Decimal(
                str(snapshot.get("execution_price_fen") or snapshot.get("price_fen") or 0)
            )
            margin_rate = Decimal(str(snapshot.get("margin_rate") or default_margin))
            allowed_cost = price_fen / 100 * (Decimal(100) - margin_rate) / 100
            if credits > 0 and allowed_cost > 0:
                rate = credits / allowed_cost
        rate = Decimal(str(rate or 2500))
        account_type = "current_cycle" if row["source_type"] == "subscription_cycle" else "manual"
        normalized_snapshot = {
            **snapshot,
            "credits_per_cost_yuan": str(rate),
            "backfilled": True,
        }
        connection.execute(
            grant_table.update()
            .where(grant_table.c.id == row["id"])
            .values(
                credits_per_cost_yuan=rate,
                account_type=account_type,
                pricing_snapshot=normalized_snapshot,
            )
        )


def downgrade() -> None:
    columns = _columns("client_message_campaign")
    if "cancelled_at" in columns:
        op.drop_column("client_message_campaign", "cancelled_at")
    if "failed_count" in columns:
        op.drop_column("client_message_campaign", "failed_count")
