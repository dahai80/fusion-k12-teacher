from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# E8: 每个层级配置须含的键集 — 加载时校验, typo (如 excersise_count) 立即暴露,
# 不再被引擎 f-string 抛 KeyError 后被 gather 当层异常静默降级空 LayerContent。
_REQUIRED_CONFIG_KEYS = frozenset({
    "label", "vocabulary_level", "example_complexity", "exercise_count",
    "hint_density", "scaffold_steps", "extension", "max_abstraction", "prompt_modifier",
})

LEVEL_CONFIGS: dict[str, dict[str, Any]] = {
    "struggling": {
        "label": "学困生",
        "vocabulary_level": "基础",
        "example_complexity": 1,
        "exercise_count": 5,
        "hint_density": "high",
        "scaffold_steps": True,
        "extension": False,
        "max_abstraction": "concrete",
        "prompt_modifier": (
            "请用最通俗、最简单的语言讲解。"
            "多用生活中的具体例子，一步一步拆解。"
            "练习题以基础题为主，数量适中。"
            "每个步骤都要给出明确提示。"
            "不要出现任何拓展探究内容。"
        ),
    },
    "standard": {
        "label": "中等生",
        "vocabulary_level": "标准",
        "example_complexity": 2,
        "exercise_count": 8,
        "hint_density": "medium",
        "scaffold_steps": False,
        "extension": False,
        "max_abstraction": "semi-abstract",
        "prompt_modifier": (
            "请用标准教学语言讲解。"
            "例题包含基本和中等难度。"
            "练习题覆盖基础和中等难度。"
            "适当给出提示，但不必每步都给。"
            "不要出现拓展探究内容。"
        ),
    },
    "advanced": {
        "label": "优等生",
        "vocabulary_level": "拓展",
        "example_complexity": 3,
        "exercise_count": 5,
        "hint_density": "low",
        "scaffold_steps": False,
        "extension": True,
        "max_abstraction": "abstract",
        "prompt_modifier": (
            "请用更深入、更有挑战性的方式讲解。"
            "例题可以涉及复杂情境和综合应用。"
            "练习题以高难度、开放性题目为主，数量不需要太多。"
            "提示尽量少给，让学生自主思考。"
            "必须包含拓展探究内容，引导学生深入探索。"
        ),
    },
}


def _validate_level_configs() -> None:
    """E8: 加载时校验各层级配置键集完整 — typo/缺键立即抛, 不静默空层。"""
    for lvl, cfg in LEVEL_CONFIGS.items():
        missing = _REQUIRED_CONFIG_KEYS - set(cfg.keys())
        extra = set(cfg.keys()) - _REQUIRED_CONFIG_KEYS
        if missing:
            raise KeyError(
                f"LEVEL_CONFIGS[{lvl!r}] 缺键 {sorted(missing)}, 须含 {sorted(_REQUIRED_CONFIG_KEYS)}"
            )
        if extra:
            raise KeyError(
                f"LEVEL_CONFIGS[{lvl!r}] 多键 {sorted(extra)}, 未知键可能 typo"
            )
    logger.debug("LEVEL_CONFIGS 键集校验通过: %s", list(LEVEL_CONFIGS.keys()))


_validate_level_configs()
