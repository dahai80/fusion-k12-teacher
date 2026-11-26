# PII encryption utility tests — M1-T5.

from __future__ import annotations

import os

import pytest

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False

pytestmark = pytest.mark.skipif(not _HAS_CRYPTO, reason="cryptography missing, install: pip install -e '.[cluster]'")


def test_missing_cryptography_clear_error(monkeypatch):
    # M1-T5: cryptography missing → DataCipher raises a clear ImportError (with pip install hint)
    monkeypatch.delenv("FUSION_K12_DATA_KEY", raising=False)
    monkeypatch.delenv("FUSION_K12_DATA_KEY_FILE", raising=False)
    import sys

    import fusion_k12_teacher.safety.crypto as crypto_mod

    # Simulate cryptography missing: setting sys.modules entries to None makes the from-import raise ImportError
    for mod in (
        "cryptography",
        "cryptography.hazmat",
        "cryptography.hazmat.primitives",
        "cryptography.hazmat.primitives.ciphers",
        "cryptography.hazmat.primitives.ciphers.aead",
    ):
        monkeypatch.setitem(sys.modules, mod, None)
    with pytest.raises(ImportError, match="cryptography"):
        crypto_mod.DataCipher()


@pytest.fixture
def cipher(monkeypatch, tmp_path):
    # 32-byte hex key
    key_hex = "00" * 32
    monkeypatch.setenv("FUSION_K12_DATA_KEY", key_hex)
    from fusion_k12_teacher.safety import CryptoError, DataCipher
    return DataCipher(), CryptoError


class TestDataCipher:
    def test_encrypt_decrypt_roundtrip(self, cipher):
        dc, _ = cipher
        # i18n: user-facing
        ct = dc.encrypt("张三")
        assert ct != "张三"
        pt = dc.decrypt(ct)
        assert pt == "张三"

    def test_ciphertext_unique_per_call(self, cipher):
        dc, _ = cipher
        ct1 = dc.encrypt("same")
        ct2 = dc.encrypt("same")
        # GCM nonce is random: same plaintext, different ciphertext
        assert ct1 != ct2
        assert dc.decrypt(ct1) == dc.decrypt(ct2) == "same"

    def test_wrong_key_fails(self, cipher, monkeypatch):
        dc, CryptoError = cipher
        ct = dc.encrypt("secret")
        # After the key change, the same cipher instance has the old key cached; a new instance with the new key must fail to decrypt
        monkeypatch.setenv("FUSION_K12_DATA_KEY", "ff" * 32)
        from fusion_k12_teacher.safety import DataCipher
        dc2 = DataCipher()
        with pytest.raises(CryptoError):
            dc2.decrypt(ct)

    def test_corrupt_ciphertext_fails(self, cipher):
        dc, CryptoError = cipher
        ct = dc.encrypt("data")
        # Tamper with the trailing bytes
        corrupt = ct[:-2] + ("00" if not ct.endswith("00") else "11")
        with pytest.raises(CryptoError):
            dc.decrypt(corrupt)

    def test_short_key_derived(self, monkeypatch):
        monkeypatch.setenv("FUSION_K12_DATA_KEY", "shortpass")
        from fusion_k12_teacher.safety import DataCipher
        dc = DataCipher()
        ct = dc.encrypt("x")
        assert dc.decrypt(ct) == "x"

    def test_key_from_file(self, monkeypatch, tmp_path):
        keyfile = tmp_path / "key"
        keyfile.write_text("ab" * 32)
        os.chmod(keyfile, 0o600)
        monkeypatch.delenv("FUSION_K12_DATA_KEY", raising=False)
        monkeypatch.setenv("FUSION_K12_DATA_KEY_FILE", str(keyfile))
        from fusion_k12_teacher.safety import DataCipher
        dc = DataCipher()
        ct = dc.encrypt("fromfile")
        assert dc.decrypt(ct) == "fromfile"

    def test_no_key_raises(self, monkeypatch):
        monkeypatch.delenv("FUSION_K12_DATA_KEY", raising=False)
        monkeypatch.delenv("FUSION_K12_DATA_KEY_FILE", raising=False)
        from fusion_k12_teacher.safety import CryptoError, DataCipher
        dc = DataCipher()
        with pytest.raises(CryptoError, match="data_key"):
            dc.encrypt("nokey")

    def test_encrypt_decrypt_dict(self, cipher):
        dc, _ = cipher
        # i18n: user-facing
        obj = {"name": "李四", "phone": "13800000000", "id": "S001"}
        enc = dc.encrypt_dict(obj, ["name", "phone"])
        assert enc["name"] != "李四"
        assert enc["phone"] != "13800000000"
        assert enc["id"] == "S001"  # unencrypted fields untouched
        dec = dc.decrypt_dict(enc, ["name", "phone"])
        assert dec["name"] == "李四"
        assert dec["phone"] == "13800000000"
        assert dec["id"] == "S001"

    def test_decrypt_dict_plaintext_passthrough(self, cipher):
        # Gradual migration of legacy plaintext data: non-ciphertext fields pass through unchanged without error
        dc, _ = cipher
        # i18n: user-facing
        obj = {"name": "明文张三"}  # not encrypted
        dec = dc.decrypt_dict(obj, ["name"])
        assert dec["name"] == "明文张三"
