# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Fusion-K12-Teacher is a local AI-powered K-12 education assistant for macOS Apple Silicon. It provides lesson planning, assessment, subject expertise, personalized learning, and content generation — all 100% offline via fusion-mlx. The CLI entry point is `fusion-k12`.

## Development Setup

```bash
cd /Users/dahai/fusion/fusion-k12-teacher
source .venv/bin/activate
pip install -e ".[test]"
```

## Commands

| Command | Purpose |
|---------|---------|
| `pytest tests/ -v` | Run all tests |
| `pytest tests/test_core.py -v` | Run core tests only |
| `pytest tests/test_core.py::TestCurriculumEngine -v` | Run a single test class |
| `pytest -k "test_generate_lesson_plan" -v` | Run a single test by name |
| `pytest --cov=fusion_k12_teacher tests/` | Run with coverage |
| `fusion-k12 --help` | CLI help |
| `fusion-k12 lesson plan 数学 3 分数` | Generate a lesson plan (requires fusion-mlx running) |

## Architecture

```
CLI (click) → Engine Layer → MLXClient (HTTP) → fusion-mlx (/v1/chat/completions)
```

- **CLI** (`fusion_k12_teacher/cli.py`): Click-based CLI with 11 command groups: `lesson`, `assess`, `subject`, `personalize`, `content`, `standards`, `analytics`, `agent`, `safety`, `desensitize`, `serve`. Each command is async; `asyncio.run()` bridges sync Click to async engines.

- **MLXClient** (`fusion_k12_teacher/ai_client.py`): Thin wrapper around `fusion_core.mlx_client.FusionMLXClient`. All LLM calls go through `self._inner.chat_text()`. Default model auto-detected via `list_models()`, falls back to `qwen3.5-9b`.

- **5 Engine modules** — all follow the same pattern:
  - Accept `MLXClient` in constructor (dependency injection)
  - Build a Chinese-language prompt requesting JSON output
  - Call `self.mlx.chat()` with low temperature (0.2–0.5)
  - Parse response via `_parse_json()` (handles ```json code blocks)
  - Return a dataclass on success, or a default/empty dataclass on failure

  | Module | Engine Class | Data Classes | Key Methods |
  |--------|-------------|--------------|-------------|
  | `curriculum/` | `CurriculumEngine` | `LessonPlan`, `Quiz` | `generate_lesson_plan`, `generate_quiz`, `generate_unit_plan` |
  | `assessment/` | `AssessmentEngine` | `GradingResult`, `StudentReport` | `grade_essay`, `grade_math`, `generate_report`, `generate_rubric` |
  | `subjects/` | `SubjectExpert` | `SubjectExercise` | `explain_concept`, `generate_exercise`, `stem_project`, `language_activity` |
  | `personalization/` | `PersonalizationEngine` | `LearningPath` | `create_learning_path`, `diagnose_skills`, `recommend_resources` |
  | `content/` | `ContentGenerator` | `Worksheet` | `generate_worksheet`, `generate_flashcards`, `generate_lesson_slides`, `generate_educational_game`, `generate_parent_communication` |
  | `analytics/` | `AnalyticsEngine` | `ClassProfile`, `StudentProfile`, `ErrorAnalysis`, `RemedialPlan`, `StudentAssessment`, `WeakPoint` | `build_class_profile`, `build_student_profile`, `analyze_errors`, `generate_remedial_plan`, `generate_class_report` |
  | `agent/` | `EngineRegistry` + `TaskScheduler` | `TaskStep`, `TeachingTask`, `TaskResult` | `execute_task`, `scheduler.run_task` |
  | `safety/` | `ContentFilter` | `ContentCheckResult`, `AgeRating`, `FilterLevel` | `check_text`, `check_output`, `llm_review`, `filter_sensitive` |
  | `desensitize/` | `DataAnonymizer` | `DesensitizeConfig`, `AnonymizeResult` | `anonymize_records`, `deanonymize_record`, `export_desensitized` |

## Key Patterns

- **`_parse_json()` duplication**: Every engine has its own `_parse_json()` method (strips markdown code blocks, then `json.loads`). This is intentional per-module isolation, not a refactor target.

- **Graceful degradation**: All async engine methods catch exceptions and return default dataclass instances rather than raising. Tests account for this by checking `result.field == expected OR "error" in result`.

- **fusion-mlx dependency**: The AI backend (`fusion-mlx`) runs as a separate HTTP service at `http://localhost:11434/v1`. Start/stop it with `~/claude-home/fusion-mlx/start.sh start|stop`. Tests that hit real AI calls require the service running; mock-based tests (in `test_coverage.py`) work offline.

- **Shared `fusion-core`**: `MLXClient` wraps `fusion_core.mlx_client.FusionMLXClient` — no direct HTTP client code in this repo.

- **Standards integration**: `AnalyticsEngine` and `DifferentiationEngine` accept optional `StandardsQuery` for prerequisite lookups and curriculum alignment.

- **Data import**: `analytics/loader.py` provides `load_from_json()` and `load_from_csv()` for importing assessment data. JSON supports array and object (`assessments`/`records` key) formats.

- **Agent module**: `agent/` provides multi-step task orchestration. `EngineRegistry` maps engine names to instances; `execute_step`/`execute_task` run steps sequentially, passing outputs between steps. `TaskScheduler` (APScheduler + SQLite) handles cron-based scheduling and persistence. 5 predefined task builders (`weekly_prep`, `weekly_summary`, `daily_homework_review`, `monthly_report`, `batch_differentiated_materials`) wire together existing engine methods.

- **Safety module**: `safety/` provides multi-layer content filtering. `SensitiveWordList` loads/checks/replaces sensitive words from text file. `AgeChecker` validates content against grade-tiered rules (1-3: concrete, 4-6: semi-abstract, 7-12: abstract). `ContentFilter` combines sensitive word check, age check, LLM self-review, and output verification. `FilterLevel` controls which layers are active.

- **Desensitize module**: `desensitize/` provides student data privacy protection. `DataAnonymizer` maps names to IDs (张三→S001), masks fields (phone→1**********), and supports reversible deanonymization via `name_map`. `DesensitizeConfig` controls name_mode (id/mask), id_prefix, and fields_to_mask.

## Testing

- `test_core.py`: Unit + integration tests (some require fusion-mlx for real AI calls)
- `test_coverage.py`: Mock-based tests using `async def mock_chat()` monkey-patching on `engine.mlx.chat` for full success-path coverage without fusion-mlx
- `test_analytics.py`: Analytics module tests — models round-trip, loader JSON/CSV, engine stats, LLM mock with graceful degradation
- `test_agent.py`: Agent module tests — EngineRegistry, execute_step/execute_task, predefined task builders, TaskScheduler scheduling and persistence
- `test_safety.py`: Safety module tests — ContentCheckResult/AgeRating/FilterLevel models, SensitiveWordList load/add/remove/check, AgeChecker grade tiers, ContentFilter multi-layer check/output/llm_review
- `test_desensitize.py`: Desensitize module tests — DesensitizeConfig/AnonymizeResult models, DataAnonymizer anonymize/deanonymize/mask/export
- `pytest.ini_options.asyncio_mode = "auto"` — all `async def test_*` are auto-treated as async tests
