-- 1013调整：三种服务模式、用户当前模式、订单模式切换信息
-- PostgreSQL / public；对应 Alembic revision: 20261013_service_modes
-- 支持前置版本：20261010_duration_adjustment 或 20261010_merge_mobile_duration。
-- 自动补齐并核验手机号验证字段及唯一索引，再执行 1013 调整。
-- 与 Alembic upgrade 二选一；本文件成功后同步更新 alembic_version。
-- 请在运营端数据库中整份执行；执行前备份并暂停该服务的业务写入。
-- 重复执行、前置版本不符或结构冲突时会报错，整笔事务回滚。
-- 遇到错误请 ROLLBACK 并核对迁移状态，不要跳过检查或单独执行版本更新。
-- 新应用默认“均支持”；存量应用与用户保留原模式，不清空积分、不修改到期时间。
-- 不创建 billing_mode_preview 确认表；现有 duration_adjustment 表不重复创建。
-- 此文件仅生成并离线核对，未连接或执行任何实际数据库迁移。

BEGIN;
SET LOCAL search_path TO public;
SET LOCAL lock_timeout = '10s';

LOCK TABLE public.alembic_version IN EXCLUSIVE MODE;
DO $migration$
BEGIN
    IF (SELECT COUNT(*) FROM public.alembic_version) <> 1
       OR NOT EXISTS (
           SELECT 1 FROM public.alembic_version
           WHERE version_num IN ('20261010_duration_adjustment', '20261010_merge_mobile_duration')
       ) THEN
        RAISE EXCEPTION 'Expected revision 20261010_duration_adjustment or 20261010_merge_mobile_duration; verify migration state before running 1013.';
    END IF;
END
$migration$;

-- 补齐手机号身份分支。只增加验证时间字段，不回填旧手机号的验证状态。
-- 已手工添加过时校验结构；发现同名但不同定义的字段/索引则停止，不覆盖。
ALTER TABLE public.client_user
    ADD COLUMN IF NOT EXISTS mobile_verified_at TIMESTAMP WITH TIME ZONE;

DO $mobile_identity$
DECLARE
    index_id oid;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_attribute a
        WHERE a.attrelid = 'public.client_user'::regclass
          AND a.attname = 'mobile_verified_at' AND NOT a.attisdropped
          AND a.atttypid = 'timestamp with time zone'::regtype
          AND a.atttypmod IN (-1, 6) AND NOT a.attnotnull AND NOT a.atthasdef
    ) THEN
        RAISE EXCEPTION 'client_user.mobile_verified_at has an incompatible definition; expected nullable timestamptz without a default.';
    END IF;

    index_id := to_regclass('public.uq_client_user_verified_mobile');
    IF index_id IS NULL THEN
        CREATE UNIQUE INDEX uq_client_user_verified_mobile
            ON public.client_user (app_id, mobile)
            WHERE mobile_verified_at IS NOT NULL AND is_deleted = false;
        index_id := 'public.uq_client_user_verified_mobile'::regclass;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_index i
        JOIN pg_class c ON c.oid = i.indexrelid
        JOIN pg_am am ON am.oid = c.relam
        WHERE i.indexrelid = index_id
          AND i.indrelid = 'public.client_user'::regclass
          AND i.indisunique AND i.indisvalid AND i.indisready
          AND NOT i.indisprimary AND NOT i.indisexclusion
          AND i.indnkeyatts = 2 AND i.indnatts = 2
          AND i.indexprs IS NULL AND am.amname = 'btree'
          AND pg_get_indexdef(i.indexrelid, 1, true) = 'app_id'
          AND pg_get_indexdef(i.indexrelid, 2, true) = 'mobile'
          AND regexp_replace(pg_get_expr(i.indpred, i.indrelid), '[()[:space:]]', '', 'g')
              = 'mobile_verified_atISNOTNULLANDis_deleted=false'
    ) THEN
        RAISE EXCEPTION 'uq_client_user_verified_mobile has an incompatible definition; verify the existing index before migrating.';
    END IF;
END
$mobile_identity$;

-- 1013 调整：新增模式字段，保留已有应用与用户的原模式。
ALTER TABLE client_app ADD COLUMN service_mode VARCHAR(20) DEFAULT 'user_choice' NOT NULL;

UPDATE client_app SET service_mode = CASE WHEN platform_model_enabled THEN 'credits_only' ELSE 'duration_only' END;

ALTER TABLE client_user ADD COLUMN active_billing_mode VARCHAR(10);

ALTER TABLE client_user ADD COLUMN mode_version INTEGER DEFAULT '1' NOT NULL;

UPDATE client_user SET active_billing_mode = (SELECT CASE WHEN client_app.platform_model_enabled THEN 'credits' ELSE 'duration' END FROM client_app WHERE client_app.id = client_user.app_id);

ALTER TABLE payment_order ADD COLUMN mode_switch JSON;

-- 仅在以上全部成功时推进版本，与结构和回填在同一事务提交。
UPDATE public.alembic_version
SET version_num = '20261013_service_modes'
WHERE version_num IN ('20261010_duration_adjustment', '20261010_merge_mobile_duration');

COMMIT;

-- 执行后只读核对：目标版本、新应用默认值、存量模式分布。
SELECT version_num FROM public.alembic_version;
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'client_app'
  AND column_name = 'service_mode';
SELECT service_mode, COUNT(*) AS app_count FROM public.client_app GROUP BY service_mode;
SELECT active_billing_mode, COUNT(*) AS user_count FROM public.client_user GROUP BY active_billing_mode;
