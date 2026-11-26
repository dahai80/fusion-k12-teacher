# Educational content generator — slides, worksheets, flashcards, educational games.

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .._parse import parse_json
from ..ai_client import MLXClient
from ..errors import rethrow_if_fatal
from ..safety.filter import ContentFilter, sanitize_input

logger = logging.getLogger(__name__)

_MAX_STR_FIELD = 5000
_MAX_LIST_ITEMS = 50
_PARENT_COMM_MAX = 4000
_GAME_KEYS = ("title", "type", "objective", "rules", "materials",
              "duration", "setup", "variations", "debrief")


def _bound_str(val: Any) -> str:
    s = str(val) if val is not None else ""
    return s[:_MAX_STR_FIELD]


def _bound_str_list(val: Any) -> list[str]:
    if not isinstance(val, list):
        return []
    return [_bound_str(x) for x in val[:_MAX_LIST_ITEMS]]


# Worksheet / exercise book.
@dataclass
class Worksheet:
    title: str = ""
    subject: str = ""
    grade: str = ""
    sections: list[dict[str, Any]] = field(default_factory=list)
    answer_key: str = ""
    instructions: str = ""
    error: str = ""


# Educational content generator — teaching material production on par with Claude K-12 Teacher.
class ContentGenerator:

    def __init__(self, mlx: MLXClient | None = None, content_filter: ContentFilter | None = None):
        self.mlx = mlx or MLXClient()
        self._filter = content_filter or ContentFilter()

    # SEC-4: generated content passes safety.check_output before reaching
    #         students, replaced with mask and warned on hit.
    def _filter_output(self, text: str, grade: str) -> str:
        if not isinstance(text, str) or not text:
            return text
        check = self._filter.check_output(text, grade)
        if not check.is_safe:
            logger.warning("Unsafe generated content detected, filtered: %s", check.summary)
            return check.filtered_text
        return text

    # Generate a worksheet / exercise book.
    async def generate_worksheet(self, subject: str, grade: str, topic: str, num_questions: int = 10) -> Worksheet:
        subject_s = sanitize_input(subject, 20)
        grade_s = sanitize_input(grade, 4)
        topic_s = sanitize_input(topic)
        # i18n: user-facing — LLM prompt template (product content), keep Chinese.
        prompt = f"""为{grade_s}年级{subject_s}学科生成一份关于"{topic_s}"的练习题工作纸。

题目数量: {num_questions}

返回JSON: {{"title": "标题", "instructions": "答题说明", "sections": [{{"title": "板块名", "questions": [{{"question": "题目", "type": "题型", "points": 分值}}]}}], "answer_key": "答案"}}"""
        try:
            # i18n: user-facing — LLM system prompt (product content), keep Chinese.
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位教材编写专家，设计高质量的练习题。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            data = self._parse_json(response)
            if isinstance(data, dict):
                instructions = self._filter_output(_bound_str(data.get("instructions", "")), grade_s)
                answer_key = self._filter_output(_bound_str(data.get("answer_key", "")), grade_s)
                sections = []
                raw_sections = data.get("sections", []) if isinstance(data.get("sections"), list) else []
                for sec in raw_sections[:_MAX_LIST_ITEMS] if isinstance(raw_sections, list) else []:
                    if not isinstance(sec, dict):
                        continue
                    q_list = sec.get("questions", [])
                    filtered_q = []
                    if isinstance(q_list, list):
                        for q in q_list[:_MAX_LIST_ITEMS]:
                            if isinstance(q, dict) and "question" in q:
                                q = dict(q)
                                q["question"] = self._filter_output(_bound_str(q.get("question", "")), grade_s)
                            filtered_q.append(q)
                    # ENG-16: whitelist section keys, bound title, do not
                    # expand arbitrary LLM keys
                    sections.append({
                        "title": self._filter_output(_bound_str(sec.get("title", "")), grade_s),
                        "questions": filtered_q,
                    })
                return Worksheet(
                    # i18n: user-facing — default title shown to users, keep Chinese.
                    title=_bound_str(data.get("title", f"{topic_s}练习")),
                    subject=subject_s, grade=grade_s,
                    sections=sections,
                    answer_key=answer_key,
                    instructions=instructions,
                )
            logger.error("Worksheet generation failed: LLM returned empty or unparseable output")
            # i18n: user-facing — default title shown to users, keep Chinese.
            return Worksheet(title=f"{topic_s}练习", subject=subject_s, grade=grade_s, error="LLM returned empty or unparseable output")
        except Exception as e:
            logger.error(f"Worksheet generation failed: {e}")
            rethrow_if_fatal(e)
            # i18n: user-facing — default title shown to users, keep Chinese.
            return Worksheet(title=f"{topic_s}练习", subject=subject_s, grade=grade_s, error=str(e))

    # Generate flashcards.
    async def generate_flashcards(self, subject: str, grade: str, topic: str, count: int = 10) -> list[dict[str, str]]:
        subject_s = sanitize_input(subject, 20)
        grade_s = sanitize_input(grade, 4)
        topic_s = sanitize_input(topic)
        # i18n: user-facing — LLM prompt template (product content), keep Chinese.
        prompt = f"""为{grade_s}年级{subject_s}学科关于"{topic_s}"生成{count}张学习闪卡。

返回JSON数组，每项包含：front(正面), back(背面), hint(提示)"""
        try:
            # i18n: user-facing — LLM system prompt (product content), keep Chinese.
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位教学设计师，制作有效的学习闪卡。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            data = self._parse_json(response)
            if isinstance(data, list):
                # ENG-12: card content reaches students directly, every field
                # passes _filter_output
                out = []
                for item in data[:_MAX_LIST_ITEMS]:
                    if not isinstance(item, dict):
                        continue
                    card = {
                        k: self._filter_output(_bound_str(item.get(k, "")), grade_s)
                        for k in ("front", "back", "hint")
                    }
                    out.append(card)
                return out
            logger.error("Flashcard generation failed: LLM returned empty or unparseable output")
            return []
        except Exception as e:
            logger.error(f"Flashcard generation failed: {e}")
            rethrow_if_fatal(e)
            return []

    # Generate a slide deck outline.
    async def generate_lesson_slides(self, subject: str, grade: str, topic: str, num_slides: int = 8) -> list[dict[str, str]]:
        subject_s = sanitize_input(subject, 20)
        grade_s = sanitize_input(grade, 4)
        topic_s = sanitize_input(topic)
        # i18n: user-facing — LLM prompt template (product content), keep Chinese.
        prompt = f"""为{grade_s}年级{subject_s}学科关于"{topic_s}"设计{num_slides}页课件大纲。

返回JSON数组，每项包含：slide_number, title, content, teacher_notes, visual_suggestion"""
        try:
            # i18n: user-facing — LLM system prompt (product content), keep Chinese.
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位课件设计专家，制作结构清晰、视觉美观的课件。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            data = self._parse_json(response)
            if isinstance(data, list):
                # ENG-12: slide content reaches students directly, text fields
                # pass _filter_output
                out = []
                for item in data[:_MAX_LIST_ITEMS]:
                    if not isinstance(item, dict):
                        continue
                    slide = {}
                    for k in ("slide_number", "title", "content", "teacher_notes", "visual_suggestion"):
                        slide[k] = self._filter_output(_bound_str(item.get(k, "")), grade_s)
                    out.append(slide)
                return out
            logger.error("Slide outline generation failed: LLM returned empty or unparseable output")
            return []
        except Exception as e:
            logger.error(f"Slide outline generation failed: {e}")
            rethrow_if_fatal(e)
            return []

    # Generate an educational game design — whitelisted schema + bounded
    #         lengths (CNT-1).
    async def generate_educational_game(self, subject: str, grade: str, topic: str, game_type: str = "quiz") -> dict[str, Any]:
        subject_s = sanitize_input(subject, 20)
        grade_s = sanitize_input(grade, 4)
        topic_s = sanitize_input(topic)
        gt_s = sanitize_input(game_type, 30)
        # i18n: user-facing — LLM prompt template (product content), keep Chinese.
        prompt = f"""为{grade_s}年级{subject_s}学科关于"{topic_s}"设计一个{gt_s}类型的教育游戏。

返回JSON: {{"title": "游戏名", "type": "游戏类型", "objective": "学习目标", "rules": ["规则"], "materials": ["所需材料"], "duration": "时长", "setup": "准备步骤", "variations": ["变体玩法"], "debrief": "总结讨论问题"}}"""
        try:
            # i18n: user-facing — LLM system prompt (product content), keep Chinese.
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位教育游戏设计师，设计有趣又有教育意义的课堂游戏。"},
                {"role": "user", "content": prompt},
            ], temperature=0.4)
            data = self._parse_json(response)
            if isinstance(data, dict):
                # ENG-12: game content reaches students directly, text fields
                # and list items pass _filter_output
                out: dict[str, Any] = {}
                for k in _GAME_KEYS:
                    if k in ("rules", "materials", "variations"):
                        out[k] = [
                            self._filter_output(s, grade_s) for s in _bound_str_list(data.get(k, []))
                        ]
                    else:
                        out[k] = self._filter_output(_bound_str(data.get(k, "")), grade_s)
                if not out.get("title"):
                    # i18n: user-facing — default title shown to users, keep Chinese.
                    out["title"] = f"{topic_s}游戏"
                return out
            logger.error("Educational game generation failed: LLM returned empty or unparseable output")
            # i18n: user-facing — default title shown to users, keep Chinese.
            return {"title": f"{topic_s}游戏", "error": "LLM returned empty or unparseable output"}
        except Exception as e:
            logger.error(f"Educational game generation failed: {e}")
            rethrow_if_fatal(e)
            # i18n: user-facing — default title shown to users, keep Chinese.
            return {"title": f"{topic_s}游戏", "error": str(e)}

    # Generate a parent-communication letter template — content filtered +
    #         length capped, error strings never leak on failure (CNT-2/4).
    async def generate_parent_communication(self, student: str, grade: str, subject: str, topic: str) -> str:
        student_s = sanitize_input(student, 50)
        grade_s = sanitize_input(grade, 4)
        subject_s = sanitize_input(subject, 20)
        topic_s = sanitize_input(topic)
        # i18n: user-facing — LLM prompt template (product content), keep Chinese.
        prompt = f"""为{grade_s}年级学生{student_s}的家长撰写一封关于{subject_s}学科"{topic_s}"学习情况的沟通信。

要求：语气积极、具体、有建设性建议。"""
        try:
            # i18n: user-facing — LLM system prompt (product content), keep Chinese.
            raw = await self.mlx.chat([
                {"role": "system", "content": "你是一位经验丰富的教师，善于与家长沟通。"},
                {"role": "user", "content": prompt},
            ], temperature=0.5)
            if not isinstance(raw, str) or not raw.strip():
                logger.error("Parent communication letter generation failed: LLM returned empty")
                return ""
            text = raw.strip()[:_PARENT_COMM_MAX]
            check = self._filter.check_output(text, grade_s)
            if not check.is_safe:
                logger.warning("Unsafe content detected in parent communication letter, blocked: %s", check.summary)
                return ""
            return text
        except Exception as e:
            logger.error(f"Parent communication letter generation failed: {e}")
            rethrow_if_fatal(e)
            return ""

    # Parse LLM JSON — E1: converge on the single _parse.parse_json
    #         (bounded length + balanced-brace scan).
    def _parse_json(self, text: Any) -> Any:
        return parse_json(text)