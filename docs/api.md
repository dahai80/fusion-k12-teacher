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

## Data Models

### `Vulnerability`

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Unique identifier |
| `title` | `str` | Vulnerability title |
| `description` | `str` | Detailed description |
| `severity` | `str` | `critical`, `high`, `medium`, `low` |
| `confidence` | `float` | 0.0 - 1.0 |
| `file_path` | `str` | Affected file path |
| `line_number` | `int` | Line number |
| `code_snippet` | `str` | Surrounding code context |
| `rule_id` | `str` | Matching rule ID |
| `cwe_id` | `str` | CWE identifier |
| `fix_suggestion` | `str` | Fix recommendation |
| `verified` | `bool` | AI-verified status |

### `ScanRule`

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Rule identifier |
| `name` | `str` | Human-readable name |
| `description` | `str` | Rule description |
| `severity` | `str` | Default severity |
| `cwe_id` | `str` | CWE mapping |
| `pattern` | `str` | Regex pattern |
| `language` | `str` | Target language |
| `fix_template` | `str` | Fix suggestion template |
| `category` | `str` | `injection`, `xss`, `crypto`, `config`, `auth` |