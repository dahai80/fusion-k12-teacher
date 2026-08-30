"""SaltProvider — 脱敏 salt 来源抽象 (M1-T7)。

v1.3.0 anonymizer._resolve_salt 内联 env/file/random 三路解析, 不可扩展。
v2.0 抽象为 SaltProvider, 支持单机 (env/file) 与集群 (配置中心 + Redis 缓存)。

实现:
- EnvSaltProvider: FUSION_K12_SALT env (单机)
- FileSaltProvider: FUSION_K12_SALT_FILE (单机, 0600)
- ConfigCenterSaltProvider: Redis 缓存 (TTL 300s), miss 回源配置中心 (集群)

选型: get_salt_provider() 按 FUSION_K12_SALT_PROVIDER 选, 缺省链式 env→file→随机回退
(保持 v1.3.0 单机行为)。Redis 可选依赖, 缺失抛清晰 ImportError。
"""

from __future__ import annotations

import logging
import os
import secrets
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

_SALT_ENV = "FUSION_K12_SALT"
_SALT_FILE_ENV = "FUSION_K12_SALT_FILE"
_PROVIDER_ENV = "FUSION_K12_SALT_PROVIDER"
_DEFAULT_SALT_FILE = os.path.expanduser("~/.fusion-k12/salt")


class SaltProvider(ABC):
    """salt 来源抽象 — get_salt() 返回当前生效 salt。"""

    @abstractmethod
    def get_salt(self) -> str:
        """返回当前 salt。"""

    def close(self) -> None:
        """释放资源 (Redis 连接等)。默认空。"""


class EnvSaltProvider(SaltProvider):
    # 单机: salt 来自 FUSION_K12_SALT env

    def __init__(self, env_var: str = _SALT_ENV):
        self._env_var = env_var

    def get_salt(self) -> str:
        salt = os.environ.get(self._env_var, "")
        if not salt:
            logger.warning("EnvSaltProvider: %s 未配置", self._env_var)
        return salt


class FileSaltProvider(SaltProvider):
    # 单机: salt 来自文件 (0600), env FUSION_K12_SALT_FILE 覆盖路径

    def __init__(self, path: str | None = None):
        self._path = path or os.environ.get(_SALT_FILE_ENV, _DEFAULT_SALT_FILE)

    def get_salt(self) -> str:
        try:
            with open(self._path, encoding="utf-8") as f:
                salt = f.read().strip()
            if salt:
                return salt
            logger.warning("FileSaltProvider: salt 文件为空: %s", self._path)
        except FileNotFoundError:
            logger.warning("FileSaltProvider: salt 文件不存在: %s", self._path)
        except OSError as e:
            logger.warning("FileSaltProvider: 读取 salt 文件失败: %s", e)
        return ""


class ConfigCenterSaltProvider(SaltProvider):
    # 集群: Redis 缓存 salt (TTL 300s), miss 回源配置中心 HTTP endpoint。
    # redis 可选依赖, 缺失抛 ImportError。
    # 注: 真实配置中心 URL 由 FUSION_K12_CONFIG_CENTER_URL 指定; 此处先 Redis 直读。

    def __init__(
        self,
        redis_url: str | None = None,
        cache_key: str = "fusion:k12:salt",
        ttl: int = 300,
    ):
        self._redis_url = redis_url or os.environ.get("FUSION_K12_REDIS_URL", "")
        self._cache_key = cache_key
        self._ttl = ttl
        self._client = None
        self._cached_salt: str | None = None
        self._cached_ts: float = 0.0

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        if not self._redis_url:
            raise ImportError("ConfigCenterSaltProvider 需 FUSION_K12_REDIS_URL")
        try:
            import redis
        except ImportError as e:
            raise ImportError(
                "集群 salt 需 redis: pip install redis"
            ) from e
        self._client = redis.Redis.from_url(self._redis_url, decode_responses=True)
        return self._client

    def get_salt(self) -> str:
        import time
        now = time.monotonic()
        if self._cached_salt is not None and (now - self._cached_ts) < self._ttl:
            return self._cached_salt
        client = self._ensure_client()
        salt = client.get(self._cache_key)
        if not salt:
            logger.warning("ConfigCenterSaltProvider: Redis 无 salt (key=%s), 须配置中心写入", self._cache_key)
            return ""
        self._cached_salt = salt
        self._cached_ts = now
        return salt

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception as e:
                logger.warning("关闭 Redis salt 连接失败: %s", e)
            self._client = None


class RandomFallbackSaltProvider(SaltProvider):
    # 单机回退: 无显式 salt 时生成随机 salt (跨节点断链风险, 仅单机可用)。

    def __init__(self, path: str | None = None):
        self._path = path or os.environ.get(_SALT_FILE_ENV, _DEFAULT_SALT_FILE)
        self._salt: str | None = None

    def get_salt(self) -> str:
        if self._salt is not None:
            return self._salt
        # 优先读已持久化的随机 salt (跨实例/重启一致)
        try:
            with open(self._path, encoding="utf-8") as f:
                existing = f.read().strip()
            if existing:
                self._salt = existing
                return existing
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning("读取已有随机 salt 文件失败: %s", e)
        self._salt = secrets.token_hex(16)
        logger.error(
            "脱敏 salt 未显式配置(FUSION_K12_SALT/FUSION_K12_SALT_FILE), "
            "回退到本节点随机 salt。多节点部署将致同一学生跨节点 ID 不一致, "
            "须分发统一 salt 文件或设环境变量。"
        )
        try:
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            fd = os.open(
                self._path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(self._salt)
        except OSError as e:
            logger.warning("持久化随机 salt 文件失败, 用进程内 salt: %s", e)
        return self._salt


class _ExplicitSaltProvider(SaltProvider):
    def __init__(self, salt: str):
        self._salt = salt

    def get_salt(self) -> str:
        return self._salt


def get_salt_provider(explicit: str = "") -> SaltProvider:
    """按 env 选 salt provider — 显式 salt 优先, 否则 FUSION_K12_SALT_PROVIDER 选型。

    缺省链式: env → file → 随机回退 (保持 v1.3.0 单机行为)。
    explicit 非空直接返 _ExplicitSaltProvider (兼容 config.salt 注入)。
    """
    if explicit:
        logger.info("使用显式注入 salt (config.salt)")
        return _ExplicitSaltProvider(explicit)
    kind = os.environ.get(_PROVIDER_ENV, "chain").lower()
    if kind == "env":
        return EnvSaltProvider()
    if kind == "file":
        return FileSaltProvider()
    if kind == "configcenter":
        return ConfigCenterSaltProvider()
    # 缺省链式: env 有值用 env, 否则 file 有值用 file, 否则随机回退
    env_salt = os.environ.get(_SALT_ENV, "")
    if env_salt:
        return EnvSaltProvider()
    file_prov = FileSaltProvider()
    if file_prov.get_salt():
        return file_prov
    return RandomFallbackSaltProvider()

