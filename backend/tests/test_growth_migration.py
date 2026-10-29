"""Exercise the shipped migration against a separate in-memory database."""

import importlib
from io import StringIO

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

from app.core.base_model import MappedBase


def test_growth_migration_upgrade_matches_models_and_downgrades(test_client):
    migration = importlib.import_module("app.alembic.versions.20260907_growth_core")
    metadata = MappedBase.metadata
    growth = [table for table in metadata.tables.values() if table.name.startswith("growth_")]
    assert len(growth) == 16
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        metadata.create_all(connection)
        metadata.drop_all(connection, tables=growth)
        connection.execute(text("ALTER TABLE client_support_ticket DROP COLUMN value_grade"))
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()
        assert {t.name for t in growth} <= set(inspect(connection).get_table_names())
        assert "value_grade" in {c["name"] for c in inspect(connection).get_columns("client_support_ticket")}
        context = MigrationContext.configure(connection, opts={"include_object": lambda obj, name, kind, reflected, compare: name.startswith("growth_") if kind == "table" else True})
        assert compare_metadata(context, metadata) == []
        with Operations.context(context):
            migration.downgrade()
        assert not {t.name for t in growth} & set(inspect(connection).get_table_names())
        assert "value_grade" not in {c["name"] for c in inspect(connection).get_columns("client_support_ticket")}
    engine.dispose()


def test_growth_migration_compiles_for_postgresql():
    migration = importlib.import_module("app.alembic.versions.20260907_growth_core")
    output = StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        migration.upgrade()
    sql = output.getvalue()
    assert sql.count("CREATE TABLE growth_") == 16
    assert "ALTER TABLE client_support_ticket ADD COLUMN value_grade" in sql
    assert "NULLTYPE" not in sql


def test_migration_adopts_startup_created_tables_without_losing_rows(test_client):
    migration = importlib.import_module("app.alembic.versions.20260907_growth_core")
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        MappedBase.metadata.create_all(connection)
        connection.execute(MappedBase.metadata.tables["growth_profile"].insert().values(app_id=1, user_id=1, invite_code="MIGRATION123", usage_grade="R2"))
        connection.execute(text("ALTER TABLE growth_profile DROP COLUMN credit_debt"))
        connection.execute(text("ALTER TABLE growth_reward DROP COLUMN reversed_amount"))
        connection.execute(text("ALTER TABLE growth_cash_ledger DROP COLUMN frozen_delta"))
        connection.execute(text("ALTER TABLE growth_cash_ledger DROP COLUMN debt_delta"))
        connection.execute(text("ALTER TABLE growth_withdrawal DROP COLUMN confirmation_package"))
        connection.execute(text("ALTER TABLE growth_withdrawal DROP COLUMN next_attempt_at"))
        connection.execute(text("ALTER TABLE client_support_ticket DROP COLUMN value_grade"))
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()
            migration.upgrade()
        assert "credit_debt" in {c["name"] for c in inspect(connection).get_columns("growth_profile")}
        assert "value_grade" in {c["name"] for c in inspect(connection).get_columns("client_support_ticket")}
        assert connection.execute(text("SELECT invite_code, usage_grade, credit_debt FROM growth_profile")).one() == ("MIGRATION123", "R2", 0)
    engine.dispose()
