"""任务执行器 — 按步骤链调度引擎方法。"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from .models import TaskResult, TaskStep, TeachingTask

logger = logging.getLogger(__name__)


class EngineRegistry:
    """引擎注册表 — 按名称查找引擎实例。"""

    def __init__(self):
        self._engines: dict[str, Any] = {}

    def register(self, name: str, engine: Any) -> None:
        self._engines[name] = engine
        logger.info(f"引擎注册: {name}")

    def get(self, name: str) -> Any | None:
        return self._engines.get(name)

    def list_names(self) -> list:
        return list(self._engines.keys())


registry = EngineRegistry()


def register_all_engines(
    curriculum=None,
    assessment=None,
    subjects=None,
    personalization=None,
    content=None,
    differentiation=None,
    analytics=None,
    standards_query=None,
) -> EngineRegistry:
    """注册所有引擎到全局注册表。"""
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


async def execute_step(step: TaskStep, context: dict[str, Any]) -> Any:
    """执行单个步骤。"""
    engine = registry.get(step.engine)
    if not engine:
        raise ValueError(f"引擎未注册: {step.engine}")

    method = getattr(engine, step.method, None)
    if not method or not callable(method):
        raise ValueError(f"引擎 {step.engine} 无方法 {step.method}")

    resolved_params = {}
    for k, v in step.params.items():
        if isinstance(v, str) and v.startswith("$"):
            ref_key = v[1:]
            resolved_params[k] = context.get(ref_key, v)
        else:
            resolved_params[k] = v

    if asyncio.iscoroutinefunction(method):
        result = await method(**resolved_params)
    else:
        result = method(**resolved_params)

    if step.output_key:
        if hasattr(result, "to_dict"):
            context[step.output_key] = result.to_dict()
        else:
            context[step.output_key] = result

    logger.info(f"步骤完成: {step.engine}.{step.method} → {step.output_key}")
    return result


async def execute_task(task: TeachingTask) -> TaskResult:
    """执行完整任务 — 按步骤链顺序执行。"""
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
                    raise ValueError(f"步骤依赖未满足: {dep}")

            step_result = await execute_step(step, context)
            result.step_results[step.output_key or f"{step.engine}.{step.method}"] = (
                step_result.to_dict() if hasattr(step_result, "to_dict") else str(step_result)
            )

        result.status = "success"
        result.summary = f"完成 {len(task.steps)} 步"
    except Exception as e:
        result.status = "failed"
        result.summary = f"失败: {e}"
        logger.error(f"任务执行失败 {task.id}: {e}")

    result.completed_at = datetime.now().isoformat()

    task.last_run = result.completed_at
    task.last_status = result.status

    return result
