"""Complete client profile and rich-message experience.

Revision ID: 20260904_user_experience
Revises: 20260904_entitlement_snapshot
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260904_user_experience"
down_revision: str | None = "20260904_entitlement_snapshot"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "avatar" not in _columns("client_user"):
        op.add_column("client_user", sa.Column("avatar", sa.String(length=1000), nullable=True))

    for table in ("client_message_template", "client_message_campaign", "client_message_delivery"):
        if "content_type" not in _columns(table):
            op.add_column(
                table,
                sa.Column("content_type", sa.String(length=20), nullable=False, server_default="plain_text"),
            )

    if "timezone" not in _columns("client_message_campaign"):
        op.add_column(
            "client_message_campaign",
            sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Asia/Shanghai"),
        )


def downgrade() -> None:
    if "timezone" in _columns("client_message_campaign"):
        op.drop_column("client_message_campaign", "timezone")
    for table in ("client_message_delivery", "client_message_campaign", "client_message_template"):
        if "content_type" in _columns(table):
            op.drop_column(table, "content_type")
    if "avatar" in _columns("client_user"):
        op.drop_column("client_user", "avatar")
