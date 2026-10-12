"""BNUP 评估 harness — 四维指标自动化评估 (PRD §384-558, issue #23 A3)。

维度 1 格式硬约束: 标签隔离率/JSON 语法率/Schema 合格率/eval 可执行率
维度 2 数理准确率: 最终数值与 Ground Truth 一致率
维度 3 教学质量: SxS 裁判 (sxs_judge.py)
维度 4 系统性能: TTFT/TPS (compare_models.py 采集)

复用 cot_pipeline.extract_thinking/extract_dsl 做 <thinking>/<dsl> 标签隔离,
内联 DSL_SCHEMA 与 fusion-core SOCRATIC_DSL_V3_SCHEMA + to_spec_dict 输出对齐。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from ..course.cot_pipeline import extract_dsl, extract_thinking

logger = logging.getLogger(__name__)

DSL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["meta", "parameters", "entities", "pipeline"],
    "additionalProperties": False,
    "properties": {
        "meta": {
            "type": "object",
            "required": ["id", "grade", "topic", "visual_type", "fallback_type"],
            "additionalProperties": False,
            "properties": {
                "id": {"type": "string"},
                "grade": {"type": "number"},
                "topic": {"type": "string"},
                "visual_type": {"type": "string"},
                "fallback_type": {"type": "string"},
            },
        },
        "parameters": {"type": "object"},
        "entities": {"type": "array"},
        "pipeline": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["step", "title", "formula", "eval", "result_unit", "visual_state"],
            },
        },
    },
}

PRD_THRESHOLDS = {
    "tag_rate": 99.5,
    "json_rate": 100.0,
    "schema_rate": 99.0,
    "eval_exec_rate": 100.0,
    "math_accuracy": 89.0,
}

_PARAM_SUB = re.compile(r"params\.(\w+)")
_RESULT_SUB = re.compile(r"results\[(\d+)\]")


@dataclass
class SampleResult:
    sample_id: str
    tag_ok: bool = False
    json_ok: bool = False
    schema_ok: bool = False
    eval_exec_ok: bool = False
    math_ok: bool = False
    computed_value: float | None = None
    ground_truth: float = 0.0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "tag_ok": self.tag_ok,
            "json_ok": self.json_ok,
            "schema_ok": self.schema_ok,
            "eval_exec_ok": self.eval_exec_ok,
            "math_ok": self.math_ok,
            "computed_value": self.computed_value,
            "ground_truth": self.ground_truth,
            "error": self.error,
        }


@dataclass
class EvalReport:
    total_samples: int = 0
    tag_passed: int = 0
    json_passed: int = 0
    schema_passed: int = 0
    eval_exec_passed: int = 0
    math_correct: int = 0
    unit_aligned: int = 0
    milestone_covered: int = 0
    per_sample: list[SampleResult] = field(default_factory=list)

    @property
    def tag_rate(self) -> float:
        return (self.tag_passed / self.total_samples * 100) if self.total_samples else 0.0

    @property
    def json_rate(self) -> float:
        return (self.json_passed / self.total_samples * 100) if self.total_samples else 0.0

    @property
    def schema_rate(self) -> float:
        return (self.schema_passed / self.total_samples * 100) if self.total_samples else 0.0

    @property
    def eval_exec_rate(self) -> float:
        return (self.eval_exec_passed / self.total_samples * 100) if self.total_samples else 0.0

    @property
    def math_accuracy(self) -> float:
        return (self.math_correct / self.total_samples * 100) if self.total_samples else 0.0

    @property
    def unit_alignment_rate(self) -> float:
        return (self.unit_aligned / self.total_samples * 100) if self.total_samples else 0.0

    @property
    def milestone_coverage(self) -> float:
        return (self.milestone_covered / self.total_samples * 100) if self.total_samples else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_samples": self.total_samples,
            "tag_rate": round(self.tag_rate, 2),
            "json_rate": round(self.json_rate, 2),
            "schema_rate": round(self.schema_rate, 2),
            "eval_exec_rate": round(self.eval_exec_rate, 2),
            "math_accuracy": round(self.math_accuracy, 2),
            "unit_alignment_rate": round(self.unit_alignment_rate, 2),
            "milestone_coverage": round(self.milestone_coverage, 2),
            "thresholds": PRD_THRESHOLDS,
            "per_sample": [s.to_dict() for s in self.per_sample],
        }

    def summary_str(self) -> str:
        if self.total_samples == 0:
            return "无测试数据"
        lines = [
            "",
            "==================== BNUP 评估报告 ====================",
            f"测试总样本数: {self.total_samples}",
            "指标名                          | 实际值    | PRD 目标  | 达标",
            "-" * 60,
        ]
        metrics = [
            ("标签隔离率 (Tag Rate)", self.tag_rate, PRD_THRESHOLDS["tag_rate"]),
            ("JSON 语法成功率 (JSON Rate)", self.json_rate, PRD_THRESHOLDS["json_rate"]),
            ("Schema 合格率 (Schema Rate)", self.schema_rate, PRD_THRESHOLDS["schema_rate"]),
            ("Eval 可执行率 (Eval Rate)", self.eval_exec_rate, PRD_THRESHOLDS["eval_exec_rate"]),
            ("数学准确率 (Accuracy)", self.math_accuracy, PRD_THRESHOLDS["math_accuracy"]),
            ("单位对齐率 (Unit Alignment)", self.unit_alignment_rate, 0),
            ("里程碑覆盖度 (Milestone)", self.milestone_coverage, 0),
        ]
        for label, actual, target in metrics:
            mark = ""
            if target > 0:
                mark = "✅" if actual >= target else "❌"
            lines.append(f"{label:<30} | {actual:>7.2f}% | {target:>7.1f}% | {mark}")
        lines.append("=" * 60)
        return "\n".join(lines)

    def meets_thresholds(self) -> bool:
        return (
            self.tag_rate >= PRD_THRESHOLDS["tag_rate"]
            and self.json_rate >= PRD_THRESHOLDS["json_rate"]
            and self.schema_rate >= PRD_THRESHOLDS["schema_rate"]
            and self.eval_exec_rate >= PRD_THRESHOLDS["eval_exec_rate"]
            and self.math_accuracy >= PRD_THRESHOLDS["math_accuracy"]
        )


class BNUPEvaluator:
    """四维指标自动化评估器 (PRD §434-558)。

    evaluate_sample: 5 步瀑布式校验 (tag → json → schema → eval → math)。
    evaluate_batch: 批量评估 + 聚合报告。
    """

    def __init__(self) -> None:
        self.report = EvalReport()
        try:
            import jsonschema
            self._validator = jsonschema.Draft202012Validator(DSL_SCHEMA)
        except ImportError:
            logger.warning("jsonschema 未安装, Schema 校验降级为字典键检查")
            self._validator = None

    def extract_tags(self, response_text: str) -> dict[str, str | None]:
        thinking, _ = extract_thinking(response_text)
        dsl = extract_dsl(response_text)
        return {"thinking": thinking or None, "dsl": dsl}

    def evaluate_eval_expression(
        self, pipeline: list[dict[str, Any]], parameters: dict[str, Any]
    ) -> float:
        """安全执行 pipeline eval 表达式 (PRD §453-471)。

        params.xxx → params_val['xxx'], results[n] → results_val[n]。
        eval restricted globals: __builtins__=None。
        返回最后一个 step 的计算结果。
        """
        params_val = {k: v.get("value", 0) for k, v in parameters.items() if isinstance(v, dict)}
        results_val: dict[int, float] = {}
        for step_item in pipeline:
            step_id = step_item.get("step", 0)
            expr = str(step_item.get("eval", ""))
            if not expr:
                continue
            py_expr = _PARAM_SUB.sub(r"params_val['\1']", expr)
            py_expr = _RESULT_SUB.sub(r"results_val[\1]", py_expr)
            val = eval(
                py_expr,
                {"__builtins__": None},
                {"params_val": params_val, "results_val": results_val},
            )
            results_val[int(step_id)] = float(val)
        if not results_val:
            return 0.0
        return results_val[max(results_val.keys())]

    def _check_unit_alignment(
        self, dsl_json: dict[str, Any]
    ) -> bool:
        params = dsl_json.get("parameters", {})
        pipeline = dsl_json.get("pipeline", [])
        if not params or not pipeline:
            return True
        has_param_units = any(
            isinstance(p, dict) and p.get("unit")
            for p in params.values()
        )
        has_result_unit = bool(str(pipeline[-1].get("result_unit", "")))
        return has_param_units and has_result_unit

    def _check_milestone_coverage(
        self, dsl_json: dict[str, Any]
    ) -> bool:
        pipeline = dsl_json.get("pipeline", [])
        if not pipeline:
            return False
        ranges = []
        for step in pipeline:
            vs = step.get("visual_state", {})
            pr = vs.get("progress_range", [0.0, 1.0])
            if isinstance(pr, list) and len(pr) == 2:
                ranges.append((float(pr[0]), float(pr[1])))
        if not ranges:
            return False
        ranges.sort()
        if ranges[0][0] > 0.01:
            return False
        if ranges[-1][1] < 0.99:
            return False
        for i in range(1, len(ranges)):
            if ranges[i][0] > ranges[i - 1][1] + 0.01:
                return False
        return True

    def evaluate_sample(
        self, response_text: str, ground_truth: float, sample_id: str = ""
    ) -> SampleResult:
        sid = sample_id or f"s{self.report.total_samples + 1}"
        res = SampleResult(sample_id=sid, ground_truth=ground_truth)
        self.report.total_samples += 1

        extracted = self.extract_tags(response_text)
        if extracted["thinking"] and extracted["dsl"]:
            res.tag_ok = True
            self.report.tag_passed += 1
        else:
            res.error = "tag isolation failed"
            self.report.per_sample.append(res)
            return res

        dsl_text = extracted["dsl"]
        if not dsl_text:
            res.error = "no dsl content"
            self.report.per_sample.append(res)
            return res

        try:
            dsl_json = json.loads(dsl_text)
            res.json_ok = True
            self.report.json_passed += 1
        except Exception as e:
            res.error = f"json parse: {e}"
            self.report.per_sample.append(res)
            return res

        if self._validator:
            errors = list(self._validator.iter_errors(dsl_json))
            if errors:
                res.error = f"schema: {errors[0].message}"
                self.report.per_sample.append(res)
                return res
        else:
            for key in ("meta", "parameters", "entities", "pipeline"):
                if key not in dsl_json:
                    res.error = f"schema: missing {key}"
                    self.report.per_sample.append(res)
                    return res

        res.schema_ok = True
        self.report.schema_passed += 1

        if self._check_unit_alignment(dsl_json):
            self.report.unit_aligned += 1
        if self._check_milestone_coverage(dsl_json):
            self.report.milestone_covered += 1

        try:
            computed = self.evaluate_eval_expression(
                dsl_json.get("pipeline", []), dsl_json.get("parameters", {})
            )
            res.computed_value = computed
            res.eval_exec_ok = True
            self.report.eval_exec_passed += 1
            if abs(computed - ground_truth) < 1e-3:
                res.math_ok = True
                self.report.math_correct += 1
            else:
                res.error = f"math mismatch: {computed} != {ground_truth}"
        except Exception as e:
            res.error = f"eval exec: {e}"

        self.report.per_sample.append(res)
        return res

    def evaluate_batch(
        self, samples: list[dict[str, Any]]
    ) -> EvalReport:
        """批量评估。sample: {id, response_text, ground_truth}。"""
        for item in samples:
            self.evaluate_sample(
                response_text=item.get("response_text", ""),
                ground_truth=float(item.get("ground_truth", 0)),
                sample_id=item.get("id", ""),
            )
        logger.info(
            "evaluate_batch: %d samples, tag=%.1f%% json=%.1f%% schema=%.1f%% eval=%.1f%% math=%.1f%%",
            self.report.total_samples,
            self.report.tag_rate,
            self.report.json_rate,
            self.report.schema_rate,
            self.report.eval_exec_rate,
            self.report.math_accuracy,
        )
        return self.report
