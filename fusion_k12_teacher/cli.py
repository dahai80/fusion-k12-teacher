"""Fusion-K12-Teacher CLI 入口。"""

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
    # CLI-1: LLM 返回的列表项可能非 str(int/dict/None), join 前过滤+转 str 防 TypeError
    if not items:
        return ""
    return sep.join(str(x) for x in items if x is not None)


def _atomic_write_json(path: str, data, indent: int = 2) -> None:
    """CLI-4: 原子写 JSON — 先写 .tmp 再 os.replace, 兼 SRV-3 O_NOFOLLOW。

    写中崩溃只留 .tmp 临时文件, 目标文件保持旧值或不存在, 不留半文件。
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
    # CLI-2: 引擎优雅降级返含 error 的 dataclass/None 时, 以 ClickException 退出码 1, 不再静默 0
    if result is None:
        raise click.ClickException(f"{label} 生成失败: 引擎返回空")
    err = getattr(result, "error", None)
    if not err and isinstance(result, dict):
        err = result.get("error")
    if err:
        raise click.ClickException(f"{label} 生成失败: {err}")


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
    # A14: 注册与构造分离 — 工厂不再副作用注册, 此处显式注册全局 registry
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


# ── 课程规划 ──

@cli.group()
def lesson():
    """课程规划与教案管理。"""


@lesson.command("plan")
@click.argument("subject")
@click.argument("grade")
@click.argument("topic")
@click.option("--duration", default=45, help="课时(分钟)")
@click.pass_context
def lesson_plan(ctx, subject, grade, topic, duration):
    """生成教案。"""
    asyncio.run(_async_lesson_plan(ctx, subject, grade, topic, duration))


async def _async_lesson_plan(ctx, subject, grade, topic, duration):
    engine = ctx.obj["curriculum"]
    plan = await engine.generate_lesson_plan(subject, grade, topic, duration)
    _check_engine_result(plan, "教案")
    click.echo()
    click.echo(f"📚 {plan.title}")
    click.echo(f"   学科: {plan.subject} | 年级: {plan.grade} | 课时: {plan.duration_minutes}分钟")
    click.echo(f"   目标: {_join_str(plan.objectives[:3])}")
    click.echo(f"   评估: {plan.assessment[:100]}")
    click.echo()


@lesson.command("quiz")
@click.argument("subject")
@click.argument("grade")
@click.argument("topic")
@click.option("--questions", "-n", default=5, help="题目数量")
@click.pass_context
def lesson_quiz(ctx, subject, grade, topic, questions):
    """生成测验。"""
    asyncio.run(_async_lesson_quiz(ctx, subject, grade, topic, questions))


async def _async_lesson_quiz(ctx, subject, grade, topic, questions):
    engine = ctx.obj["curriculum"]
    quiz = await engine.generate_quiz(subject, grade, topic, questions)
    _check_engine_result(quiz, "测验")
    click.echo()
    click.echo(f"📝 {quiz.title}")
    click.echo(f"   总分: {quiz.total_points}")
    for q in quiz.questions[:3]:
        click.echo(f"   Q: {q.get('question', '')[:100]}")
    click.echo()


# ── 评估 ──

@cli.group()
def assess():
    """作业批改与评估。"""


@assess.command("essay")
@click.argument("essay_text")
@click.pass_context
def assess_essay(ctx, essay_text):
    """批改作文。"""
    asyncio.run(_async_assess_essay(ctx, essay_text))


async def _async_assess_essay(ctx, essay_text):
    engine = ctx.obj["assessment"]
    result = await engine.grade_essay(essay_text)
    _check_engine_result(result, "作文批改")
    click.echo()
    click.echo(f"📊 评分: {result.score}/{result.total} ({result.percentage:.0f}%)")
    if result.strengths:
        click.echo(f"   优点: {_join_str(result.strengths[:3])}")
    if result.improvements:
        click.echo(f"   建议: {_join_str(result.improvements[:3])}")
    click.echo()


# ── 学科 ──

@cli.group()
def subject():
    """学科知识问答与练习。"""


@subject.command("explain")
@click.argument("subject_name")
@click.argument("grade")
@click.argument("concept")
@click.pass_context
def subject_explain(ctx, subject_name, grade, concept):
    """解释概念。"""
    asyncio.run(_async_subject_explain(ctx, subject_name, grade, concept))


async def _async_subject_explain(ctx, subject_name, grade, concept):
    engine = ctx.obj["subjects"]
    result = await engine.explain_concept(subject_name, grade, concept)
    _check_engine_result(result, "概念解释")
    click.echo()
    click.echo(f"📖 {concept}")
    click.echo(f"   {result.get('simple_explanation', '')[:200]}")
    if result.get('example'):
        click.echo(f"   📌 例子: {result['example'][:100]}")
    click.echo()


# ── 个性化 ──

@cli.group()
def personalize():
    """个性化学习。"""


@personalize.command("path")
@click.argument("student")
@click.argument("grade")
@click.argument("subject")
@click.argument("goal")
@click.pass_context
def personalize_path(ctx, student, grade, subject, goal):
    """创建学习路径。"""
    asyncio.run(_async_personalize_path(ctx, student, grade, subject, goal))


async def _async_personalize_path(ctx, student, grade, subject, goal):
    engine = ctx.obj["personalization"]
    path = await engine.create_learning_path(student, grade, subject, goal)
    _check_engine_result(path, "学习路径")
    click.echo()
    click.echo(f"🎯 {student}的个性化学习路径")
    click.echo(f"   目标: {_join_str(path.goals[:3])}")
    click.echo(f"   预计时长: {path.estimated_duration}")
    click.echo()


# ── 内容生成 ──

@cli.group()
def content():
    """教学材料生成。"""


@content.command("worksheet")
@click.argument("subject")
@click.argument("grade")
@click.argument("topic")
@click.pass_context
def content_worksheet(ctx, subject, grade, topic):
    """生成工作纸。"""
    asyncio.run(_async_content_worksheet(ctx, subject, grade, topic))


async def _async_content_worksheet(ctx, subject, grade, topic):
    engine = ctx.obj["content"]
    ws = await engine.generate_worksheet(subject, grade, topic)
    _check_engine_result(ws, "工作纸")
    click.echo()
    click.echo(f"📄 {ws.title}")
    click.echo(f"   板块数: {len(ws.sections)}")
    click.echo()


@content.command("worksheet-diff")
@click.argument("subject")
@click.argument("grade")
@click.argument("topic")
@click.option("--questions", "-n", default=8, help="每层题目数量")
@click.pass_context
def content_worksheet_diff(ctx, subject, grade, topic, questions):
    """生成三层分层工作纸。"""
    asyncio.run(_async_content_worksheet_diff(ctx, subject, grade, topic, questions))


async def _async_content_worksheet_diff(ctx, subject, grade, topic, questions):
    engine = ctx.obj["differentiation"]
    result = await engine.generate_differentiated_worksheet(subject, grade, topic, questions)
    _check_engine_result(result, "分层工作纸")
    click.echo()
    click.echo(f"📄 三层分层工作纸: {result.topic}")
    click.echo(f"   学科: {result.subject} | 年级: {result.grade}")
    # E3: layers 改 dict, 遍历 result.layers 按 LEVEL_CONFIGS label 显示
    from .differentiation.level_config import LEVEL_CONFIGS
    for level_name in result.layers:
        layer = result.layers[level_name]
        label = LEVEL_CONFIGS.get(level_name, {}).get("label", level_name)
        click.echo(f"   [{label}] {len(layer.exercises)} 道题")
    click.echo()


@cli.command()
@click.option("--host", default="127.0.0.1", help="监听地址(仅本地回环, 外部绑定请用反向代理+鉴权)")
@click.option("--port", default=0, help="监听端口 (0=读 FUSION_K12_PORT env, 默认 11448)")
def serve(host, port):
    """启动 HTTP API 服务。"""
    # P3: FUSION_K12_PORT env 生效 — deploy.md 原文档提及但 serve 未读, CMD 硬编码 11448 误导运维。
    if port == 0:
        port = int(os.environ.get("FUSION_K12_PORT", "11448"))
    if host not in ("127.0.0.1", "localhost", "::1"):
        click.echo("❌ 禁止监听非回环地址; 请用反向代理+鉴权暴露服务, 避免裸奔")
        raise SystemExit(1)
    # A2: 引擎池为进程内模块级全局, 多 worker 各持一套致状态分区/内存翻倍。
    # 本地优先约束无进程外共享服务 → 强制单 worker + fcntl 单实例锁, 拒第二实例。
    # 若需横向扩展, 须先上外部共享状态(Redis/DB) + 引擎池外置, 非本架构支持。
    import fcntl
    lock_path = os.path.join(os.path.dirname(__file__), ".serve.lock")
    _serve_lock_fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        fcntl.flock(_serve_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        click.echo(f"❌ fusion-k12 serve 已在运行 (锁占用 {lock_path}) — 架构为单实例, 拒第二进程")
        raise SystemExit(1)
    logger.info("A2: 单实例锁已获 (%s), 单 worker 模式", lock_path)
    import uvicorn
    uvicorn.run("fusion_k12_teacher.serve:app", host=host, port=port, workers=1)



# ── 课标查询 ──

@cli.group()
def standards():
    """课标知识点查询。"""


@standards.command("list")
@click.option("--subject", "-s", default="", help="学科过滤")
@click.option("--grade", "-g", default="", help="年级过滤")
@click.pass_context
def standards_list(ctx, subject, grade):
    """列出课标知识点。"""
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
    click.echo(f"📋 共 {len(points)} 个知识点")
    for p in points[:20]:
        click.echo(f"   {p.id}: [{p.strand}] {p.topic} ({p.difficulty_level})")
    if len(points) > 20:
        click.echo(f"   ... 还有 {len(points) - 20} 个")
    click.echo()


@standards.command("show")
@click.argument("point_id")
@click.pass_context
def standards_show(ctx, point_id):
    """显示知识点详情。"""
    loader = ctx.obj["standards_loader"]
    query = ctx.obj["standards_query"]
    kp = loader.get_point(point_id)
    if not kp:
        click.echo(f"❌ 知识点不存在: {point_id}")
        return

    click.echo()
    click.echo(f"📌 {kp.topic}")
    click.echo(f"   ID: {kp.id}")
    click.echo(f"   学科: {kp.subject} | 年级: {kp.grade} | 领域: {kp.strand}")
    click.echo(f"   课标编码: {kp.curriculum_code}")
    click.echo(f"   难度: {kp.difficulty_level}")
    click.echo(f"   描述: {kp.description}")

    if kp.prerequisites:
        pres = query.get_prerequisites(point_id)
        click.echo(f"   前置: {_join_str(p.topic for p in pres)}")

    if kp.progression_next:
        nxts = query.get_progression(point_id)
        click.echo(f"   进阶: {_join_str(n.topic for n in nxts)}")

    click.echo()


# ── 分层教学 ──

@lesson.command("plan-diff")
@click.argument("subject")
@click.argument("grade")
@click.argument("topic")
@click.option("--duration", default=45, help="课时(分钟)")
@click.pass_context
def lesson_plan_diff(ctx, subject, grade, topic, duration):
    """生成三层分层教案。"""
    asyncio.run(_async_lesson_plan_diff(ctx, subject, grade, topic, duration))


async def _async_lesson_plan_diff(ctx, subject, grade, topic, duration):
    engine = ctx.obj["differentiation"]
    result = await engine.generate_differentiated_lesson(subject, grade, topic, duration)
    _check_engine_result(result, "分层教案")
    click.echo()
    click.echo(f"📚 三层分层教案: {result.topic}")
    click.echo(f"   学科: {result.subject} | 年级: {result.grade}")
    for level_name in ["struggling", "standard", "advanced"]:
        layer = getattr(result, level_name)
        label = {"struggling": "学困生", "standard": "中等生", "advanced": "优等生"}[level_name]
        click.echo(f"   [{label}] {layer.explanation[:80]}...")
    for gt in result.group_tasks:
        click.echo(f"   📋 {gt.group_name}: {gt.task_description[:60]}")
    click.echo()


@lesson.command("quiz-diff")
@click.argument("subject")
@click.argument("grade")
@click.argument("topic")
@click.option("--questions", "-n", default=5, help="每层题目数量")
@click.pass_context
def lesson_quiz_diff(ctx, subject, grade, topic, questions):
    """生成三层分层测验。"""
    asyncio.run(_async_lesson_quiz_diff(ctx, subject, grade, topic, questions))


async def _async_lesson_quiz_diff(ctx, subject, grade, topic, questions):
    engine = ctx.obj["differentiation"]
    result = await engine.generate_differentiated_quiz(subject, grade, topic, questions)
    _check_engine_result(result, "分层测验")
    click.echo()
    click.echo(f"📝 三层分层测验: {result.topic}")
    click.echo(f"   学科: {result.subject} | 年级: {result.grade}")
    for level_name in ["struggling", "standard", "advanced"]:
        layer = getattr(result, level_name)
        label = {"struggling": "学困生", "standard": "中等生", "advanced": "优等生"}[level_name]
        click.echo(f"   [{label}] {len(layer.exercises)} 道题")
    click.echo()


# ── 学情分析 ──

@cli.group()
def analytics():
    """学情分析与补救方案。"""


@analytics.command("class-profile")
@click.argument("class_id")
@click.argument("subject")
@click.argument("grade")
@click.option("--data", "-d", default="", help="评估数据文件路径(JSON/CSV)")
@click.pass_context
def analytics_class_profile(ctx, class_id, subject, grade, data):
    """生成班级学情画像。"""
    asyncio.run(_async_class_profile(ctx, class_id, subject, grade, data))


async def _async_class_profile(ctx, class_id, subject, grade, data):
    engine = ctx.obj["analytics"]
    assessments = _load_assessments(data)
    profile = await engine.build_class_profile(class_id, subject, grade, assessments)
    _check_engine_result(profile, "班级画像")
    click.echo()
    click.echo(f"📊 班级画像: {profile.class_id}")
    click.echo(f"   学科: {profile.subject} | 年级: {profile.grade}")
    click.echo(f"   学生数: {profile.total_students} | 平均分: {profile.avg_score}")
    click.echo(f"   分数分布: {profile.score_distribution}")
    click.echo(f"   高风险学生: {sum(1 for v in profile.student_risk_levels.values() if v == 'high')}")
    for wp in profile.weak_knowledge_points[:3]:
        click.echo(f"   ⚠️ {wp.knowledge_point_name}: 错误率 {wp.error_rate:.0%}")
    click.echo()


@analytics.command("student-profile")
@click.argument("student_id")
@click.argument("subject")
@click.argument("grade")
@click.option("--data", "-d", default="", help="评估数据文件路径(JSON/CSV)")
@click.pass_context
def analytics_student_profile(ctx, student_id, subject, grade, data):
    """生成学生个体画像。"""
    asyncio.run(_async_student_profile(ctx, student_id, subject, grade, data))


async def _async_student_profile(ctx, student_id, subject, grade, data):
    engine = ctx.obj["analytics"]
    all_assessments = _load_assessments(data)
    history = [a for a in all_assessments if a.student_id == student_id]
    profile = await engine.build_student_profile(student_id, subject, grade, history)
    _check_engine_result(profile, "学生画像")
    click.echo()
    click.echo(f"👤 学生画像: {profile.name}({profile.student_id})")
    click.echo(f"   学科: {profile.subject} | 年级: {profile.grade}")
    click.echo(f"   水平: {profile.overall_level} | 趋势: {profile.learning_trend}")
    if profile.risk_indicators:
        click.echo(f"   ⚠️ 风险: {_join_str(profile.risk_indicators)}")
    if profile.recommended_actions:
        click.echo(f"   💡 建议: {_join_str(profile.recommended_actions[:3])}")
    click.echo()


@analytics.command("error-analysis")
@click.argument("subject")
@click.argument("grade")
@click.option("--data", "-d", default="", help="评估数据文件路径(JSON/CSV)")
@click.pass_context
def analytics_error_analysis(ctx, subject, grade, data):
    """错题归因分析。"""
    asyncio.run(_async_error_analysis(ctx, subject, grade, data))


async def _async_error_analysis(ctx, subject, grade, data):
    engine = ctx.obj["analytics"]
    all_assessments = _load_assessments(data)
    responses = []
    for a in all_assessments:
        responses.extend(a.responses)
    errors = await engine.analyze_errors(subject, grade, responses)
    if errors is None:
        raise click.ClickException("错题归因分析失败: 引擎返回空")
    click.echo()
    click.echo(f"🔍 错题归因分析: {subject} {grade}")
    click.echo(f"   错误类型数: {len(errors)}")
    for e in errors[:5]:
        click.echo(f"   [{e.error_type}] {e.root_cause[:60]}")
        click.echo(f"      补救: {e.remediation[:60]}")
    click.echo()


@analytics.command("remedial")
@click.argument("student_id")
@click.argument("subject")
@click.argument("grade")
@click.option("--data", "-d", default="", help="评估数据文件路径(JSON/CSV)")
@click.pass_context
def analytics_remedial(ctx, student_id, subject, grade, data):
    """生成补救教学方案。"""
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
    _check_engine_result(plan, "补救方案")
    click.echo()
    click.echo(f"💊 补救方案: {plan.student_id}")
    click.echo(f"   薄弱点: {_join_str(wp.knowledge_point_name for wp in plan.weak_points[:3])}")
    click.echo(f"   策略: {_join_str(plan.strategies[:3])}")
    click.echo(f"   时间线: {plan.timeline}")
    click.echo()


@analytics.command("report")
@click.argument("class_id")
@click.argument("subject")
@click.argument("grade")
@click.option("--data", "-d", default="", help="评估数据文件路径(JSON/CSV)")
@click.pass_context
def analytics_report(ctx, class_id, subject, grade, data):
    """生成班级学情报告(Markdown)。"""
    asyncio.run(_async_report(ctx, class_id, subject, grade, data))


async def _async_report(ctx, class_id, subject, grade, data):
    engine = ctx.obj["analytics"]
    assessments = _load_assessments(data)
    profile = await engine.build_class_profile(class_id, subject, grade, assessments)
    _check_engine_result(profile, "班级报告")
    report = await engine.generate_class_report(profile)
    if not isinstance(report, str) or not report.strip():
        raise click.ClickException("班级报告生成失败: 引擎返回空")
    click.echo()
    click.echo(report)
    click.echo()


def _load_assessments(path: str):
    if not path:
        return []
    if path.endswith(".csv"):
        return load_from_csv(path)
    return load_from_json(path)


# ── Agent 任务编排 ──

@cli.group()
def agent():
    """任务编排与自动化调度。"""


@agent.command("tasks")
def agent_tasks():
    """列出可用预定义任务。"""
    tasks = list_available_tasks()
    click.echo()
    click.echo("📋 可用预定义任务:")
    for tid, name in tasks.items():
        click.echo(f"   {tid}: {name}")
    click.echo()


@agent.command("enable")
@click.argument("task_id")
def agent_enable(task_id):
    """启用任务。"""
    if not scheduler.get_task(task_id):
        scheduler.load_default_tasks()
    if scheduler.enable_task(task_id):
        click.echo(f"✅ 已启用: {task_id}")
    else:
        click.echo(f"❌ 未找到: {task_id}")


@agent.command("disable")
@click.argument("task_id")
def agent_disable(task_id):
    """禁用任务。"""
    if scheduler.disable_task(task_id):
        click.echo(f"⛔ 已禁用: {task_id}")
    else:
        click.echo(f"❌ 未找到: {task_id}")


@agent.command("run")
@click.argument("task_id")
@click.option("--subject", "-s", default="数学", help="学科")
@click.option("--grade", "-g", default="3", help="年级")
@click.option("--data", "data_path", default=None, help="学情数据文件路径 (JSON/CSV)")
def agent_run(task_id, subject, grade, data_path):
    """立即执行任务 — 每次按参数即时重建，避免烘焙过期数据 (AGT-5)。"""
    if not scheduler.get_task(task_id):
        scheduler.load_default_tasks(subject=subject, grade=grade)
    run_kwargs = {"subject": subject, "grade": grade}
    if data_path:
        run_kwargs["data_path"] = data_path
    result = asyncio.run(scheduler.run_task(task_id, **run_kwargs))
    click.echo()
    click.echo(f"📌 任务: {result.task_id}")
    click.echo(f"   状态: {result.status}")
    click.echo(f"   摘要: {result.summary}")
    click.echo()
    if result.status != "success":
        raise click.ClickException(f"任务执行失败: {result.summary}")


@agent.command("history")
@click.option("--limit", "-n", default=10, help="显示条数")
def agent_history(limit):
    """查看执行历史。"""
    history = scheduler.get_history(limit=limit)
    click.echo()
    click.echo(f"📜 执行历史 (最近 {limit} 条):")
    for r in history:
        click.echo(f"   [{r.status}] {r.task_id} — {r.summary[:60]}")
    click.echo()


@agent.command("start")
def agent_start():
    """启动调度器守护。"""
    scheduler.load_default_tasks()
    scheduler.start()
    click.echo("🚀 Agent 调度器已启动，Ctrl+C 退出")
    try:
        import time
        while scheduler.is_running():
            time.sleep(1)
    except KeyboardInterrupt:
        scheduler.stop()
        click.echo("🛑 Agent 调度器已停止")


@agent.command("stop")
def agent_stop():
    """停止调度器守护。"""
    scheduler.stop()
    click.echo("🛑 Agent 调度器已停止")


# ── 内容安全 ──

@cli.group()
def safety():
    """内容安全过滤与审查。"""


@safety.command("check")
@click.argument("text")
@click.option("--grade", "-g", default="3", help="目标年级")
def safety_check(text, grade):
    """检查文本内容安全性。"""
    cf = ContentFilter()
    result = cf.check_text(text, grade)
    click.echo()
    click.echo("🛡️ 内容检查结果:")
    click.echo(f"   安全: {'✅ 是' if result.is_safe else '❌ 否'}")
    click.echo(f"   风险等级: {result.risk_level}")
    if result.flagged_words:
        click.echo(f"   敏感词: {_join_str(result.flagged_words)}")
    if result.age_issues:
        click.echo(f"   适龄问题: {_join_str(result.age_issues, sep='; ')}")
    click.echo(f"   摘要: {result.summary}")
    click.echo()


@safety.command("filter")
@click.argument("text")
def safety_filter(text):
    """过滤文本中的敏感词。"""
    cf = ContentFilter()
    filtered = cf.filter_sensitive(text)
    click.echo()
    click.echo(f"📝 过滤结果: {filtered}")
    click.echo()


@safety.command("wordlist")
@click.option("--add", "add_word", default="", help="添加敏感词")
@click.option("--remove", "remove_word", default="", help="移除敏感词")
@click.option("--list", "list_words", is_flag=True, help="列出所有敏感词")
@click.option(
    "--path", "wl_path", default="",
    help="词库文件路径; 默认 ~/.fusion-k12/sensitive_words.txt (避免写只读包目录)",
)
def safety_wordlist(add_word, remove_word, list_words, wl_path):
    """管理敏感词库。"""
    # CLI-3: 默认写用户数据目录, 不写包内 site-packages(只读装会 PermissionError)
    if not wl_path:
        user_dir = os.path.expanduser("~/.fusion-k12")
        os.makedirs(user_dir, exist_ok=True)
        wl_path = os.path.join(user_dir, "sensitive_words.txt")
    wl = SensitiveWordList(path=wl_path)
    if add_word:
        wl.add(add_word)
        wl.save()
        click.echo(f"✅ 已添加: {add_word} (词库: {wl_path})")
    elif remove_word:
        wl.remove(remove_word)
        wl.save()
        click.echo(f"⛔ 已移除: {remove_word} (词库: {wl_path})")
    elif list_words:
        words = wl.list_words()
        click.echo()
        click.echo(f"📋 敏感词库 ({len(words)} 个) @ {wl_path}")
        for w in words:
            click.echo(f"   {w}")
        click.echo()
    else:
        click.echo(f"当前词库: {wl.count} 个敏感词 @ {wl_path}")


# ── 数据脱敏 ──

@cli.group()
def desensitize():
    """数据脱敏与匿名化。"""


@desensitize.command("anon")
@click.argument("input_file")
@click.option("--mode", "-m", "mode", default="id", help="匿名模式: id/mask",
              type=click.Choice(["id", "mask"], case_sensitive=False))
@click.option("--prefix", "-p", default="S", help="ID前缀")
@click.option("--output", "-o", default="", help="输出文件路径")
def desensitize_anon(input_file, mode, prefix, output):
    """对JSON文件中的记录进行脱敏。"""
    import json as _json
    try:
        with open(input_file, encoding="utf-8") as f:
            records = _json.load(f)
    except Exception as e:
        click.echo(f"❌ 读取文件失败: {e}")
        return
    if not isinstance(records, list):
        click.echo("❌ 输入文件须为JSON数组")
        return
    cfg = DesensitizeConfig(name_mode=mode, id_prefix=prefix)
    anon = DataAnonymizer(cfg)
    result = anon.anonymize_records(records)
    desensitized = anon.export_desensitized(records)
    # SEC-18: 反匿名表不随结果流转, 经 get_name_map() 显式取
    name_map = anon.get_name_map()
    click.echo()
    click.echo("🔒 脱敏完成:")
    click.echo(f"   原始记录: {result.original_count}")
    click.echo(f"   脱敏记录: {result.anonymized_count}")
    click.echo(f"   名称映射: {len(name_map)} 个")
    click.echo(f"   脱敏字段: {_join_str(result.masked_fields)}")
    if output:
        # CLI-4: temp+rename 原子写, 写中崩溃不留半文件
        _atomic_write_json(output, desensitized)
        click.echo(f"   输出文件: {output}")
    else:
        click.echo(f"   脱敏数据: {_json.dumps(desensitized[:1], ensure_ascii=False)[:200]}...")
    click.echo()


@desensitize.command("export")
@click.argument("input_file")
@click.option("--output", "-o", required=True, help="输出文件路径")
@click.option("--mode", "-m", "mode", default="id", help="匿名模式: id/mask",
              type=click.Choice(["id", "mask"], case_sensitive=False))
def desensitize_export(input_file, output, mode):
    """导出脱敏数据到文件。"""
    import json as _json
    try:
        # SRV-3: O_NOFOLLOW 防符号链接劫持读取
        fd_in = os.open(input_file, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd_in, encoding="utf-8") as f:
            records = _json.load(f)
    except Exception as e:
        click.echo(f"❌ 读取文件失败: {e}")
        return
    if not isinstance(records, list):
        records = [records]
    cfg = DesensitizeConfig(name_mode=mode)
    anon = DataAnonymizer(cfg)
    desensitized = anon.export_desensitized(records)
    # CLI-4: 原子写脱敏数据 (temp+rename), 兼 SRV-3 O_NOFOLLOW
    _atomic_write_json(output, desensitized)
    name_map = anon.get_name_map()
    keys_dir = os.path.expanduser("~/.fusion-k12/keys")
    os.makedirs(keys_dir, exist_ok=True)
    os.chmod(keys_dir, 0o700)
    # CLI-6: basename 去重不充分, 同名不同目录两次导出互覆 _map.json, 首份映射静默丢失。
    # 改用 output 绝对路径的短 hash 前缀 + basename, 保证唯一。
    out_abs = os.path.abspath(output)
    out_hash = hashlib.sha1(out_abs.encode("utf-8")).hexdigest()[:8]
    base_name = os.path.basename(output).replace(".json", "")
    map_path = os.path.join(keys_dir, f"{out_hash}_{base_name}_map.json")
    _atomic_write_json(map_path, name_map)
    if os.path.exists(map_path):
        os.chmod(map_path, 0o600)
    logger.warning("可逆映射表已导出至受限目录(0600, 含敏感还原信息, 勿与脱敏数据同存/外传): %s", map_path)
    click.echo(f"✅ 脱敏数据已导出: {output}")
    click.echo(f"✅ 映射表已导出(0600, 独立受限目录): {map_path}")


@cli.command()
@click.option("--from-db", "from_db", required=True, help="源 SQLite 路径 (standalone)")
@click.option("--to-dsn", "to_dsn", required=True, help="目标 Postgres DSN (cluster)")
@click.option("--dry-run", is_flag=True, help="仅预览迁移记录数, 不写入")
@click.option("--encrypt", is_flag=True, help="M1-T9: name_map 加密导入 (AES-256-GCM, 需 FUSION_K12_DATA_KEY)")
def migrate(from_db, to_dsn, dry_run, encrypt):
    """M1-T3/T9: 单机→集群数据迁移 — 导出 standalone SQLite (history/name_map) 导入 Postgres。

    schema 由目标后端构造时自建 (CREATE TABLE IF NOT EXISTS), 无需 Alembic。
    迁移不可逆回滚, 源库只读不删。
    --encrypt: name_map 以 name_hash+name_encrypted 加密写入 (PII 不落明文)。
    """
    from .repository import SQLiteRepository
    try:
        from .repository import PostgresRepository
    except ImportError as e:
        click.echo(f"❌ 目标 Postgres 后端不可用: {e}")
        click.echo("   安装: pip install -e '.[cluster]'")
        raise SystemExit(1)

    cipher = None
    if encrypt:
        try:
            from .safety import DataCipher
            cipher = DataCipher()
        except ImportError as e:
            click.echo(f"❌ 加密需 cryptography: {e}")
            click.echo("   安装: pip install -e '.[cluster]'")
            raise SystemExit(1)

    src = SQLiteRepository(from_db)
    history = src.load_history()
    name_map, reverse_map = src.load_name_map()
    src.close()
    logger.info("迁移源读取: history=%d 条, name_map=%d 条, encrypt=%s", len(history), len(name_map), encrypt)
    click.echo(f"📦 源数据: 历史 {len(history)} 条, 脱敏映射 {len(name_map)} 条" + (" (加密导入)" if encrypt else ""))

    if dry_run:
        click.echo("🔍 --dry-run: 仅预览, 未写入目标")
        return

    async def _run():
        dst = PostgresRepository(to_dsn)
        await dst.asave_history(history)
        await dst.asave_name_map(name_map, reverse_map, cipher=cipher)
        # 验证: 回读比对 (加密模式需同 cipher 解密)
        loaded_hist = await dst.aload_history()
        loaded_nm, _ = await dst.aload_name_map(cipher=cipher)
        await dst.aclose()
        return loaded_hist, loaded_nm

    loaded_hist, loaded_nm = asyncio.run(_run())
    ok_hist = len(loaded_hist) == len(history)
    ok_nm = len(loaded_nm) == len(name_map)
    logger.info("迁移目标验证: history %s, name_map %s", ok_hist, ok_nm)
    if ok_hist and ok_nm:
        click.echo(f"✅ 迁移完成: 历史 {len(loaded_hist)} 条, 脱敏映射 {len(loaded_nm)} 条")
    else:
        click.echo(f"⚠️ 迁移后数量不符 (历史 {len(loaded_hist)}/{len(history)}, "
                   f"映射 {len(loaded_nm)}/{len(name_map)}) — 请检查目标库")
        raise SystemExit(1)


@cli.command("encrypt-name-map")
@click.option("--db", "db_path", required=True, help="standalone SQLite 路径")
@click.option("--dry-run", is_flag=True, help="仅预览待加密条数, 不写入")
def encrypt_name_map(db_path, dry_run):
    """M1-T9: 就地加密 standalone SQLite 旧明文 name_map (name_hash + name_encrypted)。

    读明文 map_key/reverse, 用 DataCipher 重写为加密列。原明文 reverse 列保留
    (渐进迁移, 解密失败可回退); 加密列成为权威。需 FUSION_K12_DATA_KEY。
    """
    try:
        from .safety import DataCipher
        cipher = DataCipher()
    except ImportError as e:
        click.echo(f"❌ 加密需 cryptography: {e}")
        click.echo("   安装: pip install -e '.[cluster]'")
        raise SystemExit(1)

    from .repository import SQLiteRepository
    repo = SQLiteRepository(db_path)
    name_map, reverse_map = repo.load_name_map()
    click.echo(f"📦 待加密 name_map: {len(name_map)} 条")
    if dry_run:
        click.echo("🔍 --dry-run: 仅预览, 未写入")
        repo.close()
        return
    repo.save_name_map(name_map, reverse_map, cipher=cipher)
    logger.info("name_map 就地加密完成: %d 条", len(name_map))
    click.echo(f"✅ name_map 已加密 ({len(name_map)} 条), 明文 reverse 列保留作回退")
    repo.close()


@cli.command("rotate-salt")
@click.option("--salt-file", "salt_file", default=None, help="salt 文件路径 (默认 ~/.fusion-k12/salt)")
@click.option("--show-versions", is_flag=True, help="仅列出所有版本, 不轮换")
def rotate_salt(salt_file, show_versions):
    """M1-T8: salt 轮换 — 当前 salt 归档为历史版本, 生成新 salt 写主文件。

    旧版本保留用于解析历史脱敏 ID (反向回查), 新 salt 用于后续新写入。
    轮换后历史 ID 与新 ID 不同 (同姓名), 属预期行为。
    """
    from .safety.salt_provider import VersionedSaltProvider

    prov = VersionedSaltProvider(salt_file)
    if show_versions:
        versions = prov.list_versions()
        click.echo(f"📋 salt 版本 (共 {len(versions)} 个):")
        for v, s in versions:
            masked = s[:6] + "..." + s[-4:]
            click.echo(f"   v{v}: {masked}")
        return
    new_ver, new_salt = prov.rotate()
    masked = new_salt[:6] + "..." + new_salt[-4:]
    logger.info("salt 轮换完成: 新版本 v%d", new_ver)
    click.echo(f"✅ salt 已轮换 → v{new_ver}: {masked}")
    click.echo("   旧版本已归档, 历史脱敏 ID 仍可解析 (反向回查用旧版本 salt)")


def main():
    cli()


if __name__ == "__main__":
    main()