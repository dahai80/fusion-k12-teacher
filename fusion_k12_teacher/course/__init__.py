"""学科课程平台 — 平台与内容解耦的抽象层。

本包定义学科无关的课程能力协议 (SubjectModule), 各学科 (math/physics/chemistry/
english/chinese) 各自实现并注册进 SubjectRegistry。平台 (engines/serve/gui) 只依赖
协议与 registry, 加学科零改平台代码。

能力维度 (每学科可选择性实现, 未实现的返回 None/501):
- KnowledgeGraphBase: 学科知识图谱 (节点/边/DAG/逆向归因)
- SceneCompilerBase: 题目→参数化场景 DSL (动画可视化)
- SocraticTutorBase: 5E 苏格拉底课稿 DSL 生成 + checkpoint 判分
- VerifierBase: 严谨性校验 (数值权威覆写, 防学科幻觉)
- MasteryTracker: 学科无关, 平台共享
"""

from __future__ import annotations

from .base import (
    KnowledgeGraphBase,
    SceneCompilerBase,
    SocraticTutorBase,
    SubjectModule,
    VerifierBase,
)
from .mastery import MasteryRecord, MasteryTracker
from .models import (
    AnimationSegment,
    Checkpoint,
    CheckpointType,
    CoursePackage,
    FusionSocraticDSL,
    GraphNode,
    JudgeResult,
    Landmark,
    Milestone,
    OnErrorAction,
    SceneDSL,
    SceneEntity,
    TeachingStep,
    VerifyResult,
)
from .registry import SubjectNotFoundError, SubjectRegistry

__all__ = [
    "AnimationSegment",
    "Checkpoint",
    "CheckpointType",
    "CoursePackage",
    "FusionSocraticDSL",
    "GraphNode",
    "JudgeResult",
    "KnowledgeGraphBase",
    "Landmark",
    "MasteryRecord",
    "MasteryTracker",
    "Milestone",
    "OnErrorAction",
    "SceneCompilerBase",
    "SceneDSL",
    "SceneEntity",
    "SocraticTutorBase",
    "SubjectModule",
    "SubjectNotFoundError",
    "SubjectRegistry",
    "TeachingStep",
    "VerifierBase",
    "VerifyResult",
]
