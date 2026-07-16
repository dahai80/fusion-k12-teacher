"""教育内容生成器 — 课件、工作纸、闪卡、教育游戏。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..ai_client import MLXClient

logger = logging.getLogger(__name__)


@dataclass
class Worksheet:
    """工作纸/练习册。"""
    title: str = ""
    subject: str = ""
    grade: str = ""
    sections: List[Dict[str, Any]] = field(default_factory=list)
    answer_key: str = ""
    instructions: str = ""


class ContentGenerator:
    """教育内容生成器 — 对标 Claude K-12 Teacher 的教学材料制作能力。"""

    def __init__(self, mlx: Optional[MLXClient] = None):
        self.mlx = mlx or MLXClient()

    async def generate_worksheet(self, subject: str, grade: str, topic: str, num_questions: int = 10) -> Worksheet:
        """生成工作纸/练习册。"""
        prompt = f"""为{grade}年级{subject}学科生成一份关于"{topic}"的练习题工作纸。

题目数量: {num_questions}

返回JSON: {{"title": "标题", "instructions": "答题说明", "sections": [{{"title": "板块名", "questions": [{{"question": "题目", "type": "题型", "points": 分值}}]}}], "answer_key": "答案"}}"""
        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位教材编写专家，设计高质量的练习题。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            data = self._parse_json(response)
            if data:
                return Worksheet(
                    title=data.get("title", f"{topic}练习"), subject=subject, grade=grade,
                    sections=data.get("sections", []),
                    answer_key=data.get("answer_key", ""),
                    instructions=data.get("instructions", ""),
                )
        except Exception as e:
            logger.error(f"工作纸生成失败: {e}")
        return Worksheet(title=f"{topic}练习", subject=subject, grade=grade)

    async def generate_flashcards(self, subject: str, grade: str, topic: str, count: int = 10) -> List[Dict[str, str]]:
        """生成闪卡/抽认卡。"""
        prompt = f"""为{grade}年级{subject}学科关于"{topic}"生成{count}张学习闪卡。

返回JSON数组，每项包含：front(正面), back(背面), hint(提示)"""
        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位教学设计师，制作有效的学习闪卡。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            data = self._parse_json(response)
            return data if isinstance(data, list) else []
        except Exception as e:
            return []

    async def generate_lesson_slides(self, subject: str, grade: str, topic: str, num_slides: int = 8) -> List[Dict[str, str]]:
        """生成课件大纲。"""
        prompt = f"""为{grade}年级{subject}学科关于"{topic}"设计{num_slides}页课件大纲。

返回JSON数组，每项包含：slide_number, title, content, teacher_notes, visual_suggestion"""
        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位课件设计专家，制作结构清晰、视觉美观的课件。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            data = self._parse_json(response)
            return data if isinstance(data, list) else []
        except Exception as e:
            return []

    async def generate_educational_game(self, subject: str, grade: str, topic: str, game_type: str = "quiz") -> Dict[str, Any]:
        """生成教育游戏设计。"""
        prompt = f"""为{grade}年级{subject}学科关于"{topic}"设计一个{game_type}类型的教育游戏。

返回JSON: {{"title": "游戏名", "type": "游戏类型", "objective": "学习目标", "rules": ["规则"], "materials": ["所需材料"], "duration": "时长", "setup": "准备步骤", "variations": ["变体玩法"], "debrief": "总结讨论问题"}}"""
        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位教育游戏设计师，设计有趣又有教育意义的课堂游戏。"},
                {"role": "user", "content": prompt},
            ], temperature=0.4)
            return self._parse_json(response) or {"title": f"{topic}游戏"}
        except Exception as e:
            return {"error": str(e)}

    async def generate_parent_communication(self, student: str, grade: str, subject: str, topic: str) -> str:
        """生成家校沟通模板。"""
        prompt = f"""为{grade}年级学生{student}的家长撰写一封关于{subject}学科"{topic}"学习情况的沟通信。

要求：语气积极、具体、有建设性建议。"""
        try:
            return await self.mlx.chat([
                {"role": "system", "content": "你是一位经验丰富的教师，善于与家长沟通。"},
                {"role": "user", "content": prompt},
            ], temperature=0.5)
        except Exception as e:
            return f"生成失败: {e}"

    def _parse_json(self, text: str) -> Any:
        text = text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None