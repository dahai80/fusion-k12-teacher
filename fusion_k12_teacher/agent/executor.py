"""任务执行器 — 按步骤链调度引擎方法。"""

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


def _resolve_params(step: TaskStep, context: dict[str, Any]) -> dict[str, Any]:
    """解析步骤参数 — $ref 引用须已产出或在 depends_on 中声明，否则报错不静默。"""
    resolved = {}
    for k, v in step.params.items():
        if isinstance(v, str) and v.startswith("$"):
            ref_key = v[1:]
            if ref_key in context:
                resolved[k] = context[ref_key]
            elif ref_key in step.depends_on:
                raise ValueError(f"步骤引用未解析: {ref_key} (参数 {k})")
            else:
                raise ValueError(f"步骤引用未声明依赖: ${ref_key} (参数 {k})，须加入 depends_on")
        else:
            resolved[k] = v
    return resolved


async def execute_step(step: TaskStep, context: dict[str, Any]) -> Any:
    """执行单个步骤 — 带超时与协程安全。"""
    engine = registry.get(step.engine)
    if not engine:
        raise ValueError(f"引擎未注册: {step.engine}")

    method = getattr(engine, step.method, None)
    if not method or not callable(method):
        raise ValueError(f"引擎 {step.engine} 无方法 {step.method}")

    resolved_params = _resolve_params(step, context)

    is_coro = inspect.iscoroutinefunction(method) or (
        callable(method) and inspect.iscoroutinefunction(getattr(method, "__wrapped__", None))
    )
    try:
        if is_coro:
            raw = await asyncio.wait_for(method(**resolved_params), timeout=_STEP_TIMEOUT)
        else:
            raw = method(**resolved_params)
            if inspect.isawaitable(raw):
                raw = await asyncio.wait_for(raw, timeout=_STEP_TIMEOUT)
        result = raw
    except TimeoutError:
        raise RuntimeError(f"步骤超时({int(_STEP_TIMEOUT)}s): {step.engine}.{step.method}")
    except Exception:
        raise

    if step.output_key:
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
            key = step.output_key or f"{step.engine}.{step.method}"
            if key in result.step_results:
                logger.warning(f"步骤输出键重复: {key}，追加序号")
                idx = 0
                base = key
                while key in result.step_results:
                    idx += 1
                    key = f"{base}_{idx}"
            result.step_results[key] = (
                step_result.to_dict() if hasattr(step_result, "to_dict") else str(step_result)
            )

        result.status = "success"
        result.summary = f"完成 {len(task.steps)} 步"
    except Exception as e:
        result.status = "failed"
        result.summary = f"失败: {e}"
        logger.error(f"任务执行失败 {task.id}: {e}", exc_info=True)

    result.completed_at = datetime.now().isoformat()

    task.last_run = result.completed_at
    task.last_status = result.status

    return result
