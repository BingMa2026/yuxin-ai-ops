-- PostgreSQL：修复迁移记录滞后，并升级平台模型开关与时长套餐
-- 适用状态：版本记录为 20260923_client_wechat_login，
-- 但 20260928_payment_recovery 的全部字段、约束和索引已实际存在。
-- 2026-10-09 已只读核对 yuxin_ai_ops / public 符合此状态。
-- 本文件仅生成，未执行数据库写入；执行时会重新验证，不依赖此前检查。
--
-- 在之前报错的 SQL 窗口先单独执行 ROLLBACK;，再整份执行本文件。
-- 执行前确认数据库和备份。本文件取代此次原升级脚本，无需两份都执行。
-- 任一检查失败时整笔事务不能提交，执行 ROLLBACK 后再排查。
-- 已完成本次升级后再次执行会拒绝，不会重复添加字段。

BEGIN;
SET LOCAL search_path TO public;
LOCK TABLE public.alembic_version IN EXCLUSIVE MODE;

DO $migration$
BEGIN
    IF (SELECT COUNT(*) FROM public.alembic_version) <> 1
       OR NOT EXISTS (
           SELECT 1 FROM public.alembic_version
           WHERE version_num = '20260923_client_wechat_login'
       ) THEN
        RAISE EXCEPTION 'Expected revision 20260923_client_wechat_login; verify current migration state.';
    END IF;

    -- 必须已经完整应用前置迁移的结构，才能同步它的版本记录。
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'payment_order'
          AND column_name = 'next_query_at'
          AND data_type = 'timestamp with time zone'
          AND is_nullable = 'YES' AND column_default IS NULL
    ) THEN
        RAISE EXCEPTION 'payment_order.next_query_at does not match payment recovery migration.';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'payment_order'
          AND column_name = 'query_attempts' AND data_type = 'integer'
          AND is_nullable = 'NO' AND column_default = '0'
    ) THEN
        RAISE EXCEPTION 'payment_order.query_attempts does not match payment recovery migration.';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint c
        JOIN pg_index i ON i.indexrelid = c.conindid
        WHERE c.conrelid = 'public.payment_order'::regclass
          AND c.conname = 'uq_payment_order_provider_trade'
          AND c.contype = 'u' AND c.convalidated
          AND i.indisvalid AND i.indisunique
          AND pg_get_constraintdef(c.oid) = 'UNIQUE (provider, provider_trade_no)'
    ) THEN
        RAISE EXCEPTION 'Payment provider trade unique constraint is absent or incompatible.';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_index i
        WHERE i.indexrelid = to_regclass('public.ix_payment_order_recovery')
          AND i.indrelid = 'public.payment_order'::regclass
          AND i.indisvalid AND NOT i.indisunique
          AND pg_get_indexdef(i.indexrelid) =
              'CREATE INDEX ix_payment_order_recovery ON public.payment_order USING btree (app_id, status, next_query_at)'
    ) THEN
        RAISE EXCEPTION 'Payment recovery index is absent or incompatible.';
    END IF;
END
$migration$;

-- 前置结构已验证。新增字段成功后，同一事务将版本记录推进到最终版本。
-- true：平台模型及现有积分规则；false：自配模型及订阅时长。
-- 旧应用默认 true，避免升级后自动改变现有收费模式。
ALTER TABLE client_app
    ADD COLUMN platform_model_enabled BOOLEAN DEFAULT true NOT NULL;

-- 模式配置版本，用于并发修改校验与客户端配置同步。
ALTER TABLE client_app
    ADD COLUMN model_policy_version INTEGER DEFAULT '1' NOT NULL;

-- credits：积分权益；duration：订阅时长权益。
-- 旧模板、旧刊例、旧订阅默认 credits，不自动转换历史资产。
ALTER TABLE pricing_plan_template
    ADD COLUMN entitlement_kind VARCHAR(20) DEFAULT 'credits' NOT NULL;

ALTER TABLE app_catalog_plan
    ADD COLUMN entitlement_kind VARCHAR(20) DEFAULT 'credits' NOT NULL;

ALTER TABLE subscription
    ADD COLUMN entitlement_kind VARCHAR(20) DEFAULT 'credits' NOT NULL;

-- 手动执行字段变更时同步迁移记录，防止后续 Alembic 重复加列。
UPDATE alembic_version
SET version_num = '20261008_model_mode'
WHERE version_num = '20260923_client_wechat_login';

COMMIT;

-- 只读验证：应返回本次新增的 5 个字段和新的迁移版本。
SELECT table_name, column_name, data_type, character_maximum_length,
       is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = current_schema()
  AND (
      (table_name = 'client_app'
       AND column_name IN ('platform_model_enabled', 'model_policy_version'))
      OR (table_name IN ('pricing_plan_template', 'app_catalog_plan', 'subscription')
          AND column_name = 'entitlement_kind')
  )
ORDER BY table_name, column_name;

SELECT version_num FROM alembic_version;
