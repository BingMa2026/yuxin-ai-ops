"""enable the real operations overview menu

Revision ID: 20260904_operations_overview
Revises: 20260904_client_logo_fix
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260904_operations_overview"
down_revision: str | None = "20260904_client_logo_fix"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("sys_menu"):
        return
    bind.execute(
        sa.text(
            """
            UPDATE sys_menu
            SET name = '经营总览',
                title = '经营总览',
                component_path = 'module_operations/overview/index',
                hidden = false,
                status = 0
            WHERE route_name = 'OperationsOverview'
            """
        )
    )
    bind.execute(sa.text("UPDATE sys_menu SET hidden = true WHERE route_name = 'OpportunityResources'"))
    bind.execute(
        sa.text(
            """
            UPDATE sys_menu
            SET hidden = false,
                status = 0,
                redirect = '/operations/overview'
            WHERE route_name = 'OperationsCenter'
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("sys_menu"):
        return
    bind.execute(
        sa.text(
            """
            UPDATE sys_menu
            SET name = '模块概览',
                title = '模块概览',
                component_path = 'workspace/placeholder/index',
                hidden = true
            WHERE route_name = 'OperationsOverview'
            """
        )
    )
    bind.execute(sa.text("UPDATE sys_menu SET hidden = true WHERE route_name = 'OperationsCenter'"))
    bind.execute(sa.text("UPDATE sys_menu SET hidden = false WHERE route_name = 'OpportunityResources'"))
