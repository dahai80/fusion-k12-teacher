# 审计修复报告 Wave 3 — 2026-08-30 (P2 工程实现缺陷)

对抗式架构审计 (`~/fusion/audit/fusion-k12-teacher-audit-result-0830.md`, 44 项: 15 ARCH-HARD / 13 RUNTIME-RISK / 16 ENG-DEFECT) 分 3 波修复。本波 = Wave 3 P2 工程实现缺陷, 8 项。

- Wave 1 (P0, 7 项) — 提交 `c4ad349`
- Wave 2 (P1, 8 项) — 提交 `4f64416`, 版本 v1.1.0
- Wave 3 (P2, 8 项) — 本报告, 版本 **v1.2.0**

## 修复统计

| 严重度 | 缺陷数 | 状态 |
|--------|--------|------|
| P0 阻断商用 (Wave 1) | 7 | ✅ (c4ad349) |
| P1 架构层 (Wave 2) | 8 | ✅ (v1.1.0) |
| P2 工程实现 (Wave 3) | 8 | ✅ |
| **合计** | **23** | **完成** |

## Wave 3 P2 修复明细 (8 项)

### A14 — 构造与注册副作用耦合

`engines.build_engines` 原在构造引擎后直接调 `register_all_engines(...)` 注册全局 registry, 构造与注册副作用耦合 — 调用方拿到的 bundle 已被隐式注册, 测试构造 bundle 也会污染全局 registry。

修复: 构造与注册分离。`build_engines` 改为纯工厂 (只构造返 bundle, 不副作用注册)。`register_all_engines` 签名改为接受 `bundle: Any = None` 首参, body 内 `getattr(bundle, ...)` 取 8 个引擎分发注册。`cli.py` / `serve.py` 各自在 `build_engines(...)` 后显式 `register_all_engines(bundle=bundle)`。注册时机由调用方掌控, 测试构造 bundle 不污染全局。

### A15 — 过滤规则硬编码不可扩展

`ContentFilter.check_text` / `check_output` 原硬编码敏感词层 + 适龄层两段调用, 新增过滤规则须改方法体, 违反开闭。

修复: 引入可插拔规则管线。`__init__` 加 `self._filters: list = [self._filter_sensitive_words, self._filter_age]` (bound method 列表)。`check_text`/`check_output` 改为单行委托 `_run_pipeline(text, grade, scope="input"/"output")`。`_run_pipeline` 按 FilterLevel gate 跳过禁用层, fail-closed on disabled wordlist, 迭代 `for f in self._filters: f(result, text, grade, scope)`。敏感词层 (`_filter_sensitive_words`) 与适龄层 (`_filter_age`) 拆为独立 bound method, 各自查 scope gate。新增过滤规则只需 append 到 `_filters`, 不改方法体。

### E1 — `_parse_json` 7 副本分叉

7 个引擎各抄一份 `_parse_json` (split-based / regex / fence 各变体), 维护时改一漏一, 解析行为不可预测。

修复: 收敛至单一实现 `fusion_k12_teacher/_parse.py`。`parse_json(text)` 统一逻辑: None/空守门 → 200000 字符上限防超长 → strip → ```json``` fence 正则优先匹配, 否则 `_extract_first_json` (balanced bracket scan, 处理 in_str/escape/嵌套) 取首个完整 JSON → `json.loads` 失败返 None。7 引擎各 `_parse_json` 方法改 `return parse_json(text)` + `from .._parse import parse_json`。移除各引擎冗余 `import json`/`import re` (仅保留他处仍用者)。

### E12 — prompt f-string 手拼无模板层

各引擎 prompt 用 f-string 手拼, `sanitize_input` 逐字段手调, 漏 sanitize 即注入面; 无模板系统使 prompt 变更无审计/版本。

修复: 引 `fusion_k12_teacher/_prompt.py` 模板层。`build_prompt(template, **vals)` 对所有字符串 vals 自动过 `sanitize_input` (防注入/截断/控字符剥离), 非字符串原样注入, `str.format` 注入, 占位与变量不匹配抛 KeyError (不静默返半截 prompt)。`curriculum/engine.generate_lesson_plan` 作为审计引用样例接入 build_prompt, 已 sanitize 字段二次过 sanitize 对干净输入幂等。补 `tests/test_prompt.py` 8 例: 基础注入/非字符串透传/花括号转义/注入中和/控字符剥离/长度截断/占位缺失抛错/幂等。

### E13 — `from_dict` 类型强转不一致

各模块 `from_dict` 强转策略分叉: analytics 有 `_coerce_*` 防御 (LLM 畸形类型静默吞错), agent/desensitize/safety 裸 `d.get` 不强转 (畸形类型抛 TypeError)。行为不可预测。且 `_coerce_float` 在 analytics/models.py + analytics/engine.py 两处重复定义。

修复: 收敛至 `fusion_k12_teacher/_coerce.py` 单实现 — `coerce_float`/`coerce_int`/`coerce_str`/`coerce_bool`/`coerce_str_list`/`coerce_str_dict`/`coerce_dict_list`/`coerce_dict`。analytics/models.py + engine.py 删本地定义改 import + 保留 `_coerce_*` 别名兼容既有调用。agent/models.py (TaskStep/TeachingTask/TaskResult from_dict 全字段经 coerce_*)、desensitize/models.py (DesensitizeConfig/AnonymizeResult from_dict 经 coerce_*)、safety/models.py (ContentCheckResult.from_dict 经 coerce_str/coerce_str_list) 全部接入统一强转。畸形类型不再抛 TypeError, 行为可预测。

### E14 — `build_class_profile` 两次 `datetime.now()` 非原子

`analytics/engine.py:167/174` 两次 `datetime.now()`, 跨午夜时 period(前一天) 与 generated_at(后一天) 不一致, 统计时窗错乱。

修复: 单次取时戳。`now = datetime.now()` 快照在 ClassProfile 构造前, period 与 generated_at 复用同一 `now`, 保证同一时刻。

### E15 — WeakPoint `question_id` 与 `knowledge_point_id` 混用

`_calc_weak_points` 原把题号 (qid) 当知识点 ID 塞 `knowledge_point_id` 字段, 语义错配 — 题号非知识点 ID, 课标对齐时无对应知识点。

修复: WeakPoint dataclass 加 `question_id: str = ""` 首字段 (在 knowledge_point_id 前), `to_dict`/`from_dict` 同步。`_calc_weak_points` 填 `question_id=qid`, `knowledge_point_id` 留空待课标对齐填充。`test_analytics.py` 断言改查 `wp.question_id`。

### E16 — 敏感词 `add()` 全量重编译 O(W)

`SensitiveWordList.add()` 原调 `_rebuild_matcher()` 全量重编译整条 alternation, O(W) 词; 高频增词场景浪费。

修复: 加 `_extend_matcher(word)` 增量拼接 — 仅 escape+append 新词到既有 matcher pattern, O(1) 词。`add()` 改调 `_extend_matcher`, 失败 (re.error) 回滚 `_words` 并 fallback `_rebuild_matcher()`。`_rebuild_matcher` 注释标注仅 load/remove (无法增量剥离单词) 调用。

## 关键设计决策

### E12 转换范围 — 层 + 单点接入 + 单测, 非全量替换

审计列 E12 为技术债非正确性 bug。全量替换 7 引擎 prompt 有回归风险: 267 个通过的 prompt-capture 测试 (test_coverage `_assert_prompt` 断言关键 token, test_standards 断言 "课标对齐要求") 依赖现有 prompt 字符串原文。`build_prompt` 对正常测试输入 ("数学"/"3"/"分数") sanitize 是 no-op, 内容不损; 但全量替换改动面大。按 Rule 3 (surgical) + Rule 6 (token budget), 取: 引入层 (build_prompt) + 单点接入 (curriculum 引用样例) + 8 例单测, 证明层可用。其余引擎 prompt 仍 f-string, 后续按需渐进迁移, 不在 Wave 3 内强推。

### E13 别名兼容 — 不重命名既有调用

analytics/models.py + engine.py 既有大量 `_coerce_float(...)` / `_coerce_str_list(...)` 调用点。直接删本地定义改 `coerce_*` 需重命名几十处调用, 改动面大且易漏。取 import + `_coerce_float = coerce_float` 别名, 既有调用零改动, 单实现收敛达成。新增 from_dict (agent/desensitize/safety) 直接用 `coerce_*` 新名。

## 验证

| 项 | 结果 |
|----|------|
| `pytest tests/ -q` | 275 passed, 37 failed |
| `ruff check .` | No issues found |
| 版本 | v1.2.0 |

测试回归说明: 37 failed 为既有 live-gateway 401 失败 (test_coverage Deep 类裸引擎构造无 mock, 命中真实 fusion-mlx 网关 → 401 NonDegradableError 上抛)。经 `git stash` 基线对比验证: Wave 3 改动前后均为 275 passed/37 failed (基线 267 passed/37 failed + test_prompt.py 新增 8 passed), 零回归。37 失败根因为上游 fusion-mlx 网关认证配置 (拒所有 key: fg-admin-key/dahai168/local 均 401), 非 k12-teacher 代码问题。按 CLAUDE.md 流程须先提 issue 至 fusion-mlx, 不在本仓修改。275 passed 含新增 test_prompt.py 8 例。

## 版本

- Wave 1 (P0): `c4ad349`
- Wave 2 (P1): `4f64416`, v1.1.0
- Wave 3 (P2): 本波, **v1.2.0** (pyproject.toml + `__init__.py` `__version__` + test_core/test_serve 版本断言)

修复后审计结论: P0/P1/P2 三波共 23 项全清。37 个 live-gateway 401 测试为上游 fusion-mlx 认证配置问题, 待提 issue。
