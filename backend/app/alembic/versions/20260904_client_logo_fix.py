"""Repair the built-in client logo URL for the web base path.

Revision ID: 20260904_client_logo_fix
Revises: 20260904_release_artifact_fix
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260904_client_logo_fix"
down_revision: str | None = "20260904_release_artifact_fix"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            """
            UPDATE client_app
            SET logo = '/web/logo.png', updated_time = NOW()
            WHERE code = 'bid_agent'
              AND (logo IS NULL OR logo = '' OR logo = '/logo.png')
            """
        )
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            """
            UPDATE client_app
            SET logo = '/logo.png', updated_time = NOW()
            WHERE code = 'bid_agent' AND logo = '/web/logo.png'
            """
        )
    )
