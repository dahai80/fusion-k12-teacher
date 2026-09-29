"""数学学科实现 — SubjectModule 注册入口。

实现 course.base 协议:
- MathKnowledgeGraph (KnowledgeGraphBase)
- MathSympyVerifier (VerifierBase)
- MathSceneCompiler (SceneCompilerBase)
- MathSocraticTutor (SocraticTutorBase)

数学专用: SymPy 符号引擎 + networkx 图谱 + 行程问题场景公式注册表。
"""

from __future__ import annotations

from ...base import (
    KnowledgeGraphBase,
    SceneCompilerBase,
    SocraticTutorBase,
    SubjectModule,
    VerifierBase,
)
from .knowledge_graph import MathKnowledgeGraph
from .problem_bank import MathProblemBank
from .scene_compiler import MathSceneCompiler
from .socratic_tutor import MathSocraticTutor
from .sympy_verifier import MathSympyVerifier


class MathSubject(SubjectModule):
    """数学学科模块。"""

    @property
    def subject_id(self) -> str:
        return "math"

    @property
    def display_name(self) -> str:
        return "数学"

    @property
    def supported_grades(self) -> tuple[int, ...]:
        return tuple(range(1, 13))

    @property
    def has_knowledge_graph(self) -> bool:
        return True

    @property
    def has_scene_compiler(self) -> bool:
        return True

    @property
    def has_socratic_tutor(self) -> bool:
        return True

    @property
    def has_verifier(self) -> bool:
        return True

    @property
    def has_problem_bank(self) -> bool:
        return True

    def init(self, mlx, content_filter, standards_query=None) -> None:
        super().init(mlx, content_filter, standards_query)
        self._verifier = MathSympyVerifier()
        self._kg = MathKnowledgeGraph()
        self._scene = MathSceneCompiler(mlx, self._verifier, content_filter)
        self._tutor = MathSocraticTutor(mlx, self._verifier, content_filter)
        self._bank = MathProblemBank()
        self._bank.load()

    def knowledge_graph(self) -> KnowledgeGraphBase | None:
        return self._kg if getattr(self, "_kg", None) else None

    def scene_compiler(self) -> SceneCompilerBase | None:
        return self._scene if getattr(self, "_scene", None) else None

    def socratic_tutor(self) -> SocraticTutorBase | None:
        return self._tutor if getattr(self, "_tutor", None) else None

    def verifier(self) -> VerifierBase | None:
        return self._verifier if getattr(self, "_verifier", None) else None

    def problem_bank(self):
        return self._bank if getattr(self, "_bank", None) else None
