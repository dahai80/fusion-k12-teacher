---
doc_id: fusion-k12-teacher/product-page
product: fusion-k12-teacher
class: app
entry: guided-ui
doc_type: product-page
title: { zh: "Fusion-K12-Teacher 产品页", en: "Fusion-K12-Teacher product page" }
audience: engineer
status: draft
version: 2.2.6
updated: 2026-11-07
owner: "@dahai"
source_of_truth:
  - README.md
  - fusion_k12_teacher/serve.py
  - web/
  - pyproject.toml
---

# Fusion-K12-Teacher 产品页 / Product Page

本地 AI K-12 教学助手。macOS Apple Silicon 原生（本地形态），也可部署到 Linux（云形态）。基于 fusion-mlx 推理，默认 100% 本地离线，数据不出设备。

Local AI-powered K-12 teaching assistant. macOS Apple Silicon native (local form), deployable to Linux (cloud form). Inference via fusion-mlx; fully offline by default, data stays on the machine.

## 网格定位 / Grid position

- 产品类别 class: `app`
- 入口形态 entry: `guided-ui` — 教师通过 Web GUI 驱动产品。`fusion-k12 serve` 在同一进程内同时提供 HTTP API（`/api/*`）与教师 Web GUI（`web/dist/` 由 FastAPI `StaticFiles` 挂载在 `/`，见 `fusion_k12_teacher/serve.py:3113`）。见 `fusion_k12_teacher/serve.py:3113`。GUI 为 Vue 3 + TypeScript + Naive UI SPA，含 10 个导航分区约 30 个用例。见 `fusion_k12_teacher/serve.py` 与 `web/`。

## 核心能力 / Capabilities

### 1. 备课与出题 / Lesson planning and quiz generation

教师输入学科、年级、课题，生成教案与测验。分层模式一次产出基础/标准/提高三层内容。

- 用户不再需要 / Users no longer need to: 手工对照课标写教案框架、为不同水平学生分别准备三套材料。
- 约束 / Constraints: 内容质量取决于本地模型（fusion-mlx 网关默认模型）；生成前需完成安装与 `.env` 配置（见 get-started）。

### 2. 学情分析 / Learning analytics

导入成绩数据（JSON/CSV）后生成班级画像、学生画像、错因分析、补救教学方案与班级报告。

- 用户不再需要 / Users no longer need to: 用表格工具手工统计错题分布、逐份撰写学情总结。
- 约束 / Constraints: 分析质量依赖上传数据的完整度；数据集经 Pinia + localStorage 在会话间保留（见 `web/`）。

### 3. 课程平台（数学） / Course platform (math)

平台与内容解耦：平台只依赖 `SubjectModule` 协议，首个学科为北师大版小学数学（12 学期、156 节点知识图谱、SymPy 数值权威覆写、苏格拉底 5E 教学脚本 DSL v3.0）。

- 用户不再需要 / Users no longer need to: 自行搭建知识图谱或手写判定逻辑——判分由 SymPy 本地引擎完成，不走模型。
- 约束 / Constraints: 目前仅数学学科有内容（`course/subjects/math/`）；其他学科需按协议自行接入。需安装 `.[math]` extras（sympy + networkx）。

### 4. 教师身份与资源库 / Teacher identity and resource library

教师可注册/登录（PBKDF2-SHA256 + HMAC token），从人教版小学数学教材目录选课，所有生成结果自动按"教材-单元-课时"归档到个人资源库。

- 用户不再需要 / Users no longer need to: 每次匿名开会话、手动保存生成结果。
- 约束 / Constraints: 账户与资源存储在本地 SQLite（`~/.fusion-k12/k12.db`）；`FUSION_K12_AUTH_SECRET` 未设置时 token 密钥由 API key 派生。

### 5. 课堂模块 / Classroom module

教师备课脚本 → 打包为 6 位课堂码 → 学生凭码取包答题 → 生成课堂报告（到课、答题统计、薄弱点）。

- 用户不再需要 / Users no longer need to: 自建答题收集工具。
- 约束 / Constraints: 当前为文本版（K1）；LiveKit/数字人/TTS 集成为后续演进项。

### 6. 数字人老师 / Digital-human teacher

自实现 6 项 TLive-Omni 设计模式（5 态 FSM、打断事件总线、4 层插件抽象、emotion_tag、滚动窗口记忆、会话生命周期）。Kokoro TTS / Whisper ASR / MuseTalk 唇形同步均走 fusion-mlx。

- 用户不再需要 / Users no longer need to: 部署第三方数字人栈。
- 约束 / Constraints: MuseTalk 唇形同步仅限 Apple Silicon；LiveKit 未配置或包缺失时自动降级为 WS-only（TTS 音频 + 静态头像）。数字人模块需 `.[digital-human]` extras。

### 7. 内容安全与脱敏 / Content safety and desensitization

多层内容过滤（敏感词、适龄检查、LLM 自审、输出校验）+ 学生数据脱敏（加盐哈希匿名化、定宽字段掩码、可逆映射默认不落盘）。

- 用户不再需要 / Users no longer need to: 自行编写合规过滤或脱敏脚本。
- 约束 / Constraints: 敏感词表需按校情维护（`safety wordlist` 命令）；改盐后历史 name_map 不可逆查。

### 8. 定时任务自动化 / Scheduled task automation

预置 5 类教学任务模板（周备课、周总结、每日作业复盘、月报、批量分层材料），APScheduler + SQLite 持久化调度。

- 用户不再需要 / Users no longer need to: 手动周期性重复同一组生成操作。
- 约束 / Constraints: standalone 模式单实例（fcntl 锁）；cluster 模式经 DB 任务锁跨实例去重，需 Postgres + Redis。

## 部署形态 / Deployment forms

| 形态 | 启动器 | 平台 | 推理后端 |
|------|--------|------|----------|
| 本地 Local | `./startLocal.sh` | macOS Apple Silicon | fusion-mlx + fusion-gateway |
| 云端 Cloud | `./startCloud.sh` | Linux | 任意 OpenAI 兼容 API |
| 单机 standalone | `./start.sh` / `fusion-k12 serve` | 均可 | 默认，SQLite |
| 集群 cluster | Docker Compose / K8s（`deploy/`） | 均可 | Postgres + AES-256-GCM + Redis |

## 相关文档 / Related docs

- 快速上手 / Get started: [get-started.md](get-started.md)
- 故障排查 / Troubleshooting: [troubleshooting.md](troubleshooting.md)
- HTTP API: [api.md](api.md)
- 部署 / Deploy: [deploy.md](deploy.md)
