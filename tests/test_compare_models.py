"""ModelComparator 前后对比测试 — issue #23 A4。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fusion_k12_teacher.eval.compare_models import (
    CONTROLLED_MAX_TOKENS,
    CONTROLLED_TEMP,
    ModelComparator,
    ModelStats,
)

VALID_DSL = """<thinking>火车过桥: (800+200)/20=50</thinking>
<dsl>
{
  "meta": {"id": "n1", "grade": 5, "topic": "火车过桥", "visual_type": "track_timeline", "fallback_type": "tape_diagram"},
  "parameters": {"L_bridge": {"label": "桥长", "value": 800, "unit": "m"}, "L_train": {"label": "车长", "value": 200, "unit": "m"}, "v_train": {"label": "速度", "value": 20, "unit": "m/s"}},
  "entities": [{"id": "train", "type": "moving_object", "label": "火车"}],
  "pipeline": [
    {"step": 1, "title": "路程", "formula": "L_bridge+L_train", "eval": "params.L_bridge+params.L_train", "result_unit": "m", "visual_state": {"progress_range": [0.0, 0.5], "active_entities": ["train"], "action": "run"}},
    {"step": 2, "title": "时间", "formula": "results[1]/v", "eval": "results[1]/params.v_train", "result_unit": "s", "visual_state": {"progress_range": [0.5, 1.0], "active_entities": ["train"], "action": "stop"}}
  ]
}
</dsl>"""

BAD_DSL = "<thinking>不会做</thinking>"


class MockMLX:
    def __init__(self, responses: dict[str, str]):
        self._responses = responses
        self.calls: list[dict] = []
        self.model = ""

    async def chat(self, messages, temperature=0.7, max_tokens=4096, model="", grammar=None):
        self.calls.append({
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "model": model,
        })
        return self._responses.get(model or "default", "")


def _make_testset(tmp_path: Path, count: int = 4) -> str:
    items = [
        {"id": f"s{i+1}", "question": f"火车过桥问题 {i+1}", "ground_truth": 50.0}
        for i in range(count)
    ]
    path = tmp_path / "testset.json"
    path.write_text(json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")
    return str(path)


class TestModelComparator:
    def test_init(self):
        mlx = MockMLX({})
        comp = ModelComparator(mlx, "base-model", "ft-model")
        assert comp.baseline_model == "base-model"
        assert comp.finetuned_model == "ft-model"

    @pytest.mark.asyncio
    async def test_run_comparison_mock(self, tmp_path):
        mlx = MockMLX({
            "base-model": BAD_DSL,
            "ft-model": VALID_DSL,
        })
        testset = _make_testset(tmp_path, count=4)
        comp = ModelComparator(mlx, "base-model", "ft-model")
        report = await comp.run_comparison(testset)
        assert report.total_samples == 4
        assert report.baseline.total == 4
        assert report.finetuned.total == 4
        assert report.finetuned.math > report.baseline.math
        assert report.finetuned.tag_rate > report.baseline.tag_rate

    @pytest.mark.asyncio
    async def test_controlled_variables(self, tmp_path):
        mlx = MockMLX({"base-model": VALID_DSL, "ft-model": VALID_DSL})
        testset = _make_testset(tmp_path, count=2)
        comp = ModelComparator(mlx, "base-model", "ft-model")
        await comp.run_comparison(testset)
        for call in mlx.calls:
            assert call["temperature"] == CONTROLLED_TEMP
            assert call["max_tokens"] == CONTROLLED_MAX_TOKENS

    @pytest.mark.asyncio
    async def test_comparison_report_delta_table(self, tmp_path):
        mlx = MockMLX({"base-model": BAD_DSL, "ft-model": VALID_DSL})
        testset = _make_testset(tmp_path, count=3)
        comp = ModelComparator(mlx, "base-model", "ft-model")
        report = await comp.run_comparison(testset)
        s = report.summary_str()
        assert "基座" in s
        assert "增训" in s
        assert "Delta" in s
        d = report.to_dict()
        assert "deltas" in d
        assert d["deltas"]["math_accuracy"] > 0

    @pytest.mark.asyncio
    async def test_output_log_written(self, tmp_path):
        mlx = MockMLX({"base-model": VALID_DSL, "ft-model": VALID_DSL})
        testset = _make_testset(tmp_path, count=2)
        out_log = str(tmp_path / "comparison.json")
        comp = ModelComparator(mlx, "base-model", "ft-model")
        await comp.run_comparison(testset, output_log=out_log)
        assert Path(out_log).exists()
        data = json.loads(Path(out_log).read_text(encoding="utf-8"))
        assert "baseline" in data
        assert "finetuned" in data
        assert "results_log" in data


class TestModelStats:
    def test_rates(self):
        stats = ModelStats()
        stats.total = 10
        stats.tags = 8
        stats.math = 5
        assert stats.tag_rate == 80.0
        assert stats.math_accuracy == 50.0

    def test_avg_tps(self):
        stats = ModelStats()
        stats.tps_list = [10, 20, 30]
        assert stats.avg_tps == 20.0
