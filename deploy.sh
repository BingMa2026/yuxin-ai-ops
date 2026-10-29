#!/usr/bin/env bash
# 防止旧全家桶脚本重建共享数据库和网关。
echo '旧部署入口已停用。运营端发布使用 deploy-production.ps1；公共 HTTPS 入口见 deploy/edge-nginx/README.md。' >&2
exit 2
