"""SubjectRegistry — 学科注册表 + 自动发现。

平台 (engines/serve) 只持 registry, 不 import 学科具体类。加学科:
1. 新建 course/subjects/{subject}/ 包, 实现 SubjectModule。
2. 在 course/subjects/__init__.py 的 _BUILTIN 注册表加一行。
3. 平台零改。

discover_and_init 自动遍历已注册学科, 注入 mlx/content_filter/standards_query 并 init。
学科加载失败不阻塞其他学科 (loud 日志, 沿 fail-fast 但隔离爆炸半径)。
"""

from __future__ import annotations

import logging
from typing import Any

from ..ai_client import MLXClient
from ..safety.filter import ContentFilter
from ..standards.query import StandardsQuery
from .base import SubjectModule
from .mastery import MasteryTracker

logger = logging.getLogger(__name__)


class SubjectNotFoundError(Exception):
    pass


class SubjectRegistry:
    """学科注册表 — 平台与内容解耦的关键。"""

    def __init__(self) -> None:
        self._modules: dict[str, SubjectModule] = {}
        self._mastery = MasteryTracker()

    def register(self, module: SubjectModule) -> None:
        if module.subject_id in self._modules:
            logger.warning("subject_registry: 学科 %s 已注册, 覆盖", module.subject_id)
        self._modules[module.subject_id] = module
        logger.info("subject_registry: 注册学科 %s (%s)", module.subject_id, module.display_name)

    def get(self, subject_id: str) -> SubjectModule:
        mod = self._modules.get(subject_id)
        if mod is None:
            raise SubjectNotFoundError(f"学科未注册: {subject_id}")
        return mod

    def list_subjects(self) -> list[SubjectModule]:
        return list(self._modules.values())

    def manifests(self) -> list[dict[str, Any]]:
        return [m.to_manifest() for m in self._modules.values()]

    @property
    def mastery(self) -> MasteryTracker:
        return self._mastery

    def discover_and_init(
        self, mlx: MLXClient, content_filter: ContentFilter,
        standards_query: StandardsQuery | None = None,
    ) -> None:
        """自动发现并初始化内置学科。单学科失败不阻塞其他。"""
        from .subjects import get_builtin_subjects
        for module_cls in get_builtin_subjects():
            try:
                module = module_cls()
                module.init(mlx=mlx, content_filter=content_filter, standards_query=standards_query)
                # 各学科按需加载图谱 (fail-fast 但隔离)
                kg = module.knowledge_graph() if module.has_knowledge_graph else None
                if kg is not None:
                    try:
                        kg.load(standards_query=standards_query)
                    except Exception as exc:
                        logger.error("subject_registry: 学科 %s 图谱加载失败: %s (该学科图谱不可用, 其他功能不受影响)", module.subject_id, exc)
                        # 图谱挂掉仍注册模块 (降级), 路由侧判 None 返 501
                self.register(module)
            except Exception as exc:
                logger.error("subject_registry: 学科 %s 初始化失败: %s (跳过, 不阻塞其他学科)", getattr(module_cls, "subject_id", "?"), exc)
