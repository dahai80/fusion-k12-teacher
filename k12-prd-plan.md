# Fusion-K12-Teacher 可落地方案与整体计划

> 基于 claude-k12-teacher-insight.md 差距分析 + ar.md 国内合规约束
> 目标：对标 Claude K-12 Teacher 六大场景，分阶段交付可落地的国内本地化教育 AI

---

## 一、版本规划总览

| 版本 | 代号 | 核心主题 | 关键交付 | 预计周期 |
|------|------|---------|---------|---------|
| v0.2 | ✅ 已发布 | HTTP API | 5 端点 + serve CLI | 已完成 |
| v0.3 | 课标基石 | 国内课标知识图谱 + 分层教学引擎 | 课标数据层 + 三层分层输出 | 4 周 |
| v0.4 | 学情闭环 | 学情数据分析 + 教学反馈循环 | 班级画像 + 错题归因 + 辅导方案 | 4 周 |
| v0.5 | Agent 起步 | 任务编排 + 批量自动化 | 定时任务 + 批量生成工作流 | 3 周 |
| v0.6 | 安全加固 | 内容过滤 + 合规体系 | 敏感词过滤 + 适龄审查 + 数据脱敏 | 2 周 |
| v1.0 | 正式发布 | 全功能集成 + 文档完善 | 完整 CLI/API + 部署文档 + 示例 | 2 周 |

---

## 二、v0.3 课标基石 — 详细方案

### 2.1 国内课标知识图谱

#### 目标
构建覆盖义务教育 + 高中的结构化课标体系，所有生成内容从课标知识点出发反向生成。

#### 数据来源

| 学段 | 课标文件 | 知识点数量（估） |
|------|---------|---------------|
| 小学 1-6 | 《义务教育课程标准（2022年版）》语数英科 | ~800 |
| 初中 7-9 | 《义务教育课程标准》全学科 | ~1200 |
| 高中 10-12 | 《普通高中课程标准（2017版2020修订）》 | ~1500 |

#### 数据结构设计

```python
# fusion_k12_teacher/standards/models.py

@dataclass
class KnowledgePoint:
    id: str                     # "math-g3-nf-01"
    subject: str                # "数学"
    grade: str                  # "3"
    strand: str                 # "数与代数"
    topic: str                  # "分数的初步认识"
    description: str            # 课标原文描述
    prerequisites: List[str]    # 前置知识点 ID 列表
    progression_next: List[str] # 进阶知识点 ID 列表
    difficulty_level: str       # "basic/standard/advanced"
    curriculum_code: str        # 课标编码 "2022-数学-3-NF.1"

@dataclass
class CurriculumStandard:
    id: str
    name: str                   # "义务教育数学课程标准（2022年版）"
    year: str                   # "2022"
    subject: str
    grade_range: str            # "1-6"
    knowledge_points: List[KnowledgePoint]
```

#### 存储方案

```
fusion_k12_teacher/standards/
├── __init__.py
├── models.py              # KnowledgePoint, CurriculumStandard 数据类
├── loader.py              # 课标数据加载器（JSON → 内存）
├── query.py               # 课标查询 API（按学科/年级/知识点检索）
├── aligner.py             # 课标对齐器（生成内容 → 课标知识点映射）
└── data/
    ├── math_g1-6.json     # 小学数学课标知识点
    ├── math_g7-9.json     # 初中数学课标知识点
    ├── chinese_g1-6.json  # 小学语文课标知识点
    ├── chinese_g7-9.json  # 初中语文课标知识点
    ├── english_g1-6.json  # 小学英语课标知识点
    ├── science_g1-6.json  # 小学科学课标知识点
    ├── physics_g8-9.json  # 初中物理课标知识点
    ├── chemistry_g8-9.json# 初中化学课标知识点
    ├── biology_g7-9.json  # 初中生物课标知识点
    ├── history_g7-9.json  # 初中历史课标知识点
    └── high_school/       # 高中课标（v0.3 可先建框架，内容后续填充）
```

#### 课标查询 API

```python
class StandardsQuery:
    def get_knowledge_points(self, subject: str, grade: str) -> List[KnowledgePoint]
    def get_prerequisites(self, point_id: str) -> List[KnowledgePoint]
    def get_progression(self, point_id: str) -> List[KnowledgePoint]
    def find_by_topic(self, subject: str, grade: str, topic: str) -> List[KnowledgePoint]
    def validate_coverage(self, subject: str, grade: str, objectives: List[str]) -> CoverageReport
```

#### 课标对齐器

生成内容时自动注入课标上下文，替代当前纯 prompt 方式：

```python
class StandardsAligner:
    def align_lesson_plan(self, subject: str, grade: str, topic: str) -> AlignmentContext:
        """返回课标对齐上下文，注入到 engine prompt"""
        points = self.query.find_by_topic(subject, grade, topic)
        prerequisites = [self.query.get_prerequisites(p.id) for p in points]
        return AlignmentContext(
            knowledge_points=points,
            prerequisites=prerequisites,
            curriculum_codes=[p.curriculum_code for p in points],
            suggested_objectives=[p.description for p in points],
            must_cover=[p.id for p in points if p.difficulty_level == "basic"],
            optional_advanced=[p.id for p in points if p.difficulty_level == "advanced"],
        )
```

### 2.2 分层教学引擎

#### 目标
所有生成内容默认三层输出：学困生/中等生/优等生，每层材料难度、深度、形式自适应。

#### 新增模块

```
fusion_k12_teacher/differentiation/
├── __init__.py
├── engine.py              # DifferentiationEngine 分层教学引擎
├── level_config.py        # 三层配置（学困/中等/优等参数定义）
└── templates/             # 分层 prompt 模板
    ├── lesson_plan.md     # 分层教案模板
    ├── worksheet.md       # 分层工作纸模板
    ├── quiz.md            # 分层测验模板
    └── activity.md        # 分层课堂活动模板
```

#### 核心数据结构

```python
@dataclass
class DifferentiatedContent:
    topic: str
    grade: str
    subject: str
    struggling: LayerContent    # 学困生材料
    standard: LayerContent      # 中等生材料
    advanced: LayerContent      # 优等生材料
    group_tasks: List[GroupTask] # 分组课堂任务单

@dataclass
class LayerContent:
    explanation: str           # 概念讲解（通俗度不同）
    examples: List[str]        # 例题（难度不同）
    exercises: List[Dict]      # 练习题（难度/数量不同）
    hints: List[str]           # 提示（学困生更多）
    extension: str             # 拓展（优等生专属）

@dataclass
class GroupTask:
    group_name: str            # "A组(基础)" / "B组(标准)" / "C组(挑战)"
    task_description: str
    expected_output: str
    time_allocation: str
```

#### 分层策略配置

```python
LEVEL_CONFIGS = {
    "struggling": {
        "vocabulary_level": "基础",
        "example_complexity": 1,        # 最简
        "exercise_count": 5,            # 题量少
        "hint_density": "high",         # 提示密集
        "scaffold_steps": True,         # 脚手架式拆解
        "extension": False,             # 无拓展
        "max_abstraction": "concrete",  # 具象为主
    },
    "standard": {
        "vocabulary_level": "标准",
        "example_complexity": 2,
        "exercise_count": 8,
        "hint_density": "medium",
        "scaffold_steps": False,
        "extension": False,
        "max_abstraction": "semi-abstract",
    },
    "advanced": {
        "vocabulary_level": "拓展",
        "example_complexity": 3,        # 最复杂
        "exercise_count": 5,            # 题量少但难
        "hint_density": "low",          # 提示少
        "scaffold_steps": False,
        "extension": True,              # 有拓展探究
        "max_abstraction": "abstract",  # 抽象推理
    },
}
```

#### 分层与课标联动

```python
class DifferentiationEngine:
    def __init__(self, mlx: MLXClient, standards: StandardsQuery):
        self.mlx = mlx
        self.standards = standards

    async def generate_differentiated_lesson(
        self, subject: str, grade: str, topic: str, duration: int = 45
    ) -> DifferentiatedContent:
        # 1. 从课标获取知识点 + 进阶路径
        alignment = self.standards.find_by_topic(subject, grade, topic)
        # 2. 生成三层内容（三次 LLM 调用，不同 prompt 模板）
        # 3. 生成分组任务单
        ...
```

#### 与现有引擎集成

- `CurriculumEngine.generate_lesson_plan()` 新增 `differentiated: bool = False` 参数
- 为 True 时返回 `DifferentiatedContent` 而非 `LessonPlan`
- `generate_quiz()` 新增 `level: str = "standard"` 参数，按层出题

### 2.3 课标数据建设方案

#### 阶段一：小学数学课标（v0.3 MVP）

手工整理 + LLM 辅助提取，覆盖小学 1-6 年级数学全部知识点：

```
1. 从《义务教育数学课程标准（2022年版）》提取原文
2. 按学段/领域/主题拆分为 KnowledgePoint 结构
3. 标注前置知识点依赖关系（如：分数→小数→百分数）
4. 标注难度层级（basic/standard/advanced）
5. 存储 JSON，通过 loader.py 加载
```

预计 ~200 个知识点，1-2 天完成。

#### 阶段二：小学语文 + 英语 + 科学课标（v0.3 完整）

各学科同流程建设，预计 ~600 个知识点，3-4 天。

#### 阶段三：初中全学科课标（v0.4 范围）

预计 ~1200 个知识点，5-7 天。

---

## 三、v0.4 学情闭环 — 详细方案

### 3.1 学情数据分析引擎

#### 新增模块

```
fusion_k12_teacher/analytics/
├── __init__.py
├── engine.py              # AnalyticsEngine 学情分析引擎
├── class_profile.py       # 班级学情画像
├── error_analyzer.py      # 错题归因分析
├── student_tracker.py     # 学生个体追踪
└── report_builder.py      # 报告构建器
```

#### 核心数据结构

```python
@dataclass
class ClassProfile:
    class_id: str
    subject: str
    grade: str
    period: str                      # "2026春季学期"
    total_students: int
    avg_score: float
    score_distribution: Dict[str, int]  # {"90-100": 5, "80-89": 12, ...}
    weak_knowledge_points: List[WeakPoint]
    strong_knowledge_points: List[str]
    student_risk_levels: Dict[str, str]  # student_id → "high/medium/low"
    generated_at: str

@dataclass
class WeakPoint:
    knowledge_point_id: str
    knowledge_point_name: str
    error_rate: float               # 0.0-1.0
    affected_students: List[str]    # student_id 列表
    common_mistakes: List[str]      # 高频错误类型
    suggested_remedial: str         # 建议补救措施

@dataclass
class StudentProfile:
    student_id: str
    name: str
    grade: str
    subject: str
    overall_level: str              # "struggling/standard/advanced"
    knowledge_mastery: Dict[str, float]  # point_id → 0.0-1.0
    learning_trend: str             # "improving/stable/declining"
    risk_indicators: List[str]
    recommended_actions: List[str]

@dataclass
class ErrorAnalysis:
    error_id: str
    knowledge_point_id: str
    error_type: str                 # "conceptual/procedural/careful/unknown"
    frequency: int                  # 出现次数
    sample_responses: List[str]     # 典型错误回答
    root_cause: str                 # 根因分析
    remediation: str                # 补救策略
```

#### AnalyticsEngine 方法

```python
class AnalyticsEngine:
    async def build_class_profile(
        self, class_id: str, subject: str, grade: str,
        assessment_data: List[StudentAssessment]
    ) -> ClassProfile

    async def build_student_profile(
        self, student_id: str, subject: str, grade: str,
        history: List[StudentAssessment]
    ) -> StudentProfile

    async def analyze_errors(
        self, subject: str, grade: str,
        responses: List[Dict]  # [{question, student_answer, correct_answer}]
    ) -> List[ErrorAnalysis]

    async def generate_remedial_plan(
        self, student_id: str, weak_points: List[WeakPoint]
    ) -> RemedialPlan

    async def generate_class_report(
        self, class_profile: ClassProfile
    ) -> str  # Markdown 格式报告
```

### 3.2 学情数据输入

#### 数据格式定义

```python
@dataclass
class StudentAssessment:
    student_id: str
    student_name: str
    assessment_id: str
    date: str                       # "2026-07-28"
    subject: str
    grade: str
    scores: Dict[str, float]        # 题目ID → 得分
    responses: List[Dict]           # [{question_id, question, answer, correct, points, max_points}]
    total_score: float
    max_score: float
```

#### 数据导入方式

1. **JSON 文件**：`analytics.load_from_json(path)` — 批量导入
2. **CSV 文件**：`analytics.load_from_csv(path)` — Excel 导出格式适配
3. **API 接口**：`POST /api/analytics/upload` — HTTP 上传
4. **手动录入**：CLI `fusion-k12 analytics record` — 交互式录入

### 3.3 教学反馈循环

```
             ┌──────────────────────────────┐
             │                              │
             ▼                              │
    ┌──────────────┐    ┌───────────┐    ┌──┴──────────┐
    │ 学情数据采集  │───▶│ 学情分析   │───▶│ 教学策略调整 │
    └──────────────┘    └───────────┘    └─────────────┘
                             │                    │
                             ▼                    ▼
                      ┌───────────┐      ┌───────────────┐
                      │ 错题归因   │      │ 分层教学调整    │
                      └───────────┘      └───────────────┘
                             │                    │
                             ▼                    ▼
                      ┌───────────┐      ┌───────────────┐
                      │ 补救方案   │      │ 重新生成教案/习题│
                      └───────────┘      └───────────────┘
```

**闭环流程**：
1. 教师使用 `generate_quiz` 出题 → 学生作答
2. 教师录入/上传成绩 → `build_class_profile` 分析
3. 系统输出薄弱知识点 + 高频错题 → `analyze_errors` 归因
4. 自动建议调整 → `generate_remedial_plan` 生成补救方案
5. 调整后的教案/习题 → 下一轮教学

### 3.4 新增 HTTP API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/analytics/class-profile` | POST | 生成班级学情画像 |
| `/api/analytics/student-profile` | POST | 生成学生个体画像 |
| `/api/analytics/error-analysis` | POST | 错题归因分析 |
| `/api/analytics/remedial-plan` | POST | 生成补救方案 |
| `/api/analytics/upload` | POST | 上传学情数据（JSON/CSV） |

---

## 四、v0.5 Agent 起步 — 详细方案

### 4.1 任务编排框架

#### 新增模块

```
fusion_k12_teacher/agent/
├── __init__.py
├── scheduler.py           # 任务调度器
├── tasks.py               # 预定义任务库
├── workflow.py            # 工作流编排
└── executor.py            # 任务执行器
```

#### 核心数据结构

```python
@dataclass
class TeachingTask:
    id: str
    name: str                      # "每周学情汇总"
    task_type: str                 # "scheduled/triggered/batch"
    schedule: str                  # cron 表达式 "0 18 * * 5" = 每周五18:00
    steps: List[TaskStep]
    enabled: bool = True
    last_run: str = ""
    last_status: str = ""          # "success/failed/running"

@dataclass
class TaskStep:
    engine: str                    # "curriculum/assessment/analytics/..."
    method: str                    # "generate_lesson_plan"
    params: Dict[str, Any]
    output_key: str                # 输出变量名，供后续步骤引用
    depends_on: List[str] = []     # 依赖的前置步骤 output_key

@dataclass
class TaskResult:
    task_id: str
    status: str
    started_at: str
    completed_at: str
    step_results: Dict[str, Any]
    summary: str
```

### 4.2 预定义任务库

| 任务名 | 触发方式 | 步骤链 | 产出 |
|--------|---------|--------|------|
| `weekly_prep` | 每周定时 | quiz → worksheet → slides | 下周全套备课材料 |
| `weekly_summary` | 每周五 | analytics.class_profile → analytics.error_analysis → report_builder | 班级学情周报 |
| `daily_homework_review` | 每日 | analytics.error_analysis → differentiation.remedial | 每日作业错题补救 |
| `monthly_report` | 每月末 | analytics.class_profile → analytics.student_profile → report_builder | 月度教学报告 |
| `batch_differentiated_materials` | 手动触发 | differentiation.generate_differentiated_lesson × N | 批量分层教学材料 |

### 4.3 CLI 命令

```bash
# 查看所有可用任务
fusion-k12 agent tasks

# 启用/禁用任务
fusion-k12 agent enable weekly_prep
fusion-k12 agent disable daily_homework_review

# 立即执行任务
fusion-k12 agent run weekly_prep

# 查看任务执行历史
fusion-k12 agent history

# 启动 Agent 守护进程
fusion-k12 agent start
fusion-k12 agent stop
```

### 4.4 技术选型

- **调度器**：`APScheduler`（轻量，无外部依赖，适合本地单机）
- **持久化**：SQLite（任务配置 + 执行历史）
- **执行方式**：后台线程（`fusion-k12 agent start` 启动守护进程）
- **HTTP API 集成**：任务管理端点挂到现有 serve.py

---

## 五、v0.6 安全加固 — 详细方案

### 5.1 内容过滤引擎

```
fusion_k12_teacher/safety/
├── __init__.py
├── filter.py              # ContentFilter 内容过滤器
├── wordlist.py            # 敏感词库管理
├── age_checker.py         # 适龄内容审查
└── data/
    ├── sensitive_words.txt # 敏感词库
    └── age_ratings.json   # 适龄等级配置
```

#### 过滤策略

| 过滤层 | 实现方式 | 说明 |
|--------|---------|------|
| 敏感词过滤 | 正则匹配 + 词库 | 暴力/色情/政治敏感词 |
| 适龄审查 | 课标对齐 + 年级匹配 | 内容深度不超过目标年级 |
| LLM 自审查 | prompt 注入安全指令 | 生成前注入"面向K-12学生"约束 |
| 输出校验 | 关键词检测 + 语义匹配 | 生成后二次检查 |

### 5.2 数据脱敏

- 学生姓名 → 编号化（张三 → S001）
- 学情数据本地加密存储（SQLite + SQLCipher）
- 导出报告自动脱敏
- API 请求/响应日志不含学生个人信息

---

## 六、v1.0 正式发布 — 详细方案

### 6.1 完整 CLI 命令体系

```bash
# 课标查询
fusion-k12 standards list --subject 数学 --grade 3
fusion-k12 standards show math-g3-nf-01

# 分层教学
fusion-k12 lesson plan-diff 数学 3 分数          # 三层分层教案
fusion-k12 lesson quiz-diff 数学 3 分数           # 三层分层测验
fusion-k12 content worksheet-diff 英语 3 动物     # 三层分层工作纸

# 学情分析
fusion-k12 analytics class-profile --data scores.json
fusion-k12 analytics student-profile 张三 --subject 数学
fusion-k12 analytics errors --data responses.json
fusion-k12 analytics remedial 张三 --weak-points "分数,小数"

# Agent
fusion-k12 agent tasks
fusion-k12 agent run weekly_prep
fusion-k12 agent start

# 内容过滤
fusion-k12 safety check "要检查的文本"

# HTTP API
fusion-k12 serve --port 11448
```

### 6.2 完整 HTTP API 端点

| 端点 | 方法 | 版本 |
|------|------|------|
| `/api/health` | GET | v0.2 |
| `/api/curriculum/plan` | POST | v0.2 |
| `/api/assessment/grade` | POST | v0.2 |
| `/api/subject/explain` | POST | v0.2 |
| `/api/personalize/path` | POST | v0.2 |
| `/api/content/generate` | POST | v0.2 |
| `/api/curriculum/plan-diff` | POST | v0.3 |
| `/api/curriculum/quiz-diff` | POST | v0.3 |
| `/api/standards/list` | GET | v0.3 |
| `/api/standards/query` | GET | v0.3 |
| `/api/analytics/class-profile` | POST | v0.4 |
| `/api/analytics/student-profile` | POST | v0.4 |
| `/api/analytics/error-analysis` | POST | v0.4 |
| `/api/analytics/remedial-plan` | POST | v0.4 |
| `/api/analytics/upload` | POST | v0.4 |
| `/api/agent/tasks` | GET | v0.5 |
| `/api/agent/run` | POST | v0.5 |
| `/api/agent/schedule` | POST | v0.5 |

### 6.3 部署方案

| 场景 | 部署方式 | 说明 |
|------|---------|------|
| 个人教师本地 | `pip install + fusion-k12 serve` | 无备案要求 |
| 学校内网 | Docker 镜像 + docker-compose | 校内非商用，无需算法备案 |
| 教培机构商用 | K8s 集群 + 算法备案 + 境内服务器 | 需完成网信办算法备案 |

---

## 七、里程碑时间线

```
2026-07    08    09    10    11    12
           │     │     │     │     │
v0.2 ✅ ───┤     │     │     │     │
           │     │     │     │     │
v0.3 课标 ─┤─────┤     │     │     │
           │     │     │     │     │
v0.4 学情 ─┤─────┤─────┤     │     │
           │     │     │     │     │
v0.5 Agent ┤─────┤─────┤─────┤     │
           │     │     │     │     │
v0.6 安全 ─┤─────┤─────┤─────┤─────┤
           │     │     │     │     │
v1.0 发布 ─┤─────┤─────┤─────┤─────┤─────▶
```

---

## 八、技术风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| 课标知识点手工整理工作量大 | 延迟 v0.3 交付 | LLM 辅助提取 + 教师社区众包 |
| 本地模型能力限制（7B-9B） | 分层/学情分析质量不如云端 | prompt 工程优化 + 多轮调用策略 |
| 学情数据格式不统一 | 学情分析难以通用 | 定义标准数据格式 + 提供 CSV 适配器 |
| Agent 定时任务稳定性 | 守护进程崩溃 | APScheduler 持久化 + 自动重启 |
| 敏感词库维护成本 | 过滤误杀/漏杀 | 分级过滤 + 人工复审机制 |

---

## 九、成功指标

| 指标 | v0.3 目标 | v1.0 目标 |
|------|----------|----------|
| 课标覆盖率 | 小学4学科 | 义务教育全学科 |
| 分层内容可用率 | ≥70% | ≥85% |
| 学情分析准确率 | ≥60% | ≥80% |
| 错题归因准确率 | ≥50% | ≥75% |
| Agent 任务完成率 | ≥80% | ≥95% |
| 内容过滤召回率 | ≥90% | ≥98% |
| 测试覆盖 | ≥80% | ≥90% |
