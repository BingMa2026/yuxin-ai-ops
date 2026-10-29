# 运营平台与客户端体验验收记录

## 验收范围

- 运营端：用户管理、用户详情、等级规则、价格体系、工单与反馈、消息触达。
- 客户端：注册登录、个人资料、左下角账户卡片、问题反馈、站内消息。
- 数据状态：开发环境 `bid_agent` 客户端，测试账号 `client_test`，包含订阅、积分、模型用量、工单、消息和等级数据。

## 视觉依据

- 用户列表：`C:\Users\Administrator\AppData\Local\Temp\codex-clipboard-72858eff-6dbb-4334-9006-630e8e604a0f.png`（2549 × 940）。
- 用户详情：`C:\Users\Administrator\AppData\Local\Temp\codex-clipboard-866a5a8a-9fa1-47b1-af5a-44bc83228285.png`（2312 × 1239）。
- 消息定时发送：`C:\Users\Administrator\AppData\Local\Temp\codex-clipboard-cf38c8bd-5245-41b1-84d5-17e19dc32fc0.png`（739 × 758）。
- 客户端账户菜单：`C:\Users\Administrator\AppData\Local\Temp\codex-clipboard-d7868e73-588f-4826-833e-2f7646f9170a.png`（304 × 242）。
- 现有产品规范：运营端 `FaSearchBar + FaTableHeader + FaTable`，客户端既有设置页布局与图标体系。

## 实现证据

实现截图位于 `E:\yx-code\yuxin-ai-ops\docs\audit\operations-ux-20260904`。

- 全屏证据：`ops-user-list.png`、`ops-user-detail.png`、`ops-pricing.png`、`ops-message-scheduled.png`、`client-registration.png`、`client-profile.png`、`client-support.png`、`client-message-center.png`、`client-account-card.png`。
- 同屏对比：`compare-user-list.png`、`compare-user-detail.png`、`compare-message-scheduled.png`、`compare-account-card.png`。
- 实现视口：2560 × 1215，浏览器默认像素密度，亮色主题；除注册页外均为已登录、已加载真实演示数据的业务状态。

## 发现与修正记录

1. **已修正 · P2**：定时发送抽屉内容过长导致底部操作不可见，并出现多余字符。调整抽屉顶部、最大高度、滚动区和编辑器高度，补齐发送时间、时区、收件人预估、样例和重新计算逻辑；复验见 `ops-message-scheduled.png`。
2. **已修正 · P2**：用户、工单、消息状态全部使用黑色文本，难以扫描。统一为等级、订阅、性质、分类、优先级和状态标签，并补齐对应筛选；复验见 `ops-user-list.png`、`client-support.png`。
3. **已修正 · P2**：用户详情首屏缺少老板原型中的经营感知。将累计支付、订阅、积分、活跃天数、模型调用和近 30 日活跃趋势提到首屏，次要数据分区加载；复验见 `ops-user-detail.png`。
4. **已修正 · P2**：客户端账户入口信息不足。补齐彩色首字头像、名称、LV、账号、当前订阅和可用积分，并保持菜单操作紧凑；复验见 `client-account-card.png`。
5. **已修正 · P2**：客户端消息按普通文本展示，无法承载运营富文本。运营端接入富文本编辑，服务端清洗，客户端使用 DOMPurify 清洗后展示；复验见 `client-message-center.png`。
6. **已修正 · P2**：问题反馈的性质、分类、优先级和状态不易区分。运营端与客户端采用同一语义模型和差异化标签，并验证运营公开回复可进入客户端消息中心。
7. **已修正 · P3**：客户端反馈列表存在弃用组件控制台告警。替换为语义化列表并使用新版抽屉尺寸属性，重新挂载后未出现新警告或错误。
8. **接受 · P3**：2560 × 1215 视口下注册表单为保证字段完整保留内层滚动；主操作可通过表单滚动到达，常见桌面视口可用。后续可在独立视觉精修轮次压缩纵向密度。

## 功能复验

- 注册、自动登录、头像上传、资料编辑、账户卡片、消息已读和反馈续答均可操作。
- 运营端公开回复生成客户端站内消息，内部备注不会返回客户端。
- 用户列表、等级规则、工单、消息和价格体系使用现有平台查询、重置、展开、表头工具和分页规范。
- 后端目标测试 15 个通过；运营端类型检查与构建通过；客户端 225 个应用测试、25 个契约测试、架构检查、类型检查与 Web 构建通过。

final result: passed
