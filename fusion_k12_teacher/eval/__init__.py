"""BNUP 评估 harness — 四维指标/前后对比/SxS 裁判 (issues #23 #24)。

模块:
  eval_harness.BNUPEvaluator — 四维指标自动化评估 (tag/json/schema/eval/math)
  compare_models.ModelComparator — baseline vs fine-tuned 前后对比
  sxs_judge.SxSJudge — 双盲 LLM 裁判 (苏格拉底教学质量)

数据:
  data/bnup_benchmark.json — 300-500 题域内/域外/对抗测试集
"""

from __future__ import annotations

from .compare_models import ComparisonReport, ModelComparator, ModelStats
from .eval_harness import BNUPEvaluator, EvalReport, SampleResult
from .sxs_judge import SxSAggregate, SxSJudge, SxSResult

__all__ = [
    "BNUPEvaluator",
    "ComparisonReport",
    "EvalReport",
    "ModelComparator",
    "ModelStats",
    "SampleResult",
    "SxSAggregate",
    "SxSJudge",
    "SxSResult",
]
