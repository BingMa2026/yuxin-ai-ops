import re
from urllib.parse import urlsplit, urlunsplit

from app.core.exceptions import CustomException


def speech_adapter(model_id: str, configured: str | None = None) -> str | None:
    if configured:
        return configured
    model_id = model_id.lower()
    if "filetrans" in model_id:
        return None
    if model_id.startswith("qwen") and "asr" in model_id and "realtime" in model_id:
        return "qwen_realtime"
    if (model_id.startswith(("fun-asr", "paraformer")) and "realtime" in model_id) or ("asr" in model_id and "streaming" in model_id):
        return "dashscope_realtime"
    if model_id.startswith(("qwen-audio-", "fun-asr-flash")) and "asr" in model_id:
        return "dashscope_asr"
    if model_id.startswith("qwen") and "asr" in model_id:
        return "qwen_asr"
    if "whisper" in model_id or "transcribe" in model_id:
        return "openai_transcriptions"
    return None


def speech_endpoint(endpoint: str, protocol: str = "qwen_asr") -> str:
    try:
        url = urlsplit(endpoint)
        port = url.port
    except ValueError:
        raise CustomException(msg="语音服务接口地址无效", status_code=400) from None
    host = url.hostname or ""
    allowed = host in {"dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com", "dashscope-us.aliyuncs.com"} or bool(
        re.fullmatch(r"[a-zA-Z0-9-]+\.(?:cn-beijing|ap-southeast-1)\.maas\.aliyuncs\.com", host)
    )
    if protocol == "openai_transcriptions":
        if url.scheme != "https" or not host or url.username or url.password or url.query or url.fragment:
            raise CustomException(msg="语音识别接口需要 HTTPS 地址", status_code=400)
        return endpoint.rstrip("/") + "/audio/transcriptions"
    if not allowed or url.scheme != "https" or url.username or url.password or url.query or url.fragment or port not in (None, 443):
        raise CustomException(msg="语音输入需要阿里云百炼官方 HTTPS 接口地址", status_code=400)
    paths = {
        "qwen_asr": "/compatible-mode/v1/chat/completions",
        "qwen_realtime": "/api-ws/v1/realtime",
        "dashscope_realtime": "/api-ws/v1/inference",
        "dashscope_asr": "/api/v1/services/aigc/multimodal-generation/generation",
    }
    if protocol not in paths:
        raise CustomException(msg="尚未接入该语音识别协议", status_code=400)
    path = paths[protocol]
    realtime = protocol.endswith("realtime")
    return urlunsplit(("wss" if realtime else "https", url.netloc, path, "", ""))
