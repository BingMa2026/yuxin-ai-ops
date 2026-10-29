# HTTPS 上线记录

- 时间：2026-09-09，北京时间约 14:53 完成切换。
- 发布版本：`https-20260909-144129`。
- 正式域名：`https://www.yxciedu.com`。
- 运营端：`/web/`；运营 API：`/api/v1/`；官网 API：`/api/`；官网产品接口：`/product-api/`。

## 本次发布内容

官网前后端和运营后端均重新构建为本次版本镜像；运营前端按正式 `.env.production` 重新构建、类型检查并发布。公共 Nginx 使用现有 `nginx:1.30.4-alpine`，新增 443 端口和只读证书挂载。API 由公共入口直接转发到对应后端，官网 Nginx 仅提供静态资源。

运营端生产模式判断从 `prod` 修正为 `production`。构建顺序改为 Vite 先生成自动导入类型声明，再运行 vue-tsc，解决全新检出在声明文件不存在时无法构建的问题；任何构建或类型错误都会阻止发布。

运行环境文件：

- 官网：`/data/stacks/bid-website/.env`，与前端公开 `.env.production` 分开；旧服务器 `.env.production` 已存入受限备份。
- 运营后端：`/data/stacks/yuxin-ai-ops/docker/.env.backend`，统一注入运行参数。
- 官网源码：`/data/stacks/bid-website/current`；运营源码：`/data/stacks/yuxin-ai-ops/current`。
- 网关：`/data/stacks/nginx/compose.yaml`、`conf.d/yxciedu.conf`、`snippets/`。

保留了现有数据库、账号密码、JWT 密钥、Redis 和上传卷。共享 PostgreSQL、Redis 和另一套投标系统没有重启。迁移期仍保留旧 IP API，供桌面客户端升级；不向旧客户端强制返回 HTTPS 重定向。

## 来源与可追溯性

本次没有提交或推送 Git。使用已提交基线加明确列出的本次配置改动生成独立发布包，排除了工作区正在编辑的计费功能：

- 运营基线：`16a03e6663f1b37fde9f480856b4e028bc456377`。
- 官网基线：`a9cb8a1097802c947e2f166b81c8b673d08865c0`。
- 源码包 SHA-256：`cd7d1d0e566c3c169a9d6e8727ac42d3621a1929b03d74d8b202bcb954e59037`。
- 运营前端包 SHA-256：`c3f5c206a9633545080851ca741f85b8bbbdf8000d384391f5cea61f2f29ce0a`。

服务器 `/data/stacks/https-migration/https-20260909-144129` 保存源码包、校验和、源码覆盖清单、构建日志、一次性迁移脚本与 `APPLIED` 标记。说明文档在上线后补充，应用发布内容以该源码包和镜像标签为准。

## 验证结果

- 两份应用 Compose 和公共网关 Compose 校验通过。
- 本地实际 Nginx 的 21 项路由/HTTPS 用例通过，Linux 容器 `nginx -t` 通过。
- 运营后端 Ruff 通过，184 项测试通过；测试使用 SQLite/模拟 Redis。
- 运营前端 16 项测试通过，生产构建和类型检查通过。
- 官网前端 lint、类型检查、13 项测试及生产构建通过。
- 官网后端类型检查和 lint 通过；3 项集成测试在一次性隔离 PostgreSQL 中通过，测试容器/网络已清理。未在生产库中创建测试用户或预约。
- 官网 API 启动报告 `No pending migrations to apply`；历史 SQL 仅存在换行形式差异，内容一致，没有新增数据库迁移。
- 外网 HTTPS 证书校验通过；HTTP 返回 308 到正式 HTTPS 地址。
- 官网首页、运营登录页、注册页在浏览器正常渲染，已检查页面没有加载 HTTP 脚本/样式/图片，初始页面控制台无错误。
- 官网 bootstrap、运营 readiness、运营静态 favicon 分别返回 200；注册页实际收到无效邀请的业务 JSON/“邀请链接不存在”，验证了 /product-api 链路。

本次没有使用生产账号完成登录、上传或真实微信支付；生产认证业务仍需使用实际账号验收。隔离测试验证了官网登录及预约授权流程，HTTPS 不代替微信渠道开通。

## 备份与证书

备份目录：`/data/stacks/https-migration/https-20260909-144129/backup`。包含两个业务数据库 dump、原环境文件、原 Compose、网关配置、容器镜像 ID 和旧软链接；目录权限受限，不将其中内容放入 Git。

证书目录：`/data/nginx/yxciedu`。私钥权限已收紧到 600；证书有效至 **2026-12-08 08:59:59（北京时间）**。需在到期前续签并校验、reload。没有新建定时任务，也没有恢复旧独立 HTTPS/Let's Encrypt 配置。

