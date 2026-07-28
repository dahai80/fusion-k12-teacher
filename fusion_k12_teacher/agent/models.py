"""Agent 模块数据模型 — TeachingTask, TaskStep, TaskResult。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class TaskStep:
    """任务步骤 — 指定引擎方法及参数。"""

    engine: str
    method: str
    params: Dict[str, Any] = field(default_factory=dict)
    output_key: str = ""
    depends_on: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "engine": self.engine,
            "method": self.method,
            "params": self.params,
            "output_key": self.output_key,
            "depends_on": self.depends_on,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> TaskStep:
        return cls(
            engine=d.get("engine", ""),
            method=d.get("method", ""),
            params=d.get("params", {}),
            output_key=d.get("output_key", ""),
            depends_on=d.get("depends_on", []),
        )


@dataclass
class TeachingTask:
    """教学任务 — 含调度配置与步骤链。"""

    id: str
    name: str
    task_type: str = "scheduled"
    schedule: str = ""
    steps: List[TaskStep] = field(default_factory=list)
    enabled: bool = True
    last_run: str = ""
    last_status: str = ""

    def to_dict(self) -> Dict[str, Any]:
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
    def from_dict(cls, d: Dict[str, Any]) -> TeachingTask:
        steps = [TaskStep.from_dict(s) for s in d.get("steps", [])]
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            task_type=d.get("task_type", "scheduled"),
            schedule=d.get("schedule", ""),
            steps=steps,
            enabled=d.get("enabled", True),
            last_run=d.get("last_run", ""),
            last_status=d.get("last_status", ""),
        )


@dataclass
class TaskResult:
    """任务执行结果。"""

    task_id: str
    status: str = "pending"
    started_at: str = ""
    completed_at: str = ""
    step_results: Dict[str, Any] = field(default_factory=dict)
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "step_results": self.step_results,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> TaskResult:
        return cls(
            task_id=d.get("task_id", ""),
            status=d.get("status", "pending"),
            started_at=d.get("started_at", ""),
            completed_at=d.get("completed_at", ""),
            step_results=d.get("step_results", {}),
            summary=d.get("summary", ""),
        )
