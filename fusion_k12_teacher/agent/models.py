"""Agent 模块数据模型 — TeachingTask, TaskStep, TaskResult。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .._coerce import coerce_bool, coerce_dict, coerce_str, coerce_str_list


@dataclass
class TaskStep:
    """任务步骤 — 指定引擎方法及参数。"""

    engine: str
    method: str
    params: dict[str, Any] = field(default_factory=dict)
    output_key: str = ""
    depends_on: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "method": self.method,
            "params": self.params,
            "output_key": self.output_key,
            "depends_on": self.depends_on,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TaskStep:
        return cls(
            engine=coerce_str(d.get("engine", "")),
            method=coerce_str(d.get("method", "")),
            params=coerce_dict(d.get("params", {})),
            output_key=coerce_str(d.get("output_key", "")),
            depends_on=coerce_str_list(d.get("depends_on", [])),
        )


@dataclass
class TeachingTask:
    """教学任务 — 含调度配置与步骤链。"""

    id: str
    name: str
    task_type: str = "scheduled"
    schedule: str = ""
    steps: list[TaskStep] = field(default_factory=list)
    enabled: bool = True
    last_run: str = ""
    last_status: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "task_type": self.task_type,
            "schedule": self.schedule,
            "steps": [s.to_dict() for s in self.steps],
            "enabled": self.enabled,
            "last_run": self.last_run,
            "last_status": self.last_status,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TeachingTask:
        steps = [TaskStep.from_dict(s) for s in d.get("steps", [])]
        return cls(
            id=coerce_str(d.get("id", "")),
            name=coerce_str(d.get("name", "")),
            task_type=coerce_str(d.get("task_type", "scheduled")),
            schedule=coerce_str(d.get("schedule", "")),
            steps=steps,
            enabled=coerce_bool(d.get("enabled", True)),
            last_run=coerce_str(d.get("last_run", "")),
            last_status=coerce_str(d.get("last_status", "")),
        )


@dataclass
class TaskResult:
    """任务执行结果。"""

    task_id: str
    status: str = "pending"
    started_at: str = ""
    completed_at: str = ""
    step_results: dict[str, Any] = field(default_factory=dict)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "step_results": self.step_results,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TaskResult:
        return cls(
            task_id=coerce_str(d.get("task_id", "")),
            status=coerce_str(d.get("status", "pending")),
            started_at=coerce_str(d.get("started_at", "")),
            completed_at=coerce_str(d.get("completed_at", "")),
            step_results=coerce_dict(d.get("step_results", {})),
            summary=coerce_str(d.get("summary", "")),
        )
