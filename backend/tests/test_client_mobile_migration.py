"""Keep legacy profile numbers while enforcing unique verified mobile identities."""

import importlib

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_mobile_identity_migration_preserves_legacy_duplicates() -> None:
    migration = importlib.import_module("app.alembic.versions.20261009_client_mobile_identity")
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE client_user (id INTEGER PRIMARY KEY, app_id INTEGER NOT NULL, mobile VARCHAR(20), is_deleted BOOLEAN NOT NULL DEFAULT 0)")
        connection.exec_driver_sql("INSERT INTO client_user (id, app_id, mobile) VALUES (1, 7, '13800138000'), (2, 7, '13800138000')")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert connection.exec_driver_sql("SELECT count(*) FROM client_user").scalar_one() == 2
        connection.exec_driver_sql("UPDATE client_user SET mobile_verified_at = '2026-10-09' WHERE id = 1")
        with connection.begin_nested(), pytest.raises(sa.exc.IntegrityError):
            connection.exec_driver_sql("UPDATE client_user SET mobile_verified_at = '2026-10-09' WHERE id = 2")
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert "mobile_verified_at" not in {column["name"] for column in sa.inspect(connection).get_columns("client_user")}
        assert connection.exec_driver_sql("SELECT count(*) FROM client_user").scalar_one() == 2
    engine.dispose()
