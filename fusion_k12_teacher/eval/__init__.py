"""BNUP evaluation harness — four-dimension metrics / before-after comparison /
SxS judge (issues #23 #24).

Modules:
  eval_harness.BNUPEvaluator — automated four-dimension metric evaluation
  (tag/json/schema/eval/math)
  compare_models.ModelComparator — baseline vs fine-tuned before/after comparison
  sxs_judge.SxSJudge — double-blind LLM judge (Socratic teaching quality)

Data:
  data/bnup_benchmark.json — 300-500 question in-domain/out-of-domain/adversarial
  test set
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
