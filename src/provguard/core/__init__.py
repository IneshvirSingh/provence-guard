"""Core: provenance types, plan schema and the policy engine. Pure Python, no LLM calls.

Designed in docs/design/core.md.
"""

from provguard.core.plan import Plan, PlanError, ToolSpec
from provguard.core.policy import Decision, PolicySet, Reason, decide
from provguard.core.provenance import PLANNER, SYSTEM, USER, Labeled, Source, tool
from provguard.core.runner import PlanRunner, RunResult, confirm_permissive, confirm_strict
from provguard.core.trust import TrustConfig

__all__ = [
    "PLANNER",
    "SYSTEM",
    "USER",
    "Decision",
    "Labeled",
    "Plan",
    "PlanError",
    "PlanRunner",
    "PolicySet",
    "Reason",
    "RunResult",
    "Source",
    "ToolSpec",
    "TrustConfig",
    "confirm_permissive",
    "confirm_strict",
    "decide",
    "tool",
]
