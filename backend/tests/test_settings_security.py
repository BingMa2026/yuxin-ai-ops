import pytest
from pydantic import ValidationError

from app.config.setting import Settings


def test_production_rejects_default_or_short_secret_key() -> None:
    with pytest.raises(ValidationError, match="至少32位"):
        Settings(_env_file=None, ENVIRONMENT="prod", SECRET_KEY="too-short")


def test_production_accepts_explicit_strong_secret_key() -> None:
    configured = Settings(
        _env_file=None,
        ENVIRONMENT="prod",
        SECRET_KEY="production-secret-key-with-more-than-32-characters",
    )

    assert configured.ENVIRONMENT.value == "prod"
