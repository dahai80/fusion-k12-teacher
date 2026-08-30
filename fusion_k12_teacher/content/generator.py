"""教育内容生成器 — 课件、工作纸、闪卡、教育游戏。"""

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


@dataclass
class Worksheet:
    """工作纸/练习册。"""
    title: str = ""
    subject: str = ""
    grade: str = ""
    sections: list[dict[str, Any]] = field(default_factory=list)
    answer_key: str = ""
    instructions: str = ""
    error: str = ""


class ContentGenerator:
    """教育内容生成器 — 对标 Claude K-12 Teacher 的教学材料制作能力。"""

    def __init__(self, mlx: MLXClient | None = None, content_filter: ContentFilter | None = None):
        self.mlx = mlx or MLXClient()
        self._filter = content_filter or ContentFilter()

    def _filter_output(self, text: str, grade: str) -> str:
        """SEC-4: 生成内容送学生前过 safety.check_output, 命中则替换掩码并告警。"""
        if not isinstance(text, str) or not text:
            return text
        check = self._filter.check_output(text, grade)
        if not check.is_safe:
            logger.warning("生成内容检出不当, 已过滤: %s", check.summary)
            return check.filtered_text
        return text

    async def generate_worksheet(self, subject: str, grade: str, topic: str, num_questions: int = 10) -> Worksheet:
        """生成工作纸/练习册。"""
        subject_s = sanitize_input(subject, 20)
        grade_s = sanitize_input(grade, 4)
        topic_s = sanitize_input(topic)
        prompt = f"""为{grade_s}年级{subject_s}学科生成一份关于"{topic_s}"的练习题工作纸。

题目数量: {num_questions}

返回JSON: {{"title": "标题", "instructions": "答题说明", "sections": [{{"title": "板块名", "questions": [{{"question": "题目", "type": "题型", "points": 分值}}]}}], "answer_key": "答案"}}"""
        try:
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
                    # ENG-16: 白名单 section 键, title 有界, 不展开 LLM 任意键
                    sections.append({
                        "title": self._filter_output(_bound_str(sec.get("title", "")), grade_s),
                        "questions": filtered_q,
                    })
                return Worksheet(
                    title=_bound_str(data.get("title", f"{topic_s}练习")),
                    subject=subject_s, grade=grade_s,
                    sections=sections,
                    answer_key=answer_key,
                    instructions=instructions,
                )
            logger.error("工作纸生成失败: LLM 返回空或无法解析")
            return Worksheet(title=f"{topic_s}练习", subject=subject_s, grade=grade_s, error="LLM 返回空或无法解析")
        except Exception as e:
            logger.error(f"工作纸生成失败: {e}")
            rethrow_if_fatal(e)
            return Worksheet(title=f"{topic_s}练习", subject=subject_s, grade=grade_s, error=str(e))

    async def generate_flashcards(self, subject: str, grade: str, topic: str, count: int = 10) -> list[dict[str, str]]:
        """生成闪卡/抽认卡。"""
        subject_s = sanitize_input(subject, 20)
        grade_s = sanitize_input(grade, 4)
        topic_s = sanitize_input(topic)
        prompt = f"""为{grade_s}年级{subject_s}学科关于"{topic_s}"生成{count}张学习闪卡。

返回JSON数组，每项包含：front(正面), back(背面), hint(提示)"""
        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位教学设计师，制作有效的学习闪卡。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            data = self._parse_json(response)
            if isinstance(data, list):
                # ENG-12: 卡片内容直达学生, 每字段过 _filter_output
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
            logger.error("闪卡生成失败: LLM 返回空或无法解析")
            return []
        except Exception as e:
            logger.error(f"闪卡生成失败: {e}")
            rethrow_if_fatal(e)
            return []

    async def generate_lesson_slides(self, subject: str, grade: str, topic: str, num_slides: int = 8) -> list[dict[str, str]]:
        """生成课件大纲。"""
        subject_s = sanitize_input(subject, 20)
        grade_s = sanitize_input(grade, 4)
        topic_s = sanitize_input(topic)
        prompt = f"""为{grade_s}年级{subject_s}学科关于"{topic_s}"设计{num_slides}页课件大纲。

返回JSON数组，每项包含：slide_number, title, content, teacher_notes, visual_suggestion"""
        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位课件设计专家，制作结构清晰、视觉美观的课件。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            data = self._parse_json(response)
            if isinstance(data, list):
                # ENG-12: 幻灯内容直达学生, 文本字段过 _filter_output
                out = []
                for item in data[:_MAX_LIST_ITEMS]:
                    if not isinstance(item, dict):
                        continue
                    slide = {}
                    for k in ("slide_number", "title", "content", "teacher_notes", "visual_suggestion"):
                        slide[k] = self._filter_output(_bound_str(item.get(k, "")), grade_s)
                    out.append(slide)
                return out
            logger.error("课件大纲生成失败: LLM 返回空或无法解析")
            return []
        except Exception as e:
            logger.error(f"课件大纲生成失败: {e}")
            rethrow_if_fatal(e)
            return []

    async def generate_educational_game(self, subject: str, grade: str, topic: str, game_type: str = "quiz") -> dict[str, Any]:
        """生成教育游戏设计 — 白名单 schema + 有界长度 (CNT-1)。"""
        subject_s = sanitize_input(subject, 20)
        grade_s = sanitize_input(grade, 4)
        topic_s = sanitize_input(topic)
        gt_s = sanitize_input(game_type, 30)
        prompt = f"""为{grade_s}年级{subject_s}学科关于"{topic_s}"设计一个{gt_s}类型的教育游戏。

返回JSON: {{"title": "游戏名", "type": "游戏类型", "objective": "学习目标", "rules": ["规则"], "materials": ["所需材料"], "duration": "时长", "setup": "准备步骤", "variations": ["变体玩法"], "debrief": "总结讨论问题"}}"""
        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位教育游戏设计师，设计有趣又有教育意义的课堂游戏。"},
                {"role": "user", "content": prompt},
            ], temperature=0.4)
            data = self._parse_json(response)
            if isinstance(data, dict):
                # ENG-12: 游戏内容直达学生, 文本与列表项过 _filter_output
                out: dict[str, Any] = {}
                for k in _GAME_KEYS:
                    if k in ("rules", "materials", "variations"):
                        out[k] = [
                            self._filter_output(s, grade_s) for s in _bound_str_list(data.get(k, []))
                        ]
                    else:
                        out[k] = self._filter_output(_bound_str(data.get(k, "")), grade_s)
                if not out.get("title"):
                    out["title"] = f"{topic_s}游戏"
                return out
            logger.error("教育游戏生成失败: LLM 返回空或无法解析")
            return {"title": f"{topic_s}游戏", "error": "LLM 返回空或无法解析"}
        except Exception as e:
            logger.error(f"教育游戏生成失败: {e}")
            rethrow_if_fatal(e)
            return {"title": f"{topic_s}游戏", "error": str(e)}

    async def generate_parent_communication(self, student: str, grade: str, subject: str, topic: str) -> str:
        """生成家校沟通模板 — 经内容过滤 + 长度上限, 失败不外泄错误串 (CNT-2/4)。"""
        student_s = sanitize_input(student, 50)
        grade_s = sanitize_input(grade, 4)
        subject_s = sanitize_input(subject, 20)
        topic_s = sanitize_input(topic)
        prompt = f"""为{grade_s}年级学生{student_s}的家长撰写一封关于{subject_s}学科"{topic_s}"学习情况的沟通信。

要求：语气积极、具体、有建设性建议。"""
        try:
            raw = await self.mlx.chat([
                {"role": "system", "content": "你是一位经验丰富的教师，善于与家长沟通。"},
                {"role": "user", "content": prompt},
            ], temperature=0.5)
            if not isinstance(raw, str) or not raw.strip():
                logger.error("家校沟通信生成失败: LLM 返回空")
                return ""
            text = raw.strip()[:_PARENT_COMM_MAX]
            check = self._filter.check_output(text, grade_s)
            if not check.is_safe:
                logger.warning("家校沟通信检出不当内容, 已拦截: %s", check.summary)
                return ""
            return text
        except Exception as e:
            logger.error(f"家校沟通信生成失败: {e}")
            rethrow_if_fatal(e)
            return ""

    def _parse_json(self, text: Any) -> Any:
        """解析 LLM JSON — E1: 收敛至单一 _parse.parse_json (有界长度+平衡扫描)。"""
        return parse_json(text)