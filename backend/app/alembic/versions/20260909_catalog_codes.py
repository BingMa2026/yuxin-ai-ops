"""Allow deleted catalog codes to be reused without changing historical rows."""

import sqlalchemy as sa
from alembic import op

revision = "20260909_catalog_codes"
down_revision = "20260907_growth_core"
branch_labels = None
depends_on = None

TABLE = "app_catalog_plan"
UNIQUE = "uq_app_catalog_plan_app_code"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(TABLE):
        return
    if UNIQUE in {c["name"] for c in inspector.get_unique_constraints(TABLE)}:
        with op.batch_alter_table(TABLE) as batch:
            batch.drop_constraint(UNIQUE, type_="unique")
    if UNIQUE not in {index["name"] for index in sa.inspect(bind).get_indexes(TABLE)}:
        op.create_index(UNIQUE, TABLE, ["app_id", "code"], unique=True, postgresql_where=sa.text("is_deleted = false"), sqlite_where=sa.text("is_deleted = 0"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(TABLE):
        return
    if bind.execute(sa.text("SELECT 1 FROM app_catalog_plan GROUP BY app_id, code HAVING COUNT(*) > 1 LIMIT 1")).first():
        raise RuntimeError("存在含历史记录的重复编码，不能恢复旧唯一约束；请先处理重复编码")
    if UNIQUE in {index["name"] for index in inspector.get_indexes(TABLE)}:
        op.drop_index(UNIQUE, table_name=TABLE)
    if UNIQUE not in {constraint["name"] for constraint in sa.inspect(bind).get_unique_constraints(TABLE)}:
        with op.batch_alter_table(TABLE) as batch:
            batch.create_unique_constraint(UNIQUE, ["app_id", "code"])
