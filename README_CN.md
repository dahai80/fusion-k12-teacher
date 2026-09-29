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
  <img src="https://img.shields.io/badge/tests-548%20passed-brightgreen" alt="Tests">
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

Student data privacy: salted-hash name anonymization, fixed-width field masking, reversible mapping (in-memory only, never serialized by default).
学生数据隐私保护：加盐哈希姓名匿名化、定宽字段脱敏、可逆映射（仅存内存，默认不序列化）。

| Command | Description |
|---------|-------------|
| `desensitize anon <file.json> --mode id` | Anonymize student records / 匿名化学生记录 |
| `desensitize export <file.json> --output out.json` | Export desensitized data / 导出脱敏数据 |
| `DataAnonymizer.anonymize_records()` | Batch anonymize, returns stats + records / 批量匿名化，返回统计与脱敏记录 |
| `DataAnonymizer.mask_field()` | Fixed-width mask, no length/domain leak / 定宽脱敏，不泄露长度与域名 |
| `DataAnonymizer.deanonymize_record()` | Reverse anonymization / 反向匿名化 |

### 12. HTTP API / HTTP 接口 (`serve.py`)

REST API for programmatic access (default port 11448).
REST API 编程访问（默认端口 11448）。

Full endpoint list: see [README.md](README.md#12-http-api-servepy)

完整端点列表：见 [README.md](README.md#12-http-api-servepy)

---

### 13. Course Platform / 学科课程平台 (`course/`) — v2.1, 平台-内容解耦

学科无关的课程平台。平台只依赖 `SubjectModule` 协议 — 数学内容在 `course/subjects/math/`, 后续物理/化学/英语/语文接入零平台改动。

- **SymPy 符号引擎**作数值 SSoT, 覆盖 LLM 提取值 (PRD §6 严谨性)
- **networkx DAG** 替代 Neo4j (离线纯 Python, 52 节点, Tarjan SCC 校验)
- **置信度启发式**替代 DKT Transformer (Wilson 下界, N≥5 冷启动)
- **结构化 prompt + Pydantic + SymPy** 替代 GBNF Logits Masker
- **火车过桥 5 题型**: 完全过桥 / 完全在桥上 / 相对运动 / 错车超车 / 回声
- **首发题库**: 9 题 (5 例 + 3 练习), 按「知识点 + 认知层级 + 错因」三元组打标, A/B/C 分层

安装数学扩展: `pip install -e ".[math]"` (增加 `sympy`, `networkx`)

详见 [README.md](README.md#13-course-platform-course-v21-platform-content-decoupled)

---

### 14. Teacher Web GUI / 教师 Web 图形界面 (`web/`) — v1.0

Vue 3 + TypeScript + Vite 单页应用, 由 `serve.py` 通过 FastAPI `StaticFiles` 静态挂载分发 (单进程交付, 生产无 Node 运行时依赖)。

- **技术栈**: Vue 3, Naive UI, Pinia, Vue Router (hash history)
- **10 导航分区**, ~30 用例覆盖完整教学工作流
- **健康轮询** (15s, 顶栏状态徽章), **优雅降级 UX** (骨架屏 + 引擎错误 + 重试), **会话级数据集绑定** (Pinia + localStorage)
- **WebSocket** 流式苏格拉底课稿生成 (5 事件协议)

```bash
cd web && pnpm install && pnpm build      # 产物 web/dist/, serve.py 自动挂载
cd web && pnpm dev                          # 开发服务器 :5174, 代理 API 到 :11448
```

详见 [README.md](README.md#14-teacher-web-gui-web-v10)

### 14a. 教师身份 + 教材目录 + 资源库 / Teacher Identity + Textbook + Resource Library — v2.3

三个耦合特性, 闭合"匿名临时会话"断层 — 教师现拥有持久账号、从真实教材目录选题、每次生成自动存入个人资源库。

- **教师账号** (`auth/`): 注册/登录, PBKDF2-SHA256 密码哈希 (stdlib `hashlib`, 10 万次迭代), HMAC 签名 bearer token (7 天 TTL, `X-Auth-Token` 头)。与现有机器 API key 双重鉴权 — `require_api_key` 守门, `get_optional_teacher`/`require_teacher` 承载用户身份。路由: `POST /api/auth/{register,login,logout}`, `GET /api/auth/me`。
- **教材目录** (`textbook/`): 自建人教版小学数学 1-6 年级目录 (`data/renjiao-math-g1-6.json`, 确定性公开课标数据 — 非 LLM 生成)。`TextbookLoader` 仿 `StandardsLoader` (线程锁懒加载, `(edition, subject, grade)` 索引)。复合 lesson_id `{unit}-{lesson}` (课号跨单元重复)。三年级完整映射 `standards/data/math_g1-6.json` 知识点 ID。路由: `GET /api/textbook/editions`, `…/grades`, `…/units`, `…/lesson/{lesson_id}`。
- **资源库** (`repository/`): 现有 WAL+线程锁仓库上新增 3 表 (`teachers`/`sessions`/`materials`)。**自动保存中间件** 消费响应 `body_iterator`, 校验教师 token, 将 28 个生成端点结果全部落盘 — 标注 edition/subject/grade/lesson_id/unit_title/lesson_title, 按教材位置找回资源。路由: `GET /api/materials` (按 type/subject/grade 筛选), `GET /api/materials/{id}`, `DELETE /api/materials/{id}`。
- **前端** (`web/`): `TextbookSelect.vue` 级联选择器 (版本→年级→单元→课, 自动带出课题) 接入全部 28 个生成页; `Login.vue` (注册/登录 tab); `MyMaterials.vue` (卡片网格 + 详情弹窗用 `ResultViewer` 渲染); Pinia auth store + `X-Auth-Token` 头注入; 路由守卫拦截未登录跳 `/login`。生成成功 toast 确认已保存。

环境变量: `FUSION_K12_AUTH_SECRET` (可选, HMAC token 签名密钥; 默认从 API key 派生)。数据库: `~/.fusion-k12/k12.db`。

### 15. Classroom Module / 课堂模块 (`classroom/`) — v2.1, K1 文字版

文字版课堂交付 (LiveKit/数字人/TTS 上游 deferred)。落地课堂 PRD E1-E6, 平台-内容解耦 — 判分委托 `AssessmentEngine`/课程 verifier, 不耦合学科。

```
classroom/
├── models.py      # ScriptPage/LessonScript/CoursePackage/ClassSession/AnswerRecord/ClassReport
├── store.py       # ClassroomStore: SQLite (课程包 + 会话, 线程安全)
├── scripter.py    # LessonScripter: LLM → JSON 分页 (旁白/提问/情绪标签), 降级回退
├── packager.py    # Packager: 6 位课堂码, 唯一码重试, 课程包 CRUD
└── session.py     # SessionManager: 创建/作答/翻页/结束 + 报告 (放弃=不写快照)
```

**E1-E6 端点** (`/api/classroom/*`): `POST /script` (E1 生成讲稿), `POST /pack` (E2 打包→6位码), `GET /pack/{code}` (E3 学生取包), `POST /answer` (E4 判分: 选择/数值本地, 表达/开放委托 AssessmentEngine), `POST /session` + `PATCH /session/{id}/finish` (E5 创建/结束, abandoned 跳过快照), `GET /report/{sid}` (E6 出勤/浏览/测验统计/薄弱点)。

**Web GUI 页面**: 教师备课 (讲稿+打包+列表), 学生入口 (6位码), 播放器 (逐页讲课+答题卡+结束), 报告 (E6 统计)。见 `🏫 课堂` 菜单。

### 16. Digital-Human Platform Layer / 数字人平台层 (`digital_human/`) — v2.2, K2/K3

学科无关数字人老师平台 (PRD K2 实时语音 + K3 数字人)。自主实现 TLive-Omni 六大核心设计, 不引入第三方仓库。内容经 `SubjectModule` (课程路) 或 `LessonScripter` (课堂路) 注入, 零学科硬编码。

**6 大核心 (自主实现):**
1. **五态 FSM** (`fsm.py`): IDLE/USER_SPEAKING/AI_THINKING/AI_SPEAKING/ERROR + 统一钩子; ERROR 自动经 BargeInBus 取消所有插件任务
2. **Barge-in 事件总线** (`barge_in.py`): 单次 `fire()` 广播 cancel+clear 至所有注册插件 + 追踪任务, 不散落中断代码
3. **四层插件抽象** (`plugins/base.py`): ASRPlugin/LLMPlugin/TTSPlugin/AvatarPlugin ABC 解耦调度与推理
4. **emotion_tag 模块** (`emotion.py`): 正则剥离 `[tag]` → TTS 语速 + Avatar 表情; 日志过滤器剥离 tag
5. **滚动窗口记忆** (`memory.py`): MAX_TOKENS 预算, 自动截断最旧非 system 消息, 分层 system prompt 拼接
6. **会话生命周期** (`session.py`): 空闲超时自动释放 MLX (`mx.clear_cache()`), `finish()` 排空任务 + 落库

**插件 (可插拔, 优雅降级):**
- `KokoroTTS` — fusion-mlx `/v1/audio/speech` (Kokoro-82M), emotion→语速映射
- `MlxLLM` — fusion-mlx `/v1/chat/completions` stream (SSE token 流)
- `MlxWhisperASR` — fusion-mlx `/v1/audio/transcriptions` (word_timestamps=False)
- `MuseTalkAvatar` — `fusion_mlx.video.musetalk_mlx` 进程内库 (从 mel 推口型, 无需 word timestamps); ImportError → `StaticAvatar` 兜底 (仅 idle 帧, 始终可用)

**传输**: LiveKit SFU 适配层 (`livekit_adapter.py`) — token 签名 (timedelta TTL)/room 连接/音视频轨道发布/DataChannel 状态。livekit 包缺失或 key 未配 → WS 降级 (TTS 音频二进制帧 + 状态走 WS, 静态头像)。`FUSION_K12_LIVEKIT_*` 环境变量未设时自动回退 linguakids-mvp `configs/.env` 的 LiveKit key。MuseTalk 源码路径自动从 `FUSION_MLX_SOURCE` 环境变量或 `~/fusion/fusion-mlx` / `~/claude-home/fusion-mlx` 解析。

**音视频管线 (全接线):**
- TTS 音频 (Kokoro WAV) 在每个 `narrate_done`/`qa_done` 事件后以 WS 二进制帧流式推送; 浏览器 `AudioContext.decodeAudioData` 同步播放。
- 按住说话: 浏览器 `MediaRecorder` 采集麦克风 → WS 二进制 → `session.on_student_speech(pcm)` → Whisper ASR → barge-in 中断讲解 → LLM 答疑 → TTS 回答。
- LiveKit 视频轨: `livekit-client` `Room.connect(token)` 订阅 `RemoteVideoTrack` → 挂载到 `<video>`; `RemoteAudioTrack` 自动播放。LiveKit SFU 不可用时降级 WS-only (emoji 头像 + TTS 音频)。
- 检查点/随堂提问卡片逐页渲染 (success/warning 提示)。
- 会话落库: 课堂路会话 (有课堂码) 写 `ClassroomStore` 记录 — 翻页/提问/结束快照, 供学情分析延续。自主学习会话为临时 (不落库)。

**端点** (`/api/digital-human/*`): `POST /session` (创建+加载讲稿), `POST /token` (LiveKit token+room), `POST /narrate` (逐页 TTS+头像, 仅元数据 — 音频走 WS), `POST /raise-hand` (LLM 答疑), `POST /finish` (释放+落库)。`WS /ws/digital-human/{session_id}` 推状态事件 + TTS 音频二进制; 学生发 JSON `{action: "narrate_page"|"raise_hand"|"finish"}` 或二进制麦克风 PCM。

**Web GUI**: 自主学习入口 (UC-C7 — 选学科/年级/主题, 即时会话, 无需课堂码) → 数字人播放器 (LiveKit `<video>` 头像 + 讲稿字幕 + 步骤导航 + 检查点/提问卡片 + 举手抽屉 + 按住说话麦克风)。课堂播放器有 `🤖 数字人模式` 启动按钮。见 `🤖 数字人老师` 菜单。

```bash
# 可选环境变量 (见 .env.example):
export FUSION_K12_LIVEKIT_URL=ws://127.0.0.1:7880
export FUSION_K12_LIVEKIT_API_KEY=...
export FUSION_K12_LIVEKIT_API_SECRET=...
export FUSION_MLX_SOURCE=/Users/dahai/fusion/fusion-mlx   # MuseTalk 进程内导入
pip install -e ".[digital-human]"                         # mlx + livekit + opencv + librosa
```

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
- **Data Desensitization / 数据脱敏** — Salted-hash name→ID (non-deterministic, non-reversible), fixed-width field masking (no length/domain leakage, GB/T 35273 aligned); name_map never serialized by default / 加盐哈希姓名→ID（非确定性、不可逆）、定宽字段脱敏（不泄露长度与域名，对齐 GB/T 35273）；name_map 默认不序列化
- **Input Sanitization / 输入消毒** — `sanitize_input()` truncates length, strips control chars, isolates prompt-injection attempts before every engine call / 各引擎调用前统一截断长度、剥离控制字符、隔离提示注入企图
- **Output Filtering / 输出过滤** — Generated content (worksheets, parent letters) passes `ContentFilter.check_output()` (sensitive words + age-appropriate) before reaching students/parents / 生成内容（工作纸、家长信）送达前过敏感词+适龄检查
- **API Hardening / API 加固** — Optional `X-API-Key` auth, per-IP sliding-window rate limit, allowed-directory path validation (`is_relative_to`), async file I/O off the event loop / 可选 X-API-Key 鉴权、按 IP 滑窗限流、允许目录路径精确校验、文件 I/O 移出事件循环
- **Graceful-but-Visible Failure / 失败可见** — Engine failures set an `error` flag instead of raising; parent-communication failure returns empty (never leaks internal error strings) / 引擎失败置 error 标志而非抛异常；家长信失败返回空（不外泄内部错误串）

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
