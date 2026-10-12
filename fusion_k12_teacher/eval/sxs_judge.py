"""SxS 双盲 LLM 裁判 — 苏格拉底教学质量评估 (PRD §769-799, issue #23 A4)。

仅靠硬断言无法评估 <thinking> 内部教学质量。
引入强模型做 SxS 对比打分: 随机打乱 A/B 位置避免偏见,
3 维度 1-5 分: 启发性/错因针对性/DSL 可行性, 判胜/负/平。
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any

from .._parse import parse_json
from ..ai_client import MLXClient

logger = logging.getLogger(__name__)

JUDGE_PROMPT = """You are an expert K-12 Pedagogy Evaluator specializing in the Beijing Normal University Press (BNUP) Mathematics Curriculum.
Your task is to compare two model outputs (Model A and Model B) for a given math word problem.

### EVALUATION CRITERIA (1 to 5 Points Each)
1. Socratic Guidance (启发性): Does the <thinking> section guide the student via step-by-step reasoning and misconception awareness rather than directly blurting out formulas?
2. BNUP Misconception Alignment (错因针对性): Does the reasoning target common primary/middle school student errors?
3. DSL Feasibility (DSL 绘图可行性): Is the generated JSON DSL logically sound for 2D/3D canvas rendering?

### INPUT PROBLEM
{prompt}

### MODEL A OUTPUT
{output_a}

### MODEL B OUTPUT
{output_b}

### OUTPUT FORMAT
Provide a brief justification, then assign scores and declare the winner in valid JSON:
{{
  "rationale": "Brief critique comparing Model A and Model B...",
  "scores": {{
    "model_a": {{"socratic": 3, "misconception": 4, "dsl_feasibility": 2}},
    "model_b": {{"socratic": 5, "misconception": 5, "dsl_feasibility": 5}}
  }},
  "winner": "Model B"
}}
"""


@dataclass
class SxSResult:
    sample_id: str
    prompt: str
    output_a: str
    output_b: str
    shuffled: bool = False
    a_is_base: bool = True
    rationale: str = ""
    scores_a: dict[str, int] = field(default_factory=dict)
    scores_b: dict[str, int] = field(default_factory=dict)
    winner: str = ""
    error: str = ""

    @property
    def base_wins(self) -> bool:
        if self.a_is_base:
            return self.winner == "Model A"
        return self.winner == "Model B"

    @property
    def ft_wins(self) -> bool:
        if self.a_is_base:
            return self.winner == "Model B"
        return self.winner == "Model A"

    @property
    def is_tie(self) -> bool:
        return self.winner == "Tie" or self.winner == ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "shuffled": self.shuffled,
            "a_is_base": self.a_is_base,
            "rationale": self.rationale,
            "scores_a": self.scores_a,
            "scores_b": self.scores_b,
            "winner": self.winner,
            "base_wins": self.base_wins,
            "ft_wins": self.ft_wins,
            "is_tie": self.is_tie,
            "error": self.error,
        }


@dataclass
class SxSAggregate:
    total: int = 0
    base_wins: int = 0
    ft_wins: int = 0
    ties: int = 0
    socratic_scores: list[int] = field(default_factory=list)
    misconception_scores: list[int] = field(default_factory=list)
    dsl_feasibility_scores: list[int] = field(default_factory=list)
    per_pair: list[SxSResult] = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        return (self.ft_wins / self.total) if self.total else 0.0

    @property
    def loss_rate(self) -> float:
        return (self.base_wins / self.total) if self.total else 0.0

    @property
    def tie_rate(self) -> float:
        return (self.ties / self.total) if self.total else 0.0

    def to_dict(self) -> dict[str, Any]:
        avg = lambda lst: round(sum(lst) / len(lst), 2) if lst else 0.0  # noqa: E731
        return {
            "total": self.total,
            "win_rate": round(self.win_rate, 4),
            "loss_rate": round(self.loss_rate, 4),
            "tie_rate": round(self.tie_rate, 4),
            "avg_socratic": avg(self.socratic_scores),
            "avg_misconception": avg(self.misconception_scores),
            "avg_dsl_feasibility": avg(self.dsl_feasibility_scores),
            "per_pair": [p.to_dict() for p in self.per_pair],
        }

    def summary_str(self) -> str:
        avg = lambda lst: round(sum(lst) / len(lst), 2) if lst else 0.0  # noqa: E731
        lines = [
            "",
            "==================== SxS 双盲裁判报告 ====================",
            f"对比样本数: {self.total}",
            f"增训胜率 (Win Rate):  {self.win_rate:.1%}",
            f"基座胜率 (Loss Rate): {self.loss_rate:.1%}",
            f"平局率 (Tie Rate):    {self.tie_rate:.1%}",
            f"平均启发性 (Socratic):         {avg(self.socratic_scores):.2f} / 5.0",
            f"平均错因针对性 (Misconception): {avg(self.misconception_scores):.2f} / 5.0",
            f"平均 DSL 可行性 (Feasibility):  {avg(self.dsl_feasibility_scores):.2f} / 5.0",
            "=" * 60,
        ]
        return "\n".join(lines)


class SxSJudge:
    """SxS 双盲裁判 (PRD §769-799)。

    用 MLXClient 做裁判模型, 随机打乱 base/ft 位置避免偏见。
    """

    def __init__(self, mlx: MLXClient, judge_model: str = "") -> None:
        self.mlx = mlx
        self.judge_model = judge_model
        self._rng = random.Random(42)

    async def judge_pair(
        self,
        prompt: str,
        output_a: str,
        output_b: str,
        a_is_base: bool = True,
        sample_id: str = "",
    ) -> SxSResult:
        shuffled = self._rng.random() < 0.5
        if shuffled:
            out_a, out_b = output_b, output_a
            a_is_base_eff = not a_is_base
        else:
            out_a, out_b = output_a, output_b
            a_is_base_eff = a_is_base

        judge_input = JUDGE_PROMPT.format(
            prompt=prompt, output_a=out_a, output_b=out_b
        )
        messages = [
            {"role": "system", "content": "You are an expert K-12 pedagogy evaluator. Respond only with valid JSON."},
            {"role": "user", "content": judge_input},
        ]

        result = SxSResult(
            sample_id=sample_id,
            prompt=prompt,
            output_a=output_a,
            output_b=output_b,
            shuffled=shuffled,
            a_is_base=a_is_base_eff,
        )

        try:
            raw = await self.mlx.chat(
                messages=messages,
                temperature=0.1,
                max_tokens=1024,
                model=self.judge_model,
            )
            parsed = parse_json(raw)
            if not parsed:
                result.error = "judge response not JSON"
                return result
            result.rationale = str(parsed.get("rationale", ""))
            scores = parsed.get("scores", {})
            result.scores_a = {
                k: int(v) for k, v in scores.get("model_a", {}).items()
            } if isinstance(scores.get("model_a"), dict) else {}
            result.scores_b = {
                k: int(v) for k, v in scores.get("model_b", {}).items()
            } if isinstance(scores.get("model_b"), dict) else {}
            result.winner = str(parsed.get("winner", ""))
            logger.info("sxs judge %s: winner=%s shuffled=%s", sample_id, result.winner, shuffled)
        except Exception as e:
            result.error = f"judge inference: {e}"
            logger.error("sxs judge failed for %s: %s", sample_id, e)

        return result

    async def judge_batch(
        self,
        pairs: list[dict[str, Any]],
    ) -> SxSAggregate:
        agg = SxSAggregate()
        for item in pairs:
            sid = item.get("id", f"p{agg.total + 1}")
            res = await self.judge_pair(
                prompt=item.get("prompt", ""),
                output_a=item.get("output_a", item.get("baseline_output", "")),
                output_b=item.get("output_b", item.get("finetuned_output", "")),
                a_is_base=True,
                sample_id=sid,
            )
            agg.total += 1
            agg.per_pair.append(res)
            if res.is_tie:
                agg.ties += 1
            elif res.ft_wins:
                agg.ft_wins += 1
            else:
                agg.base_wins += 1
            for scores in (res.scores_a, res.scores_b):
                if not scores:
                    continue
                if "socratic" in scores:
                    agg.socratic_scores.append(scores["socratic"])
                if "misconception" in scores:
                    agg.misconception_scores.append(scores["misconception"])
                if "dsl_feasibility" in scores:
                    agg.dsl_feasibility_scores.append(scores["dsl_feasibility"])
        logger.info(
            "sxs batch: %d pairs, win=%.1f%% loss=%.1f%% tie=%.1f%%",
            agg.total, agg.win_rate * 100, agg.loss_rate * 100, agg.tie_rate * 100,
        )
        return agg
