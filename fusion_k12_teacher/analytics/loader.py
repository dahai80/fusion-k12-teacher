"""学情数据导入 — JSON/CSV 批量加载。"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any

from .models import StudentAssessment

logger = logging.getLogger(__name__)

_CSV_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")

# AGT-2: 数据文件允许目录 — CLI/tasks 与 serve 共用同一白名单, 杜绝任意路径读取
def _allowed_data_dirs() -> list[Path]:
    project_root = Path(__file__).resolve().parent.parent
    return [
        (project_root / "data").resolve(),
        (project_root / "examples").resolve(),
        (Path.cwd() / "data").resolve(),
    ]


class DataPathError(ValueError):
    """数据路径越界 — CLI 转 click.ClickException, serve 转 HTTPException。"""


def validate_data_path(path: str) -> Path:
    """AGT-2: 校验 data_path 在允许目录内 (is_relative_to 精确匹配, 非前缀)。"""
    resolved = Path(path).resolve()
    for d in _allowed_data_dirs():
        try:
            if resolved.is_relative_to(d):
                return resolved
        except (ValueError, OSError):
            continue
    logger.warning("data path outside allowed dirs: %s", resolved)
    raise DataPathError(f"data path not allowed: {resolved}")


def _sanitize_cell(val: Any) -> str:
    """消毒 CSV 单元格 — 剥离公式注入前缀 (ENG-8)。"""
    s = str(val) if val is not None else ""
    if s.startswith(_CSV_INJECTION_PREFIXES):
        logger.warning("CSV 单元格疑似公式注入, 已剥离前导字符: %r", s[:20])
        s = "'" + s
    return s


def _parse_num(val: Any, default: float = 0.0) -> float | None:
    """解析数值字段 — 空串返回 None(区别于真实 0), 非数返回 default (ENG-7)。"""
    if val is None:
        return None
    s = str(val).strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        logger.warning("数值字段非数字, 回退默认值 %s: %r", default, s[:20])
        return default


def load_from_json(path: str | Path) -> list[StudentAssessment]:
    """从 JSON 文件加载学情数据。

    支持两种格式:
    1. 数组: [{student_id, ...}, ...]
    2. 对象: {assessments: [...]} 或 {records: [...]}
       值为按学号键的 dict 时, 自动展开为记录列表 (ENG-9)。
    """
    path = Path(path)
    if not path.exists():
        logger.error(f"学情文件不存在: {path}")
        return []

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"学情文件读取失败: {path} — {e}")
        return []

    raw_list: list[Any] = []
    if isinstance(data, list):
        raw_list = data
    elif isinstance(data, dict):
        bucket = data.get("assessments")
        if bucket is None:
            bucket = data.get("records")
        if isinstance(bucket, list):
            raw_list = bucket
        elif isinstance(bucket, dict):
            raw_list = list(bucket.values())
        elif not bucket and data:
            top = next(iter(data.values()))
            if isinstance(top, dict):
                logger.warning("JSON 顶层为按学号键的 dict, 自动展开为记录列表")
                raw_list = list(data.values())
    else:
        logger.error("学情文件非 list/dict 结构, 跳过: %s", path)
        return []

    return normalize_assessments(raw_list)


def load_from_csv(path: str | Path) -> list[StudentAssessment]:
    """从 CSV 文件加载学情数据。

    期望列: student_id, student_name, assessment_id, date, subject, grade,
            total_score, max_score, question_id, question, student_answer, correct_answer, points, max_points
    每行一条答题记录，按 student_id+assessment_id 聚合。
    空单元格不静默零填 — total_score 空则跳过该测评记录 (ENG-7)。
    """
    path = Path(path)
    if not path.exists():
        logger.error(f"学情文件不存在: {path}")
        return []

    grouped: dict[str, dict[str, Any]] = {}
    try:
        with open(path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    sid = row.get("student_id", "").strip()
                    aid = row.get("assessment_id", "").strip()
                    key = f"{sid}::{aid}"
                    total = _parse_num(row.get("total_score"), 0.0)
                    max_s = _parse_num(row.get("max_score"), 100.0)
                    if max_s is None:
                        max_s = 100.0
                    if key not in grouped:
                        grouped[key] = {
                            "student_id": _sanitize_cell(sid),
                            "student_name": _sanitize_cell(row.get("student_name", "")),
                            "assessment_id": _sanitize_cell(aid),
                            "date": _sanitize_cell(row.get("date", "")),
                            "subject": _sanitize_cell(row.get("subject", "")),
                            "grade": _sanitize_cell(row.get("grade", "")),
                            "total_score": total if total is not None else 0.0,
                            "max_score": max_s,
                            "_total_missing": total is None,
                            "responses": [],
                        }
                    else:
                        if total is not None and grouped[key]["_total_missing"]:
                            grouped[key]["total_score"] = total
                            grouped[key]["_total_missing"] = False
                    resp = {
                        "question_id": _sanitize_cell(row.get("question_id", "")),
                        "question": _sanitize_cell(row.get("question", "")),
                        "student_answer": _sanitize_cell(row.get("student_answer", "")),
                        "correct_answer": _sanitize_cell(row.get("correct_answer", "")),
                        "points": _parse_num(row.get("points"), 0.0) or 0.0,
                        "max_points": _parse_num(row.get("max_points"), 0.0) or 0.0,
                    }
                    grouped[key]["responses"].append(resp)
                except (ValueError, TypeError) as e:
                    logger.warning(f"跳过无效 CSV 行: {e} — {row}")
                    continue
    except (OSError, csv.Error) as e:
        logger.error(f"CSV 读取失败: {path} — {e}")
        return []

    results = []
    for key, rec in grouped.items():
        if rec.pop("_total_missing", False):
            logger.warning("CSV 测评记录缺 total_score, 跳过(不静默零填): %s", key)
            continue
        results.append(rec)
    return normalize_assessments(results)


def normalize_assessments(data: list[Any]) -> list[StudentAssessment]:
    """将原始字典列表标准化为 StudentAssessment 列表。"""
    results = []
    for item in data:
        if not isinstance(item, dict):
            logger.warning("跳过非 dict 学情记录: %r", type(item).__name__)
            continue
        try:
            sa = StudentAssessment.from_dict(item)
            if sa.student_id:
                results.append(sa)
            else:
                logger.warning("跳过无 student_id 的学情记录")
        except Exception as e:
            logger.warning(f"跳过无效学情记录: {e}")
    logger.info(f"学情数据加载完成: {len(results)} 条")
    return results
