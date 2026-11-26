# SubjectRegistry — subject registry + auto-discovery.
#
# The platform (engines/serve) only holds the registry, never imports concrete subject classes.
# Adding a subject:
# 1. Create the course/subjects/{subject}/ package implementing SubjectModule.
# 2. Add one line to the _BUILTIN registry in course/subjects/__init__.py.
# 3. Zero platform changes.
#
# discover_and_init iterates registered subjects, injects mlx/content_filter/standards_query and inits.
# A subject load failure does not block other subjects (loud logs; fail-fast with a contained blast radius).

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


# Subject registry — the key to platform/content decoupling.
class SubjectRegistry:

    def __init__(self) -> None:
        self._modules: dict[str, SubjectModule] = {}
        self._mastery = MasteryTracker()

    def register(self, module: SubjectModule) -> None:
        if module.subject_id in self._modules:
            logger.warning("subject_registry: subject %s already registered, overwriting", module.subject_id)
        self._modules[module.subject_id] = module
        logger.info("subject_registry: registered subject %s (%s)", module.subject_id, module.display_name)

    def get(self, subject_id: str) -> SubjectModule:
        mod = self._modules.get(subject_id)
        if mod is None:
            raise SubjectNotFoundError(f"subject not registered: {subject_id}")
        return mod

    def list_subjects(self) -> list[SubjectModule]:
        return list(self._modules.values())

    def manifests(self) -> list[dict[str, Any]]:
        return [m.to_manifest() for m in self._modules.values()]

    @property
    def mastery(self) -> MasteryTracker:
        return self._mastery

    # Auto-discover and initialize built-in subjects. One subject failing does not block others.
    def discover_and_init(
        self, mlx: MLXClient, content_filter: ContentFilter,
        standards_query: StandardsQuery | None = None,
    ) -> None:
        from .subjects import get_builtin_subjects
        for module_cls in get_builtin_subjects():
            try:
                module = module_cls()
                module.init(mlx=mlx, content_filter=content_filter, standards_query=standards_query)
                # Each subject loads its knowledge graph on demand (fail-fast but isolated)
                kg = module.knowledge_graph() if module.has_knowledge_graph else None
                if kg is not None:
                    try:
                        kg.load(standards_query=standards_query)
                    except Exception as exc:
                        logger.error("subject_registry: subject %s knowledge graph load failed: %s (this subject's graph unavailable, other features unaffected)", module.subject_id, exc)
                        # Graph down but module still registered (degraded); router checks None and returns 501
                self.register(module)
            except Exception as exc:
                logger.error("subject_registry: subject %s init failed: %s (skipped, not blocking other subjects)", getattr(module_cls, "subject_id", "?"), exc)
