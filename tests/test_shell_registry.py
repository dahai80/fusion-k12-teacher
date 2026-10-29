"""#30: Union Web shell 网关注册 — env 门控 / manifest 加载 / 注册-心跳-重注册循环。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    for var in (
        "FUSION_SHELL_GATEWAY_URL",
        "FUSION_ADMIN_KEY",
        "FUSION_SHELL_MANIFEST",
        "FUSION_K12_WEB_UPSTREAM",
        "FUSION_K12_WEB_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    # 签发密钥落盘路径隔离到 tmp — 防止 fixture 密钥污染真实 ~/.fusion-k12/
    from fusion_k12_teacher import shell_registry

    monkeypatch.setattr(shell_registry, "MODULE_KEY_PATH", tmp_path / "web_module_key")


def _manifest(tmp_path: Path) -> Path:
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps({"id": "fusion-k12-teacher", "title": "t"}), encoding="utf-8")
    return p


def _env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FUSION_SHELL_GATEWAY_URL", "http://127.0.0.1:22432")
    monkeypatch.setenv("FUSION_ADMIN_KEY", "fg-admin")
    monkeypatch.setenv("FUSION_SHELL_MANIFEST", str(_manifest(tmp_path)))


class TestGating:
    def test_disabled_without_env(self):
        from fusion_k12_teacher.shell_registry import shell_registration_enabled

        assert shell_registration_enabled() is False

    def test_enabled_with_both_envs(self, monkeypatch):
        from fusion_k12_teacher.shell_registry import shell_registration_enabled

        monkeypatch.setenv("FUSION_SHELL_GATEWAY_URL", "http://127.0.0.1:11432")
        monkeypatch.setenv("FUSION_ADMIN_KEY", "fg-admin")
        assert shell_registration_enabled() is True

    def test_enabled_requires_admin_key(self, monkeypatch):
        from fusion_k12_teacher.shell_registry import shell_registration_enabled

        monkeypatch.setenv("FUSION_SHELL_GATEWAY_URL", "http://127.0.0.1:11432")
        assert shell_registration_enabled() is False


class TestManifestLoad:
    def test_load_default_repo_manifest(self):
        from fusion_k12_teacher.shell_registry import load_manifest

        m = load_manifest()
        assert m["id"] == "fusion-k12-teacher"
        assert m["category"] == "domain"
        assert m["upstream"] == "http://127.0.0.1:11448"
        assert m["entry"] == "/shell/fusion-k12-teacher/"
        assert "api_key" not in m  # 未配 FUSION_K12_WEB_API_KEY 不注入

    def test_missing_file_raises(self, monkeypatch, tmp_path):
        from fusion_k12_teacher.shell_registry import load_manifest

        monkeypatch.setenv("FUSION_SHELL_MANIFEST", str(tmp_path / "nope.json"))
        with pytest.raises(FileNotFoundError):
            load_manifest()

    def test_missing_id_raises(self, monkeypatch, tmp_path):
        from fusion_k12_teacher.shell_registry import load_manifest

        p = tmp_path / "manifest.json"
        p.write_text(json.dumps({"title": "t"}), encoding="utf-8")
        monkeypatch.setenv("FUSION_SHELL_MANIFEST", str(p))
        with pytest.raises(ValueError):
            load_manifest()

    def test_upstream_env_override(self, monkeypatch, tmp_path):
        from fusion_k12_teacher.shell_registry import load_manifest

        _env(monkeypatch, tmp_path)
        monkeypatch.setenv("FUSION_K12_WEB_UPSTREAM", "http://10.0.0.5:11448")
        m = load_manifest()
        assert m["upstream"] == "http://10.0.0.5:11448"

    def test_api_key_injected_from_env(self, monkeypatch, tmp_path):
        from fusion_k12_teacher.shell_registry import load_manifest

        p = tmp_path / "manifest.json"
        p.write_text(
            json.dumps(
                {"id": "fusion-k12-teacher", "title": "t", "api_key_env": "FUSION_K12_WEB_API_KEY"}
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("FUSION_SHELL_MANIFEST", str(p))
        monkeypatch.setenv("FUSION_K12_WEB_API_KEY", "k12-web-key")
        m = load_manifest()
        assert m["api_key"] == "k12-web-key"


class TestRegistryLoop:
    def test_register_then_heartbeat_then_reregister_on_404(self, monkeypatch, tmp_path):
        from fusion_k12_teacher.shell_registry import shell_registry_loop

        _env(monkeypatch, tmp_path)
        calls: list[tuple[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append((request.method, request.url.path))
            if request.url.path == "/api/v1/shell/manifests":
                if len([c for c in calls if c[1] == "/api/v1/shell/manifests"]) == 1:
                    return httpx.Response(200, json={"raw_key": "fm-issued-1"})
                return httpx.Response(200, json={})
            if request.url.path == "/api/v1/shell/manifests/fusion-k12-teacher/heartbeat":
                # 第 1 拍 200, 第 2 拍 404 → 触发重注册
                beats = [c for c in calls if c[1].endswith("/heartbeat")]
                if len(beats) <= 1:
                    return httpx.Response(200, json={})
                return httpx.Response(404, json={})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)

        async def _go():
            task = asyncio.create_task(
                shell_registry_loop(client=httpx.AsyncClient(transport=transport), interval=0.01)
            )
            for _ in range(200):
                await asyncio.sleep(0.01)
                registers = [c for c in calls if c[1] == "/api/v1/shell/manifests"]
                if len(registers) >= 2:
                    break
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            assert len([c for c in calls if c[1] == "/api/v1/shell/manifests"]) >= 2
            assert any(c[1].endswith("/heartbeat") for c in calls)

        asyncio.run(_go())

    def test_register_failure_retries_not_fatal(self, monkeypatch, tmp_path):
        from fusion_k12_teacher.shell_registry import shell_registry_loop

        _env(monkeypatch, tmp_path)
        attempts: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            attempts.append(1)
            return httpx.Response(500, text="boom")

        transport = httpx.MockTransport(handler)

        async def _go():
            task = asyncio.create_task(
                shell_registry_loop(client=httpx.AsyncClient(transport=transport), interval=0.01)
            )
            for _ in range(50):
                await asyncio.sleep(0.01)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            assert len(attempts) >= 2  # 失败后持续重试, 未崩溃退出

        asyncio.run(_go())

    def test_manifest_missing_disables_loop(self, monkeypatch, tmp_path):
        from fusion_k12_teacher.shell_registry import shell_registry_loop

        monkeypatch.setenv("FUSION_SHELL_GATEWAY_URL", "http://127.0.0.1:22432")
        monkeypatch.setenv("FUSION_ADMIN_KEY", "fg-admin")
        monkeypatch.setenv("FUSION_SHELL_MANIFEST", str(tmp_path / "nope.json"))

        async def _go():
            # manifest 缺失 → 直接返回, 不抛
            await shell_registry_loop(
                client=httpx.AsyncClient(
                    transport=httpx.MockTransport(lambda r: httpx.Response(200))
                )
            )

        asyncio.run(_go())

    def test_issued_key_persisted_and_used_for_heartbeat(self, monkeypatch, tmp_path):
        from fusion_k12_teacher import shell_registry
        from fusion_k12_teacher.shell_registry import shell_registry_loop

        _env(monkeypatch, tmp_path)
        key_path = tmp_path / "web_module_key"
        monkeypatch.setattr(shell_registry, "MODULE_KEY_PATH", key_path)

        seen_auth: list[str] = []
        state = {"registered": False}

        def handler(request: httpx.Request) -> httpx.Response:
            seen_auth.append(request.headers.get("authorization", ""))
            if request.url.path == "/api/v1/shell/manifests":
                state["registered"] = True
                return httpx.Response(200, json={"raw_key": "fm-issued-abc"})
            if request.url.path == "/api/v1/shell/manifests/fusion-k12-teacher/heartbeat":
                # 心跳必须用签发密钥而非 admin key
                assert seen_auth[-1] == "Bearer fm-issued-abc", seen_auth[-1]
                return httpx.Response(200, json={})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)

        async def _go():
            task = asyncio.create_task(
                shell_registry_loop(client=httpx.AsyncClient(transport=transport), interval=0.01)
            )
            for _ in range(200):
                await asyncio.sleep(0.01)
                if any(a == "Bearer fm-issued-abc" for a in seen_auth):
                    break
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            assert state["registered"]
            assert key_path.exists()
            assert any(a == "Bearer fm-issued-abc" for a in seen_auth)

        asyncio.run(_go())

    def test_heartbeat_403_drops_stale_key_and_falls_back_to_admin(self, monkeypatch, tmp_path):
        from fusion_k12_teacher import shell_registry
        from fusion_k12_teacher.shell_registry import shell_registry_loop

        _env(monkeypatch, tmp_path)
        key_path = tmp_path / "web_module_key"
        key_path.write_text("fm-stale\n", encoding="utf-8")
        monkeypatch.setattr(shell_registry, "MODULE_KEY_PATH", key_path)

        seen_auth: list[str] = []
        beats: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_auth.append(request.headers.get("authorization", ""))
            if request.url.path == "/api/v1/shell/manifests":
                # 重注册不回显 raw_key (网关 K1: 只发一次)
                return httpx.Response(200, json={})
            if request.url.path == "/api/v1/shell/manifests/fusion-k12-teacher/heartbeat":
                beats.append(seen_auth[-1])
                if seen_auth[-1] == "Bearer fm-stale":
                    return httpx.Response(403, json={"code": "heartbeat_forbidden"})
                return httpx.Response(200, json={})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)

        async def _go():
            task = asyncio.create_task(
                shell_registry_loop(client=httpx.AsyncClient(transport=transport), interval=0.01)
            )
            for _ in range(300):
                await asyncio.sleep(0.01)
                if "Bearer fg-admin" in beats:
                    break
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            # 失效 key 被 403 拒 → 丢弃文件 → 下拍用 admin key 自愈
            assert "Bearer fm-stale" in beats
            assert "Bearer fg-admin" in beats
            assert not key_path.exists()

        asyncio.run(_go())
