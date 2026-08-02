#!/usr/bin/env python3
"""示例：通过 HTTP API 使用 fusion-k12-teacher"""
import json
import logging

import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE = "http://localhost:11448/api"


def demo_health():
    resp = requests.get(f"{BASE}/health")
    logger.info("健康检查: %s", resp.json())


def demo_lesson_plan():
    payload = {"subject": "数学", "grade": 3, "topic": "分数的初步认识"}
    resp = requests.post(f"{BASE}/lesson/plan", json=payload)
    result = resp.json()
    logger.info("课程计划: 目标数=%d", len(result.get("objectives", [])))
    print(json.dumps(result, ensure_ascii=False, indent=2))


def demo_quiz():
    payload = {"subject": "语文", "grade": 5, "topic": "古诗词", "num_questions": 5}
    resp = requests.post(f"{BASE}/assess/quiz", json=payload)
    result = resp.json()
    logger.info("测验: 题目数=%d", len(result.get("questions", [])))
    print(json.dumps(result, ensure_ascii=False, indent=2))


def demo_safety_check():
    payload = {"text": "这是一段教学内容示例", "grade": 3}
    resp = requests.post(f"{BASE}/safety/check", json=payload)
    result = resp.json()
    logger.info("安全检查: passed=%s", result.get("passed"))
    print(json.dumps(result, ensure_ascii=False, indent=2))


def demo_desensitize():
    records = [
        {"student_name": "张三", "phone": "13812345678", "score": 95},
        {"student_name": "李四", "phone": "13987654321", "score": 88},
    ]
    payload = {"records": records, "name_mode": "id", "id_prefix": "S"}
    resp = requests.post(f"{BASE}/desensitize/anonymize", json=payload)
    result = resp.json()
    logger.info("脱敏: 记录数=%d", result.get("anonymized_count", 0))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    demo_health()
    demo_lesson_plan()
    demo_quiz()
    demo_safety_check()
    demo_desensitize()
