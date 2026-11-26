"""Predefined task library — 5 teaching automation tasks."""

from __future__ import annotations

import logging
from collections.abc import Callable

from .models import TaskStep, TeachingTask

logger = logging.getLogger(__name__)


def _load_assessments(data_path: str) -> list:
    """Load assessment data from data_path; return an empty list on failure."""
    if not data_path:
        return []
    try:
        # AGT-2: validate the path is inside allowed directories first; reject escapes directly
        # (shares the allowlist with serve)
        from ..analytics.loader import load_from_csv, load_from_json, validate_data_path
        validate_data_path(data_path)
        if data_path.lower().endswith(".csv"):
            return load_from_csv(data_path)
        return load_from_json(data_path)
    except Exception as e:
        logger.warning(f"Failed to load assessment data {data_path}: {e}")
        return []


def _extract_responses(assessments: list) -> list[dict]:
    """Aggregate all answer records from a StudentAssessment list."""
    responses = []
    for a in assessments:
        if hasattr(a, "responses") and a.responses:
            responses.extend(a.responses)
    return responses


def weekly_prep(subject: str = "数学", grade: str = "3", topic: str = "本周主题") -> TeachingTask:
    """Weekly prep — quiz → worksheet → slides."""
    # i18n: user-facing (task name shown in scheduler UI/API)
    return TeachingTask(
        id="weekly_prep",
        name="每周备课材料生成",
        task_type="scheduled",
        schedule="0 18 * * 0",
        steps=[
            TaskStep(
                engine="curriculum",
                method="generate_quiz",
                params={"subject": subject, "grade": grade, "topic": topic, "num_questions": 10},
                output_key="quiz",
            ),
            TaskStep(
                engine="content",
                method="generate_worksheet",
                params={"subject": subject, "grade": grade, "topic": topic},
                output_key="worksheet",
            ),
            TaskStep(
                engine="content",
                method="generate_lesson_slides",
                params={"subject": subject, "grade": grade, "topic": topic},
                output_key="slides",
            ),
        ],
    )


def weekly_summary(class_id: str = "C1", subject: str = "数学", grade: str = "3", data_path: str = "") -> TeachingTask:
    """Weekly class summary — class_profile → error_analysis → report."""
    assessments = _load_assessments(data_path)
    # i18n: user-facing (task name shown in scheduler UI/API)
    return TeachingTask(
        id="weekly_summary",
        name="班级学情周报",
        task_type="scheduled",
        schedule="0 18 * * 5",
        steps=[
            TaskStep(
                engine="analytics",
                method="build_class_profile",
                params={"class_id": class_id, "subject": subject, "grade": grade, "assessments": assessments},
                output_key="class_profile",
            ),
            TaskStep(
                engine="analytics",
                method="analyze_errors",
                params={"subject": subject, "grade": grade, "responses": _extract_responses(assessments)},
                output_key="error_analysis",
            ),
            TaskStep(
                engine="analytics",
                method="generate_class_report",
                params={"class_profile": "$class_profile"},
                output_key="report",
                depends_on=["class_profile"],
            ),
        ],
    )


def daily_homework_review(subject: str = "数学", grade: str = "3", data_path: str = "") -> TeachingTask:
    """Daily homework error remediation — error_analysis → remedial."""
    assessments = _load_assessments(data_path)
    responses = _extract_responses(assessments)
    # i18n: user-facing (task name shown in scheduler UI/API)
    return TeachingTask(
        id="daily_homework_review",
        name="每日作业错题补救",
        task_type="scheduled",
        schedule="0 20 * * 1-5",
        steps=[
            TaskStep(
                engine="analytics",
                method="analyze_errors",
                params={"subject": subject, "grade": grade, "responses": responses},
                output_key="errors",
            ),
            TaskStep(
                engine="analytics",
                method="generate_remedial_plan",
                params={"student_id": "all", "subject": subject, "grade": grade, "weak_points": "$errors"},
                output_key="remedial",
                depends_on=["errors"],
            ),
        ],
    )


def monthly_report(class_id: str = "C1", subject: str = "数学", grade: str = "3") -> TeachingTask:
    """Monthly teaching report — class_profile → report."""
    # i18n: user-facing (task name shown in scheduler UI/API)
    return TeachingTask(
        id="monthly_report",
        name="月度教学报告",
        task_type="scheduled",
        schedule="0 18 28 * *",
        steps=[
            TaskStep(
                engine="analytics",
                method="build_class_profile",
                params={"class_id": class_id, "subject": subject, "grade": grade, "assessments": []},
                output_key="class_profile",
            ),
            TaskStep(
                engine="analytics",
                method="generate_class_report",
                params={"class_profile": "$class_profile"},
                output_key="report",
                depends_on=["class_profile"],
            ),
        ],
    )


def batch_differentiated_materials(subject: str = "数学", grade: str = "3", topics: str = "分数,小数,百分数") -> TeachingTask:
    """Batch differentiated materials — generate three-tier content per topic."""
    steps = []
    # AGT-10: reject empty segments — topics.split(",") on an empty string yields [""], and an
    # empty topic would enqueue a step generating meaningless material.
    # Dedupe preserving first-occurrence order to avoid duplicate topics generating twice.
    seen = set()
    topic_list = []
    for t in topics.split(","):
        ts = t.strip()
        if ts and ts not in seen:
            seen.add(ts)
            topic_list.append(ts)
    for i, topic in enumerate(topic_list):
        steps.append(TaskStep(
            engine="differentiation",
            method="generate_differentiated_lesson",
            params={"subject": subject, "grade": grade, "topic": topic},
            output_key=f"lesson_{i}",
        ))
        steps.append(TaskStep(
            engine="differentiation",
            method="generate_differentiated_quiz",
            params={"subject": subject, "grade": grade, "topic": topic},
            output_key=f"quiz_{i}",
        ))

    # i18n: user-facing (task name shown in scheduler UI/API)
    return TeachingTask(
        id="batch_differentiated_materials",
        name="批量分层教学材料",
        task_type="triggered",
        steps=steps,
    )


TASK_BUILDERS: dict[str, Callable] = {
    "weekly_prep": weekly_prep,
    "weekly_summary": weekly_summary,
    "daily_homework_review": daily_homework_review,
    "monthly_report": monthly_report,
    "batch_differentiated_materials": batch_differentiated_materials,
}


def list_available_tasks() -> dict[str, str]:
    """Return available tasks {id: name}."""
    builder = {tid: fn().name for tid, fn in TASK_BUILDERS.items()}
    return builder


def build_task(task_id: str, **kwargs) -> TeachingTask:
    """Build a task instance by ID."""
    builder = TASK_BUILDERS.get(task_id)
    if not builder:
        raise ValueError(f"Unknown task: {task_id}")
    return builder(**kwargs)
