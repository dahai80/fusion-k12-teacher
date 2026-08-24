# 审计修复报告 — 2026-08-24

对抗式架构审计（`audit/fusion-k12-teacher-audit-report-0824.md`，68 项缺陷，8 簇）全量修复。

## 修复统计

| 簇 | 缺陷数 | 状态 |
|----|--------|------|
| LLM（ai_client） | 10 | ✅ |
| AGT（agent） | 8 | ✅ |
| ENG（引擎群） | 17 | ✅ |
| SRV（serve） | 8 | ✅ |
| STD（standards） | 7 | ✅ |
| CNT（content） | 4 | ✅ |
| SEC（safety/desensitize） | 13 | ✅ |
| SRVf（serve 残余） | 2 | ✅ |
| **合计** | **68** | **✅** |

严重度：致命 15 / 高 18 / 中 22 / 低 13。

## LLM 簇（ai_client.py，10 项）

- 双路客户端：优先 `fusion_core.FusionMLXClient`，缺失时 httpx fallback（issue #6）。
- 模型自动选择跳过非聊天模型（扩散/嵌入/TTS），关键词过滤 `dit/vae/embed/clip/tts/...`。
- base_url 默认 `http://localhost:11432/v1`（gateway），`FUSION_MLX_URL` 可覆盖。
- 默认模型 `Qwen3.5-9B-4bit`，`FUSION_MLX_MODEL` 可覆盖。
- auto-select 加锁，避免缓存竞态（LLM-2/5）。
- `close()` 释放 httpx 连接（LLM-4）。

## AGT 簇（agent/，8 项）

- `EngineRegistry` 映射引擎名→实例；`execute_step`/`execute_task` 顺序执行，步骤间传递输出。
- `TaskScheduler`（APScheduler + SQLite）cron 调度 + 持久化。
- `run_task` 每次按请求参数即时构建，避免共享 `_tasks` 跨请求污染（SRV-7/AGT-5）。
- `data_path` 每次传入并重新加载，避免烘焙过期数据（AGT-5）。
- `disable_task` 不再 `except: pass`，异常透传返回 False（AGT-8）。
- `load_history`/`load_default_tasks` 加锁，多 worker 安全。
- 步骤超时 `asyncio.wait_for` + `TimeoutError`（AGT-8 executor UP041）。
- 5 个预定义任务构建器（weekly_prep/weekly_summary/daily_homework_review/monthly_report/batch_differentiated_materials）。

## ENG 簇（引擎群，17 项）

- **ENG-1 提示注入防御**：共享 `sanitize_input(text, max_len)`（safety/filter.py），各引擎调用前清洗 subject/grade/topic/essay/problem 等用户字段。截断长度、剥离控制字符、包裹注入企图标记。
- **ENG-2 失败可见**：结果 dataclass 加 `error: str = ""`（LessonPlan/Quiz/GradingResult/StudentReport/ClassProfile/StudentProfile/RemedialPlan/Worksheet/DifferentiatedContent 等）。解析失败与异常路径都置 error 标志，替代静默降级。
- **ENG-5/6/13 类型强转**：analytics 加 `_coerce_float/_coerce_int/_coerce_str_list`，防御 LLM 返回错误类型字段；weak_knowledge_points error_rate 钳到 [0,1]。
- **ENG-7/8/9 CSV 注入**：loader 加 `_sanitize_cell`（前缀 `=+@` tab cr lf 加单引号）、`_parse_num`（空单元格返 None 区分真实 0）、畸形 JSON 兼容 dict 容器、非 dict 项跳过告警。
- **ENG-10/11/12 评分**：grader `grade_essay` 超长截断 + `partial` 标志；`grade_math` total 钳到 (0,100]；`_clamp_score` 统一分数钳制。
- **ENG-14/15 统计门槛**：`_calc_weak_points` 样本 <2 跳过（原 ==0）；`_calc_trend` 历史 <4 返 stable（原 <2）。
- **ENG-16/17 单元计划/分层**：`generate_unit_plan` 缺 unit_title 时注入兜底；分组任务 LLM 失败 try/except + 空返回告警。
- **`_parse_json` 统一重写**：None 安全 + regex fence 提取 + 大小守卫（200000 字符截断），各引擎保持复制（CLAUDE.md 约定，非重构目标）。

## SRV 簇（serve.py，8 项）

- **SRV-1 认证**：`require_api_key`（`X-API-Key`，`FUSION_K12_API_KEY` 未设时静默放行——本地工具默认）。写端点 + 敏感操作（wordlist/desensitize）挂 `Depends`。
- **SRV-2 限流**：`_RateLimiter` 进程内滑动窗口（`FUSION_K12_RATE_WINDOW`/`FUSION_K12_RATE_MAX`，默认 60/60s），按 client IP，429。
- **SRV-3**：CLI/serve 共享 engines 构建路径（`build_engines()`）。
- **SRV-4 非阻塞 I/O**：`_load_assessments` 走 `asyncio.to_thread`，调用点 `await`（修了 SRV-4 改 async 时漏 await 的回归）。
- **SRV-5 路径校验**：`_check_allowed_path` 用 `is_relative_to` 精确匹配（非 startswith 前缀），杜绝 `data-evil/` 绕过。
- **SRV-6 upload**：校验 + 落盘 + 返回可用 data_path，不再无操作报成功。
- **SRV-7 agent/run**：每次按请求参数即时构建 + data_path 重载 + `_check_allowed_path`。
- **SRV-8 资源释放**：lifespan shutdown 关 scheduler + `mlx_client.close()`。

## STD 簇（standards/，7 项）

- **STD-1**：loader 追踪 `_failed_files`，畸形文件跳过并告警，`failed_files` 属性暴露。
- **STD-2**：`CurriculumStandard` 加 `schema_version`，from_dict 缺失时告警默认 "1.0"。
- **STD-3**：`all_points`/`all_standards` 返 `MappingProxyType` 零拷贝只读视图。
- **STD-4**：`find_by_topic` 单字仅精确匹配 topic，≥2 字才子串，避免 "加" 误匹配 "加权/增加"。
- **STD-5**：`validate_coverage` 修正反向子句（`obj in description` → `description in obj`）。
- **STD-6/7**：aligner 加 `_cjk_tokens` CJK bigram 分词，替代中文无效的 whitespace split；`align` fallback 与 `validate_alignment` 用 bigram token 重叠。

## CNT 簇（content/，4 项）

- **CNT-1 游戏 schema**：`generate_educational_game` 返白名单 key（title/type/objective/rules/materials/duration/setup/variations/debrief），值有界（str ≤5000, list ≤50）；serve 响应不再 `**result.items()` 透传任意 key，剥离 `error`/`type`。
- **CNT-2 家长信过滤**：`generate_parent_communication` 输入 sanitize，输出过 `ContentFilter.check_output`（敏感词+适龄），长度上限 4000，检出不当返空。
- **CNT-3 `_parse_json`**：None 安全 + regex fence + 大小守卫（200000 截断）。
- **CNT-4 失败可见**：`Worksheet` 加 `error`；家长信失败返空（不外泄 `生成失败:{e}` 错误串给家长）。

## SEC 簇（safety/desensitize，13 项）

- **SEC-1 学生再识别**：name→ID 用加盐哈希（`_hash_id`，salt=`fusion-k12`），非确定性顺序 ID，跨实例无碰撞。
- **SEC-2 映射表外泄**：`AnonymizeResult.to_dict` 默认 `include_map=False`，name_map 不序列化；serve export 仅返 `name_count`。
- **SEC-3 mask 泄露**：phone/email/generic 改定宽掩码——不保留长度（phone 固定 4 掩码+末 4 位），email 哈希成不可逆伪邮箱（不泄露域名），generic 固定 8 位。对齐 GB/T 35273。
- **SEC-4 安全审查接入**：`ContentGenerator._filter_output` 对工作纸 instructions/answer_key/问题文本过 `check_output`；家长信过 `check_output`。
- **SEC-5 risk_level 单调性**：`_escalate` + `_RISK_ORDER` 等级单调叠加，age 命中不再被吞。
- **SEC-6 fail-open**：移除 `llm_review` 死代码路径，`check_output` 无 LLM 依赖、无默认 True。
- **SEC-8 `_strip_json`**：regex 优先匹配 `{...}`，无闭合 fence 不丢内容。
- **SEC-9 非法年级**：`_grade_index` 告警 + 回退最严格档。
- **SEC-10 import 位置**：清理方法体内 `import json`。
- **SECb-A2**：`anonymize_records` 直接返脱敏 records（`AnonymizeResult.records`），免二次遍历。
- **SECb-P1 性能**：wordlist `check` 改单正则一次扫描（`_matcher`），替代 O(W×N) 逐词 in 子串；add/remove 重建 matcher。
- 敏感词绕过：`_BYPASS_RE`/`_BYPASS_CLASS` 扩展（`.`、`、。/|` 等全角标点）。

## 验证

- `pytest tests/` — **284 passed**
- `ruff check .` — **No issues found**
- 测试更新：`test_desensitize.py` 掩码断言对齐 SEC-3 定宽格式。
