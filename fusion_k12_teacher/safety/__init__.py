"""Safety module — content filtering + age-appropriateness review + data
desensitization + PII encryption + salt sourcing (M1-T5/T7)."""

from .age_checker import AgeChecker
from .filter import SAFETY_PROMPT_SUFFIX, ContentFilter
from .models import AgeRating, ContentCheckResult, FilterLevel
from .salt_provider import (
    ConfigCenterSaltProvider,
    EnvSaltProvider,
    FileSaltProvider,
    RandomFallbackSaltProvider,
    SaltProvider,
    VersionedSaltProvider,
    get_salt_provider,
)
from .wordlist import SensitiveWordList

__all__ = [
    "SAFETY_PROMPT_SUFFIX",
    "AgeChecker",
    "AgeRating",
    "ConfigCenterSaltProvider",
    "ContentCheckResult",
    "ContentFilter",
    "EnvSaltProvider",
    "FileSaltProvider",
    "FilterLevel",
    "RandomFallbackSaltProvider",
    "SaltProvider",
    "SensitiveWordList",
    "VersionedSaltProvider",
    "get_salt_provider",
]


def __getattr__(name):
    # M1-T5: DataCipher/CryptoError lazy export — missing cryptography does not break package import
    if name in ("DataCipher", "CryptoError"):
        from .crypto import CryptoError, DataCipher
        return {"DataCipher": DataCipher, "CryptoError": CryptoError}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
