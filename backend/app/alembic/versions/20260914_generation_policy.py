"""Explicit route generation policy and frozen per-call execution metadata."""

import sqlalchemy as sa
from alembic import op

revision = "20260914_generation_policy"
down_revision = "20260913_speech_input"
branch_labels = None
depends_on = None


def upgrade():
    # NULL is intentional: migration must not silently alter active routes or
    # invent a governed policy for historical usage.
    for table, name in (("app_model_route", "generation_settings"), ("model_usage", "execution_snapshot")):
        if not op.get_context().as_sql:
            existing = next((column for column in sa.inspect(op.get_bind()).get_columns(table) if column["name"] == name), None)
            if existing:
                if not isinstance(existing["type"], sa.JSON) or not existing["nullable"]:
                    raise RuntimeError("Unexpected generation policy column schema; explicit reconciliation required")
                continue
        op.add_column(table, sa.Column(name, sa.JSON(), nullable=True))


def downgrade():
    # Rolling schema back is not permission to erase governed call evidence.
    if not op.get_context().as_sql:
        bind = op.get_bind()
        if bind.scalar(sa.text("SELECT COUNT(*) FROM model_usage WHERE execution_snapshot IS NOT NULL")):
            raise RuntimeError("Generation execution evidence exists; restore a compatible backup for downgrade")
        if bind.scalar(sa.text("SELECT COUNT(*) FROM app_model_route WHERE generation_settings IS NOT NULL")):
            raise RuntimeError("Explicit generation settings exist; archive configuration before downgrade")
    op.drop_column("model_usage", "execution_snapshot")
    op.drop_column("app_model_route", "generation_settings")
