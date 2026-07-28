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

- **CLI** (`fusion_k12_teacher/cli.py`): Click-based CLI with 5 command groups: `lesson`, `assess`, `subject`, `personalize`, `content`. Each command is async; `asyncio.run()` bridges sync Click to async engines.

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

## Key Patterns

- **`_parse_json()` duplication**: Every engine has its own `_parse_json()` method (strips markdown code blocks, then `json.loads`). This is intentional per-module isolation, not a refactor target.

- **Graceful degradation**: All async engine methods catch exceptions and return default dataclass instances rather than raising. Tests account for this by checking `result.field == expected OR "error" in result`.

- **fusion-mlx dependency**: The AI backend (`fusion-mlx`) runs as a separate HTTP service at `http://localhost:8000/v1`. Start/stop it with `~/claude-home/fusion-mlx/start.sh start|stop`. Tests that hit real AI calls require the service running; mock-based tests (in `test_coverage.py`) work offline.

- **Shared `fusion-core`**: `MLXClient` wraps `fusion_core.mlx_client.FusionMLXClient` — no direct HTTP client code in this repo.

## Testing

- `test_core.py`: Unit + integration tests (some require fusion-mlx for real AI calls)
- `test_coverage.py`: Mock-based tests using `async def mock_chat()` monkey-patching on `engine.mlx.chat` for full success-path coverage without fusion-mlx
- `pytest.ini_options.asyncio_mode = "auto"` — all `async def test_*` are auto-treated as async tests
