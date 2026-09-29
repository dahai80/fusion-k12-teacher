"""数字人平台层测试 — Phase A: 6 大核心 pattern + session/manager (mock 插件)。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from fusion_k12_teacher.digital_human.barge_in import BargeInBus
from fusion_k12_teacher.digital_human.content import ContentInjector, NarrationSegment
from fusion_k12_teacher.digital_human.emotion import EmotionLogFilter, EmotionTagParser
from fusion_k12_teacher.digital_human.fsm import SessionFSM, SessionState, TransitionError
from fusion_k12_teacher.digital_human.memory import RollingWindowMemory
from fusion_k12_teacher.digital_human.plugins.avatar_static import StaticAvatar
from fusion_k12_teacher.digital_human.plugins.base import (
    ASRPlugin,
    LLMPlugin,
    TTSPlugin,
)

# ---------- FSM ----------

class TestFSM:
    @pytest.mark.asyncio
    async def test_legal_transitions(self):
        fsm = SessionFSM("t1")
        assert fsm.state is SessionState.IDLE
        await fsm.transition(SessionState.AI_THINKING, reason="start")
        await fsm.transition(SessionState.AI_SPEAKING, reason="speak")
        await fsm.transition(SessionState.IDLE, reason="done")
        assert fsm.state is SessionState.IDLE

    @pytest.mark.asyncio
    async def test_illegal_transition_raises(self):
        fsm = SessionFSM("t2")
        await fsm.transition(SessionState.AI_THINKING, reason="think")
        await fsm.transition(SessionState.AI_SPEAKING, reason="speak")
        with pytest.raises(TransitionError):
            await fsm.transition(SessionState.AI_THINKING)

    @pytest.mark.asyncio
    async def test_error_state_fires_barge_in(self):
        fsm = SessionFSM("t3")
        bus = BargeInBus("t3")
        called = []
        bus.register("fake", lambda: called.append("cancel"), lambda: called.append("clear"))
        fsm.bind_barge_in(bus)
        await fsm.transition(SessionState.ERROR, reason="boom")
        assert fsm.state is SessionState.ERROR
        assert "cancel" in called
        assert "clear" in called

    @pytest.mark.asyncio
    async def test_hooks_fire(self):
        fsm = SessionFSM("t4")
        seen: list[str] = []
        async def on_enter_speaking(reason: str) -> None:
            seen.append("enter_speaking:" + reason)
        fsm.register_hook("on_enter_" + SessionState.AI_SPEAKING.value, on_enter_speaking)
        await fsm.transition(SessionState.AI_THINKING)
        await fsm.transition(SessionState.AI_SPEAKING, reason="go")
        assert seen == ["enter_speaking:go"]


# ---------- BargeInBus ----------

class TestBargeInBus:
    @pytest.mark.asyncio
    async def test_fire_cancels_and_clears_all(self):
        bus = BargeInBus("b1")
        log: list[str] = []
        async def cancel_a() -> None:
            log.append("a_cancel")
        def clear_a() -> None:
            log.append("a_clear")
        def cancel_b() -> None:
            log.append("b_cancel")
        bus.register("a", cancel_a, clear_a)
        bus.register("b", cancel_b, None)
        await bus.fire("test")
        assert "a_cancel" in log and "a_clear" in log and "b_cancel" in log

    @pytest.mark.asyncio
    async def test_fire_cancels_tracked_tasks(self):
        bus = BargeInBus("b2")
        async def long_task() -> None:
            await asyncio.sleep(100)
        task = asyncio.create_task(long_task())
        bus.track(task)
        await bus.fire("kill")
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert task.done()

    @pytest.mark.asyncio
    async def test_unregister(self):
        bus = BargeInBus("b3")
        log: list[str] = []
        bus.register("x", lambda: log.append("x"), None)
        bus.unregister("x")
        await bus.fire("noop")
        assert log == []


# ---------- EmotionTagParser ----------

class TestEmotionTagParser:
    def test_strip_known_tag(self):
        p = EmotionTagParser("e1")
        clean, tag = p.strip("同学们好 [happy]")
        assert clean == "同学们好"
        assert tag == "happy"

    def test_unknown_tag_to_neutral(self):
        p = EmotionTagParser("e2")
        clean, tag = p.strip("想想看 [xyz_abc]")
        assert tag == "neutral"
        assert "[xyz_abc]" not in clean

    def test_no_tag_neutral(self):
        p = EmotionTagParser("e3")
        _, tag = p.strip("普通文本")
        assert tag == "neutral"

    def test_speed_for(self):
        p = EmotionTagParser("e4")
        assert p.speed_for("happy") == 1.05
        assert p.speed_for("thinking") == 0.95
        assert p.speed_for("unknown") == 1.0

    @pytest.mark.asyncio
    async def test_broadcast_calls_both(self):
        p = EmotionTagParser("e5")
        seen: list[Any] = []
        async def tts_cb(tag: str, speed: float) -> None:
            seen.append(("tts", tag, speed))
        async def avatar_cb(expr: str) -> None:
            seen.append(("avatar", expr))
        await p.broadcast("happy", tts_cb, avatar_cb)
        assert ("tts", "happy", 1.05) in seen
        assert ("avatar", "smile") in seen

    def test_log_filter_strips_tag(self):
        import logging
        f = EmotionLogFilter()
        rec = logging.LogRecord("x", logging.INFO, __file__, 1, "msg [happy]", None, None)
        assert f.filter(rec) is True
        assert "[happy]" not in rec.msg


# ---------- RollingWindowMemory ----------

class TestRollingWindowMemory:
    def test_truncate_keeps_system(self):
        m = RollingWindowMemory(session_id="m1", max_tokens=50)
        m.set_layers(base="老师", course_context="数学 分数")
        for i in range(20):
            m.add("user", f"这是第 {i} 条比较长的学生发言内容用于触发截断")
        msgs = m.build_messages()
        assert msgs[0]["role"] == "system"
        assert len(m._msgs) <= 20

    def test_build_system_prompt_layers(self):
        m = RollingWindowMemory(session_id="m2")
        m.set_layers(base="老师", persona="耐心", course_context="分数", level="C")
        sp = m.build_system_prompt()
        assert "老师" in sp and "分数" in sp and "耐心" in sp and "C" in sp

    def test_add_rag_sticky(self):
        m = RollingWindowMemory(session_id="m3", max_tokens=10)
        m.add_rag("知识片段")
        assert any(x.sticky and "知识片段" in x.content for x in m._msgs)

    def test_build_messages(self):
        m = RollingWindowMemory(session_id="m4")
        m.add("user", "你好")
        m.add("assistant", "你好同学")
        msgs = m.build_messages()
        assert msgs[0]["role"] == "system"
        roles = [x["role"] for x in msgs[1:]]
        assert roles == ["user", "assistant"]


# ---------- ContentInjector ----------

class _FakeStep:
    def __init__(self, i: int) -> None:
        self.step_id = f"s{i}"
        self.step_title = f"步骤{i}"
        self.speech_narration = f"讲解内容{i} [curious]"
        self.phase = "Explain"
        self.checkpoint = None


class _FakeDSL:
    def __init__(self, n: int) -> None:
        self.steps = [_FakeStep(i) for i in range(n)]
        self.error = ""


class _FakeTutor:
    async def generate_lesson_script(self, **kw: Any) -> _FakeDSL:
        return _FakeDSL(3)


class _FakeSubjectModule:
    subject_id = "math"
    display_name = "数学"
    has_socratic_tutor = True
    def socratic_tutor(self) -> _FakeTutor:
        return _FakeTutor()


class _FakeRegistry:
    def get(self, subject_id: str) -> _FakeSubjectModule:
        return _FakeSubjectModule()


class _FakePage:
    def __init__(self, i: int) -> None:
        self.page_index = i
        self.title = f"页{i}"
        self.narration = f"旁白{i} [happy]"
        self.emotion_tag = "happy"
        self.question_point = {"id": f"q{i}"}


class _FakeScript:
    def __init__(self, n: int) -> None:
        self.pages = [_FakePage(i) for i in range(n)]


class _FakeScripter:
    async def generate(self, subject: str, grade: str, topic: str, lesson_plan: dict) -> _FakeScript:
        return _FakeScript(2)


class TestContentInjector:
    @pytest.mark.asyncio
    async def test_course_path(self):
        ci = ContentInjector(_FakeRegistry(), None)
        segs = await ci.load_lesson("math", "分数", "3", layer="B")
        assert len(segs) == 3
        assert isinstance(segs[0], NarrationSegment)
        assert segs[0].text == "讲解内容0 [curious]"
        assert segs[0].phase == "Explain"

    @pytest.mark.asyncio
    async def test_classroom_path_fallback(self):
        ci = ContentInjector(None, _FakeScripter())
        segs = await ci.load_lesson("math", "分数", "3", lesson_plan={})
        assert len(segs) == 2
        assert segs[0].emotion == "happy"

    @pytest.mark.asyncio
    async def test_no_source_returns_empty(self):
        ci = ContentInjector(None, None)
        segs = await ci.load_lesson("math", "分数", "3")
        assert segs == []

    def test_build_course_context(self):
        ci = ContentInjector(_FakeRegistry(), None)
        ctx = ci.build_course_context("math", "分数", "3", ["整数"], ["分母为0"])
        assert "分数" in ctx and "整数" in ctx and "分母为0" in ctx


# ---------- Mock Plugins ----------

class MockTTS(TTSPlugin):
    name = "mock_tts"
    def __init__(self) -> None:
        self.speed = 1.0
        self.synth_calls: list[str] = []
    def set_speed(self, s: float) -> None:
        self.speed = s
    async def synthesize(self, text: str, emotion: str = "neutral") -> bytes:
        self.synth_calls.append(text)
        return b"\x00" * 100


class MockLLM(LLMPlugin):
    name = "mock_llm"
    def __init__(self, reply: str = "好的同学") -> None:
        self.reply = reply
    async def stream(self, messages: list[dict[str, str]]):
        for ch in self.reply:
            yield ch


class MockASR(ASRPlugin):
    name = "mock_asr"
    async def transcribe(self, pcm: bytes) -> str:
        return "什么是分数"


# ---------- Session ----------

class TestDigitalHumanSession:
    @pytest.mark.asyncio
    async def test_narrate_drives_fsm(self):
        from fusion_k12_teacher.digital_human.session import DigitalHumanSession
        ci = ContentInjector(_FakeRegistry(), None)
        sess = DigitalHumanSession(
            "s1", "math", "分数", "3",
            content=ci, tts=MockTTS(), llm=MockLLM(), asr=MockASR(),
            avatar=StaticAvatar("s1"), idle_timeout=9999,
        )
        n = await sess.start()
        assert n == 3
        res = await sess.narrate_page(0)
        assert res["idx"] == 0
        assert res["emotion"] == "curious"
        assert sess.fsm.state is SessionState.IDLE
        await sess.finish()

    @pytest.mark.asyncio
    async def test_student_speech_qa_flow(self):
        from fusion_k12_teacher.digital_human.session import DigitalHumanSession
        ci = ContentInjector(_FakeRegistry(), None)
        sess = DigitalHumanSession(
            "s2", "math", "分数", "3",
            content=ci, tts=MockTTS(), llm=MockLLM("分数是..."), asr=MockASR(),
            avatar=StaticAvatar("s2"), idle_timeout=9999,
        )
        await sess.start()
        res = await sess.on_student_speech(b"\x00" * 50)
        assert res["question"] == "什么是分数"
        assert "分数" in res["answer"]
        assert sess.fsm.state is SessionState.IDLE
        await sess.finish()

    @pytest.mark.asyncio
    async def test_narrate_out_of_range(self):
        from fusion_k12_teacher.digital_human.session import DigitalHumanSession
        ci = ContentInjector(_FakeRegistry(), None)
        sess = DigitalHumanSession(
            "s3", "math", "分数", "3",
            content=ci, avatar=StaticAvatar("s3"), idle_timeout=9999,
        )
        await sess.start()
        res = await sess.narrate_page(99)
        assert "error" in res
        await sess.finish()

    @pytest.mark.asyncio
    async def test_barge_in_cancels_narration(self):
        from fusion_k12_teacher.digital_human.session import DigitalHumanSession

        class SlowTTS(TTSPlugin):
            name = "slow_tts"
            async def synthesize(self, text: str, emotion: str = "neutral") -> bytes:
                await asyncio.sleep(5)
                return b"\x00"

        ci = ContentInjector(_FakeRegistry(), None)
        sess = DigitalHumanSession(
            "s4", "math", "分数", "3",
            content=ci, tts=SlowTTS(), avatar=StaticAvatar("s4"), idle_timeout=9999,
        )
        await sess.start()
        task = asyncio.create_task(sess.narrate_page(0))
        await asyncio.sleep(0.05)
        await sess.bus.fire("student_barge")
        with pytest.raises(asyncio.CancelledError):
            await task
        assert sess.fsm.state is SessionState.IDLE
        await sess.finish()

    @pytest.mark.asyncio
    async def test_student_speech_barge_in_during_narration(self):
        from fusion_k12_teacher.digital_human.session import DigitalHumanSession

        class SlowTTS(TTSPlugin):
            name = "slow_tts"
            async def synthesize(self, text: str, emotion: str = "neutral") -> bytes:
                await asyncio.sleep(5)
                return b"\x00"

        ci = ContentInjector(_FakeRegistry(), None)
        sess = DigitalHumanSession(
            "s5", "math", "分数", "3",
            content=ci, tts=SlowTTS(), llm=MockLLM("分数是整体的一部分"),
            asr=MockASR(), avatar=StaticAvatar("s5"), idle_timeout=9999,
        )
        await sess.start()
        task = asyncio.create_task(sess.narrate_page(0))
        await asyncio.sleep(0.05)
        res = await sess.on_student_speech(b"\x00" * 30)
        assert task.done()
        assert res["question"] == "什么是分数"
        assert sess.fsm.state is SessionState.IDLE
        await sess.finish()

    @pytest.mark.asyncio
    async def test_page_manifest(self):
        from fusion_k12_teacher.digital_human.session import DigitalHumanSession
        ci = ContentInjector(_FakeRegistry(), None)
        sess = DigitalHumanSession(
            "s6", "math", "分数", "3",
            content=ci, avatar=StaticAvatar("s6"), idle_timeout=9999,
        )
        await sess.start()
        manifest = sess.page_manifest()
        assert len(manifest) == 3
        assert manifest[0]["text"] == "讲解内容0 [curious]"
        await sess.finish()


# ---------- StaticAvatar degradation ----------

class TestStaticAvatar:
    @pytest.mark.asyncio
    async def test_always_available(self):
        av = StaticAvatar("d1")
        assert av.available is True
        frames = await av.generate_idle_frames()
        assert len(frames) >= 1

    @pytest.mark.asyncio
    async def test_render_caches(self):
        av = StaticAvatar("d2")
        f1 = await av.render("hello", b"", "neutral")
        assert av.cached_frames("hello") is f1 or av.cached_frames("hello") == f1
        assert av.is_rendering("hello") is False


# ---------- LiveKitAdapter ----------

class TestLiveKitAdapter:
    def test_sign_token_requires_config(self):
        from fusion_k12_teacher.digital_human.livekit_adapter import LiveKitAdapter
        ad = LiveKitAdapter("l1")
        if ad.available:
            tok = ad.sign_token("student1", "room1")
            assert isinstance(tok, str) and len(tok) > 10
        else:
            with pytest.raises(RuntimeError):
                ad.sign_token("x", "y")

    def test_unavailable_when_no_config(self):
        import os

        import fusion_k12_teacher.digital_human.livekit_adapter as mod
        from fusion_k12_teacher.digital_human.livekit_adapter import LiveKitAdapter
        saved = (os.environ.get("FUSION_K12_LIVEKIT_API_KEY"),
                 os.environ.get("FUSION_K12_LIVEKIT_API_SECRET"))
        os.environ.pop("FUSION_K12_LIVEKIT_API_KEY", None)
        os.environ.pop("FUSION_K12_LIVEKIT_API_SECRET", None)
        saved_load = mod._load_linguakids_env
        mod._load_linguakids_env = lambda: ("", "", "")
        try:
            ad = LiveKitAdapter("l2")
            assert ad.available is False
        finally:
            mod._load_linguakids_env = saved_load
            if saved[0]:
                os.environ["FUSION_K12_LIVEKIT_API_KEY"] = saved[0]
            if saved[1]:
                os.environ["FUSION_K12_LIVEKIT_API_SECRET"] = saved[1]


# ---------- Simulation 3-stage barge-in ----------

class TestSimulationStages:
    def test_three_stages_cascade(self):
        from fusion_k12_teacher.digital_human.simulation import IdleMotion
        sim = IdleMotion("sim1")
        lips0, eyes0, head0 = sim.barge_in_stages(0.0)
        assert lips0 < 0.01 and eyes0 == 0.0 and head0 == 0.0
        # 20ms: lips mid, eyes/head not started
        lips20, eyes20, head20 = sim.barge_in_stages(20.0)
        assert 0.0 < lips20 < 1.0
        assert eyes20 == 0.0
        assert head20 == 0.0
        # 60ms: lips done, eyes mid, head not started
        lips60, eyes60, head60 = sim.barge_in_stages(60.0)
        assert lips60 == 1.0
        assert 0.0 < eyes60 < 1.0
        assert head60 == 0.0
        # 150ms: all done
        lips150, eyes150, head150 = sim.barge_in_stages(150.0)
        assert lips150 == 1.0 and eyes150 == 1.0 and head150 == 1.0



# ---------- MuseTalk degradation ----------

class TestMuseTalkAvatar:
    @pytest.mark.asyncio
    async def test_init_graceful_and_render_degrades(self):
        from fusion_k12_teacher.digital_human.plugins.avatar_musetalk import MuseTalkAvatar
        av = MuseTalkAvatar("m1")
        await av.init()
        assert isinstance(av.available, bool)
        frames = await av.render("hi", b"", "neutral")
        assert isinstance(frames, list)

    @pytest.mark.asyncio
    async def test_cancel_and_clear(self):
        from fusion_k12_teacher.digital_human.plugins.avatar_musetalk import MuseTalkAvatar
        av = MuseTalkAvatar("m2")
        await av.cancel_render()
        av.clear()
        assert av.is_rendering("x") is False


# ---------- Real plugins (mock mlx) ----------

class _MockMlxClient:
    async def speech(self, text, **kw):
        return b"\x00" * 50
    async def transcribe(self, audio, **kw):
        return "你好老师"
    async def chat_stream(self, messages, **kw):
        class _Resp:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): pass
            async def aiter_lines(self):
                yield 'data: {"choices":[{"delta":{"content":"好的"}}]}'
                yield 'data: [DONE]'
        return _Resp()


class TestRealPlugins:
    @pytest.mark.asyncio
    async def test_kokoro_tts(self):
        from fusion_k12_teacher.digital_human.plugins.tts_kokoro import KokoroTTS
        tts = KokoroTTS(_MockMlxClient())
        await tts.init()
        assert tts.available is True
        wav = await tts.synthesize("你好", "happy")
        assert len(wav) == 50

    @pytest.mark.asyncio
    async def test_mlx_llm_stream(self):
        from fusion_k12_teacher.digital_human.plugins.llm_mlx import MlxLLM
        llm = MlxLLM(_MockMlxClient())
        await llm.init()
        assert llm.available is True
        chunks = [c async for c in llm.stream([{"role": "user", "content": "hi"}])]
        assert "好的" in "".join(chunks)

    @pytest.mark.asyncio
    async def test_mlx_asr(self):
        from fusion_k12_teacher.digital_human.plugins.asr_mlx import MlxWhisperASR
        asr = MlxWhisperASR(_MockMlxClient())
        await asr.init()
        assert asr.available is True
        text = await asr.transcribe(b"\x00" * 20)
        assert text == "你好老师"


# ---------- Manager ----------

class TestDigitalHumanManager:
    @pytest.mark.asyncio
    async def test_prewarm_and_create_session(self):
        from fusion_k12_teacher.digital_human.manager import DigitalHumanManager
        mgr = DigitalHumanManager(_MockMlxClient(), _FakeRegistry(), None, None)
        await mgr.start()
        assert mgr._avatar is not None
        assert mgr._tts is not None
        assert mgr._llm is not None
        sess = await mgr.create_session("math", "分数", "3")
        assert sess.page_count == 3
        assert sess.fsm.state.value == "idle"
        await mgr.aclose()

    @pytest.mark.asyncio
    async def test_finish_releases_gate(self):
        from fusion_k12_teacher.digital_human.manager import DigitalHumanManager
        mgr = DigitalHumanManager(_MockMlxClient(), _FakeRegistry(), None, None, max_sessions=2)
        await mgr.start()
        sess = await mgr.create_session("math", "分数", "3")
        res = await mgr.finish(sess.session_id)
        assert res["finished"] is True
        assert mgr.get(sess.session_id) is None
        await mgr.aclose()

    @pytest.mark.asyncio
    async def test_gate_timeout_rejects_when_full(self):
        # gate 耗尽时 create_session 快失败, 不永久阻塞 (issue: 忘 finish 致第11课挂死)
        import fusion_k12_teacher.digital_human.manager as mod
        old = mod._GATE_TIMEOUT
        mod._GATE_TIMEOUT = 0.5
        try:
            mgr = mod.DigitalHumanManager(_MockMlxClient(), _FakeRegistry(), None, None, max_sessions=1)
            await mgr.start()
            await mgr.create_session("math", "分数", "3")  # 占满唯一闸门
            with pytest.raises(RuntimeError, match="并发已满"):
                await mgr.create_session("math", "另一题", "3")
        finally:
            mod._GATE_TIMEOUT = old
