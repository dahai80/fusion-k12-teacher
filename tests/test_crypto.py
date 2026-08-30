"""PII 加密工具测试 — M1-T5。"""

from __future__ import annotations

import os

import pytest

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False

pytestmark = pytest.mark.skipif(not _HAS_CRYPTO, reason="缺 cryptography, 安装: pip install -e '.[cluster]'")


def test_missing_cryptography_clear_error(monkeypatch):
    # M1-T5: cryptography 缺失 → DataCipher 抛清晰 ImportError (含 pip install 提示)
    monkeypatch.delenv("FUSION_K12_DATA_KEY", raising=False)
    monkeypatch.delenv("FUSION_K12_DATA_KEY_FILE", raising=False)
    import sys

    import fusion_k12_teacher.safety.crypto as crypto_mod

    if "cryptography" in sys.modules:
        pytest.skip("cryptography 已安装, 缺失场景无法复现")
    with pytest.raises(ImportError, match="cryptography"):
        crypto_mod.DataCipher()


@pytest.fixture
def cipher(monkeypatch, tmp_path):
    # 32 字节 hex key
    key_hex = "00" * 32
    monkeypatch.setenv("FUSION_K12_DATA_KEY", key_hex)
    from fusion_k12_teacher.safety import CryptoError, DataCipher
    return DataCipher(), CryptoError


class TestDataCipher:
    def test_encrypt_decrypt_roundtrip(self, cipher):
        dc, _ = cipher
        ct = dc.encrypt("张三")
        assert ct != "张三"
        pt = dc.decrypt(ct)
        assert pt == "张三"

    def test_ciphertext_unique_per_call(self, cipher):
        dc, _ = cipher
        ct1 = dc.encrypt("same")
        ct2 = dc.encrypt("same")
        # GCM nonce 随机, 同明文密文不同
        assert ct1 != ct2
        assert dc.decrypt(ct1) == dc.decrypt(ct2) == "same"

    def test_wrong_key_fails(self, cipher, monkeypatch):
        dc, CryptoError = cipher
        ct = dc.encrypt("secret")
        # 换 key 后同一 cipher 实例已缓存旧 key, 新实例用新 key 应解密失败
        monkeypatch.setenv("FUSION_K12_DATA_KEY", "ff" * 32)
        from fusion_k12_teacher.safety import DataCipher
        dc2 = DataCipher()
        with pytest.raises(CryptoError):
            dc2.decrypt(ct)

    def test_corrupt_ciphertext_fails(self, cipher):
        dc, CryptoError = cipher
        ct = dc.encrypt("data")
        # 篡改末尾字节
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
        obj = {"name": "李四", "phone": "13800000000", "id": "S001"}
        enc = dc.encrypt_dict(obj, ["name", "phone"])
        assert enc["name"] != "李四"
        assert enc["phone"] != "13800000000"
        assert enc["id"] == "S001"  # 未加密字段不动
        dec = dc.decrypt_dict(enc, ["name", "phone"])
        assert dec["name"] == "李四"
        assert dec["phone"] == "13800000000"
        assert dec["id"] == "S001"

    def test_decrypt_dict_plaintext_passthrough(self, cipher):
        # 历史明文数据渐进迁移: 非密文字段保持原样不报错
        dc, _ = cipher
        obj = {"name": "明文张三"}  # 未加密
        dec = dc.decrypt_dict(obj, ["name"])
        assert dec["name"] == "明文张三"
