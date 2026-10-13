#!/usr/bin/env python
"""易错题批量场景编译测试 — 逐题调 DeepSeek, 五步瀑布记录通过/失败。"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
# DeepSeek 云端配置 — 必须在 import MLXClient 前注入, 本地 .env 是 local 形态
# (mlx gateway), 直跑会 401。key 从环境变量或 .env 读取, 禁止硬编码进仓库。
os.environ['FUSION_MLX_CLOUD'] = '1'
os.environ['FUSION_MLX_URL'] = os.environ.get('FUSION_MLX_URL', 'https://api.deepseek.com/v1')
os.environ['FUSION_MLX_MODEL'] = os.environ.get('FUSION_MLX_MODEL', 'deepseek-chat')
_env_key = os.environ.get('FUSION_MLX_API_KEY', '')
if not _env_key:
    _env_file = Path('.env')
    if _env_file.exists():
        for _line in _env_file.read_text().splitlines():
            if _line.strip().startswith('FUSION_MLX_API_KEY='):
                _env_key = _line.split('=', 1)[1].strip()
                break
if not _env_key:
    raise SystemExit("FUSION_MLX_API_KEY 未设置: export 或写入 .env (勿提交仓库)")
os.environ['FUSION_MLX_API_KEY'] = _env_key
os.environ['FUSION_MLX_CONNECT_TIMEOUT'] = '30'
os.environ['FUSION_MLX_READ_TIMEOUT'] = '240'
from fusion_k12_teacher.ai_client import MLXClient
from fusion_k12_teacher.course.subjects.math.scene_compiler import MathSceneCompiler
from fusion_k12_teacher.course.subjects.math.sympy_verifier import MathSympyVerifier
from fusion_k12_teacher.eval.eval_harness import BNUPEvaluator
import jsonschema

# SceneDSL 实际产物 schema (entities/timeline 结构) — eval_harness.DSL_SCHEMA
# 是 bnup_prep 训练闸的 pipeline/parameters 结构, 与 compiler 产物不同构
SCENE_DSL_SCHEMA = {
    "type": "object",
    "required": ["version", "subject", "template_type", "meta", "entities",
                 "canvas_config", "timeline", "verified"],
    "properties": {
        "version": {"type": "string"},
        "subject": {"const": "math"},
        "template_type": {"type": "string", "not": {"const": "generic_solve"}},
        "entities": {"type": "array", "minItems": 1},
        "canvas_config": {"type": "object"},
        "timeline": {"type": "object",
                     "required": ["answer", "milestones"],
                     "properties": {"answer": {"type": "number"},
                                    "milestones": {"type": "array", "minItems": 1}}},
        "verified": {"type": "boolean"},
    },
}

# timeline.answer 语义随场景: 里程映射已把各场景主解统一进 answer
ANSWER_FIELD = {}  # 空 → 全部读 timeline.answer


def is_math_ok(rec: dict) -> bool | None:
    ans = (rec.get('dsl') or {}).get('timeline', {}).get('answer')
    if ans is None:
        return None
    return abs(float(ans) - float(rec['gt'])) <= 0.01

problems = json.load(open('/tmp/misconception_problems.json'))
problems = [p for p in problems if p['template_type'] != 'adversarial' or True]

async def run_one(compiler, ev, client, p, sem):
    async with sem:
        t0 = time.time()
        rec = {"id": p['id'], "template": p['template_type'], "gt": p['ground_truth']}
        try:
            dsl = await asyncio.wait_for(
                compiler.compile(p['question'], ""), timeout=180)
            d = dsl.to_dict()
            rec['template_type'] = d.get('template_type', '')
            rec['dsl'] = d
            # gate: schema (SceneDSL 结构判据 — 非具名场景视为路由失败)
            try:
                jsonschema.Draft202012Validator(SCENE_DSL_SCHEMA).validate(d)
                rec['schema_ok'] = True
            except jsonschema.ValidationError as e:
                rec['schema_ok'] = False
                rec['err'] = f"schema: {e.message[:60]}"
            # gate: 数学正确 (timeline.answer vs gt, ε=0.01; verified=True 时 SymPy 已验)
            if rec.get('schema_ok'):
                m_ok = is_math_ok(rec)
                rec['math_ok'] = m_ok
                if m_ok is None:
                    rec['err'] = "no answer value"
        except asyncio.TimeoutError:
            rec['err'] = "timeout 180s"
        except Exception as e:
            rec['err'] = f"{type(e).__name__}: {str(e)[:100]}"
        rec['secs'] = round(time.time() - t0, 1)
        mark = ("PASS" if rec.get('math_ok') else
                "SCHEMA-FAIL" if rec.get('schema_ok') is False else
                "MATH-FAIL" if rec.get('math_ok') is False else
                "NO-ANSWER" if rec.get('err') == "no answer value" else
                "NO-DSL")
        rec['verdict'] = mark
        print(f"[{p['id']}] {mark} ({rec['secs']}s) {rec.get('err','')}", flush=True)
        return rec

async def main():
    client = MLXClient()
    compiler = MathSceneCompiler(client, MathSympyVerifier())
    ev = BNUPEvaluator()
    sem = asyncio.Semaphore(2)
    results = await asyncio.gather(*[run_one(compiler, ev, client, p, sem) for p in problems])
    json.dump(results, open('/tmp/misconception_compile_results.json', 'w'), ensure_ascii=False, indent=1)
    from collections import Counter
    vc = Counter(r['verdict'] for r in results)
    print("\n=== 汇总 ===")
    total = len(results)
    for k, n in vc.most_common():
        print(f"  {k}: {n} ({n/total*100:.0f}%)")
    print(f"数学正确率: {vc.get('PASS',0)/total*100:.1f}% (目标 89%)")

asyncio.run(main())
