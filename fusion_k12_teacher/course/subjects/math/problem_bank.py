"""数学题库加载器 — 首发火车过桥全题型 (k_12.md 收编)。

按「知识点节点 ID + 认知层级 + 错因标签」三元组打标, A/B/C 分层。
数据源: data/train_bridge_bank.json。只读加载, 提供 query/filter。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Problem:
    id: str
    kind: str = ""
    template_id: str = ""
    difficulty_layer: str = ""
    cognitive_level: str = ""
    knowledge_node_id: str = ""
    prerequisite_node_ids: list[str] = field(default_factory=list)
    misconception_tags: list[str] = field(default_factory=list)
    problem_text: str = ""
    variables: dict = field(default_factory=dict)
    expected: dict = field(default_factory=dict)
    key_cognition: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> Problem:
        return cls(
            id=str(d.get("id", "")),
            kind=str(d.get("kind", "")),
            template_id=str(d.get("template_id", "")),
            difficulty_layer=str(d.get("difficulty_layer", "")),
            cognitive_level=str(d.get("cognitive_level", "")),
            knowledge_node_id=str(d.get("knowledge_node_id", "")),
            prerequisite_node_ids=list(d.get("prerequisite_node_ids", [])),
            misconception_tags=list(d.get("misconception_tags", [])),
            problem_text=str(d.get("problem_text", "")),
            variables=dict(d.get("variables", {})),
            expected=dict(d.get("expected", {})),
            key_cognition=str(d.get("key_cognition", "")),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "template_id": self.template_id,
            "difficulty_layer": self.difficulty_layer, "cognitive_level": self.cognitive_level,
            "knowledge_node_id": self.knowledge_node_id,
            "prerequisite_node_ids": self.prerequisite_node_ids,
            "misconception_tags": self.misconception_tags,
            "problem_text": self.problem_text, "variables": self.variables,
            "expected": self.expected, "key_cognition": self.key_cognition,
        }


class MathProblemBank:
    """数学题库 — 从 JSON 加载, 内存查询。"""

    def __init__(self) -> None:
        self._problems: list[Problem] = []
        self._misconceptions: list[dict] = []
        self._formula_cheatsheet: list[dict] = []
        self._meta: dict = {}

    def load(self) -> None:
        p = Path(__file__).parent / "data" / "train_bridge_bank.json"
        if not p.exists():
            logger.warning("math_problem_bank: 题库文件不存在 %s", p)
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("math_problem_bank: JSON 解析失败 %s: %s", p, exc)
            return
        self._meta = {k: v for k, v in data.items() if k not in ("problems", "misconceptions", "formula_cheatsheet")}
        self._problems = [Problem.from_dict(d) for d in data.get("problems", [])]
        self._misconceptions = list(data.get("misconceptions", []))
        self._formula_cheatsheet = list(data.get("formula_cheatsheet", []))
        logger.info("math_problem_bank: 加载完成 problems=%d misconceptions=%d", len(self._problems), len(self._misconceptions))

    @property
    def count(self) -> int:
        return len(self._problems)

    def all(self) -> list[Problem]:
        return list(self._problems)

    def get(self, problem_id: str) -> Problem | None:
        for p in self._problems:
            if p.id == problem_id:
                return p
        return None

    def query(
        self,
        template_id: str | None = None,
        difficulty_layer: str | None = None,
        knowledge_node_id: str | None = None,
        misconception_tag: str | None = None,
        kind: str | None = None,
    ) -> list[Problem]:
        out = self._problems
        if template_id:
            out = [p for p in out if p.template_id == template_id]
        if difficulty_layer:
            out = [p for p in out if p.difficulty_layer == difficulty_layer]
        if knowledge_node_id:
            out = [p for p in out if p.knowledge_node_id == knowledge_node_id or knowledge_node_id in p.prerequisite_node_ids]
        if misconception_tag:
            out = [p for p in out if misconception_tag in p.misconception_tags]
        if kind:
            out = [p for p in out if p.kind == kind]
        return list(out)

    def misconceptions(self) -> list[dict]:
        return list(self._misconceptions)

    def formula_cheatsheet(self) -> list[dict]:
        return list(self._formula_cheatsheet)

    def to_manifest(self) -> dict:
        return {
            "count": self.count,
            "misconceptions": self._misconceptions,
            "formula_cheatsheet": self._formula_cheatsheet,
            "meta": self._meta,
        }
