"""图片预占按视觉 Token 计算，不按传输字节数计算。"""

from app.api.v1.module_model_gateway.image_reservation import (
    MAX_QWEN38_IMAGE_TOKENS,
    estimate_qwen38_image_request,
)
from app.api.v1.module_model_gateway.schema import RuntimeCompletionRequest


def _request(image_bytes: int) -> RuntimeCompletionRequest:
    return RuntimeCompletionRequest(
        request_id="visual-reserve-test",
        business_code="document_intelligence",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "识别这一页图片"},
                    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + "A" * image_bytes}},
                ],
            }
        ],
    )


def test_qwen_image_reservation_does_not_charge_base64_as_text() -> None:
    small = estimate_qwen38_image_request(_request(100_000))
    large = estimate_qwen38_image_request(_request(500_000))
    assert small == large
    assert MAX_QWEN38_IMAGE_TOKENS < large < MAX_QWEN38_IMAGE_TOKENS + 1000


def test_text_only_keeps_legacy_reservation_path() -> None:
    request = RuntimeCompletionRequest(request_id="text-reserve-test", messages=[{"role": "user", "content": "普通文本"}])
    assert estimate_qwen38_image_request(request) is None
