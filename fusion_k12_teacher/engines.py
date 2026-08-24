"""引擎工厂 — 统一构建所有引擎实例，供 cli/serve 共用，避免重复 DI 接线。"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .agent import register_all_engines
from .ai_client import MLXClient
from .analytics import AnalyticsEngine
from .assessment import AssessmentEngine
from .content import ContentGenerator
from .curriculum import CurriculumEngine
from .differentiation import DifferentiationEngine
from .personalization import PersonalizationEngine
from .standards import StandardsLoader, StandardsQuery
from .subjects import SubjectExpert

logger = logging.getLogger(__name__)


@dataclass
class EngineBundle:
    """所有引擎实例 + 共享 MLXClient。"""
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


def build_engines(model: str = "", mlx: MLXClient | None = None) -> EngineBundle:
    """构建全部引擎 — 单一接线点，cli/serve 共用。

    model/mlx 二选一：传 mlx 则复用，否则用 model 新建。
    """
    if mlx is None:
        mlx = MLXClient(model=model)
    curriculum = CurriculumEngine(mlx)
    assessment = AssessmentEngine(mlx)
    subjects = SubjectExpert(mlx)
    personalization = PersonalizationEngine(mlx)
    content = ContentGenerator(mlx)
    loader = StandardsLoader()
    loader.load_all()
    standards_query = StandardsQuery(loader)
    differentiation = DifferentiationEngine(mlx, standards_query)
    analytics = AnalyticsEngine(mlx, standards_query)
    register_all_engines(
        curriculum=curriculum,
        assessment=assessment,
        subjects=subjects,
        personalization=personalization,
        content=content,
        differentiation=differentiation,
        analytics=analytics,
        standards_query=standards_query,
    )
    logger.info("引擎构建完成: model=%s", mlx.model or "(auto)")
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
    )
