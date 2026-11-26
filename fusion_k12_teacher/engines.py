# Engine factory — builds all engine instances uniformly for cli/serve, avoiding duplicated DI wiring.

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from .ai_client import MLXClient
from .analytics import AnalyticsEngine
from .assessment import AssessmentEngine
from .content import ContentGenerator
from .course.registry import SubjectRegistry
from .curriculum import CurriculumEngine
from .differentiation import DifferentiationEngine
from .personalization import PersonalizationEngine
from .safety import ContentFilter
from .standards import StandardsLoader, StandardsQuery
from .subjects import SubjectExpert

logger = logging.getLogger(__name__)

# issue #14: fire-and-forget tasks must hold a strong reference, otherwise the event loop only
# keeps a weak reference and they can be GC'd.
_close_tasks: set[asyncio.Task[None]] = set()


# All engine instances + shared MLXClient + shared ContentFilter.
@dataclass
class EngineBundle:
    mlx: MLXClient
    curriculum: CurriculumEngine
    assessment: AssessmentEngine
    subjects: SubjectExpert
    personalization: PersonalizationEngine
    content: ContentGenerator
    differentiation: DifferentiationEngine
    standards_loader: StandardsLoader
    standards_query: StandardsQuery
    analytics: AnalyticsEngine
    # P1-9: expose the shared ContentFilter so serve reuses the same instance (one copy of
    # sensitive-word/age rules), instead of serve constructing its own and ending up with two
    # divergent rule sets.
    content_filter: ContentFilter = None  # type: ignore[assignment]
    # Subject course platform (PRD math-doubao decoupling): SubjectRegistry holds each subject
    # module (math/physics/...); the platform is not coupled to specific subjects — adding a
    # subject requires zero changes to engines/serve.
    subject_registry: SubjectRegistry = None  # type: ignore[assignment]


# Build all engines — single wiring point, shared by cli/serve.
#
#     model/mlx are mutually exclusive: pass mlx to reuse it, otherwise create a new one from model.
def build_engines(model: str = "", mlx: MLXClient | None = None) -> EngineBundle:
    _owns_mlx = mlx is None
    if mlx is None:
        mlx = MLXClient(model=model)
    # P3: if any step during construction raises (e.g. loader.load_all on corrupted standards),
    # the already-eagerly-created mlx httpx pool must be closed; otherwise the caller gets no
    # bundle and holds no reference → pool leak. When mlx is passed in by the caller, leave it
    # alone (the caller owns its lifecycle).
    try:
        # A6: single shared ContentFilter — unified safety filtering across 7 engines, not each
        # engine's default construction (one copy of sensitive-word/age rules).
        content_filter = ContentFilter()
        curriculum = CurriculumEngine(mlx, content_filter)
        assessment = AssessmentEngine(mlx, content_filter)
        subjects = SubjectExpert(mlx, content_filter)
        personalization = PersonalizationEngine(mlx, content_filter)
        content = ContentGenerator(mlx, content_filter)
        loader = StandardsLoader()
        loader.load_all()
        standards_query = StandardsQuery(loader)
        differentiation = DifferentiationEngine(mlx, standards_query, content_filter)
        analytics = AnalyticsEngine(mlx, standards_query, content_filter)
        # Subject course platform: SubjectRegistry auto-discovers registered subjects under course/subjects/*.
        # The platform only holds the registry and does not import concrete subjects — adding a
        # subject (physics/chemistry/...) requires zero changes to engines/serve.
        subject_registry = SubjectRegistry()
        subject_registry.discover_and_init(mlx=mlx, content_filter=content_filter, standards_query=standards_query)
    except Exception:
        if _owns_mlx:
            try:
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    _close_task = loop.create_task(mlx.close())
                    _close_tasks.add(_close_task)
                    _close_task.add_done_callback(_close_tasks.discard)
                    logger.warning("build_engines failed, scheduled async cleanup of mlx pool: %s", _close_task)
                else:
                    loop.run_until_complete(mlx.close())
            except Exception as close_exc:
                logger.warning("build_engines failed to clean up mlx pool: %s", close_exc)
        raise
    # A14: build_engines is pure construction, no longer registers the global registry as a side effect.
    # Registration and construction are separated — callers (cli/serve) explicitly call
    # register_all_engines(bundle...).
    # Previously build_engines called register_all_engines, mutating the module-level registry
    # (executor.py:61); construction and registration were coupled, tests building a bundle also
    # polluted the global, and the factory was impure. Now split apart.
    logger.info("Engines built: model=%s", mlx.model or "(auto)")
    return EngineBundle(
        mlx=mlx,
        curriculum=curriculum,
        assessment=assessment,
        subjects=subjects,
        personalization=personalization,
        content=content,
        differentiation=differentiation,
        standards_loader=loader,
        standards_query=standards_query,
        analytics=analytics,
        content_filter=content_filter,
        subject_registry=subject_registry,
    )
