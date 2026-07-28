#!/usr/bin/env python3
"""示例：批量生成不同学科的课程计划"""
import asyncio
import json
import logging

from fusion_k12_teacher.ai_client import MLXClient
from fusion_k12_teacher.curriculum.engine import CurriculumEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    mlx = MLXClient()
    engine = CurriculumEngine(mlx)

    subjects = [
        ("数学", 3, "分数的初步认识"),
        ("语文", 5, "古诗词三首"),
        ("英语", 7, "Present Perfect Tense"),
        ("物理", 10, "牛顿第二定律"),
    ]

    for subject, grade, topic in subjects:
        logger.info("生成课程计划: %s %d年级 %s", subject, grade, topic)
        result = await engine.generate_lesson_plan(subject, grade, topic)
        logger.info("完成: %s — 目标数=%d", topic, len(result.objectives))
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        print("---")


if __name__ == "__main__":
    asyncio.run(main())
