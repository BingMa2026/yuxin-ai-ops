#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

release_id="${1:-}"
if [[ ! "$release_id" =~ ^[0-9a-f]{8,40}$ ]]; then
    echo "发布编号格式无效" >&2
    exit 2
fi
public_origin="${2:-https://www.yxciedu.com}"
if [[ ! "$public_origin" =~ ^https?://[A-Za-z0-9.-]+$ ]]; then
    echo "公网 Origin 格式无效" >&2
    exit 2
fi
public_host="${public_origin#*://}"
public_port=80
[[ "$public_origin" == https://* ]] && public_port=443

stack_root="/data/stacks/yuxin-ai-ops"
incoming_dir="${stack_root}/incoming/${release_id}"
release_dir="${stack_root}/releases/${release_id}"
source_archive="${incoming_dir}/yuxin-ai-ops-${release_id}.tar.gz"
web_archive="${incoming_dir}/yuxin-ai-ops-web-${release_id}.tar.gz"
checksums_file="${incoming_dir}/checksums.sha256"
environment_file="${stack_root}/docker/.env.backend"
export BACKEND_ENV_FILE="$environment_file"
compose_file="${release_dir}/docker/docker-compose.backend.yaml"
backup_dir="${stack_root}/backups"
web_root="/data/stacks/nginx/html"
web_link="${web_root}/web"

exec 9>"/var/lock/yuxin-ai-ops-deploy.lock"
if ! flock -n 9; then
    echo "已有运营端部署正在执行，请稍后重试" >&2
    exit 3
fi

for required_file in "$source_archive" "$web_archive" "$checksums_file" "$environment_file"; do
    if [[ ! -f "$required_file" ]]; then
        echo "缺少部署文件：$required_file" >&2
        exit 4
    fi
done

deployment_started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
previous_backend_image="$(docker inspect -f '{{.Config.Image}}' yuxin-ai-ops-backend 2>/dev/null || true)"
previous_backend_tag="${previous_backend_image##*:}"
previous_web_target="$(readlink "$web_link" 2>/dev/null || true)"
backend_switched=0
web_switched=0

rollback_on_error() {
    status=$?
    trap - ERR
    echo "部署失败，开始恢复上一应用版本..." >&2

    if [[ "$web_switched" == "1" && -n "$previous_web_target" ]]; then
        ln -sfn "$previous_web_target" "$web_link" || true
    fi

    if [[ "$backend_switched" == "1" && "$previous_backend_tag" =~ ^[A-Za-z0-9._-]+$ ]]; then
        (
            cd "${release_dir}/docker"
            BACKEND_IMAGE_TAG="$previous_backend_tag" docker compose \
                --env-file "$environment_file" \
                -f "$compose_file" \
                up -d --no-deps --force-recreate backend
        ) || true
    fi

    echo "数据库未自动回退；部署前备份保留在 ${backup_dir}" >&2
    exit "$status"
}
trap rollback_on_error ERR

echo "[1/8] 校验发布包"
(
    cd "$incoming_dir"
    sha256sum -c "$(basename "$checksums_file")"
)
# 同一提交重新构建时也可能产生不同的静态包，不能复用该提交的旧 Web 目录。
web_archive_hash="$(sha256sum "$web_archive" | cut -d ' ' -f 1)"
web_release_name="${release_id}-${web_archive_hash}"
web_release_dir="${web_root}/releases/yuxin-ai-ops/${web_release_name}"

if [[ -d "$release_dir" ]]; then
    if [[ ! -f "${release_dir}/.release-commit" ]] || [[ "$(<"${release_dir}/.release-commit")" != "$release_id" ]]; then
        echo "发布目录已存在但标记不一致：$release_dir" >&2
        exit 5
    fi
else
    release_stage="${release_dir}.preparing.$$"
    mkdir -p "$release_stage"
    tar -xzf "$source_archive" -C "$release_stage"
    printf '%s\n' "$release_id" >"${release_stage}/.release-commit"
    test -f "${release_stage}/docker/docker-compose.backend.yaml"
    mv "$release_stage" "$release_dir"
fi

echo "[2/8] 备份 PostgreSQL"
set -a
# shellcheck disable=SC1090
source "$environment_file"
set +a
for variable_name in DATABASE_USER DATABASE_PASSWORD DATABASE_NAME; do
    if [[ -z "${!variable_name:-}" ]]; then
        echo "环境文件缺少 ${variable_name}" >&2
        exit 6
    fi
done
mkdir -p "$backup_dir"
backup_file="${backup_dir}/yuxin_ai_ops_pre_${release_id}_$(date +%Y%m%d_%H%M%S).dump"
docker exec -e PGPASSWORD="$DATABASE_PASSWORD" shared-postgres \
    pg_dump -U "$DATABASE_USER" -d "$DATABASE_NAME" -Fc >"$backup_file"
test -s "$backup_file"
echo "数据库备份：$backup_file"

echo "[3/8] 构建后端镜像"
(
    cd "${release_dir}/docker"
    BACKEND_IMAGE_TAG="$release_id" docker compose \
        --env-file "$environment_file" \
        -f "$compose_file" \
        build backend
)

echo "[4/8] 执行 Alembic 迁移"
(
    cd "${release_dir}/docker"
    BACKEND_IMAGE_TAG="$release_id" docker compose \
        --env-file "$environment_file" \
        -f "$compose_file" \
        run --rm --no-deps backend python main.py upgrade --env=prod
)

echo "[5/8] 切换后端"
(
    cd "${release_dir}/docker"
    BACKEND_IMAGE_TAG="$release_id" docker compose \
        --env-file "$environment_file" \
        -f "$compose_file" \
        up -d --no-deps --force-recreate backend
)
backend_switched=1

backend_health=""
for _ in $(seq 1 30); do
    backend_health="$(docker inspect -f '{{.State.Health.Status}}' yuxin-ai-ops-backend 2>/dev/null || true)"
    echo "后端健康状态：${backend_health:-missing}"
    [[ "$backend_health" == "healthy" ]] && break
    [[ "$backend_health" == "unhealthy" ]] && break
    sleep 2
done
if [[ "$backend_health" != "healthy" ]]; then
    echo "新后端未通过健康检查" >&2
    exit 7
fi

echo "[6/8] 准备并切换 Web 前端"
if [[ -d "$web_release_dir" ]]; then
    if [[ ! -f "${web_release_dir}/.release-commit" ]] || [[ "$(<"${web_release_dir}/.release-commit")" != "$release_id" ]]; then
        echo "Web 发布目录已存在但标记不一致：$web_release_dir" >&2
        exit 8
    fi
else
    web_stage="${web_release_dir}.preparing.$$"
    mkdir -p "$web_stage"
    tar -xzf "$web_archive" -C "$web_stage"
    printf '%s\n' "$release_id" >"${web_stage}/.release-commit"
    test -s "${web_stage}/index.html"
    test -d "${web_stage}/js"
    mv "$web_stage" "$web_release_dir"
fi
ln -sfn "releases/yuxin-ai-ops/${web_release_name}" "$web_link"
web_switched=1

echo "[7/8] 验证公网入口"
# --resolve 同时验证 TLS SNI、证书域名和本机入口；不跳过证书校验。
curl --noproxy '*' --connect-timeout 5 --max-time 20 -fsS --resolve "${public_host}:${public_port}:127.0.0.1" "${public_origin}/api/v1/common/health/ready" >/dev/null
served_index_hash="$(curl --noproxy '*' --connect-timeout 5 --max-time 20 -fsS --resolve "${public_host}:${public_port}:127.0.0.1" "${public_origin}/web/" | sha256sum | cut -d ' ' -f 1)"
expected_index_hash="$(sha256sum "${web_release_dir}/index.html" | cut -d ' ' -f 1)"
if [[ "$served_index_hash" != "$expected_index_hash" ]]; then
    echo "公网 Web 入口与本次构建不一致" >&2
    false # 触发 ERR trap，恢复上一应用版本。
fi

echo "[8/8] 记录当前版本"
ln -sfn "releases/${release_id}" "${stack_root}/current"
docker inspect -f '后端镜像={{.Config.Image}} 状态={{.State.Status}} 健康={{.State.Health.Status}}' yuxin-ai-ops-backend
echo "Web 目录=$(readlink -f "$web_link")"
echo "部署完成：${release_id}"
echo "开始时间：${deployment_started_at}"
echo "数据库备份：${backup_file}"

trap - ERR
