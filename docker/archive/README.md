# 停用的上游与旧生产配置

此目录仅供历史参考，不是可运行的部署方案。文件已改为 `.disabled`，相对路径不再有效。

- `docker-compose.yaml.disabled`、`nginx.conf.disabled`、`env.legacy.example`：上游 MySQL 全家桶。
- `deploy.sh.disabled`：上游完整部署脚本，可能操作共享资源，不执行。
- `yuxin-ai-ops-api.conf.disabled`：原 IP 入口；已合并到 `deploy/edge-nginx` 的共享路由片段。

运营端生产入口只有 `docker/docker-compose.backend.yaml`。公共入口只有 `deploy/edge-nginx/compose.yaml`。
