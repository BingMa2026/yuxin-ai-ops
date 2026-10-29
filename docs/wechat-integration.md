# 微信扫码登录与 Native 收款接入

当前客户端使用微信开放平台**网站应用**扫码登录、微信支付普通商户 **Native** 二维码收款。两项能力分别申请；网站应用审核通过不等于商户 Native 已开通。公众号服务号的 AppID 也不能替代网站应用 AppID。

## 需要在微信后台完成

1. 在微信开放平台确认网站应用已获“微信登录”权限，授权回调域名包含 `www.yxciedu.com`。服务端实际回调地址为 `https://www.yxciedu.com/api/v1/client/auth/wechat/callback`。客户端使用 `snsapi_login`；首次扫码可创建新账号（必须验证本人手机号并设置账号密码），也可用已有账号密码或已验证手机号短信码绑定。已绑定后再次扫码直接登录。不把微信授权码或产品令牌放进浏览器跳转地址。
2. 新账号和手机号验证码登录依赖腾讯云短信：开通短信应用、国内验证码短信套餐，取得 SDKAppID；审核签名和仅含一个验证码变量的模板。至少配置注册、登录、绑定三个模板 ID（可复用同一已审核模板；绑定模板也用于登录后验证或更换手机号），并把 SecretId/SecretKey 仅写入运营后端安全环境。缺配置时短信接口明确返回 503，不会假装发送成功。历史未验证手机号不能直接用于登录或认领账号，用户可先用账号密码登录，再在个人资料中验证本人手机号。
3. 在微信支付商户平台确认**Native 支付**已开通，并将已认证的服务号（或微信支付支持的小程序、移动应用）AppID 与当前商户号绑定；网站应用 AppID 只用于本项目的扫码登录，不能作为 Native 支付 AppID。当前代码调用 `/v3/pay/transactions/native`，仅开通 JSAPI、付款码、刷脸支付不能满足这条链路。
4. 从商户平台取得商户号，配置 APIv3 密钥，生成并登记商户 API 证书，取得**同一张证书**的序列号和私钥文件。已有证书若丢失配套私钥，不能仅凭序列号调用 API；需申请新证书并更新序列号与私钥，旧证书在确认其他系统不再使用前不要作废。验签材料可使用微信支付公钥及公钥 ID，或微信支付平台证书；公钥切换过渡期若微信仍用平台证书签发回调，应同时配置平台证书。商户私钥、APIv3 密钥、网站应用 AppSecret 只保存在服务器安全配置中，不写到运营网页或客户端。

## 服务端配置

生产参数放在服务器 `docker/.env.backend`，模板见 `docker/.env.backend.example`：

| 登录 | 支付 |
| --- | --- |
| `CLIENT_WECHAT_LOGIN_APP_ID`：网站应用 AppID | `WECHAT_PAY_APP_ID`：已关联商户号的服务号/小程序/移动应用 AppID |
| `CLIENT_WECHAT_LOGIN_APP_SECRET`：网站应用 AppSecret | `WECHAT_PAY_MCH_ID`：商户号 |
| `CLIENT_WECHAT_LOGIN_CALLBACK_URL`：上述固定 HTTPS 回调地址 | `WECHAT_PAY_MERCHANT_SERIAL_NO`、`WECHAT_PAY_PRIVATE_KEY_PATH`：商户证书序列号和私钥 |
|  | `WECHAT_PAY_API_V3_KEY`：32 字节 APIv3 密钥 |
|  | `WECHAT_PAY_PUBLIC_KEY_ID` + `WECHAT_PAY_PUBLIC_KEY_PATH`，或 `WECHAT_PAY_PLATFORM_CERT_PATH`：微信侧验签材料 |
|  | `PAYMENT_PUBLIC_BASE_URL`：`https://www.yxciedu.com/api/v1` |

密钥文件必须由服务器提供并挂载到容器；私钥不能进入 Git 或镜像。登录和 Native 支付使用不同类型的 AppID，分别配置和校验。使用微信支付公钥时，出站 API 请求携带公钥 ID 作为 `Wechatpay-Serial`；回调根据微信响应的序列号选择相应公钥或平台证书验签。微信支付回调为 `https://www.yxciedu.com/api/v1/payment/callback/wechat`。本机开发环境即使配置了生产回调地址，也无法独立完成微信登录或支付通知回调；完整扫码验收需在该生产域名对应的服务上完成。

短信配置项见 `docker/.env.backend.example` 中的 `TENCENT_SMS_*`。短信通过腾讯云 `SendSms` API 发送，验证码 5 分钟有效、单次使用；服务端限流并只存短时摘要。必须使用真实通过审核的模板，模板参数只有一个 6 位验证码。身份关联存于 `client_user` 的 `(app_id, wechat_openid)`；手机号只有在 `mobile_verified_at` 非空时才可登录，同应用已验证手机号唯一。服务号 OpenID 与网站应用 OpenID 不等同，当前没有按 UnionID 自动合并用户。

## 发布与验收

先部署含 `20260923_client_wechat_login` 与 `20261009_client_mobile_identity` 迁移的运营后端，再发布使用手机号验证的新版客户端。未填登录配置时扫码入口返回 503；未填短信配置时短信入口返回 503；未填支付配置时运营端不能启用微信渠道。部署后检查运营端“财务中心 → 支付渠道 → 微信支付 → 管理渠道”的缺项清单。

使用测试账号扫码，覆盖首次短信验证注册、已有账号密码绑定、已验证手机号短信绑定、再次扫码、取消授权、过期二维码和重复回调；再验证账号/手机号密码登录与手机号验证码登录。用经授权的最小金额测试订单验证 Native 下单返回 `code_url`、真实扫码付款、回调验签、查单补偿和权益仅发放一次。只有真实商户回执和对账均正确后才启用生产支付渠道。

官方接口：[网站应用微信登录](https://developers.weixin.qq.com/doc/oplatform/Website_App/WeChat_Login/Wechat_Login.html)、[Native 接入准备](https://pay.wechatpay.cn/doc/v3/merchant/4015614538)、[Native 下单](https://pay.wechatpay.cn/doc/v3/merchant/4012791877)。
