"""issue #22: BNUP 苏格拉底 prompt 注册表测试 — 路由规则 + 系统指令 + 集中引用。"""

from __future__ import annotations

from fusion_k12_teacher.course.prompts.bnup_socratic import (
    BNUP_COT_FORMAT_PROMPT,
    BNUP_SYSTEM_PROMPT,
    BNUP_VISUAL_ROUTING_PROMPT,
    FALLBACK_VISUAL,
    VISUAL_ROUTING_RULES,
    build_bnup_prompt,
    route_visual_type,
)


class TestVisualRouting:
    def test_8_routing_rules(self):
        assert len(VISUAL_ROUTING_RULES) == 8

    def test_route_counting_to_array_grid(self):
        assert route_visual_type("10以内数的认识") == "array_grid"

    def test_route_fraction_to_tape_diagram(self):
        assert route_visual_type("分数加减法") == "tape_diagram"

    def test_route_geometry_to_geometry_2d(self):
        assert route_visual_type("三角形面积") == "geometry_2d"

    def test_route_solid_to_isometric_3d(self):
        assert route_visual_type("圆柱体积") == "isometric_3d"

    def test_route_motion_to_track_timeline(self):
        assert route_visual_type("火车过桥") == "track_timeline"

    def test_route_combination_to_bucket_divider(self):
        assert route_visual_type("鸡兔同笼") == "bucket_divider"

    def test_route_statistics_to_data_chart(self):
        assert route_visual_type("折线统计图") == "data_chart"

    def test_route_equation_to_flow_card(self):
        assert route_visual_type("解方程") == "flow_card"

    def test_route_fallback_flow_card(self):
        assert route_visual_type("不知道什么题型") == FALLBACK_VISUAL
        assert FALLBACK_VISUAL == "flow_card"

    def test_route_with_problem_text(self):
        vtype = route_visual_type("", "一辆火车以每秒20米的速度过桥")
        assert vtype == "track_timeline"


class TestSystemPrompt:
    def test_mentions_8_primitives(self):
        for v in ("array_grid", "tape_diagram", "geometry_2d", "isometric_3d",
                  "track_timeline", "bucket_divider", "data_chart", "flow_card"):
            assert v in BNUP_SYSTEM_PROMPT

    def test_mentions_5e(self):
        assert "5E" in BNUP_SYSTEM_PROMPT
        assert "Engage" in BNUP_SYSTEM_PROMPT

    def test_mentions_socratic(self):
        assert "苏格拉底" in BNUP_SYSTEM_PROMPT

    def test_mentions_fallback_chain(self):
        assert "fallback" in BNUP_SYSTEM_PROMPT.lower()


class TestVisualRoutingPrompt:
    def test_has_all_8_rules(self):
        for v in ("array_grid", "tape_diagram", "geometry_2d", "isometric_3d",
                  "track_timeline", "bucket_divider", "data_chart", "flow_card"):
            assert v in BNUP_VISUAL_ROUTING_PROMPT


class TestCotFormatPrompt:
    def test_mentions_thinking_tag(self):
        assert "<thinking>" in BNUP_COT_FORMAT_PROMPT

    def test_mentions_dsl_tag(self):
        assert "<dsl>" in BNUP_COT_FORMAT_PROMPT


class TestBuildBnupPrompt:
    def test_basic_prompt(self):
        p = build_bnup_prompt("分数乘法", grade="6")
        assert "分数乘法" in p
        assert "6" in p
        assert "tape_diagram" in p

    def test_with_cot_enabled(self):
        p = build_bnup_prompt("火车过桥", grade="5", cot_enabled=True)
        assert "<thinking>" in p
        assert "track_timeline" in p

    def test_with_extras(self):
        p = build_bnup_prompt("圆柱体积", grade="6",
                              knowledge_node_id="math-g6-gm-02b",
                              prerequisites="长方体体积",
                              misconceptions="忘记除以3")
        assert "math-g6-gm-02b" in p
        assert "长方体体积" in p
        assert "忘记除以3" in p
        assert "isometric_3d" in p

    def test_visual_type_routed_in_prompt(self):
        p = build_bnup_prompt("鸡兔同笼", grade="6")
        assert "bucket_divider" in p
