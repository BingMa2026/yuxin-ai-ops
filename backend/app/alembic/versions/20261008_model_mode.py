"""应用模型开关及可追溯的时长套餐。"""

import sqlalchemy as sa
from alembic import op

revision = "20261008_model_mode"
down_revision = "20260928_payment_recovery"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("client_app", sa.Column("platform_model_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("client_app", sa.Column("model_policy_version", sa.Integer(), nullable=False, server_default="1"))
    for table in ("pricing_plan_template", "app_catalog_plan", "subscription"):
        op.add_column(table, sa.Column("entitlement_kind", sa.String(20), nullable=False, server_default="credits"))


def downgrade():
    # A downgrade would reinterpret purchased duration as credits. Keep the
    # additive schema until duration assets have been explicitly reconciled.
    raise RuntimeError("存在时长权益后不可直接回退，请先完成权益核对并使用兼容版本")
