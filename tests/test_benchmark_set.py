"""BNUP 基准测试集结构测试 — issue #24 A5。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_BENCHMARK = Path(__file__).parent.parent / "fusion_k12_teacher" / "eval" / "data" / "bnup_benchmark.json"


@pytest.fixture(scope="module")
def benchmark_data():
    if not _BENCHMARK.exists():
        pytest.skip("bnup_benchmark.json not generated")
    with open(_BENCHMARK, encoding="utf-8") as f:
        return json.load(f)


class TestBenchmarkStructure:
    def test_benchmark_exists_and_valid(self, benchmark_data):
        assert "version" in benchmark_data
        assert "items" in benchmark_data
        assert isinstance(benchmark_data["items"], list)

    def test_benchmark_count_in_range(self, benchmark_data):
        total = len(benchmark_data["items"])
        assert 300 <= total <= 500, f"count {total} not in [300, 500]"

    def test_benchmark_category_distribution(self, benchmark_data):
        dist = benchmark_data["distribution"]
        total = benchmark_data["total"]
        in_pct = dist["in_domain"] / total * 100
        ood_pct = dist["ood"] / total * 100
        adv_pct = dist["adversarial"] / total * 100
        assert 55 <= in_pct <= 65, f"in_domain {in_pct:.1f}% not ~60%"
        assert 15 <= ood_pct <= 25, f"ood {ood_pct:.1f}% not ~20%"
        assert 15 <= adv_pct <= 25, f"adversarial {adv_pct:.1f}% not ~20%"

    def test_benchmark_item_fields(self, benchmark_data):
        required = {"id", "question", "ground_truth", "category", "grade", "topic",
                    "template_type", "expected_visual_type", "variables", "misconception_tags"}
        for item in benchmark_data["items"][:20]:
            missing = required - set(item.keys())
            assert not missing, f"item {item.get('id')} missing: {missing}"

    def test_benchmark_ground_truth_numeric(self, benchmark_data):
        for item in benchmark_data["items"][:50]:
            gt = item["ground_truth"]
            assert isinstance(gt, (int, float)), f"{item['id']} ground_truth not numeric: {type(gt)}"

    def test_benchmark_covers_grades_1_6(self, benchmark_data):
        in_domain = [i for i in benchmark_data["items"] if i["category"] == "in_domain"]
        grades = set(i["grade"] for i in in_domain)
        assert {1, 2, 3, 4, 5, 6}.issubset(grades), f"grades {grades} missing 1-6"

    def test_benchmark_covers_visual_types(self, benchmark_data):
        in_domain = [i for i in benchmark_data["items"] if i["category"] == "in_domain"]
        vts = set(i["expected_visual_type"] for i in in_domain)
        expected = {"array_grid", "tape_diagram", "geometry_2d", "isometric_3d",
                    "track_timeline", "bucket_divider", "data_chart", "flow_card"}
        assert expected.issubset(vts), f"visual types {vts} missing: {expected - vts}"

    def test_benchmark_categories_valid(self, benchmark_data):
        valid = {"in_domain", "ood", "adversarial"}
        for item in benchmark_data["items"]:
            assert item["category"] in valid, f"{item['id']} bad category: {item['category']}"

    def test_benchmark_ids_unique(self, benchmark_data):
        ids = [i["id"] for i in benchmark_data["items"]]
        assert len(ids) == len(set(ids)), "duplicate IDs"

    def test_benchmark_has_adversarial_tags(self, benchmark_data):
        adv = [i for i in benchmark_data["items"] if i["category"] == "adversarial"]
        tags_seen = set()
        for item in adv:
            tags_seen.update(item.get("misconception_tags", []))
        assert "unit_mixing" in tags_seen or "redundant" in tags_seen or "ambiguous" in tags_seen
