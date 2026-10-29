-- PostgreSQL：duration_adjustment 已存在时补齐权限及迁移记录。
-- 对照用户提供的 public.duration_adjustment DDL 制作；未连接数据库执行。
-- 替代 20261010_duration_adjustment.sql，不要再执行原建表脚本。
-- 允许版本 20261008_model_mode 或 20261010_duration_adjustment，可重复执行。
-- 不建表、不删表、不修改已有天数或调整记录、不自动给普通角色授权。
-- 在运营端数据库整份执行；若 SQL 窗口此前报错，先单独执行 ROLLBACK。
-- 任一校验失败即回滚整个事务，不要跳过校验直接修改迁移版本。

BEGIN;
SET LOCAL search_path TO public;
LOCK TABLE public.alembic_version IN EXCLUSIVE MODE;
LOCK TABLE public.duration_adjustment IN ACCESS SHARE MODE;
LOCK TABLE public.sys_menu IN SHARE ROW EXCLUSIVE MODE;

DO $migration$
BEGIN
    IF (SELECT COUNT(*) FROM public.alembic_version) <> 1
       OR NOT EXISTS (
           SELECT 1 FROM public.alembic_version
           WHERE version_num IN ('20261008_model_mode', '20261010_duration_adjustment')
       ) THEN
        RAISE EXCEPTION 'Unexpected migration version; check alembic_version before reconciliation.';
    END IF;

    -- 检查字段类型、长度及可空性；不依赖字段排列顺序。
    IF EXISTS (
        SELECT 1 FROM (VALUES
            ('app_id', 'integer', 'NO', NULL::integer),
            ('user_id', 'integer', 'NO', NULL),
            ('subscription_id', 'integer', 'NO', NULL),
            ('idempotency_key', 'character varying', 'NO', 100),
            ('request_fingerprint', 'character varying', 'NO', 64),
            ('direction', 'character varying', 'NO', 10),
            ('days', 'integer', 'NO', NULL),
            ('seconds_delta', 'integer', 'NO', NULL),
            ('before_expires_at', 'timestamp with time zone', 'YES', NULL),
            ('after_expires_at', 'timestamp with time zone', 'NO', NULL),
            ('reason', 'character varying', 'NO', 500),
            ('operator_name', 'character varying', 'NO', 150),
            ('cycle_changes', 'json', 'NO', NULL),
            ('id', 'integer', 'NO', NULL),
            ('uuid', 'character varying', 'NO', 64),
            ('is_deleted', 'boolean', 'NO', NULL),
            ('created_time', 'timestamp with time zone', 'NO', NULL),
            ('updated_time', 'timestamp with time zone', 'NO', NULL),
            ('deleted_time', 'timestamp with time zone', 'YES', NULL),
            ('created_id', 'integer', 'YES', NULL),
            ('updated_id', 'integer', 'YES', NULL),
            ('deleted_id', 'integer', 'YES', NULL)
        ) AS expected(column_name, data_type, is_nullable, max_length)
        LEFT JOIN information_schema.columns actual
          ON actual.table_schema = 'public'
         AND actual.table_name = 'duration_adjustment'
         AND actual.column_name = expected.column_name
        WHERE actual.column_name IS NULL
           OR actual.data_type <> expected.data_type
           OR actual.is_nullable <> expected.is_nullable
           OR actual.character_maximum_length IS DISTINCT FROM expected.max_length
    ) THEN
        RAISE EXCEPTION 'duration_adjustment columns do not match the migration; no changes applied.';
    END IF;

    IF pg_get_serial_sequence('public.duration_adjustment', 'id') IS NULL THEN
        RAISE EXCEPTION 'duration_adjustment.id sequence is missing.';
    END IF;

    -- 主键、请求唯一约束、外键及删除/更新规则。
    IF EXISTS (
        SELECT 1 FROM (VALUES
            ('PRIMARY KEY (id)'),
            ('UNIQUE (app_id, idempotency_key)'),
            ('FOREIGN KEY (app_id) REFERENCES client_app(id) ON DELETE RESTRICT'),
            ('FOREIGN KEY (user_id) REFERENCES client_user(id) ON DELETE RESTRICT'),
            ('FOREIGN KEY (subscription_id) REFERENCES subscription(id) ON DELETE RESTRICT'),
            ('FOREIGN KEY (created_id) REFERENCES sys_user(id) ON UPDATE CASCADE ON DELETE SET NULL'),
            ('FOREIGN KEY (updated_id) REFERENCES sys_user(id) ON UPDATE CASCADE ON DELETE SET NULL'),
            ('FOREIGN KEY (deleted_id) REFERENCES sys_user(id) ON UPDATE CASCADE ON DELETE SET NULL')
        ) AS expected(definition)
        WHERE NOT EXISTS (
            SELECT 1 FROM pg_constraint c
            WHERE c.conrelid = 'public.duration_adjustment'::regclass
              AND c.convalidated
              AND NOT c.condeferrable
              AND pg_get_constraintdef(c.oid) = expected.definition
        )
    ) THEN
        RAISE EXCEPTION 'duration_adjustment constraints do not match the migration.';
    END IF;

    IF EXISTS (
        SELECT 1 FROM (VALUES
            ('ix_duration_adjustment_id', 'id', false),
            ('ix_duration_adjustment_uuid', 'uuid', true),
            ('ix_duration_adjustment_is_deleted', 'is_deleted', false),
            ('ix_duration_adjustment_created_time', 'created_time', false),
            ('ix_duration_adjustment_created_id', 'created_id', false),
            ('ix_duration_adjustment_updated_id', 'updated_id', false),
            ('ix_duration_adjustment_deleted_id', 'deleted_id', false),
            ('ix_duration_adjustment_user', 'app_id, user_id, created_time', false)
        ) AS expected(index_name, columns, is_unique)
        WHERE NOT EXISTS (
            SELECT 1 FROM pg_index i
            WHERE i.indexrelid = to_regclass('public.' || expected.index_name)
              AND i.indrelid = 'public.duration_adjustment'::regclass
              AND i.indisvalid AND i.indisready
              AND i.indisunique = expected.is_unique
              AND pg_get_indexdef(i.indexrelid) =
                  'CREATE ' || CASE WHEN expected.is_unique THEN 'UNIQUE ' ELSE '' END ||
                  'INDEX ' || expected.index_name ||
                  ' ON public.duration_adjustment USING btree (' || expected.columns || ')'
        )
    ) THEN
        RAISE EXCEPTION 'duration_adjustment indexes do not match the migration.';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM public.sys_menu
        WHERE permission = 'workspace:user:management:list'
          AND scope = 'web' AND type = 2 AND is_deleted = false
    ) THEN
        RAISE EXCEPTION 'User management menu is missing; cannot attach duration permission.';
    END IF;
END
$migration$;

-- 已存在的权限保持原样；缺失时才添加。固定 UUID 仅用于该权限的首次创建。
INSERT INTO public.sys_menu
    (uuid, is_deleted, created_time, updated_time, name, type, "order", permission,
     title, status, scope, parent_id, hidden, keep_alive, always_show, affix,
     is_iframe, is_hide_tab, show_badge)
SELECT 'ab9c632b-6a45-4692-94d5-0040ca6b3904', false, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
       '调整使用天数', 3, 4, 'workspace:user:management:duration',
       '调整使用天数', 0, 'web', parent.id, false, true, false, false, false, false, false
FROM public.sys_menu parent
WHERE parent.permission = 'workspace:user:management:list'
  AND parent.scope = 'web' AND parent.type = 2 AND parent.is_deleted = false
  AND NOT EXISTS (
      SELECT 1 FROM public.sys_menu
      WHERE permission = 'workspace:user:management:duration' AND is_deleted = false
  )
ORDER BY parent.id LIMIT 1;

-- 已在目标版本时不重复更新；只允许从已验证的前置版本推进。
UPDATE public.alembic_version
SET version_num = '20261010_duration_adjustment'
WHERE version_num = '20261008_model_mode';

COMMIT;

-- 应返回目标版本，以及一条“调整使用天数”权限。
SELECT version_num FROM public.alembic_version;
SELECT id, name, permission, parent_id, status
FROM public.sys_menu
WHERE permission = 'workspace:user:management:duration' AND is_deleted = false;
