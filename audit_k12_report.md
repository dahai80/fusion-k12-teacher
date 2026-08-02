# Fusion-K12-Teacher 全面代码审计报告

> **审计日期**: 2026-07-29  
> **审计范围**: 全代码库 — 52 个 Python 源文件, 8 个测试文件, 配置/文档/部署文件  
> **代码版本**: `v1.0.0` (pyproject.toml v0.3.0)  
> **审计人**: AtomCode (deepseek-v4-flash)

---

## 目录

1. [总体评价](#1-总体评价)
2. [技术架构审计](#2-技术架构审计)
3. [代码质量审计](#3-代码质量审计)
4. [安全可靠性审计](#4-安全可靠性审计)
5. [内存泄漏风险分析](#5-内存泄漏风险分析)
6. [可读性审计](#6-可读性审计)
7. [可扩展性审计](#7-可扩展性审计)
8. [功能完整性审计](#8-功能完整性审计)
9. [测试覆盖审计](#9-测试覆盖审计)
10. [配置与部署审计](#10-配置与部署审计)
11. [发现的问题与修复建议](#11-发现的问题与修复建议)
12. [改进路线图](#12-改进路线图)

---

## 1. 总体评价

| 维度 | 评分 | 说明 |
|------|------|------|
| 架构设计 | ★★★★☆ | 清晰的分层架构，模块边界明确 |
| 代码质量 | ★★★★☆ | 一致性高，遵循 PEP 8，类型注解完善 |
| 安全可靠性 | ★★★★★ | 离线优先策略从根本上消除多数安全风险 |
| 内存管理 | ★★★☆☆ | 存在内存累积风险（未清理的缓存） |
| 可读性 | ★★★★☆ | 中英双语文档，良好注释 |
| 可扩展性 | ★★★★★ | DI 模式 + 注册表模式，模块隔离优秀 |
| 功能完整性 | ★★★★★ | 超越对标产品（Claude K-12 Teacher） |
| 测试覆盖 | ★★★★☆ | 272 测试，覆盖全面但存在盲区 |
| 文档质量 | ★★★★☆ | README + API 文档 + 部署指南完善 |

**综合评分: ★★★★☆ (4.3/5)**

---

## 2. 技术架构审计

### 2.1 整体架构

```
CLI (click) ──→ Engine Layer ──→ MLXClient ──→ fusion-mlx (/v1/chat/completions)
                     ↑
HTTP API (FastAPI) ──┘
```

**架构特点**:
- **严格的单向依赖**: CLI/HTTP → Engines → MLXClient → fusion-mlx HTTP，无反向引用
- **依赖注入**: 所有 Engine 的构造函数接受 `Optional[MLXClient]`，默认 `MLXClient()`，测试友好
- **模块独立性**: 11 个功能模块各自独立目录，`__init__.py` 显式控制导出，无跨模块直接引用
- **同步/异步桥接**: CLI 使用 `asyncio.run()` 桥接 Click 同步命令 → async 引擎方法

### 2.2 架构评估

#### 优势 ✅

1. **层次清晰**: CLI 层仅负责参数解析和命令路由，Engine 层负责业务逻辑，MLXClient 层负责 LLM 通信
2. **单一职责**: 每个 Engine 只处理一个领域（课程/评估/学科/个性化/内容），无职责交叉
3. **数据流简洁**: 所有 AI 推理统一经过 `MLXClient.chat()`，便于审计和日志
4. **CLI/HTTP 双入口**: 同一套 Engine 层同时支持 CLI 交互和 HTTP API 调用，代码零重复
5. **全局注册表**: Agent 模块的 `EngineRegistry` 允许任务编排引擎解耦

#### 问题及建议 🔧

1. **全局变量过多**: `serve.py` 使用 12 个 `global` 变量（L44-47），`cli.py` 通过 `ctx.obj` 字典传递，风格不统一。  
   **建议**: 统一使用 `AppContext` 单例或依赖容器

2. **version 不一致**: `__init__.py` 声明 `__version__ = "1.0.0"`，但 `pyproject.toml` 是 `version = "0.3.0"`。  
   **建议**: 统一版本来源，从 pyproject.toml 或单一文件读取

3. **asyncio.run() 嵌套风险**: `cli.py` 的每个命令都调用 `asyncio.run()`，如果某个异步命令内部再调用 `asyncio.run()` 会抛出 `RuntimeError`。当前设计避免了嵌套，但未来添加新命令时需格外小心。  
   **建议**: 考虑全局事件循环或 Click 的 `async` 支持（`await click.defer()`）

4. **serve.py 的启动开销**: `lifespan` 中串行初始化所有引擎，没有延迟加载。  
   **建议**: 对不常用的引擎（analytics, agent）采用懒加载

---

## 3. 代码质量审计

### 3.1 代码风格

- ✅ **类型注解**: 全项目使用 `from __future__ import annotations` + 完整类型注解
- ✅ **PEP 8**: 符合 Python 编码规范，使用 Black/Ruff 格式化（有 `.ruff_cache`）
- ✅ **命名规范**: 类名 PascalCase，方法/变量 snake_case，常量 UPPER_CASE
- ✅ **异常处理**: 所有 async 方法都有 try/except，异常降级为默认值
- ❌ **少数 `import` 位置**: `cli.py` L259 `import uvicorn`，L692 `import json as _json`，L727 类似，在函数体内 import

### 3.2 代码重复分析

| 重复模式 | 出现文件数 | 建议 |
|---------|-----------|------|
| `_parse_json()` | 7 个 Engine | 按 CLAUDE.md 说明为 "刻意隔离"，接受此设计 |
| prompt 模板拼接模式 | 7 个 Engine | 每个方法都有自己的 prompt 字符串，无共享模板 |
| `to_dict()` / `from_dict()` | 约 18 个 dataclass | 标准序列化模式，合理 |
| 构造函数的 DI 模板 | 7 个 Engine | 可提取基类 `BaseEngine` |
| 异常处理 try/except 模板 | 约 30 处 | 可提取装饰器 `@safe_call(default)` |

### 3.3 Pyright / mypy 合规

项目使用了 `from __future__ import annotations` 和类型注解，但未配置类型检查器配置。  
**建议**: 在 pyproject.toml 中添加 `[tool.pyright]` 或 `[tool.mypy]` 配置

---

## 4. 安全可靠性审计

### 4.1 安全架构

```
Offline-first → 零数据上传 → 无远程漏洞面
```

#### 安全优势 ✅

1. **100% 离线**: 所有处理在本地完成，无数据外传，从根本上消除数据泄露
2. **无遥测/埋点**: 代码中无任何 HTTP 回调、分析 SDK、telemetry 上报
3. **内容安全模块完整**:
   - `SensitiveWordList`: 敏感词库，case-insensitive 匹配，可持久化
   - `AgeChecker`: 按年级分层的内容适龄检查（1-3 concrete, 4-6 semi-abstract, 7-12 abstract）
   - `ContentFilter`: 四层过滤（敏感词 + 年龄 + LLM 自审 + 输出检查）
   - `FilterLevel`: 可配置过滤等级
4. **数据脱敏模块**: `DataAnonymizer` 支持姓名匿名化和字段掩码，可逆映射
5. **FastAPI CORS**: 未显式配置 CORS（默认同源），安全但限制跨域使用

#### 安全隐患 🔴

1. **敏感词库过小**: 仅 14 个敏感词，覆盖不足。中文教育场景下需扩展至 100+ 词  
   **风险**: 低  
   **建议**: 扩展敏感词库，覆盖校园霸凌、不当交友、网络沉迷等教育场景关键词

2. **`_replace_words` 使用 `re.IGNORECASE`**: `ContentFilter._replace_words()` 对每个敏感词使用 `re.compile(re.escape(w), re.IGNORECASE)` 进行替换。输入文本中包含正则特殊字符时性能会下降。  
   **建议**: 对纯文本匹配，优先使用 `str.replace()`，仅在需要大小写不敏感时用正则

3. **`filter_sensitive` 操作没有 lock**: 多线程/多协程并发调用 `filter_sensitive()` 时，`SensitiveWordList._words` 是 `set()`，可能存在竞争。当前实践是单协程，风险极低。  
   **建议**: 添加 `threading.Lock` 或 `asyncio.Lock`

4. **LLM 审查结果信任**: `llm_review()` 解析 LLM 返回的 JSON 字段 `safe` 来决定内容是否安全，但未验证 LLM 输出格式的完整性。  
   **建议**: 增加 schema 校验（pydantic）

5. **无速率限制**: HTTP API 无任何速率限制（rate limiting），可能在并发请求下被滥用。  
   **建议**: 添加 `slowapi` 或中间件速率限制

### 4.2 可靠性评估

#### 可靠设计 ✅

1. **优雅降级**: 所有 Engine 方法在异常时返回默认值/空对象，始终不抛出异常到上层
2. **无超时配置**: `MLXClient.chat()` 使用 `fusion_core` 的默认超时，未覆盖自定义  
   **风险**: LLM 无限等待  
   **建议**: 在 `MLXClient.__init__` 中接受 `timeout` 参数
3. **APScheduler 异步调度**: `TaskScheduler` 使用 `AsyncIOScheduler`，正确
4. **文件操作异常处理**: 所有文件读写（JSON/CSV/文本）都有异常处理

#### 可靠性隐患 🔴

1. **MLXClient 的模型自动检测失败无缓存**: `chat()` 方法每次无 `self.model` 时都调用 `list_models()`，失败则默认 `qwen3.5-9b`。但 `self.model` 只赋值一次（成功时），失败时后续调用仍会重试。  
   **建议**: 模型检测失败后设置一个 sentinel 值，避免每次都重试

2. **Dockerfile 缺失健康检查**: `Dockerfile` 未添加 `HEALTHCHECK` 指令  
   **建议**: 添加 `HEALTHCHECK --interval=30s CMD curl -f http://localhost:11448/api/health || exit 1`

3. **`_parse_cron` 解析简单**: `TaskScheduler._parse_cron()` 只支持 standard cron 5 字段的子集，对 `*/15` 等语法不支持  
   **建议**: 使用 `croniter` 库进行完整的 cron 表达式解析

4. **`serve.py` 的 `_load_assessments` 从文件路径直接读取**: 路径来自用户输入，存在路径遍历风险（虽在 `_init_allowed_dirs` 中做了限制，但仍需加固）

---

## 5. 内存泄漏风险分析

### 5.1 静态内存持有分析

| 位置 | 数据结构 | 增长条件 | 清理机制 | 风险 |
|------|---------|---------|---------|------|
| `CurriculumEngine._plans` | `Dict[str, LessonPlan]` | 每次 `generate_lesson_plan()` 调用 | 无 | **高** — 无上限增长 |
| `DataAnonymizer._name_map` | `Dict[str, str]` | 每次 `anonymize_name()` 调用 | `reset()` 方法存在但 CLI/API 不调用 | **中** |
| `DataAnonymizer._reverse_map` | `Dict[str, str]` | 同上 | 同上 | **中** |
| `TaskScheduler._history` | `List[TaskResult]` | 每次 `run_task()` | `_save_history()` 只保留最近 100 条到磁盘，但内存中无限制 | **中** |
| `TaskScheduler._tasks` | `Dict[str, TeachingTask]` | `register_task()` / `load_default_tasks()` | 无（但数量固定） | **低** |
| `StandardsLoader._standards` / `_points_index` | Dict | `load_all()` 一次加载 | 无（但只加载一次） | **低** |
| `AgeChecker._ratings` | `Dict[str, AgeRating]` | `load()` 一次加载 | 无（但只加载一次） | **低** |
| `SensitiveWordList._words` | `Set[str]` | `load()` 一次加载 + `add()` | 无（但规模可控） | **低** |

### 5.2 高风险项

**`CurriculumEngine._plans` — 关键泄漏点**
```python
self._plans: Dict[str, LessonPlan] = {}
plan = LessonPlan(...)
self._plans[plan.id] = plan  # 只进不出
```
- 每次生成教案都追加到字典，永不删除
- 连续调用 10,000 次将耗尽内存（每个 LessonPlan ~2KB → ~20MB）
- 长时间运行的 API 服务场景下风险很高  
- **建议**: 实现 LRU 缓存（基于 `orderedict` 或 `cachetools`），设置最大容量（例如 100）

**`DataAnonymizer._name_map` — 中风险**
- `anonymize_name()` 每次新增名称都追加，无上限
- `reset()` 存在但 CLI 和 API 入口都不调用  
- **建议**: 添加 `max_entries` 配置或定期清理

### 5.3 异步资源管理

- **HTTP 连接**: `MLXClient._inner` (FusionMLXClient) 使用 httpx.AsyncClient，正确使用 async/await，无连接泄漏风险
- **文件句柄**: 所有文件操作使用 `with` 上下文管理器，正确关闭
- **事件循环**: CLI 使用 `asyncio.run()` 正确管理，无泄漏

### 5.4 结论

内存风险集中在**长期运行的 API 服务**上。CLI 模式的单次调用无风险。修复优先级：

| 优先级 | 问题 | 影响场景 |
|--------|------|---------|
| P0 | `_plans` 无上限增长 | API 服务 > 1000 次调用 |
| P1 | `_name_map` 无上限增长 | 批量脱敏 > 10万条记录 |
| P2 | `_history` 内存中无限增长 | 长期运行调度器 |

---

## 6. 可读性审计

### 6.1 文档与注释

- ✅ **中文注释**: 所有模块、类、方法都有中文 docstring
- ✅ **对口文档**: README（中英双语）、API 文档、部署文档齐全
- ✅ **CLAUDE.md**: 项目开发指南完备，包含架构说明、命令列表、测试指南
- ⚠️ **缺少架构决策记录 (ADR)**: 没有记录为什么选择某些设计模式

### 6.2 命名

- ✅ 变量名清晰：`mlx`, `plan`, `quiz`, `prompt`, `response`
- ✅ 中文概念词保留：`学困生`, `中等生`, `优等生`, `课标对齐`
- ✅ 方法名自文档化：`generate_lesson_plan`, `diagnose_skills`
- ✅ 常量大写：`GRADE_LEVELS`, `SUBJECTS`, `SAFETY_PROMPT_SUFFIX`

### 6.3 代码组织

- ✅ 每个模块文件不超过 600 行，可管理
- ✅ `__init__.py` 统一导出，用法清晰
- ⚠️ `cli.py` 754 行，是最大的源文件，包含 30+ 命令和异步桥接函数  
   **建议**: 按命令组拆分为 `cli/` 子包
- ⚠️ `serve.py` 612 行，22 个 API endpoint + 大量 request model  
   **建议**: 拆分路由到 `routes/` 子包

---

## 7. 可扩展性审计

### 7.1 架构可扩展性

| 扩展场景 | 现有机制 | 评价 |
|---------|---------|------|
| 新增 Engine | 创建目录 → 实现类 → 注入 MLXClient | **优秀**，DI 模式零耦合 |
| 新增 CLI 命令 | @click.command/@click.group 装饰 | **良好** |
| 新增 API 端点 | 在 serve.py 添加 @app.post | **一般**，文件已过大 |
| 新增 LLM 后端 | 替换/扩展 MLXClient | **优秀**，唯一 AI 接口 |
| 新增安全层 | 扩展 ContentFilter | **良好**，FilterLevel 可配置 |
| 新增任务类型 | 在 tasks.py 注册 builder | **优秀**，插件模式 |
| 新增数据源 | 扩展 loader.py | **良好** |

### 7.2 扩展障碍

1. **serve.py 单体化**: 22 个 API 路由 + 15 个 Request Model 都在一个文件中，添加新路由需要修改大文件  
   **建议**: 使用 FastAPI `APIRouter` 按模块拆分

2. **`cli.py` 命令组混合**: CLI 命令定义 + 异步桥接 + 输出逻辑在同一个文件中  
   **建议**: 使用 Click 的 `Cloup` 或拆分为多文件

3. **无配置管理**: 所有配置（模型名、URL、超时、过滤等级）硬编码在代码中  
   **建议**: 添加 `config.py` 模块，支持环境变量 + YAML/TOML 配置

4. **缺少中间件/插件系统**: 没有 hook 机制来扩展 Engine 行为  
   **建议**: 考虑添加 Pipeline/Middleware 模式

### 7.3 依赖管理

```
dependencies = [
    "fusion-core>=0.1.0",
    "httpx>=0.27.0",
    "pydantic>=2.0.0",
]
optional-dependencies = {
    test = ["pytest>=8.0.0", "pytest-asyncio>=0.23.0", "pytest-cov>=5.0.0"]
    web = ["fastapi>=0.104.0", "uvicorn>=0.24.0"]
}
```

- ✅ 最小依赖（3 个核心 + 测试/Web 可选）
- ✅ `apscheduler` 是 agent 模块的运行时依赖，但在 pyproject.toml 中未声明  
  **风险**: `pip install -e .` 后运行 agent 功能会缺失依赖  
  **建议**: 在 `[project.optional-dependencies]` 中添加 `agent = ["apscheduler>=3.10"]`

---

## 8. 功能完整性审计

### 8.1 功能清单对照

| 功能领域 | 预期功能 | 实现状态 | 对比 Claude K-12 Teacher |
|---------|---------|---------|------------------------|
| **教案生成** | 按学科/年级/主题生成 | ✅ 完整 | ✅ 同等 |
| **测验生成** | 多种题型、难度 | ✅ 完整 | ✅ 同等 |
| **单元计划** | 多周教学规划 | ✅ 完整 | ✅ 同等 |
| **作文批改** | 多维评分+反馈 | ✅ 完整 | ✅ 同等 |
| **数学批改** | 步骤分析 | ✅ 完整 | ✅ 同等 |
| **学习报告** | 学期/单元报告 | ✅ 完整 | ✅ 同等 |
| **评分标准** | Rubric 设计 | ✅ 完整 | ✅ 同等 |
| **概念解释** | 分年级解释 | ✅ 完整 | ✅ 同等 |
| **学科练习** | 多学科习题 | ✅ 完整 | ✅ 同等 |
| **STEM 项目** | 项目式学习 | ✅ 完整 | ✅ 同等 |
| **语言活动** | 语言学习活动 | ✅ 完整 | ✅ 同等 |
| **学习路径** | 个性化路径 | ✅ 完整 | ✅ 同等 |
| **能力诊断** | 技能水平诊断 | ✅ 完整 | ✅ 同等 |
| **资源推荐** | 针对性资源 | ✅ 完整 | ✅ 同等 |
| **工作纸** | 练习册生成 | ✅ 完整 | ✅ 同等 |
| **闪卡** | 抽认卡生成 | ✅ 完整 | ✅ 同等 |
| **课件** | 幻灯片大纲 | ✅ 完整 | ✅ 同等 |
| **教育游戏** | 课堂游戏设计 | ✅ 完整 | ✅ 同等 |
| **家校沟通** | 家长沟通模板 | ✅ 完整 | ✅ 同等 |
| **课标知识图谱** | 2022 课标对齐 | ✅ **超越** | ❌ 无 |
| **分层教学** | 三层差异化 | ✅ **超越** | ❌ 无 |
| **学情分析** | 班级/学生画像 | ✅ **超越** | ❌ 无 |
| **错题归因** | 根因分析 | ✅ **超越** | ❌ 无 |
| **补救方案** | 针对性补习计划 | ✅ **超越** | ❌ 无 |
| **任务自动化** | 定时多步任务 | ✅ **超越** | ❌ 无 |
| **内容过滤** | 敏感词+适龄 | ✅ **超越** | ❌ 无 |
| **数据脱敏** | 隐私保护 | ✅ **超越** | ❌ 无 |
| **HTTP API** | REST 接口 | ✅ **超越** | ❌ 无 |
| **Docker 部署** | 容器化 | ✅ **超越** | ❌ 无 |

### 8.2 功能差距

| 缺失功能 | 优先级 | 建议 |
|---------|--------|------|
| **多媒体内容生成** | 中 | 支持生成 SVG 图表、LaTeX 公式等 |
| **课堂互动模式** | 低 | 现在以生成内容为主，无实时互动 |
| **学习进度追踪** | 中 | 持久化存储学生学习历史 |
| **知识图谱可视化** | 低 | 课标知识点的图形化展示 |
| **多语种支持** | 低 | 当前仅支持中文prompt |
| **批量导出** | 中 | 批量导出教案/工作纸为 PDF |

---

## 9. 测试覆盖审计

### 9.1 测试统计

| 测试文件 | 测试类数 | 测试方法数 | 测试类型 |
|---------|---------|-----------|---------|
| `test_core.py` | 6 | 26 | 单元 + 集成 |
| `test_coverage.py` | 6 | 30+ | 模拟覆盖 |
| `test_analytics.py` | 5 | 35+ | 单元 + LLM 模拟 |
| `test_agent.py` | 11 | 20+ | 单元 + Mock |
| `test_safety.py` | 8 | 20+ | 单元 + Mock |
| `test_desensitize.py` | 3 | 18 | 单元 |
| `test_serve.py` | 6 | 10 | 集成 (ASGI) |
| `test_standards.py` | 8 | 30+ | 单元 + Mock |

### 9.2 覆盖盲区

| 盲区 | 风险 | 建议 |
|------|------|------|
| **`cli.py` 中的 differentiation / analytics / agent / safety / desensitize 命令** | 中 | `test_coverage.py` 只覆盖了 5 个基础 CLI 命令，其余 CLI 命令（约 20 个）未测试 |
| **`serve.py` 中的 standards / analytics / agent / safety / desensitize API endpoint** | 中 | `test_serve.py` 只测试了 5 个基础 API，其余 15+ 端点未测试 |
| **`analytics/engine.py` 的文件路径遍历防护** | 中 | `_load_assessments` 的 `_init_allowed_dirs` 路径检查逻辑未测试 |
| **`TaskScheduler` 的 cron 解析边界情况** | 低 | 未测试 `*/5` 等复杂 cron 表达式 |
| **`ContentFilter` 的正则替换 DoS 场景** | 低 | 极长文本 + 大量敏感词时的性能未测试 |
| **`MLXClient` 模型检测失败重试逻辑** | 低 | `list_models()` 抛异常后的 fallback 行为未模拟测试 |
| **并发安全** | 低 | 没有任何多线程/多协程并发测试 |

### 9.3 测试质量

- ✅ **Mock 模式完备**: `test_coverage.py` 通过 monkey-patch `engine.mlx.chat` 实现了无 fusion-mlx 的覆盖测试
- ✅ **异常路径测试**: 大多数 Engine 方法的异常降级路径都被覆盖
- ✅ **序列化测试**: `to_dict()` / `from_dict()` round-trip 测试覆盖了主要模型
- ❌ **缺少集成测试**: 没有端到端测试（模拟完整 LLM 调用链 + 解析 + 返回）

---

## 10. 配置与部署审计

### 10.1 Docker 部署

```dockerfile
FROM python:3.11-slim
COPY . .
RUN pip install --no-cache-dir -e .
EXPOSE 11448
CMD ["fusion-k12", "serve", "--host", "127.0.0.1", "--port", "11448"]
```

#### 问题 🔴
1. **`.dockerignore` 缺失**: `COPY . .` 会包含 `.venv/`, `.git/`, `__pycache__/`, `.pytest_cache/` 等无用文件  
   **建议**: 添加 `.dockerignore` 排除构建缓存和虚拟环境

2. **多阶段构建未使用**: 无多阶段构建，镜像体积大（包含 build tools）  
   **建议**: 使用多阶段构建，最终镜像仅包含运行时依赖

3. **`fusion-mlx` 依赖未标明**: Docker compose 依赖 `fusion-mlx:latest` 镜像，但没有提供构建说明  
   **建议**: 在文档中明确标注 fusion-mlx 镜像来源

4. **无 `--preload` 工作进程**: `uvicorn` 默认单进程  
   **建议**: 使用 `gunicorn -w 4 -k uvicorn.workers.UvicornWorker` 多进程

### 10.2 环境变量

| 变量 | 默认值 | 使用处 | 状态 |
|------|--------|-------|------|
| `FUSION_MLX_URL` | `http://localhost:11434/v1` | MLXClient | ✅ 文档 |
| `FUSION_K12_PORT` | `11448` | serve.py | ✅ 文档 |

**建议**: 增加配置项：`FUSION_K12_MODEL`, `FUSION_K12_LOG_LEVEL`, `FUSION_K12_SAFETY_LEVEL`

---

## 11. 发现的问题与修复建议

### P0 — 必须修复

| ID | 问题 | 文件 | 建议 |
|----|------|------|------|
| P0-1 | `_plans` 无上限增长 | `curriculum/engine.py:64` | 实现 LRU 缓存，限制最大 100 条 |
| P0-2 | 版本号不一致 | `__init__.py:12` vs `pyproject.toml:3` | 统一版本号来源，从 pyproject.toml 读取 |
| P0-3 | `apscheduler` 未声明依赖 | `pyproject.toml` | 添加 `agent = ["apscheduler>=3.10"]` 可选依赖 |

### P1 — 重要改进

| ID | 问题 | 文件 | 建议 |
|----|------|------|------|
| P1-1 | `_name_map` 无上限 | `desensitize/anonymizer.py:15-16` | 添加最大条目限制，或改为 LRU |
| P1-2 | 敏感词库仅 14 词 | `safety/data/sensitive_words.txt` | 扩展至覆盖 8 大类教育场景 |
| P1-3 | serve.py/CLI 无速率限制 | `serve.py`, `cli.py` | 添加 rate limiting 中间件 |
| P1-4 | `cli.py` 754 行 | `cli.py` | 按命令组拆分到 `cli/` 子包 |
| P1-5 | `serve.py` 612 行 | `serve.py` | 使用 APIRouter 按模块拆分路由 |

### P2 — 建议改进

| ID | 问题 | 文件 | 建议 |
|----|------|------|------|
| P2-1 | MLXClient 无超时配置 | `ai_client.py:25` | 添加 `timeout` 参数 |
| P2-2 | 模型自动检测失败重试 | `ai_client.py:32-36` | 失败后设置 sentinel |
| P2-3 | DLLM 审查无 schema 校验 | `safety/filter.py:109` | 添加 pydantic schema |
| P2-4 | Docker 镜像大 | `Dockerfile` | 多阶段构建 + .dockerignore |
| P2-5 | 缺失配置管理 | 全项目 | 添加 `config.py` + 环境变量支持 |
| P2-6 | `_parse_cron` 过于简单 | `agent/scheduler.py:140` | 使用 `croniter` |
| P2-7 | `_load_assessments` 路径安全 | `serve.py:345` | 路径白名单验证 |
| P2-8 | CLI 未测试命令达 20 个 | `tests/test_coverage.py` | 扩展覆盖到所有 CLI 命令 |

---

## 12. 改进路线图

### Phase 1 — 紧急修复 (1-2天)

```
□ P0-1: _plans LRU 缓存
□ P0-2: 统一版本号
□ P0-3: 添加 apscheduler 依赖声明
□ P1-1: _name_map 上限控制
```

### Phase 2 — 架构优化 (3-5天)

```
□ P1-3: API 速率限制
□ P1-4: cli.py 拆分
□ P1-5: serve.py APIRouter 拆分
□ P2-1: MLXClient 超时配置
□ P2-5: 配置管理模块
```

### Phase 3 — 安全增强 (2-3天)

```
□ P1-2: 扩展敏感词库
□ P2-3: LLM 审查 schema 校验
□ P2-4: Docker 构建优化
□ P2-7: 路径安全检查加固
```

### Phase 4 — 测试与质量 (2-3天)

```
□ P2-6: croniter 替换
□ P2-8: 扩展 CLI/API 测试覆盖
□ 添加集成测试
□ 配置 pyright/mypy
```

---

## 附录 A — 文件清单

| 文件 | 行数 | 功能 |
|------|------|------|
| `cli.py` | 754 | CLI 入口，30+ 命令 |
| `serve.py` | 612 | FastAPI HTTP 服务 |
| `analytics/engine.py` | 555 | 学情分析引擎 |
| `agent/scheduler.py` | 169 | 任务调度器 |
| `agent/executor.py` | 131 | 任务执行器 |
| `agent/tasks.py` | 166 | 预定义任务库 |
| `agent/models.py` | 110 | Agent 数据模型 |
| `curriculum/engine.py` | 184 | 课程规划引擎 |
| `assessment/grader.py` | 155 | 评估批改引擎 |
| `subjects/expert.py` | 117 | 学科专家引擎 |
| `personalization/engine.py` | 97 | 个性化引擎 |
| `content/generator.py` | 122 | 内容生成引擎 |
| `differentiation/engine.py` | 291 | 分层教学引擎 |
| `standards/aligner.py` | 115 | 课标对齐器 |
| `standards/query.py` | 131 | 课标查询 |
| `standards/loader.py` | 135 | 课标加载器 |
| `standards/models.py` | 95 | 课标数据模型 |
| `safety/filter.py` | 159 | 内容过滤器 |
| `safety/age_checker.py` | 118 | 适龄检查器 |
| `safety/wordlist.py` | 60 | 敏感词库 |
| `safety/models.py` | 82 | 安全数据模型 |
| `desensitize/anonymizer.py` | 102 | 数据脱敏器 |
| `desensitize/models.py` | 66 | 脱敏数据模型 |
| `ai_client.py` | 43 | AI 客户端 |
| `analytics/loader.py` | 103 | 数据导入 |
| `analytics/models.py` | 255 | 分析数据模型 |
| `standards/data/math_g1-6.json` | 633 | 数学课标数据 |
| `safety/data/sensitive_words.txt` | 19 | 敏感词列表 |
| `safety/data/age_ratings.json` | 16 | 适龄配置 |

## 附录 B — 依赖图

```
fusion-k12-teacher
├── fusion-core (MLX client 底层)
│   └── httpx (HTTP 通信)
├── pydantic (数据模型/序列化)
├── click (CLI 框架)
├── fastapi (HTTP API) [optional: web]
│   └── uvicorn (ASGI 服务器) [optional: web]
├── apscheduler (任务调度) [NOT DECLARED]
└── pytest + pytest-asyncio + pytest-cov (测试) [optional: test]
```

---

*报告结束。*
