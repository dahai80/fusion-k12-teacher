"""BNUP 1-6 年级端到端测试 — 真实模型推理 + 四维评估。

验证: 所有课后题/易错题能否产出正确解题步骤和答案。
用法: python scripts/e2e_bnup_eval.py [--max N] [--category in_domain]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent.parent))

from fusion_k12_teacher.ai_client import MLXClient  # noqa: E402
from fusion_k12_teacher.eval.eval_harness import BNUPEvaluator  # noqa: E402

BENCHMARK = Path(__file__).parent.parent / "fusion_k12_teacher" / "eval" / "data" / "bnup_benchmark.json"
RESULTS_DIR = Path(__file__).parent.parent / "scripts" / "e2e_results"

EVAL_SYSTEM_PROMPT = """你是数学解题专家。对于每道题, 必须严格按以下格式输出:

1. 先在 <thinking> 标签内简短写出解题思路 (1-3 句话, 不要长篇推导)。
2. 紧接着在 <dsl> 标签内输出一个合法 JSON 对象, 不要在 JSON 前后加任何文字。

DSL JSON 格式 (必须严格遵守 JSON 语法, 双引号包裹所有键和字符串值):
{
  "meta": {"id":"q1","grade":5,"topic":"题目主题","visual_type":"track_timeline","fallback_type":"flow_card"},
  "parameters": {"变量名":{"label":"中文标签","value":数值,"unit":"单位"}},
  "entities": [{"id":"e1","type":"object","label":"实体名"}],
  "pipeline": [
    {"step":1,"title":"步骤标题","formula":"公式文本","eval":"params.变量名+params.变量名","result_unit":"单位","visual_state":{"progress_range":[0.0,0.5],"active_entities":["e1"],"action":"compute"}},
    {"step":2,"title":"最终结果","formula":"results[1]/params.变量名","eval":"results[1]/params.变量名","result_unit":"单位","visual_state":{"progress_range":[0.5,1.0],"active_entities":["e1"],"action":"result"}}
  ]
}

规则:
- eval 表达式用 params.变量名 引用参数, results[n] 引用第 n 步结果
- eval 中的变量名必须与 parameters 中定义的键名完全一致 (区分大小写)
- eval 必须用 Python 运算符: 乘法用 * (不是×), 除法用 / (不是÷), 减法用 - (不是−)
- 最后一步的 eval 计算结果必须等于题目答案
- JSON 必须合法: 双引号、无尾逗号、无注释
- <dsl> 标签内只放 JSON, 不要放任何其他文字

示例:
<thinking>
总路程=桥长+车长=800+200=1000, 时间=1000/20=50
</thinking>
<dsl>
{"meta":{"id":"q1","grade":5,"topic":"火车过桥","visual_type":"track_timeline","fallback_type":"tape_diagram"},"parameters":{"L_bridge":{"label":"桥长","value":800,"unit":"m"},"L_train":{"label":"车长","value":200,"unit":"m"},"v_train":{"label":"速度","value":20,"unit":"m/s"}},"entities":[{"id":"train","type":"moving_object","label":"火车"}],"pipeline":[{"step":1,"title":"总路程","formula":"L_bridge+L_train","eval":"params.L_bridge+params.L_train","result_unit":"m","visual_state":{"progress_range":[0.0,0.5],"active_entities":["train"],"action":"run"}},{"step":2,"title":"求时间","formula":"results[1]/v_train","eval":"results[1]/params.v_train","result_unit":"s","visual_state":{"progress_range":[0.5,1.0],"active_entities":["train"],"action":"arrive"}}]}
</dsl>

现在请解答以下题目, 严格按上述格式输出。
"""

SFT_SYSTEM_PROMPT = """你是一名北师大版 K-12 数学苏格拉底讲师。请分析题目，先在 <thinking> 标签内输出思考链，再在 <dsl> 标签内输出标准的 JSON DSL。"""


async def stream_chat(
    messages: list[dict],
    model: str,
    adapters: str,
    base_url: str,
    api_key: str,
    max_tokens: int = 2048,
    timeout: float = 1800.0,
) -> str:
    import httpx
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if adapters:
        payload["adapters"] = adapters
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    parts: list[str] = []
    async with httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(timeout, connect=30.0)) as client:
        async with client.stream("POST", "/chat/completions", json=payload, headers=headers) as resp:
            if resp.status_code != 200:
                body = (await resp.aread()).decode(errors="replace")[:200]
                raise RuntimeError(f"stream HTTP {resp.status_code}: {body}")
            async for line in resp.aiter_lines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                try:
                    d = json.loads(line[6:])
                    c = d["choices"][0].get("delta", {}).get("content", "")
                    if c:
                        parts.append(c)
                except (KeyError, IndexError, ValueError):
                    continue
    return "".join(parts)


async def run_eval(
    mlx: MLXClient,
    items: list[dict],
    model: str,
    max_concurrent: int = 1,
    adapters: str = "",
    stream: bool = False,
    base_url: str = "http://localhost:11434/v1",
    api_key: str = "",
    prompt_style: str = "eval",
) -> tuple:
    evaluator = BNUPEvaluator()
    semaphore = asyncio.Semaphore(max_concurrent)
    system_prompt = SFT_SYSTEM_PROMPT if prompt_style == "sft" else EVAL_SYSTEM_PROMPT

    async def eval_one(idx: int, item: dict) -> dict:
        sid = item.get("id", f"s{idx}")
        prompt = item.get("question", "")
        gt = float(item.get("ground_truth", 0))
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        async with semaphore:
            try:
                start = time.time()
                if stream:
                    resp = await stream_chat(messages, model, adapters, base_url, api_key)
                else:
                    resp = await mlx.chat(
                        messages, temperature=0.1, max_tokens=2048,
                        model=model, adapters=adapters or None,
                    )
                latency = time.time() - start
            except Exception as e:
                logger.error("[%d/%d] %s inference failed: %s", idx + 1, len(items), sid, e)
                resp = ""
                latency = 0
        resp = resp or ""
        res = evaluator.evaluate_sample(resp, gt, sample_id=sid)
        status = "✅" if res.math_ok else "❌"
        logger.info(
            "[%d/%d] %s %s grade=%s cat=%s gt=%s computed=%s tag=%s json=%s schema=%s eval=%s math=%s %.1fs",
            idx + 1, len(items), sid, status,
            item.get("grade", ""), item.get("category", ""),
            gt, res.computed_value,
            res.tag_ok, res.json_ok, res.schema_ok, res.eval_exec_ok, res.math_ok,
            latency,
        )
        return {
            "id": sid,
            "question": prompt[:100],
            "grade": item.get("grade"),
            "category": item.get("category"),
            "topic": item.get("topic"),
            "visual_type": item.get("expected_visual_type"),
            "ground_truth": gt,
            "response": resp[:2000],
            "latency": round(latency, 2),
            "tag_ok": res.tag_ok,
            "json_ok": res.json_ok,
            "schema_ok": res.schema_ok,
            "eval_exec_ok": res.eval_exec_ok,
            "math_ok": res.math_ok,
            "computed_value": res.computed_value,
            "error": res.error,
        }

    tasks = [eval_one(i, item) for i, item in enumerate(items)]
    results = await asyncio.gather(*tasks)
    return results, evaluator.report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=0, help="max items (0=all)")
    parser.add_argument("--category", default="", help="filter: in_domain|ood|adversarial")
    parser.add_argument("--grade", type=int, default=0, help="filter grade")
    parser.add_argument("--model", default="", help="model name")
    parser.add_argument("--concurrency", type=int, default=1, help="max concurrent")
    parser.add_argument("--output", default="", help="output JSON path")
    parser.add_argument("--testset", default="", help="custom testset JSON path (default: builtin benchmark)")
    parser.add_argument("--direct-mlx", action="store_true", help="bypass gateway, hit fusion-mlx :11434 directly")
    parser.add_argument("--adapters", default="", help="LoRA/DoRA adapter dir path (fusion-mlx inplace swap)")
    parser.add_argument("--stream", action="store_true", help="SSE streaming (bypass 600s server cap, for slow 32B)")
    parser.add_argument("--prompt-style", default="eval", choices=["eval", "sft"], help="system prompt: eval=harness prompt, sft=SFT training prompt (in-distribution)")
    args = parser.parse_args()

    testset_path = args.testset if args.testset else str(BENCHMARK)
    with open(testset_path, encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("items", [])

    if args.category:
        items = [i for i in items if i.get("category") == args.category]
    if args.grade:
        items = [i for i in items if i.get("grade") == args.grade]
    if args.max > 0:
        items = items[:args.max]

    logger.info("loaded %d items (model=%s concurrency=%d)", len(items), args.model or "auto", args.concurrency)

    if args.direct_mlx:
        os.environ["FUSION_MLX_URL"] = "http://localhost:11434/v1"
        os.environ["FUSION_MLX_API_KEY"] = "fg-admin-key"
        os.environ.setdefault("FUSION_MLX_READ_TIMEOUT", "600")
        logger.info("direct-mlx mode: base_url=http://localhost:11434/v1 key=fg-admin-key")
    else:
        os.environ.setdefault("FUSION_MLX_URL", "http://localhost:11432/v1")
        env_path = Path(__file__).parent.parent / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line.startswith("FUSION_MLX_API_KEY=") and line.split("=", 1)[1].strip():
                    os.environ["FUSION_MLX_API_KEY"] = line.split("=", 1)[1].strip()
                elif line.startswith("FUSION_MLX_MODEL=") and line.split("=", 1)[1].strip():
                    os.environ.setdefault("FUSION_MLX_MODEL", line.split("=", 1)[1].strip())

    mlx = MLXClient(model=args.model)

    results, report = asyncio.run(
        run_eval(
            mlx, items, args.model, args.concurrency, args.adapters,
            stream=args.stream,
            base_url=os.environ.get("FUSION_MLX_URL", "http://localhost:11434/v1"),
            api_key=os.environ.get("FUSION_MLX_API_KEY", ""),
            prompt_style=args.prompt_style,
        )
    )

    print(report.summary_str())

    by_grade = {}
    by_category = {}
    by_vt = {}
    for r in results:
        g = r.get("grade", 0)
        by_grade.setdefault(g, {"total": 0, "math_ok": 0})
        by_grade[g]["total"] += 1
        if r["math_ok"]:
            by_grade[g]["math_ok"] += 1

        c = r.get("category", "")
        by_category.setdefault(c, {"total": 0, "math_ok": 0})
        by_category[c]["total"] += 1
        if r["math_ok"]:
            by_category[c]["math_ok"] += 1

        vt = r.get("visual_type", "")
        by_vt.setdefault(vt, {"total": 0, "math_ok": 0})
        by_vt[vt]["total"] += 1
        if r["math_ok"]:
            by_vt[vt]["math_ok"] += 1

    print("\n--- 按年级 ---")
    for g in sorted(by_grade):
        s = by_grade[g]
        rate = s["math_ok"] / s["total"] * 100 if s["total"] else 0
        print(f"  年级 {g}: {s['math_ok']}/{s['total']} = {rate:.1f}%")

    print("\n--- 按类别 ---")
    for c in sorted(by_category):
        s = by_category[c]
        rate = s["math_ok"] / s["total"] * 100 if s["total"] else 0
        print(f"  {c}: {s['math_ok']}/{s['total']} = {rate:.1f}%")

    print("\n--- 按可视化类型 ---")
    for vt in sorted(by_vt, key=lambda x: -by_vt[x]["total"]):
        s = by_vt[vt]
        rate = s["math_ok"] / s["total"] * 100 if s["total"] else 0
        print(f"  {vt}: {s['math_ok']}/{s['total']} = {rate:.1f}%")

    failures = [r for r in results if not r["math_ok"]]
    print(f"\n失败题: {len(failures)}/{len(results)}")
    for f in failures[:10]:
        print(f"  {f['id']} grade={f['grade']} topic={f['topic']} gt={f['ground_truth']} computed={f['computed_value']} error={f['error'][:80]}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = args.output or str(RESULTS_DIR / f"e2e_{int(time.time())}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "model": args.model or "auto",
            "adapters": args.adapters or "",
            "total": len(results),
            "report": report.to_dict(),
            "by_grade": by_grade,
            "by_category": by_category,
            "by_visual_type": by_vt,
            "results": results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n完整结果: {out}")


if __name__ == "__main__":
    main()
