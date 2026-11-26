#!/usr/bin/env python3
# Example: batch-generate lesson plans for different subjects
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

    # i18n: user-facing (subject names and teaching topics, LLM inputs)
    subjects = [
        ("数学", 3, "分数的初步认识"),
        ("语文", 5, "古诗词三首"),
        ("英语", 7, "Present Perfect Tense"),
        ("物理", 10, "牛顿第二定律"),
    ]

    for subject, grade, topic in subjects:
        logger.info("Generating lesson plan: %s grade %d %s", subject, grade, topic)
        result = await engine.generate_lesson_plan(subject, grade, topic)
        logger.info("Done: %s — objectives=%d", topic, len(result.objectives))
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        print("---")


if __name__ == "__main__":
    asyncio.run(main())
