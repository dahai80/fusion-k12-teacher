"""Fusion-K12-Teacher CLI entry point."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os

import click

from . import __app_name__, __version__
from .agent import list_available_tasks, register_all_engines, scheduler
from .analytics import load_from_csv, load_from_json
from .analytics.models import WeakPoint
from .desensitize import DataAnonymizer, DesensitizeConfig
from .engines import build_engines
from .safety import ContentFilter, SensitiveWordList

logger = logging.getLogger(__name__)


def _join_str(items, sep: str = ", ") -> str:
    # CLI-1: list items from the LLM may be non-str (int/dict/None); filter + cast to str before join to prevent TypeError
    if not items:
        return ""
    return sep.join(str(x) for x in items if x is not None)


def _atomic_write_json(path: str, data, indent: int = 2) -> None:
    """CLI-4: atomic JSON write — write .tmp first then os.replace, with SRV-3 O_NOFOLLOW.

    A crash mid-write leaves only the .tmp temp file; the target keeps its old value or does not exist, never a half-written file.
    """
    import json as _json
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False, indent=indent)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _check_engine_result(result, label: str) -> None:
    # CLI-2: when an engine degrades gracefully to a dataclass/None carrying .error, exit with ClickException code 1 instead of a silent 0
    if result is None:
        raise click.ClickException(f"{label} generation failed: engine returned empty")
    err = getattr(result, "error", None)
    if not err and isinstance(result, dict):
        err = result.get("error")
    if err:
        raise click.ClickException(f"{label} generation failed: {err}")


@click.group()
@click.option("--verbose", "-v", is_flag=True)
@click.option("--model", "-m", default="", help="fusion-mlx model")
@click.version_option(version=__version__, prog_name=__app_name__)
@click.pass_context
def cli(ctx, verbose, model):
    """Fusion-K12-Teacher — Local AI-powered K-12 education assistant."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)-8s %(message)s")
    ctx.ensure_object(dict)
    bundle = build_engines(model=model)
    # A14: registration separated from construction — the factory no longer registers as a side effect; register the global registry explicitly here
    register_all_engines(bundle=bundle)
    ctx.obj["mlx"] = bundle.mlx
    ctx.obj["curriculum"] = bundle.curriculum
    ctx.obj["assessment"] = bundle.assessment
    ctx.obj["subjects"] = bundle.subjects
    ctx.obj["personalization"] = bundle.personalization
    ctx.obj["content"] = bundle.content
    ctx.obj["differentiation"] = bundle.differentiation
    ctx.obj["standards_query"] = bundle.standards_query
    ctx.obj["standards_loader"] = bundle.standards_loader
    ctx.obj["analytics"] = bundle.analytics


# ── Curriculum ──

@cli.group()
def lesson():
    """Lesson planning and management."""


@lesson.command("plan")
@click.argument("subject")
@click.argument("grade")
@click.argument("topic")
# i18n: user-facing
@click.option("--duration", default=45, help="课时(分钟)")
@click.pass_context
def lesson_plan(ctx, subject, grade, topic, duration):
    """Generate a lesson plan."""
    asyncio.run(_async_lesson_plan(ctx, subject, grade, topic, duration))


async def _async_lesson_plan(ctx, subject, grade, topic, duration):
    engine = ctx.obj["curriculum"]
    plan = await engine.generate_lesson_plan(subject, grade, topic, duration)
    _check_engine_result(plan, "lesson plan")
    click.echo()
    click.echo(f"📚 {plan.title}")
    # i18n: user-facing
    click.echo(f"   学科: {plan.subject} | 年级: {plan.grade} | 课时: {plan.duration_minutes}分钟")
    # i18n: user-facing
    click.echo(f"   目标: {_join_str(plan.objectives[:3])}")
    # i18n: user-facing
    click.echo(f"   评估: {plan.assessment[:100]}")
    click.echo()


@lesson.command("quiz")
@click.argument("subject")
@click.argument("grade")
@click.argument("topic")
# i18n: user-facing
@click.option("--questions", "-n", default=5, help="题目数量")
@click.pass_context
def lesson_quiz(ctx, subject, grade, topic, questions):
    """Generate a quiz."""
    asyncio.run(_async_lesson_quiz(ctx, subject, grade, topic, questions))


async def _async_lesson_quiz(ctx, subject, grade, topic, questions):
    engine = ctx.obj["curriculum"]
    quiz = await engine.generate_quiz(subject, grade, topic, questions)
    _check_engine_result(quiz, "quiz")
    click.echo()
    click.echo(f"📝 {quiz.title}")
    # i18n: user-facing
    click.echo(f"   总分: {quiz.total_points}")
    for q in quiz.questions[:3]:
        click.echo(f"   Q: {q.get('question', '')[:100]}")
    click.echo()


# ── Assessment ──

@cli.group()
def assess():
    """Assignment grading and assessment."""


@assess.command("essay")
@click.argument("essay_text")
@click.pass_context
def assess_essay(ctx, essay_text):
    """Grade an essay."""
    asyncio.run(_async_assess_essay(ctx, essay_text))


async def _async_assess_essay(ctx, essay_text):
    engine = ctx.obj["assessment"]
    result = await engine.grade_essay(essay_text)
    _check_engine_result(result, "essay grading")
    click.echo()
    # i18n: user-facing
    click.echo(f"📊 评分: {result.score}/{result.total} ({result.percentage:.0f}%)")
    if result.strengths:
        # i18n: user-facing
        click.echo(f"   优点: {_join_str(result.strengths[:3])}")
    if result.improvements:
        # i18n: user-facing
        click.echo(f"   建议: {_join_str(result.improvements[:3])}")
    click.echo()


# ── Subjects ──

@cli.group()
def subject():
    """Subject knowledge Q&A and exercises."""


@subject.command("explain")
@click.argument("subject_name")
@click.argument("grade")
@click.argument("concept")
@click.pass_context
def subject_explain(ctx, subject_name, grade, concept):
    """Explain a concept."""
    asyncio.run(_async_subject_explain(ctx, subject_name, grade, concept))


async def _async_subject_explain(ctx, subject_name, grade, concept):
    engine = ctx.obj["subjects"]
    result = await engine.explain_concept(subject_name, grade, concept)
    _check_engine_result(result, "concept explanation")
    click.echo()
    click.echo(f"📖 {concept}")
    click.echo(f"   {result.get('simple_explanation', '')[:200]}")
    if result.get('example'):
        # i18n: user-facing
        click.echo(f"   📌 例子: {result['example'][:100]}")
    click.echo()


# ── Personalization ──

@cli.group()
def personalize():
    """Personalized learning."""


@personalize.command("path")
@click.argument("student")
@click.argument("grade")
@click.argument("subject")
@click.argument("goal")
@click.pass_context
def personalize_path(ctx, student, grade, subject, goal):
    """Create a learning path."""
    asyncio.run(_async_personalize_path(ctx, student, grade, subject, goal))


async def _async_personalize_path(ctx, student, grade, subject, goal):
    engine = ctx.obj["personalization"]
    path = await engine.create_learning_path(student, grade, subject, goal)
    _check_engine_result(path, "learning path")
    click.echo()
    # i18n: user-facing
    click.echo(f"🎯 {student}的个性化学习路径")
    # i18n: user-facing
    click.echo(f"   目标: {_join_str(path.goals[:3])}")
    # i18n: user-facing
    click.echo(f"   预计时长: {path.estimated_duration}")
    click.echo()


# ── Content generation ──

@cli.group()
def content():
    """Teaching material generation."""


@content.command("worksheet")
@click.argument("subject")
@click.argument("grade")
@click.argument("topic")
@click.pass_context
def content_worksheet(ctx, subject, grade, topic):
    """Generate a worksheet."""
    asyncio.run(_async_content_worksheet(ctx, subject, grade, topic))


async def _async_content_worksheet(ctx, subject, grade, topic):
    engine = ctx.obj["content"]
    ws = await engine.generate_worksheet(subject, grade, topic)
    _check_engine_result(ws, "worksheet")
    click.echo()
    click.echo(f"📄 {ws.title}")
    # i18n: user-facing
    click.echo(f"   板块数: {len(ws.sections)}")
    click.echo()


@content.command("worksheet-diff")
@click.argument("subject")
@click.argument("grade")
@click.argument("topic")
# i18n: user-facing
@click.option("--questions", "-n", default=8, help="每层题目数量")
@click.pass_context
def content_worksheet_diff(ctx, subject, grade, topic, questions):
    """Generate a three-tier differentiated worksheet."""
    asyncio.run(_async_content_worksheet_diff(ctx, subject, grade, topic, questions))


async def _async_content_worksheet_diff(ctx, subject, grade, topic, questions):
    engine = ctx.obj["differentiation"]
    result = await engine.generate_differentiated_worksheet(subject, grade, topic, questions)
    _check_engine_result(result, "differentiated worksheet")
    click.echo()
    # i18n: user-facing
    click.echo(f"📄 三层分层工作纸: {result.topic}")
    # i18n: user-facing
    click.echo(f"   学科: {result.subject} | 年级: {result.grade}")
    # E3: layers became a dict; iterate result.layers and display via LEVEL_CONFIGS labels
    from .differentiation.level_config import LEVEL_CONFIGS
    for level_name in result.layers:
        layer = result.layers[level_name]
        label = LEVEL_CONFIGS.get(level_name, {}).get("label", level_name)
        # i18n: user-facing
        click.echo(f"   [{label}] {len(layer.exercises)} 道题")
    click.echo()


@cli.command()
# i18n: user-facing
@click.option("--host", default="127.0.0.1", help="监听地址(仅本地回环, 外部绑定请用反向代理+鉴权)")
# i18n: user-facing
@click.option("--port", default=0, help="监听端口 (0=读 FUSION_K12_PORT env, 默认 11448)")
def serve(host, port):
    """Start the HTTP API server."""
    # Process title shows the service name (recognizable in ps/top), not a bare "python ..." — on macOS
    # exec -a gets argv overwritten by Python.app; setproctitle is the only reliable way
    try:
        import setproctitle
        setproctitle.setproctitle("fusion-k12-teacher-serve")
    except ImportError:
        pass
    # P3: FUSION_K12_PORT env takes effect — deploy.md mentioned it but serve never read it, and the hardcoded CMD 11448 misled operators.
    # #34: the port resolves through fusion_core.config.service_port as a single point — FUSION_K12_TEACHER_PORT
    # wins (config-conventions §1), falls back to legacy FUSION_K12_PORT when unset, zero changes for old deployments.
    if port == 0:
        from ._keys import service_listen_port
        port = service_listen_port(11448)
    if host not in ("127.0.0.1", "localhost", "::1"):
        click.echo("❌ Non-loopback addresses are forbidden; expose the service behind a reverse proxy with auth instead of leaving it wide open")
        raise SystemExit(1)
    # A2: the engine pool is module-level in-process globals; multiple workers each hold a copy, splitting state and doubling memory.
    # Local-first constraints leave no out-of-process shared service, so force single worker + fcntl single-instance lock and reject a second instance.
    # Horizontal scaling first requires external shared state (Redis/DB) + an externalized engine pool, which this architecture does not support.
    import fcntl
    lock_path = os.path.join(os.path.dirname(__file__), ".serve.lock")
    _serve_lock_fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        fcntl.flock(_serve_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        click.echo(f"❌ fusion-k12 serve is already running (lock held at {lock_path}) — the architecture is single-instance, a second process is rejected")
        raise SystemExit(1)
    logger.info("A2: single-instance lock acquired (%s), single-worker mode", lock_path)
    import uvicorn
    uvicorn.run("fusion_k12_teacher.serve:app", host=host, port=port, workers=1)



# ── Curriculum standards ──

@cli.group()
def standards():
    """Curriculum-standard knowledge point queries."""


@standards.command("list")
# i18n: user-facing
@click.option("--subject", "-s", default="", help="学科过滤")
# i18n: user-facing
@click.option("--grade", "-g", default="", help="年级过滤")
@click.pass_context
def standards_list(ctx, subject, grade):
    """List curriculum-standard knowledge points."""
    query = ctx.obj["standards_query"]
    if subject and grade:
        points = query.get_knowledge_points(subject, grade)
    elif subject:
        loader = ctx.obj["standards_loader"]
        all_points = loader.all_points()
        points = [p for p in all_points.values() if p.subject == subject]
    else:
        loader = ctx.obj["standards_loader"]
        all_points = loader.all_points()
        points = list(all_points.values())

    click.echo()
    # i18n: user-facing
    click.echo(f"📋 共 {len(points)} 个知识点")
    for p in points[:20]:
        click.echo(f"   {p.id}: [{p.strand}] {p.topic} ({p.difficulty_level})")
    if len(points) > 20:
        # i18n: user-facing
        click.echo(f"   ... 还有 {len(points) - 20} 个")
    click.echo()


@standards.command("show")
@click.argument("point_id")
@click.pass_context
def standards_show(ctx, point_id):
    """Show knowledge point details."""
    loader = ctx.obj["standards_loader"]
    query = ctx.obj["standards_query"]
    kp = loader.get_point(point_id)
    if not kp:
        click.echo(f"❌ Knowledge point not found: {point_id}")
        return

    click.echo()
    click.echo(f"📌 {kp.topic}")
    click.echo(f"   ID: {kp.id}")
    # i18n: user-facing
    click.echo(f"   学科: {kp.subject} | 年级: {kp.grade} | 领域: {kp.strand}")
    # i18n: user-facing
    click.echo(f"   课标编码: {kp.curriculum_code}")
    # i18n: user-facing
    click.echo(f"   难度: {kp.difficulty_level}")
    # i18n: user-facing
    click.echo(f"   描述: {kp.description}")

    if kp.prerequisites:
        pres = query.get_prerequisites(point_id)
        # i18n: user-facing
        click.echo(f"   前置: {_join_str(p.topic for p in pres)}")

    if kp.progression_next:
        nxts = query.get_progression(point_id)
        # i18n: user-facing
        click.echo(f"   进阶: {_join_str(n.topic for n in nxts)}")

    click.echo()


# ── Differentiated instruction ──

@lesson.command("plan-diff")
@click.argument("subject")
@click.argument("grade")
@click.argument("topic")
# i18n: user-facing
@click.option("--duration", default=45, help="课时(分钟)")
@click.pass_context
def lesson_plan_diff(ctx, subject, grade, topic, duration):
    """Generate a three-tier differentiated lesson plan."""
    asyncio.run(_async_lesson_plan_diff(ctx, subject, grade, topic, duration))


async def _async_lesson_plan_diff(ctx, subject, grade, topic, duration):
    engine = ctx.obj["differentiation"]
    result = await engine.generate_differentiated_lesson(subject, grade, topic, duration)
    _check_engine_result(result, "differentiated lesson plan")
    click.echo()
    # i18n: user-facing
    click.echo(f"📚 三层分层教案: {result.topic}")
    # i18n: user-facing
    click.echo(f"   学科: {result.subject} | 年级: {result.grade}")
    for level_name in ["struggling", "standard", "advanced"]:
        layer = getattr(result, level_name)
        # i18n: user-facing (tier labels shown to teachers)
        label = {"struggling": "学困生", "standard": "中等生", "advanced": "优等生"}[level_name]
        click.echo(f"   [{label}] {layer.explanation[:80]}...")
    for gt in result.group_tasks:
        click.echo(f"   📋 {gt.group_name}: {gt.task_description[:60]}")
    click.echo()


@lesson.command("quiz-diff")
@click.argument("subject")
@click.argument("grade")
@click.argument("topic")
# i18n: user-facing
@click.option("--questions", "-n", default=5, help="每层题目数量")
@click.pass_context
def lesson_quiz_diff(ctx, subject, grade, topic, questions):
    """Generate a three-tier differentiated quiz."""
    asyncio.run(_async_lesson_quiz_diff(ctx, subject, grade, topic, questions))


async def _async_lesson_quiz_diff(ctx, subject, grade, topic, questions):
    engine = ctx.obj["differentiation"]
    result = await engine.generate_differentiated_quiz(subject, grade, topic, questions)
    _check_engine_result(result, "differentiated quiz")
    click.echo()
    # i18n: user-facing
    click.echo(f"📝 三层分层测验: {result.topic}")
    # i18n: user-facing
    click.echo(f"   学科: {result.subject} | 年级: {result.grade}")
    for level_name in ["struggling", "standard", "advanced"]:
        layer = getattr(result, level_name)
        # i18n: user-facing (tier labels shown to teachers)
        label = {"struggling": "学困生", "standard": "中等生", "advanced": "优等生"}[level_name]
        # i18n: user-facing
        click.echo(f"   [{label}] {len(layer.exercises)} 道题")
    click.echo()


# ── Learning analytics ──

@cli.group()
def analytics():
    """Learning analytics and remediation plans."""


@analytics.command("class-profile")
@click.argument("class_id")
@click.argument("subject")
@click.argument("grade")
# i18n: user-facing
@click.option("--data", "-d", default="", help="评估数据文件路径(JSON/CSV)")
@click.pass_context
def analytics_class_profile(ctx, class_id, subject, grade, data):
    """Generate a class learning profile."""
    asyncio.run(_async_class_profile(ctx, class_id, subject, grade, data))


async def _async_class_profile(ctx, class_id, subject, grade, data):
    engine = ctx.obj["analytics"]
    assessments = _load_assessments(data)
    profile = await engine.build_class_profile(class_id, subject, grade, assessments)
    _check_engine_result(profile, "class profile")
    click.echo()
    # i18n: user-facing
    click.echo(f"📊 班级画像: {profile.class_id}")
    # i18n: user-facing
    click.echo(f"   学科: {profile.subject} | 年级: {profile.grade}")
    # i18n: user-facing
    click.echo(f"   学生数: {profile.total_students} | 平均分: {profile.avg_score}")
    # i18n: user-facing
    click.echo(f"   分数分布: {profile.score_distribution}")
    # i18n: user-facing
    click.echo(f"   高风险学生: {sum(1 for v in profile.student_risk_levels.values() if v == 'high')}")
    for wp in profile.weak_knowledge_points[:3]:
        # i18n: user-facing
        click.echo(f"   ⚠️ {wp.knowledge_point_name}: 错误率 {wp.error_rate:.0%}")
    click.echo()


@analytics.command("student-profile")
@click.argument("student_id")
@click.argument("subject")
@click.argument("grade")
# i18n: user-facing
@click.option("--data", "-d", default="", help="评估数据文件路径(JSON/CSV)")
@click.pass_context
def analytics_student_profile(ctx, student_id, subject, grade, data):
    """Generate an individual student profile."""
    asyncio.run(_async_student_profile(ctx, student_id, subject, grade, data))


async def _async_student_profile(ctx, student_id, subject, grade, data):
    engine = ctx.obj["analytics"]
    all_assessments = _load_assessments(data)
    history = [a for a in all_assessments if a.student_id == student_id]
    profile = await engine.build_student_profile(student_id, subject, grade, history)
    _check_engine_result(profile, "student profile")
    click.echo()
    # i18n: user-facing
    click.echo(f"👤 学生画像: {profile.name}({profile.student_id})")
    # i18n: user-facing
    click.echo(f"   学科: {profile.subject} | 年级: {profile.grade}")
    # i18n: user-facing
    click.echo(f"   水平: {profile.overall_level} | 趋势: {profile.learning_trend}")
    if profile.risk_indicators:
        # i18n: user-facing
        click.echo(f"   ⚠️ 风险: {_join_str(profile.risk_indicators)}")
    if profile.recommended_actions:
        # i18n: user-facing
        click.echo(f"   💡 建议: {_join_str(profile.recommended_actions[:3])}")
    click.echo()


@analytics.command("error-analysis")
@click.argument("subject")
@click.argument("grade")
# i18n: user-facing
@click.option("--data", "-d", default="", help="评估数据文件路径(JSON/CSV)")
@click.pass_context
def analytics_error_analysis(ctx, subject, grade, data):
    """Error attribution analysis."""
    asyncio.run(_async_error_analysis(ctx, subject, grade, data))


async def _async_error_analysis(ctx, subject, grade, data):
    engine = ctx.obj["analytics"]
    all_assessments = _load_assessments(data)
    responses = []
    for a in all_assessments:
        responses.extend(a.responses)
    errors = await engine.analyze_errors(subject, grade, responses)
    if errors is None:
        raise click.ClickException("error attribution analysis failed: engine returned empty")
    click.echo()
    # i18n: user-facing
    click.echo(f"🔍 错题归因分析: {subject} {grade}")
    # i18n: user-facing
    click.echo(f"   错误类型数: {len(errors)}")
    for e in errors[:5]:
        click.echo(f"   [{e.error_type}] {e.root_cause[:60]}")
        # i18n: user-facing
        click.echo(f"      补救: {e.remediation[:60]}")
    click.echo()


@analytics.command("remedial")
@click.argument("student_id")
@click.argument("subject")
@click.argument("grade")
# i18n: user-facing
@click.option("--data", "-d", default="", help="评估数据文件路径(JSON/CSV)")
@click.pass_context
def analytics_remedial(ctx, student_id, subject, grade, data):
    """Generate a remedial teaching plan."""
    asyncio.run(_async_remedial(ctx, student_id, subject, grade, data))


async def _async_remedial(ctx, student_id, subject, grade, data):
    engine = ctx.obj["analytics"]
    all_assessments = _load_assessments(data)
    profile = await engine.build_student_profile(student_id, subject, grade,
                                                  [a for a in all_assessments if a.student_id == student_id])
    weak_names = list(profile.knowledge_mastery.keys())[:5]
    weak_points = [
        WeakPoint(
            knowledge_point_id=wn, knowledge_point_name=wn, error_rate=0.5,
        )
        for wn in weak_names
    ]
    plan = await engine.generate_remedial_plan(student_id, subject, grade, weak_points)
    _check_engine_result(plan, "remedial plan")
    click.echo()
    # i18n: user-facing
    click.echo(f"💊 补救方案: {plan.student_id}")
    # i18n: user-facing
    click.echo(f"   薄弱点: {_join_str(wp.knowledge_point_name for wp in plan.weak_points[:3])}")
    # i18n: user-facing
    click.echo(f"   策略: {_join_str(plan.strategies[:3])}")
    # i18n: user-facing
    click.echo(f"   时间线: {plan.timeline}")
    click.echo()


@analytics.command("report")
@click.argument("class_id")
@click.argument("subject")
@click.argument("grade")
# i18n: user-facing
@click.option("--data", "-d", default="", help="评估数据文件路径(JSON/CSV)")
@click.pass_context
def analytics_report(ctx, class_id, subject, grade, data):
    """Generate a class learning report (Markdown)."""
    asyncio.run(_async_report(ctx, class_id, subject, grade, data))


async def _async_report(ctx, class_id, subject, grade, data):
    engine = ctx.obj["analytics"]
    assessments = _load_assessments(data)
    profile = await engine.build_class_profile(class_id, subject, grade, assessments)
    _check_engine_result(profile, "class report")
    report = await engine.generate_class_report(profile)
    if not isinstance(report, str) or not report.strip():
        raise click.ClickException("class report generation failed: engine returned empty")
    click.echo()
    click.echo(report)
    click.echo()


def _load_assessments(path: str):
    if not path:
        return []
    if path.endswith(".csv"):
        return load_from_csv(path)
    return load_from_json(path)


# ── Agent task orchestration ──

@cli.group()
def agent():
    """Task orchestration and automated scheduling."""


@agent.command("tasks")
def agent_tasks():
    """List available predefined tasks."""
    tasks = list_available_tasks()
    click.echo()
    # i18n: user-facing
    click.echo("📋 可用预定义任务:")
    for tid, name in tasks.items():
        click.echo(f"   {tid}: {name}")
    click.echo()


@agent.command("enable")
@click.argument("task_id")
def agent_enable(task_id):
    """Enable a task."""
    if not scheduler.get_task(task_id):
        scheduler.load_default_tasks()
    if scheduler.enable_task(task_id):
        # i18n: user-facing
        click.echo(f"✅ 已启用: {task_id}")
    else:
        # i18n: user-facing
        click.echo(f"❌ 未找到: {task_id}")


@agent.command("disable")
@click.argument("task_id")
def agent_disable(task_id):
    """Disable a task."""
    if scheduler.disable_task(task_id):
        # i18n: user-facing
        click.echo(f"⛔ 已禁用: {task_id}")
    else:
        # i18n: user-facing
        click.echo(f"❌ 未找到: {task_id}")


@agent.command("run")
@click.argument("task_id")
# i18n: user-facing
@click.option("--subject", "-s", default="数学", help="学科")
# i18n: user-facing
@click.option("--grade", "-g", default="3", help="年级")
# i18n: user-facing
@click.option("--data", "data_path", default=None, help="学情数据文件路径 (JSON/CSV)")
def agent_run(task_id, subject, grade, data_path):
    """Run a task immediately — rebuilt from parameters each call, avoiding stale baked-in data (AGT-5)."""
    if not scheduler.get_task(task_id):
        scheduler.load_default_tasks(subject=subject, grade=grade)
    run_kwargs = {"subject": subject, "grade": grade}
    if data_path:
        run_kwargs["data_path"] = data_path
    result = asyncio.run(scheduler.run_task(task_id, **run_kwargs))
    click.echo()
    # i18n: user-facing
    click.echo(f"📌 任务: {result.task_id}")
    # i18n: user-facing
    click.echo(f"   状态: {result.status}")
    # i18n: user-facing
    click.echo(f"   摘要: {result.summary}")
    click.echo()
    if result.status != "success":
        raise click.ClickException(f"task execution failed: {result.summary}")


@agent.command("history")
# i18n: user-facing
@click.option("--limit", "-n", default=10, help="显示条数")
def agent_history(limit):
    """View execution history."""
    history = scheduler.get_history(limit=limit)
    click.echo()
    # i18n: user-facing
    click.echo(f"📜 执行历史 (最近 {limit} 条):")
    for r in history:
        click.echo(f"   [{r.status}] {r.task_id} — {r.summary[:60]}")
    click.echo()


@agent.command("start")
def agent_start():
    """Start the scheduler daemon."""
    scheduler.load_default_tasks()
    scheduler.start()
    # i18n: user-facing
    click.echo("🚀 Agent 调度器已启动，Ctrl+C 退出")
    try:
        import time
        while scheduler.is_running():
            time.sleep(1)
    except KeyboardInterrupt:
        scheduler.stop()
        # i18n: user-facing
        click.echo("🛑 Agent 调度器已停止")


@agent.command("stop")
def agent_stop():
    """Stop the scheduler daemon."""
    scheduler.stop()
    # i18n: user-facing
    click.echo("🛑 Agent 调度器已停止")


# ── Content safety ──

@cli.group()
def safety():
    """Content safety filtering and review."""


@safety.command("check")
@click.argument("text")
# i18n: user-facing
@click.option("--grade", "-g", default="3", help="目标年级")
def safety_check(text, grade):
    """Check text content safety."""
    cf = ContentFilter()
    result = cf.check_text(text, grade)
    click.echo()
    # i18n: user-facing
    click.echo("🛡️ 内容检查结果:")
    # i18n: user-facing
    click.echo(f"   安全: {'✅ 是' if result.is_safe else '❌ 否'}")
    # i18n: user-facing
    click.echo(f"   风险等级: {result.risk_level}")
    if result.flagged_words:
        # i18n: user-facing
        click.echo(f"   敏感词: {_join_str(result.flagged_words)}")
    if result.age_issues:
        # i18n: user-facing
        click.echo(f"   适龄问题: {_join_str(result.age_issues, sep='; ')}")
    # i18n: user-facing
    click.echo(f"   摘要: {result.summary}")
    click.echo()


@safety.command("filter")
@click.argument("text")
def safety_filter(text):
    """Filter sensitive words in text."""
    cf = ContentFilter()
    filtered = cf.filter_sensitive(text)
    click.echo()
    # i18n: user-facing
    click.echo(f"📝 过滤结果: {filtered}")
    click.echo()


@safety.command("wordlist")
# i18n: user-facing
@click.option("--add", "add_word", default="", help="添加敏感词")
# i18n: user-facing
@click.option("--remove", "remove_word", default="", help="移除敏感词")
# i18n: user-facing
@click.option("--list", "list_words", is_flag=True, help="列出所有敏感词")
@click.option(
    "--path", "wl_path", default="",
    # i18n: user-facing
    help="词库文件路径; 默认 ~/.fusion-k12/sensitive_words.txt (避免写只读包目录)",
)
def safety_wordlist(add_word, remove_word, list_words, wl_path):
    """Manage the sensitive-word list."""
    # CLI-3: default to the user data directory, not site-packages inside the package (read-only installs raise PermissionError)
    if not wl_path:
        user_dir = os.path.expanduser("~/.fusion-k12")
        os.makedirs(user_dir, exist_ok=True)
        wl_path = os.path.join(user_dir, "sensitive_words.txt")
    wl = SensitiveWordList(path=wl_path)
    if add_word:
        wl.add(add_word)
        wl.save()
        # i18n: user-facing
        click.echo(f"✅ 已添加: {add_word} (词库: {wl_path})")
    elif remove_word:
        wl.remove(remove_word)
        wl.save()
        # i18n: user-facing
        click.echo(f"⛔ 已移除: {remove_word} (词库: {wl_path})")
    elif list_words:
        words = wl.list_words()
        click.echo()
        # i18n: user-facing
        click.echo(f"📋 敏感词库 ({len(words)} 个) @ {wl_path}")
        for w in words:
            click.echo(f"   {w}")
        click.echo()
    else:
        # i18n: user-facing
        click.echo(f"当前词库: {wl.count} 个敏感词 @ {wl_path}")


# ── Data desensitization ──

@cli.group()
def desensitize():
    """Data masking and anonymization."""


@desensitize.command("anon")
@click.argument("input_file")
# i18n: user-facing
@click.option("--mode", "-m", "mode", default="id", help="匿名模式: id/mask",
              type=click.Choice(["id", "mask"], case_sensitive=False))
# i18n: user-facing
@click.option("--prefix", "-p", default="S", help="ID前缀")
# i18n: user-facing
@click.option("--output", "-o", default="", help="输出文件路径")
def desensitize_anon(input_file, mode, prefix, output):
    """Anonymize records in a JSON file."""
    import json as _json
    try:
        with open(input_file, encoding="utf-8") as f:
            records = _json.load(f)
    except Exception as e:
        click.echo(f"❌ Failed to read file: {e}")
        return
    if not isinstance(records, list):
        click.echo("❌ Input file must be a JSON array")
        return
    cfg = DesensitizeConfig(name_mode=mode, id_prefix=prefix)
    anon = DataAnonymizer(cfg)
    result = anon.anonymize_records(records)
    desensitized = anon.export_desensitized(records)
    # SEC-18: the reverse-anonymization map does not flow with the result; fetch it explicitly via get_name_map()
    name_map = anon.get_name_map()
    click.echo()
    # i18n: user-facing
    click.echo("🔒 脱敏完成:")
    # i18n: user-facing
    click.echo(f"   原始记录: {result.original_count}")
    # i18n: user-facing
    click.echo(f"   脱敏记录: {result.anonymized_count}")
    # i18n: user-facing
    click.echo(f"   名称映射: {len(name_map)} 个")
    # i18n: user-facing
    click.echo(f"   脱敏字段: {_join_str(result.masked_fields)}")
    if output:
        # CLI-4: temp+rename atomic write; a crash mid-write never leaves a half file
        _atomic_write_json(output, desensitized)
        # i18n: user-facing
        click.echo(f"   输出文件: {output}")
    else:
        # i18n: user-facing
        click.echo(f"   脱敏数据: {_json.dumps(desensitized[:1], ensure_ascii=False)[:200]}...")
    click.echo()


@desensitize.command("export")
@click.argument("input_file")
# i18n: user-facing
@click.option("--output", "-o", required=True, help="输出文件路径")
# i18n: user-facing
@click.option("--mode", "-m", "mode", default="id", help="匿名模式: id/mask",
              type=click.Choice(["id", "mask"], case_sensitive=False))
def desensitize_export(input_file, output, mode):
    """Export anonymized data to a file."""
    import json as _json
    try:
        # SRV-3: O_NOFOLLOW prevents symlink-hijacked reads
        fd_in = os.open(input_file, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd_in, encoding="utf-8") as f:
            records = _json.load(f)
    except Exception as e:
        click.echo(f"❌ Failed to read file: {e}")
        return
    if not isinstance(records, list):
        records = [records]
    cfg = DesensitizeConfig(name_mode=mode)
    anon = DataAnonymizer(cfg)
    desensitized = anon.export_desensitized(records)
    # CLI-4: atomic write of anonymized data (temp+rename), with SRV-3 O_NOFOLLOW
    _atomic_write_json(output, desensitized)
    name_map = anon.get_name_map()
    keys_dir = os.path.expanduser("~/.fusion-k12/keys")
    os.makedirs(keys_dir, exist_ok=True)
    os.chmod(keys_dir, 0o700)
    # CLI-6: basename alone does not dedupe — two exports of same-named files in different directories overwrite each other's _map.json, silently losing the first mapping.
    # Use a short hash prefix of the output absolute path + basename to guarantee uniqueness.
    out_abs = os.path.abspath(output)
    out_hash = hashlib.sha1(out_abs.encode("utf-8")).hexdigest()[:8]
    base_name = os.path.basename(output).replace(".json", "")
    map_path = os.path.join(keys_dir, f"{out_hash}_{base_name}_map.json")
    _atomic_write_json(map_path, name_map)
    if os.path.exists(map_path):
        os.chmod(map_path, 0o600)
    logger.warning("reversible mapping table exported to a restricted directory (0600, contains sensitive restoration info; do not store with or transmit alongside the anonymized data): %s", map_path)
    # i18n: user-facing
    click.echo(f"✅ 脱敏数据已导出: {output}")
    # i18n: user-facing
    click.echo(f"✅ 映射表已导出(0600, 独立受限目录): {map_path}")


@cli.command()
# i18n: user-facing
@click.option("--from-db", "from_db", required=True, help="源 SQLite 路径 (standalone)")
# i18n: user-facing
@click.option("--to-dsn", "to_dsn", required=True, help="目标 Postgres DSN (cluster)")
# i18n: user-facing
@click.option("--dry-run", is_flag=True, help="仅预览迁移记录数, 不写入")
# i18n: user-facing
@click.option("--encrypt", is_flag=True, help="M1-T9: name_map 加密导入 (AES-256-GCM, 需 FUSION_K12_DATA_KEY)")
def migrate(from_db, to_dsn, dry_run, encrypt):
    """M1-T3/T9: standalone-to-cluster data migration — export standalone SQLite (history/name_map) and import into Postgres.

    The schema is created by the target backend at construction time (CREATE TABLE IF NOT EXISTS); no Alembic needed.
    Migration is irreversible with no rollback; the source database is read-only and never deleted.
    --encrypt: name_map is written encrypted as name_hash+name_encrypted (PII never stored in plaintext).
    """
    from .repository import SQLiteRepository
    try:
        from .repository import PostgresRepository
    except ImportError as e:
        click.echo(f"❌ Target Postgres backend unavailable: {e}")
        # i18n: user-facing
        click.echo("   安装: pip install -e '.[cluster]'")
        raise SystemExit(1)

    cipher = None
    if encrypt:
        try:
            from .safety import DataCipher
            cipher = DataCipher()
        except ImportError as e:
            click.echo(f"❌ Encryption requires cryptography: {e}")
            # i18n: user-facing
            click.echo("   安装: pip install -e '.[cluster]'")
            raise SystemExit(1)

    src = SQLiteRepository(from_db)
    history = src.load_history()
    name_map, reverse_map = src.load_name_map()
    src.close()
    logger.info("migration source read: history=%d records, name_map=%d records, encrypt=%s", len(history), len(name_map), encrypt)
    # i18n: user-facing
    click.echo(f"📦 源数据: 历史 {len(history)} 条, 脱敏映射 {len(name_map)} 条" + (" (加密导入)" if encrypt else ""))

    if dry_run:
        # i18n: user-facing
        click.echo("🔍 --dry-run: 仅预览, 未写入目标")
        return

    async def _run():
        dst = PostgresRepository(to_dsn)
        await dst.asave_history(history)
        await dst.asave_name_map(name_map, reverse_map, cipher=cipher)
        # Verify: read back and compare (encrypted mode needs the same cipher to decrypt)
        loaded_hist = await dst.aload_history()
        loaded_nm, _ = await dst.aload_name_map(cipher=cipher)
        await dst.aclose()
        return loaded_hist, loaded_nm

    loaded_hist, loaded_nm = asyncio.run(_run())
    ok_hist = len(loaded_hist) == len(history)
    ok_nm = len(loaded_nm) == len(name_map)
    logger.info("migration target verification: history %s, name_map %s", ok_hist, ok_nm)
    if ok_hist and ok_nm:
        # i18n: user-facing
        click.echo(f"✅ 迁移完成: 历史 {len(loaded_hist)} 条, 脱敏映射 {len(loaded_nm)} 条")
    else:
        # i18n: user-facing
        click.echo(f"⚠️ 迁移后数量不符 (历史 {len(loaded_hist)}/{len(history)}, "
                   # i18n: user-facing
                   f"映射 {len(loaded_nm)}/{len(name_map)}) — 请检查目标库")
        raise SystemExit(1)


@cli.command("encrypt-name-map")
# i18n: user-facing
@click.option("--db", "db_path", required=True, help="standalone SQLite 路径")
# i18n: user-facing
@click.option("--dry-run", is_flag=True, help="仅预览待加密条数, 不写入")
def encrypt_name_map(db_path, dry_run):
    """M1-T9: in-place encryption of the legacy plaintext name_map (name_hash + name_encrypted) in a standalone SQLite database.

    Reads the plaintext map_key/reverse and rewrites them into encrypted columns via DataCipher. The original plaintext reverse column is kept
    (progressive migration, decryption failures can fall back); the encrypted column becomes authoritative. Requires FUSION_K12_DATA_KEY.
    """
    try:
        from .safety import DataCipher
        cipher = DataCipher()
    except ImportError as e:
        click.echo(f"❌ Encryption requires cryptography: {e}")
        # i18n: user-facing
        click.echo("   安装: pip install -e '.[cluster]'")
        raise SystemExit(1)

    from .repository import SQLiteRepository
    repo = SQLiteRepository(db_path)
    name_map, reverse_map = repo.load_name_map()
    # i18n: user-facing
    click.echo(f"📦 待加密 name_map: {len(name_map)} 条")
    if dry_run:
        # i18n: user-facing
        click.echo("🔍 --dry-run: 仅预览, 未写入")
        repo.close()
        return
    repo.save_name_map(name_map, reverse_map, cipher=cipher)
    logger.info("name_map in-place encryption completed: %d records", len(name_map))
    # i18n: user-facing
    click.echo(f"✅ name_map 已加密 ({len(name_map)} 条), 明文 reverse 列保留作回退")
    repo.close()


@cli.command("rotate-salt")
# i18n: user-facing
@click.option("--salt-file", "salt_file", default=None, help="salt 文件路径 (默认 ~/.fusion-k12/salt)")
# i18n: user-facing
@click.option("--show-versions", is_flag=True, help="仅列出所有版本, 不轮换")
def rotate_salt(salt_file, show_versions):
    """M1-T8: salt rotation — the current salt is archived as a historical version and a new salt is written to the main file.

    Old versions are kept to resolve historical anonymized IDs (reverse lookup); the new salt applies to subsequent writes.
    After rotation, historical IDs and new IDs differ for the same name — expected behavior.
    """
    from .safety.salt_provider import VersionedSaltProvider

    prov = VersionedSaltProvider(salt_file)
    if show_versions:
        versions = prov.list_versions()
        # i18n: user-facing
        click.echo(f"📋 salt 版本 (共 {len(versions)} 个):")
        for v, s in versions:
            masked = s[:6] + "..." + s[-4:]
            click.echo(f"   v{v}: {masked}")
        return
    new_ver, new_salt = prov.rotate()
    masked = new_salt[:6] + "..." + new_salt[-4:]
    logger.info("salt rotation completed: new version v%d", new_ver)
    # i18n: user-facing
    click.echo(f"✅ salt 已轮换 → v{new_ver}: {masked}")
    # i18n: user-facing
    click.echo("   旧版本已归档, 历史脱敏 ID 仍可解析 (反向回查用旧版本 salt)")


# ── BNUP evaluation harness (issues #23 #24) ──

@cli.group()
def eval():
    """BNUP evaluation harness — four-dimension metrics / before-after comparison / SxS judge."""


@eval.command("bench")
# i18n: user-facing
@click.option("--testset", "-t", default="", help="测试集路径 (默认内置 bnup_benchmark.json)")
def eval_bench(testset):
    """Show benchmark testset statistics."""
    import json as _json
    from pathlib import Path as _P
    path = testset or str(_P(__file__).parent / "eval" / "data" / "bnup_benchmark.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = _json.load(f)
    except Exception as e:
        # i18n: user-facing
        click.echo(f"❌ 读取测试集失败: {e}")
        return
    dist = data.get("distribution", {})
    # i18n: user-facing
    click.echo(f"📊 BNUP 基准测试集: {data.get('total', 0)} 题")
    # i18n: user-facing
    click.echo(f"   域内 (in_domain):   {dist.get('in_domain', 0)} ({dist.get('in_domain_pct', 0)}%)")
    # i18n: user-facing
    click.echo(f"   域外 (ood):         {dist.get('ood', 0)} ({dist.get('ood_pct', 0)}%)")
    # i18n: user-facing
    click.echo(f"   对抗 (adversarial): {dist.get('adversarial', 0)} ({dist.get('adversarial_pct', 0)}%)")
    items = data.get("items", [])
    grades = {}
    vts = {}
    for it in items:
        g = it.get("grade", 0)
        grades[g] = grades.get(g, 0) + 1
        vt = it.get("expected_visual_type", "")
        vts[vt] = vts.get(vt, 0) + 1
    # i18n: user-facing
    click.echo(f"   年级分布: {dict(sorted(grades.items()))}")
    # i18n: user-facing
    click.echo(f"   可视化类型: {dict(sorted(vts.items(), key=lambda x: -x[1]))}")


@eval.command("run")
# i18n: user-facing
@click.option("--testset", "-t", required=True, help="测试集 JSON 路径")
# i18n: user-facing
@click.option("--model", "-m", default="", help="模型名 (空=默认)")
# i18n: user-facing
@click.option("--output", "-o", default="", help="输出报告 JSON 路径")
# i18n: user-facing
@click.option("--system-prompt", "-s", default="", help="自定义 system prompt")
# i18n: user-facing
@click.option("--max-samples", "-n", type=int, default=0, help="最大样本数 (0=全部)")
@click.pass_context
def eval_run(ctx, testset, model, output, system_prompt, max_samples):
    """Run the four-dimension metrics evaluation harness."""
    import asyncio
    import json as _json

    from .course.prompts.bnup_socratic import BNUP_SYSTEM_PROMPT
    from .eval.eval_harness import BNUPEvaluator

    mlx = ctx.obj.get("mlx")
    if mlx is None:
        click.echo("❌ MLXClient not initialized")
        return
    with open(testset, encoding="utf-8") as f:
        data = _json.load(f)
    items = data.get("items", data) if isinstance(data, dict) else data
    if max_samples > 0:
        items = items[:max_samples]
    sys_prompt = system_prompt or BNUP_SYSTEM_PROMPT

    async def _run():
        evaluator = BNUPEvaluator()
        for idx, item in enumerate(items):
            prompt = item.get("question", "")
            gt = float(item.get("ground_truth", 0))
            messages = [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": prompt},
            ]
            try:
                resp = await mlx.chat(messages, temperature=0.1, max_tokens=2048, model=model)
            except Exception as e:
                logger.error("inference failed [%s]: %s", item.get("id", ""), e)
                resp = ""
            evaluator.evaluate_sample(resp, gt, sample_id=item.get("id", f"s{idx+1}"))
            if (idx + 1) % 10 == 0:
                logger.info("eval progress: %d/%d", idx + 1, len(items))
        return evaluator.report

    report = asyncio.run(_run())
    click.echo(report.summary_str())
    if output:
        with open(output, "w", encoding="utf-8") as f:
            _json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
        # i18n: user-facing
        click.echo(f"📄 报告已保存: {output}")


@eval.command("compare")
# i18n: user-facing
@click.option("--testset", "-t", required=True, help="测试集 JSON 路径")
# i18n: user-facing
@click.option("--baseline", "-b", required=True, help="基座模型名")
# i18n: user-facing
@click.option("--finetuned", "-f", required=True, help="增训模型名")
# i18n: user-facing
@click.option("--output", "-o", default="", help="输出对比日志 JSON 路径")
# i18n: user-facing
@click.option("--max-samples", "-n", type=int, default=0, help="最大样本数 (0=全部)")
@click.pass_context
def eval_compare(ctx, testset, baseline, finetuned, output, max_samples):
    """Before/after comparison — baseline vs fine-tuned."""
    import asyncio

    from .eval.compare_models import ModelComparator
    mlx = ctx.obj.get("mlx")
    if mlx is None:
        click.echo("❌ MLXClient not initialized")
        return
    if max_samples > 0:
        import json as _json
        import tempfile
        with open(testset, encoding="utf-8") as f:
            data = _json.load(f)
        items = data.get("items", data) if isinstance(data, dict) else data
        sliced = items[:max_samples]
        if isinstance(data, dict):
            data["items"] = sliced
        else:
            data = sliced
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
        _json.dump(data, tmp, ensure_ascii=False)
        tmp.close()
        testset = tmp.name

    comparator = ModelComparator(mlx, baseline, finetuned)
    report = asyncio.run(comparator.run_comparison(testset, output_log=output))
    click.echo(report.summary_str())


@eval.command("sxs")
# i18n: user-facing
@click.option("--testset", "-t", required=True, help="对比日志 JSON (compare 输出)")
# i18n: user-facing
@click.option("--judge-model", "-j", default="", help="裁判模型名")
# i18n: user-facing
@click.option("--output", "-o", default="", help="输出 SxS 报告 JSON 路径")
# i18n: user-facing
@click.option("--max-samples", "-n", type=int, default=0, help="最大样本数 (0=全部)")
@click.pass_context
def eval_sxs(ctx, testset, judge_model, output, max_samples):
    """SxS double-blind LLM judge."""
    import asyncio
    import json as _json

    from .eval.sxs_judge import SxSJudge
    mlx = ctx.obj.get("mlx")
    if mlx is None:
        click.echo("❌ MLXClient not initialized")
        return
    with open(testset, encoding="utf-8") as f:
        data = _json.load(f)
    results = data.get("results_log", [])
    pairs = []
    for r in results:
        pairs.append({
            "id": r.get("id", ""),
            "prompt": r.get("prompt", ""),
            "output_a": r.get("baseline_output", ""),
            "output_b": r.get("finetuned_output", ""),
        })
    if max_samples > 0:
        pairs = pairs[:max_samples]

    judge = SxSJudge(mlx, judge_model=judge_model)
    agg = asyncio.run(judge.judge_batch(pairs))
    click.echo(agg.summary_str())
    if output:
        with open(output, "w", encoding="utf-8") as f:
            _json.dump(agg.to_dict(), f, ensure_ascii=False, indent=2)
        # i18n: user-facing
        click.echo(f"📄 SxS 报告已保存: {output}")


def main():
    cli()


if __name__ == "__main__":
    main()