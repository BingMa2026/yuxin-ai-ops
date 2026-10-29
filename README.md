# 喻信 AI 招投标产品运营端

客户端业务模型由 `GET /api/v1/client/model/config` 下发。每条文档理解、语义审查路由需开启 `allow_user_model`，客户端才可从 `user_selectable` 模型中选择业务模型。运行接口接受可选 `thinking` 布尔值；旧版业务路由将受支持 Qwen 3.8 模型的思考开关原样转发，文本与图片使用相同的业务路径和现有用量结算。显式生成策略仍以运营端配置的预算为上限，客户端不能增加预算。模型绑定、供应商密钥和积分结算仍由运营端控制。

供应商模型目录按协议区分调用 ID 与显示名称：OpenAI 兼容和 Anthropic 接口优先使用 `id`，Gemini 使用 `name` 并移除 `models/` 前缀。例如腾讯 TokenHub 的 `Hy4 preview` 是显示名称，实际调用 ID 为 `hy4-preview`。供应商“连接正常”表示模型列表可访问，启用业务路由后仍需验证实际对话。已误用显示名称的目录记录需同步更正上游 ID，并保留原有客户端授权和业务路由。

`yuxin-ai-ops` 是喻信招投标智能体产品的内部运营管理平台，用于承载账号、角色与权限、系统配置、运营数据及后续招投标业务管理能力。

项目基于 [FastApiAdmin](https://github.com/fastapiadmin/FastapiAdmin) 3.0 二次开发，保留其 FastAPI + Vue 3 的基础能力。新业务以喻信产品需求为准，上游演示模块不代表已经规划或交付的喻信功能。

## 当前约束

邀请注册链接由后端 `GROWTH_INVITE_BASE_URL` 配置生成。生产环境使用 `https://www.yxciedu.com`，与微信收款页 `GROWTH_PUBLIC_BASE_URL` 统一域名；真实生产参数统一保存在服务器 `.env.backend`。2026-09-09 已完成 HTTPS 上线，配置归属与回滚见 [公共入口说明](deploy/edge-nginx/README.md)。

微信网站应用扫码登录与 Native 收款的配置、发布顺序和验收步骤见[微信接入说明](docs/wechat-integration.md)。

- 运营主体按单团队设计，默认名称为“喻信运营团队”。
- 桌面端是独立项目，通过本后端完成登录并使用运营 API。
- 当前线上同时部署后端和 Web 运营界面，Web 使用 `/web/`。
- 登录验证码已按现阶段产品要求关闭。
- 线上 PostgreSQL、Redis 和 Nginx 是共享资源，部署本项目时不能影响服务器上的其他服务。

## 技术架构

| 部分 | 技术 |
| --- | --- |
| Web 运营端 | Vue 3、TypeScript、Vite、Pinia、Vue Router、Element Plus、Tailwind CSS v4 |
| 后端 | Python 3.12+、FastAPI、Pydantic v2、SQLAlchemy 2、Alembic |
| 数据与缓存 | PostgreSQL、Redis |
| 测试与质量 | Vitest、vue-tsc、pytest、Ruff |
| 部署 | Docker、Docker Compose、Nginx |

```text
yuxin-ai-ops/
├─ backend/          FastAPI 后端与数据库迁移
├─ frontend/
│  ├─ web/           运营后台，当前主要前端交付物
│  ├─ app/           上游 UniApp 工程，当前非主要交付物
│  └─ docs/          上游文档站，当前非主要交付物
├─ docker/           后端镜像、Compose 与 Nginx 配置
├─ AGENTS.md         全仓 AI 协作规则
└─ README.md         项目入口文档
```

## 本地开发

### 环境要求

- Python 3.12+
- uv
- Node.js 20+
- pnpm 9
- 可访问配置文件指定的 PostgreSQL 和 Redis

### 启动后端

后端开发配置来自 `backend/env/.env.dev`。本机没有数据库或 Redis 时，该文件可以连接已获授权的远程开发资源，但不要把真实密码提交到 Git。

```powershell
cd backend
uv sync
uv run main.py run --env=dev
```

默认监听 `localhost:8001`；实际值以 `.env.dev` 为准。常用入口：

- API：`http://localhost:8001/api/v1`
- Swagger：`http://localhost:8001/docs`
- 就绪检查：`http://localhost:8001/common/health/ready`

### 启动 Web 运营端

```powershell
cd frontend/web
pnpm install --frozen-lockfile
pnpm dev
```

通用公开配置位于 `frontend/web/.env`，开发环境覆盖可参考 `.env.development.example`。Vite 当前默认端口为 `5180`，最终访问地址以启动输出为准。

## 模型服务模式与时长套餐

客户端管理支持“启用平台模型服务”：开启沿用平台积分计费，关闭允许客户端自配模型并购买使用天数。数据库迁移、运营操作、兼容边界和客户端接口见 [实施说明](docs/模型服务开关与时长套餐-实施说明.md)。

时长模式支持在“用户运营 → 用户管理 → 调天数”中人工开通、增加或扣减天数，保留操作审计。启用前需执行 `20261010_duration_adjustment` 迁移，并为运营角色分配“调整使用天数”权限；具体规则见实施说明第 9 节。

## 开发检查

Web 运营端：

```powershell
cd frontend/web
pnpm type-check
pnpm test
pnpm build
```

后端：

```powershell
cd backend
uv run ruff check .
uv run pytest -q
```

数据库模型发生变化时，使用 Alembic 生成并应用迁移：

```powershell
cd backend
uv run main.py revision --env=dev
uv run main.py upgrade --env=dev
```

执行迁移前务必确认 `.env.dev` 指向的目标数据库，禁止在不明确的远程环境上试运行破坏性迁移。

## 环境文件

| 文件 | 用途 | 是否可包含真实密钥 |
| --- | --- | --- |
| `backend/env/.env.example` | 后端配置模板 | 否 |
| `backend/env/.env.dev` | 本地开发后端配置 | 可以，但不得提交 |
| `backend/env/.env.test` | 自动测试配置 | 仅测试值 |
| `/data/stacks/yuxin-ai-ops/docker/.env.backend` | Docker 生产后端唯一运行环境文件 | 可以，但不得提交 |
| `backend/env/.env.prod` | 非 Docker 直接运行时的环境文件，不打入生产镜像 | 可以，但不得提交 |
| `frontend/web/.env` | Web 公共 Vite 配置 | 只能放浏览器可公开值 |
| `frontend/web/.env.*.example` | Web 环境示例 | 否 |

任何 `VITE_*` 值都会进入浏览器构建产物，不能存放数据库密码、Redis 密码、JWT 密钥或第三方私钥。

## 生产部署

运营端地址为 `https://www.yxciedu.com/web/`，API 为同域名 `/api/v1/`；旧 IP API 在客户端迁移期保留。后端只使用 `docker/docker-compose.backend.yaml`，连接服务器已有的共享 PostgreSQL、Redis 和 Nginx 网络。公共入口唯一配置位于 `deploy/edge-nginx`，独立于应用发布。

完成代码修改后，先提交并推送 `main`，然后在仓库根目录执行：

```powershell
.\deploy-production.ps1
```

脚本会依次完成：

1. 确认当前分支为 `main`、工作区无未提交内容，且本地 `HEAD` 与 `origin/main` 完全一致。
2. 执行后端 Ruff 和 pytest，以及前端类型检查、测试和生产构建。
3. 前端构建到独立临时目录，按当前 Git 提交号生成并校验后端源码包和本次 Web 静态包，不复用本地 `dist`。
4. 上传发布包，备份线上 PostgreSQL，并执行 Alembic 升级。
5. 仅重建 `yuxin-ai-ops-backend`，不会重建共享 PostgreSQL、Redis、Nginx 或其他业务容器。
6. 后端健康后原子切换 `/web`，再验证公网 API 和页面入口内容与本次构建一致。Web 目录按提交号与静态包 SHA256 区分，同一提交重新发布也会使用对应的新产物。
7. 发布失败时恢复上一后端镜像和 Web 软链接；数据库不会自动降级，部署前备份会保留在服务器。

默认菜单和工作台模块只在首次初始化（尚无运营账号和菜单记录）时导入。已有系统在部署或重启后保留后台维护的菜单删除、移动、所属模块、名称、排序及显示状态，不再按种子配置恢复；即使菜单已全部清空，也不会重新导入。后续新增功能菜单或组件路径调整应通过明确的一次性 Alembic 迁移交付，不依赖每次启动重新校准。`-SkipChecks` 不影响这一规则。

本机已使用独立部署密钥 `~/.ssh/yuxin_ai_ops_deploy_ed25519`。不要把服务器密码、私钥或生产环境文件提交到仓库。首次在其他电脑部署时，需要先配置对应 SSH 公钥，也可以显式指定密钥：

```powershell
.\deploy-production.ps1 -IdentityFile "D:\secure\yuxin-ai-ops-deploy"
```

紧急情况下可以使用 `-SkipChecks` 跳过测试和静态检查，但前端生产构建、数据库备份、迁移和健康检查仍会执行：

```powershell
.\deploy-production.ps1 -SkipChecks
```

生产脚本位于 `deploy-production.ps1`，服务器执行逻辑位于 `scripts/deploy-release.sh`。默认按 HTTPS 域名校验，SSH 地址由 `-Server` 设置；首次切换前可用 `-PublicOrigin http://119.45.121.36`。旧 `deploy.sh` 已停用，上游配置归档到 `docker/archive`。配置来源与环境变量规则见 [Docker 说明](docker/README.md)。

## AI 协作说明

协议维护、场景配置、客户端读取接口及上线顺序见 [协议与政策](docs/协议与政策.md)。

- 根目录 [AGENTS.md](./AGENTS.md) 描述产品定位、跨端契约、安全和发布边界。
- [frontend/web/AGENTS.md](./frontend/web/AGENTS.md) 描述 Vue、交互、浅色/深色主题和前端验证规则。
- [backend/AGENTS.md](./backend/AGENTS.md) 描述 FastAPI 分层、数据迁移、安全和后端测试规则。

从仓库根目录启动 AI 编码任务时，根规则会要求代理在修改对应子项目之前继续读取子目录规则。

## 上游与许可

本项目基于 FastApiAdmin 二次开发，继续遵循仓库中的 [MIT License](./LICENSE)。`README.en.md`、部分演示页面和文档仍保留上游内容，仅作为技术参考，不是喻信项目需求的事实来源。


客户端聊天语音输入的运营配置、计费口径和接口约定见 [语音输入说明](docs/speech-input.md)。
