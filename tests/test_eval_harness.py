"""BNUPEvaluator 四维指标测试 — issue #23 A3。"""

from __future__ import annotations

import pytest

from fusion_k12_teacher.eval.eval_harness import (
    DSL_SCHEMA,
    BNUPEvaluator,
    EvalReport,
)

VALID_OUTPUT = """<thinking>
1. 识别题型: 火车过桥。
2. 总路程 = 桥长 + 车长 = 800 + 200 = 1000。
3. 时间 = 路程 / 速度 = 1000 / 20 = 50。
</thinking>
<dsl>
{
  "meta": {"id": "node-01", "grade": 5, "topic": "火车过桥", "visual_type": "track_timeline", "fallback_type": "tape_diagram"},
  "parameters": {
    "L_bridge": {"label": "桥长", "value": 800, "unit": "m"},
    "L_train": {"label": "车长", "value": 200, "unit": "m"},
    "v_train": {"label": "速度", "value": 20, "unit": "m/s"}
  },
  "entities": [
    {"id": "train", "type": "moving_object", "label": "火车"},
    {"id": "bridge", "type": "static_structure", "label": "大桥"}
  ],
  "pipeline": [
    {"step": 1, "title": "总路程", "formula": "L_bridge+L_train", "eval": "params.L_bridge+params.L_train", "result_unit": "m", "visual_state": {"progress_range": [0.0, 0.5], "active_entities": ["train", "bridge"], "action": "run"}},
    {"step": 2, "title": "求时间", "formula": "results[1]/v_train", "eval": "results[1]/params.v_train", "result_unit": "s", "visual_state": {"progress_range": [0.5, 1.0], "active_entities": ["train"], "action": "arrive"}}
  ]
}
</dsl>"""


class TestExtractTags:
    def test_extract_tags_both_present(self):
        ev = BNUPEvaluator()
        tags = ev.extract_tags(VALID_OUTPUT)
        assert tags["thinking"] is not None
        assert "火车过桥" in tags["thinking"]
        assert tags["dsl"] is not None
        assert "meta" in tags["dsl"]

    def test_extract_tags_missing_dsl(self):
        ev = BNUPEvaluator()
        tags = ev.extract_tags("<thinking>只有思考</thinking> 没有 dsl")
        assert tags["thinking"] is not None
        assert tags["dsl"] is None

    def test_extract_tags_empty(self):
        ev = BNUPEvaluator()
        tags = ev.extract_tags("")
        assert tags["thinking"] is None
        assert tags["dsl"] is None


class TestEvalExpression:
    def test_params_substitution(self):
        ev = BNUPEvaluator()
        pipeline = [{"step": 1, "eval": "params.L_bridge+params.L_train"}]
        params = {"L_bridge": {"value": 800}, "L_train": {"value": 200}}
        assert ev.evaluate_eval_expression(pipeline, params) == 1000.0

    def test_results_chain(self):
        ev = BNUPEvaluator()
        pipeline = [
            {"step": 1, "eval": "params.L_bridge+params.L_train"},
            {"step": 2, "eval": "results[1]/params.v_train"},
        ]
        params = {"L_bridge": {"value": 800}, "L_train": {"value": 200}, "v_train": {"value": 20}}
        assert ev.evaluate_eval_expression(pipeline, params) == 50.0

    def test_safe_no_builtins(self):
        ev = BNUPEvaluator()
        pipeline = [{"step": 1, "eval": "__import__('os')"}]
        with pytest.raises(Exception):
            ev.evaluate_eval_expression(pipeline, {})

    def test_empty_pipeline(self):
        ev = BNUPEvaluator()
        assert ev.evaluate_eval_expression([], {}) == 0.0


class TestEvaluateSample:
    def test_all_pass(self):
        ev = BNUPEvaluator()
        res = ev.evaluate_sample(VALID_OUTPUT, ground_truth=50.0, sample_id="s1")
        assert res.tag_ok is True
        assert res.json_ok is True
        assert res.schema_ok is True
        assert res.eval_exec_ok is True
        assert res.math_ok is True
        assert res.computed_value == 50.0
        assert res.error == ""

    def test_math_mismatch(self):
        ev = BNUPEvaluator()
        res = ev.evaluate_sample(VALID_OUTPUT, ground_truth=99.0, sample_id="s2")
        assert res.eval_exec_ok is True
        assert res.math_ok is False
        assert "mismatch" in res.error

    def test_schema_fail_missing_parameters(self):
        bad = """<thinking>x</thinking>
<dsl>{"meta": {"id": "n", "grade": 5, "topic": "t", "visual_type": "flow_card", "fallback_type": "tape_diagram"}, "entities": [], "pipeline": []}</dsl>"""
        ev = BNUPEvaluator()
        res = ev.evaluate_sample(bad, ground_truth=0, sample_id="s3")
        assert res.tag_ok is True
        assert res.json_ok is True
        assert res.schema_ok is False
        assert "parameters" in res.error

    def test_tag_fail_no_dsl(self):
        ev = BNUPEvaluator()
        res = ev.evaluate_sample("<thinking>只有思考</thinking>", ground_truth=50, sample_id="s4")
        assert res.tag_ok is False
        assert res.json_ok is False

    def test_json_fail(self):
        bad = """<thinking>x</thinking>
<dsl>{not valid json}</dsl>"""
        ev = BNUPEvaluator()
        res = ev.evaluate_sample(bad, ground_truth=50, sample_id="s5")
        assert res.tag_ok is True
        assert res.json_ok is False


class TestBatchReport:
    def test_evaluate_batch_rates(self):
        ev = BNUPEvaluator()
        samples = [
            {"id": f"s{i}", "response_text": VALID_OUTPUT, "ground_truth": 50.0}
            for i in range(7)
        ]
        samples.append({"id": "s8", "response_text": "<thinking>x</thinking>", "ground_truth": 50.0})
        report = ev.evaluate_batch(samples)
        assert report.total_samples == 8
        assert report.tag_rate == 87.5
        assert report.json_rate == 87.5
        assert report.schema_rate == 87.5
        assert report.eval_exec_rate == 87.5
        assert report.math_accuracy == 87.5
        assert len(report.per_sample) == 8

    def test_summary_str_contains_metrics(self):
        ev = BNUPEvaluator()
        ev.evaluate_sample(VALID_OUTPUT, 50.0, "s1")
        s = ev.report.summary_str()
        assert "标签隔离率" in s
        assert "JSON 语法成功率" in s
        assert "Schema 合格率" in s
        assert "Eval 可执行率" in s
        assert "数学准确率" in s

    def test_meets_thresholds_perfect_batch(self):
        ev = BNUPEvaluator()
        for i in range(10):
            ev.evaluate_sample(VALID_OUTPUT, 50.0, f"s{i}")
        assert ev.report.meets_thresholds() is True

    def test_empty_report_summary(self):
        report = EvalReport()
        assert "无测试数据" in report.summary_str()


class TestSchema:
    def test_dsl_schema_rejects_missing_parameters(self):
        try:
            import jsonschema
        except ImportError:
            pytest.skip("jsonschema not installed")
        validator = jsonschema.Draft202012Validator(DSL_SCHEMA)
        errors = list(validator.iter_errors({"meta": {}, "entities": [], "pipeline": []}))
        assert len(errors) > 0
        assert "parameters" in errors[0].message

    def test_dsl_schema_rejects_extra_root_keys(self):
        try:
            import jsonschema
        except ImportError:
            pytest.skip("jsonschema not installed")
        validator = jsonschema.Draft202012Validator(DSL_SCHEMA)
        bad = {
            "meta": {"id": "n", "grade": 5, "topic": "t", "visual_type": "x", "fallback_type": "y"},
            "parameters": {},
            "entities": [],
            "pipeline": [],
            "extra_key": "bad",
        }
        errors = list(validator.iter_errors(bad))
        assert len(errors) > 0

    def test_dsl_schema_accepts_valid(self):
        try:
            import jsonschema
        except ImportError:
            pytest.skip("jsonschema not installed")
        validator = jsonschema.Draft202012Validator(DSL_SCHEMA)
        import json
        ev = BNUPEvaluator()
        dsl_text = ev.extract_tags(VALID_OUTPUT)["dsl"]
        dsl_json = json.loads(dsl_text)
        errors = list(validator.iter_errors(dsl_json))
        assert errors == []


class TestUnitMilestone:
    def test_unit_alignment_pass(self):
        ev = BNUPEvaluator()
        import json
        dsl = json.loads(ev.extract_tags(VALID_OUTPUT)["dsl"])
        assert ev._check_unit_alignment(dsl) is True

    def test_milestone_coverage_pass(self):
        ev = BNUPEvaluator()
        import json
        dsl = json.loads(ev.extract_tags(VALID_OUTPUT)["dsl"])
        assert ev._check_milestone_coverage(dsl) is True

    def test_milestone_coverage_gap(self):
        ev = BNUPEvaluator()
        dsl = {
            "pipeline": [
                {"visual_state": {"progress_range": [0.0, 0.3]}},
                {"visual_state": {"progress_range": [0.5, 1.0]}},
            ]
        }
        assert ev._check_milestone_coverage(dsl) is False
