"""Agent 模块测试 — models / executor / tasks / scheduler。"""

import asyncio
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fusion_k12_teacher.agent.executor import (
    EngineRegistry,
    execute_step,
    execute_task,
    registry,
)
from fusion_k12_teacher.agent.models import TaskResult, TaskStep, TeachingTask
from fusion_k12_teacher.agent.scheduler import TaskScheduler
from fusion_k12_teacher.agent.tasks import build_task, list_available_tasks

# ─── Models ────────────────────────────────────────────


class TestTaskStep:
    def test_create(self):
        step = TaskStep(engine="curriculum", method="generate_lesson_plan", params={"subject": "数学"}, output_key="plan")
        assert step.engine == "curriculum"
        assert step.method == "generate_lesson_plan"
        assert step.params == {"subject": "数学"}
        assert step.output_key == "plan"
        assert step.depends_on == []

    def test_to_dict_from_dict(self):
        step = TaskStep(engine="assessment", method="grade_essay", params={"text": "hello"}, output_key="grade", depends_on=["step1"])
        d = step.to_dict()
        assert d["engine"] == "assessment"
        assert d["depends_on"] == ["step1"]
        step2 = TaskStep.from_dict(d)
        assert step2.engine == step.engine
        assert step2.depends_on == step.depends_on


class TestTeachingTask:
    def test_create(self):
        step = TaskStep(engine="curriculum", method="generate_lesson_plan", params={}, output_key="p")
        task = TeachingTask(id="t1", name="test", task_type="manual", steps=[step])
        assert task.id == "t1"
        assert task.enabled is True
        assert task.last_run == ""

    def test_to_dict_from_dict(self):
        step = TaskStep(engine="curriculum", method="generate_lesson_plan", params={}, output_key="p")
        task = TeachingTask(id="t1", name="test", task_type="manual", steps=[step], schedule="0 8 * * 1")
        d = task.to_dict()
        task2 = TeachingTask.from_dict(d)
        assert task2.id == task.id
        assert task2.schedule == task.schedule
        assert len(task2.steps) == 1


class TestTaskResult:
    def test_create(self):
        r = TaskResult(task_id="t1", status="success", summary="ok")
        assert r.task_id == "t1"
        assert r.status == "success"
        assert r.step_results == {}

    def test_to_dict_from_dict(self):
        r = TaskResult(task_id="t1", status="success", step_results={"key": "val"}, summary="done")
        d = r.to_dict()
        r2 = TaskResult.from_dict(d)
        assert r2.task_id == r.task_id
        assert r2.step_results == r.step_results


# ─── Executor ──────────────────────────────────────────


class TestEngineRegistry:
    def test_register_and_get(self):
        reg = EngineRegistry()
        mock_engine = MagicMock()
        reg.register("test_engine", mock_engine)
        assert reg.get("test_engine") is mock_engine

    def test_get_missing(self):
        reg = EngineRegistry()
        assert reg.get("no_such") is None

    def test_list_names(self):
        reg = EngineRegistry()
        reg.register("a", MagicMock())
        reg.register("b", MagicMock())
        assert set(reg.list_names()) == {"a", "b"}


class TestExecuteStep:
    def test_execute_step_simple(self):
        # AGT-1: 须用白名单内的 engine+method, 否则被方法授权拦截
        # TEST-8: try/finally 保清理, 失败也勿泄漏全局 registry 单例
        mock_engine = MagicMock()
        mock_engine.generate_lesson_plan = AsyncMock(return_value={"result": "ok"})
        registry.register("curriculum", mock_engine)
        try:
            step = TaskStep(engine="curriculum", method="generate_lesson_plan", params={"x": 1}, output_key="out")
            context = {}
            result = asyncio.run(execute_step(step, context))
            assert result == {"result": "ok"}
            assert context["out"] == {"result": "ok"}
        finally:
            registry._engines.pop("curriculum", None)

    def test_execute_step_variable_resolution(self):
        # AGT-1: 须用白名单内的 engine+method
        # TEST-8: try/finally 保清理
        mock_engine = MagicMock()
        mock_engine.generate_quiz = AsyncMock(return_value={"processed": True})
        registry.register("curriculum", mock_engine)
        try:
            step = TaskStep(engine="curriculum", method="generate_quiz", params={"data": "$prev_result"}, output_key="out")
            context = {"prev_result": "some_data"}
            asyncio.run(execute_step(step, context))
            mock_engine.generate_quiz.assert_called_once_with(data="some_data")
        finally:
            registry._engines.pop("curriculum", None)

    def test_execute_step_missing_engine(self):
        step = TaskStep(engine="_missing", method="foo", params={}, output_key="out")
        context = {}
        with pytest.raises(ValueError, match="引擎未注册"):
            asyncio.run(execute_step(step, context))


class TestExecuteTask:
    def test_execute_task_single_step(self):
        # AGT-1: 须用白名单内的 engine+method
        # TEST-8: try/finally 保清理
        mock_engine = MagicMock()
        mock_engine.grade_essay = AsyncMock(return_value={"done": True})
        registry.register("assessment", mock_engine)
        try:
            step = TaskStep(engine="assessment", method="grade_essay", params={}, output_key="result")
            task = TeachingTask(id="t1", name="test", task_type="manual", steps=[step])
            result = asyncio.run(execute_task(task))
            assert result.status == "success"
        finally:
            registry._engines.pop("assessment", None)

    def test_execute_task_step_failure(self):
        # TEST-8: try/finally 保清理
        mock_engine = MagicMock()
        mock_engine.fail_method = AsyncMock(side_effect=Exception("boom"))
        registry.register("_test_eng4", mock_engine)
        try:
            step = TaskStep(engine="_test_eng4", method="fail_method", params={}, output_key="out")
            task = TeachingTask(id="t1", name="test", task_type="manual", steps=[step])
            result = asyncio.run(execute_task(task))
            assert result.status == "failed"
        finally:
            registry._engines.pop("_test_eng4", None)

    def test_execute_task_depends_on_unmet(self):
        step = TaskStep(engine="x", method="y", params={}, output_key="o", depends_on=["missing_dep"])
        task = TeachingTask(id="t1", name="test", task_type="manual", steps=[step])
        result = asyncio.run(execute_task(task))
        assert result.status == "failed"


# ─── Tasks (预定义) ────────────────────────────────────


class TestPredefinedTasks:
    def test_list_available_tasks(self):
        tasks = list_available_tasks()
        assert isinstance(tasks, dict)
        assert len(tasks) >= 5

    def test_build_task_weekly_prep(self):
        task = build_task("weekly_prep", subject="数学", grade=3)
        assert task.name == "每周备课材料生成"
        assert len(task.steps) == 3
        assert task.task_type == "scheduled"

    def test_build_task_weekly_summary(self):
        task = build_task("weekly_summary")
        assert task.name == "班级学情周报"
        assert len(task.steps) == 3

    def test_build_task_daily_homework_review(self):
        task = build_task("daily_homework_review", subject="语文", grade=4)
        assert task.name == "每日作业错题补救"
        assert len(task.steps) == 2

    def test_build_task_monthly_report(self):
        task = build_task("monthly_report")
        assert task.name == "月度教学报告"
        assert len(task.steps) == 2

    def test_build_task_batch_differentiated(self):
        task = build_task("batch_differentiated_materials", subject="英语", grade=5, topics="阅读,写作")
        assert task.name == "批量分层教学材料"
        assert len(task.steps) == 4  # 2 topics × (lesson + quiz)

    def test_build_task_unknown(self):
        with pytest.raises(ValueError):
            build_task("nonexistent_task")


# ─── Scheduler ─────────────────────────────────────────


class TestTaskScheduler:
    def test_register_and_list(self):
        s = TaskScheduler()
        step = TaskStep(engine="eng", method="m", params={}, output_key="o")
        task = TeachingTask(id="t1", name="test", task_type="manual", steps=[step])
        s.register_task(task)
        assert len(s.list_tasks()) == 1
        assert s.get_task("t1") is task

    def test_enable_disable(self):
        s = TaskScheduler()
        step = TaskStep(engine="eng", method="m", params={}, output_key="o")
        task = TeachingTask(id="t1", name="test", task_type="manual", steps=[step])
        s.register_task(task)
        assert s.enable_task("t1") is True
        assert task.enabled is True
        assert s.disable_task("t1") is True
        assert task.enabled is False
        assert s.enable_task("nonexistent") is False

    def test_run_task_not_found(self):
        s = TaskScheduler()
        result = asyncio.run(s.run_task("missing"))
        assert result.status == "failed"

    def test_run_task_success(self):
        s = TaskScheduler()
        step = TaskStep(engine="eng", method="work", params={}, output_key="out")
        task = TeachingTask(id="t1", name="test", task_type="manual", steps=[step])
        s.register_task(task)

        with patch("fusion_k12_teacher.agent.scheduler.execute_task", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = TaskResult(task_id="t1", status="success", summary="done")
            result = asyncio.run(s.run_task("t1"))
            assert result.status == "success"

    def test_get_history(self):
        s = TaskScheduler()
        s._history = [TaskResult(task_id=f"t{i}", status="success", summary="") for i in range(5)]
        hist = s.get_history(limit=3)
        assert len(hist) == 3

    def test_load_default_tasks(self):
        s = TaskScheduler()
        s.load_default_tasks(subject="数学", grade=3)
        assert len(s.list_tasks()) >= 5

    def test_start_stop(self):
        s = TaskScheduler()
        s.start()
        assert s.is_running() is True
        s.stop()
        assert s.is_running() is False

    def test_start_idempotent(self):
        s = TaskScheduler()
        s.start()
        s.start()
        assert s.is_running() is True
        s.stop()

    def test_parse_cron(self):
        s = TaskScheduler()
        result = s._parse_cron("30 8 * * 1")
        assert result == {"minute": "30", "hour": "8", "day_of_week": "1"}

    def test_parse_cron_all_wildcard(self):
        s = TaskScheduler()
        result = s._parse_cron("* * * * *")
        assert result == {}

    def test_save_and_load_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "history.json")
            s = TaskScheduler()
            s._history_path = path
            s._history = [TaskResult(task_id="t1", status="success", summary="ok")]
            s._save_history()
            assert os.path.exists(path)

            s2 = TaskScheduler()
            s2._history_path = path
            s2.load_history()
            assert len(s2._history) == 1
            assert s2._history[0].task_id == "t1"
