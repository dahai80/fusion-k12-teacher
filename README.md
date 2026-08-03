<div align="center">
  <h1>🍎 Fusion-K12-Teacher</h1>
  <p><strong>Local AI-powered K-12 education assistant for macOS Apple Silicon</strong></p>
  <p><em>100% offline, zero data upload, powered by fusion-mlx. The domestic alternative to Claude K-12 Teacher.</em></p>
  <p>
    <a href="README_CN.md">中文文档</a>
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
| **Curriculum standards** | ❌ Not built-in | ✅ **2022 Curriculum Knowledge Graph** |
| **Differentiated teaching** | ❌ Not available | ✅ **Three-tier lessons** |
| **Learning analytics** | ❌ Not available | ✅ **Class/student profiles, error analysis** |
| **Task automation** | ❌ Not available | ✅ **Scheduled multi-step teaching tasks** |
| **Content safety** | ❌ Not available | ✅ **Multi-layer content filtering & age check** |
| **Data desensitization** | ❌ Not available | ✅ **Name anonymization & field masking** |
| **Docker deployment** | ❌ Not available | ✅ **Docker Compose & K8s ready** |
| **License** | Enterprise subscription | **Apache 2.0 (free)** |

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
fusion-k12 serve --port 11448
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

Curriculum standards knowledge graph aligned with 2022 national curriculum standards.

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

REST API for programmatic access (default port 11448).

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
| `/api/analytics/upload` | POST | Upload assessment data |
| `/api/content/worksheet-diff` | POST | Generate differentiated worksheet |
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

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────────┐
│              CLI (fusion-k12)  │  HTTP API (serve.py:11448)  │
│  lesson │ assess │ subject │ personalize │ content │ serve   │
│  standards │ lesson plan-diff/quiz-diff │ analytics │ agent  │
│  safety │ desensitize                                        │
├──────────────────────────────────────────────────────────────┤
│                    Engine Layer                                │
│  CurriculumEngine │ AssessmentEngine │ SubjectExpert          │
│  PersonalizationEngine │ ContentGenerator                     │
│  StandardsLoader │ StandardsQuery │ StandardsAligner          │
│  DifferentiationEngine (Three-tier Differentiation)           │
│  AnalyticsEngine (Learning Analytics / Error Analysis)        │
│  ContentFilter + SensitiveWordList + AgeChecker (Safety)     │
│  DataAnonymizer (Data Desensitization)                        │
├──────────────────────────────────────────────────────────────┤
│  Agent Layer (v0.5)                                           │
│  EngineRegistry → execute_step → Engines                      │
│  TaskScheduler (APScheduler + SQLite) │ Predefined Tasks      │
├──────────────────────────────────────────────────────────────┤
│                    AI Backend (fusion-mlx)                     │
│  HTTP → http://localhost:11434/v1/chat/completions            │
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

- **Individual teacher** — `pip install -e .` + CLI/API
- **School intranet** — Docker Compose (`docker-compose up -d`)
- **Commercial institution** — K8s + algorithm registration + compliance config

Quick Docker start:
```bash
docker build -t fusion-k12-teacher:latest .
docker-compose up -d
curl http://localhost:11448/api/health
```

---

## 📦 Examples

| File | Description |
|------|-------------|
| [`examples/batch_lesson_plans.py`](examples/batch_lesson_plans.py) | Batch generate lesson plans for multiple subjects |
| [`examples/api_demo.py`](examples/api_demo.py) | HTTP API usage demo (lesson/quiz/safety/desensitize) |

---

## 📄 License

Apache License 2.0. See [LICENSE](LICENSE) for details.

---

<p align="center">
  <strong>Fusion-K12-Teacher — Local AI Education. Zero Upload, Complete Privacy.</strong>
</p>
<p align="center">
  <sub>Built with ❤️ and fusion-mlx</sub>
</p>
