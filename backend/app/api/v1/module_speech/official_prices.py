"""Verified Beijing public list prices, 2026-09-13. Never infer future prices.

Source: https://help.aliyun.com/zh/model-studio/model-pricing
Only exact published IDs and the Beijing provider endpoint match this snapshot.
"""

from copy import deepcopy
from decimal import Decimal
from urllib.parse import urlsplit

PRICES: dict[str, dict] = {}


def _add(ids, unit, prices, note=""):
    profile = {
        "region": "华北2（北京）",
        "currency": "CNY",
        "source_url": "https://help.aliyun.com/zh/model-studio/model-pricing",
        "verified_at": "2026-09-13",
        "items": [{"label": label, "unit": unit, "price": value} for label, value in prices],
        "note": note or "官方刊例价；不含免费额度、折扣，实际费用以供应商账单为准。",
    }
    for model_id in ids.split():
        PRICES[model_id.lower()] = deepcopy(profile)


_add("qwen-audio-3.0-asr-flash fun-asr-flash-2026-06-15 qwen3-asr-flash qwen3-asr-flash-2026-02-10 qwen3-asr-flash-2025-09-08", "second", [("音频输入", "0.00022")])
_add("qwen3-asr-flash-realtime qwen3-asr-flash-realtime-2026-02-10 qwen3-asr-flash-realtime-2025-10-27 qwen-audio-3.0-asr-flash-streaming", "second", [("音频输入", "0.00033")])
_add(
    "qwen3-tts-flash qwen3-tts-flash-2025-11-27 qwen3-tts-flash-2025-09-18 qwen3-tts-instruct-flash qwen3-tts-instruct-flash-2026-01-26 qwen3-tts-vd-2026-01-26 qwen3-tts-vc-2026-01-22",
    "10k_characters",
    [("语音合成", "0.8")],
    "按计费字符统计；汉字计2字符，其他字符通常计1字符；输出不另计费。音色创建等附加服务另计。",
)
_add(
    "qwen3-tts-flash-realtime qwen3-tts-flash-realtime-2025-11-27 qwen3-tts-flash-realtime-2025-09-18 qwen3-tts-instruct-flash-realtime qwen3-tts-instruct-flash-realtime-2026-01-22 qwen3-tts-vd-realtime-2026-01-15 qwen3-tts-vd-realtime-2025-12-16 qwen3-tts-vc-realtime-2026-01-15 qwen3-tts-vc-realtime-2025-11-27",
    "10k_characters",
    [("语音合成", "1")],
    "按计费字符统计；汉字计2字符，其他字符通常计1字符；输出不另计费。音色创建等附加服务另计。",
)
_add("MiniMax/speech-2.8-hd MiniMax/speech-02-hd", "10k_characters", [("语音合成", "3.5")])
_add("MiniMax/speech-2.8-turbo MiniMax/speech-02-turbo", "10k_characters", [("语音合成", "2")])
for _id, _profile in PRICES.items():
    if _id.startswith("minimax/"):
        _profile["items"].append({"label": "音色复刻（首次合成收取）", "unit": "voice", "price": "9.9"})
_add("qwen-tts-2025-05-22", "million_tokens", [("文本输入", "1.6"), ("音频输出", "10")])


def _omni(ids, values, combined=False):
    labels = (
        ["文本/图片/视频输入", "音频输入", "文本输出（多模态输入）", "音频输出（伴随文本不计费）"]
        if combined
        else ["文本输入", "音频输入", "图片/视频输入", "文本输出（纯文本输入）", "文本输出（多模态输入）", "音频输出（伴随文本不计费）"]
    )
    _add(ids, "million_tokens", list(zip(labels, values.split(), strict=True)))


_omni("qwen3.5-omni-plus qwen3.5-omni-plus-2026-03-15", "7 53 40 213", True)
_omni("qwen3.5-omni-flash qwen3.5-omni-flash-2026-03-15", "2.2 18 13.3 72", True)
_omni("qwen3.5-omni-plus-realtime qwen3.5-omni-plus-realtime-2026-03-15", "10 80 60 300", True)
_omni("qwen3.5-omni-flash-realtime qwen3.5-omni-flash-realtime-2026-03-15", "3.3 27 20 107", True)
_omni("qwen3-omni-flash qwen3-omni-flash-2025-12-01 qwen3-omni-flash-2025-09-15", "1.8 15.8 3.3 6.9 12.7 62.6")
_omni("qwen3-omni-flash-realtime qwen3-omni-flash-realtime-2025-12-01 qwen3-omni-flash-realtime-2025-09-15", "2.2 18.9 3.9 8.3 15.2 75.1")
_omni("qwen-omni-turbo", "0.4 25 1.5 1.6 4.5 50")
_add("qwen-audio-3.0-realtime-plus", "million_tokens", list(zip(["文本输入", "音频输入", "文本输出", "音频输出"], "5 40 40 150".split(), strict=True)))
_add("qwen-audio-3.0-realtime-flash", "million_tokens", list(zip(["文本输入", "音频输入", "文本输出", "音频输出"], "3 30 30 100".split(), strict=True)))


def official_speech_price(model_id: str, endpoint: str) -> dict | None:
    host = urlsplit(endpoint).hostname or ""
    if host != "dashscope.aliyuncs.com" and not host.endswith(".cn-beijing.maas.aliyuncs.com"):
        return None
    return deepcopy(PRICES.get(model_id.lower()))


def duration_rate(pricing: dict | None) -> Decimal | None:
    if not pricing:
        return None
    # Token and character costs must never be converted into invented time rates.
    item = next((item for item in pricing.get("items", []) if item["unit"] == "second"), None)
    return Decimal(str(item["price"])) * 60 if item else None
