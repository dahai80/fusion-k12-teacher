"""学科模块协议 — SubjectModule + 各能力基类。

学科 (math/physics/...) 实现 SubjectModule, 声明自己支持哪些能力并返回实例。
平台通过 SubjectRegistry 取学科模块, 再取能力, 全程不 import 学科具体类。

未实现的能力返回 None, 平台/serve 路由返回 501 NotSupported — 学科可渐进实现。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from ..ai_client import MLXClient
from ..safety.filter import ContentFilter
from ..standards.query import StandardsQuery
from .models import (
    Checkpoint,
    FusionSocraticDSL,
    GraphNode,
    JudgeResult,
    SceneDSL,
    VerifyResult,
)

logger = logging.getLogger(__name__)


class KnowledgeGraphBase(ABC):
    """学科知识图谱基类。"""

    @abstractmethod
    def load(self, standards_query: StandardsQuery | None = None) -> None:
        """加载图谱数据 (从课标/增强文件)。fail-fast: 环依赖拒启。"""

    @abstractmethod
    def get_node(self, node_id: str) -> GraphNode | None: ...

    @abstractmethod
    def query(self, **filters: Any) -> list[GraphNode]: ...

    @abstractmethod
    def reverse_attribution(self, node_id: str, max_depth: int = 3) -> list[str]: ...

    @abstractmethod
    def is_dag(self) -> bool: ...

    @abstractmethod
    def to_json(self) -> dict[str, Any]: ...


class VerifierBase(ABC):
    """学科严谨性校验基类 — 数值权威覆写, 防学科幻觉。"""

    @abstractmethod
    def verify_scene(self, scenario: str, entities: dict[str, Any]) -> VerifyResult: ...

    @abstractmethod
    def judge_checkpoint(self, checkpoint: Checkpoint, student_answer: str) -> JudgeResult: ...


class SceneCompilerBase(ABC):
    """题目→场景 DSL 编译器基类。"""

    @abstractmethod
    async def compile(self, problem_text: str, knowledge_node_id: str = "") -> SceneDSL: ...


class SocraticTutorBase(ABC):
    """5E 苏格拉底课稿生成基类。"""

    @abstractmethod
    async def generate_lesson_script(
        self, topic: str, grade: str, knowledge_node_id: str = "",
        prerequisites: list[str] | None = None,
        misconceptions: list[str] | None = None,
        layer: str = "B",
    ) -> FusionSocraticDSL: ...

    @abstractmethod
    async def judge_checkpoint(self, checkpoint: Checkpoint, student_answer: str) -> JudgeResult: ...


class SubjectModule(ABC):
    """学科模块 — 声明学科元信息 + 支持的能力。平台只依赖此协议。"""

    @property
    @abstractmethod
    def subject_id(self) -> str:
        """学科 ID: math / physics / chemistry / english / chinese。"""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """中文显示名: 数学 / 物理 / 化学 / 英语 / 语文。"""

    @property
    def supported_grades(self) -> tuple[int, ...]:
        return tuple(range(1, 13))

    @property
    def has_knowledge_graph(self) -> bool:
        return False

    @property
    def has_scene_compiler(self) -> bool:
        return False

    @property
    def has_socratic_tutor(self) -> bool:
        return False

    @property
    def has_verifier(self) -> bool:
        return False

    @property
    def has_problem_bank(self) -> bool:
        return False

    def init(
        self, mlx: MLXClient, content_filter: ContentFilter,
        standards_query: StandardsQuery | None = None,
    ) -> None:
        """注入共享依赖 (mlx/安全过滤器/课标查询)。学科按需保存。"""
        self._mlx = mlx
        self._content_filter = content_filter
        self._standards_query = standards_query

    def knowledge_graph(self) -> KnowledgeGraphBase | None:
        return None

    def scene_compiler(self) -> SceneCompilerBase | None:
        return None

    def socratic_tutor(self) -> SocraticTutorBase | None:
        return None

    def verifier(self) -> VerifierBase | None:
        return None

    def problem_bank(self) -> Any:
        return None

    def to_manifest(self) -> dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "display_name": self.display_name,
            "supported_grades": list(self.supported_grades),
            "capabilities": {
                "knowledge_graph": self.has_knowledge_graph,
                "scene_compiler": self.has_scene_compiler,
                "socratic_tutor": self.has_socratic_tutor,
                "verifier": self.has_verifier,
                "problem_bank": self.has_problem_bank,
            },
        }
