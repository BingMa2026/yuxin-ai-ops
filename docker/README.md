# 运营端生产部署

生产后端只使用 `docker-compose.backend.yaml`，生产环境文件固定在服务器 `/data/stacks/yuxin-ai-ops/docker/.env.backend`。环境模板为 [.env.backend.example](.env.backend.example)。

公共入口独立维护于 [deploy/edge-nginx](../deploy/edge-nginx/README.md)，统一处理 `https://www.yxciedu.com`、证书、官网和运营端路由。运营前端仍由公共入口读取 `/data/stacks/nginx/html/web`，不额外创建前端容器。

## 唯一配置来源

- Compose：容器、镜像、网络、健康检查和固定的运行参数。
- 服务器 `.env.backend`：真实密钥、环境差异和短信/支付等可选配置；同一文件同时用于 Compose 插值和 `env_file` 注入。
- `backend/env/.env.dev`：仅本地开发。生产镜像不复制 `backend/env/.env.*`，避免镜像里的旧值暗中生效。
- 前端 `.env.production` 是已版本化的正式公开构建配置，使用 `/web/`、`/api/v1` 和 `wss://www.yxciedu.com`。
- [archive](archive/README.md)：已停用的旧配置，不执行。

本地 `backend/env/.env.prod` 不参与 Docker 生产部署；`.dockerignore` 排除了环境文件和支付密钥。`deploy-production.ps1` 发布代码，服务器 `scripts/deploy-release.sh` 通过 `--env-file` 和 `BACKEND_ENV_FILE` 继续加载云端现有 `.env.backend`，不会自动上传本地环境文件或密钥。更换支付密钥时必须先更新云端对应文件和参数，再按下文重建后端容器；仅改本地文件后执行部署不会让新密钥在云端生效。

首次迁移必须先合并现有生产运行参数到服务器环境文件，并保留原密钥；不能用 example 覆盖真实文件。环境文件保持 shell 兼容的 `KEY=value` 格式，含空格、JSON 或特殊字符的值使用单引号包裹，因为现有发布脚本还会加载该文件用于备份数据库。

## 验证与发布

在仓库根目录用安全示例验证 Compose（本地把 `BACKEND_ENV_FILE` 指向示例的绝对路径）：

```powershell
$env:BACKEND_ENV_FILE = (Resolve-Path docker/.env.backend.example).Path
docker compose --env-file docker/.env.backend.example -f docker/docker-compose.backend.yaml config --quiet
```

线上配置检查不要把展开后的密钥打印到终端：

```bash
docker compose --env-file /data/stacks/yuxin-ai-ops/docker/.env.backend -f docker/docker-compose.backend.yaml config --quiet
```

常规代码发布仍使用根目录 `deploy-production.ps1`；默认校验 `https://www.yxciedu.com`。SSH 服务器地址 `-Server` 和访问域名 `-PublicOrigin` 分开设置。

HTTPS 首次切换前如需使用现有 HTTP 入口验证：

```powershell
.\deploy-production.ps1 -PublicOrigin http://119.45.121.36
```

共享网关不随运营端发布修改。首次切换和回滚顺序见公共入口文档。

## 支付宝密钥与回调配置

客户端扫码收款使用支付宝当面付 `alipay.trade.precreate`，使用 RSA2 公钥模式。支付宝应用上线后，还需确认当前 AppID 具有当面付预下单权限；仅开通电脑网站支付不够。原有网页支付订单仍可通过收银台完成，新增订单返回支付宝签名响应中的 `qr_code`。

现有 `POST /api/v1/client/payment/orders` 下单接口不变，`pay_url` 在支付宝订单中为官方 `qr_code`，微信订单中为 Native 下单返回的 `code_url`。二维码图片由客户端绘制，不能把 `alipay.trade.page.pay` 网关长链接当作扫码付款码。订阅、积分、回调验签与查单沿用原订单流程；旧订单重新创建后才会得到新的付款码。

支付密钥使用独立目录 `/data/stacks/yuxin-ai-ops/payment-keys`（可通过 `PAYMENT_KEYS_HOST_DIR` 覆盖），只读挂载到容器 `/run/secrets/payment`。目录不存在时 Compose 会创建空目录，未配置支付的部署仍可启动；空目录不代表支付已就绪。密钥不放进镜像、Git、上传卷或任何 Nginx 静态目录。

配置步骤：

1. 将与支付宝应用现有加签配置匹配的应用私钥保存为 `alipay-app-private-key.pem`，将支付宝平台公钥保存为 `alipay-public-key.pem`。公钥需包含 `-----BEGIN PUBLIC KEY-----` / `-----END PUBLIC KEY-----` 的 PEM 包装，不能直接使用后台复制的裸 Base64 文本，也不能误用应用公钥。保留现有私钥，不重新生成或轮换。
2. 在 Linux 服务器将密钥目录权限设为 `700`、私钥文件设为 `600`，确保后端容器运行用户可读。生产密钥单独做受限备份；数据库备份不包含它们。
3. 向现有服务器 `.env.backend` 合并模板中的六项 `ALIPAY_*`、`PAYMENT_PUBLIC_BASE_URL`、`PAYMENT_KEYS_HOST_DIR` 配置。填写正式应用 AppID 和实际收款账号的卖家 ID，两个密钥路径必须是 `/run/secrets/payment/` 下的容器路径。不要用模板覆盖已有数据库、短信等参数。
4. 使用常规发布流程加载新 Compose 和运行参数；环境变量或挂载变化需要重建运营后端容器，单纯 `docker restart` 不生效。
5. 财务中心确认参数就绪后，启用支付宝平台渠道，并为当前客户端开启收款授权。最后验证真实小额订单、支付通知、主动查单和权益只发放一次。

仅更新生产支付参数或密钥、且线上已经包含所需代码和密钥挂载时，可以在服务器上沿用当前镜像，只重建运营后端。先备份 `.env.backend` 和原密钥，再合并参数；不要直接运行未指定版本的 `docker compose up`，以免切换到 `latest`：

```bash
environment_file=/data/stacks/yuxin-ai-ops/docker/.env.backend
compose_file=$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project.config_files" }}' yuxin-ai-ops-backend)
current_image=$(docker inspect -f '{{.Config.Image}}' yuxin-ai-ops-backend)
export BACKEND_ENV_FILE="$environment_file"
export BACKEND_IMAGE_TAG="${current_image##*:}"
docker compose --env-file "$environment_file" -f "$compose_file" config --quiet
docker compose --env-file "$environment_file" -f "$compose_file" up -d --no-deps --no-build --pull never --force-recreate backend
docker inspect -f '{{.State.Health.Status}}' yuxin-ai-ops-backend
```

等待状态变成 `healthy`，并检查公网 `/api/v1/common/health/ready` 后，再启用渠道。代码变更仍须纳入下一次常规发布；配置重建不会包含本地尚未发布的代码。

支付宝主动查单必须把签名参数中的 `charset=utf-8` 放在请求 URL 查询串中，其余参数通过 POST 表单发送。只在 POST 表单里传 charset 时，网关可能返回并按 GBK 签名，导致 JSON 解析或验签失败。可以查询一个从未创建的订单号，确认验签通过且返回“交易不存在”，无需创建订单或支付。

三类地址用途不同：

| 地址 | 当前用途 |
| --- | --- |
| 支付异步通知 `notify_url` | 后端自动传入 `https://www.yxciedu.com/api/v1/payment/callback/alipay`，用于验签和到账处理；不能填运营端 `/web/` 页面。 |
| 支付同步返回 `return_url` | 旧网页支付流程的浏览器返回页；当前当面付预下单不使用，客户端请求字段仅为兼容保留，不能作为到账依据。 |
| 支付宝后台的授权回调地址 | OAuth 授权取得授权码后的返回地址。当前收款没有使用支付宝 OAuth，也没有对应授权回调处理接口，无需为电脑网站支付修改为运营首页或支付通知地址。 |

应用网关用于平台消息，不替代逐笔支付请求中的 `notify_url`。已有授权回调若用于其他系统，修改前需确认那个系统的用途。

## 支付宝推广提现（商户转账）

这是企业向推广用户付款的功能，独立于当面付收款。支付宝接入检测要求企业开通 [转账到支付宝账户](https://open.alipay.com/api/detail?code=I1080300001000046143)，且应用配置公钥证书。只有普通公钥和当面付权限时不能开启提现。

1. 在企业商家平台申请转账产品，确认当前应用的接入检测通过。按 [单笔转账接口](https://opendocs.alipay.com/open/62987723_alipay.fund.trans.uni.transfer?pathHash=66064890&scene=ca56bca529e64125a2786703c6192d41) 的要求，2026 年及以后新接入商户还需申明转账场景，并随请求上报 `transfer_scene_name`、`transfer_scene_report_infos`。推广佣金应按实际业务申明，不能照抄其他商户的材料。
2. 准备与应用私钥匹配的应用公钥证书、支付宝公钥证书及支付宝根证书。在现有 `payment-keys` 目录分别保存 `appCertPublicKey.crt`、`alipayCertPublicKey_RSA2.crt`、`alipayRootCert.crt`。`ALIPAY_APP_CERT_PATH` 和 `ALIPAY_ROOT_CERT_PATH` 指向对应的 `/run/secrets/payment/` 路径，`ALIPAY_PUBLIC_KEY_PATH` 改为支付宝公钥证书路径。系统会校验应用证书与私钥匹配、应用及平台证书有效期，并生成参与签名的证书序列号。平台证书采用本地固定文件，轮换时需更新，当前不自动下载新证书。
3. 向云端 `.env.backend` 合并 `GROWTH_PAYOUT_ENCRYPTION_KEY`、`GROWTH_ALIPAY_TRANSFER_SCENE_NAME`、`GROWTH_ALIPAY_SCENE_REPORT_JSON`。加密密钥由 `cryptography.fernet.Fernet.generate_key()` 生成，单独备份；已有密钥必须保留，否则历史收款账户和提现单无法解密。场景上报为 JSON 数组，包含支付宝要求的 `info_type`、`info_content`；环境文件中用单引号包裹整段 JSON。
4. 先发布支持证书模式的后端代码，再协调支付宝后台与云端文件、变量切换。普通公钥收款时两个新增证书路径必须均留空；一旦配置证书模式，收款、查单和转账共用证书签名。不能只修改支付宝后台加签方式而不更新后端。切换前保留普通公钥配置备份，切换后先核验收款预下单、查单和支付回调。
5. 产品、证书和场景均核验后，将 `GROWTH_ALIPAY_PAYOUT_ENABLED=true` 并重建后端容器，确认提现能力就绪。当前客户端权益政策还需允许提现；财务审核通过后才进入转账队列。上线前检查是否已有待转账提现单，再启用开关。

能力接口只检查本地配置，不代替支付宝产品审核或场景审核。转账前确保企业支付宝余额充足；结果未知时按原商户单号查单，不能换单号重付。退款核验按钮只查询已存在的退款并冲正奖励，不会发起转账或退款。

本地开发同样需要证书和应用私钥，放在已被 Git 忽略的 `backend/env/payment-keys/`，并在 `.env.dev` 使用本机绝对路径；`.env.prod` 保留容器内 `/run/secrets/payment/` 路径。若开发环境连接同一数据库，提现账户加密密钥必须与云端一致。支付宝提现开关是环境变量 `GROWTH_ALIPAY_PAYOUT_ENABLED`，`true` 开启、`false` 关闭；运营页面目前没有该开关入口。本地修改 `.env.dev` 后重启后端，云端修改 `/data/stacks/yuxin-ai-ops/docker/.env.backend` 后重建后端容器。两个环境独立配置，连接真实支付宝时开启后均可执行实际转账。

2026-09-10 下载的证书已整理为标准 PEM；运行时 `alipayRootCert.crt` 保留原包中参与 RSA2 序列号计算的两份 RSA 根证书。原始下载包包含非 RSA 证书，其中一份旧 ECDSA 证书的 ASN.1 格式不能被当前解析库读取，不能直接用原包覆盖运行时文件。更新证书时保留原始下载文件，核对控制台证书序列号、应用私钥匹配关系和支付宝签名响应后再切换。
