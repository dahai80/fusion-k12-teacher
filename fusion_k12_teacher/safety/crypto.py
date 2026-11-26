"""AES-256-GCM encryption utilities — M1-T5.

Encrypts PII (name_map) at rest, without relying on file permissions.
data_key source: env FUSION_K12_DATA_KEY (hex/base64, 32 bytes) or
                 file FUSION_K12_DATA_KEY_FILE (mode 600, 32 raw bytes or hex).
cryptography is an optional dependency (cluster extras); if missing, raise —
encryption must never degrade to plaintext (hard security constraint).
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
    """Encryption/decryption failure."""


def _load_key() -> bytes:
    """Load the 32-byte data_key from env/file.

    Prefers env FUSION_K12_DATA_KEY (hex or base64),
    then FUSION_K12_DATA_KEY_FILE (raw 32 bytes or a hex line).
    Short keys are derived to 32 bytes via sha256 (supports human-memorable
    passphrases; not best practice but usable).
    """
    raw = os.environ.get("FUSION_K12_DATA_KEY", "")
    source = "env"
    if not raw:
        path = os.environ.get("FUSION_K12_DATA_KEY_FILE", "")
        if not path:
            raise CryptoError(
                "data_key not configured — set FUSION_K12_DATA_KEY or FUSION_K12_DATA_KEY_FILE "
                "(install: pip install -e '.[cluster]')"
            )
        source = "file"
        try:
            with open(path, encoding="utf-8") as f:
                raw = f.read().strip()
        except OSError as e:
            raise CryptoError(f"Failed to read data_key file: {e}") from e
        # File permission check (Unix)
        if os.name == "posix":
            mode = os.stat(path).st_mode & 0o777
            if mode & 0o077:
                logger.warning("data_key file permission %o too broad, 0600 recommended: %s", mode, path)

    # Try hex → base64 → raw
    key: bytes
    try:
        key = bytes.fromhex(raw)
    except ValueError:
        try:
            key = base64.b64decode(raw, validate=True)
        except Exception:
            key = raw.encode("utf-8")

    if len(key) < _KEY_LEN:
        # Short key derivation — stretch to 32 bytes via sha256
        logger.info("data_key (%s) length %d < 32, deriving via sha256", source, len(key))
        key = hashlib.sha256(key).digest()
    elif len(key) > _KEY_LEN:
        key = key[:_KEY_LEN]
    logger.info("data_key loaded (source=%s, len=%d)", source, len(key))
    return key


class DataCipher:
    """AES-256-GCM cipher — built lazily, key loaded on first use.

    Ciphertext format: base64(nonce(12) || ciphertext || tag(16))
    """

    def __init__(self):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as e:
            raise ImportError(
                "cryptography required for encryption: pip install -e '.[cluster]'"
            ) from e
        self._AESGCM = AESGCM
        self._key: bytes | None = None

    def _aes(self):
        if self._key is None:
            self._key = _load_key()
        return self._AESGCM(self._key)

    def encrypt(self, plaintext: str, aad: bytes | None = None) -> str:
        """Encrypt a string → base64 ciphertext (nonce included)."""
        import os as _os
        aes = self._aes()
        nonce = _os.urandom(12)
        ct = aes.encrypt(nonce, plaintext.encode("utf-8"), aad)
        return base64.b64encode(nonce + ct).decode("ascii")

    def decrypt(self, ciphertext: str, aad: bytes | None = None) -> str:
        """Decrypt base64 ciphertext → plaintext."""
        try:
            blob = base64.b64decode(ciphertext, validate=True)
        except Exception as e:
            raise CryptoError(f"Failed to base64-decode ciphertext: {e}") from e
        if len(blob) < 12 + 16:
            raise CryptoError("Ciphertext too short (nonce+tag)")
        nonce, ct = blob[:12], blob[12:]
        aes = self._aes()
        try:
            pt = aes.decrypt(nonce, ct, aad)
        except Exception as e:
            raise CryptoError(f"Decryption failed (key mismatch or corrupted ciphertext): {e}") from e
        return pt.decode("utf-8")

    def encrypt_dict(self, obj: dict[str, Any], fields: list[str]) -> dict[str, Any]:
        """Encrypt the given fields of a dict (returns a copy), leaving other fields untouched."""
        import copy
        out = copy.deepcopy(obj)
        for f in fields:
            if f in out and out[f] is not None:
                out[f] = self.encrypt(str(out[f]))
        return out

    def decrypt_dict(self, obj: dict[str, Any], fields: list[str]) -> dict[str, Any]:
        """Decrypt the given fields of a dict (returns a copy)."""
        import copy
        out = copy.deepcopy(obj)
        for f in fields:
            if f in out and out[f] is not None:
                try:
                    out[f] = self.decrypt(str(out[f]))
                except CryptoError:
                    # Not ciphertext (legacy plaintext data) — keep as-is for progressive migration
                    logger.debug("Field %s is not ciphertext, keeping original value", f)
        return out
