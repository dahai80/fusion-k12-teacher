# Subject module protocol — SubjectModule + capability base classes.
#
# Subjects (math/physics/...) implement SubjectModule, declaring which capabilities they
# support and returning instances. The platform fetches the subject module via SubjectRegistry,
# then the capability — never importing concrete subject classes.
#
# Unimplemented capabilities return None; platform/serve routes return 501 NotSupported —
# subjects can be implemented incrementally.

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


# Subject knowledge graph base class.
class KnowledgeGraphBase(ABC):

    # Load graph data (from curriculum standards/augmentation files). Fail-fast: cyclic dependencies refuse startup.
    @abstractmethod
    def load(self, standards_query: StandardsQuery | None = None) -> None:
        pass

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


# Subject rigor verification base class — authoritative numeric override, prevents subject hallucination.
class VerifierBase(ABC):

    @abstractmethod
    def verify_scene(self, scenario: str, entities: dict[str, Any]) -> VerifyResult: ...

    @abstractmethod
    def judge_checkpoint(self, checkpoint: Checkpoint, student_answer: str) -> JudgeResult: ...


# Problem-to-scene DSL compiler base class.
class SceneCompilerBase(ABC):

    @abstractmethod
    async def compile(self, problem_text: str, knowledge_node_id: str = "") -> SceneDSL: ...


# 5E Socratic lesson script generation base class.
class SocraticTutorBase(ABC):

    @abstractmethod
    async def generate_lesson_script(
        self, topic: str, grade: str, knowledge_node_id: str = "",
        prerequisites: list[str] | None = None,
        misconceptions: list[str] | None = None,
        layer: str = "B",
    ) -> FusionSocraticDSL: ...

    @abstractmethod
    async def judge_checkpoint(self, checkpoint: Checkpoint, student_answer: str) -> JudgeResult: ...


# Subject module — declares subject metadata + supported capabilities. The platform depends only on this protocol.
class SubjectModule(ABC):

    # Subject ID: math / physics / chemistry / english / chinese.
    @property
    @abstractmethod
    def subject_id(self) -> str:
        pass

    # Display name in the product locale (Chinese, e.g. the subject's native name).
    @property
    @abstractmethod
    def display_name(self) -> str:
        pass

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

    # Inject shared dependencies (mlx/safety filter/standards query). Subjects persist as needed.
    def init(
        self, mlx: MLXClient, content_filter: ContentFilter,
        standards_query: StandardsQuery | None = None,
    ) -> None:
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
