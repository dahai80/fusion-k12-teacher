"""预定义任务库 — 5 个教学自动化任务。"""

from __future__ import annotations

from .models import TaskStep, TeachingTask


def weekly_prep(subject: str = "数学", grade: str = "3", topic: str = "本周主题") -> TeachingTask:
    """每周备课 — quiz → worksheet → slides。"""
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
    """每周学情汇总 — class_profile → error_analysis → report。"""
    return TeachingTask(
        id="weekly_summary",
        name="班级学情周报",
        task_type="scheduled",
        schedule="0 18 * * 5",
        steps=[
            TaskStep(
                engine="analytics",
                method="build_class_profile",
                params={"class_id": class_id, "subject": subject, "grade": grade},
                output_key="class_profile",
            ),
            TaskStep(
                engine="analytics",
                method="analyze_errors",
                params={"subject": subject, "grade": grade},
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
    """每日作业错题补救 — error_analysis → remedial。"""
    return TeachingTask(
        id="daily_homework_review",
        name="每日作业错题补救",
        task_type="scheduled",
        schedule="0 20 * * 1-5",
        steps=[
            TaskStep(
                engine="analytics",
                method="analyze_errors",
                params={"subject": subject, "grade": grade},
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
    """月度教学报告 — class_profile → student_profile → report。"""
    return TeachingTask(
        id="monthly_report",
        name="月度教学报告",
        task_type="scheduled",
        schedule="0 18 28 * *",
        steps=[
            TaskStep(
                engine="analytics",
                method="build_class_profile",
                params={"class_id": class_id, "subject": subject, "grade": grade},
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
    """批量分层教学材料 — 逐主题生成三层内容。"""
    steps = []
    for i, topic in enumerate(topics.split(",")):
        steps.append(TaskStep(
            engine="differentiation",
            method="generate_differentiated_lesson",
            params={"subject": subject, "grade": grade, "topic": topic.strip()},
            output_key=f"lesson_{i}",
        ))
        steps.append(TaskStep(
            engine="differentiation",
            method="generate_differentiated_quiz",
            params={"subject": subject, "grade": grade, "topic": topic.strip()},
            output_key=f"quiz_{i}",
        ))

    return TeachingTask(
        id="batch_differentiated_materials",
        name="批量分层教学材料",
        task_type="triggered",
        steps=steps,
    )


TASK_BUILDERS: dict[str, callable] = {
    "weekly_prep": weekly_prep,
    "weekly_summary": weekly_summary,
    "daily_homework_review": daily_homework_review,
    "monthly_report": monthly_report,
    "batch_differentiated_materials": batch_differentiated_materials,
}


def list_available_tasks() -> dict[str, str]:
    """返回可用任务 {id: name}。"""
    builder = {tid: fn().name for tid, fn in TASK_BUILDERS.items()}
    return builder


def build_task(task_id: str, **kwargs) -> TeachingTask:
    """按 ID 构建任务实例。"""
    builder = TASK_BUILDERS.get(task_id)
    if not builder:
        raise ValueError(f"未知任务: {task_id}")
    return builder(**kwargs)
