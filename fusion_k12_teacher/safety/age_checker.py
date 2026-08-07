"""适龄内容审查。"""

from __future__ import annotations

import json
import logging
import os

from .models import AgeRating

logger = logging.getLogger(__name__)

DEFAULT_RATINGS_PATH = os.path.join(os.path.dirname(__file__), "data", "age_ratings.json")

GRADE_ORDER = [
    "1", "2", "3", "4", "5", "6",
    "7", "8", "9", "10", "11", "12",
]


def _grade_index(grade: str) -> int:
    try:
        return GRADE_ORDER.index(grade)
    except ValueError:
        return 0


class AgeChecker:
    """适龄内容审查 — 检查内容是否超出目标年级范围。"""

    def __init__(self, ratings_path: str = ""):
        self._path = ratings_path or DEFAULT_RATINGS_PATH
        self._ratings: dict[str, AgeRating] = {}
        self.load()

    def load(self) -> None:
        if not os.path.exists(self._path):
            logger.warning(f"适龄配置文件不存在: {self._path}")
            self._init_defaults()
            return
        with open(self._path, encoding="utf-8") as f:
            data = json.load(f)
        self._ratings = {
            g: AgeRating(**r) for g, r in data.get("ratings", {}).items()
        }
        logger.info(f"适龄配置加载: {len(self._ratings)} 个年级")

    def save(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        data = {
            "ratings": {g: r.to_dict() for g, r in self._ratings.items()}
        }
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"适龄配置保存: {len(self._ratings)} 个年级")

    def get_rating(self, grade: str) -> AgeRating:
        if grade not in self._ratings:
            return self._default_rating(grade)
        return self._ratings[grade]

    def check_content(self, text: str, grade: str) -> list[str]:
        issues = []
        rating = self.get_rating(grade)
        for restricted in rating.restricted_topics:
            if restricted in text:
                issues.append(f"受限主题: {restricted}")
        return issues

    def check_abstraction(self, abstraction: str, grade: str) -> list[str]:
        issues = []
        rating = self.get_rating(grade)
        order = {"concrete": 0, "semi-abstract": 1, "abstract": 2}
        if order.get(abstraction, 0) > order.get(rating.max_abstraction, 0):
            issues.append(
                f"抽象层级超出: {abstraction} > {rating.max_abstraction}"
            )
        return issues

    def _init_defaults(self) -> None:
        for i, g in enumerate(GRADE_ORDER):
            if i < 3:
                self._ratings[g] = AgeRating(
                    grade=g,
                    max_abstraction="concrete",
                    restricted_topics=["暴力", "死亡", "恐怖"],
                    vocabulary_level="基础",
                )
            elif i < 6:
                self._ratings[g] = AgeRating(
                    grade=g,
                    max_abstraction="semi-abstract",
                    restricted_topics=["暴力", "色情"],
                    vocabulary_level="标准",
                )
            else:
                self._ratings[g] = AgeRating(
                    grade=g,
                    max_abstraction="abstract",
                    restricted_topics=["色情"],
                    vocabulary_level="拓展",
                )
        logger.info(f"适龄默认配置初始化: {len(self._ratings)} 个年级")

    def _default_rating(self, grade: str) -> AgeRating:
        idx = _grade_index(grade)
        if idx < 3:
            return AgeRating(grade=grade, max_abstraction="concrete",
                             restricted_topics=["暴力", "死亡", "恐怖"],
                             vocabulary_level="基础")
        elif idx < 6:
            return AgeRating(grade=grade, max_abstraction="semi-abstract",
                             restricted_topics=["暴力", "色情"],
                             vocabulary_level="标准")
        return AgeRating(grade=grade, max_abstraction="abstract",
                         restricted_topics=["色情"],
                         vocabulary_level="拓展")
