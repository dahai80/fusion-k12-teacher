# Subject course platform — abstraction layer decoupling platform from content.
#
# This package defines subject-agnostic course capability protocols (SubjectModule);
# each subject (math/physics/chemistry/english/chinese) implements and registers
# into SubjectRegistry on its own. The platform (engines/serve/gui) depends only on
# the protocols and the registry — adding a subject requires zero platform changes.
#
# Capability dimensions (each subject implements optionally; unimplemented
# returns None/501):
# - KnowledgeGraphBase: subject knowledge graph (nodes/edges/DAG/reverse attribution)
# - SceneCompilerBase: problem -> parameterized scene DSL (animated visualization)
# - SocraticTutorBase: 5E Socratic lesson-script DSL generation + checkpoint scoring
# - VerifierBase: rigor verification (authoritative numeric override, guards against
#   subject hallucination)
# - MasteryTracker: subject-agnostic, shared by the platform

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
    FALLBACK_TYPES,
    VISUAL_TYPES,
    AnimationSegment,
    Checkpoint,
    CheckpointType,
    CoursePackage,
    FallbackType,
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
    VisualState,
    VisualType,
)
from .registry import SubjectNotFoundError, SubjectRegistry

__all__ = [
    "FALLBACK_TYPES",
    "VISUAL_TYPES",
    "AnimationSegment",
    "Checkpoint",
    "CheckpointType",
    "CoursePackage",
    "FallbackType",
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
    "VisualState",
    "VisualType",
]
