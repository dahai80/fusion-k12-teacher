"""Union Web shell 注册 — issue #30 (PRD R-3, 对齐 cowork/agent-studio shell_registry)。

serve 启动时向 fusion-gateway shell 注册表注册 web/manifest.json
(POST /api/v1/shell/manifests, fg-key auth) 并周期心跳保活
(heartbeat_timeout 后网关置灰菜单)。env 门控 — 需同时配置:
- FUSION_SHELL_GATEWAY_URL + FUSION_ADMIN_KEY
可选 FUSION_SHELL_MANIFEST 覆盖 manifest 路径, FUSION_K12_WEB_UPSTREAM
覆盖部署特定端口。未配置则静默跳过 (默认 OFF, 不影响本地 standalone)。
/shell/fusion-k12-teacher/ 动态代理由网关按 manifest.upstream 建立。
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

# 网关签发 fm- 模块密钥落盘路径 (0600)。静态 env 密钥作为覆盖路径向后兼容;
# 网关签发后文件覆盖 env 值 (心跳鉴权用签发密钥)。
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
    logger.info("网关签发模块密钥已持久化: %s (%s)", MODULE_KEY_PATH, _mask_key(key))
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
    # issue #35: admin key 单点解析走 fusion_core.config.admin_key (规范名
    # FUSION_ADMIN_KEY, prod 缺失 RuntimeError 在 fusion-core 内收敛)。裸装无
    # fusion-core 时回退只认规范名, 不在本仓重复别名链。
    try:
        from fusion_core.config import admin_key

        return admin_key()
    except ImportError:
        key = os.environ.get("FUSION_ADMIN_KEY", "")
        if not key:
            logger.warning("FUSION_ADMIN_KEY 未设置: shell 网关注册不可用 (向 fusion-gateway admin API 索取)")
        return key


def shell_registration_enabled() -> bool:
    # URL 未配置时短路, 不触发 admin key 解析 (prod 缺 key 的 RuntimeError 只在
    # 明确要注册时才是配置错误)
    if not os.environ.get(GATEWAY_URL_ENV, "").strip():
        return False
    return bool(_gateway_admin_key().strip())


def load_manifest() -> dict[str, Any]:
    path = Path(os.environ.get(MANIFEST_PATH_ENV, "").strip() or _default_manifest_path())
    if not path.exists():
        raise FileNotFoundError(f"shell manifest 不存在: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not manifest.get("id"):
        raise ValueError(f"shell manifest 缺少 id: {path}")
    # manifest 声明默认 upstream; env 覆盖部署特定端口; api_key 经
    # api_key_env 指向的运行时变量注入 (空值不注入, 不落盘) — env 未配置时
    # 不随注册体发送 api_key, 网关 (K1) 签发 fm- 密钥并在响应中返回一次。
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
        "shell manifest 已加载: %s (id=%s upstream=%s api_key=%s)",
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
                    logger.info("shell manifest 已注册: %s", module_id)
                    issued = _extract_issued_key(_safe_json(resp))
                    if issued and issued != load_module_key():
                        save_module_key(issued)
                    elif issued:
                        logger.info("网关签发密钥与已存值一致, 不重复落盘")
                else:
                    logger.warning(
                        "shell manifest 注册失败: %s %s", resp.status_code, resp.text[:200]
                    )
            else:
                # 心跳改用签发 fm- 密钥鉴权; 未签发时回退 admin key。
                # 每拍重读磁盘, 磁盘编辑一个心跳周期内收敛到网关注册表;
                # 重读失败沿用注册时版本, 不中断心跳保活。
                module_key = load_module_key()
                beat_key = module_key or admin_key
                headers = {
                    "Authorization": f"Bearer {beat_key}",
                    "Content-Type": "application/json",
                }
                try:
                    beat_manifest = load_manifest()
                except Exception as e:
                    logger.warning("shell 心跳重读 manifest 失败, 沿用注册时版本: %s", e)
                    beat_manifest = manifest
                resp = await client.post(
                    f"{gateway}/api/v1/shell/manifests/{module_id}/heartbeat",
                    json=beat_manifest,
                    headers=headers,
                )
                if resp.status_code == 404:
                    logger.info("shell 心跳 404, 重注册 %s", module_id)
                    registered = False
                elif resp.status_code == 401 and module_key:
                    logger.warning("shell 心跳 401 (签发密钥失效), 重注册 %s", module_id)
                    registered = False
                elif resp.status_code == 403 and module_key:
                    # 网关 #261: 签发密钥只返回一次, 重注册不回显 — 失效后重注册
                    # 也拿不回新 key。403 heartbeat_forbidden = 本地 key 失效/污染,
                    # 丢弃后回退 admin key 心跳 (网关恒接受), 下拍自愈。
                    logger.warning("shell 心跳 403 (本地签发密钥失效), 丢弃并回退 admin key")
                    try:
                        MODULE_KEY_PATH.unlink(missing_ok=True)
                    except OSError as e:
                        logger.warning("签发密钥文件删除失败: %s", e)
                elif resp.status_code != 200:
                    raise RuntimeError(f"shell 心跳失败: {resp.status_code} {resp.text[:200]}")
        except asyncio.CancelledError:
            logger.info("shell 注册循环已取消 (module=%s)", module_id)
            raise
        except Exception as e:
            logger.warning("shell 注册循环错误 (将重试): %s", e)
        await asyncio.sleep(interval)


def _safe_json(resp: Any) -> Any:
    try:
        return resp.json()
    except Exception:
        return None


async def shell_registry_loop(
    client: Any = None, interval: float = REGISTER_INTERVAL_SECONDS
) -> None:
    """注册一次, 心跳保活; 网关重启 (404) 后重注册。失败仅告警重试, 不影响服务。"""
    try:
        manifest = load_manifest()
    except Exception as e:
        logger.error("shell 注册禁用 (manifest 不可用): %s", e)
        return
    if client is None:
        import httpx

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as own:
            await _registry_loop_body(own, manifest, interval)
    else:
        await _registry_loop_body(client, manifest, interval)
