"""Audited manual subscription duration changes and operator permission."""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "20261010_duration_adjustment"
down_revision = "20261008_model_mode"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "duration_adjustment",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("uuid", sa.String(64), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_time", sa.DateTime(timezone=True)),
        *[sa.Column(field, sa.Integer(), sa.ForeignKey("sys_user.id", ondelete="SET NULL", onupdate="CASCADE")) for field in ("created_id", "updated_id", "deleted_id")],
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("client_user.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("subscription_id", sa.Integer(), sa.ForeignKey("subscription.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column("seconds_delta", sa.Integer(), nullable=False),
        sa.Column("before_expires_at", sa.DateTime(timezone=True)),
        sa.Column("after_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("operator_name", sa.String(150), nullable=False),
        sa.Column("cycle_changes", sa.JSON(), nullable=False),
        sa.UniqueConstraint("app_id", "idempotency_key", name="uq_duration_adjustment_request"),
    )
    for field in ("id", "uuid", "is_deleted", "created_time", "created_id", "updated_id", "deleted_id"):
        op.create_index(f"ix_duration_adjustment_{field}", "duration_adjustment", [field], unique=field == "uuid")
    op.create_index("ix_duration_adjustment_user", "duration_adjustment", ["app_id", "user_id", "created_time"])
    # Existing installations do not rerun navigation seeds. Add a button under
    # the existing user page; role assignment remains an explicit admin choice.
    permission = "workspace:user:management:duration"
    op.execute(
        sa.text("""
        INSERT INTO sys_menu
            (uuid, is_deleted, created_time, updated_time, name, type, "order", permission,
             title, status, scope, parent_id, hidden, keep_alive, always_show, affix,
             is_iframe, is_hide_tab, show_badge)
        SELECT :uuid, false, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, :name, 3, 4, :permission,
               :name, 0, 'web', parent.id, false, true, false, false, false, false, false
        FROM sys_menu parent
        WHERE parent.permission = 'workspace:user:management:list' AND parent.is_deleted = false
          AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE permission = :permission AND is_deleted = false)
        ORDER BY parent.id LIMIT 1
    """).bindparams(uuid=str(uuid4()), name="调整使用天数", permission=permission)
    )


def downgrade():
    raise RuntimeError("人工时长与审计记录需保留，请使用兼容版本回退应用代码")
