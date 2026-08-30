"""AES-256-GCM 加密工具 — M1-T5。

PII (name_map) 加密落盘, 不依赖文件权限。
data_key 来源: env FUSION_K12_DATA_KEY (hex/base64 32 字节) 或
               file FUSION_K12_DATA_KEY_FILE (600 权限, 32 字节原始或 hex)。
cryptography 可选依赖 (cluster extras), 缺失则 raise — 加密不可降级为明文 (安全硬约束)。
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_KEY_LEN = 32  # AES-256


class CryptoError(Exception):
    """加密/解密失败。"""


def _load_key() -> bytes:
    """从 env/file 加载 32 字节 data_key。

    优先 env FUSION_K12_DATA_KEY (hex 或 base64),
    其次 FUSION_K12_DATA_KEY_FILE (原始 32 字节或 hex 行)。
    短 key 用 sha256 派生到 32 字节 (兼容人类可记口令, 非最佳实践但可用)。
    """
    raw = os.environ.get("FUSION_K12_DATA_KEY", "")
    source = "env"
    if not raw:
        path = os.environ.get("FUSION_K12_DATA_KEY_FILE", "")
        if not path:
            raise CryptoError(
                "未配置 data_key — 设 FUSION_K12_DATA_KEY 或 FUSION_K12_DATA_KEY_FILE "
                "(安装: pip install -e '.[cluster]')"
            )
        source = "file"
        try:
            with open(path, encoding="utf-8") as f:
                raw = f.read().strip()
        except OSError as e:
            raise CryptoError(f"读取 data_key 文件失败: {e}") from e
        # 文件权限校验 (Unix)
        if os.name == "posix":
            mode = os.stat(path).st_mode & 0o777
            if mode & 0o077:
                logger.warning("data_key 文件权限 %o 过宽, 建议 0600: %s", mode, path)

    # 尝试 hex → base64 → 原始
    key: bytes
    try:
        key = bytes.fromhex(raw)
    except ValueError:
        try:
            key = base64.b64decode(raw, validate=True)
        except Exception:
            key = raw.encode("utf-8")

    if len(key) < _KEY_LEN:
        # 短 key 派生 — sha256 拉到 32 字节
        logger.info("data_key (%s) 长度 %d < 32, sha256 派生", source, len(key))
        key = hashlib.sha256(key).digest()
    elif len(key) > _KEY_LEN:
        key = key[:_KEY_LEN]
    logger.info("data_key 已加载 (来源=%s, len=%d)", source, len(key))
    return key


class DataCipher:
    """AES-256-GCM 加解密器 — 惰性建, 首次用加载 key。

    密文格式: base64(nonce(12) || ciphertext || tag(16))
    """

    def __init__(self):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as e:
            raise ImportError(
                "加密需 cryptography: pip install -e '.[cluster]'"
            ) from e
        self._AESGCM = AESGCM
        self._key: bytes | None = None

    def _aes(self):
        if self._key is None:
            self._key = _load_key()
        return self._AESGCM(self._key)

    def encrypt(self, plaintext: str, aad: bytes | None = None) -> str:
        """加密字符串 → base64 密文 (含 nonce)。"""
        import os as _os
        aes = self._aes()
        nonce = _os.urandom(12)
        ct = aes.encrypt(nonce, plaintext.encode("utf-8"), aad)
        return base64.b64encode(nonce + ct).decode("ascii")

    def decrypt(self, ciphertext: str, aad: bytes | None = None) -> str:
        """解密 base64 密文 → 原文。"""
        try:
            blob = base64.b64decode(ciphertext, validate=True)
        except Exception as e:
            raise CryptoError(f"密文 base64 解码失败: {e}") from e
        if len(blob) < 12 + 16:
            raise CryptoError("密文长度不足 (nonce+tag)")
        nonce, ct = blob[:12], blob[12:]
        aes = self._aes()
        try:
            pt = aes.decrypt(nonce, ct, aad)
        except Exception as e:
            raise CryptoError(f"解密失败 (key 不匹配或密文损坏): {e}") from e
        return pt.decode("utf-8")

    def encrypt_dict(self, obj: dict[str, Any], fields: list[str]) -> dict[str, Any]:
        """加密 dict 指定字段 (就地返回副本), 其余字段不动。"""
        import copy
        out = copy.deepcopy(obj)
        for f in fields:
            if f in out and out[f] is not None:
                out[f] = self.encrypt(str(out[f]))
        return out

    def decrypt_dict(self, obj: dict[str, Any], fields: list[str]) -> dict[str, Any]:
        """解密 dict 指定字段 (就地返回副本)。"""
        import copy
        out = copy.deepcopy(obj)
        for f in fields:
            if f in out and out[f] is not None:
                try:
                    out[f] = self.decrypt(str(out[f]))
                except CryptoError:
                    # 非密文 (历史明文数据) 保持原样, 兼容渐进迁移
                    logger.debug("字段 %s 非密文, 保持原值", f)
        return out
