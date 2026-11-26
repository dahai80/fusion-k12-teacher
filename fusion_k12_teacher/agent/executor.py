# Task executor — dispatches engine methods along the step chain.

from __future__ import annotations

import asyncio
import inspect
import logging
import os
from datetime import datetime
from typing import Any

from .models import TaskResult, TaskStep, TeachingTask

logger = logging.getLogger(__name__)

_STEP_TIMEOUT = float(os.environ["FUSION_STEP_TIMEOUT"]) if "FUSION_STEP_TIMEOUT" in os.environ else 180.0

# AGT-1: per-engine callable method whitelist — blocks getattr on arbitrary methods (__init__/close/_private etc.)
_ALLOWED_METHODS: dict[str, set[str]] = {
    "curriculum": {"generate_lesson_plan", "generate_quiz", "generate_unit_plan"},
    "assessment": {"grade_essay", "grade_math", "generate_report", "generate_rubric"},
    "subjects": {"explain_concept", "generate_exercise", "stem_project", "language_activity"},
    "personalization": {"create_learning_path", "diagnose_skills", "recommend_resources"},
    "content": {
        "generate_worksheet", "generate_flashcards", "generate_lesson_slides",
        "generate_educational_game", "generate_parent_communication",
    },
    "differentiation": {
        "generate_differentiated_lesson", "generate_differentiated_quiz",
        "generate_differentiated_worksheet",
    },
    "analytics": {
        "build_class_profile", "build_student_profile", "analyze_errors",
        "generate_remedial_plan", "generate_class_report",
    },
    "standards_query": {
        "get_knowledge_points", "get_prerequisites", "get_progression",
        "find_by_topic", "validate_coverage", "get_strands", "get_by_strand",
        "get_by_difficulty",
    },
}


# Engine registry — looks up engine instances by name.
class EngineRegistry:

    def __init__(self):
        self._engines: dict[str, Any] = {}

    def register(self, name: str, engine: Any) -> None:
        self._engines[name] = engine
        logger.info(f"engine registered: {name}")

    def get(self, name: str) -> Any | None:
        return self._engines.get(name)

    def list_names(self) -> list:
        return list(self._engines.keys())


registry = EngineRegistry()


# Registers all engines into the global registry.
#
#     A14: the factory (build_engines) is pure construction; callers explicitly call this function to register.
#     bundle takes priority (pass an EngineBundle to register in one shot), otherwise registers via named params.
def register_all_engines(
    bundle: Any = None,
    *,
    curriculum=None,
    assessment=None,
    subjects=None,
    personalization=None,
    content=None,
    differentiation=None,
    analytics=None,
    standards_query=None,
) -> EngineRegistry:
    # A14: when a bundle is passed, pull fields in one shot; otherwise use named params
    if bundle is not None:
        curriculum = getattr(bundle, "curriculum", None)
        assessment = getattr(bundle, "assessment", None)
        subjects = getattr(bundle, "subjects", None)
        personalization = getattr(bundle, "personalization", None)
        content = getattr(bundle, "content", None)
        differentiation = getattr(bundle, "differentiation", None)
        analytics = getattr(bundle, "analytics", None)
        standards_query = getattr(bundle, "standards_query", None)
    if curriculum:
        registry.register("curriculum", curriculum)
    if assessment:
        registry.register("assessment", assessment)
    if subjects:
        registry.register("subjects", subjects)
    if personalization:
        registry.register("personalization", personalization)
    if content:
        registry.register("content", content)
    if differentiation:
        registry.register("differentiation", differentiation)
    if analytics:
        registry.register("analytics", analytics)
    if standards_query:
        registry.register("standards_query", standards_query)
    return registry


# Resolves step params — $ref references must already be produced or declared in depends_on, otherwise error out loudly.
def _resolve_params(step: TaskStep, context: dict[str, Any]) -> dict[str, Any]:
    resolved = {}
    for k, v in step.params.items():
        if isinstance(v, str) and v.startswith("$"):
            ref_key = v[1:]
            if ref_key in context:
                resolved[k] = context[ref_key]
            elif ref_key in step.depends_on:
                raise ValueError(f"step reference unresolved: {ref_key} (param {k})")
            else:
                raise ValueError(f"step reference missing dependency declaration: ${ref_key} (param {k}), must be added to depends_on")
        else:
            resolved[k] = v
    return resolved


# Executes a single step — with timeout and coroutine safety.
async def execute_step(step: TaskStep, context: dict[str, Any]) -> Any:
    engine = registry.get(step.engine)
    if not engine:
        raise ValueError(f"engine not registered: {step.engine}")

    # AGT-1: method must be whitelisted, otherwise rejected — prevents calling __init__/close/_private
    allowed = _ALLOWED_METHODS.get(step.engine)
    if allowed is None or step.method not in allowed:
        logger.error("engine method not authorized: %s.%s", step.engine, step.method)
        raise ValueError(f"engine {step.engine} method {step.method} not authorized, not in whitelist")

    method = getattr(engine, step.method, None)
    if not method or not callable(method):
        raise ValueError(f"engine {step.engine} has no method {step.method}")

    resolved_params = _resolve_params(step, context)

    is_coro = inspect.iscoroutinefunction(method) or (
        callable(method) and inspect.iscoroutinefunction(getattr(method, "__wrapped__", None))
    )
    try:
        if is_coro:
            # R13: timeout cancels the coroutine itself — asyncio.wait_for raises TimeoutError on schedule
            # and cancels the awaited coroutine, but the underlying httpx request may not respond to
            # cancellation and the backend fusion-mlx keeps running (long-task timeout pile-up).
            # No asyncio.shield (shield blocks the cancel signal from reaching the method, defeating the timeout).
            # Honest documentation here: timeout does not guarantee backend termination, it only cancels the
            # local wait; long backend tasks must rely on their own timeout.
            raw = await asyncio.wait_for(method(**resolved_params), timeout=_STEP_TIMEOUT)
        else:
            raw = method(**resolved_params)
            if inspect.isawaitable(raw):
                raw = await asyncio.wait_for(raw, timeout=_STEP_TIMEOUT)
        result = raw
    except TimeoutError:
        logger.warning("step timed out, coroutine cancelled (backend request may still be running): %s.%s", step.engine, step.method)
        raise RuntimeError(f"step timed out ({int(_STEP_TIMEOUT)}s): {step.engine}.{step.method}")

    if step.output_key:
        context[step.output_key] = result

    logger.info(f"step completed: {step.engine}.{step.method} → {step.output_key}")
    return result


# Executes the full task — running the step chain in order.
async def execute_task(task: TeachingTask) -> TaskResult:
    result = TaskResult(
        task_id=task.id,
        status="running",
        started_at=datetime.now().isoformat(),
    )

    context: dict[str, Any] = {}

    try:
        for step in task.steps:
            for dep in step.depends_on:
                if dep not in context:
                    raise ValueError(f"step dependency not satisfied: {dep}")

            step_result = await execute_step(step, context)
            key = step.output_key or f"{step.engine}.{step.method}"
            if key in result.step_results:
                logger.warning(f"duplicate step output key: {key}, appending sequence number")
                idx = 0
                base = key
                while key in result.step_results:
                    idx += 1
                    key = f"{base}_{idx}"
            # AGT-8: prefer to_dict; without to_dict try dataclasses.asdict; degrade to str only as last resort
            # and mark _non_serializable, so history does not str() dataclass lists into "[<obj>,...]" losing structure
            if hasattr(step_result, "to_dict") and callable(getattr(step_result, "to_dict")):
                result.step_results[key] = step_result.to_dict()
            else:
                try:
                    from dataclasses import asdict, is_dataclass
                    if is_dataclass(step_result) and not isinstance(step_result, type):
                        result.step_results[key] = asdict(step_result)
                    elif isinstance(step_result, (list, tuple)) and step_result and is_dataclass(step_result[0]):
                        result.step_results[key] = [
                            asdict(x) if is_dataclass(x) else str(x) for x in step_result
                        ]
                    else:
                        logger.warning("step result not serializable, degrading to str: %s", type(step_result).__name__)
                        result.step_results[key] = {"_non_serializable": str(step_result)[:500]}
                except Exception as se:
                    logger.warning("step result serialization failed, degrading to str: %s", se)
                    result.step_results[key] = {"_non_serializable": str(step_result)[:500]}

        result.status = "success"
        result.summary = f"completed {len(task.steps)} steps"
    except Exception as e:
        result.status = "failed"
        result.summary = f"failed: {e}"
        logger.error(f"task execution failed {task.id}: {e}", exc_info=True)

    result.completed_at = datetime.now().isoformat()

    task.last_run = result.completed_at
    task.last_status = result.status

    return result
