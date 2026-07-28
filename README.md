<div align="center">
  <h1>🍎 Fusion-K12-Teacher</h1>
  <p><strong>Local AI-powered K-12 education assistant for macOS Apple Silicon</strong></p>
  <p><em>100% offline, zero data upload, powered by fusion-mlx. The domestic alternative to Claude K-12 Teacher.</em></p>
</div>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-blue" alt="Python">
  <img src="https://img.shields.io/badge/macOS-Apple%20Silicon-brightgreen" alt="macOS">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  <img src="https://img.shields.io/badge/AI-MLX%20Native-orange" alt="MLX">
  <img src="https://img.shields.io/badge/Offline-First-important" alt="Offline">
  <img src="https://img.shields.io/badge/tests-272%20passed-brightgreen" alt="Tests">
</p>

---

## 📋 Overview

**Fusion-K12-Teacher** is a local AI-powered K-12 education assistant, designed as a domestic alternative to **Claude K-12 Teacher**. Built on `fusion-mlx`, it provides comprehensive teaching support — lesson planning, assessment, subject expertise, personalized learning, and content generation — all **100% offline** with zero data uploaded.

### Claude K-12 Teacher Comparison

| Capability | Claude K-12 Teacher | Fusion-K12-Teacher |
|------------|---------------------|-------------------|
| **Data residency** | ❌ Cloud-only | ✅ **100% local** |
| **Offline capable** | ❌ Requires internet | ✅ **Fully offline** |
| **China accessible** | ❌ Blocked | ✅ **Fully accessible** |
| **Lesson planning** | ✅ Standards-aligned | ✅ Standards-aligned |
| **Quiz generation** | ✅ Auto-generate | ✅ Auto-generate |
| **Essay grading** | ✅ Rubric-based | ✅ Rubric-based |
| **Subject expertise** | ✅ STEM/Languages/Arts | ✅ STEM/Languages/Arts |
| **Personalized learning** | ✅ Adaptive paths | ✅ Adaptive paths |
| **Content generation** | ✅ Worksheets, slides | ✅ Worksheets, slides, games |
| **Parent communication** | ✅ Templates | ✅ Templates |
| **STEM projects** | ✅ PBL design | ✅ PBL design |
| **Language learning** | ✅ Activities | ✅ Activities |
| **Curriculum standards** | ❌ Not built-in | ✅ **2022 课标知识图谱** |
| **Differentiated teaching** | ❌ Not available | ✅ **Three-tier lessons** |
| **Learning analytics** | ❌ Not available | ✅ **Class/student profiles, error analysis** |
| **Task automation** | ❌ Not available | ✅ **Scheduled multi-step teaching tasks** |
| **Content safety** | ❌ Not available | ✅ **Multi-layer content filtering & age check** |
| **Data desensitization** | ❌ Not available | ✅ **Name anonymization & field masking** |
| **Docker deployment** | ❌ Not available | ✅ **Docker Compose & K8s ready** |
| **License** | Enterprise subscription | **MIT (free)** |

---

## 🚀 Quick Start

```bash
# Clone
git clone https://github.com/dahai80/fusion-k12-teacher.git
cd fusion-k12-teacher

# Install
pip install -e .

# Generate a lesson plan
fusion-k12 lesson plan 数学 3 分数

# Generate a quiz
fusion-k12 lesson quiz 数学 3 分数 --questions 5

# Grade an essay
fusion-k12 assess essay "Today was a great day..."

# Explain a concept
fusion-k12 subject explain 科学 5 光合作用

# Create a learning path
fusion-k12 personalize path 张三 3 数学 掌握分数运算

# Generate a worksheet
fusion-k12 content worksheet 英语 3 动物

# Start HTTP API server
fusion-k12 serve --port 8900
```

---

## 📖 Modules

### 1. Curriculum Engine (`curriculum/`)

Lesson planning, quiz generation, unit planning.

| Command | Description |
|---------|-------------|
| `lesson plan <subject> <grade> <topic>` | Generate standards-aligned lesson plan |
| `lesson quiz <subject> <grade> <topic>` | Generate quiz with multiple question types |
| `generate_unit_plan()` | Design multi-week unit plans |

### 2. Assessment Engine (`assessment/`)

Essay grading, math grading, student reports, rubrics.

| Command | Description |
|---------|-------------|
| `assess essay <text>` | Grade essay with rubric scoring |
| `grade_math()` | Grade math problems with step analysis |
| `generate_report()` | Create semester learning reports |
| `generate_rubric()` | Design scoring rubrics |

### 3. Subject Expert (`subjects/`)

STEM, Language, Arts, and Humanities knowledge base.

| Command | Description |
|---------|-------------|
| `subject explain <subject> <grade> <concept>` | Explain concepts at grade level |
| `generate_exercise()` | Generate subject-specific exercises |
| `stem_project()` | Design STEM project-based learning |
| `language_activity()` | Create language learning activities |

### 4. Personalization Engine (`personalization/`)

Adaptive learning paths, skill diagnosis, resource recommendations.

| Command | Description |
|---------|-------------|
| `personalize path <student> <grade> <subject> <goal>` | Create personalized learning path |
| `diagnose_skills()` | Diagnose student skill levels |
| `recommend_resources()` | Recommend targeted learning resources |

### 5. Content Generator (`content/`)

Worksheets, flashcards, slides, educational games, parent communication.

| Command | Description |
|---------|-------------|
| `content worksheet <subject> <grade> <topic>` | Generate practice worksheets |
| `generate_flashcards()` | Create study flashcards |
| `generate_lesson_slides()` | Design lesson slide outlines |
| `generate_educational_game()` | Design classroom learning games |
| `generate_parent_communication()` | Write parent communication templates |

### 6. Curriculum Standards (`standards/`) — v0.3

Curriculum standards knowledge graph aligned with 《义务教育课程标准（2022年版）》.

| Command | Description |
|---------|-------------|
| `standards list [--subject] [--grade]` | List knowledge points with filters |
| `standards show <point_id>` | Show knowledge point details with prerequisites/progression |
| `StandardsQuery.get_knowledge_points()` | Query by subject & grade |
| `StandardsQuery.find_by_topic()` | Fuzzy search by topic keyword |
| `StandardsAligner.align()` | Generate alignment context for prompts |
| `StandardsAligner.validate_alignment()` | Check coverage of mandatory points |

### 7. Differentiated Teaching (`differentiation/`) — v0.3

Three-tier differentiated content: struggling / standard / advanced.

| Command | Description |
|---------|-------------|
| `lesson plan-diff <subject> <grade> <topic>` | Generate three-tier lesson plan |
| `lesson quiz-diff <subject> <grade> <topic>` | Generate three-tier quiz |
| `DifferentiationEngine.generate_differentiated_lesson()` | Full differentiated lesson |
| `DifferentiationEngine.generate_differentiated_quiz()` | Full differentiated quiz |

### 8. Learning Analytics (`analytics/`) — v0.4

Class profiles, student profiles, error root-cause analysis, remedial plans, class reports.

| Command | Description |
|---------|-------------|
| `analytics class-profile <class_id> <subject> <grade> [-d data.json]` | Generate class learning profile |
| `analytics student-profile <student_id> <subject> <grade> [-d data.json]` | Generate student profile |
| `analytics error-analysis <subject> <grade> [-d data.json]` | Error root-cause analysis |
| `analytics remedial <student_id> <subject> <grade> [-d data.json]` | Generate remedial teaching plan |
| `analytics report <class_id> <subject> <grade> [-d data.json]` | Generate class Markdown report |
| `AnalyticsEngine.build_class_profile()` | Full class profile with statistics |
| `AnalyticsEngine.analyze_errors()` | Error root-cause with LLM |
| `AnalyticsEngine.generate_remedial_plan()` | Standards-aware remedial plan |
| `load_from_json()` / `load_from_csv()` | Import assessment data |

### 9. Agent Module (`agent/`) — v0.5

Multi-step task orchestration with scheduling, predefined teaching workflows, and engine registry.

| Command | Description |
|---------|-------------|
| `agent tasks` | List predefined task templates |
| `agent enable <task_name>` | Enable a scheduled task |
| `agent disable <task_name>` | Disable a scheduled task |
| `agent run <task_name> [options]` | Execute a task immediately |
| `agent history [--limit N]` | Show task execution history |
| `agent start` | Start the task scheduler daemon |
| `agent stop` | Stop the task scheduler daemon |

Predefined task builders:
- `weekly_prep` — Weekly lesson prep (lesson plan + quiz + slides)
- `weekly_summary` — Weekly class summary (analytics + report)
- `daily_homework_review` — Daily homework review (grade + remedial)
- `monthly_report` — Monthly class report (full analytics)
- `batch_differentiated_materials` — Batch differentiated materials for multiple topics

### 10. Content Safety (`safety/`) — v0.6

Multi-layer content filtering: sensitive word detection, age-appropriate check, LLM self-review, output verification.

| Command | Description |
|---------|-------------|
| `safety check <text> --grade 3` | Full input-side safety check (sensitive words + age) |
| `safety filter <text>` | Replace sensitive words with `**` |
| `safety wordlist --add <word>` | Add a sensitive word |
| `safety wordlist --remove <word>` | Remove a sensitive word |
| `safety wordlist --list` | List all sensitive words |

Components:
- `ContentFilter` — Multi-layer filter with configurable `FilterLevel` (sensitive_words / age_check / llm_review / output_check)
- `SensitiveWordList` — Load/save/check word list from text file, case-insensitive
- `AgeChecker` — Grade-tiered content review (1-3: concrete, 4-6: semi-abstract, 7-12: abstract) with restricted topics

### 11. Data Desensitization (`desensitize/`) — v1.0

Student data privacy: name anonymization, field masking, reversible mapping.

| Command | Description |
|---------|-------------|
| `desensitize anon <file.json> --mode id --prefix S --output out.json` | Anonymize student records |
| `desensitize export <file.json> --output out.json` | Export desensitized data + name map |
| `DataAnonymizer.anonymize_records()` | Batch anonymize with name→ID mapping |
| `DataAnonymizer.mask_field()` | Mask phone/email/address fields |
| `DataAnonymizer.export_desensitized()` | Full export with reversible name_map |
| `DataAnonymizer.deanonymize_record()` | Reverse anonymization |

### 12. HTTP API (`serve.py`)

### 11. HTTP API (`serve.py`)

REST API for programmatic access (default port 8900).

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/curriculum/plan` | POST | Generate lesson plan |
| `/api/assessment/grade` | POST | Grade math problem |
| `/api/subject/explain` | POST | Explain concept |
| `/api/personalize/path` | POST | Create learning path |
| `/api/content/generate` | POST | Generate content (worksheet/flashcards/slides/game) |
| `/api/standards/list` | GET | List curriculum knowledge points |
| `/api/standards/query` | POST | Query knowledge points by subject/grade/topic |
| `/api/curriculum/plan-diff` | POST | Generate three-tier differentiated lesson plan |
| `/api/curriculum/quiz-diff` | POST | Generate three-tier differentiated quiz |
| `/api/analytics/class-profile` | POST | Generate class learning profile |
| `/api/analytics/student-profile` | POST | Generate student profile |
| `/api/analytics/error-analysis` | POST | Error root-cause analysis |
| `/api/analytics/remedial` | POST | Generate remedial teaching plan |
| `/api/analytics/class-report` | POST | Generate class Markdown report |
| `/api/agent/tasks` | GET | List predefined task templates |
| `/api/agent/run` | POST | Execute a task immediately |
| `/api/agent/schedule` | POST | Enable/disable scheduled task |
| `/api/agent/history` | GET | Show task execution history |
| `/api/safety/check` | POST | Full content safety check |
| `/api/safety/filter` | POST | Filter sensitive words in text |
| `/api/safety/wordlist` | GET | List sensitive words |
| `/api/safety/wordlist` | POST | Add/remove sensitive words |
| `/api/desensitize/anonymize` | POST | Anonymize student records |
| `/api/desensitize/export` | POST | Export desensitized data |
| `/api/analytics/upload` | POST | Upload assessment data |
| `/api/content/worksheet-diff` | POST | Generate differentiated worksheet |

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────────┐
│              CLI (fusion-k12)  │  HTTP API (serve.py:8900)   │
│  lesson │ assess │ subject │ personalize │ content │ serve   │
│  standards │ lesson plan-diff/quiz-diff │ analytics │ agent  │
│  safety                                                          │
├──────────────────────────────────────────────────────────────┤
│                    Engine Layer                                │
│  CurriculumEngine │ AssessmentEngine │ SubjectExpert          │
│  PersonalizationEngine │ ContentGenerator                     │
│  StandardsLoader │ StandardsQuery │ StandardsAligner          │
│  DifferentiationEngine (三层分层教学)                          │
│  AnalyticsEngine (学情分析/错题归因/补救方案)                   │
│  ContentFilter + SensitiveWordList + AgeChecker (内容安全)      │
│  DataAnonymizer (数据脱敏)                                      │
├──────────────────────────────────────────────────────────────┤
│  Agent Layer (v0.5)                                           │
│  EngineRegistry → execute_step → Engines                      │
│  TaskScheduler (APScheduler + SQLite) │ Predefined Tasks      │
├──────────────────────────────────────────────────────────────┤
│                    AI Backend (fusion-mlx)                     │
│  HTTP → http://localhost:8000/v1/chat/completions             │
│  100% local, zero data upload                                │
└──────────────────────────────────────────────────────────────┘
```

---

## 🧪 Running Tests

```bash
pip install -e ".[test]"
pytest tests/ -v
```

---

## 🔒 Security & Compliance

- **100% Local Offline** — Zero data upload, no privacy leakage
- **No Telemetry** — No analytics, no phoning home
- **Data Sovereignty** — All processing on local machine
- **Compliant with Chinese regulations** — No cross-border data transfer
- **Student Privacy** — All student data stays on device
- **Data Desensitization** — Automatic name anonymization & field masking

---

## 🐳 Deployment

See [docs/deploy.md](docs/deploy.md) for full deployment guide:

- **个人教师本地** — `pip install -e .` + CLI/API
- **学校内网** — Docker Compose (`docker-compose up -d`)
- **教培机构商用** — K8s + 算法备案 + 合规配置

Quick Docker start:
```bash
docker build -t fusion-k12-teacher:latest .
docker-compose up -d
curl http://localhost:8900/api/health
```

---

## 📦 Examples

| File | Description |
|------|-------------|
| [`examples/batch_lesson_plans.py`](examples/batch_lesson_plans.py) | Batch generate lesson plans for multiple subjects |
| [`examples/api_demo.py`](examples/api_demo.py) | HTTP API usage demo (lesson/quiz/safety/desensitize) |

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.

---

<p align="center">
  <strong>Fusion-K12-Teacher — Local AI Education. Zero Upload, Complete Privacy.</strong>
</p>
<p align="center">
  <sub>Built with ❤️ and fusion-mlx</sub>
</p>

---

<br>

<div align="center">
  <h1>🍎 Fusion-K12-Teacher</h1>
  <p><strong>本地 AI K-12 教育助手 — macOS Apple Silicon 原生</strong></p>
  <p><em>100% 本地离线，数据不出境，基于 fusion-mlx。国内 Claude K-12 Teacher 替代方案。</em></p>
</div>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-blue" alt="Python">
  <img src="https://img.shields.io/badge/macOS-Apple%20Silicon-brightgreen" alt="macOS">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="许可证">
  <img src="https://img.shields.io/badge/AI-MLX%20Native-orange" alt="MLX">
  <img src="https://img.shields.io/badge/离线优先-核心特性-important" alt="离线优先">
  <img src="https://img.shields.io/badge/测试-272%20通过-brightgreen" alt="测试">
</p>

---

## 📋 产品简介

**Fusion-K12-Teacher** 是一款本地 AI K-12 教育助手，基于 `fusion-mlx` 构建，**100% 本地离线，数据不出境**，是国内环境下 Claude K-12 Teacher 的合规替代方案。

### 对标 Claude K-12 Teacher

| 能力 | Claude K-12 Teacher | Fusion-K12-Teacher |
|------|---------------------|-------------------|
| 数据本地化 | ❌ 云端处理 | ✅ **100% 本地** |
| 离线运行 | ❌ 需要联网 | ✅ **完全离线** |
| 国内可访问 | ❌ 被屏蔽 | ✅ **完全可用** |
| 教案生成 | ✅ 标准对齐 | ✅ 标准对齐 |
| 测验生成 | ✅ 自动出题 | ✅ 自动出题 |
| 作文批改 | ✅ 评分标准 | ✅ 评分标准 |
| 学科知识 | ✅ STEM/语言/文科 | ✅ STEM/语言/文科 |
| 个性化学习 | ✅ 自适应路径 | ✅ 自适应路径 |
| 内容生成 | ✅ 工作纸/课件 | ✅ 工作纸/课件/游戏 |
| 家校沟通 | ✅ 模板 | ✅ 模板 |
| STEM 项目 | ✅ PBL 设计 | ✅ PBL 设计 |
| 语言学习 | ✅ 活动设计 | ✅ 活动设计 |
| 课标对齐 | ❌ 无内置 | ✅ **2022课标知识图谱** |
| 分层教学 | ❌ 不支持 | ✅ **三层差异化内容** |
| 学情分析 | ❌ 不支持 | ✅ **班级/学生画像、错题归因** |
| 任务自动化 | ❌ 不支持 | ✅ **定时多步骤教学任务** |
| 内容安全 | ❌ 不支持 | ✅ **多层内容过滤与适龄检查** |
| 数据脱敏 | ❌ 不支持 | ✅ **姓名匿名化 & 字段脱敏** |
| Docker 部署 | ❌ 不支持 | ✅ **Docker Compose & K8s 就绪** |
| 开源免费 | ❌ 企业订阅 | ✅ **MIT 协议** |

### 快速开始

```bash
# 安装
git clone https://github.com/dahai80/fusion-k12-teacher.git
cd fusion-k12-teacher
pip install -e .

# 生成教案
fusion-k12 lesson plan 数学 3 分数

# 生成测验
fusion-k12 lesson quiz 数学 3 分数 --questions 5

# 批改作文
fusion-k12 assess essay "今天真是美好的一天..."

# 解释概念
fusion-k12 subject explain 科学 5 光合作用

# 创建学习路径
fusion-k12 personalize path 张三 3 数学 掌握分数运算

# 生成工作纸
fusion-k12 content worksheet 英语 3 动物
```

### 五大模块

| 模块 | 功能 | 命令 |
|------|------|------|
| 📚 **课程规划** | 教案、测验、单元计划 | `lesson plan/quiz` |
| 📊 **评估** | 作文批改、数学批改、报告 | `assess essay` |
| 🔬 **学科知识** | 概念解释、STEM 项目、语言活动 | `subject explain` |
| 🎯 **个性化** | 学习路径、能力诊断、资源推荐 | `personalize path` |
| 📄 **内容生成** | 工作纸、闪卡、课件、游戏 | `content worksheet` |
| 📐 **课标知识图谱** | 2022课标对齐、知识关联 | `standards list/show` |
| 🎚️ **分层教学** | 三层差异化教案/测验 | `lesson plan-diff/quiz-diff` |
| 📊 **学情分析** | 班级画像、错题归因、补救方案 | `analytics class-profile/student-profile/error-analysis/remedial/report` |
| 🤖 **任务自动化** | 多步骤教学任务编排、定时调度 | `agent tasks/enable/disable/run/history/start/stop` |
| 🛡️ **内容安全** | 敏感词过滤、适龄检查、LLM审核 | `safety check/filter/wordlist` |
| 🔐 **数据脱敏** | 姓名匿名化、字段脱敏、可逆映射 | `desensitize anon/export` |

### 安全合规

- **100% 本地离线** — 零数据上传，零隐私泄露
- **无遥测** — 无埋点、无回传
- **数据主权** — 所有处理在本地完成
- **符合国内法规** — 无跨境数据传输
- **学生隐私** — 所有学生数据留在设备上
- **内容安全** — 多层过滤（敏感词+适龄+LLM审核+输出检查）
- **数据脱敏** — 自动姓名匿名化与字段脱敏

### 开源协议

MIT License