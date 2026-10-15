#!/usr/bin/env python
"""中评 gate runner — 引擎外直载 (mlx_lm) 32B 底座 + LoRA adapter, 绕过引擎服务层。

背景: fusion-mlx v0.10.12 服务层对 32B 底座长生成输出乱码（tokenizer 引擎外验证正常,
mlx_lm 直载底座输出正常）, 28 题冒烟经由服务层跑批反复失败。本 runner 用 mlx_lm
直载底座 + adapters.safetensors (step 500 权重) 逐题推理, 复用 e2e 的
EVAL_SYSTEM_PROMPT + BNUPEvaluator 五步瀑布判定 (tag/json/schema/eval_exec/math)。
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.setdefault("HF_HOME", str(Path.home() / ".fusion-mlx" / "models"))

# 引擎外直载, 不经过 fusion-mlx 服务层
from mlx_lm import load, generate  # noqa: E402

from e2e_bnup_eval import EVAL_SYSTEM_PROMPT, BENCHMARK  # noqa: E402
from fusion_k12_teacher.eval.eval_harness import BNUPEvaluator  # noqa: E402

SNAP = next((Path.home() / ".fusion-mlx/models/models--mlx-community--Qwen2.5-32B-Instruct-4bit/snapshots").glob("*/"))
ADAPTER_DIR = Path.home() / ".fusion-mlx/adapters/mlx-community--Qwen2.5-32B-Instruct-4bit/bnup_sft_32b"
OUT = ROOT / "scripts/e2e_results/e2e_sft_midgate_28.json"
MAX_TOKENS = 2048


def main():
    items = json.load(open(BENCHMARK))["items"]
    # 28 题冒烟集: benchmark 头部隔层抽样 (与 e2e --max 28 同口径)
    items = items[:28]
    print(f"加载底座 + LoRA adapter ({ADAPTER_DIR.name})...", flush=True)
    model, tokenizer = load(str(SNAP), adapter_path=str(ADAPTER_DIR))
    evaluator = BNUPEvaluator()
    results = []

    for idx, item in enumerate(items):
        sid = item.get("id", f"s{idx}")
        gt = float(item.get("ground_truth", 0))
        messages = [
            {"role": "system", "content": EVAL_SYSTEM_PROMPT},
            {"role": "user", "content": item["question"]},
        ]
        prompt = tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
        t0 = time.time()
        try:
            resp = generate(model, tokenizer, prompt=prompt, max_tokens=MAX_TOKENS, verbose=False)
        except Exception as e:
            print(f"[{idx+1}/28] {sid} inference failed: {type(e).__name__} {e}", flush=True)
            resp = ""
        latency = round(time.time() - t0, 1)
        res = evaluator.evaluate_sample(resp or "", gt, sample_id=sid)
        status = "✅" if res.math_ok else "❌"
        print(
            f"[{idx+1}/28] {sid} {status} grade={item.get('grade','')} cat={item.get('category','')} "
            f"gt={gt} computed={res.computed_value} tag={res.tag_ok} json={res.json_ok} "
            f"schema={res.schema_ok} eval={res.eval_exec_ok} math={res.math_ok} {latency}s",
            flush=True,
        )
        results.append({
            "id": sid,
            "question": item["question"][:100],
            "grade": item.get("grade"),
            "category": item.get("category"),
            "topic": item.get("topic"),
            "visual_type": item.get("expected_visual_type"),
            "ground_truth": gt,
            "response": (resp or "")[:2000],
            "latency": latency,
            "tag_ok": res.tag_ok,
            "json_ok": res.json_ok,
            "schema_ok": res.schema_ok,
            "eval_exec_ok": res.eval_exec_ok,
            "math_ok": res.math_ok,
            "computed_value": res.computed_value,
            "error": res.error,
        })

    rep = evaluator.report
    OUT.write_text(json.dumps({"model": f"32B-LoRA:{ADAPTER_DIR.name}", "report": rep, "results": results},
                              ensure_ascii=False, indent=1))
    n = len(results)
    print("\n=== 28 题中评 gate (引擎外直载) ===", flush=True)
    print(f"样本: {n}")
    for k in ("tag_rate", "json_rate", "schema_rate", "eval_exec_rate", "math_accuracy"):
        v = rep.get(k)
        v = f"{v*100:.1f}%" if isinstance(v, (int, float)) else v
        print(f"  {k}: {v}")
    ee = rep.get("eval_exec_rate") or 0
    ee_pct = ee * 100 if ee <= 1.5 else ee
    print(f"GATE: eval_exec {ee_pct:.1f}% vs 85% -> {'PASS' if ee_pct >= 85 else 'FAIL'}")


if __name__ == "__main__":
    main()
