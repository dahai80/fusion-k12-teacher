# M1 基础底座实施报告 (v2.0.0a0)

**日期**: 2026-08-30  
**版本**: v1.3.0 → v2.0.0a0  
**里程碑**: M1 基础底座 (T1-T9 全部完成)

## 概述

M1 为 v2.0 企业级集群架构奠基: 持久化解耦 (Repository 抽象) + PII 加密 + salt 统一分发与轮换 + 单机→集群迁移。单机 (standalone) 行为完全向后兼容 v1.3.0; 集群 (cluster) 模式为可选增强。

## 任务清单

| 任务 | 内容 | 文件 |
|------|------|------|
| T1 | Repository 抽象 + SQLite 后端 | `repository/base.py`, `sqlite_repo.py`, `__init__.py` |
| T2 | Postgres asyncpg 后端 + factory | `postgres_repo.py`, `factory.py` |
| T3 | migrate CLI (单机→集群) | `cli.py` |
| T4 | factory 完整 (standalone/cluster/fallback) | `factory.py` (T2 内完成) |
| T5 | AES-256-GCM 加密工具 | `safety/crypto.py` |
| T6 | 加密 name_map 存取 | `sqlite_repo.py`, `postgres_repo.py` |
| T7 | SaltProvider 抽象 + 三实现 | `safety/salt_provider.py` |
| T8 | salt 轮换 + 版本化 | `safety/salt_provider.py`, `cli.py` |
| T9 | 单机→集群迁移加密脚本 | `cli.py` |

## 架构

```
FUSION_K12_MODE=standalone (默认)
  → SQLiteRepository (~/.fusion-k12/k12.db, stdlib sqlite3, WAL)
  → 明文 name_map (兼容 v1.3.0) 或加密 (配 FUSION_K12_DATA_KEY)
  → salt: env / file / 随机回退

FUSION_K12_MODE=cluster
  → PostgresRepository (FUSION_K12_PG_DSN, asyncpg 连接池)
  → 加密 name_map (name_hash + name_encrypted, AES-256-GCM)
  → salt: ConfigCenterSaltProvider (Redis 缓存 TTL 300s)
```

业务层面向 `Repository` 接口编程, 不感知后端; 工厂按 `FUSION_K12_MODE` 注入。

## 关键设计

### 可选依赖不阻塞单机
- `asyncpg` / `cryptography` / `redis` 均为 cluster extras, 惰性 import。
- 缺失 → 清晰 ImportError + 回退 SQLite/明文, 单机行为不受影响。
- `safety/__init__.py` 用 `__getattr__` 惰性导出 DataCipher, 缺 cryptography 不破坏包导入。

### PII 加密 (T5/T6)
- `DataCipher`: AES-256-GCM, key 来源 env `FUSION_K12_DATA_KEY` / file `FUSION_K12_DATA_KEY_FILE` (600)。
- 密文格式 `base64(nonce(12) || ct || tag(16))`, nonce 每次 `os.urandom` 随机。
- 短 key 用 sha256 派生到 32 字节。
- `decrypt_dict` 对非密文字段保持原样 (渐进迁移, 不报错)。
- name_map 加密: `name_hash`=sha256(map_key) 查询键 (无明文) + `name_encrypted`=AES-GCM(原名)。
- 解密失败回退明文 reverse 列, 不崩。

### salt 统一分发与轮换 (T7/T8)
- `SaltProvider` ABC: `EnvSaltProvider` / `FileSaltProvider` / `ConfigCenterSaltProvider` (Redis) / `RandomFallbackSaltProvider`。
- `get_salt_provider()`: `FUSION_K12_SALT_PROVIDER` 选型, 缺省链式 env→file→随机。
- `VersionedSaltProvider.rotate()`: 当前 salt 归档为 `salt.vN`, 生成新 salt; 旧版本保留供 `get_salt_for_version()` 回查历史脱敏 ID。
- CLI `rotate-salt`: 轮换 + `--show-versions` 查版本。

### 单机→集群迁移 (T3/T9)
- `migrate --from-db X --to-dsn Y [--encrypt]`: SQLite→Postgres, `--encrypt` 加密导入。
- `encrypt-name-map --db X`: 就地加密 standalone SQLite 旧明文 name_map。

## 测试

- **346 passed, 0 failed, 22 skipped** (cluster extras 已装; skipped = 需真实 Postgres/缺库场景)。
- 新增测试: `test_crypto.py` (10), `test_repository.py` 增 TestEncryptedNameMap (6) + T9 CLI (2), `test_salt_provider.py` (15), `test_salt_rotation.py` (10)。
- LLM 真实调用测试需 fusion-gateway (端口 11432) + `FUSION_MLX_API_KEY` (网关 key, 非 mlx key)。

## 向后兼容

- `FUSION_K12_MODE` 未设 = standalone, 行为同 v1.3.0。
- scheduler `repo` 参数可选 (None → 旧 JSON history)。
- anonymizer salt 来源经 `get_salt_provider`, 缺省链式保持原 `_resolve_salt` 行为。
- name_map 无 cipher = 明文 (v1.3.0 schema), 有 cipher = 加密列, 同表共存。

## 后续里程碑

- **M2**: 配置中心 + 服务发现 (Etcd/Consul), Redis 共享会话。
- **M3**: 多实例负载均衡, 无状态化, 健康检查与故障转移。
- **M4**: 可观测性 (Prometheus 指标 + 结构化日志 + 审计链路)。

见 `docs/v2-enterprise-arch-upgrade.md`。
