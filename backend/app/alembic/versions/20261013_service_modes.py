"""Three application service modes, per-user mode and confirmed switching."""

import sqlalchemy as sa
from alembic import op

revision = "20261013_service_modes"
down_revision = "20261010_merge_mobile_duration"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("client_app", sa.Column("service_mode", sa.String(20), nullable=False, server_default="user_choice"))
    op.execute(sa.text("UPDATE client_app SET service_mode = CASE WHEN platform_model_enabled THEN 'credits_only' ELSE 'duration_only' END"))
    op.add_column("client_user", sa.Column("active_billing_mode", sa.String(10), nullable=True))
    op.add_column("client_user", sa.Column("mode_version", sa.Integer(), nullable=False, server_default="1"))
    op.execute(
        sa.text(
            "UPDATE client_user SET active_billing_mode = (SELECT CASE WHEN client_app.platform_model_enabled THEN 'credits' ELSE 'duration' END FROM client_app WHERE client_app.id = client_user.app_id)"
        )
    )
    op.add_column("payment_order", sa.Column("mode_switch", sa.JSON(), nullable=True))


def downgrade():
    raise RuntimeError("模式切换及权益审计不能自动回退，请使用兼容版本回退应用代码")
