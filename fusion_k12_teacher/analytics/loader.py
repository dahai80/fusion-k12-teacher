"""学情数据导入 — JSON/CSV 批量加载。"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from .models import StudentAssessment

logger = logging.getLogger(__name__)


def load_from_json(path: str | Path) -> List[StudentAssessment]:
    """从 JSON 文件加载学情数据。

    支持两种格式:
    1. 数组: [{student_id, ...}, ...]
    2. 对象: {assessments: [{...}, ...]}
    """
    path = Path(path)
    if not path.exists():
        logger.error(f"学情文件不存在: {path}")
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"学情文件读取失败: {path} — {e}")
        return []

    raw_list = []
    if isinstance(data, list):
        raw_list = data
    elif isinstance(data, dict):
        raw_list = data.get("assessments", data.get("records", []))

    return normalize_assessments(raw_list)


def load_from_csv(path: str | Path) -> List[StudentAssessment]:
    """从 CSV 文件加载学情数据。

    期望列: student_id, student_name, assessment_id, date, subject, grade,
            total_score, max_score, question_id, question, student_answer, correct_answer, points, max_points
    每行一条答题记录，按 student_id+assessment_id 聚合。
    """
    path = Path(path)
    if not path.exists():
        logger.error(f"学情文件不存在: {path}")
        return []

    grouped: Dict[str, Dict[str, Any]] = {}
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sid = row.get("student_id", "").strip()
                aid = row.get("assessment_id", "").strip()
                key = f"{sid}::{aid}"
                if key not in grouped:
                    grouped[key] = {
                        "student_id": sid,
                        "student_name": row.get("student_name", ""),
                        "assessment_id": aid,
                        "date": row.get("date", ""),
                        "subject": row.get("subject", ""),
                        "grade": row.get("grade", ""),
                        "total_score": float(row.get("total_score", 0)),
                        "max_score": float(row.get("max_score", 100)),
                        "responses": [],
                    }
                resp = {
                    "question_id": row.get("question_id", ""),
                    "question": row.get("question", ""),
                    "student_answer": row.get("student_answer", ""),
                    "correct_answer": row.get("correct_answer", ""),
                    "points": float(row.get("points", 0)),
                    "max_points": float(row.get("max_points", 0)),
                }
                grouped[key]["responses"].append(resp)
    except (OSError, csv.Error, ValueError) as e:
        logger.error(f"CSV 读取失败: {path} — {e}")
        return []

    return normalize_assessments(list(grouped.values()))


def normalize_assessments(data: List[Dict[str, Any]]) -> List[StudentAssessment]:
    """将原始字典列表标准化为 StudentAssessment 列表。"""
    results = []
    for item in data:
        try:
            sa = StudentAssessment.from_dict(item)
            if sa.student_id:
                results.append(sa)
        except Exception as e:
            logger.warning(f"跳过无效学情记录: {e}")
    logger.info(f"学情数据加载完成: {len(results)} 条")
    return results
