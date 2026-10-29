"""Conservative provider defaults used while importing a model directory.

Only exact model identifiers published by the provider are included here.  An
unknown model intentionally stays unpriced so an operator must verify its
commercial terms before enabling it.
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class OfficialPriceTier:
    context_min: int
    context_max: int | None
    input_cost_per_million: Decimal
    output_cost_per_million: Decimal


@dataclass(frozen=True, slots=True)
class OfficialModelPricing:
    context_length: int | None
    tiers: tuple[OfficialPriceTier, ...]


@dataclass(frozen=True, slots=True)
class DiscoveredModelCapabilities:
    context_length: int | None
    supports_stream: bool
    supports_vision: bool


def _tier(
    context_min: int,
    context_max: int | None,
    input_cost: str,
    output_cost: str,
) -> OfficialPriceTier:
    return OfficialPriceTier(
        context_min=context_min,
        context_max=context_max,
        input_cost_per_million=Decimal(input_cost),
        output_cost_per_million=Decimal(output_cost),
    )


_QWEN_PRICES: dict[str, OfficialModelPricing] = {}


def _register_qwen(
    model_ids: tuple[str, ...],
    context_length: int | None,
    *tiers: OfficialPriceTier,
) -> None:
    pricing = OfficialModelPricing(context_length=context_length, tiers=tuple(tiers))
    for model_id in model_ids:
        _QWEN_PRICES[model_id] = pricing


_register_qwen(
    ("qwen3.8-max", "qwen3.8-max-0902"),
    1_000_000,
    _tier(0, 1_000_000, "12", "36"),
)
_register_qwen(
    (
        "qwen3.7-max",
        "qwen3.7-max-2026-05-17",
        "qwen3.7-max-2026-05-20",
        "qwen3.7-max-2026-06-08",
    ),
    1_000_000,
    _tier(0, 1_000_000, "12", "36"),
)
_register_qwen(
    ("qwen3.6-max-preview",),
    262_144,
    _tier(0, 131_072, "9", "54"),
    _tier(131_073, 262_144, "15", "90"),
)
_register_qwen(
    ("qwen3-max", "qwen3-max-2026-01-23"),
    262_144,
    _tier(0, 32_768, "2.5", "10"),
    _tier(32_769, 131_072, "4", "16"),
    _tier(131_073, 262_144, "7", "28"),
)
_register_qwen(
    ("qwen3-max-preview", "qwen3-max-2025-09-23"),
    262_144,
    _tier(0, 32_768, "6", "24"),
    _tier(32_769, 131_072, "10", "40"),
    _tier(131_073, 262_144, "15", "60"),
)
_register_qwen(("qwen-max",), None, _tier(0, None, "2.4", "9.6"))

_register_qwen(
    ("qwen3.7-plus", "qwen3.7-plus-2026-05-26"),
    1_000_000,
    _tier(0, 262_144, "2", "8"),
    _tier(262_145, 1_000_000, "6", "24"),
)
_register_qwen(
    ("qwen3.6-plus", "qwen3.6-plus-2026-04-02"),
    1_000_000,
    _tier(0, 262_144, "2", "12"),
    _tier(262_145, 1_000_000, "8", "48"),
)
_register_qwen(
    ("qwen3.5-plus", "qwen3.5-plus-2026-02-15", "qwen3.5-plus-2026-04-20"),
    1_000_000,
    _tier(0, 131_072, "0.8", "4.8"),
    _tier(131_073, 262_144, "2", "12"),
    _tier(262_145, 1_000_000, "4", "24"),
)
_register_qwen(
    (
        "qwen-plus",
        "qwen-plus-latest",
        "qwen-plus-2025-12-01",
        "qwen-plus-2025-09-11",
        "qwen-plus-2025-07-28",
    ),
    1_000_000,
    _tier(0, 131_072, "0.8", "8"),
    _tier(131_073, 262_144, "2.4", "24"),
    _tier(262_145, 1_000_000, "4.8", "64"),
)
_register_qwen(
    ("qwen-long", "qwen-long-latest", "qwen-long-2025-01-25"),
    None,
    _tier(0, None, "0.5", "2"),
)
_register_qwen(
    ("qwen3.5-397b-a17b",),
    262_144,
    _tier(0, 131_072, "1.2", "7.2"),
    _tier(131_073, 262_144, "3", "18"),
)
_register_qwen(
    ("qwen3.5-122b-a10b",),
    262_144,
    _tier(0, 131_072, "0.8", "6.4"),
    _tier(131_073, 262_144, "2", "16"),
)
_register_qwen(
    ("qwen3.5-27b",),
    262_144,
    _tier(0, 131_072, "0.6", "4.8"),
    _tier(131_073, 262_144, "1.8", "14.4"),
)
_register_qwen(("qwen3.5-35b-a3b",), 131_072, _tier(0, 131_072, "0.4", "3.2"))
_register_qwen(("qwen-mt-plus",), None, _tier(0, None, "1.8", "5.4"))
_register_qwen(("qwen-mt-flash", "qwen-mt-turbo"), None, _tier(0, None, "0.7", "1.95"))
_register_qwen(("qwen-mt-lite",), None, _tier(0, None, "0.6", "1.6"))


_NON_CHAT_MARKERS = (
    "-asr",
    "-tts",
    "-audio",
    "-embedding",
    "-rerank",
    "-image",
    "image-edit",
    "speech-",
    "livetranslate",
    "realtime",
)


def official_model_pricing(provider_code: str, model_id: str) -> OfficialModelPricing | None:
    """Return an exact, provider-published default price or ``None``."""

    if provider_code.lower() != "qwen":
        return None
    return _QWEN_PRICES.get(model_id.strip().lower())


def discovered_model_capabilities(
    provider_code: str,
    model_id: str,
) -> DiscoveredModelCapabilities:
    """Infer only capabilities that are safe for the current chat gateway."""

    normalized = model_id.strip().lower()
    pricing = official_model_pricing(provider_code, normalized)
    incompatible_with_chat_gateway = normalized.startswith(("wan", "z-image")) or any(marker in normalized for marker in _NON_CHAT_MARKERS)
    supports_vision = not incompatible_with_chat_gateway and any(marker in normalized for marker in ("-vl", "vision", "omni"))
    return DiscoveredModelCapabilities(
        context_length=pricing.context_length if pricing else None,
        supports_stream=not incompatible_with_chat_gateway,
        supports_vision=supports_vision,
    )


__all__ = [
    "DiscoveredModelCapabilities",
    "OfficialModelPricing",
    "OfficialPriceTier",
    "discovered_model_capabilities",
    "official_model_pricing",
]
