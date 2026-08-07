from __future__ import annotations

from typing import Any

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
