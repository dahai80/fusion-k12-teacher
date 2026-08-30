"""SaltProvider 测试 — M1-T7。"""

from __future__ import annotations

import pytest

from fusion_k12_teacher.safety.salt_provider import (
    ConfigCenterSaltProvider,
    EnvSaltProvider,
    FileSaltProvider,
    RandomFallbackSaltProvider,
    SaltProvider,
    get_salt_provider,
)


class TestEnvSaltProvider:
    def test_reads_env(self, monkeypatch):
        monkeypatch.setenv("FUSION_K12_SALT", "envsalt123")
        p = EnvSaltProvider()
        assert p.get_salt() == "envsalt123"

    def test_empty_env_warns(self, monkeypatch):
        monkeypatch.delenv("FUSION_K12_SALT", raising=False)
        assert EnvSaltProvider().get_salt() == ""


class TestFileSaltProvider:
    def test_reads_file(self, tmp_path):
        f = tmp_path / "salt"
        f.write_text("filesalt456\n")
        assert FileSaltProvider(str(f)).get_salt() == "filesalt456"

    def test_missing_file(self, tmp_path):
        assert FileSaltProvider(str(tmp_path / "nope")).get_salt() == ""

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty"
        f.write_text("")
        assert FileSaltProvider(str(f)).get_salt() == ""


class TestRandomFallbackSaltProvider:
    def test_generates_persistent(self, tmp_path):
        path = str(tmp_path / "rand")
        salt1 = RandomFallbackSaltProvider(path).get_salt()
        assert len(salt1) == 32  # token_hex(16)
        # 文件已写, 第二次读应一致
        salt2 = RandomFallbackSaltProvider(path).get_salt()
        assert salt2 == salt1

    def test_cached_in_process(self, tmp_path):
        p = RandomFallbackSaltProvider(str(tmp_path / "r2"))
        assert p.get_salt() == p.get_salt()


class TestConfigCenterSaltProvider:
    def test_missing_redis_url_raises(self, monkeypatch):
        monkeypatch.delenv("FUSION_K12_REDIS_URL", raising=False)
        with pytest.raises(ImportError, match="REDIS_URL"):
            ConfigCenterSaltProvider().get_salt()

    def test_missing_redis_lib_raises(self, monkeypatch):
        # redis 未安装 (cluster extras 不含 redis), 应抛清晰 ImportError
        monkeypatch.setenv("FUSION_K12_REDIS_URL", "redis://localhost:6379")
        with pytest.raises(ImportError, match="redis"):
            ConfigCenterSaltProvider().get_salt()


class TestGetSaltProvider:
    def test_explicit_injection(self):
        p = get_salt_provider("mysalt")
        assert isinstance(p, SaltProvider)
        assert p.get_salt() == "mysalt"

    def test_chain_env_first(self, monkeypatch, tmp_path):
        monkeypatch.setenv("FUSION_K12_SALT", "envfirst")
        monkeypatch.setenv("FUSION_K12_SALT_FILE", str(tmp_path / "f"))
        p = get_salt_provider()
        assert p.get_salt() == "envfirst"

    def test_chain_file_when_no_env(self, monkeypatch, tmp_path):
        monkeypatch.delenv("FUSION_K12_SALT", raising=False)
        f = tmp_path / "f"
        f.write_text("filefallback")
        monkeypatch.setenv("FUSION_K12_SALT_FILE", str(f))
        p = get_salt_provider()
        assert p.get_salt() == "filefallback"

    def test_explicit_provider_env(self, monkeypatch):
        monkeypatch.setenv("FUSION_K12_SALT_PROVIDER", "env")
        monkeypatch.setenv("FUSION_K12_SALT", "viaenv")
        assert get_salt_provider().get_salt() == "viaenv"

    def test_file_provider_explicit(self, monkeypatch, tmp_path):
        f = tmp_path / "s"
        f.write_text("explicitfile")
        monkeypatch.setenv("FUSION_K12_SALT_PROVIDER", "file")
        monkeypatch.setenv("FUSION_K12_SALT_FILE", str(f))
        assert get_salt_provider().get_salt() == "explicitfile"


class TestAnonymizerUsesProvider:
    def test_anonymizer_picks_env_salt(self, monkeypatch):
        # M1-T7: DataAnonymizer 经 get_salt_provider 取 salt
        monkeypatch.setenv("FUSION_K12_SALT", "unified-salt")
        from fusion_k12_teacher.desensitize import DataAnonymizer, DesensitizeConfig

        anon = DataAnonymizer(DesensitizeConfig())
        assert anon.salt == "unified-salt"
        # 同 salt → 同名同 ID (跨节点一致前提)
        anon2 = DataAnonymizer(DesensitizeConfig())
        assert anon.anonymize_name("张三") == anon2.anonymize_name("张三")
