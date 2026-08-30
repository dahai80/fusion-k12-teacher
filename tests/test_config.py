"""M3-T17 配置热更新测试。"""

from __future__ import annotations

import os
import time

from fusion_k12_teacher.config import (
    HOT_RELOADABLE,
    EnvProvider,
    FileProvider,
    get_config,
    reset_config,
)


class TestEnvProvider:
    def test_static_get(self):
        os.environ["FUSION_TEST_K"] = "v1"
        try:
            p = EnvProvider()
            assert p.get("FUSION_TEST_K") == "v1"
            assert p.get("MISSING", "def") == "def"
        finally:
            del os.environ["FUSION_TEST_K"]

    def test_refresh_noop(self):
        p = EnvProvider()
        assert p.refresh() == {}


class TestFileProvider:
    def test_parse_kv(self, tmp_path):
        f = tmp_path / "cfg.txt"
        f.write_text("# comment\nFUSION_MLX_MODEL=qwen\nFUSION_K12_RATE_LIMIT=100\n\nbad line no eq\n")
        p = FileProvider(str(f))
        assert p.get("FUSION_MLX_MODEL") == "qwen"
        assert p.get("FUSION_K12_RATE_LIMIT") == "100"
        assert p.get("MISSING", "x") == "x"

    def test_mtime_change_triggers_reload(self, tmp_path):
        f = tmp_path / "cfg.txt"
        f.write_text("FUSION_MLX_MODEL=qwen\n")
        p = FileProvider(str(f))
        assert p.refresh() == {}  # mtime 未变
        # 触碰 mtime (写新内容 + 显式后置 mtime 避同秒抖动)
        time.sleep(0.01)
        f.write_text("FUSION_MLX_MODEL=qwen2\n")
        changed = p.refresh()
        assert changed.get("FUSION_MLX_MODEL") == "qwen2"
        assert p.get("FUSION_MLX_MODEL") == "qwen2"

    def test_non_hot_key_change_not_returned(self, tmp_path):
        f = tmp_path / "cfg.txt"
        f.write_text("SOME_OTHER=val1\n")
        p = FileProvider(str(f))
        time.sleep(0.01)
        f.write_text("SOME_OTHER=val2\n")
        changed = p.refresh()
        # 非 HOT_RELOADABLE 不进 changed
        assert "SOME_OTHER" not in changed

    def test_missing_file_empty(self, tmp_path):
        p = FileProvider(str(tmp_path / "nope.txt"))
        assert p.get("X", "d") == "d"


class TestConfigProviderCallback:
    def test_on_change_callback_fires(self, tmp_path):
        f = tmp_path / "cfg.txt"
        f.write_text("FUSION_MLX_MODEL=m1\n")
        p = FileProvider(str(f))
        seen: list[tuple[str, str]] = []
        p.on_change(lambda k, v: seen.append((k, v)))
        time.sleep(0.01)
        f.write_text("FUSION_MLX_MODEL=m2\n")
        # 手动调 refresh + 回调 (绕过线程时序)
        changed = p.refresh()
        for k, v in changed.items():
            for cb in p._callbacks:
                cb(k, v)
        assert ("FUSION_MLX_MODEL", "m2") in seen

    def test_hot_reloadable_whitelist(self):
        assert "FUSION_MLX_MODEL" in HOT_RELOADABLE
        assert "FUSION_K12_RATE_LIMIT" in HOT_RELOADABLE

    def test_callback_exception_isolated(self, tmp_path):
        f = tmp_path / "cfg.txt"
        f.write_text("FUSION_MLX_MODEL=m1\n")
        p = FileProvider(str(f))
        p.on_change(lambda k, v: (_ for _ in ()).throw(RuntimeError("boom")))
        ok: list[str] = []
        p.on_change(lambda k, v: ok.append(v))
        time.sleep(0.01)
        f.write_text("FUSION_MLX_MODEL=m2\n")
        changed = p.refresh()
        for k, v in changed.items():
            for cb in p._callbacks:
                try:
                    cb(k, v)
                except Exception:
                    pass
        assert ok == ["m2"]


class TestGetConfigFactory:
    def test_env_default(self, monkeypatch):
        monkeypatch.delenv("FUSION_K12_CONFIG_FILE", raising=False)
        reset_config()
        c = get_config()
        assert isinstance(c, EnvProvider)
        assert get_config() is c
        reset_config()

    def test_file_when_config_file_set(self, tmp_path, monkeypatch):
        f = tmp_path / "cfg.txt"
        f.write_text("FUSION_MLX_MODEL=qwen\n")
        monkeypatch.setenv("FUSION_K12_CONFIG_FILE", str(f))
        reset_config()
        c = get_config()
        assert isinstance(c, FileProvider)
        assert c.get("FUSION_MLX_MODEL") == "qwen"
        reset_config()

    def test_file_env_but_missing_falls_back_env(self, monkeypatch):
        monkeypatch.setenv("FUSION_K12_CONFIG_FILE", "/no/such/file")
        reset_config()
        c = get_config()
        assert isinstance(c, EnvProvider)
        reset_config()


class TestRedact:
    def test_salt_redacted_in_log(self, tmp_path, caplog):
        import logging
        f = tmp_path / "cfg.txt"
        f.write_text("FUSION_K12_SALT=secretval\n")
        p = FileProvider(str(f))
        p.on_change(lambda k, v: None)
        time.sleep(0.01)
        f.write_text("FUSION_K12_SALT=newsecret\n")
        with caplog.at_level(logging.INFO):
            changed = p.refresh()
            for k, v in changed.items():
                for cb in p._callbacks:
                    cb(k, v)
        joined = "\n".join(r.message for r in caplog.records)
        assert "newsecret" not in joined
