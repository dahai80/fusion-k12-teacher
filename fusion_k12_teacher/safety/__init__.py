"""安全模块 — 内容过滤 + 适龄审查 + 数据脱敏 + PII 加密 + salt 来源 (M1-T5/T7)。"""

from .age_checker import AgeChecker
from .filter import SAFETY_PROMPT_SUFFIX, ContentFilter
from .models import AgeRating, ContentCheckResult, FilterLevel
from .salt_provider import (
    ConfigCenterSaltProvider,
    EnvSaltProvider,
    FileSaltProvider,
    RandomFallbackSaltProvider,
    SaltProvider,
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
    "get_salt_provider",
]


def __getattr__(name):
    # M1-T5: DataCipher/CryptoError 惰性导出 — 缺 cryptography 不影响 import 包
    if name in ("DataCipher", "CryptoError"):
        from .crypto import CryptoError, DataCipher
        return {"DataCipher": DataCipher, "CryptoError": CryptoError}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
