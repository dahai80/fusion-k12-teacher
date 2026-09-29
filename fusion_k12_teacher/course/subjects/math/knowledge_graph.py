"""数学知识图谱 — networkx DAG + Tarjan 环校验 + GraphRAG 逆向归因 (PRD §3, §8)。

替代 Neo4j (上游不可改, 提 issue): networkx 纯 Python 离线, 原生 Tarjan SCC
校验 DAG, 杜绝环形追溯 UI 卡死 (PRD §3.4 环依赖防护)。

数据源: standards/data/math_g*.json knowledge_points → PRE_REQUIRES 边 (prerequisites)
+ progression_next (DERIVES_FROM)。增强节点 (Concept/Theorem/Misconception + EXEMPLIFIES/
CROSS 边) 从 data/math_enhanced.json 叠加。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ....standards.query import StandardsQuery
from ...base import KnowledgeGraphBase
from ...models import GraphNode

logger = logging.getLogger(__name__)

_EDGE_PRE = "PRE_REQUIRES"
_EDGE_DERIVE = "DERIVES_FROM"
_EDGE_EXEMPLIFIES = "EXEMPLIFIES"
_EDGE_CROSS = "CROSS_DISCIPLINE"


class MathKnowledgeGraph(KnowledgeGraphBase):
    """数学知识图谱 — 加载/校验/查询/逆向归因。fail-fast: 环依赖拒启 (PRD M6-E05)。"""

    def __init__(self) -> None:
        try:
            import networkx  # noqa: F401
            self._nx_ok = True
        except ImportError:
            self._nx_ok = False
            logger.warning("math_knowledge_graph: networkx 未安装, 图谱功能不可用")
            return
        import networkx as nx
        self._nx = nx
        self._digraph: nx.DiGraph = nx.DiGraph()
        self._nodes: dict[str, GraphNode] = {}
        self._loaded = False

    @property
    def loaded(self) -> bool:
        return self._nx_ok and self._loaded

    def load(self, standards_query: StandardsQuery | None = None) -> None:
        """从 StandardsLoader 的 knowledge_points 构建底座图 + 叠加增强节点。"""
        if not self._nx_ok:
            return
        kps: list[dict[str, Any]] = []
        if standards_query is not None:
            loader = getattr(standards_query, "loader", None) or getattr(standards_query, "_loader", None)
            stds = getattr(loader, "_standards", None) or getattr(loader, "standards", None)
            if isinstance(stds, dict):
                for std in stds.values():
                    kps.extend(self._extract_kps(std))
            elif isinstance(stds, (list, tuple)):
                for std in stds:
                    kps.extend(self._extract_kps(std))
        if not kps:
            logger.warning("math_knowledge_graph: 无课标知识点可加载")
        self.load_standards(kps)
        self._load_enhanced()
        self._loaded = True
        if not self.is_dag():
            raise ValueError("MathKnowledgeGraph: 检测到环形依赖, 拒绝启动 (PRD M6-E05) — 请修复 DAG")
        logger.info("math_knowledge_graph: 加载完成 nodes=%d edges=%d", self.node_count(), self.edge_count())

    def load_standards(self, knowledge_points: list[dict[str, Any]]) -> None:
        for kp in knowledge_points:
            nid = str(kp.get("id", ""))
            if not nid:
                continue
            node = GraphNode(
                id=nid,
                title=str(kp.get("topic") or kp.get("description", ""))[:80],
                node_type="Concept",
                stage=self._stage_for_grade(str(kp.get("grade", ""))),
                strand=str(kp.get("strand", "")),
                grade=str(kp.get("grade", "")),
                description=str(kp.get("description", "")),
                curriculum_code=str(kp.get("curriculum_code", "")),
                cognitive_level=str(kp.get("difficulty_level", "")),
                edges={
                    _EDGE_PRE: [str(p) for p in kp.get("prerequisites", [])],
                    _EDGE_DERIVE: [str(p) for p in kp.get("progression_next", [])],
                },
            )
            self._add_node(node)
        for kp in knowledge_points:
            nid = str(kp.get("id", ""))
            for pre in kp.get("prerequisites", []):
                self._digraph.add_edge(str(pre), nid, type=_EDGE_PRE)
            for nxt in kp.get("progression_next", []):
                self._digraph.add_edge(nid, str(nxt), type=_EDGE_DERIVE)

    def _load_enhanced(self) -> None:
        p = Path(__file__).parent / "data" / "math_enhanced.json"
        if not p.exists():
            logger.debug("math_knowledge_graph: 无增强文件 %s", p)
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("math_knowledge_graph: 增强 JSON 解析失败 %s: %s", p, exc)
            return
        for item in data.get("nodes", []):
            node = GraphNode(
                id=str(item.get("id", "")),
                title=str(item.get("title", "")),
                node_type=str(item.get("node_type", "Concept")),
                stage=str(item.get("stage", "")),
                strand=str(item.get("strand", "")),
                grade=str(item.get("grade", "")),
                spatial=item.get("spatial", {}),
                visual_engine=str(item.get("visual_engine", "")),
                formula=str(item.get("formula", "")),
                misconceptions=list(item.get("misconceptions", [])),
                cognitive_level=str(item.get("cognitive_level", "")),
                description=str(item.get("description", "")),
                edges=item.get("edges", {}),
            )
            self._add_node(node)
        for item in data.get("nodes", []):
            nid = str(item.get("id", ""))
            edges = item.get("edges", {})
            for tgt in edges.get(_EDGE_EXEMPLIFIES, []):
                self._digraph.add_edge(nid, str(tgt), type=_EDGE_EXEMPLIFIES)
            for tgt in edges.get(_EDGE_CROSS, []):
                self._digraph.add_edge(nid, str(tgt), type=_EDGE_CROSS)

    def _add_node(self, node: GraphNode) -> None:
        self._nodes[node.id] = node
        self._digraph.add_node(node.id)

    @staticmethod
    def _extract_kps(std: Any) -> list[dict[str, Any]]:
        """从单个课标提取 knowledge_points — 兼容 dict 和 CurriculumStandard dataclass。"""
        if std is None:
            return []
        kps = getattr(std, "knowledge_points", None) if not isinstance(std, dict) else std.get("knowledge_points")
        if not isinstance(kps, list):
            return []
        out: list[dict[str, Any]] = []
        for kp in kps:
            if isinstance(kp, dict):
                out.append(kp)
            else:
                # KnowledgePoint dataclass → dict
                out.append({f: getattr(kp, f, "") for f in ("id", "subject", "grade", "strand", "topic", "description", "prerequisites", "progression_next", "difficulty_level", "curriculum_code")})
        return out

    def is_dag(self) -> bool:
        if not self._nx_ok:
            return True
        return self._nx.is_directed_acyclic_graph(self._digraph)

    def strongly_connected_components(self) -> list[list[str]]:
        if not self._nx_ok:
            return []
        return [list(c) for c in self._nx.strongly_connected_components(self._digraph) if len(c) > 1]

    def get_node(self, node_id: str) -> GraphNode | None:
        return self._nodes.get(node_id)

    def query(self, **filters: Any) -> list[GraphNode]:
        stage = filters.get("stage")
        strand = filters.get("strand")
        grade = filters.get("grade")
        node_type = filters.get("node_type")
        out: list[GraphNode] = []
        for n in self._nodes.values():
            if stage and n.stage and n.stage != stage:
                continue
            if strand and n.strand and n.strand != strand:
                continue
            if grade and n.grade and n.grade != grade:
                continue
            if node_type and n.node_type != node_type:
                continue
            out.append(n)
        return out

    def reverse_attribution(self, node_id: str, max_depth: int = 3) -> list[str]:
        if not self._nx_ok or node_id not in self._nodes:
            return []
        visited: list[str] = []
        seen = {node_id}
        frontier = [node_id]
        for _ in range(max_depth):
            nxt: list[str] = []
            for cur in frontier:
                for pre in self._pre_requires(cur):
                    if pre not in seen:
                        seen.add(pre)
                        nxt.append(pre)
                        visited.append(pre)
            frontier = nxt
            if not frontier:
                break
        return visited

    def _pre_requires(self, node_id: str) -> list[str]:
        out: list[str] = []
        for pre in self._digraph.predecessors(node_id):
            edata = self._digraph.get_edge_data(pre, node_id) or {}
            if edata.get("type") == _EDGE_PRE:
                out.append(pre)
        return out

    def prerequisites_chain(self, node_id: str) -> list[str]:
        if not self._nx_ok:
            return []
        try:
            return list(self._nx.ancestors(self._digraph, node_id))
        except Exception:
            return []

    @staticmethod
    def _stage_for_grade(grade: str) -> str:
        try:
            g = int(grade)
        except (TypeError, ValueError):
            return ""
        if g <= 6:
            return "Primary"
        if g <= 9:
            return "Junior"
        return "Senior"

    def node_count(self) -> int:
        return len(self._nodes)

    def edge_count(self) -> int:
        return self._digraph.number_of_edges() if self._nx_ok else 0

    def to_json(self) -> dict[str, Any]:
        return {
            "node_count": self.node_count(),
            "edge_count": self.edge_count(),
            "is_dag": self.is_dag(),
            "nodes": [n.to_dict() for n in list(self._nodes.values())[:200]],
        }
