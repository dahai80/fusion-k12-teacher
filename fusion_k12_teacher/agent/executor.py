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

# AGT-1: 每引擎可调方法白名单 — 杜绝 getattr 任意方法(__init__/close/_private 等)
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
    """注册所有引擎到全局注册表。

    A14: 工厂(build_engines)纯构造, 注册由调用方显式调用本函数。
    bundle 优先(传 EngineBundle 一键注册), 否则按具名参数注册。
    """
    # A14: 传 bundle 时一键取字段, 否则用具名参数
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

    # AGT-1: 方法须在白名单内, 否则拒绝 — 防止调用 __init__/close/_private
    allowed = _ALLOWED_METHODS.get(step.engine)
    if allowed is None or step.method not in allowed:
        logger.error("引擎方法未授权: %s.%s", step.engine, step.method)
        raise ValueError(f"引擎 {step.engine} 方法 {step.method} 未授权, 不在白名单内")

    method = getattr(engine, step.method, None)
    if not method or not callable(method):
        raise ValueError(f"引擎 {step.engine} 无方法 {step.method}")

    resolved_params = _resolve_params(step, context)

    is_coro = inspect.iscoroutinefunction(method) or (
        callable(method) and inspect.iscoroutinefunction(getattr(method, "__wrapped__", None))
    )
    try:
        if is_coro:
            # R13: 超时取消协程本体 — asyncio.wait_for 到点抛 TimeoutError 并取消被等协程,
            # 但底层 httpx 请求可能不响应取消, 后端 fusion-mlx 仍在跑(长任务超时堆积)。
            # 不用 asyncio.shield (shield 会阻止取消信号到达 method, 反而无法超时取消)。
            # 此处诚实文档: 超时不保证后端终止, 仅取消本地等待; 后端长任务须靠其自身超时。
            raw = await asyncio.wait_for(method(**resolved_params), timeout=_STEP_TIMEOUT)
        else:
            raw = method(**resolved_params)
            if inspect.isawaitable(raw):
                raw = await asyncio.wait_for(raw, timeout=_STEP_TIMEOUT)
        result = raw
    except TimeoutError:
        logger.warning("步骤超时, 协程已取消(后端请求可能仍在跑): %s.%s", step.engine, step.method)
        raise RuntimeError(f"步骤超时({int(_STEP_TIMEOUT)}s): {step.engine}.{step.method}")

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
            # AGT-8: 优先 to_dict; 无 to_dict 时尝试 dataclasses.asdict; 都不行才降级 str
            # 并标记 _non_serializable, 避免历史把 dataclass 列表 str 成 "[<obj>,...]" 丢结构
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
                        logger.warning("步骤结果不可序列化, 降级 str: %s", type(step_result).__name__)
                        result.step_results[key] = {"_non_serializable": str(step_result)[:500]}
                except Exception as se:
                    logger.warning("步骤结果序列化失败, 降级 str: %s", se)
                    result.step_results[key] = {"_non_serializable": str(step_result)[:500]}

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
