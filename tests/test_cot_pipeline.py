"""issue #20: 两阶段 CoT pipeline 测试 — thinking 提取, cot_enabled, 流式降级。"""

from __future__ import annotations

import pytest

from fusion_k12_teacher.course.cot_pipeline import (
    COT_DSL_PROMPT,
    COT_THINKING_PROMPT,
    cot_enabled,
    extract_dsl,
    extract_thinking,
)


class TestCotEnabled:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("FUSION_K12_COT_ENABLED", raising=False)
        assert cot_enabled() is False

    def test_enabled_true(self, monkeypatch):
        monkeypatch.setenv("FUSION_K12_COT_ENABLED", "true")
        assert cot_enabled() is True

    def test_enabled_yes(self, monkeypatch):
        monkeypatch.setenv("FUSION_K12_COT_ENABLED", "yes")
        assert cot_enabled() is True

    def test_enabled_1(self, monkeypatch):
        monkeypatch.setenv("FUSION_K12_COT_ENABLED", "1")
        assert cot_enabled() is True

    def test_disabled_random(self, monkeypatch):
        monkeypatch.setenv("FUSION_K12_COT_ENABLED", "no")
        assert cot_enabled() is False


class TestExtractThinking:
    def test_think_tag_pair(self):
        raw = "<thinking>深度分析教学路径</thinking>正文内容"
        thinking, content = extract_thinking(raw)
        assert "深度分析" in thinking
        assert "正文内容" in content

    def test_think_tag_variant(self):
        raw = "<think>推理过程</think>结果"
        thinking, content = extract_thinking(raw)
        assert "推理过程" in thinking
        assert "结果" in content

    def test_no_thinking_tag(self):
        raw = "纯正文无思考"
        thinking, content = extract_thinking(raw)
        assert thinking == ""
        assert content == "纯正文无思考"

    def test_empty_input(self):
        thinking, content = extract_thinking("")
        assert thinking == ""
        assert content == ""

    def test_thinking_only_no_close(self):
        raw = "<thinking>未闭合的思考"
        thinking, _content = extract_thinking(raw)
        assert "未闭合的思考" in thinking

    def test_multiple_thinking_blocks(self):
        raw = "<thinking>第一段</thinking>中间<thinking>第二段</thinking>结尾"
        thinking, content = extract_thinking(raw)
        assert "第一段" in thinking
        assert "第二段" in thinking
        assert "中间" in content
        assert "结尾" in content


# ── issue #20 gap 1: extract_dsl 测试 ──────────────────────────────

class TestExtractDsl:
    def test_dsl_tag_pair(self):
        raw = '<thinking>分析</thinking><dsl>{"steps":[]}</dsl>'
        dsl = extract_dsl(raw)
        assert dsl is not None
        assert '"steps"' in dsl

    def test_dsl_tag_only(self):
        raw = '<dsl>{"meta":{"visual_type":"track_timeline"}}</dsl>'
        dsl = extract_dsl(raw)
        assert dsl is not None
        assert "track_timeline" in dsl

    def test_dsl_open_no_close(self):
        raw = '<dsl>{"steps": [{"step_id": "s1"}]'
        dsl = extract_dsl(raw)
        assert dsl is not None
        assert "s1" in dsl

    def test_no_dsl_tag_fallback_json(self):
        raw = '{"meta":{"visual_type":"flow_card"},"steps":[]}'
        dsl = extract_dsl(raw)
        assert dsl is not None
        assert "flow_card" in dsl

    def test_no_dsl_no_json(self):
        raw = '纯文字描述, 没有 JSON'
        dsl = extract_dsl(raw)
        assert dsl is None

    def test_empty_input(self):
        assert extract_dsl("") is None
        assert extract_dsl(None) is None

    def test_multiple_dsl_tags_first_wins(self):
        raw = '<dsl>{"v":1}</dsl>中间<dsl>{"v":2}</dsl>'
        dsl = extract_dsl(raw)
        assert dsl is not None
        assert '"v":1' in dsl or '"v": 1' in dsl


# ── issue #20 gap 2: GBNF grammar 测试 ─────────────────────────────

class TestDslGbnfGrammar:
    def test_grammar_non_empty(self):
        from fusion_k12_teacher.course.cot_pipeline import DSL_GBNF_GRAMMAR
        assert len(DSL_GBNF_GRAMMAR) > 50
        assert "root" in DSL_GBNF_GRAMMAR
        assert "steps" in DSL_GBNF_GRAMMAR
        assert "meta" in DSL_GBNF_GRAMMAR

    def test_grammar_has_string_rule(self):
        from fusion_k12_teacher.course.cot_pipeline import DSL_GBNF_GRAMMAR
        assert "string" in DSL_GBNF_GRAMMAR
        assert "number" in DSL_GBNF_GRAMMAR

    @pytest.mark.asyncio
    async def test_chat_stream_passes_grammar(self):
        """issue #20 gap 2: chat_stream 应将 grammar 透传到 payload。"""
        from fusion_k12_teacher.ai_client import MLXClient

        class MockStream:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                pass
            async def aiter_lines(self):
                yield 'data: [DONE]'

        class MockHttpx:
            def stream(self, method, url, **kwargs):
                self.last_payload = kwargs.get("json", {})
                return MockStream()

        mock_httpx = MockHttpx()
        client = MLXClient()
        client._httpx_client = mock_httpx
        client.model = "test-model"
        await client.chat_stream(
            [{"role": "user", "content": "test"}],
            grammar="root ::= test",
        )
        assert mock_httpx.last_payload.get("grammar") == "root ::= test"

    @pytest.mark.asyncio
    async def test_chat_non_stream_passes_grammar(self, monkeypatch):
        """issue #20 gap 2: chat() (non-stream) 也应透传 grammar 到 payload。"""
        from fusion_k12_teacher.ai_client import MLXClient

        class MockResp:
            status_code = 200
            def json(self):
                return {"choices": [{"message": {"content": '{"steps":[]}'}}]}
            def raise_for_status(self):
                pass

        class MockHttpx:
            def __init__(self):
                self.last_payload = None
            async def post(self, url, json=None, headers=None):
                self.last_payload = json
                return MockResp()

        mock_httpx = MockHttpx()
        client = MLXClient()
        client._httpx_client = mock_httpx
        client._inner = None
        client.model = "test-model"
        await client.chat(
            [{"role": "user", "content": "test"}],
            grammar="root ::= test",
        )
        assert mock_httpx.last_payload.get("grammar") == "root ::= test"

    @pytest.mark.asyncio
    async def test_socratic_tutor_passes_grammar_when_cot_enabled(self, monkeypatch):
        """issue #20 gap 2: socratic_tutor 在 CoT 开启时应传 grammar=DSL_GBNF_GRAMMAR。"""
        monkeypatch.setenv("FUSION_K12_COT_ENABLED", "true")
        from fusion_k12_teacher.course.cot_pipeline import DSL_GBNF_GRAMMAR
        from fusion_k12_teacher.course.subjects.math.socratic_tutor import MathSocraticTutor
        from fusion_k12_teacher.course.subjects.math.sympy_verifier import MathSympyVerifier

        captured_grammar = []

        class MockMLX:
            async def chat(self, messages, temperature=0.7, max_tokens=4096, **kwargs):
                captured_grammar.append(kwargs.get("grammar"))
                return '{"meta":{"visual_type":"flow_card","fallback_type":"flow_card"},"steps":[]}'

        tutor = MathSocraticTutor(MockMLX(), MathSympyVerifier())
        await tutor.generate_lesson_script(topic="测试", grade="5")
        assert len(captured_grammar) > 0
        assert captured_grammar[0] == DSL_GBNF_GRAMMAR

    @pytest.mark.asyncio
    async def test_socratic_tutor_no_grammar_when_cot_disabled(self, monkeypatch):
        """issue #20: CoT 关闭时 grammar=None, 不影响原有行为。"""
        monkeypatch.delenv("FUSION_K12_COT_ENABLED", raising=False)
        from fusion_k12_teacher.course.subjects.math.socratic_tutor import MathSocraticTutor
        from fusion_k12_teacher.course.subjects.math.sympy_verifier import MathSympyVerifier

        captured_grammar = []

        class MockMLX:
            async def chat(self, messages, temperature=0.7, max_tokens=4096, **kwargs):
                captured_grammar.append(kwargs.get("grammar"))
                return '{"meta":{"visual_type":"flow_card","fallback_type":"flow_card"},"steps":[]}'

        tutor = MathSocraticTutor(MockMLX(), MathSympyVerifier())
        await tutor.generate_lesson_script(topic="测试", grade="5")
        assert len(captured_grammar) > 0
        assert captured_grammar[0] is None


class TestCotPrompts:
    def test_thinking_prompt_has_placeholders(self):
        assert "{topic}" in COT_THINKING_PROMPT
        assert "{grade}" in COT_THINKING_PROMPT
        assert "{node_id}" in COT_THINKING_PROMPT
        assert "{prerequisites}" in COT_THINKING_PROMPT
        assert "{misconceptions}" in COT_THINKING_PROMPT

    def test_dsl_prompt_has_placeholders(self):
        assert "{topic}" in COT_DSL_PROMPT
        assert "{grade}" in COT_DSL_PROMPT
        assert "{visual_type}" in COT_DSL_PROMPT

    def test_thinking_prompt_mentions_5e(self):
        assert "5E" in COT_THINKING_PROMPT
        assert "Engage" in COT_THINKING_PROMPT

    def test_dsl_prompt_mentions_visual_type(self):
        assert "visual_type" in COT_DSL_PROMPT
        assert "8 基元" in COT_DSL_PROMPT


class TestStreamThinking:
    @pytest.mark.asyncio
    async def test_stream_thinking_degrades_on_error(self):
        from fusion_k12_teacher.course.cot_pipeline import stream_thinking

        class FailingMLX:
            async def chat_stream(self, messages, **kwargs):
                raise ConnectionError("no mlx")

        chunks: list[str] = []

        async def on_chunk(t):
            chunks.append(t)

        result = await stream_thinking(FailingMLX(), [{"role": "user", "content": "x"}], on_chunk=on_chunk)
        assert result == ""
        assert chunks == []

    @pytest.mark.asyncio
    async def test_stream_thinking_sse_parse(self):
        from fusion_k12_teacher.course.cot_pipeline import stream_thinking

        class MockStream:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            async def aiter_lines(self):
                lines = [
                    'data: {"choices":[{"delta":{"reasoning_content":"思考"}}]}',
                    'data: {"choices":[{"delta":{"content":"正文"}}]}',
                    'data: [DONE]',
                ]
                for ln in lines:
                    yield ln

        class MockMLX:
            async def chat_stream(self, messages, **kwargs):
                assert kwargs.get("enable_thinking") is True
                return MockStream()

        chunks: list[str] = []

        async def on_chunk(t):
            chunks.append(t)

        result = await stream_thinking(MockMLX(), [{"role": "user", "content": "x"}], on_chunk=on_chunk)
        assert "思考" in result
        assert "正文" in result
        assert len(chunks) == 2
