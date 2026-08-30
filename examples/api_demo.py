#!/usr/bin/env python3
"""示例：通过 HTTP API 使用 fusion-k12-teacher。

P1-18: 对齐真实路由 (/curriculum/plan 等) + X-API-Key 鉴权 + 实际请求字段。
启动 serve 前设 FUSION_K12_API_KEY, 本脚本读同 env 自动带 header。
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
    logger.info("健康检查: %s", _get("health"))


def demo_lesson_plan():
    payload = {"subject": "数学", "grade": "3", "topic": "分数的初步认识"}
    result = _post("curriculum/plan", payload)
    logger.info("课程计划: 目标数=%d", len(result.get("objectives", [])))
    print(json.dumps(result, ensure_ascii=False, indent=2))


def demo_quiz():
    payload = {"subject": "语文", "grade": "5", "topic": "古诗词", "num_questions": 5}
    result = _post("curriculum/quiz", payload)
    questions = result.get("questions") or result.get("exercises", [])
    logger.info("测验: 题目数=%d", len(questions))
    print(json.dumps(result, ensure_ascii=False, indent=2))


def demo_safety_check():
    payload = {"text": "这是一段教学内容示例", "grade": "3"}
    result = _post("safety/check", payload)
    logger.info("安全检查: is_safe=%s", result.get("is_safe"))
    print(json.dumps(result, ensure_ascii=False, indent=2))


def demo_desensitize():
    records = [
        {"student_name": "张三", "phone": "13812345678", "score": 95},
        {"student_name": "李四", "phone": "13987654321", "score": 88},
    ]
    payload = {"records": records, "name_mode": "id", "id_prefix": "S"}
    result = _post("desensitize/anonymize", payload)
    logger.info("脱敏: 记录数=%d", result.get("anonymized_count", 0))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if not API_KEY:
        logger.warning("FUSION_K12_API_KEY 未设, 受保护端点将 401 (fail-closed)")
    demo_health()
    demo_lesson_plan()
    demo_quiz()
    demo_safety_check()
    demo_desensitize()
