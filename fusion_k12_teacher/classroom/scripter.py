"""E1 讲课脚本生成器 — 教案/主题 → 逐页讲稿 (narration + 提问点 + emotion_tag)。

K1 文字版: 复用 CurriculumEngine.lesson_plan / ContentGenerator.lesson_slides 作输入,
LLM 按页生成讲解词。失败降级: 用 lesson_plan.sections 直接切页, 不阻塞课堂。
"""

from __future__ import annotations

import logging
from typing import Any

from .._parse import parse_json
from ..ai_client import MLXClient
from ..safety.filter import sanitize_input
from .models import LessonScript, ScriptPage, new_id

logger = logging.getLogger(__name__)

_SCRIPT_PROMPT = """你是 K12 课堂讲课脚本生成器。将教案转为逐页讲课脚本 (JSON)。

输入教案: {lesson_input}
课题: {topic}  学科: {subject}  年级: {grade}

输出 JSON (仅 JSON, 无 markdown):
{{
  "pages": [
    {{
      "page_index": 0,
      "title": "页面标题",
      "narration": "老师讲课口语化讲解词, 80-150字, 引导学生思考",
      "slide_content": "该页课件要点 (简短)",
      "question_point": {{"prompt": "随堂提问", "type": "multiple_choice|numeric|open", "options": ["A","B","C","D"], "answer": "B", "explanation": "一句话讲解"}},
      "emotion_tag": "neutral|happy|curious|encouraging"
    }}
  ]
}}
要求: 3-6 页; 每页有讲解词; 至少 2 页含 question_point; 语气亲切苏格拉底式。"""


class LessonScripter:
    def __init__(self, mlx: MLXClient) -> None:
        self.mlx = mlx

    async def generate(
        self, subject: str, grade: str, topic: str,
        lesson_plan: dict[str, Any] | None = None,
    ) -> LessonScript:
        sid = new_id("scr_")
        topic_s = sanitize_input(topic)[:100]
        lesson_input = "无教案, 即时生成" if not lesson_plan else str(lesson_plan)[:2000]
        script = LessonScript(script_id=sid, subject=subject, grade=grade, topic=topic_s)
        try:
            prompt = _SCRIPT_PROMPT.format(
                lesson_input=lesson_input, topic=topic_s, subject=subject, grade=grade,
            )
            resp = await self.mlx.chat(
                [{"role": "user", "content": prompt}], temperature=0.4, max_tokens=4096,
            )
            data = parse_json(resp) or {}
            pages_raw = data.get("pages", [])
            if not isinstance(pages_raw, list) or not pages_raw:
                script.error = "LLM 返回无 pages, 降级切页"
                return self._fallback(script, lesson_plan)
            for i, p in enumerate(pages_raw):
                if not isinstance(p, dict):
                    continue
                qp = p.get("question_point", {})
                if not isinstance(qp, dict):
                    qp = {}
                script.pages.append(ScriptPage(
                    page_index=i,
                    title=str(p.get("title", f"第{i+1}页"))[:80],
                    narration=str(p.get("narration", ""))[:600],
                    slide_content=str(p.get("slide_content", ""))[:300],
                    question_point=qp,
                    emotion_tag=str(p.get("emotion_tag", "neutral"))[:20],
                ))
            logger.info("scripter: topic=%s pages=%d", topic_s, len(script.pages))
            if not script.pages:
                script.error = "解析后无有效页"
                return self._fallback(script, lesson_plan)
            return script
        except Exception as exc:
            logger.warning("scripter 生成失败 topic=%s: %s", topic_s, exc)
            script.error = f"讲稿生成失败: {exc}"
            return self._fallback(script, lesson_plan)

    def _fallback(self, script: LessonScript, lesson_plan: dict[str, Any] | None) -> LessonScript:
        sections = (lesson_plan or {}).get("sections", []) if lesson_plan else []
        if not sections:
            script.pages = [ScriptPage(
                page_index=0, title=script.topic,
                narration=f"今天我们学习{script.topic}。请大家先思考: 这个知识点在生活中哪里用到?",
                slide_content=script.topic, emotion_tag="curious",
            )]
            return script
        for i, sec in enumerate(sections):
            if not isinstance(sec, dict):
                continue
            script.pages.append(ScriptPage(
                page_index=i,
                title=str(sec.get("title", f"第{i+1}节"))[:80],
                narration=str(sec.get("content", str(sec)))[:500],
                slide_content=str(sec.get("title", ""))[:200],
                emotion_tag="neutral",
            ))
        logger.info("scripter: 降级切页 pages=%d", len(script.pages))
        return script
