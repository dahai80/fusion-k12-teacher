"""Fusion-K12-Teacher CLI 入口。"""

from __future__ import annotations

import asyncio
import logging
import os

import click

from . import __app_name__, __version__
from .agent import list_available_tasks, scheduler
from .analytics import load_from_csv, load_from_json
from .analytics.models import WeakPoint
from .desensitize import DataAnonymizer, DesensitizeConfig
from .engines import build_engines
from .safety import ContentFilter, SensitiveWordList

logger = logging.getLogger(__name__)


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
    click.echo()
    click.echo(f"📚 {plan.title}")
    click.echo(f"   学科: {plan.subject} | 年级: {plan.grade} | 课时: {plan.duration_minutes}分钟")
    click.echo(f"   目标: {', '.join(plan.objectives[:3])}")
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
    click.echo()
    click.echo(f"📊 评分: {result.score}/{result.total} ({result.percentage:.0f}%)")
    if result.strengths:
        click.echo(f"   优点: {', '.join(result.strengths[:3])}")
    if result.improvements:
        click.echo(f"   建议: {', '.join(result.improvements[:3])}")
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
    click.echo()
    click.echo(f"🎯 {student}的个性化学习路径")
    click.echo(f"   目标: {', '.join(path.goals[:3])}")
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
    click.echo()
    click.echo(f"📄 三层分层工作纸: {result.topic}")
    click.echo(f"   学科: {result.subject} | 年级: {result.grade}")
    for level_name in ["struggling", "standard", "advanced"]:
        layer = getattr(result, level_name)
        label = {"struggling": "学困生", "standard": "中等生", "advanced": "优等生"}[level_name]
        click.echo(f"   [{label}] {len(layer.exercises)} 道题")
    click.echo()


@cli.command()
@click.option("--host", default="127.0.0.1", help="监听地址(仅本地回环, 外部绑定请用反向代理+鉴权)")
@click.option("--port", default=11448, help="监听端口")
def serve(host, port):
    """启动 HTTP API 服务。"""
    if host not in ("127.0.0.1", "localhost", "::1"):
        click.echo("❌ 禁止监听非回环地址; 请用反向代理+鉴权暴露服务, 避免裸奔")
        raise SystemExit(1)
    import uvicorn
    uvicorn.run("fusion_k12_teacher.serve:app", host=host, port=port)


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
        click.echo(f"   前置: {', '.join(p.topic for p in pres)}")

    if kp.progression_next:
        nxts = query.get_progression(point_id)
        click.echo(f"   进阶: {', '.join(n.topic for n in nxts)}")

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
    click.echo()
    click.echo(f"👤 学生画像: {profile.name}({profile.student_id})")
    click.echo(f"   学科: {profile.subject} | 年级: {profile.grade}")
    click.echo(f"   水平: {profile.overall_level} | 趋势: {profile.learning_trend}")
    if profile.risk_indicators:
        click.echo(f"   ⚠️ 风险: {', '.join(profile.risk_indicators)}")
    if profile.recommended_actions:
        click.echo(f"   💡 建议: {', '.join(profile.recommended_actions[:3])}")
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
    click.echo()
    click.echo(f"💊 补救方案: {plan.student_id}")
    click.echo(f"   薄弱点: {', '.join(wp.knowledge_point_name for wp in plan.weak_points[:3])}")
    click.echo(f"   策略: {', '.join(plan.strategies[:3])}")
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
    report = await engine.generate_class_report(profile)
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
        click.echo(f"   敏感词: {', '.join(result.flagged_words)}")
    if result.age_issues:
        click.echo(f"   适龄问题: {'; '.join(result.age_issues)}")
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
def safety_wordlist(add_word, remove_word, list_words):
    """管理敏感词库。"""
    wl = SensitiveWordList()
    if add_word:
        wl.add(add_word)
        wl.save()
        click.echo(f"✅ 已添加: {add_word}")
    elif remove_word:
        wl.remove(remove_word)
        wl.save()
        click.echo(f"⛔ 已移除: {remove_word}")
    elif list_words:
        words = wl.list_words()
        click.echo()
        click.echo(f"📋 敏感词库 ({len(words)} 个):")
        for w in words:
            click.echo(f"   {w}")
        click.echo()
    else:
        click.echo(f"当前词库: {wl.count} 个敏感词")


# ── 数据脱敏 ──

@cli.group()
def desensitize():
    """数据脱敏与匿名化。"""


@desensitize.command("anon")
@click.argument("input_file")
@click.option("--mode", "-m", default="id", help="匿名模式: id/mask")
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
    click.echo()
    click.echo("🔒 脱敏完成:")
    click.echo(f"   原始记录: {result.original_count}")
    click.echo(f"   脱敏记录: {result.anonymized_count}")
    click.echo(f"   名称映射: {len(result.name_map)} 个")
    click.echo(f"   脱敏字段: {', '.join(result.masked_fields)}")
    if output:
        with open(output, "w", encoding="utf-8") as f:
            _json.dump(desensitized, f, ensure_ascii=False, indent=2)
        click.echo(f"   输出文件: {output}")
    else:
        click.echo(f"   脱敏数据: {_json.dumps(desensitized[:1], ensure_ascii=False)[:200]}...")
    click.echo()


@desensitize.command("export")
@click.argument("input_file")
@click.option("--output", "-o", required=True, help="输出文件路径")
@click.option("--mode", "-m", default="id", help="匿名模式: id/mask")
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
    # SRV-3: 输出文件 O_NOFOLLOW, 勿跟随已有符号链接
    fd_out = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd_out, "w", encoding="utf-8") as f:
        _json.dump(desensitized, f, ensure_ascii=False, indent=2)
    name_map = anon.get_name_map()
    keys_dir = os.path.expanduser("~/.fusion-k12/keys")
    os.makedirs(keys_dir, exist_ok=True)
    os.chmod(keys_dir, 0o700)
    base_name = os.path.basename(output).replace(".json", "")
    map_path = os.path.join(keys_dir, f"{base_name}_map.json")
    # SRV-3: 映射表 O_NOFOLLOW (含敏感还原信息)
    fd = os.open(map_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        _json.dump(name_map, f, ensure_ascii=False, indent=2)
    if os.path.exists(map_path):
        os.chmod(map_path, 0o600)
    logger.warning("可逆映射表已导出至受限目录(0600, 含敏感还原信息, 勿与脱敏数据同存/外传): %s", map_path)
    click.echo(f"✅ 脱敏数据已导出: {output}")
    click.echo(f"✅ 映射表已导出(0600, 独立受限目录): {map_path}")


def main():
    cli()


if __name__ == "__main__":
    main()