# Fusion-K12-Teacher API Reference

## MLXClient

```python
from fusion_k12_teacher import MLXClient

client = MLXClient(model="qwen3.5-9b")
response = await client.chat([
    {"role": "system", "content": "You are a teacher."},
    {"role": "user", "content": "Explain fractions."},
], temperature=0.3, max_tokens=4096)
```

## Curriculum Engine

### `LessonPlan`

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Unique identifier |
| `title` | `str` | Lesson title |
| `subject` | `str` | Subject name |
| `grade` | `str` | Grade level (K-12) |
| `duration_minutes` | `int` | Class duration |
| `objectives` | `List[str]` | Learning objectives |
| `materials` | `List[str]` | Required materials |
| `procedures` | `List[Dict]` | Step-by-step procedures |
| `assessment` | `str` | Assessment method |
| `homework` | `str` | Homework assignment |
| `differentiation` | `Dict` | Differentiation strategies |

### `Quiz`

| Field | Type | Description |
|-------|------|-------------|
| `title` | `str` | Quiz title |
| `subject` | `str` | Subject name |
| `grade` | `str` | Grade level |
| `questions` | `List[Dict]` | Question array |
| `total_points` | `int` | Total score |
| `time_limit_minutes` | `int` | Time limit |

### `CurriculumEngine`

```python
from fusion_k12_teacher.curriculum import CurriculumEngine

engine = CurriculumEngine()

# Generate lesson plan
plan = await engine.generate_lesson_plan(
    subject="数学", grade="3", topic="分数",
    duration=45, standards=["Common Core"]
)

# Generate quiz
quiz = await engine.generate_quiz(
    subject="数学", grade="3", topic="分数",
    num_questions=10, question_types=["multiple_choice", "short_answer"]
)

# Generate unit plan
unit = await engine.generate_unit_plan(
    subject="数学", grade="3", unit_title="分数运算", weeks=4
)
```

## Assessment Engine

### `GradingResult`

| Field | Type | Description |
|-------|------|-------------|
| `score` | `float` | Score achieved |
| `total` | `float` | Maximum score |
| `percentage` | `float` | Percentage |
| `feedback` | `str` | Detailed feedback |
| `strengths` | `List[str]` | Strengths identified |
| `improvements` | `List[str]` | Areas for improvement |
| `rubric_scores` | `Dict[str, float]` | Per-criterion scores |

### `StudentReport`

| Field | Type | Description |
|-------|------|-------------|
| `student_name` | `str` | Student name |
| `subject` | `str` | Subject |
| `grade` | `str` | Grade level |
| `overall_score` | `float` | Overall score |
| `skills` | `Dict[str, float]` | Skill mastery levels |
| `strengths` | `List[str]` | Strengths |
| `areas_to_improve` | `List[str]` | Improvement areas |
| `teacher_notes` | `str` | Teacher comments |

### `AssessmentEngine`

```python
from fusion_k12_teacher.assessment import AssessmentEngine

engine = AssessmentEngine()

# Grade essay
result = await engine.grade_essay(
    essay="Student essay text...",
    rubric={"内容": 40, "结构": 20, "语言": 20, "创意": 20}
)

# Grade math
result = await engine.grade_math(
    problem="2x + 3 = 7", answer="x = 2", solution="2x = 4, x = 2"
)

# Generate report
report = await engine.generate_report(
    student="张三", subject="数学", grade="3",
    history=[{"score": 85, "date": "2026-01-01"}]
)

# Generate rubric
rubric = await engine.generate_rubric(
    assignment_type="作文", grade="5",
    criteria=["内容", "结构", "语言", "创意"]
)
```

## Subject Expert

### `SubjectExercise`

| Field | Type | Description |
|-------|------|-------------|
| `question` | `str` | Exercise question |
| `difficulty` | `str` | easy/medium/hard |
| `subject` | `str` | Subject |
| `grade` | `str` | Grade level |
| `hints` | `List[str]` | Hints for solving |
| `answer` | `str` | Correct answer |
| `explanation` | `str` | Step-by-step explanation |
| `skills` | `List[str]` | Skills tested |

### `SubjectExpert`

```python
from fusion_k12_teacher.subjects import SubjectExpert

expert = SubjectExpert()

# Explain concept
result = await expert.explain_concept(
    subject="科学", grade="5", concept="光合作用"
)

# Generate exercise
exercise = await expert.generate_exercise(
    subject="数学", grade="3", topic="加法", difficulty="medium"
)

# Design STEM project
project = await expert.stem_project(
    grade="5", topic="水循环", duration="2课时"
)

# Create language activity
activity = await expert.language_activity(
    grade="3", language="英语", skill="口语", theme="自我介绍"
)
```

## Personalization Engine

### `LearningPath`

| Field | Type | Description |
|-------|------|-------------|
| `student_id` | `str` | Student identifier |
| `grade` | `str` | Grade level |
| `subject` | `str` | Subject |
| `units` | `List[Dict]` | Learning units |
| `estimated_duration` | `str` | Estimated time |
| `prerequisites` | `List[str]` | Prerequisites |
| `goals` | `List[str]` | Learning goals |

### `PersonalizationEngine`

```python
from fusion_k12_teacher.personalization import PersonalizationEngine

engine = PersonalizationEngine()

# Create learning path
path = await engine.create_learning_path(
    student="张三", grade="3", subject="数学",
    goal="掌握分数运算"
)

# Diagnose skills
diagnosis = await engine.diagnose_skills(
    subject="数学", grade="3",
    responses=[{"question": "2+2=?", "answer": "4", "correct": True}]
)

# Recommend resources
resources = await engine.recommend_resources(
    student="张三", grade="3", subject="数学", weakness="分数"
)
```

## Content Generator

### `Worksheet`

| Field | Type | Description |
|-------|------|-------------|
| `title` | `str` | Worksheet title |
| `subject` | `str` | Subject |
| `grade` | `str` | Grade level |
| `sections` | `List[Dict]` | Worksheet sections |
| `answer_key` | `str` | Answer key |
| `instructions` | `str` | Instructions |

### `ContentGenerator`

```python
from fusion_k12_teacher.content import ContentGenerator

gen = ContentGenerator()

# Generate worksheet
ws = await gen.generate_worksheet(
    subject="数学", grade="3", topic="分数", num_questions=10
)

# Generate flashcards
cards = await gen.generate_flashcards(
    subject="数学", grade="3", topic="分数", count=10
)

# Generate lesson slides
slides = await gen.generate_lesson_slides(
    subject="数学", grade="3", topic="分数", num_slides=8
)

# Design educational game
game = await gen.generate_educational_game(
    subject="数学", grade="3", topic="分数", game_type="quiz"
)

# Generate parent communication
letter = await gen.generate_parent_communication(
    student="张三", grade="3", subject="数学", topic="分数"
)
```

## CLI Reference

```bash
fusion-k12 [OPTIONS] COMMAND [ARGS]
```

### Global Options

| Option | Description |
|--------|-------------|
| `--verbose`, `-v` | Verbose output |
| `--model`, `-m` | fusion-mlx model name |
| `--version` | Show version |

### Commands

#### `lesson plan`

```bash
fusion-k12 lesson plan <subject> <grade> <topic> [--duration 45]
```

#### `lesson quiz`

```bash
fusion-k12 lesson quiz <subject> <grade> <topic> [--questions 5]
```

#### `assess essay`

```bash
fusion-k12 assess essay <essay_text>
```

#### `subject explain`

```bash
fusion-k12 subject explain <subject> <grade> <concept>
```

#### `personalize path`

```bash
fusion-k12 personalize path <student> <grade> <subject> <goal>
```

#### `content worksheet`

```bash
fusion-k12 content worksheet <subject> <grade> <topic>
```

#### `serve`

```bash
fusion-k12 serve [--host 127.0.0.1] [--port 11448]
```

## HTTP API Reference

Base URL: `http://localhost:11448`

### Health Check

```
GET /api/health
```

Response: `{"status": "ok", "version": "1.0.0"}`

### Curriculum Plan

```
POST /api/curriculum/plan
```

Request body:
```json
{"grade": "3", "subject": "数学", "topic": "分数"}
```

### Assessment Grade

```
POST /api/assessment/grade
```

Request body:
```json
{"question": "2+2=?", "answer": "4", "standard": "4"}
```

### Subject Explain

```
POST /api/subject/explain
```

Request body:
```json
{"question": "分数", "grade": "3"}
```

### Personalize Path

```
POST /api/personalize/path
```

Request body:
```json
{"student_id": "张三", "progress": {"grade": "3", "subject": "数学", "goal": "掌握分数"}}
```

### Content Generate

```
POST /api/content/generate
```

Request body:
```json
{"topic": "分数", "grade": "3", "style": "interactive"}
```

`style` values: `interactive` (worksheet), `flashcards`, `slides`, `game`

## Curriculum Standards (v0.3)

### `KnowledgePoint`

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Knowledge point ID (e.g. "math-g3-na-05") |
| `subject` | `str` | Subject name |
| `grade` | `str` | Grade level |
| `strand` | `str` | Curriculum strand (e.g. "数与代数") |
| `topic` | `str` | Knowledge point topic |
| `description` | `str` | Detailed description |
| `prerequisites` | `List[str]` | Prerequisite point IDs |
| `progression_next` | `List[str]` | Next-level point IDs |
| `difficulty_level` | `str` | basic/standard/advanced |
| `curriculum_code` | `str` | Official curriculum code |

### `StandardsLoader`

```python
from fusion_k12_teacher.standards import StandardsLoader

loader = StandardsLoader()
loader.load_all()

subjects = loader.list_subjects()
grades = loader.list_grades("数学")
kp = loader.get_point("math-g3-na-05")
```

### `StandardsQuery`

```python
from fusion_k12_teacher.standards import StandardsQuery

query = StandardsQuery(loader)
points = query.get_knowledge_points("数学", "3")
points = query.find_by_topic("数学", "3", "分数")
prereqs = query.get_prerequisites("math-g3-na-05")
report = query.validate_coverage("数学", "3", ["分数的初步认识"])
```

### `StandardsAligner`

```python
from fusion_k12_teacher.standards import StandardsAligner

aligner = StandardsAligner(query)
ctx = aligner.align("数学", "3", "分数")
prompt_text = aligner.build_prompt_context(ctx)
result = aligner.validate_alignment("数学", "3", ["分数的初步认识"])
```

## Differentiated Teaching (v0.3)

### `DifferentiatedContent`

| Field | Type | Description |
|-------|------|-------------|
| `topic` | `str` | Topic name |
| `grade` | `str` | Grade level |
| `subject` | `str` | Subject |
| `struggling` | `LayerContent` | Content for struggling students |
| `standard` | `LayerContent` | Content for standard students |
| `advanced` | `LayerContent` | Content for advanced students |
| `group_tasks` | `List[GroupTask]` | Collaborative group tasks |
| `standards_aligned` | `bool` | Whether standards alignment was applied |

### `DifferentiationEngine`

```python
from fusion_k12_teacher.differentiation import DifferentiationEngine

engine = DifferentiationEngine(mlx=client, standards_query=query)
result = await engine.generate_differentiated_lesson("数学", "3", "分数", duration=45)
result = await engine.generate_differentiated_quiz("数学", "3", "分数", num_questions=5)
```

### Level Configuration

| Level | Label | Exercises | Scaffold | Extension |
|-------|-------|-----------|----------|-----------|
| `struggling` | 学困生 | 8 | ✅ | ❌ |
| `standard` | 中等生 | 5 | ❌ | ❌ |
| `advanced` | 优等生 | 3 | ❌ | ✅ |

## CLI Reference (v0.3 additions)

```bash
fusion-k12 standards list [--subject 数学] [--grade 3]
fusion-k12 standards show <point_id>
fusion-k12 lesson plan-diff <subject> <grade> <topic> [--duration 45]
fusion-k12 lesson quiz-diff <subject> <grade> <topic> [--questions 5]
```

## HTTP API Reference (v0.3 additions)

### Standards List

```
GET /api/standards/list?subject=数学&grade=3
```

### Standards Query

```
POST /api/standards/query
{"subject": "数学", "grade": "3", "topic": "分数"}
```

### Differentiated Lesson Plan

```
POST /api/curriculum/plan-diff
{"subject": "数学", "grade": "3", "topic": "分数", "duration": 45}
```

### Differentiated Quiz

```
POST /api/curriculum/quiz-diff
{"subject": "数学", "grade": "3", "topic": "分数", "num_questions": 5}
```

## Learning Analytics (v0.4)

### `StudentAssessment`

| Field | Type | Description |
|-------|------|-------------|
| `student_id` | `str` | Student identifier |
| `student_name` | `str` | Student name |
| `assessment_id` | `str` | Assessment identifier |
| `subject` | `str` | Subject |
| `grade` | `str` | Grade level |
| `date` | `str` | Assessment date |
| `total_score` | `float` | Total score achieved |
| `max_score` | `float` | Maximum possible score |
| `scores` | `Dict[str, float]` | Per-topic scores |
| `responses` | `List[Dict]` | Individual question responses |

### `WeakPoint`

| Field | Type | Description |
|-------|------|-------------|
| `knowledge_point_id` | `str` | Knowledge point ID |
| `knowledge_point_name` | `str` | Knowledge point name |
| `error_rate` | `float` | Error rate (0.0–1.0) |
| `affected_students` | `List[str]` | Student IDs with errors |
| `common_mistakes` | `List[str]` | Common wrong answers |
| `suggested_remedial` | `str` | Suggested remediation |

### `ClassProfile`

| Field | Type | Description |
|-------|------|-------------|
| `class_id` | `str` | Class identifier |
| `subject` | `str` | Subject |
| `grade` | `str` | Grade level |
| `period` | `str` | Analysis period |
| `total_students` | `int` | Number of students |
| `avg_score` | `float` | Average score |
| `score_distribution` | `Dict[str, int]` | 5-tier distribution |
| `weak_knowledge_points` | `List[WeakPoint]` | Weak areas |
| `strong_knowledge_points` | `List[str]` | Strong areas |
| `student_risk_levels` | `Dict[str, str]` | Risk levels (high/medium/low) |

### `StudentProfile`

| Field | Type | Description |
|-------|------|-------------|
| `student_id` | `str` | Student identifier |
| `name` | `str` | Student name |
| `grade` | `str` | Grade level |
| `subject` | `str` | Subject |
| `overall_level` | `str` | struggling/standard/advanced |
| `knowledge_mastery` | `Dict[str, float]` | Per-topic mastery |
| `learning_trend` | `str` | improving/stable/declining |
| `risk_indicators` | `List[str]` | Risk indicators |
| `recommended_actions` | `List[str]` | Recommended actions |

### `ErrorAnalysis`

| Field | Type | Description |
|-------|------|-------------|
| `error_id` | `str` | Error identifier |
| `knowledge_point_id` | `str` | Knowledge point ID |
| `error_type` | `str` | conceptual/procedural/careless/unknown |
| `frequency` | `int` | Occurrence count |
| `sample_responses` | `List[str]` | Typical wrong answers |
| `root_cause` | `str` | Root cause analysis |
| `remediation` | `str` | Remediation strategy |

### `RemedialPlan`

| Field | Type | Description |
|-------|------|-------------|
| `student_id` | `str` | Student identifier |
| `subject` | `str` | Subject |
| `grade` | `str` | Grade level |
| `weak_points` | `List[WeakPoint]` | Weak areas to address |
| `strategies` | `List[str]` | Remedial strategies |
| `timeline` | `str` | Suggested timeline |
| `exercises` | `List[Dict]` | Practice exercises |
| `estimated_duration` | `str` | Estimated duration |

### `AnalyticsEngine`

```python
from fusion_k12_teacher.analytics import AnalyticsEngine, load_from_json

engine = AnalyticsEngine(mlx=client, standards_query=query)

# Load assessment data
assessments = load_from_json("data.json")

# Build class profile
profile = await engine.build_class_profile("C1", "数学", "3", assessments)

# Build student profile
student = await engine.build_student_profile("S001", "数学", "3", history)

# Error analysis
errors = await engine.analyze_errors("数学", "3", responses)

# Remedial plan
plan = await engine.generate_remedial_plan("S001", "数学", "3", weak_points)

# Class report (Markdown)
report = await engine.generate_class_report(profile)
```

### Data Import

```python
from fusion_k12_teacher.analytics import load_from_json, load_from_csv

# JSON: array format or {"assessments": [...]} / {"records": [...]}
assessments = load_from_json("assessments.json")

# CSV: row-per-response, auto-groups by student_id + assessment_id
assessments = load_from_csv("assessments.csv")
```

## CLI Reference (v0.4 additions)

```bash
fusion-k12 analytics class-profile <class_id> <subject> <grade> [-d data.json]
fusion-k12 analytics student-profile <student_id> <subject> <grade> [-d data.json]
fusion-k12 analytics error-analysis <subject> <grade> [-d data.json]
fusion-k12 analytics remedial <student_id> <subject> <grade> [-d data.json]
fusion-k12 analytics report <class_id> <subject> <grade> [-d data.json]
```

## HTTP API Reference (v0.4 additions)

### Class Profile

```
POST /api/analytics/class-profile
{"class_id": "C1", "subject": "数学", "grade": "3", "data_path": "data.json"}
```

### Student Profile

```
POST /api/analytics/student-profile
{"student_id": "S001", "subject": "数学", "grade": "3", "data_path": "data.json"}
```

### Error Analysis

```
POST /api/analytics/error-analysis
{"subject": "数学", "grade": "3", "data_path": "data.json"}
```

### Remedial Plan

```
POST /api/analytics/remedial
{"student_id": "S001", "subject": "数学", "grade": "3", "data_path": "data.json"}
```

### Class Report

```
POST /api/analytics/class-report
{"class_id": "C1", "subject": "数学", "grade": "3", "data_path": "data.json"}
```

## Agent Module (v0.5)

### `TaskStep`

| Field | Type | Description |
|-------|------|-------------|
| `step_id` | `str` | Step identifier |
| `engine` | `str` | Engine name (curriculum/assessment/subject/personalization/content/analytics) |
| `method` | `str` | Engine method to call |
| `params` | `Dict` | Method parameters |
| `output_key` | `str` | Key name for passing output to next step |

### `TeachingTask`

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | `str` | Task identifier |
| `name` | `str` | Task name |
| `description` | `str` | Task description |
| `steps` | `List[TaskStep]` | Ordered list of steps |
| `tags` | `List[str]` | Task tags |
| `created_at` | `str` | Creation timestamp |

### `TaskResult`

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | `str` | Task identifier |
| `status` | `str` | success/partial/failed |
| `step_results` | `Dict[str, Any]` | Per-step results keyed by output_key |
| `errors` | `List[str]` | Error messages |
| `started_at` | `str` | Start timestamp |
| `completed_at` | `str` | Completion timestamp |

### `EngineRegistry`

```python
from fusion_k12_teacher.agent import EngineRegistry, execute_step, execute_task

registry = EngineRegistry()
registry.register("curriculum", curriculum_engine)
registry.register("assessment", assessment_engine)

# Execute a single step
result = await execute_step(registry, step)

# Execute a full task
task_result = await execute_task(registry, teaching_task)
```

### `TaskScheduler`

```python
from fusion_k12_teacher.agent import TaskScheduler

scheduler = TaskScheduler(registry, db_path="tasks.db")

# Add a cron-scheduled task
scheduler.add_task(teaching_task, cron="0 8 * * 1")  # Every Monday 8:00

# Enable/disable
scheduler.enable_task("weekly_prep")
scheduler.disable_task("weekly_prep")

# Run a task immediately
result = await scheduler.run_task("weekly_prep", params={...})

# Start/stop the scheduler daemon
scheduler.start()
scheduler.stop()

# Query history
history = scheduler.get_history(limit=10)
```

### Predefined Task Builders

| Builder | Steps | Description |
|---------|-------|-------------|
| `weekly_prep` | lesson plan + quiz + slides | Generate weekly lesson preparation materials |
| `weekly_summary` | class profile + class report | Generate weekly class summary report |
| `daily_homework_review` | grade + error analysis + remedial plan | Review daily homework and generate remedial |
| `monthly_report` | class profile + student profiles + error analysis + class report | Full monthly analytics report |
| `batch_differentiated_materials` | differentiated lessons for N topics | Batch generate differentiated materials |

### CLI Reference (v0.5 additions)

```bash
fusion-k12 agent tasks                                    # List predefined task templates
fusion-k12 agent enable <task_name>                       # Enable a scheduled task
fusion-k12 agent disable <task_name>                      # Disable a scheduled task
fusion-k12 agent run <task_name> [--subject 数学] [--grade 3] [--topic 分数]
fusion-k12 agent history [--limit 10]                     # Show task execution history
fusion-k12 agent start                                    # Start the task scheduler daemon
fusion-k12 agent stop                                     # Stop the task scheduler daemon
```

### HTTP API Reference (v0.5 additions)

#### List Agent Tasks

```
GET /api/agent/tasks
```

Response:
```json
[
  {
    "task_id": "weekly_prep",
    "name": "周备课任务",
    "description": "生成周教案、测验和课件",
    "steps": [
      {"step_id": "s1", "engine": "curriculum", "method": "generate_lesson_plan", "params": {}, "output_key": "lesson"},
      {"step_id": "s2", "engine": "curriculum", "method": "generate_quiz", "params": {}, "output_key": "quiz"},
      {"step_id": "s3", "engine": "content", "method": "generate_lesson_slides", "params": {}, "output_key": "slides"}
    ],
    "tags": ["weekly", "prep"]
  }
]
```

#### Run Agent Task

```
POST /api/agent/run
```

Request body:
```json
{"task_name": "weekly_prep", "params": {"subject": "数学", "grade": "3", "topic": "分数"}}
```

Response:
```json
{
  "task_id": "weekly_prep",
  "status": "success",
  "step_results": {
    "lesson": {"title": "分数初步认识教案", "subject": "数学", "grade": "3"},
    "quiz": {"title": "分数测验", "questions": [...]},
    "slides": {"title": "分数课件", "slides": [...]}
  },
  "errors": [],
  "started_at": "2026-07-28T08:00:00",
  "completed_at": "2026-07-28T08:00:15"
}
```

#### Schedule Agent Task

```
POST /api/agent/schedule
```

Request body:
```json
{"task_name": "weekly_prep", "action": "enable", "cron": "0 8 * * 1"}
```

`action` values: `enable`, `disable`

Response:
```json
{"task_name": "weekly_prep", "action": "enable", "status": "scheduled", "cron": "0 8 * * 1"}
```

#### Agent Task History

```
GET /api/agent/history?limit=10
```

Response:
```json
[
  {
    "task_id": "weekly_prep",
    "run_id": "run_001",
    "status": "success",
    "started_at": "2026-07-28T08:00:00",
    "completed_at": "2026-07-28T08:00:15",
    "step_results": {...}
  }
]
```

## Content Safety (v0.6)

### `ContentCheckResult`

| Field | Type | Description |
|-------|------|-------------|
| `is_safe` | `bool` | Whether content passed all checks |
| `risk_level` | `str` | safe/low/medium/high |
| `flagged_words` | `List[str]` | Sensitive words detected |
| `age_issues` | `List[str]` | Age-appropriateness issues |
| `llm_issues` | `List[str]` | LLM review issues |
| `filtered_text` | `str` | Text with sensitive words replaced |
| `summary` | `str` | Human-readable summary |

### `AgeRating`

| Field | Type | Description |
|-------|------|-------------|
| `grade` | `int` | Grade level (1-12) |
| `max_abstraction` | `str` | concrete/semi-abstract/abstract |
| `allowed_topics` | `List[str]` | Allowed topic categories |
| `restricted_topics` | `List[str]` | Restricted topic categories |
| `vocabulary_level` | `str` | basic/intermediate/advanced |

### `FilterLevel`

| Field | Type | Description |
|-------|------|-------------|
| `level` | `str` | strict/moderate/permissive |
| `sensitive_words` | `bool` | Enable sensitive word check |
| `age_check` | `bool` | Enable age-appropriateness check |
| `llm_review` | `bool` | Enable LLM safety review |
| `output_check` | `bool` | Enable output re-check |

### `ContentFilter`

```python
from fusion_k12_teacher.safety import ContentFilter, SensitiveWordList, AgeChecker

wordlist = SensitiveWordList()
age_checker = AgeChecker()
filter = ContentFilter(wordlist, age_checker, mlx=client)

# Full input check
result = filter.check_text("Some content...", grade=3)

# Output re-check
result = filter.check_output("Generated content...", grade=3)

# LLM safety review (async)
result = await filter.llm_review("Content to review", grade=3)

# Simple sensitive word filter
filtered = filter.filter_sensitive("Text with sensitive words")

# Get safety prompt suffix for prompt injection
suffix = filter.get_safety_prompt_suffix()
```

### `SensitiveWordList`

```python
from fusion_k12_teacher.safety import SensitiveWordList

wl = SensitiveWordList()
wl.load()                    # Load from data/sensitive_words.txt
wl.add("badword")            # Add a word
wl.remove("badword")         # Remove a word
words = wl.list_words()      # List all words
found = wl.check("text")     # Check text → list of flagged words
wl.save()                    # Persist to file
```

### `AgeChecker`

```python
from fusion_k12_teacher.safety import AgeChecker

checker = AgeChecker()
checker.load()               # Load from data/age_ratings.json
rating = checker.get_rating(3)  # Get AgeRating for grade 3
issues = checker.check_content("text", 3)  # Check content for grade
ok = checker.check_abstraction("abstract concept", 3)  # Check abstraction level
checker.save()               # Persist to file
```

### CLI Reference (v0.6 additions)

```bash
fusion-k12 safety check "content text" --grade 3    # Full safety check
fusion-k12 safety filter "content text"              # Filter sensitive words
fusion-k12 safety wordlist --add "word"              # Add sensitive word
fusion-k12 safety wordlist --remove "word"           # Remove sensitive word
fusion-k12 safety wordlist --list                    # List all words
```

### HTTP API Reference (v0.6 additions)

#### Safety Check

```
POST /api/safety/check
```

Request body:
```json
{"text": "content to check", "grade": 3}
```

Response:
```json
{
  "is_safe": false,
  "risk_level": "medium",
  "flagged_words": ["violence"],
  "age_issues": ["内容包含暴力描述，不适合1-3年级"],
  "llm_issues": [],
  "filtered_text": "content with ** replacement",
  "summary": "检测到1个敏感词，1个适龄问题"
}
```

#### Safety Filter

```
POST /api/safety/filter
```

Request body:
```json
{"text": "text to filter"}
```

Response:
```json
{"filtered_text": "text with ** replacement", "replaced_count": 2}
```

#### Safety Wordlist

```
GET /api/safety/wordlist
```

Response:
```json
{"words": ["暴力", "杀人", "血腥", ...], "count": 15}
```

```
POST /api/safety/wordlist
```

Request body:
```json
{"action": "add", "word": "newword"}
```

```json
{"action": "remove", "word": "someword"}
```

## Data Desensitization (v1.0)

### `DesensitizeConfig`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name_mode` | `str` | `"id"` | Name anonymization mode: id or mask |
| `id_prefix` | `str` | `"S"` | Prefix for ID-based names (S001, S002...) |
| `fields_to_mask` | `List[str]` | `["student_name","name","phone","email","address","id_number"]` | Fields to mask |
| `mask_char` | `str` | `"*"` | Mask character |
| `mask_keep_chars` | `int` | `1` | Number of leading chars to keep when masking |
| `id_counter_start` | `int` | `1` | Starting number for ID assignment |

### `AnonymizeResult`

| Field | Type | Description |
|-------|------|-------------|
| `original_count` | `int` | Number of original records |
| `anonymized_count` | `int` | Number of anonymized records |
| `name_map` | `Dict[str,str]` | Original name → anonymized ID |
| `masked_fields` | `List[str]` | Fields that were masked |

### `DataAnonymizer`

```python
from fusion_k12_teacher.desensitize import DataAnonymizer, DesensitizeConfig

config = DesensitizeConfig(name_mode="id", id_prefix="S")
anonymizer = DataAnonymizer(config)

# Anonymize records
result = anonymizer.anonymize_records([{"student_name": "张三", "phone": "13812345678", "score": 95}])
# result.anonymized_count == 1, result.name_map == {"张三": "S001"}

# Export desensitized data
exported = anonymizer.export_desensitized(records)

# Reverse: deanonymize
original = anonymizer.deanonymize_record(anonymized_record)

# Get name mapping
name_map = anonymizer.get_name_map()  # {"张三": "S001", "李四": "S002"}
```

### CLI Reference (v1.0 additions)

```bash
fusion-k12 desensitize anon data.json --mode id --prefix S --output anon.json
fusion-k12 desensitize export data.json --output desensitized.json
fusion-k12 content worksheet-diff --subject 数学 --grade 5 --topic 分数
```

### HTTP API Reference (v1.0 additions)

#### Desensitize Anonymize

```
POST /api/desensitize/anonymize
```

Request body:
```json
{"records": [{"student_name": "张三", "phone": "13812345678", "score": 95}], "name_mode": "id", "id_prefix": "S"}
```

Response:
```json
{"original_count": 1, "anonymized_count": 1, "name_map": {"张三": "S001"}, "masked_fields": ["phone"]}
```

#### Desensitize Export

```
POST /api/desensitize/export
```

Request body:
```json
{"records": [{"student_name": "张三", "phone": "13812345678"}], "name_mode": "id", "id_prefix": "S"}
```

Response:
```json
{"desensitized": [{"student_name": "S001", "phone": "1*********"}], "name_map": {"张三": "S001"}}
```

#### Analytics Upload

```
POST /api/analytics/upload
```

Request body:
```json
[{"student_name": "张三", "subject": "数学", "score": 95, "grade": 5}]
```

Response:
```json
{"uploaded": 1, "message": "上传成功"}
```

#### Differentiated Worksheet

```
POST /api/content/worksheet-diff
```

Request body:
```json
{"subject": "数学", "grade": 5, "topic": "分数", "num_questions": 8}
```

Response:
```json
{"struggling": {...}, "standard": {...}, "advanced": {...}}
```

## Deployment (v1.0)

See [deploy.md](deploy.md) for full deployment guide covering:

- **个人教师本地** — pip install + CLI/API
- **学校内网** — Docker Compose deployment
- **教培机构商用** — K8s + algorithm registration + compliance

