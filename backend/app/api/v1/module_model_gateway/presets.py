COMMON_KEY_FIELDS = [
    {"key": "api_key", "label": "API Key", "type": "password", "required": True, "secret": True},
]


def _provider(
    code: str,
    name: str,
    protocol: str,
    endpoint: str | None,
    recommended_model: str | None,
    description: str,
    fields: list[dict] = COMMON_KEY_FIELDS,
    *,
    adapter_ready: bool = True,
) -> dict:
    return {
        "code": code,
        "name": name,
        "protocol": protocol,
        "default_endpoint": endpoint,
        "field_schema": fields,
        "logo_key": code,
        "description": description,
        "recommended_model": recommended_model,
        "adapter_ready": adapter_ready,
    }


PROVIDER_PRESETS: tuple[dict, ...] = (
    _provider("openai", "OpenAI", "openai_compatible", "https://api.openai.com/v1", "gpt-5.2", "OpenAI 官方模型服务"),
    _provider("anthropic", "Anthropic", "anthropic", "https://api.anthropic.com", "claude-sonnet-4-5", "Claude 原生 Messages 协议"),
    _provider("gemini", "Google Gemini", "gemini", "https://generativelanguage.googleapis.com", "gemini-2.5-pro", "Google Gemini 原生生成协议"),
    _provider(
        "bedrock",
        "AWS Bedrock",
        "bedrock",
        "https://bedrock.amazonaws.com",
        "anthropic.claude-sonnet-4-5",
        "AWS 托管模型服务",
        [
            {"key": "region", "label": "区域", "type": "text", "required": True},
            {"key": "access_key", "label": "Access Key", "type": "password", "required": True, "secret": True},
            {"key": "secret_key", "label": "Secret Key", "type": "password", "required": True, "secret": True},
        ],
    ),
    _provider(
        "vertex",
        "Vertex AI",
        "vertex",
        None,
        "gemini-2.5-pro",
        "Google Cloud Vertex AI",
        [
            {"key": "project_id", "label": "项目ID", "type": "text", "required": True},
            {"key": "region", "label": "区域", "type": "text", "required": True},
            {"key": "service_account", "label": "服务账号JSON", "type": "textarea", "required": True, "secret": True},
        ],
        adapter_ready=False,
    ),
    _provider("openrouter", "OpenRouter", "openai_compatible", "https://openrouter.ai/api/v1", None, "聚合多家模型的一站式网关"),
    _provider("fireworks", "Fireworks AI", "openai_compatible", "https://api.fireworks.ai/inference/v1", None, "高性能开源模型推理"),
    _provider("together", "Together AI", "openai_compatible", "https://api.together.xyz/v1", None, "开源模型托管推理平台"),
    _provider("zhipu", "智谱 GLM", "openai_compatible", "https://open.bigmodel.cn/api/paas/v4", "glm-4.7", "智谱 GLM 系列模型"),
    _provider("kimi", "Kimi", "openai_compatible", "https://api.moonshot.cn/v1", "kimi-k2.5", "月之暗面 Kimi 系列模型"),
    _provider("deepseek", "DeepSeek", "openai_compatible", "https://api.deepseek.com/v1", "deepseek-chat", "DeepSeek 对话与推理模型"),
    _provider("mistral", "Mistral AI", "openai_compatible", "https://api.mistral.ai/v1", "mistral-large-latest", "Mistral 官方模型服务"),
    _provider("qwen", "通义千问", "openai_compatible", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen3-max", "阿里云百炼千问系列模型"),
    _provider("minimax", "MiniMax", "openai_compatible", "https://api.minimax.chat/v1", "MiniMax-M2.1", "MiniMax 文本模型服务"),
    _provider("xai", "xAI", "openai_compatible", "https://api.x.ai/v1", "grok-4", "xAI Grok 系列模型"),
    _provider("meta", "Meta", "openai_compatible", None, "meta-llama/Llama-4-Maverick", "Meta Llama 模型（需填写托管地址）"),
    _provider("ark", "火山引擎方舟", "openai_compatible", "https://ark.cn-beijing.volces.com/api/v3", "doubao-seed-1-6", "火山方舟 OpenAI 兼容接口"),
    _provider("hunyuan", "腾讯混元", "openai_compatible", "https://api.hunyuan.cloud.tencent.com/v1", "hunyuan-turbos-latest", "腾讯混元 OpenAI 兼容接口"),
    _provider(
        "ollama",
        "Ollama / 自建兼容服务",
        "openai_compatible",
        "http://127.0.0.1:11434/v1",
        None,
        "本地或私有部署的 OpenAI 兼容服务",
        [{"key": "api_key", "label": "API Key（可选）", "type": "password", "required": False, "secret": True}],
    ),
)
