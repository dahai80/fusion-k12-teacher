"""学科实现包 — 各学科 SubjectModule 在此注册。

加学科流程:
1. 新建 subjects/{subject_id}/ 包, 实现 SubjectModule (继承 course.base.SubjectModule)。
2. 在下方 _BUILTIN 注册表加一行。
3. 平台 (engines/serve/gui) 零改。

当前已注册: math。规划中: physics / chemistry / english / chinese。
"""

from __future__ import annotations

from ..base import SubjectModule


def get_builtin_subjects() -> list[type[SubjectModule]]:
    """返回内置学科模块类列表。import 在函数内, 避免平台层硬依赖具体学科。"""
    subjects: list[type[SubjectModule]] = []
    try:
        from .math import MathSubject
        subjects.append(MathSubject)
    except ImportError as exc:
        import logging
        logging.getLogger(__name__).warning("subjects: math 学科导入失败: %s", exc)
    return subjects
