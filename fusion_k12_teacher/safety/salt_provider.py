"""SaltProvider — anonymization salt source abstraction (M1-T7).

v1.3.0 anonymizer._resolve_salt inlined env/file/random three-way resolution,
not extensible. v2.0 abstracts it into SaltProvider, supporting standalone
(env/file) and cluster (config center + Redis cache).

Implementations:
- EnvSaltProvider: FUSION_K12_SALT env (standalone)
- FileSaltProvider: FUSION_K12_SALT_FILE (standalone, 0600)
- ConfigCenterSaltProvider: Redis cache (TTL 300s), miss falls back to the
  config center (cluster)

Selection: get_salt_provider() picks by FUSION_K12_SALT_PROVIDER; the default
chain is env→file→random fallback (preserves v1.3.0 standalone behavior).
Redis is an optional dependency; a missing install raises a clear ImportError.
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
    """Salt source abstraction — get_salt() returns the currently active salt."""

    @abstractmethod
    def get_salt(self) -> str:
        """Return the current salt."""

    def close(self) -> None:
        """Release resources (Redis connections etc.). No-op by default."""


class EnvSaltProvider(SaltProvider):
    # Standalone: salt comes from the FUSION_K12_SALT env var

    def __init__(self, env_var: str = _SALT_ENV):
        self._env_var = env_var

    def get_salt(self) -> str:
        salt = os.environ.get(self._env_var, "")
        if not salt:
            logger.warning("EnvSaltProvider: %s not configured", self._env_var)
        return salt


class FileSaltProvider(SaltProvider):
    # Standalone: salt comes from a file (0600), env FUSION_K12_SALT_FILE overrides the path

    def __init__(self, path: str | None = None):
        self._path = path or os.environ.get(_SALT_FILE_ENV, _DEFAULT_SALT_FILE)

    def get_salt(self) -> str:
        try:
            with open(self._path, encoding="utf-8") as f:
                salt = f.read().strip()
            if salt:
                return salt
            logger.warning("FileSaltProvider: salt file is empty: %s", self._path)
        except FileNotFoundError:
            logger.warning("FileSaltProvider: salt file does not exist: %s", self._path)
        except OSError as e:
            logger.warning("FileSaltProvider: failed to read salt file: %s", e)
        return ""


class ConfigCenterSaltProvider(SaltProvider):
    # Cluster: Redis caches the salt (TTL 300s), miss falls back to the config
    # center HTTP endpoint.
    # redis is an optional dependency; missing install raises ImportError.
    # Note: the real config center URL is given by FUSION_K12_CONFIG_CENTER_URL;
    # here we read from Redis directly for now.

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
            raise ImportError("ConfigCenterSaltProvider requires FUSION_K12_REDIS_URL")
        try:
            import redis
        except ImportError as e:
            raise ImportError(
                "Cluster salt requires redis: pip install redis"
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
            logger.warning("ConfigCenterSaltProvider: no salt in Redis (key=%s), the config center must write it", self._cache_key)
            return ""
        self._cached_salt = salt
        self._cached_ts = now
        return salt

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception as e:
                logger.warning("Failed to close Redis salt connection: %s", e)
            self._client = None


class RandomFallbackSaltProvider(SaltProvider):
    # Standalone fallback: generate a random salt when none is explicitly
    # configured (cross-node divergence risk, standalone only).

    def __init__(self, path: str | None = None):
        self._path = path or os.environ.get(_SALT_FILE_ENV, _DEFAULT_SALT_FILE)
        self._salt: str | None = None

    def get_salt(self) -> str:
        if self._salt is not None:
            return self._salt
        # Prefer the already-persisted random salt (consistent across
        # instances/restarts)
        try:
            with open(self._path, encoding="utf-8") as f:
                existing = f.read().strip()
            if existing:
                self._salt = existing
                return existing
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning("Failed to read existing random salt file: %s", e)
        self._salt = secrets.token_hex(16)
        logger.error(
            "Anonymization salt is not explicitly configured "
            "(FUSION_K12_SALT/FUSION_K12_SALT_FILE), "
            "falling back to a node-local random salt. Multi-node deployments "
            "will produce inconsistent student IDs across nodes; "
            "distribute a unified salt file or set the env var."
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
            logger.warning("Failed to persist random salt file, using in-process salt: %s", e)
        return self._salt


class VersionedSaltProvider(SaltProvider):
    # M1-T8: versioned salt — the current salt is used for new writes, historic
    # versions are kept to resolve old IDs.
    # The salt file stores the current value; archive files salt.vN store
    # history (N = version number).
    # rotate() generates a new salt, archives the current one under the next
    # version number, and writes the new value to the main file.

    def __init__(self, path: str | None = None):
        self._path = path or os.environ.get(_SALT_FILE_ENV, _DEFAULT_SALT_FILE)
        self._cached: str | None = None

    def get_salt(self) -> str:
        if self._cached is not None:
            return self._cached
        try:
            with open(self._path, encoding="utf-8") as f:
                salt = f.read().strip()
            if salt:
                self._cached = salt
                return salt
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning("VersionedSaltProvider read failed: %s", e)
        # No salt → generate and persist (same logic as RandomFallback)
        self._cached = secrets.token_hex(16)
        self._write_current(self._cached)
        return self._cached

    def _write_current(self, salt: str) -> None:
        try:
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            fd = os.open(
                self._path,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
                0o600,
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(salt)
        except OSError as e:
            logger.warning("VersionedSaltProvider write failed: %s", e)

    def _archive_versions(self) -> list[tuple[int, str]]:
        """Archived historic versions [(version, salt)] ascending (excluding current)."""
        import re
        versions: list[tuple[int, str]] = []
        d = os.path.dirname(self._path) or "."
        base = os.path.basename(self._path)
        try:
            for name in os.listdir(d):
                m = re.fullmatch(re.escape(base) + r"\.v(\d+)", name)
                if not m:
                    continue
                try:
                    with open(os.path.join(d, name), encoding="utf-8") as f:
                        s = f.read().strip()
                    if s:
                        versions.append((int(m.group(1)), s))
                except OSError:
                    continue
        except OSError:
            pass
        versions.sort()
        return versions

    def current_version(self) -> int:
        archived = self._archive_versions()
        return (max(v for v, _ in archived) + 1) if archived else 1

    def list_versions(self) -> list[tuple[int, str]]:
        """Return [(version, salt)] ascending — historic archives + current (current is the highest version)."""
        versions = self._archive_versions()
        cur_ver = self.current_version()
        versions.append((cur_ver, self.get_salt()))
        return versions

    def get_salt_for_version(self, version: int) -> str:
        """Fetch a historic salt by version — used to resolve old IDs."""
        for v, s in self.list_versions():
            if v == version:
                return s
        logger.warning("salt version %d does not exist, falling back to current salt", version)
        return self.get_salt()

    def rotate(self) -> tuple[int, str]:
        """Rotate the salt — archive the current one under its version number,
        generate a new salt and write the main file (version number +1).

        Returns (new version, new salt). Old versions are kept for
        get_salt_for_version to look up historic IDs.
        """
        cur_ver = self.current_version()
        cur = self.get_salt()
        archive_path = f"{self._path}.v{cur_ver}"
        try:
            os.makedirs(os.path.dirname(archive_path) or ".", exist_ok=True)
            fd = os.open(
                archive_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(cur)
        except OSError as e:
            logger.warning("Failed to archive old salt (v%d): %s", cur_ver, e)
        new_salt = secrets.token_hex(16)
        self._write_current(new_salt)
        self._cached = new_salt
        new_ver = cur_ver + 1
        logger.info("salt rotated: old v%d archived, new current v%d", cur_ver, new_ver)
        return new_ver, new_salt



class _ExplicitSaltProvider(SaltProvider):
    def __init__(self, salt: str):
        self._salt = salt

    def get_salt(self) -> str:
        return self._salt


def get_salt_provider(explicit: str = "") -> SaltProvider:
    """Pick a salt provider by env — explicit salt wins, otherwise
    FUSION_K12_SALT_PROVIDER selects.

    Default chain: env → file → random fallback (preserves v1.3.0 standalone
    behavior). Non-empty explicit returns _ExplicitSaltProvider directly
    (compatible with config.salt injection).
    """
    if explicit:
        logger.info("Using explicitly injected salt (config.salt)")
        return _ExplicitSaltProvider(explicit)
    kind = os.environ.get(_PROVIDER_ENV, "chain").lower()
    if kind == "env":
        return EnvSaltProvider()
    if kind == "file":
        return FileSaltProvider()
    if kind == "configcenter":
        return ConfigCenterSaltProvider()
    # Default chain: use env if set, else file if set, else random fallback
    env_salt = os.environ.get(_SALT_ENV, "")
    if env_salt:
        return EnvSaltProvider()
    file_prov = FileSaltProvider()
    if file_prov.get_salt():
        return file_prov
    return RandomFallbackSaltProvider()
