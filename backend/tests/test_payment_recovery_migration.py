"""支付补查字段及交易号约束的迁移回归。"""

import importlib
from io import StringIO

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

from app.core.base_model import MappedBase


def test_payment_recovery_migration_roundtrip_and_postgres_ddl(test_client):
    migration = importlib.import_module("app.alembic.versions.20260928_payment_recovery")
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        MappedBase.metadata.create_all(connection)
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            old = inspect(connection)
            assert "next_query_at" not in {column["name"] for column in old.get_columns("payment_order")}
            migration.upgrade()
        current = inspect(connection)
        assert {"next_query_at", "query_attempts"} <= {column["name"] for column in current.get_columns("payment_order")}
        assert "uq_payment_order_provider_trade" in {item["name"] for item in current.get_unique_constraints("payment_order")}
        assert "ix_payment_order_recovery" in {item["name"] for item in current.get_indexes("payment_order")}
    engine.dispose()

    output = StringIO()
    with Operations.context(MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})):
        migration.upgrade()
    sql = output.getvalue()
    assert "ADD CONSTRAINT uq_payment_order_provider_trade" in sql
    assert "CREATE INDEX ix_payment_order_recovery" in sql
