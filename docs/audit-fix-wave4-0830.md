# 审计修复报告 Wave 4 — 2026-08-30 (P3 生产加固)

生产发布审计 (`~/fusion/audit/fusion-k12-audit-result-product-0830.md`) P3 级问题修复。本波聚焦生产加固与运维配套, 不改核心业务逻辑。

- Wave A (P0, 2 项) — 阻断商用
- Wave B (P1, 20 项) — 架构层
- Wave C (P2, ~50 项) — 工程实现
- Wave D (P3, 24 项) — 本报告, 版本 **v1.3.0**

## 修复统计

| 严重度 | 缺陷数 | 状态 |
|--------|--------|------|
| P0 阻断商用 | 2 | ✅ |
| P1 架构层 | 20 | ✅ |
| P2 工程实现 | ~50 | ✅ |
| P3 生产加固 | 24 | ✅ (v1.3.0) |

## 修复清单

### 上游依赖与版本约束
- **依赖上界钉死**: `httpx>=0.27.0,<1.0.0`、`pydantic>=2.0.0,<3.0.0` (pyproject.toml), 防 major 升级破坏 ABI。

### 运维配置可观测性
- **CLI serve 端口可配置**: `fusion-k12 serve --port` 默认 0 时回退 `FUSION_K12_PORT` env, 否则 11448 (cli.py)。
- **serve 日志统一配置**: 模块级 `_configure_logging()` dictConfig, 读 `LOG_LEVEL`/`FUSION_K12_LOG_LEVEL` env, 覆盖 uvicorn 路径 (serve.py)。
- **环境变量样例**: 新增 `.env.example`, 按组(后端/HTTP/数据/安全/调度)列全 env, deploy.md 配置表对齐。

### 持久化与并发健壮性
- **cron 任务重试**: `TaskScheduler._job` 按 `FUSION_K12_CRON_RETRIES`(默认1)重试, 退避 `1.0*(attempt+1)` 秒, 耗尽记 error 不静默丢 (scheduler.py)。
- **引擎构造失败连接池泄漏**: `build_engines` 构造抛错时关闭自有 mlx httpx 连接池 (`_owns_mlx` 守卫, 调用方传入不动), 异步 loop 调度 task, 同步 run_until_complete (engines.py)。
- **课标对齐缓存上限**: `StandardsAligner._max_cache` 读 `FUSION_K12_ALIGN_CACHE_MAX`(默认500), 超 LRU 弹最旧, 防 random-topic 撑爆内存 (aligner.py)。

### 错误边界与数据一致性
- **subject/exercise 错误边界**: `SubjectExercise` 增 `error: str = ""` 字段, 生成失败降级带 error; serve 路由 `_check_engine_error` 检测→502 (expert.py, serve.py)。
- **content flashcards/slides 空结果 502**: 路由分支 `if not result: raise HTTPException(502)` (serve.py)。
- **analytics 双扫合并**: `_calc_weak_points`/`_calc_strong_points` 原对 assessments 扫两遍, 合并为单趟 `_calc_point_stats` 统计后再派生, 公共签名保留供测试 (engine.py)。
- **课标 schema 迁移**: `standards/models.py` `_migrate_standard` + `_SUPPORTED_SCHEMA_VERSIONS={"1.0"}` 已就位, 不需改。

### API 路由补全
- **新增 `/api/standards/align`**: 课标对齐上下文 (knowledge_points/must_cover/optional_advanced/curriculum_codes/suggested_objectives/prerequisite_count)。
- **新增 `/api/standards/coverage`**: 课标覆盖报告 (total_points/covered_points/coverage_ratio/missing_points/details)。
- **测试覆盖**: `test_standards_align`、`test_standards_coverage` (test_serve.py)。

### 运维手册
- **deploy.md Runbook**: 轮换 API Key / 重启服务 / 更换推理模型 / 恢复备份 四场景; 配置表补齐全 env。

## 已知设计级限制 (acknowledged, 不编码)

| 项 | 说明 | 缓解 |
|----|------|------|
| scheduler `_history_lock` 串行 | 单进程串行写, 多任务并发吞吐受限 | 单机 CLI/API 场景够用; 多节点需外部队列 |
| `engines.load_all` CLI 阻塞 | CLI 启动同步加载课标 | 单用户 CLI 可接受; serve 异步 lifespan 不阻塞 |
| analytics 线性扫描无索引 | 大班级 O(n) 扫描 | 数据量受单班限制; 需大规模上 DB |
| `name_map` 明文存盘 | 脱敏映射表明文, 文件权限护 | 加密需设计级方案, 后续迭代 |
| env 运行时不可变 | 改配置需重启 | 生产标准做法; 运维流程覆盖 |

## 验证

```
ruff check .            → No issues found
pytest tests/ -q        → 295 passed, 19 skipped (live: FUSION_K12_LIVE_TESTS=1 → 32 passed)
```
