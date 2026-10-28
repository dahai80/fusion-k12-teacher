"""#34 (config Phase 2.2): 网关凭据/端口单点解析 — fusion_core.config 优先,
缺席回退语义等价旧 env 读取 (可选依赖约束, 见 CLAUDE.md)。"""

from __future__ import annotations

import sys

import pytest

from fusion_k12_teacher._keys import gateway_client_key, service_listen_port


def _drop_fusion_core_config(monkeypatch):
    # sys.modules 置 None → from fusion_core.config import ... 触发 ImportError
    monkeypatch.setitem(sys.modules, "fusion_core.config", None)


class TestClientKey:
    def test_no_key_no_header(self, monkeypatch):
        from fusion_k12_teacher.ai_client import MLXClient

        monkeypatch.delenv("FUSION_CLIENT_KEY", raising=False)
        monkeypatch.delenv("FUSION_MLX_API_KEY", raising=False)
        assert "Authorization" not in MLXClient()._auth_headers()

    def test_canonical_env_preferred(self, monkeypatch):
        # fusion_core 别名链: FUSION_CLIENT_KEY 优先于 legacy FUSION_MLX_API_KEY
        pytest.importorskip("fusion_core.config")
        from fusion_k12_teacher.ai_client import MLXClient

        monkeypatch.setenv("FUSION_CLIENT_KEY", "ck-canonical")
        monkeypatch.setenv("FUSION_MLX_API_KEY", "legacy-key")
        assert MLXClient()._auth_headers()["Authorization"] == "Bearer ck-canonical"

    def test_legacy_env_still_honored(self, monkeypatch):
        from fusion_k12_teacher.ai_client import MLXClient

        monkeypatch.delenv("FUSION_CLIENT_KEY", raising=False)
        monkeypatch.setenv("FUSION_MLX_API_KEY", "legacy-key")
        assert MLXClient()._auth_headers()["Authorization"] == "Bearer legacy-key"

    def test_fallback_without_fusion_core(self, monkeypatch):
        _drop_fusion_core_config(monkeypatch)
        monkeypatch.delenv("FUSION_CLIENT_KEY", raising=False)
        monkeypatch.setenv("FUSION_MLX_API_KEY", "fb-key")
        assert gateway_client_key() == "fb-key"

    def test_prod_missing_key_raises(self, monkeypatch):
        # config-conventions §3: prod 缺 secret 必须 RuntimeError, 不允许静默空值
        pytest.importorskip("fusion_core.config")
        monkeypatch.delenv("FUSION_CLIENT_KEY", raising=False)
        monkeypatch.delenv("FUSION_MLX_API_KEY", raising=False)
        monkeypatch.setenv("FUSION_PROFILE", "prod")
        with pytest.raises(RuntimeError, match="FUSION_CLIENT_KEY"):
            gateway_client_key()


class TestServiceListenPort:
    def test_default_port(self, monkeypatch):
        monkeypatch.delenv("FUSION_K12_TEACHER_PORT", raising=False)
        monkeypatch.delenv("FUSION_K12_PORT", raising=False)
        assert service_listen_port(11448) == 11448

    def test_canonical_env_preferred(self, monkeypatch):
        pytest.importorskip("fusion_core.config")
        monkeypatch.setenv("FUSION_K12_TEACHER_PORT", "21448")
        monkeypatch.setenv("FUSION_K12_PORT", "31448")
        assert service_listen_port(11448) == 21448

    def test_legacy_env_fallback(self, monkeypatch):
        pytest.importorskip("fusion_core.config")
        monkeypatch.delenv("FUSION_K12_TEACHER_PORT", raising=False)
        monkeypatch.setenv("FUSION_K12_PORT", "21448")
        assert service_listen_port(11448) == 21448

    def test_fallback_without_fusion_core(self, monkeypatch):
        _drop_fusion_core_config(monkeypatch)
        monkeypatch.delenv("FUSION_K12_TEACHER_PORT", raising=False)
        monkeypatch.setenv("FUSION_K12_PORT", "21448")
        assert service_listen_port(11448) == 21448

    def test_invalid_legacy_env_warns_not_crash(self, monkeypatch, caplog):
        monkeypatch.delenv("FUSION_K12_TEACHER_PORT", raising=False)
        monkeypatch.setenv("FUSION_K12_PORT", "abc")
        with caplog.at_level("WARNING"):
            assert service_listen_port(11448) == 11448
        assert any("FUSION_K12_PORT" in r.message for r in caplog.records)
