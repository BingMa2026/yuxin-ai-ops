-- PostgreSQL: 人工调整使用天数
-- 对应 Alembic revision: 20261010_duration_adjustment
-- 必需前置 revision: 20261008_model_mode
-- 如果 duration_adjustment 表已存在，改用 20261010_duration_adjustment_reconcile.sql。
-- 仅导出，未连接或修改数据库。
-- 与 Alembic upgrade 二选一，在运营端数据库中整份执行。
-- 版本不符、已执行或存在同名表时将报错，不覆盖已有数据。
-- 执行前备份；发生错误后 ROLLBACK 并核对状态，不跳过版本检查。

BEGIN;

LOCK TABLE alembic_version IN EXCLUSIVE MODE;

DO $migration$
BEGIN
    IF (SELECT COUNT(*) FROM alembic_version) <> 1
       OR NOT EXISTS (
           SELECT 1 FROM alembic_version
           WHERE version_num = '20261008_model_mode'
       ) THEN
        RAISE EXCEPTION
            'Expected Alembic revision 20261008_model_mode. Verify migration state before executing 20261010_duration_adjustment.';
    END IF;
END
$migration$;

-- 新建审计表及索引，并添加用户管理下的操作权限。
CREATE TABLE duration_adjustment (
    id SERIAL NOT NULL,
    uuid VARCHAR(64) NOT NULL,
    is_deleted BOOLEAN NOT NULL,
    created_time TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_time TIMESTAMP WITH TIME ZONE NOT NULL,
    deleted_time TIMESTAMP WITH TIME ZONE,
    created_id INTEGER,
    updated_id INTEGER,
    deleted_id INTEGER,
    app_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    subscription_id INTEGER NOT NULL,
    idempotency_key VARCHAR(100) NOT NULL,
    request_fingerprint VARCHAR(64) NOT NULL,
    direction VARCHAR(10) NOT NULL,
    days INTEGER NOT NULL,
    seconds_delta INTEGER NOT NULL,
    before_expires_at TIMESTAMP WITH TIME ZONE,
    after_expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    reason VARCHAR(500) NOT NULL,
    operator_name VARCHAR(150) NOT NULL,
    cycle_changes JSON NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_duration_adjustment_request UNIQUE (app_id, idempotency_key),
    FOREIGN KEY(created_id) REFERENCES sys_user (id) ON DELETE SET NULL ON UPDATE CASCADE,
    FOREIGN KEY(updated_id) REFERENCES sys_user (id) ON DELETE SET NULL ON UPDATE CASCADE,
    FOREIGN KEY(deleted_id) REFERENCES sys_user (id) ON DELETE SET NULL ON UPDATE CASCADE,
    FOREIGN KEY(app_id) REFERENCES client_app (id) ON DELETE RESTRICT,
    FOREIGN KEY(user_id) REFERENCES client_user (id) ON DELETE RESTRICT,
    FOREIGN KEY(subscription_id) REFERENCES subscription (id) ON DELETE RESTRICT
);

CREATE INDEX ix_duration_adjustment_id ON duration_adjustment (id);

CREATE UNIQUE INDEX ix_duration_adjustment_uuid ON duration_adjustment (uuid);

CREATE INDEX ix_duration_adjustment_is_deleted ON duration_adjustment (is_deleted);

CREATE INDEX ix_duration_adjustment_created_time ON duration_adjustment (created_time);

CREATE INDEX ix_duration_adjustment_created_id ON duration_adjustment (created_id);

CREATE INDEX ix_duration_adjustment_updated_id ON duration_adjustment (updated_id);

CREATE INDEX ix_duration_adjustment_deleted_id ON duration_adjustment (deleted_id);

CREATE INDEX ix_duration_adjustment_user ON duration_adjustment (app_id, user_id, created_time);

INSERT INTO sys_menu
            (uuid, is_deleted, created_time, updated_time, name, type, "order", permission,
             title, status, scope, parent_id, hidden, keep_alive, always_show, affix,
             is_iframe, is_hide_tab, show_badge)
        SELECT 'ab9c632b-6a45-4692-94d5-0040ca6b3904', false, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, '调整使用天数', 3, 4, 'workspace:user:management:duration',
               '调整使用天数', 0, 'web', parent.id, false, true, false, false, false, false, false
        FROM sys_menu parent
        WHERE parent.permission = 'workspace:user:management:list' AND parent.is_deleted = false
          AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE permission = 'workspace:user:management:duration' AND is_deleted = false)
        ORDER BY parent.id LIMIT 1;


-- 同步版本，防止以后执行 Alembic 时重复建表。
UPDATE alembic_version
SET version_num = '20261010_duration_adjustment'
WHERE version_num = '20261008_model_mode';

COMMIT;

-- 只读验证：迁移版本、审计表与新增权限。
SELECT version_num FROM alembic_version;
SELECT to_regclass('duration_adjustment') AS audit_table;
SELECT id, name, permission, parent_id
FROM sys_menu
WHERE permission = 'workspace:user:management:duration'
  AND is_deleted = false;

-- 普通运营角色需在角色管理中分配“调整使用天数”权限后重新登录。
