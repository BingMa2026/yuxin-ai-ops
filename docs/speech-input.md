# 客户端语音输入

运营路径：资源中心 → 供应商与模型，维护语音识别接口和语音采购价；客户端模型配置 → 模型配置 → 语音输入，为当前客户端选择模型并设置时长限制。上线默认关闭，不自动修改任何客户端开关。

客户端点击麦克风，停止录音后识别并追加到草稿，用户确认后发送。最终用户不能选择供应商或语音模型。朗读和语音合成本期不调用，但语音合成及全模态模型的采购价可以维护、查看。

## 模型与价格

- 模型目录新增 `speech_protocol` 和 `speech_pricing`。识别协议可选择 OpenAI 兼容 Audio Transcriptions、千问 ASR Chat Completions、千问 ASR Realtime、百炼同步 ASR（Qwen Audio 3.0/Fun-ASR）、百炼流式 ASR（Fun-ASR/Paraformer）。模型 ID 不设固定白名单，新型号按其兼容协议接入；全新私有协议需要服务端适配。
- 语音合成与全模态对话不是专用语音转写，不能因为名称包含 audio/tts 就自动作为转写接口。长文件异步转写不是聊天框录音协议。
- 语音识别启用须有采购价、可用供应商连接及协议。语音模型不进入对话模型绑定、路由和用户模型选择。
- 2026-09-13 核对北京地域已同步的 44 个语音/全模态型号，价格取自[阿里云官方价格](https://help.aliyun.com/zh/model-studio/model-pricing)。ASR 元/秒、TTS 元/万计费字符、Omni 按模态元/百万 Token；MiniMax 音色复刻另列元/音色。只匹配确切已核价型号与北京接口，不把北京价格应用到国际账号，不猜未来型号价格。
- `20260913_speech_prices.json` 为迁移使用的不可变价格快照；只补空值，不覆盖人工采购价，不启用模型或客户端。供应商同步会为新导入的已知型号填入对应快照价格。价格可在模型编辑中修改，人工修改会清除官方来源标记。
- 免费额度与折扣不视为采购价。本期不扣用户积分；后台 `speech_usage` 独立记录时长、模型、状态及秒计价估算。Token 计价模型不伪造按秒成本；失败状态也不伪报为零成本。已汇入经营成本、趋势、模型排行、直接毛利、供应商请求成本及用户成本趋势。供应商账单单独核对，不叠加到请求成本；实际收费以供应商账单为准。

## API 与数据

- 运营：`GET/PUT /operations/models/speech/config`、`GET /operations/models/speech/models`，沿用模型查看/编辑权限和认证 `app_id`，配置 revision 防止覆盖并发编辑。
- 客户端：`GET /client/speech/capability`、`POST /client/speech/transcriptions`。必须使用客户端用户令牌；multipart 仅传 `audio`、`request_id`，不能自行指定模型或授权范围。标准响应包络，返回禁止缓存。
- 录音为单声道 16 kHz PCM16 WAV，单次默认最多 60 秒，每人每日默认 600 秒（北京时间自然日）。每人每分钟最多 8 次、一次进行中的请求；用户行锁只保护额度预留，供应商调用不持有数据库锁。相同客户端、用户、request_id 拒绝重复调用；失败调用占用安全额度。
- 不在业务数据库、静态文件或操作日志中保存录音和识别正文。供应商密钥始终在后端解密使用。请求最长 65 秒，不自动重试供应商；客户端取消/切换会话/退出登录后不回填旧结果。

## 验证与发布

执行后端 `uv run pytest tests/test_speech.py tests/test_speech_provider.py tests/test_speech_migration.py -q` 及全套测试，运营端类型检查、测试及生产构建。迁移测试覆盖空表安装、已由 ORM 建表、重复执行、模型一致性、原客户端保留及 PostgreSQL DDL。

按仓库 `deploy-production.ps1` 发布运营前后端并迁移，发布前备份数据库。本次不制作或上传客户端安装包；已安装的旧客户端需要后续更新客户端版本才获得麦克风实现。

协议参考：[千问 ASR](https://help.aliyun.com/zh/model-studio/qwen-asr-api-reference)、[Qwen Audio/Fun-ASR 同步接口](https://help.aliyun.com/en/model-studio/fun-asr-flash-recorded-speech-recognition-http-api)、[Paraformer 事件](https://help.aliyun.com/zh/model-studio/paraformer-client-events)、[OpenAI Audio API](https://platform.openai.com/docs/api-reference/audio)。

## 统一报表口径

- 读取聊天请求账与语音用量账的只读合并结果，不复制记账、不产生第二笔费用。历史语音记录直接参与查询，无需重写历史或重新扣款。
- 语音完成时间取终态记录的 updated_time（当前没有用量编辑入口）；运行中请求不计入已完成统计。经营总览使用北京时间及开始含、结束不含的范围。
- 保留调用当时记录的 estimated_cost_yuan，不能用模型当前价格重算。停用或软删除模型不会移除历史费用。
- 有结果和空识别都算上游调用成功；失败、取消、未能计价的结果保留未知费用，返回 unknown_cost_calls。cost_status=incomplete 表示成本及毛利只覆盖已知金额，不是最终账单。零元且明确已计价的记录不会误判为未知。
- summary/daily 新增 speech_cost_yuan、speech_calls、unknown_cost_calls；模型排行新增 usage_kind、duration_ms、unknown_cost_calls。原 provider_cost_yuan 现在包含聊天与语音，不能再与 speech_cost_yuan 相加。
- 供应商共享账号按各客户端已知请求成本占比分摊，分子和分母均包含语音。跨账期查询按实际重叠时间折算账单金额。未知费用仍待核对，语音估算不会被标成逐条已对账费用。
- 语音 Token 与用户扣分均为零，仅增加语音调用数、录音时长和采购成本；用户发送转写文字后的聊天调用按原规则独立计费。