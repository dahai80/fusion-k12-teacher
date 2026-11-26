"""Union Web shell registration — issue #30 (PRD R-3, aligned with
cowork/agent-studio shell_registry).

At serve startup, registers web/manifest.json with the fusion-gateway shell
registry (POST /api/v1/shell/manifests, fg-key auth) and keeps it alive with
periodic heartbeats (after heartbeat_timeout the gateway greys out the menu
entry). Env gated — requires both:
- FUSION_SHELL_GATEWAY_URL + FUSION_ADMIN_KEY
Optional FUSION_SHELL_MANIFEST overrides the manifest path, FUSION_K12_WEB_UPSTREAM
overrides the deployment-specific port. Silently skipped when unconfigured
(default OFF, does not affect local standalone).
The /shell/fusion-k12-teacher/ dynamic proxy is established by the gateway
per manifest.upstream.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

GATEWAY_URL_ENV = "FUSION_SHELL_GATEWAY_URL"
MANIFEST_PATH_ENV = "FUSION_SHELL_MANIFEST"
UPSTREAM_OVERRIDE_ENV = "FUSION_K12_WEB_UPSTREAM"
REGISTER_INTERVAL_SECONDS = 15.0
HTTP_TIMEOUT_SECONDS = 5.0

# Persistence path (0600) for the fm- module key issued by the gateway. The
# static env key remains a supported override path;
# after gateway issuance the file overrides the env value (heartbeats
# authenticate with the issued key).
MODULE_KEY_PATH = Path.home() / ".fusion-k12" / "web_module_key"


def load_module_key() -> str:
    try:
        return MODULE_KEY_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def save_module_key(key: str) -> bool:
    key = (key or "").strip()
    if not key:
        return False
    MODULE_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    MODULE_KEY_PATH.write_text(key + "\n", encoding="utf-8")
    MODULE_KEY_PATH.chmod(0o600)
    logger.info("Gateway-issued module key persisted: %s (%s)", MODULE_KEY_PATH, _mask_key(key))
    return True


def _mask_key(key: str) -> str:
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}****{key[-4:]}"


def _extract_issued_key(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    for field in ("raw_key", "api_key", "issued_key", "key", "module_key"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    nested = payload.get("data")
    if isinstance(nested, dict):
        for field in ("raw_key", "api_key", "issued_key", "key", "module_key"):
            value = nested.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _default_manifest_path() -> Path:
    return Path(__file__).resolve().parent.parent / "web" / "manifest.json"


def _gateway_admin_key() -> str:
    # issue #35: admin key single-point resolution goes through
    # fusion_core.config.admin_key (canonical name FUSION_ADMIN_KEY, the
    # prod-missing RuntimeError is contained inside fusion-core). On a bare
    # install without fusion-core, fall back to the canonical name only; do
    # not duplicate the alias chain in this repo.
    try:
        from fusion_core.config import admin_key

        return admin_key()
    except ImportError:
        key = os.environ.get("FUSION_ADMIN_KEY", "")
        if not key:
            logger.warning("FUSION_ADMIN_KEY not set: shell gateway registration unavailable (request it from the fusion-gateway admin API)")
        return key


def shell_registration_enabled() -> bool:
    # Short-circuit when the URL is unconfigured, without triggering admin key
    # resolution (the prod-missing-key RuntimeError is only a config error
    # when registration is actually intended)
    if not os.environ.get(GATEWAY_URL_ENV, "").strip():
        return False
    return bool(_gateway_admin_key().strip())


def load_manifest() -> dict[str, Any]:
    path = Path(os.environ.get(MANIFEST_PATH_ENV, "").strip() or _default_manifest_path())
    if not path.exists():
        raise FileNotFoundError(f"shell manifest not found: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not manifest.get("id"):
        raise ValueError(f"shell manifest missing id: {path}")
    # manifest declares the default upstream; env overrides the
    # deployment-specific port; api_key is injected via the runtime variable
    # pointed to by api_key_env (empty value is not injected, not persisted) —
    # when env is unconfigured, api_key is not sent with the registration body;
    # the gateway (K1) issues an fm- key and returns it once in the response.
    override = os.environ.get(UPSTREAM_OVERRIDE_ENV, "").strip()
    if override:
        manifest["upstream"] = override
    if not manifest.get("upstream"):
        manifest["upstream"] = "http://127.0.0.1:11448"
    key_env = str(manifest.get("api_key_env", "")).strip()
    api_key = os.environ.get(key_env, "").strip() if key_env else ""
    if api_key:
        manifest["api_key"] = api_key
    else:
        manifest.pop("api_key", None)
    logger.info(
        "shell manifest loaded: %s (id=%s upstream=%s api_key=%s)",
        path,
        manifest["id"],
        manifest["upstream"],
        "set" if api_key else "unset",
    )
    return manifest


async def _registry_loop_body(client: Any, manifest: dict[str, Any], interval: float) -> None:
    module_id = str(manifest["id"])
    gateway = os.environ.get(GATEWAY_URL_ENV, "").strip().rstrip("/")
    admin_key = _gateway_admin_key().strip()
    admin_headers = {"Authorization": f"Bearer {admin_key}", "Content-Type": "application/json"}
    registered = False
    while True:
        try:
            if not registered:
                resp = await client.post(
                    f"{gateway}/api/v1/shell/manifests", json=manifest, headers=admin_headers
                )
                if resp.status_code == 200:
                    registered = True
                    logger.info("shell manifest registered: %s", module_id)
                    issued = _extract_issued_key(_safe_json(resp))
                    if issued and issued != load_module_key():
                        save_module_key(issued)
                    elif issued:
                        logger.info("Gateway-issued key matches the stored value, not persisting again")
                else:
                    logger.warning(
                        "shell manifest registration failed: %s %s", resp.status_code, resp.text[:200]
                    )
            else:
                # Heartbeats authenticate with the issued fm- key; fall back to
                # the admin key when nothing was issued.
                # Re-read from disk every beat, so on-disk edits converge to the
                # gateway registry within one heartbeat cycle;
                # on re-read failure keep the version from registration time and
                # do not interrupt the keep-alive heartbeat.
                module_key = load_module_key()
                beat_key = module_key or admin_key
                headers = {
                    "Authorization": f"Bearer {beat_key}",
                    "Content-Type": "application/json",
                }
                try:
                    beat_manifest = load_manifest()
                except Exception as e:
                    logger.warning("shell heartbeat manifest re-read failed, keeping registration-time version: %s", e)
                    beat_manifest = manifest
                resp = await client.post(
                    f"{gateway}/api/v1/shell/manifests/{module_id}/heartbeat",
                    json=beat_manifest,
                    headers=headers,
                )
                if resp.status_code == 404:
                    logger.info("shell heartbeat 404, re-registering %s", module_id)
                    registered = False
                elif resp.status_code == 401 and module_key:
                    logger.warning("shell heartbeat 401 (issued key invalid), re-registering %s", module_id)
                    registered = False
                elif resp.status_code == 403 and module_key:
                    # Gateway #261: the issued key is returned only once and
                    # re-registration does not echo it back — after expiry,
                    # re-registering cannot retrieve a new key either. 403
                    # heartbeat_forbidden = local key invalid/corrupted; discard
                    # it and fall back to admin-key heartbeats (the gateway
                    # always accepts), self-healing on the next beat.
                    logger.warning("shell heartbeat 403 (local issued key invalid), discarding and falling back to admin key")
                    try:
                        MODULE_KEY_PATH.unlink(missing_ok=True)
                    except OSError as e:
                        logger.warning("Failed to delete issued key file: %s", e)
                elif resp.status_code != 200:
                    raise RuntimeError(f"shell heartbeat failed: {resp.status_code} {resp.text[:200]}")
        except asyncio.CancelledError:
            logger.info("shell registration loop cancelled (module=%s)", module_id)
            raise
        except Exception as e:
            logger.warning("shell registration loop error (will retry): %s", e)
        await asyncio.sleep(interval)


def _safe_json(resp: Any) -> Any:
    try:
        return resp.json()
    except Exception:
        return None


async def shell_registry_loop(
    client: Any = None, interval: float = REGISTER_INTERVAL_SECONDS
) -> None:
    """Register once, keep alive via heartbeats; re-register after a gateway
    restart (404). Failures only warn and retry, never affecting the service."""
    try:
        manifest = load_manifest()
    except Exception as e:
        logger.error("shell registration disabled (manifest unavailable): %s", e)
        return
    if client is None:
        import httpx

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as own:
            await _registry_loop_body(own, manifest, interval)
    else:
        await _registry_loop_body(client, manifest, interval)
