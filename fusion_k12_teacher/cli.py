"""Fusion-K12-Teacher CLI 入口。"""

from __future__ import annotations

import asyncio
import json
import logging
import sys

import click

from . import __version__, __app_name__
from .ai_client import MLXClient
from .curriculum import CurriculumEngine
from .assessment import AssessmentEngine
from .subjects import SubjectExpert
from .personalization import PersonalizationEngine
from .content import ContentGenerator

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
    mlx = MLXClient(model=model)
    ctx.ensure_object(dict)
    ctx.obj["mlx"] = mlx
    ctx.obj["curriculum"] = CurriculumEngine(mlx)
    ctx.obj["assessment"] = AssessmentEngine(mlx)
    ctx.obj["subjects"] = SubjectExpert(mlx)
    ctx.obj["personalization"] = PersonalizationEngine(mlx)
    ctx.obj["content"] = ContentGenerator(mlx)


# ── 课程规划 ──

@cli.group()
def lesson():
    """课程规划与教案管理。"""
    pass


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
    pass


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
    pass


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
    pass


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
    pass


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


@cli.command()
@click.option("--host", default="0.0.0.0", help="监听地址")
@click.option("--port", default=8900, help="监听端口")
def serve(host, port):
    """启动 HTTP API 服务。"""
    import uvicorn
    uvicorn.run("fusion_k12_teacher.serve:app", host=host, port=port)


def main():
    cli()


if __name__ == "__main__":
    main()