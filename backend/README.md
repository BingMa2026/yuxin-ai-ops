# 喻信运营管理平台 - 后端

基于 FastAPI 框架构建的企业级后端架构，为前端 Vue3 管理系统提供完整的 API 服务支持。

> **与仓库根文档的关系**：项目总览、一键前后端启动、演示账号、Docker 部署、架构图与默认端口等请以 [根目录 README.md](../README.md) 为准；**本文档**侧重 `backend/` 目录结构、迁移命令与后端开发约定。

## 技术栈

| 技术 | 版本 | 说明 |
|------|------|------|
| FastAPI | 0.115.2 | 现代 Web 框架 |
| SQLAlchemy | 2.0.36 | ORM 框架 |
| Alembic | 1.15.1 | 数据库迁移工具 |
| Pydantic | 2.x | 数据验证与序列化 |
| APScheduler | 3.11.0 | 定时任务调度 |
| Redis | 5.2.1 | 缓存与会话存储 |
| Uvicorn | 0.30.6 | ASGI 服务器 |
| Python | 3.12+ | 运行环境 |

## 项目结构

```txt
backend/
├── app/                     # 项目核心代码
│   ├── alembic/             # 数据库迁移管理
│   ├── api/                 # API 接口模块
│   │   └── v1/              # API v1 版本
│   │       ├── module_system/   # 系统管理模块
│   │       ├── module_monitor/  # 系统监控模块
│   │       └── module_*/       # 其他业务模块
│   ├── common/              # 公共组件（常量、枚举、响应封装）
│   ├── config/              # 项目配置文件
│   ├── core/                # 核心模块（数据库、中间件、安全）
│   ├── module_task/         # 定时任务模块
│   ├── plugin/              # 插件模块（二开目录）
│   ├── scripts/             # 初始化脚本和数据
│   └── utils/               # 公共工具
├── env/                     # 环境配置文件
├── logs/                    # 日志输出目录
├── sql/                     # SQL 初始化脚本
├── static/                  # 静态资源文件
├── main.py                  # 项目启动入口
├── alembic.ini              # Alembic 迁移配置
├── requirements.txt         # Python 依赖包
└── pyproject.toml           # 项目配置（uv / ruff）
```

### 模块分层

每个业务模块采用统一的分层结构：

```txt
module_*/
├── controller.py    # 控制器 - HTTP 请求处理
├── service.py       # 服务层 - 业务逻辑处理
├── crud.py          # 数据层 - 数据库操作
├── model.py         # ORM 模型 - 数据库表定义
├── schema.py        # Pydantic 模型 - 数据验证
└── param.py         # 参数模型 - 请求参数
```

## 快速开始

### 环境要求

- **Python**: 3.12+
- **数据库**: MySQL 8.0+ / PostgreSQL 13+ / SQLite 3.x（连接串在 `env/.env.dev`）
- **Redis**: 与 `.env.dev` 中配置一致

### 第一次在本机跑起来

1. 复制 `env/.env.dev.example` → `env/.env.dev`，填写数据库、Redis 等（先在 DB 中建好空库）。
2. 在 **`backend/` 目录下** 安装依赖：推荐 **`uv sync`**；或 `pip install -r requirements.txt`。
3. **启动**：`uv run main.py run --env=dev`（或 `python main.py run --env=dev`）。**首次启动会自动初始化数据库表与基础数据**，一般**无需**先执行 `upgrade`。接口文档示例：`http://127.0.0.1:8001/docs`（端口见 `.env.dev` 中 `SERVER_PORT`）。

### 数据库迁移命令（模型变更时使用）

日常**首次启动不必手动执行**；当你**修改了 ORM 模型**并需用 Alembic 管理结构变更时再使用：

```bash
# 生成迁移文件（模型变更后）
python main.py revision --env=dev
# 应用迁移
python main.py upgrade --env=dev

# 使用 uv 时
uv run main.py revision --env=dev
uv run main.py upgrade --env=dev
```

### 安装依赖与启动服务

```bash
# 推荐使用 uv（与 pyproject.toml 一致）
uv sync
uv run main.py run --env=dev

# 或使用传统 pip / venv
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py run --env=dev
```

### 代码格式化（ruff）

```bash
ruff check
ruff check --fix
ruff check --watch

# 使用 uv 时
uv run ruff check
uv run ruff check --fix
uv run ruff check --watch
```

## 后端约定（日期与序列化）

使用 **Pydantic v2** 与 **PostgreSQL（asyncpg）** 时：ORM 写入需要 Python 原生日期时间，JSON 输出需要可序列化字符串。

- 自定义 `DateStr` / `TimeStr` / `DateTimeStr`（`app/core/validator.py`）使用 **`PlainSerializer(..., when_used='json')`**
- `model_dump(mode='python')` 供 ORM 使用原生类型；JSON / Redis 使用 `model_dump(mode='json')`
- 统一 HTTP 响应见 `app/common/response.py` 中的 **`jsonable_encoder`**
- 写入 Redis 时请使用 **`model_dump(mode='json')`** 再序列化

## 模型网关错误诊断

供应商模板接口会返回 `max_timeout_seconds`，供运营端限制“响应等待上限”。旧版后端没有该字段时，运营端按 600 秒处理；API Key 属于 `settings` 字符串字段，不使用这个秒数上限。

`logs/fastapiadmin.log` 中的 `model_upstream_failure` 记录供应商真实 HTTP 状态、允许的错误码、诊断字段与范围、请求关联 ID，以及错误正文哈希。供应商任意回显、招标正文、密钥和请求 URL 不写入该诊断日志；无法识别的正文保留哈希与关联 ID，不能据此推断具体拒绝原因。

已配置和兼容模式的业务路由使用相同错误分类：响应业务码 `50201` 表示供应商拒绝请求、`50303` 表示授权异常，客户端应保留进度并暂停；`50302` 表示限流，`50304` 表示供应商服务异常。客户端不能仅按外层 HTTP 502/503 决定重试。只有明确的连接建立失败允许网关切换备用模型，拒绝请求或发送结果不确定的失败不在网关内部重复提交。SSE 错误事件沿用对应的 `UPSTREAM_*` 分类。

`50305` / `UPSTREAM_BILLING_REJECTED` 表示供应商返回 `Arrearage`：应检查所用 API Key 对应的供应商账户计费状态，不应提示客户端购买平台积分。供应商 HTTP 错误响应不按估算输入结算客户端积分。

## 支付订单与积分调整恢复

- 客户端下单成功返回 201；渠道明确拒绝返回 502 和失败订单；渠道请求超时等结果不确定时返回 202、`success=false` 和 `confirming` 订单。客户端保留原 `order_no` 与幂等键，查询订单状态，不把 202 当作已付款。
- 后台财务定时任务每分钟扫描到期的未付款订单，按原商户订单号查渠道，按退避间隔重试。只有验签回调或渠道查单确认支付，且订单号、渠道、金额、交易号一致时，才记为已付并发放权益。订单支付码超时只进入待确认状态，不能据此认定付款失败。
- 对账中可唯一核实的漏入账和漏发权益会自动补记；金额、交易号、退款归属不一致等差异保留异常待办，需人工核查。自动修复不直接发起新扣款或退款。
- 运营端手工调整积分请求须携带 8～64 位 `idempotency_key`。重试同一操作复用相同键；相同键的金额、原因、操作人或有效期不同会返回 409。Web 运营端已按此协议发送。
- 发布后需应用 `20260928_payment_recovery` 迁移。迁移会拒绝历史渠道交易号重复数据，须先核查资金与权益后再迁移；不要直接删除重复记录。

离线回归测试（使用模拟模型接口和临时测试数据库）：

```powershell
uv run pytest tests/test_gateway_error_diagnostics.py tests/test_generation_policy.py tests/test_generation_policy_contract.py -q
```

## 相关链接

- **FastAPI 官方文档**: [https://fastapi.tiangolo.com/](https://fastapi.tiangolo.com/)
- **SQLAlchemy 文档**: [https://docs.sqlalchemy.org/](https://docs.sqlalchemy.org/)
- **Pydantic 文档**: [https://pydantic-docs.helpmanual.io/](https://pydantic-docs.helpmanual.io/)

### 模型结果与结算恢复

模型成功后的结算异常不会再归类为模型超时。成功输出先加密保留，结算失败时返回结果和待结算状态；后台只补结算，不重发模型。配置、持久卷、隐私与恢复边界见 [恢复说明](docs/model-result-recovery-20260924.md)。
