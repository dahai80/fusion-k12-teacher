"""E2/E3 课程包打包器 — 教案+课件+测验+脚本 → class_id + 6 位课堂码, SQLite 持久化。

课堂码: 6 位数字, 唯一性靠 store code UNIQUE 约束 + 重试。
"""

from __future__ import annotations

import logging
import random

from .models import CoursePackage, new_id, now_ts
from .store import ClassroomStore

logger = logging.getLogger(__name__)

_CODE_LEN = 6
_CODE_MAX_RETRY = 10


class Packager:
    def __init__(self, store: ClassroomStore) -> None:
        self.store = store

    def pack(
        self, subject: str, grade: str, topic: str,
        lesson_plan: dict | None = None, slides: list | None = None,
        quiz: dict | None = None, script: dict | None = None,
        material_flags: dict | bool | None = None,
    ) -> CoursePackage:
        code = self._gen_unique_code()
        class_id = new_id("cls_")
        flags = material_flags if isinstance(material_flags, dict) else {
            "lesson_plan": bool(lesson_plan), "slides": bool(slides),
            "quiz": bool(quiz), "script": bool(script),
        }
        pkg = CoursePackage(
            class_id=class_id, code=code, subject=subject, grade=grade, topic=topic,
            lesson_plan=lesson_plan or {}, slides=slides or [],
            quiz=quiz or {}, script=script or {},
            created_at=now_ts(), material_flags=flags,
        )
        self.store.save_package(pkg.to_dict())
        logger.info("packager: 打包 class_id=%s code=%s topic=%s", class_id, code, topic)
        return pkg

    def get_by_code(self, code: str) -> CoursePackage | None:
        data = self.store.get_package_by_code(code)
        return self._hydrate(data)

    def get_by_id(self, class_id: str) -> CoursePackage | None:
        data = self.store.get_package_by_id(class_id)
        return self._hydrate(data)

    def list_all(self) -> list[CoursePackage]:
        return [self._hydrate(d) for d in self.store.list_packages() if d]

    def _hydrate(self, data: dict | None) -> CoursePackage | None:
        if not data:
            return None
        return CoursePackage(
            class_id=data.get("class_id", ""), code=data.get("code", ""),
            subject=data.get("subject", ""), grade=data.get("grade", ""),
            topic=data.get("topic", ""),
            lesson_plan=data.get("lesson_plan", {}), slides=data.get("slides", []),
            quiz=data.get("quiz", {}), script=data.get("script", {}),
            created_at=data.get("created_at", 0.0),
            material_flags=data.get("material_flags", {}),
        )

    def _gen_unique_code(self) -> str:
        for _ in range(_CODE_MAX_RETRY):
            code = "".join(str(random.randint(0, 9)) for _ in range(_CODE_LEN))
            if not self.store.get_package_by_code(code):
                return code
        # 极小概率冲突, 放宽用 class_id 后缀
        return new_id("")[-_CODE_LEN:]
