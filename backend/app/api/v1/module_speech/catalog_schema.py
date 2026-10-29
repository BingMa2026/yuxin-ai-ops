from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl

SpeechProtocol = Literal["openai_transcriptions", "qwen_asr", "qwen_realtime", "dashscope_asr", "dashscope_realtime"]


class SpeechPriceItem(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    unit: Literal["second", "10k_characters", "million_tokens", "voice"]
    price: Decimal = Field(ge=0, le=1000000, decimal_places=8)


class SpeechPricing(BaseModel):
    region: str = Field(min_length=1, max_length=80)
    currency: Literal["CNY"] = "CNY"
    source_url: HttpUrl | None = None
    verified_at: str = Field(min_length=10, max_length=40)
    items: list[SpeechPriceItem] = Field(min_length=1, max_length=16)
    note: str = Field(default="", max_length=500)
