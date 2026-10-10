"""issue #22: BNUP (北师大版) 苏格拉底教学 prompt 集中注册表。

所有 BNUP 苏格拉底式教学场景共用本模块的 system prompt + visual 路由规则 +
CoT 格式指令, 避免散落在 9 个 inline prompt 站点造成不一致。

使用方式:
    from .course.prompts.bnup_socratic import (
        BNUP_SYSTEM_PROMPT, BNUP_VISUAL_ROUTING_PROMPT,
        BNUP_COT_FORMAT_PROMPT, route_visual_type,
    )

build_prompt (sanitize_input) 仍在调用方执行 — 本模块只提供 prompt 文本。
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# ── 8 可视化基元路由规则 ──────────────────────────────────────────
# 按题型关键词 → visual_type 映射 (issue #19 v3.0 八基元)
VISUAL_ROUTING_RULES: list[tuple[str, str, str]] = [
    # (pattern_regex, visual_type, description)
    # 注意: isometric_3d 须在 geometry_2d 前 (圆柱/圆锥含"圆"字, 先匹配立体)
    (r"计数|数数|圈画|阵列|搭配|排列|认识数|数的认识|数一数", "array_grid", "1-2年级 计数/圈画/阵列"),
    (r"和差|倍比|分数|百分数|比例|按比分配", "tape_diagram", "2-6年级 和差倍比/分数 核心通用"),
    (r"长方体|正方体|圆柱|圆锥|立体|切削|展开图|表面积|体积", "isometric_3d", "5-6年级 立体几何/切削展开"),
    (r"周长|面积|三角形|长方形|正方形|平行四边形|梯形|圆|角度", "geometry_2d", "3-5年级 平面几何/周长面积"),
    (r"行程|追及|相遇|速度|时间|路程|火车|过桥|回声|相向|同向", "track_timeline", "4-6年级 速度/时间/行程追及"),
    (r"组合|隔板|抽屉|分配|鸡兔同笼|容斥", "bucket_divider", "4-6年级 组合/隔板/抽屉原理"),
    (r"统计|条形图|折线图|扇形图|平均数|中位数|可能性|概率", "data_chart", "4-5年级 统计/条形/折线图"),
    (r"方程|计算|四则|运算律|简便", "flow_card", "纯计算/方程/通用兜底"),
]

FALLBACK_VISUAL = "flow_card"


def route_visual_type(topic: str, problem_text: str = "") -> str:
    """issue #22: 按题型关键词路由 visual_type (8 基元)。

    优先级: topic 匹配 > problem_text 匹配 > flow_card 兜底。
    """
    text = f"{topic} {problem_text}"
    for pattern, vtype, _desc in VISUAL_ROUTING_RULES:
        if re.search(pattern, text):
            logger.info("route_visual_type: '%s' -> %s (pattern=%s)", topic[:30], vtype, pattern[:15])
            return vtype
    logger.info("route_visual_type: '%s' -> %s (fallback)", topic[:30], FALLBACK_VISUAL)
    return FALLBACK_VISUAL


# ── BNUP 统一系统 prompt ─────────────────────────────────────────
BNUP_SYSTEM_PROMPT = """你是北师大版 (BNUP) K-12 数学苏格拉底式教学设计专家。

核心原则:
1. 苏格拉底式: 不直接给答案, 用问题引导学生发现规律。
2. 5E 教学法: Engage(引入) → Explore(探索) → Explain(解释) → Elaborate(拓展) → Evaluate(评价)。
3. 分层教学: A(基础) / B(进阶) / C(拔高), 连错2次降层 (B→A)。
4. 数值准确: 所有数值经 SymPy 符号校验, 不容忍计算错误。
5. 可视化优先: 每步配可视化动作, 按 8 基元路由选择最优呈现。

可视化 8 基元 (visual_type):
- array_grid: 计数/圈画/阵列 (1-2年级)
- tape_diagram: 和差倍比/分数 (2-6年级, 核心通用)
- geometry_2d: 平面几何/周长面积 (3-5年级)
- isometric_3d: 立体几何/切削展开 (5-6年级)
- track_timeline: 行程/追及/时间推算 (4-6年级)
- bucket_divider: 组合/隔板/抽屉 (4-6年级)
- data_chart: 统计/条形/折线图 (4-5年级)
- flow_card: 纯计算/方程/通用兜底

兜底链: primary visual_type → fallback_type (tape_diagram 或 flow_card) → 纯文字。
"""


# ── 可视化路由 prompt (嵌入各生成 prompt 的 visual 选择段) ────────
BNUP_VISUAL_ROUTING_PROMPT = """可视化选择规则 (8 基元, 按题型匹配):
- array_grid: 计数/圈画/阵列/搭配枚举 → 1-2年级
- tape_diagram: 和差倍比/分数/百分数/比例 → 2-6年级 (核心通用兜底)
- geometry_2d: 周长/面积/三角形/长方形/圆/角度 → 3-5年级
- isometric_3d: 长方体/圆柱/圆锥/立体/切削/展开图 → 5-6年级
- track_timeline: 行程/追及/相遇/速度/时间/路程/火车过桥 → 4-6年级
- bucket_divider: 组合/隔板/抽屉/鸡兔同笼/容斥 → 4-6年级
- data_chart: 统计/条形图/折线图/扇形图/平均数 → 4-5年级
- flow_card: 方程/计算/四则运算/运算律 → 纯计算兜底

请根据课题/题意选择最匹配的 visual_type, 并配 fallback_type (tape_diagram 或 flow_card)。
"""


# ── CoT 格式指令 (issue #20 两阶段) ──────────────────────────────
BNUP_COT_FORMAT_PROMPT = """两阶段推理格式 (CoT):
阶段1 <thinking>: 自由推理教学路径 (学生认知起点 → 核心概念 → 障碍分析 → 5E策略 → 可视化选择)
阶段2 <dsl>: 严格 JSON 输出 (meta.visual_type + steps[].visual_state + checkpoint)

<thinking> 与 <dsl> 标签隔离, <dsl> 内容可被 JSON 解析器直接提取。
"""


def build_bnup_prompt(topic: str, grade: str = "5", **extra: Any) -> str:
    """issue #22: 构建 BNUP 苏格拉底 prompt — system + visual 路由 + topic 上下文。

    返回拼接后的完整 prompt 文本 (未经 sanitize, 调用方负责 build_prompt)。
    """
    vtype = route_visual_type(topic, str(extra.get("problem_text", "")))
    fb = "tape_diagram" if vtype != "tape_diagram" else "flow_card"
    parts = [
        BNUP_SYSTEM_PROMPT,
        f"\n课题: {topic} (年级 {grade})",
        f"推荐 visual_type: {vtype} (fallback: {fb})",
        BNUP_VISUAL_ROUTING_PROMPT,
    ]
    if extra.get("cot_enabled"):
        parts.append(BNUP_COT_FORMAT_PROMPT)
    if extra.get("knowledge_node_id"):
        parts.append(f"知识点节点: {extra['knowledge_node_id']}")
    if extra.get("prerequisites"):
        parts.append(f"前置知识: {extra['prerequisites']}")
    if extra.get("misconceptions"):
        parts.append(f"易错点: {extra['misconceptions']}")
    return "\n".join(parts)
