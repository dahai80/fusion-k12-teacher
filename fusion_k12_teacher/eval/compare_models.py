"""BNUP 前后对比 runner — baseline vs fine-tuned (PRD §570-768, issue #23 A4)。

通过 MLXClient HTTP 调用两个模型 (同一 gateway), 严格控制变量:
temp=0.1, max_tokens=2048, 相同 system prompt + user query。
逐题评估 4 维指标 + TPS, 输出 Δ 对比表。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from ..ai_client import MLXClient
from .eval_harness import BNUPEvaluator

logger = logging.getLogger(__name__)

CONTROLLED_TEMP = 0.1
CONTROLLED_MAX_TOKENS = 2048
CONTROLLED_TOP_P = 0.95
CONTROLLED_SEED = 42

_DEFAULT_SYSTEM_PROMPT = (
    "你是一名北师大版 K-12 数学苏格拉底讲师。"
    "请分析题目, 先在 <thinking> 标签内输出思考链, "
    "再在 <dsl> 标签内输出标准的 JSON DSL (含 meta/parameters/entities/pipeline)。"
)


@dataclass
class ModelStats:
    tags: int = 0
    json_ok: int = 0
    schema: int = 0
    eval_ok: int = 0
    math: int = 0
    tps_list: list[float] = field(default_factory=list)
    total: int = 0

    @property
    def tag_rate(self) -> float:
        return (self.tags / self.total * 100) if self.total else 0.0

    @property
    def json_rate(self) -> float:
        return (self.json_ok / self.total * 100) if self.total else 0.0

    @property
    def schema_rate(self) -> float:
        return (self.schema / self.total * 100) if self.total else 0.0

    @property
    def eval_rate(self) -> float:
        return (self.eval_ok / self.total * 100) if self.total else 0.0

    @property
    def math_accuracy(self) -> float:
        return (self.math / self.total * 100) if self.total else 0.0

    @property
    def avg_tps(self) -> float:
        return (sum(self.tps_list) / len(self.tps_list)) if self.tps_list else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "tag_rate": round(self.tag_rate, 2),
            "json_rate": round(self.json_rate, 2),
            "schema_rate": round(self.schema_rate, 2),
            "eval_rate": round(self.eval_rate, 2),
            "math_accuracy": round(self.math_accuracy, 2),
            "avg_tps": round(self.avg_tps, 2),
            "total": self.total,
        }


@dataclass
class ComparisonReport:
    total_samples: int = 0
    baseline_model: str = ""
    finetuned_model: str = ""
    baseline: ModelStats = field(default_factory=ModelStats)
    finetuned: ModelStats = field(default_factory=ModelStats)
    results_log: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_samples": self.total_samples,
            "baseline_model": self.baseline_model,
            "finetuned_model": self.finetuned_model,
            "baseline": self.baseline.to_dict(),
            "finetuned": self.finetuned.to_dict(),
            "deltas": {
                "tag_rate": round(self.finetuned.tag_rate - self.baseline.tag_rate, 2),
                "json_rate": round(self.finetuned.json_rate - self.baseline.json_rate, 2),
                "schema_rate": round(self.finetuned.schema_rate - self.baseline.schema_rate, 2),
                "eval_rate": round(self.finetuned.eval_rate - self.baseline.eval_rate, 2),
                "math_accuracy": round(self.finetuned.math_accuracy - self.baseline.math_accuracy, 2),
                "avg_tps": round(self.finetuned.avg_tps - self.baseline.avg_tps, 2),
            },
            "results_log": self.results_log,
        }

    def summary_str(self) -> str:
        b, f = self.baseline, self.finetuned
        lines = [
            "",
            "==================== 增训前后对比报告 ====================",
            f"测试总样本数: {self.total_samples}",
            f"基座模型: {self.baseline_model}  |  增训模型: {self.finetuned_model}",
            f"控制变量: temp={CONTROLLED_TEMP} top_p={CONTROLLED_TOP_P} "
            f"max_tokens={CONTROLLED_MAX_TOKENS} seed={CONTROLLED_SEED}",
            "指标名                | 基座 (Base)   | 增训 (FT)    | 提升幅度 (Delta)",
            "-" * 65,
        ]
        metrics = [
            ("标签隔离率", b.tag_rate, f.tag_rate),
            ("JSON 语法成功率", b.json_rate, f.json_rate),
            ("Schema 合格率", b.schema_rate, f.schema_rate),
            ("算式可执行率", b.eval_rate, f.eval_rate),
            ("求解准确率", b.math_accuracy, f.math_accuracy),
        ]
        for label, bv, fv in metrics:
            delta = fv - bv
            lines.append(f"{label:<16} | {bv:>11.2f}% | {fv:>10.2f}% | {delta:>+12.2f}%")
        lines.append(f"平均吞吐 (TPS)     | {b.avg_tps:>9.2f} t/s | {f.avg_tps:>8.2f} t/s | {f.avg_tps - b.avg_tps:>+10.2f} t/s")
        lines.append("=" * 65)
        return "\n".join(lines)


class ModelComparator:
    """前后对比 runner (PRD §616-768)。

    同一 MLXClient, 两个 model 名 (baseline / fine-tuned)。
    逐题推理 + 评估 + 统计 Δ。
    """

    def __init__(
        self,
        mlx: MLXClient,
        baseline_model: str,
        finetuned_model: str,
    ) -> None:
        self.mlx = mlx
        self.baseline_model = baseline_model
        self.finetuned_model = finetuned_model
        self.evaluator = BNUPEvaluator()
        self.report = ComparisonReport(
            baseline_model=baseline_model,
            finetuned_model=finetuned_model,
        )

    async def _generate(
        self, prompt: str, system: str, model: str
    ) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        start = time.time()
        text = await self.mlx.chat(
            messages=messages,
            temperature=CONTROLLED_TEMP,
            max_tokens=CONTROLLED_MAX_TOKENS,
            model=model,
        )
        latency = time.time() - start
        token_count = max(len(text) // 3, 1)
        tps = token_count / latency if latency > 0 else 0.0
        return {"text": text, "latency": latency, "tps": tps}

    def _eval_output(self, text: str, gt: float) -> dict[str, Any]:
        res = self.evaluator.evaluate_sample(text, gt)
        return {
            "has_tags": res.tag_ok,
            "json_ok": res.json_ok,
            "schema_ok": res.schema_ok,
            "eval_ok": res.eval_exec_ok,
            "math_ok": res.math_ok,
            "computed_value": res.computed_value,
            "error": res.error,
        }

    async def run_comparison(
        self,
        testset_path: str,
        output_log: str = "",
        system_prompt: str = _DEFAULT_SYSTEM_PROMPT,
    ) -> ComparisonReport:
        with open(testset_path, encoding="utf-8") as f:
            data = json.load(f)
        items = data.get("items", data) if isinstance(data, dict) else data

        self.report.total_samples = len(items)
        self.report.baseline.total = len(items)
        self.report.finetuned.total = len(items)

        for idx, item in enumerate(items):
            prompt = item.get("question", item.get("problem_text", ""))
            gt = float(item.get("ground_truth", 0))
            sid = item.get("id", f"s{idx + 1}")

            logger.info("compare [%d/%d] %s", idx + 1, len(items), sid)
            try:
                out_base = await self._generate(prompt, system_prompt, self.baseline_model)
            except Exception as e:
                logger.error("baseline inference failed for %s: %s", sid, e)
                out_base = {"text": "", "latency": 0, "tps": 0}
            try:
                out_ft = await self._generate(prompt, system_prompt, self.finetuned_model)
            except Exception as e:
                logger.error("finetuned inference failed for %s: %s", sid, e)
                out_ft = {"text": "", "latency": 0, "tps": 0}

            eval_base = self._eval_output(out_base["text"], gt)
            eval_ft = self._eval_output(out_ft["text"], gt)

            for stats, ev, out in [
                (self.report.baseline, eval_base, out_base),
                (self.report.finetuned, eval_ft, out_ft),
            ]:
                if ev["has_tags"]:
                    stats.tags += 1
                if ev["json_ok"]:
                    stats.json_ok += 1
                if ev["schema_ok"]:
                    stats.schema += 1
                if ev["eval_ok"]:
                    stats.eval_ok += 1
                if ev["math_ok"]:
                    stats.math += 1
                stats.tps_list.append(out["tps"])

            self.report.results_log.append({
                "id": sid,
                "prompt": prompt,
                "ground_truth": gt,
                "baseline_output": out_base["text"][:500],
                "baseline_eval": eval_base,
                "baseline_tps": out_base["tps"],
                "finetuned_output": out_ft["text"][:500],
                "finetuned_eval": eval_ft,
                "finetuned_tps": out_ft["tps"],
            })

        if output_log:
            with open(output_log, "w", encoding="utf-8") as f:
                json.dump(self.report.to_dict(), f, ensure_ascii=False, indent=2)
            logger.info("comparison log written to %s", output_log)

        return self.report
