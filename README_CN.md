<div align="center">
  <h1>🍎 Fusion-K12-Teacher</h1>
  <p><strong>Local AI-powered K-12 education assistant for macOS Apple Silicon</strong></p>
  <p><strong>本地 AI K-12 教育助手 — macOS Apple Silicon 原生</strong></p>
  <p><em>100% offline, zero data upload, powered by fusion-mlx. The domestic alternative to Claude K-12 Teacher.</em></p>
  <p><em>100% 本地离线，数据不出境，基于 fusion-mlx。国内 Claude K-12 Teacher 替代方案。</em></p>
  <p>
    <a href="README.md">English</a> | <strong>中文</strong>
  </p>
</div>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-blue" alt="Python">
  <img src="https://img.shields.io/badge/macOS-Apple%20Silicon-brightgreen" alt="macOS">
  <img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="License">
  <img src="https://img.shields.io/badge/AI-MLX%20Native-orange" alt="MLX">
  <img src="https://img.shields.io/badge/Offline-First-important" alt="Offline">
  <img src="https://img.shields.io/badge/tests-272%20passed-brightgreen" alt="Tests">
</p>

---

## 📋 Overview / 产品简介

**Fusion-K12-Teacher** is a local AI-powered K-12 education assistant, designed as a domestic alternative to **Claude K-12 Teacher**. Built on `fusion-mlx`, it provides comprehensive teaching support — lesson planning, assessment, subject expertise, personalized learning, and content generation — all **100% offline** with zero data uploaded.

**Fusion-K12-Teacher** 是一款本地 AI K-12 教育助手，基于 `fusion-mlx` 构建，**100% 本地离线，数据不出境**，是国内环境下 Claude K-12 Teacher 的合规替代方案。

### Claude K-12 Teacher Comparison / 对标 Claude K-12 Teacher

| Capability / 能力 | Claude K-12 Teacher | Fusion-K12-Teacher |
|------------|---------------------|-------------------|
| **Data residency / 数据本地化** | ❌ Cloud-only / 云端处理 | ✅ **100% local / 100% 本地** |
| **Offline capable / 离线运行** | ❌ Requires internet / 需联网 | ✅ **Fully offline / 完全离线** |
| **China accessible / 国内可访问** | ❌ Blocked / 被屏蔽 | ✅ **Fully accessible / 完全可用** |
| **Lesson planning / 教案生成** | ✅ Standards-aligned / 标准对齐 | ✅ Standards-aligned / 标准对齐 |
| **Quiz generation / 测验生成** | ✅ Auto-generate / 自动出题 | ✅ Auto-generate / 自动出题 |
| **Essay grading / 作文批改** | ✅ Rubric-based / 评分标准 | ✅ Rubric-based / 评分标准 |
| **Subject expertise / 学科知识** | ✅ STEM/Languages/Arts | ✅ STEM/Languages/Arts |
| **Personalized learning / 个性化学习** | ✅ Adaptive paths / 自适应路径 | ✅ Adaptive paths / 自适应路径 |
| **Content generation / 内容生成** | ✅ Worksheets, slides / 工作纸/课件 | ✅ Worksheets, slides, games / 工作纸/课件/游戏 |
| **Parent communication / 家校沟通** | ✅ Templates / 模板 | ✅ Templates / 模板 |
| **STEM projects / STEM 项目** | ✅ PBL design / PBL 设计 | ✅ PBL design / PBL 设计 |
| **Language learning / 语言学习** | ✅ Activities / 活动设计 | ✅ Activities / 活动设计 |
| **Curriculum standards / 课标对齐** | ❌ Not built-in / 无内置 | ✅ **2022 Curriculum Knowledge Graph / 2022课标知识图谱** |
| **Differentiated teaching / 分层教学** | ❌ Not available / 不支持 | ✅ **Three-tier lessons / 三层差异化内容** |
| **Learning analytics / 学情分析** | ❌ Not available / 不支持 | ✅ **Class/student profiles, error analysis / 班级/学生画像、错题归因** |
| **Task automation / 任务自动化** | ❌ Not available / 不支持 | ✅ **Scheduled multi-step teaching tasks / 定时多步骤教学任务** |
| **Content safety / 内容安全** | ❌ Not available / 不支持 | ✅ **Multi-layer content filtering & age check / 多层内容过滤与适龄检查** |
| **Data desensitization / 数据脱敏** | ❌ Not available / 不支持 | ✅ **Name anonymization & field masking / 姓名匿名化 & 字段脱敏** |
| **Docker deployment / Docker 部署** | ❌ Not available / 不支持 | ✅ **Docker Compose & K8s ready / Docker Compose & K8s 就绪** |
| **License / 开源协议** | Enterprise subscription / 企业订阅 | **Apache 2.0 (free) / Apache 2.0 免费** |

---

## 🚀 Quick Start / 快速开始

```bash
# Clone / 克隆
git clone https://github.com/dahai80/fusion-k12-teacher.git
cd fusion-k12-teacher

# Install / 安装
pip install -e .

# Generate a lesson plan / 生成教案
fusion-k12 lesson plan 数学 3 分数

# Generate a quiz / 生成测验
fusion-k12 lesson quiz 数学 3 分数 --questions 5

# Grade an essay / 批改作文
fusion-k12 assess essay "今天真是美好的一天..."

# Explain a concept / 解释概念
fusion-k12 subject explain 科学 5 光合作用

# Create a learning path / 创建学习路径
fusion-k12 personalize path 张三 3 数学 掌握分数运算

# Generate a worksheet / 生成工作纸
fusion-k12 content worksheet 英语 3 动物

# Start HTTP API server / 启动 HTTP API 服务
fusion-k12 serve --port 11448
```

---

## 📖 Modules / 模块

### 1. Curriculum Engine / 课程规划引擎 (`curriculum/`)

Lesson planning, quiz generation, unit planning.
教案生成、测验生成、单元计划。

| Command | Description |
|---------|-------------|
| `lesson plan <subject> <grade> <topic>` | Generate standards-aligned lesson plan / 生成标准对齐教案 |
| `lesson quiz <subject> <grade> <topic>` | Generate quiz with multiple question types / 生成多题型测验 |
| `generate_unit_plan()` | Design multi-week unit plans / 设计多周单元计划 |

### 2. Assessment Engine / 评估引擎 (`assessment/`)

Essay grading, math grading, student reports, rubrics.
作文批改、数学批改、学生报告、评分标准。

| Command | Description |
|---------|-------------|
| `assess essay <text>` | Grade essay with rubric scoring / 按评分标准批改作文 |
| `grade_math()` | Grade math problems with step analysis / 按步骤分析批改数学 |
| `generate_report()` | Create semester learning reports / 生成学期学习报告 |
| `generate_rubric()` | Design scoring rubrics / 设计评分标准 |

### 3. Subject Expert / 学科专家 (`subjects/`)

STEM, Language, Arts, and Humanities knowledge base.
STEM、语言、文科与人文知识库。

| Command | Description |
|---------|-------------|
| `subject explain <subject> <grade> <concept>` | Explain concepts at grade level / 按年级水平解释概念 |
| `generate_exercise()` | Generate subject-specific exercises / 生成学科练习 |
| `stem_project()` | Design STEM project-based learning / 设计 STEM 项目学习 |
| `language_activity()` | Create language learning activities / 创建语言学习活动 |

### 4. Personalization Engine / 个性化引擎 (`personalization/`)

Adaptive learning paths, skill diagnosis, resource recommendations.
自适应学习路径、能力诊断、资源推荐。

| Command | Description |
|---------|-------------|
| `personalize path <student> <grade> <subject> <goal>` | Create personalized learning path / 创建个性化学习路径 |
| `diagnose_skills()` | Diagnose student skill levels / 诊断学生能力水平 |
| `recommend_resources()` | Recommend targeted learning resources / 推荐针对性学习资源 |

### 5. Content Generator / 内容生成器 (`content/`)

Worksheets, flashcards, slides, educational games, parent communication.
工作纸、闪卡、课件、教育游戏、家校沟通。

| Command | Description |
|---------|-------------|
| `content worksheet <subject> <grade> <topic>` | Generate practice worksheets / 生成练习工作纸 |
| `generate_flashcards()` | Create study flashcards / 创建学习闪卡 |
| `generate_lesson_slides()` | Design lesson slide outlines / 设计课件大纲 |
| `generate_educational_game()` | Design classroom learning games / 设计课堂学习游戏 |
| `generate_parent_communication()` | Write parent communication templates / 撰写家校沟通模板 |

### 6. Curriculum Standards / 课标知识图谱 (`standards/`) — v0.3

Curriculum standards knowledge graph aligned with 2022 national curriculum standards (《义务教育课程标准（2022年版）》).

| Command | Description |
|---------|-------------|
| `standards list [--subject] [--grade]` | List knowledge points with filters / 列出知识点（可过滤） |
| `standards show <point_id>` | Show knowledge point details / 显示知识点详情 |
| `StandardsQuery.get_knowledge_points()` | Query by subject & grade / 按学科年级查询 |
| `StandardsQuery.find_by_topic()` | Fuzzy search by topic keyword / 按主题关键词模糊搜索 |
| `StandardsAligner.align()` | Generate alignment context for prompts / 生成对齐上下文 |
| `StandardsAligner.validate_alignment()` | Check coverage of mandatory points / 检查必考点覆盖 |

### 7. Differentiated Teaching / 分层教学 (`differentiation/`) — v0.3

Three-tier differentiated content: struggling / standard / advanced.
三层差异化内容：学困生 / 中等生 / 优等生。

| Command | Description |
|---------|-------------|
| `lesson plan-diff <subject> <grade> <topic>` | Generate three-tier lesson plan / 生成三层分层教案 |
| `lesson quiz-diff <subject> <grade> <topic>` | Generate three-tier quiz / 生成三层分层测验 |
| `DifferentiationEngine.generate_differentiated_lesson()` | Full differentiated lesson / 完整分层教案 |
| `DifferentiationEngine.generate_differentiated_quiz()` | Full differentiated quiz / 完整分层测验 |

### 8. Learning Analytics / 学情分析 (`analytics/`) — v0.4

Class profiles, student profiles, error root-cause analysis, remedial plans, class reports.
班级画像、学生画像、错题归因分析、补救方案、班级报告。

| Command | Description |
|---------|-------------|
| `analytics class-profile` | Generate class learning profile / 生成班级学情画像 |
| `analytics student-profile` | Generate student profile / 生成学生个体画像 |
| `analytics error-analysis` | Error root-cause analysis / 错题归因分析 |
| `analytics remedial` | Generate remedial teaching plan / 生成补救教学方案 |
| `analytics report` | Generate class Markdown report / 生成班级 Markdown 报告 |
| `load_from_json()` / `load_from_csv()` | Import assessment data / 导入学情数据 |

### 9. Agent Module / 任务编排 (`agent/`) — v0.5

Multi-step task orchestration with scheduling, predefined teaching workflows, and engine registry.
多步骤任务编排，支持调度、预定义教学工作流、引擎注册。

| Command | Description |
|---------|-------------|
| `agent tasks` | List predefined task templates / 列出预定义任务模板 |
| `agent enable/disable <task_name>` | Enable/disable a scheduled task / 启用/禁用任务 |
| `agent run <task_name>` | Execute a task immediately / 立即执行任务 |
| `agent history` | Show task execution history / 查看执行历史 |
| `agent start/stop` | Start/stop scheduler daemon / 启动/停止调度器 |

Predefined task builders / 预定义任务：
- `weekly_prep` — Weekly lesson prep / 每周备课（教案+测验+课件）
- `weekly_summary` — Weekly class summary / 每周学情总结
- `daily_homework_review` — Daily homework review / 每日作业批改
- `monthly_report` — Monthly class report / 月度班级报告
- `batch_differentiated_materials` — Batch differentiated materials / 批量分层材料

### 10. Content Safety / 内容安全 (`safety/`) — v0.6

Multi-layer content filtering: sensitive word detection, age-appropriate check, LLM self-review, output verification.
多层内容过滤：敏感词检测、适龄检查、LLM 自审查、输出校验。

| Command | Description |
|---------|-------------|
| `safety check <text> --grade 3` | Full safety check / 完整安全检查 |
| `safety filter <text>` | Replace sensitive words / 过滤敏感词 |
| `safety wordlist --add/--remove/--list` | Manage sensitive word list / 管理敏感词库 |

### 11. Data Desensitization / 数据脱敏 (`desensitize/`) — v1.0

Student data privacy: name anonymization, field masking, reversible mapping.
学生数据隐私保护：姓名匿名化、字段脱敏、可逆映射。

| Command | Description |
|---------|-------------|
| `desensitize anon <file.json> --mode id` | Anonymize student records / 匿名化学生记录 |
| `desensitize export <file.json> --output out.json` | Export desensitized data / 导出脱敏数据 |
| `DataAnonymizer.anonymize_records()` | Batch name→ID mapping / 批量姓名→ID映射 |
| `DataAnonymizer.deanonymize_record()` | Reverse anonymization / 反向匿名化 |

### 12. HTTP API / HTTP 接口 (`serve.py`)

REST API for programmatic access (default port 11448).
REST API 编程访问（默认端口 11448）。

Full endpoint list: see [README.md](README.md#12-http-api-servepy)

完整端点列表：见 [README.md](README.md#12-http-api-servepy)

---

## 🏗️ Architecture / 架构

```
┌──────────────────────────────────────────────────────────────┐
│              CLI (fusion-k12)  │  HTTP API (serve.py:11448)  │
│  lesson │ assess │ subject │ personalize │ content │ serve   │
│  standards │ lesson plan-diff/quiz-diff │ analytics │ agent  │
│  safety │ desensitize                                        │
├──────────────────────────────────────────────────────────────┤
│                    Engine Layer / 引擎层                       │
│  CurriculumEngine │ AssessmentEngine │ SubjectExpert          │
│  PersonalizationEngine │ ContentGenerator                     │
│  StandardsLoader │ StandardsQuery │ StandardsAligner          │
│  DifferentiationEngine (Three-tier Differentiation / 三层分层) │
│  AnalyticsEngine (Learning Analytics / 学情分析)              │
│  ContentFilter + SensitiveWordList + AgeChecker (Safety / 安全)│
│  DataAnonymizer (Data Desensitization / 数据脱敏)             │
├──────────────────────────────────────────────────────────────┤
│  Agent Layer / 任务编排层                                      │
│  EngineRegistry → execute_step → Engines                      │
│  TaskScheduler (APScheduler + SQLite) │ Predefined Tasks      │
├──────────────────────────────────────────────────────────────┤
│                    AI Backend (fusion-mlx)                     │
│  HTTP → http://localhost:11432/v1/chat/completions            │
│  100% local, zero data upload / 100%本地，零上传               │
└──────────────────────────────────────────────────────────────┘
```

---

## 🧪 Running Tests / 运行测试

```bash
pip install -e ".[test]"
pytest tests/ -v
```

---

## 🔒 Security & Compliance / 安全合规

- **100% Local Offline / 100% 本地离线** — Zero data upload, no privacy leakage / 零数据上传，零隐私泄露
- **No Telemetry / 无遥测** — No analytics, no phoning home / 无埋点、无回传
- **Data Sovereignty / 数据主权** — All processing on local machine / 所有处理在本地完成
- **Compliant with Chinese regulations / 符合国内法规** — No cross-border data transfer / 无跨境数据传输
- **Student Privacy / 学生隐私** — All student data stays on device / 所有学生数据留在设备上
- **Data Desensitization / 数据脱敏** — Automatic name anonymization & field masking / 自动姓名匿名化与字段脱敏

---

## 🐳 Deployment / 部署

See [docs/deploy.md](docs/deploy.md) for full deployment guide.

详见 [docs/deploy.md](docs/deploy.md) 完整部署指南。

| Scenario / 场景 | Method / 方式 |
|-----------------|---------------|
| Individual teacher / 个人教师本地 | `pip install -e .` + CLI/API |
| School intranet / 学校内网 | Docker Compose (`docker-compose up -d`) |
| Commercial institution / 教培机构商用 | K8s + algorithm registration + compliance / K8s + 算法备案 + 合规配置 |

Quick Docker start / Docker 快速启动：
```bash
docker build -t fusion-k12-teacher:latest .
docker-compose up -d
curl http://localhost:11448/api/health
```

---

## 📦 Examples / 示例

| File | Description |
|------|-------------|
| [`examples/batch_lesson_plans.py`](examples/batch_lesson_plans.py) | Batch generate lesson plans / 批量生成教案 |
| [`examples/api_demo.py`](examples/api_demo.py) | HTTP API usage demo / HTTP API 使用示例 |

---

## 📄 License / 开源协议

Apache License 2.0. See [LICENSE](LICENSE) for details.
Apache 2.0 协议，详见 [LICENSE](LICENSE)。

---

<p align="center">
  <strong>Fusion-K12-Teacher — Local AI Education. Zero Upload, Complete Privacy.</strong>
</p>
<p align="center">
  <strong>本地 AI 教育，零上传，完全隐私。</strong>
</p>
<p align="center">
  <sub>Built with ❤️ and fusion-mlx</sub>
</p>
