import importlib.util
from io import StringIO
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_agreement_migration_preserves_existing_apps_and_round_trips():
    path = Path(__file__).parents[1] / "app/alembic/versions/20260911_agreements.py"
    spec = importlib.util.spec_from_file_location("agreement_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        for table in ("client_app", "sys_user", "client_user"):
            connection.exec_driver_sql(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO client_app (id) VALUES (42)")
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            inspector = sa.inspect(connection)
            assert {"client_agreement", "client_agreement_version", "client_agreement_scene", "client_agreement_acceptance"}.issubset(inspector.get_table_names())
            constraints = inspector.get_unique_constraints("client_agreement_version")
            assert any(c["column_names"] == ["app_id", "agreement_id", "version"] for c in constraints)
            assert connection.exec_driver_sql("SELECT id FROM client_app").scalar_one() == 42
            module.downgrade()
            assert "client_agreement" not in sa.inspect(connection).get_table_names()
            assert connection.exec_driver_sql("SELECT id FROM client_app").scalar_one() == 42
    engine.dispose()


@pytest.mark.parametrize("precreated", [False, True])
def test_agreement_migration_matches_models_and_postgres_ddl(test_client, precreated):
    import importlib

    from app.core.base_model import MappedBase

    migration = importlib.import_module("app.alembic.versions.20260911_agreements")
    metadata = MappedBase.metadata
    engine = sa.create_engine("sqlite:///:memory:")
    tables = [metadata.tables[name] for name in ("client_agreement_acceptance", "client_agreement_scene", "client_agreement_version", "client_agreement")]
    with engine.begin() as connection:
        metadata.create_all(connection)
        menu = metadata.tables["sys_menu"]
        parent_id = connection.execute(menu.insert().values(name="用户运营", route_name="UserOperations", route_path="/user-operations", type=1)).inserted_primary_key[0]
        if not precreated:
            for table in tables:
                table.drop(connection)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()
        page = connection.execute(sa.select(menu).where(menu.c.route_name == "AgreementManagement")).mappings().one()
        assert page["parent_id"] == parent_id
        assert page["type"] == 2 and page["component_path"] == "module_agreement/index"
        assert connection.scalar(sa.select(sa.func.count()).select_from(menu).where(menu.c.parent_id == page["id"])) == 4
        ctx = MigrationContext.configure(connection, opts={"include_object": lambda obj, name, kind, reflected, compare: name.startswith("client_agreement") if kind == "table" else True})
        assert compare_metadata(ctx, metadata) == []
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert connection.scalar(sa.select(menu.c.id).where(menu.c.id == parent_id)) == parent_id
        assert connection.scalar(sa.select(sa.func.count()).select_from(menu).where(menu.c.permission.like("workspace:user:agreement:%"))) == 0
    engine.dispose()
    output = StringIO()
    with Operations.context(MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})):
        migration.upgrade()
    assert output.getvalue().count("CREATE TABLE client_agreement") == 4


def test_agreement_migration_rejects_schema_drift():
    import importlib

    migration = importlib.import_module("app.alembic.versions.20260911_agreements")
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE client_agreement (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO client_agreement (id) VALUES (9)")
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="incompatible columns"):
                migration.upgrade()
        assert connection.exec_driver_sql("SELECT id FROM client_agreement").scalar_one() == 9
    engine.dispose()
