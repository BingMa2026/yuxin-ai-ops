import importlib
from io import StringIO

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations


@pytest.mark.parametrize("precreated", [False, True, "legacy_empty", "legacy_populated"])
def test_speech_migration_schema_roundtrip_and_price_backfill(test_client, precreated):
    from app.core.base_model import MappedBase

    migration = importlib.import_module("app.alembic.versions.20260913_speech_input")
    metadata = MappedBase.metadata
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.exec_driver_sql(
            "INSERT INTO client_app (id,uuid,code,name,status,registration_enabled,is_deleted,created_time,updated_time) VALUES (42,'app','existing','existing','active',1,0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
        )
        accounts = metadata.tables["model_provider_account"]
        account_id = connection.execute(
            accounts.insert().values(template_id=1, code="speech", name="speech", endpoint="https://dashscope.aliyuncs.com/compatible-mode/v1", settings_cipher="test-only")
        ).inserted_primary_key[0]
        catalog = metadata.tables["model_catalog"]
        model_id = connection.execute(catalog.insert().values(provider_account_id=account_id, provider_model_id="qwen3-asr-flash-realtime-2026-02-10", display_name="speech")).inserted_primary_key[0]
        if precreated in ("legacy_empty", "legacy_populated"):
            connection.exec_driver_sql("ALTER TABLE app_speech_config ADD COLUMN cost_per_minute NUMERIC(16,8)")
            if precreated == "legacy_populated":
                connection.execute(metadata.tables["app_speech_config"].insert().values(app_id=42, catalog_model_id=model_id))
                connection.exec_driver_sql("UPDATE app_speech_config SET cost_per_minute=0.25")
                with Operations.context(MigrationContext.configure(connection)), pytest.raises(RuntimeError, match="contain data"):
                    migration.upgrade()
                assert connection.exec_driver_sql("SELECT cost_per_minute FROM app_speech_config").scalar_one() == 0.25
                return
        if not precreated:
            metadata.tables["speech_usage"].drop(connection)
            metadata.tables["app_speech_config"].drop(connection)
            connection.exec_driver_sql("ALTER TABLE model_catalog DROP COLUMN speech_protocol")
            connection.exec_driver_sql("ALTER TABLE model_catalog DROP COLUMN speech_pricing")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()
        row = connection.execute(sa.select(catalog).where(catalog.c.id == model_id)).mappings().one()
        assert row["speech_protocol"] == "qwen_realtime" and row["speech_pricing"]["items"][0]["price"] == "0.00033"
        assert row["status"] == "inactive"
        assert connection.scalar(sa.select(sa.func.count()).select_from(metadata.tables["app_speech_config"])) == 0
        ctx = MigrationContext.configure(
            connection, opts={"include_object": lambda obj, name, kind, reflected, compare: name in {"model_catalog", "speech_usage", "app_speech_config"} if kind == "table" else True}
        )
        assert compare_metadata(ctx, metadata) == []
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert connection.exec_driver_sql("SELECT id FROM client_app WHERE id=42").scalar_one() == 42
    output = StringIO()
    with Operations.context(MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})):
        migration.upgrade()
    assert "ADD COLUMN speech_protocol" in output.getvalue()
    assert "CREATE TABLE speech_usage" in output.getvalue()
    engine.dispose()
