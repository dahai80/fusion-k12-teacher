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
  <img src="https://img.shields.io/badge/tests-106%20passed-brightgreen" alt="Tests">
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

### 6. HTTP API (`serve.py`)

REST API for programmatic access (default port 8900).

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/curriculum/plan` | POST | Generate lesson plan |
| `/api/assessment/grade` | POST | Grade math problem |
| `/api/subject/explain` | POST | Explain concept |
| `/api/personalize/path` | POST | Create learning path |
| `/api/content/generate` | POST | Generate content (worksheet/flashcards/slides/game) |

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────────┐
│              CLI (fusion-k12)  │  HTTP API (serve.py:8900)   │
│  lesson │ assess │ subject │ personalize │ content │ serve   │
├──────────────────────────────────────────────────────────────┤
│                    Engine Layer                                │
│  CurriculumEngine │ AssessmentEngine │ SubjectExpert          │
│  PersonalizationEngine │ ContentGenerator                     │
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
  <img src="https://img.shields.io/badge/测试-32%20通过-brightgreen" alt="测试">
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

### 安全合规

- **100% 本地离线** — 零数据上传，零隐私泄露
- **无遥测** — 无埋点、无回传
- **数据主权** — 所有处理在本地完成
- **符合国内法规** — 无跨境数据传输
- **学生隐私** — 所有学生数据留在设备上

### 开源协议

MIT License