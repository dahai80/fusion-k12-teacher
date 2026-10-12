"""SxSJudge 双盲裁判测试 — issue #23 A4。"""

from __future__ import annotations

import json

import pytest

from fusion_k12_teacher.eval.sxs_judge import (
    JUDGE_PROMPT,
    SxSAggregate,
    SxSJudge,
    SxSResult,
)

JUDGE_RESPONSE = json.dumps({
    "rationale": "Model B provides better Socratic guidance.",
    "scores": {
        "model_a": {"socratic": 2, "misconception": 3, "dsl_feasibility": 2},
        "model_b": {"socratic": 5, "misconception": 4, "dsl_feasibility": 5},
    },
    "winner": "Model B",
})


class MockMLX:
    def __init__(self, response: str):
        self._response = response
        self.model = ""

    async def chat(self, messages, temperature=0.7, max_tokens=4096, model="", grammar=None):
        return self._response


class TestSxSJudge:
    def test_judge_prompt_contains_criteria(self):
        assert "Socratic Guidance" in JUDGE_PROMPT
        assert "BNUP Misconception Alignment" in JUDGE_PROMPT
        assert "DSL Feasibility" in JUDGE_PROMPT
        assert "1 to 5" in JUDGE_PROMPT

    @pytest.mark.asyncio
    async def test_judge_pair_parses_json_verdict(self):
        mlx = MockMLX(JUDGE_RESPONSE)
        judge = SxSJudge(mlx, judge_model="judge")
        result = await judge.judge_pair(
            prompt="火车过桥", output_a="output_a", output_b="output_b",
            a_is_base=True, sample_id="p1",
        )
        assert result.winner == "Model B"
        assert result.scores_a["socratic"] == 2
        assert result.scores_b["socratic"] == 5
        assert result.error == ""

    @pytest.mark.asyncio
    async def test_judge_pair_shuffles(self):
        mlx = MockMLX(JUDGE_RESPONSE)
        judge = SxSJudge(mlx, judge_model="j")
        call_count = {"a_first": 0, "b_first": 0}
        for _ in range(20):
            result = await judge.judge_pair("p", "out_a", "out_b", a_is_base=True)
            if result.a_is_base:
                call_count["a_first"] += 1
            else:
                call_count["b_first"] += 1
        assert call_count["a_first"] > 0
        assert call_count["b_first"] > 0

    @pytest.mark.asyncio
    async def test_judge_pair_winner_mapping(self):
        mlx = MockMLX(JUDGE_RESPONSE)
        judge = SxSJudge(mlx, judge_model="j")
        result_not_shuffled = await judge.judge_pair("p", "base", "ft", a_is_base=True)
        if result_not_shuffled.a_is_base and result_not_shuffled.winner == "Model B":
            assert result_not_shuffled.ft_wins is True
            assert result_not_shuffled.base_wins is False

    @pytest.mark.asyncio
    async def test_judge_batch_win_rate(self):
        mlx = MockMLX(JUDGE_RESPONSE)
        judge = SxSJudge(mlx, judge_model="j")
        pairs = [
            {"id": f"p{i}", "prompt": f"问题{i}", "output_a": "base", "output_b": "ft"}
            for i in range(10)
        ]
        agg = await judge.judge_batch(pairs)
        assert agg.total == 10
        assert agg.ft_wins + agg.base_wins + agg.ties == 10
        assert len(agg.per_pair) == 10
        assert len(agg.socratic_scores) > 0

    @pytest.mark.asyncio
    async def test_judge_batch_error_handling(self):
        mlx = MockMLX("not json at all")
        judge = SxSJudge(mlx, judge_model="j")
        result = await judge.judge_pair("p", "a", "b", a_is_base=True, sample_id="p1")
        assert result.error != ""
        assert result.winner == ""

    @pytest.mark.asyncio
    async def test_sxs_aggregate_summary_str(self):
        mlx = MockMLX(JUDGE_RESPONSE)
        judge = SxSJudge(mlx, judge_model="j")
        pairs = [{"id": f"p{i}", "prompt": "x", "output_a": "a", "output_b": "b"} for i in range(5)]
        agg = await judge.judge_batch(pairs)
        s = agg.summary_str()
        assert "Win Rate" in s
        assert "Loss Rate" in s
        assert "Tie Rate" in s

    def test_sxs_result_tie(self):
        r = SxSResult(sample_id="p1", prompt="", output_a="", output_b="", winner="Tie")
        assert r.is_tie is True
        assert r.ft_wins is False
        assert r.base_wins is False

    def test_sxs_aggregate_empty(self):
        agg = SxSAggregate()
        assert agg.win_rate == 0.0
        assert agg.loss_rate == 0.0
