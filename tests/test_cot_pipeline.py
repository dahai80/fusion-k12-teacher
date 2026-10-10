"""issue #20: 两阶段 CoT pipeline 测试 — thinking 提取, cot_enabled, 流式降级。"""

from __future__ import annotations

import pytest

from fusion_k12_teacher.course.cot_pipeline import (
    COT_DSL_PROMPT,
    COT_THINKING_PROMPT,
    cot_enabled,
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
