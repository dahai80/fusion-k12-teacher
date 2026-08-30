# 审计修复报告 Wave 2 — 2026-08-30 (P1 架构层)

对抗式架构审计 (`~/fusion/audit/fusion-k12-teacher-audit-result-0830.md`, 44 项: 15 ARCH-HARD / 13 RUNTIME-RISK / 16 ENG-DEFECT) 分 3 波修复。本波 = Wave 2 P1 架构层缺陷, 8 项。

- Wave 1 (P0, 7 项) — 提交 `c4ad349`
- Wave 2 (P1, 8 项) — 本报告, 提交见末尾, 版本 **v1.1.0**
- Wave 3 (P2, ~16 项) — 待修

## 修复统计

| 严重度 | 缺陷数 | 状态 |
|--------|--------|------|
| P0 阻断商用 (Wave 1) | 7 | ✅ (c4ad349) |
| P1 架构层 (Wave 2) | 8 | ✅ |
| P2 工程实现 (Wave 3) | ~16 | 待修 |
| **合计** | **31+** | 进行中 |

## Wave 2 P1 修复明细 (8 项)

- **R1 — API key 冷启动不可热加载**: `serve.py` 原 `_API_KEY` 模块级常量, 进程启动读一次 env 后固化, 运行期换 key 不生效。改为 `require_api_key` 每次请求读 `FUSION_K12_API_KEY` env, 运行期换 key 即时生效。`test_serve.py` 补 fixture 保存/恢复 env 防泄漏。
- **A9 — 课标加载阻塞事件循环**: `serve.py` lifespan 原 `await build_engines()` 内含同步磁盘 `StandardsLoader.load_all()` (读 JSON 全量解析), 阻塞 asyncio 事件循环致启动期 health-check 卡死。改为 `bundle = await asyncio.to_thread(build_engines)`, 同步磁盘 I/O 卸到线程池, 事件循环不被阻塞。
- **A10 — align fallback 重复实现 CJK 匹配**: `standards/aligner.py` 原自带 `_cjk_tokens` + bigram 匹配, 与 `query.py` 的 `_word_match` 逻辑重复, 维护时改一漏一。改为 import `query._word_match`, fallback 路径复用同一整词匹配器, 单一实现。
- **A7 — AlignmentContext 每次重算 + 分组任务脱钩课标**: `StandardsAligner.align()` 无缓存, 同 subject/grade/topic 反复调反复算对齐。加 `self._cache` dict 按 (subject, grade, topic) 缓存 AlignmentContext。`group_tasks` 原不接受 standards_context, 分组任务与课标脱钩; 加 `standards_context` 参数, 生成分层课堂任务时注入对齐课标上下文。
- **R12 — 分层失败静默降级空层**: `DifferentiationEngine` 三层 gather 用 `return_exceptions=True`, 失败层仅 `logger.error` 后赋空 `LayerContent()`, 教师拿无感知空内容, 不知哪层失败。加 `DifferentiatedContent.layer_errors: dict[str,str]` 字段, 失败层记 `{"struggling": "..."}` 透出, `to_dict` 一并序列化。
- **A8 — analytics loader 每次重读文件**: `analytics/loader.py` `load_from_json`/`load_from_csv` 每调必重读重解析磁盘文件, 同文件反复导入重复开销。加 `_LOAD_CACHE` + `_cached_load(path, parser)`, 按 (resolved_path, mtime) 缓存解析结果; mtime 变则失效重读, OSError 取 mtime 则旁路缓存, 空结果不缓存。
- **A11 — serve analytics 端点失败仍返 200**: `serve.py` 有 `_check_engine_error` (转 502) 但 4 个 analytics 端点 (class-profile / student-profile / remedial / class-report) 从不调用, LLM 失败仍返 200 空对象, 前端误判成功。补 `_check_engine_error(result, label)` 调用, `.error` 字段置位则返 502。error-analysis 返 dict 无 `.error` 信号, 跳过 (安全)。
- **A12 — blanket except 吞非预期异常 + 无类型分类** (含 A11 共享层): 各引擎 `except Exception` 统一降级返默认 dataclass, 认证错 (LLM 401/403) 也被吞成"正常空结果", 运维无法区分 LLM 崩溃 vs 正常空输出。新增 `errors.py` 异常分类层: `NonDegradableError` (配置错/认证错 401/403, 必须上抛) vs `DegradableError` (解析失败/LLM 空返回/5xx 瞬态, 降级返默认 dataclass + `.error`)。`ai_client._chat_httpx` 在 `raise_for_status` 前调 `classify_http_status`, 401/403 → 抛 `NonDegradableError`。7 引擎各 `except Exception` 块加一行 `rethrow_if_fatal(e)` — 不可降级错上抛暴露 (CLI ClickException / serve 502), 可降级错继续降级。
- **A2 — 模块级全局多 worker 状态分区**: 引擎池为进程内模块级全局, 多 worker 各持一套致状态分区/内存翻倍。本地优先约束无进程外共享服务 (无 Redis/DB), 改 `cli.py serve` 加 fcntl `LOCK_EX|LOCK_NB` 单实例锁 + `workers=1`, 拒第二进程; 注释诚实说明横向扩展须先上外部共享状态 + 引擎池外置, 非本架构支持。

## 关键设计决策

### A12 分类边界 — 仅 401/403 不可降级, 5xx 可降级

审计 A12 原文非降级例仅列"配置错/认证错" (4xx auth)。初版实现把 5xx 也归 `NonDegradableError`, 但 5xx 是 LLM 服务端瞬态硬错 (网关抖动/模型未就绪), 引擎既有优雅降级契约本就覆盖此类 — 37 个降级容错测试 (`result.field == X OR "error" in result`) 依赖 5xx 降级为默认 dataclass。把 5xx 改为上抛会打断既有容错契约, 全部转 crash。

修正后 `classify_http_status`: 仅 401/403 返 True (不可降级, 配置问题引擎无法自恢复, 须上抛让运维查 key); 5xx 返 False (可降级, 引擎返默认 dataclass + `.error`, 不上抛)。404 由 `ai_client._ModelNotFound` 单独处理 (失效缓存 + 重选模型 + 重试, 重试穷尽仍降级)。

A12 核心价值保留: 认证/配置硬错不再被静默吞成空对象, 运维可区分。降级契约不破。

### A2 单实例锁 — 本地优先约束下的诚实边界

本地优先 (100% 离线, 无云) 架构无进程外共享状态服务。引擎池为进程内模块级全局, 真·多 worker 会各持一套, 状态分区 + 内存翻倍。选项:

1. 引入 Redis/DB 外置引擎池 + 共享状态 — 违反本地优先约束, 超出本架构范围
2. 强制单 worker + fcntl 单实例锁 — 拒第二进程, 本架构内可达成, 诚实标注扩展边界

选 2。`workers=1` + `fcntl.flock(LOCK_EX|LOCK_NB)`, 第二实例启动即被拒并明确提示。代码注释写明: 若需横向扩展, 须先上外部共享状态 (Redis/DB) + 引擎池外置, 非本架构支持。`build_engines` 本身已原子 (返 bundle, await 后解包, 全有或全无)。

## 验证

| 项 | 结果 |
|----|------|
| `pytest tests/ -q` | 304 passed |
| `ruff check .` | No issues found |
| 版本 | v1.1.0 |

测试回归说明: A12 初版 5xx 归非降级致 37 个降级容错集成测试 crash (LLM 网关 502 被 rethrow)。修正分类边界 (仅 401/403 非降级) 后 37 全恢复 + 267 持稳 = 304 全绿。集成测试连真实 fusion-mlx 网关 (localhost:11432), 当前加载模型 `Qwen3.8-27B-4bit`, 网关需 API key; 默认模型 `Qwen3.5-9B-4bit` 在网关侧不存在, 触发 502, 降级路径覆盖。

## 版本

- Wave 1 (P0): `c4ad349` (版本未单独 bump, 沿用 1.0.8)
- Wave 2 (P1): 本波, 版本 **v1.1.0** (pyproject.toml + `__init__.py` `__version__` + test_core/test_serve 版本断言)
- Wave 3 (P2): 待修, 计划 v1.2.0

修复后审计结论: P1 架构层 8 项全清 (含 A11+A12 合并项)。剩余 P2 工程实现缺陷 Wave 3 处理。

