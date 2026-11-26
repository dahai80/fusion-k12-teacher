#!/usr/bin/env python3
"""Example: using fusion-k12-teacher over the HTTP API.

P1-18: aligned with real routes (/curriculum/plan etc.) + X-API-Key auth + actual request fields.
Set FUSION_K12_API_KEY before starting serve; this script reads the same env and attaches the header automatically.
"""
import json
import logging
import os

import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE = "http://localhost:11448/api"
API_KEY = os.environ.get("FUSION_K12_API_KEY", "")
HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}


def _post(path: str, payload: dict) -> dict:
    resp = requests.post(f"{BASE}/{path}", json=payload, headers=HEADERS, timeout=120)
    resp.raise_for_status()
    return resp.json()


def _get(path: str) -> dict:
    resp = requests.get(f"{BASE}/{path}", headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def demo_health():
    logger.info("health check: %s", _get("health"))


def demo_lesson_plan():
    # i18n: user-facing
    payload = {"subject": "数学", "grade": "3", "topic": "分数的初步认识"}
    result = _post("curriculum/plan", payload)
    logger.info("lesson plan: objectives=%d", len(result.get("objectives", [])))
    print(json.dumps(result, ensure_ascii=False, indent=2))


def demo_quiz():
    # i18n: user-facing
    payload = {"subject": "语文", "grade": "5", "topic": "古诗词", "num_questions": 5}
    result = _post("curriculum/quiz", payload)
    questions = result.get("questions") or result.get("exercises", [])
    logger.info("quiz: questions=%d", len(questions))
    print(json.dumps(result, ensure_ascii=False, indent=2))


def demo_safety_check():
    # i18n: user-facing
    payload = {"text": "这是一段教学内容示例", "grade": "3"}
    result = _post("safety/check", payload)
    logger.info("safety check: is_safe=%s", result.get("is_safe"))
    print(json.dumps(result, ensure_ascii=False, indent=2))


def demo_desensitize():
    # i18n: user-facing
    records = [
        {"student_name": "张三", "phone": "13812345678", "score": 95},
        {"student_name": "李四", "phone": "13987654321", "score": 88},
    ]
    payload = {"records": records, "name_mode": "id", "id_prefix": "S"}
    result = _post("desensitize/anonymize", payload)
    logger.info("desensitize: records=%d", result.get("anonymized_count", 0))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if not API_KEY:
        logger.warning("FUSION_K12_API_KEY not set, protected endpoints will 401 (fail-closed)")
    demo_health()
    demo_lesson_plan()
    demo_quiz()
    demo_safety_check()
    demo_desensitize()
