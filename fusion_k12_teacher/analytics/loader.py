# Learning analytics data import — JSON/CSV batch loading.

from __future__ import annotations

import csv
import json
import logging
import os
from pathlib import Path
from typing import Any

from .models import StudentAssessment

logger = logging.getLogger(__name__)

_CSV_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")

# A8: load results cached by (resolved_path, mtime) — unchanged files are not re-opened+re-parsed,
# large datasets (1000+ records) would block per-request re-parsing. mtime change invalidates the cache.
_LOAD_CACHE: dict[str, tuple[float, list[StudentAssessment]]] = {}


def _cached_load(path: str | Path, parser) -> list[StudentAssessment]:
    # A8: unified cache layer — parser is the pure parsing function of load_from_json/_load_from_csv (no cache lookup).
    # mtime check: missing or unreadable files are handled by the parser returning [] (parser handles it); empty results are not cached to avoid misleading hits.
    resolved = str(Path(path).resolve())
    try:
        mtime = os.path.getmtime(resolved)
    except OSError:
        return parser(path)
    entry = _LOAD_CACHE.get(resolved)
    if entry and entry[0] == mtime:
        logger.debug("learning data cache hit: %s", resolved)
        return entry[1]
    result = parser(path)
    # only cache non-empty successful results; empty results (missing file/parse failure) are not cached, retried next time
    if result:
        _LOAD_CACHE[resolved] = (mtime, result)
    return result

# AGT-2: allowed data directories — CLI/tasks and serve share the same whitelist, blocking arbitrary path reads
def _allowed_data_dirs() -> list[Path]:
    project_root = Path(__file__).resolve().parent.parent
    return [
        (project_root / "data").resolve(),
        (project_root / "examples").resolve(),
        (Path.cwd() / "data").resolve(),
    ]


# Data path outside allowed dirs — CLI converts to click.ClickException, serve converts to HTTPException.
class DataPathError(ValueError):
    pass


# AGT-2: validates data_path is inside an allowed directory (exact is_relative_to match, not prefix).
def validate_data_path(path: str) -> Path:
    resolved = Path(path).resolve()
    for d in _allowed_data_dirs():
        try:
            if resolved.is_relative_to(d):
                return resolved
        except (ValueError, OSError):
            continue
    logger.warning("data path outside allowed dirs: %s", resolved)
    raise DataPathError(f"data path not allowed: {resolved}")


# Sanitizes a CSV cell — strips formula-injection prefixes (ENG-8).
def _sanitize_cell(val: Any) -> str:
    s = str(val) if val is not None else ""
    if s.startswith(_CSV_INJECTION_PREFIXES):
        logger.warning("CSV cell suspected formula injection, leading characters stripped: %r", s[:20])
        s = "'" + s
    return s


# Parses a numeric field — empty string returns None (distinct from a real 0), non-numeric returns default (ENG-7).
def _parse_num(val: Any, default: float = 0.0) -> float | None:
    if val is None:
        return None
    s = str(val).strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        logger.warning("numeric field is not a number, falling back to default %s: %r", default, s[:20])
        return default


# Loads learning data from a JSON file (A8: mtime cache, no re-parse while unchanged).
#
#     Supports two formats:
#     1. Array: [{student_id, ...}, ...]
#     2. Object: {assessments: [...]} or {records: [...]}
#        When the value is a dict keyed by student_id, it is auto-expanded into a record list (ENG-9).
def load_from_json(path: str | Path) -> list[StudentAssessment]:
    return _cached_load(path, _parse_json_file)


# Pure JSON file parsing (A8: wrapped by _cached_load, no cache lookup of its own).
def _parse_json_file(path: str | Path) -> list[StudentAssessment]:
    path = Path(path)
    if not path.exists():
        logger.error(f"learning data file not found: {path}")
        return []

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"learning data file read failed: {path} — {e}")
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
                logger.warning("JSON top level is a dict keyed by student_id, auto-expanded into a record list")
                raw_list = list(data.values())
    else:
        logger.error("learning data file is not list/dict structure, skipped: %s", path)
        return []

    return normalize_assessments(raw_list)


# Loads learning data from a CSV file (A8: mtime cache, no re-parse while unchanged).
#
#     Expected columns: student_id, student_name, assessment_id, date, subject, grade,
#             total_score, max_score, question_id, question, student_answer, correct_answer, points, max_points
#     Each row is one answer record, aggregated by student_id+assessment_id.
#     Empty cells are never silently zero-filled — when total_score is empty the assessment record is skipped (ENG-7).
def load_from_csv(path: str | Path) -> list[StudentAssessment]:
    return _cached_load(path, _parse_csv_file)


# Pure CSV file parsing (A8: wrapped by _cached_load, no cache lookup of its own).
def _parse_csv_file(path: str | Path) -> list[StudentAssessment]:
    path = Path(path)
    if not path.exists():
        logger.error(f"learning data file not found: {path}")
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
                        # ENG-22: drop `or 0.0` — _parse_num returns None on empty, and `None or 0.0`
                        # erases the ENG-7 empty/zero distinction (real 0 score vs unanswered). Keep None; consumers handle it.
                        "points": _parse_num(row.get("points")),
                        "max_points": _parse_num(row.get("max_points")),
                    }
                    grouped[key]["responses"].append(resp)
                except (ValueError, TypeError) as e:
                    logger.warning(f"skipping invalid CSV row: {e} — {row}")
                    continue
    except (OSError, csv.Error) as e:
        logger.error(f"CSV read failed: {path} — {e}")
        return []

    results = []
    for key, rec in grouped.items():
        if rec.pop("_total_missing", False):
            logger.warning("CSV assessment record missing total_score, skipped (no silent zero-fill): %s", key)
            continue
        results.append(rec)
    return normalize_assessments(results)


# Normalizes a list of raw dicts into StudentAssessment records.
def normalize_assessments(data: list[Any]) -> list[StudentAssessment]:
    results = []
    for item in data:
        if not isinstance(item, dict):
            logger.warning("skipping non-dict learning record: %r", type(item).__name__)
            continue
        try:
            sa = StudentAssessment.from_dict(item)
            if sa.student_id:
                results.append(sa)
            else:
                logger.warning("skipping learning record without student_id")
        except Exception as e:
            logger.warning(f"skipping invalid learning record: {e}")
    logger.info(f"learning data load complete: {len(results)} records")
    return results
