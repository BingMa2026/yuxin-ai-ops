"""客户端应用排序。

Revision ID: 20260903_client_app_order
Revises: 20260903_client_auth_events
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260903_client_app_order"
down_revision: str | None = "20260903_client_auth_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return inspector.has_table(table_name) and any(
        column["name"] == column_name for column in inspector.get_columns(table_name)
    )


def upgrade() -> None:
    if not _has_column("client_app", "order"):
        op.add_column(
            "client_app",
            sa.Column("order", sa.Integer(), nullable=False, server_default="999", comment="排序"),
        )


def downgrade() -> None:
    if _has_column("client_app", "order"):
        op.drop_column("client_app", "order")
