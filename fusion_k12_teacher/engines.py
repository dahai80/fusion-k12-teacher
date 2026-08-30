"""引擎工厂 — 统一构建所有引擎实例，供 cli/serve 共用，避免重复 DI 接线。"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .ai_client import MLXClient
from .analytics import AnalyticsEngine
from .assessment import AssessmentEngine
from .content import ContentGenerator
from .curriculum import CurriculumEngine
from .differentiation import DifferentiationEngine
from .personalization import PersonalizationEngine
from .safety import ContentFilter
from .standards import StandardsLoader, StandardsQuery
from .subjects import SubjectExpert

logger = logging.getLogger(__name__)


@dataclass
class EngineBundle:
    """所有引擎实例 + 共享 MLXClient + 共享 ContentFilter。"""
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
    # P1-9: 暴露共享 ContentFilter, 供 serve 复用同实例 (敏感词/年龄规则一份),
    # 不在 serve 内再各自构造造成规则双份不同步。
    content_filter: ContentFilter = None  # type: ignore[assignment]


def build_engines(model: str = "", mlx: MLXClient | None = None) -> EngineBundle:
    """构建全部引擎 — 单一接线点，cli/serve 共用。

    model/mlx 二选一：传 mlx 则复用，否则用 model 新建。
    """
    _owns_mlx = mlx is None
    if mlx is None:
        mlx = MLXClient(model=model)
    # P3: 构造期间任一步抛错 (如 loader.load_all 课标损坏) 须关闭已 eager 建的 mlx httpx 连接池,
    # 否则调用方拿不到 bundle 也无引用 → 连接池泄漏。mlx 由调用方传入时不动 (调用方管生命周期)。
    try:
        # A6: 共享单一 ContentFilter — 7 引擎统一安全过滤, 非各自默认构造 (敏感词/年龄规则一份)。
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
    except Exception:
        if _owns_mlx:
            try:
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    _close_task = loop.create_task(mlx.close())
                    logger.warning("build_engines 失败, 已调度异步清理 mlx 连接池: %s", _close_task)
                else:
                    loop.run_until_complete(mlx.close())
            except Exception as close_exc:
                logger.warning("build_engines 失败清理 mlx 连接池失败: %s", close_exc)
        raise
    # A14: build_engines 纯构造, 不再副作用注册全局 registry。
    # 注册与构造分离 — 调用方(cli/serve)显式调 register_all_engines(bundle...)。
    # 原 build_engines 内调 register_all_engines mutate 模块级 registry(executor.py:61),
    # 构造与注册耦合, 测试建 bundle 也污染全局, 工厂非纯。现拆离。
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
        content_filter=content_filter,
    )
