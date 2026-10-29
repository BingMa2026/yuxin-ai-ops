"""为已验证的 Qwen 3.8 路由保守预占图片 Token。"""

from __future__ import annotations

import json
from math import ceil
from typing import Any

# Qwen 3.8 每 32×32 像素约消耗一个视觉 Token，单图上限为 16,777,216 像素。
# 加上两个边界 Token；依据百炼 OpenAI 兼容接口的图片输入说明。
MAX_QWEN38_IMAGE_TOKENS = 16_386


def estimate_qwen38_image_request(data: Any) -> int | None:
    """按解码后的图片预占，不按 Base64 传输长度计费。

    纯文本或无法识别的图片格式返回 None，继续使用网关原有估算。
    """

    messages = [message.model_dump(exclude_none=True) for message in data.messages]
    image_count = 0
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for index, item in enumerate(content):
            if not isinstance(item, dict) or item.get("type") != "image_url":
                continue
            image_url = item.get("image_url")
            if not isinstance(image_url, dict) or not isinstance(image_url.get("url"), str):
                return None
            url = image_url["url"]
            if not (url.startswith("data:image/") or url.startswith(("http://", "https://"))):
                return None
            content[index] = {**item, "image_url": {**image_url, "url": "[image]"}}
            image_count += 1
    if not image_count:
        return None
    serialized = json.dumps({"messages": messages, "tools": data.tools}, ensure_ascii=False, separators=(",", ":"))
    text_budget = max(1, len(serialized.encode("utf-8")), ceil(len(serialized) / 4))
    return text_budget + image_count * MAX_QWEN38_IMAGE_TOKENS
