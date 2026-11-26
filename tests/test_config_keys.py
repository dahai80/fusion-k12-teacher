# #34 (config Phase 2.2): Single-point resolution of gateway credentials/port —
# fusion_core.config first, falling back to semantically equivalent legacy env
# reads when absent (optional-dependency constraint, see CLAUDE.md).

from __future__ import annotations

import sys

import pytest

from fusion_k12_teacher._keys import gateway_client_key, service_listen_port


def _drop_fusion_core_config(monkeypatch):
    # sys.modules set to None -> from fusion_core.config import ... raises ImportError
    monkeypatch.setitem(sys.modules, "fusion_core.config", None)


class TestClientKey:
    def test_no_key_no_header(self, monkeypatch):
        from fusion_k12_teacher.ai_client import MLXClient

        monkeypatch.delenv("FUSION_CLIENT_KEY", raising=False)
        monkeypatch.delenv("FUSION_MLX_API_KEY", raising=False)
        assert "Authorization" not in MLXClient()._auth_headers()

    def test_canonical_env_preferred(self, monkeypatch):
        # fusion_core alias chain: FUSION_CLIENT_KEY takes priority over legacy FUSION_MLX_API_KEY
        pytest.importorskip("fusion_core.config")
        from fusion_k12_teacher.ai_client import MLXClient

        monkeypatch.setenv("FUSION_CLIENT_KEY", "ck-canonical")
        monkeypatch.setenv("FUSION_MLX_API_KEY", "legacy-key")
        assert MLXClient()._auth_headers()["Authorization"] == "Bearer ck-canonical"

    def test_legacy_env_still_honored(self, monkeypatch):
        # the alias chain lives only in fusion_core — this test is meaningless without it
        pytest.importorskip("fusion_core.config")
        from fusion_k12_teacher.ai_client import MLXClient

        monkeypatch.delenv("FUSION_CLIENT_KEY", raising=False)
        monkeypatch.setenv("FUSION_MLX_API_KEY", "legacy-key")
        assert MLXClient()._auth_headers()["Authorization"] == "Bearer legacy-key"

    def test_fallback_without_fusion_core(self, monkeypatch):
        # issue #35: bare-install fallback only honors canonical FUSION_CLIENT_KEY
        _drop_fusion_core_config(monkeypatch)
        monkeypatch.delenv("FUSION_MLX_API_KEY", raising=False)
        monkeypatch.setenv("FUSION_CLIENT_KEY", "fb-key")
        assert gateway_client_key() == "fb-key"

    def test_fallback_ignores_legacy_env(self, monkeypatch):
        _drop_fusion_core_config(monkeypatch)
        monkeypatch.delenv("FUSION_CLIENT_KEY", raising=False)
        monkeypatch.setenv("FUSION_MLX_API_KEY", "legacy-key")
        assert gateway_client_key() == ""

    def test_prod_missing_key_raises(self, monkeypatch):
        # config-conventions §3: prod with a missing secret must raise RuntimeError, no silent empty value
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
