-- PostgreSQL：平台模型开关与时长套餐升级
-- 对应 Alembic revision：20261008_model_mode
-- 必需前置 revision：20260928_payment_recovery
-- 仅生成脚本，未连接或修改数据库。
--
-- 执行前确认连接的是运营端数据库，并完成备份。
-- 本文件与 Alembic upgrade 是两种替代执行方式，选择其一。
-- 请整份执行：字段变更和 Alembic 版本记录在同一事务提交。
-- 若已有部分字段、版本不符或已执行本迁移，脚本会报错而不覆盖现有配置。
-- 发生错误后执行 ROLLBACK，再核对数据库状态；不要单独跳过版本检查。

BEGIN;

-- 同时保护迁移版本检查与版本更新。
LOCK TABLE alembic_version IN EXCLUSIVE MODE;

DO $migration$
BEGIN
    IF (SELECT COUNT(*) FROM alembic_version) <> 1
       OR NOT EXISTS (
           SELECT 1 FROM alembic_version
           WHERE version_num = '20260928_payment_recovery'
       ) THEN
        RAISE EXCEPTION
            'Expected Alembic revision 20260928_payment_recovery. Verify migration state before executing 20261008_model_mode.';
    END IF;
END
$migration$;

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
WHERE version_num = '20260928_payment_recovery';

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
