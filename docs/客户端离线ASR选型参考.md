# 客户端离线 ASR 选型参考

核对日期：2026-09-13。本文仅做选型，不代表已开发或已在招投标客户端实测。

## 先看结论

普通办公电脑可以考虑本地语音输入，不必把独立显卡作为前提。针对中文聊天框，我建议先对比 SenseVoiceSmall INT8、Paraformer、Qwen3-ASR-0.6B；质量增强候选再考虑 Qwen3-ASR-1.7B、Fun-ASR-Nano、GLM-ASR-Nano。没有一个模型能仅凭公开榜单保证最适合招投标术语。

sherpa-onnx、whisper.cpp 和 FunASR 是运行工具或工具箱；SenseVoice、Whisper、Paraformer 等才是模型。下载按钮背后应绑定经过测试的一组模型、量化格式与运行引擎，不能把任意模型文件交给同一个引擎运行。

## 硬件要求如何理解

- 8 GB 内存的普通办公电脑：优先测试量化 SenseVoiceSmall、Paraformer 或 Whisper base/small，先用 CPU；不要承诺所有老电脑都能即时转写。
- 16 GB 内存、较新的多核 CPU：可增加 Qwen3-ASR-0.6B、Fun-ASR-Nano 的量化版本测试；运行库适配、首次加载时间仍需验证。
- 有独立显卡或较强 Apple Silicon：更适合测试 Qwen3-ASR-1.7B、GLM-ASR-Nano、Whisper large/turbo 等质量优先方案。

以上是产品测试分档建议，不是官方最低配置。模型文件大小不等于运行内存；还要计入运行库、音频缓存、Windows、Electron 和其他应用。参数量也不能直接换算出转写速度。

作为有明确文档的例子，whisper.cpp 列出的未量化模型资源约为：

| Whisper 模型 | 模型文件 | 推理内存 |
| --- | --- | --- |
| tiny | 75 MiB | 273 MB |
| base | 142 MiB | 388 MB |
| small | 466 MiB | 852 MB |
| medium | 1.5 GiB | 2.1 GB |
| large | 2.9 GiB | 3.9 GB |

这些是项目参考值，不是整个客户端占用，也不适用于所有硬件后端或所有量化版本。[运行内存说明](https://github.com/ggml-org/whisper.cpp)、[模型下载规格](https://github.com/ggml-org/whisper.cpp/blob/master/models/README.md)。

## 候选、优点和取舍

硬件负担为针对本地短录音的选型判断，低/中/高不是统一实测排名。

| 候选模型 | 硬件负担 | 优点 | 缺点与选型取舍 | 对本项目的建议 |
| --- | --- | --- | --- | --- |
| SenseVoiceSmall + sherpa-onnx INT8 | 较低 | 有现成 ONNX 量化模型；支持普通话、粤语、英语、日语、韩语；适合 CPU 离线短句 | 开放的小模型是五语种，不能按研究中的全部语言宣传；当前更适合录完转写；专业名词仍须实测 | 首轮优先测试的默认方案 |
| Paraformer-zh | 较低至中 | 中文/中英场景，有约 220M 参数模型和成熟推理工具 | 语言覆盖及复杂口音要按具体模型看；标点、端点检测可能需要配套模型 | 与 SenseVoice 对比普通话及招投标术语 |
| Paraformer-zh-streaming | 较低至中 | 专门的流式模型，可边说边显示文字 | 要维护流式状态与断句；不能把离线模型直接当流式模型 | 后续确实需要实时出字时考虑 |
| Qwen3-ASR-0.6B | 中 | 支持 30 种语言与 22 种中文方言；同系列较轻版本 | 桌面量化引擎、Windows CPU 速度和分发体积需要单独测试；不能照搬服务端吞吐数据 | 首轮质量与资源平衡候选 |
| Qwen3-ASR-1.7B | 较高 | 官方公开评测中质量较强；方言和复杂音频覆盖广 | 权重与计算量更大，普通办公 CPU 的等待时间可能不理想 | 高性能电脑可选增强包 |
| Fun-ASR-Nano / MLT-Nano | 中至较高 | 约 800M；Nano 面向中英日及中文口音，MLT-Nano 为独立 31 语种模型；有本地推理路径 | 不同检查点语言范围不同，GGUF/ONNX/Python 格式不能混用；需要验证实际桌面运行路径 | 作为中文质量增强对比组 |
| Whisper base / small + whisper.cpp | 较低至中 | Windows 本地推理成熟；多语种；模型大小和量化选择明确 | 小版本在复杂中文或专业术语上不一定理想；噪声和无语音输入要处理；英文专用 .en 模型不适合中文 | 跨平台对比基线 |
| Whisper large-v3 / large-v3-turbo | 较高 | 多语种覆盖广；turbo 更侧重速度；桌面推理工具较成熟 | 下载较大；CPU 延迟与功耗需要测试；普通中文输入未必比中文专用模型划算 | 多语种或较强硬件用户的可选包 |
| GLM-ASR-Nano-2512 | 较高 | 约 1.5B；官方强调低音量语音、中文和方言识别 | 名字有 Nano 也不代表很轻；运行依赖与桌面适配成本较高 | 针对小声讲话、口音的专项对比 |
| Vosk small-cn | 低 | 中文小模型约 42 MB；离线、流式、低资源设备适配方便 | 官方中文测试误差仍较明显；不能仅因包小就作为高质量中文输入默认模型 | 极低配置电脑的备选 |
| Moonshine Voice 对应语言模型 | 依模型而定 | 面向设备端和低延迟流式交互；支持多平台运行 | 必须核对具体中文模型、效果和许可；部分旧版非英文非流式模型仍为非商业许可 | 保留观察，先确认适用模型再比较 |

模型能力和下载参考：

- [SenseVoice 官方](https://github.com/QwenAudio/SenseVoice)、[sherpa-onnx SenseVoice 下载](https://k2-fsa.github.io/sherpa/onnx/sense-voice/pretrained.html)
- [Paraformer / Fun-ASR-Nano 模型与运行方式](https://github.com/modelscope/FunASR)
- [Qwen3-ASR 模型、语言和评测](https://github.com/QwenLM/Qwen3-ASR)
- [Whisper 本地运行](https://github.com/ggml-org/whisper.cpp)
- [GLM-ASR-Nano](https://github.com/zai-org/GLM-ASR)
- [Vosk 官方中文模型大小与测试结果](https://alphacephei.com/vosk/models)
- [Moonshine 模型](https://moonshine-voice.readthedocs.io/en/latest/models/)、[许可例外](https://github.com/moonshine-ai/moonshine#license)

## 下载即用的产品建议（仅供后续）

默认给用户一个「离线语音包」，显示下载大小、所需空间和状态；性能足够时再提供「增强识别包」。普通用户不用看一长串模型名字。下载应支持中断后继续、完整性验证、删除释放空间和版本更新。录音和识别在独立工作进程运行，避免卡住聊天界面；失败时保留草稿，不悄悄上传音频到云端。

正式选型前，用同一批 50～100 条测试录音比较：普通话、中英混说、湖北等口音、低音量、噪声、公司名、金额、日期及招投标专有词。记录错字率、数字准确率、停止录音后的等待时间、首次加载时间、峰值内存和包大小。官网速度通常有特定硬件条件，不能直接当作用户办公电脑的体验承诺。
