"""Repair release artifact schema on databases with pre-existing tables.

Revision ID: 20260904_release_artifact_fix
Revises: 20260904_platform_experience
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260904_release_artifact_fix"
down_revision: str | None = "20260904_platform_experience"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "signature_verified" not in _columns("client_app_release_artifact"):
        op.add_column(
            "client_app_release_artifact",
            sa.Column(
                "signature_verified",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    if "signature_verified" in _columns("client_app_release_artifact"):
        op.drop_column("client_app_release_artifact", "signature_verified")
