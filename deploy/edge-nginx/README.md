# 官网与运营端统一 HTTPS 入口

状态：2026-09-09 已上线。发布版本 `https-20260909-144129`，唯一公开域名为 `www.yxciedu.com`。本次实际构建、备份和验收记录见 [上线记录](DEPLOYED.md)。

## 配置归属

本目录是公共网关的唯一版本来源，发布到 `/data/stacks/nginx`。官网仓库不再维护第二份 API 路由；运营端发布脚本不自动修改共享网关。

| 路径 | 目标 |
| --- | --- |
| / | bid-web:80，只负责官网页面 |
| /api/ | bid-website-api:3001，保留路径 |
| /product-api/ | yuxin-ai-ops-backend:8001，转换为 /api/v1/ |
| /web/ | 网关挂载的 html/web，支持 SPA 刷新 |
| /api/v1/ | yuxin-ai-ops-backend:8001，普通 API 去掉前缀 |
| /api/v1/static/ | 同一运营后端，保留静态路径前缀 |

`conf.d/yxciedu.conf` 负责唯一域名和路由，`snippets/operations.conf` 复用于正式域名和旧 IP 入口，`snippets/proxy.conf` 统一转发头。包含关系只抽取真正共享部分，不再层层代理 API。

证书只读挂载服务器 `/data/nginx/yxciedu`。2026-09-09 检查的证书覆盖 www 与根域，2026-12-08 08:59:59（北京时间）到期；不复制私钥进仓库。更新证书后先校验证书链、域名、私钥匹配和 `nginx -t`，再 reload 网关。旧的 Let's Encrypt 定时器不适用于这张证书，续签由证书签发方流程负责。

网关是公网第一跳，覆盖外部传入的转发头。后端只在内网监听；Uvicorn 的信任范围按实际 `proxy_network` 网段配置，当前为 `172.19.0.0/16`。网络不重建，数据库不迁移。

## 本次需要更新哪些服务

| 服务 | 修改 | 发布动作 |
| --- | --- | --- |
| 公共 edge-nginx | 443 映射、证书挂载、统一路由 | 首次必须重建容器，单独 reload 不能增加端口/挂载 |
| 官网 web | 移除内层 API 代理 | 构建新 web 镜像并更新容器；React 地址逻辑不变 |
| 官网 api | WEB_ORIGIN、HTTPS Cookie、代理信任、代理网络及唯一别名 | 本次重新构建并部署 API 镜像 |
| 运营 backend | 域名白名单、公开链接、转发头信任、统一 env 注入 | 本次重新构建并部署后端镜像 |
| 运营前端 | 正式 .env.production、生产模式与构建顺序 | 本次重新构建、类型检查并发布静态文件 |
| PostgreSQL / Redis / 另一套投标系统 | 无 | 不操作 |

“改 env 后生效”需要 Compose `up -d` 重建对应容器，`docker restart` 不会重新加载 Compose 环境配置。前端 Vite 变量是构建时配置，未来如改变它们仍需重新构建。

## 首次上线顺序

以下操作仅在批准线上切换后执行。预计共享入口容器重建有短暂中断，不承诺零停机。

1. 记录当前镜像 ID/标签、容器 Compose 路径、运营端 web 软链接。备份网关整个配置目录（含 compose、conf.d、snippets，如存在）、官网 Compose、两个后端环境文件。备份留在服务器且权限受限；不把真实环境文件拷回 Git。
2. 将官网与运营端需要的运行参数合并到各自现有环境文件。官网保留原 BID_DB_* 和 JWT_ACCESS_SECRET，新增 API_IMAGE 为当前 API 镜像、WEB_IMAGE 为新 web 标签、WEB_ORIGIN=https://www.yxciedu.com。不要换数据库用户、密码或 JWT。
3. 运营端环境文件追加示例中的 HTTPS 参数，核对并保留已有短信、支付、OAuth 配置；域名白名单必须包含 www、旧 IP 和健康检查主机。支付回调等渠道参数按已开通的配置迁移，HTTPS 接通不等于微信渠道开通。
4. 核实 `docker network inspect proxy_network`、`shared_backend`，证书链/域名/到期时间/私钥匹配，以及服务器防火墙与云安全组允许 TCP 443。不重建现有网络。
5. 从已确认源码构建官网 web/API 和运营后端镜像，构建并检查运营前端，先不替换运行容器。校验两份应用 Compose。官网 api 使用本次镜像标签执行 `up -d --no-deps --no-build api`，并验证内部就绪接口。API 启动命令自带 Prisma migrate deploy，本次确认没有新增迁移。
6. 运营后端使用本次镜像标签和新 Compose 执行 `up -d --no-deps --no-build backend`，健康后验证旧 IP API 仍正常。旧网关使用静态 DNS 解析，后端容器替换后先通过 nginx -t 再 reload；新网关已使用 Docker DNS 动态解析。
7. 将本目录 compose、conf.d、snippets 写入网关准备目录。使用临时 `nginx:1.30.4-alpine` 容器挂载准备配置和证书做 `nginx -t`，不发布端口、不修改运行网关；生产私钥不打印。确认后将当前生效的 default.conf、www.yxciedu.com.conf、yuxin-ai-ops-api.conf 移入备份目录，不能把新旧入口同时放在 conf.d。
8. 替换网关配置并执行 `docker compose -f /data/stacks/nginx/compose.yaml up -d --no-deps nginx`。先启用直连 API 的新入口，再更新官网 web，避免旧入口把 API 转发到已经移除代理的 web。
9. 检查 HTTPS 官网/API/运营页面均正常后，以新 WEB_IMAGE 执行官网 `up -d --no-deps --no-build web`，并原子切换运营前端 web 软链接到新构建目录。再次完成下面的外网验收。
10. 历史 `/data/stacks/bid-website/deploy/https-compose.yml`、旧 `https.conf` 与 Let's Encrypt 配置移入停用归档；不启动独立 HTTPS 容器、不恢复旧续期定时器。应用发布以后只使用各自规范化的生产 Compose。

官网每次 Compose 命令必须显式使用 `--env-file /data/stacks/bid-website/.env -f /data/stacks/bid-website/docker-compose.prod.yml`。运营端使用 `--env-file /data/stacks/yuxin-ai-ops/docker/.env.backend -f <批准版本>/docker/docker-compose.backend.yaml`，并设置当前 BACKEND_IMAGE_TAG；BACKEND_ENV_FILE 默认已指向固定服务器路径。不要使用批量 `down`、`--remove-orphans` 或清理共享卷。

## 验收

- HTTPS 真实证书校验通过；不使用 `curl -k`。HTTP www 的 GET/POST 应保持 URI 并 308 到 HTTPS。
- 官网页面、官网 API bootstrap、官网管理登录与 Cookie 刷新、退出。
- 运营端 /web/、深层路由刷新、登录、API、上传/下载/头像，以及需要的 WebSocket/SSE。
- 邀请注册链接是 HTTPS；无效邀请、清空邀请后的普通注册按现有规则工作。
- /api/v1/ 不落入官网 /api/；/product-api/ 保留查询参数，且不把官网刷新 Cookie 转给运营后端。
- 旧 IP /api/v1/ 保留到客户端完成升级，避免 Electron 拒绝重定向导致旧客户端无法登录。
- 页面与返回的文件 URL 没有混合 HTTP 内容。既有数据库中如存在绝对 HTTP 链接，单独确认迁移范围，不能批量盲改。

## 回滚

首先恢复旧官网 web 镜像（其中包含旧 API 代理），待 web 健康后恢复运营前端旧软链接、网关旧 Compose/conf.d/挂载并重建网关容器。然后按需恢复官网 API 和运营后端的原 Compose、原环境文件、原镜像并重建相应容器，恢复 current 链接；旧网关重新 reload 以刷新后端地址。数据库不自动回退。

## 本地验证

`scripts/verify-edge-nginx.py` 启动临时本机 Nginx 和两个模拟 API，使用临时自签证书验证真实代理行为。只替换测试端口、容器主机名和挂载路径；不使用生产证书、不连接线上服务。运行后关闭测试进程。

```powershell
backend/.venv/Scripts/python.exe scripts/verify-edge-nginx.py --nginx <nginx.exe> --openssl <openssl.exe> --website ../Bid-product-website
```

覆盖 API 优先级、路径/查询参数、静态资源前缀、HTTPS 转发头、Cookie 隔离、SPA 刷新、域名跳转、旧 IP 兼容和官网容器 API 404。
