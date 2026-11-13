"""Run one benchmark arm (suite x attack x defense x model) and write a self-describing results file.

Resumability comes for free: AgentDojo skips cases already present in ``logdir`` (per-case JSON) and the
client's cache makes repeated requests free. A daily quota stop raises QuotaExhausted; rerun tomorrow.
"""

from __future__ import annotations

import datetime as dt
import importlib.metadata
import subprocess
from pathlib import Path
from typing import Any

from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
from agentdojo.attacks.attack_registry import load_attack
from agentdojo.benchmark import (
    SuiteResults,
    benchmark_suite_with_injections,
    benchmark_suite_without_injections,
)
from agentdojo.logging import OutputLogger
from agentdojo.task_suite.load_suites import get_suite
from pydantic import BaseModel, Field

import provguard.bench.attacks  # noqa: F401 - registers the named important_instructions attack
from provguard.bench.attacks import prose_model_name
from provguard.bench.stats import Metrics, Proportion
from provguard.llm.client import LLMClient

RESULTS_DIR = Path("results")
LOG_DIR = Path("runs")


class ArmSpec(BaseModel):
    suite: str = "banking"
    attack: str | None = None
    defense: str = "none"
    model: str  # provider/model
    benchmark_version: str = "v1.2.2"
    user_tasks: list[str] = Field(default_factory=list)
    injection_tasks: list[str] = Field(default_factory=list)
    seed: int = 0
    mode: str = "live"
    label: str | None = None  # None = the full suite; "smoke" / "partial" runs never overwrite the full file

    @property
    def arm_id(self) -> str:
        model = self.model.replace("/", "_")
        return f"{self.suite}__{self.defense}__{self.attack or 'none'}__{model}"

    @property
    def file_stem(self) -> str:
        return f"{self.arm_id}__{self.label}" if self.label else self.arm_id


class Case(BaseModel):
    user_task: str
    injection_task: str | None
    utility: bool
    security: bool  # AgentDojo semantics: True = injection goal achieved (attack succeeded)


class ArmResult(BaseModel):
    arm_id: str
    spec: ArmSpec
    meta: dict[str, Any]
    cases: list[Case]
    injection_tasks_as_user_tasks: dict[str, bool]
    usage: dict[str, Any]
    metrics: Metrics
    guard: dict[str, Any] | None = None  # provguard arms only: confirmations, statuses (this process's cases)


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()  # noqa: S607
    except Exception:  # pragma: no cover - not a git checkout
        return "unknown"


def _version(pkg: str) -> str:
    try:
        return importlib.metadata.version(pkg)
    except importlib.metadata.PackageNotFoundError:  # pragma: no cover
        return "unknown"


def compute_metrics(results: SuiteResults, attacked: bool) -> Metrics:
    utilities = results["utility_results"]
    securities = results["security_results"]
    benign = [] if attacked else list(utilities.values())
    under_attack = list(utilities.values()) if attacked else []
    asr = list(securities.values()) if attacked else []
    return Metrics(
        benign_utility=Proportion.of(benign),
        utility_under_attack=Proportion.of(under_attack),
        targeted_asr=Proportion.of(asr),
        injection_tasks_solvable=Proportion.of(results["injection_tasks_utility_results"].values()),
    )


def _guard_stats(pipeline: BasePipelineElement) -> dict[str, Any] | None:
    guard = next((e for e in getattr(pipeline, "elements", []) if hasattr(e, "history")), None)
    if guard is None:
        return None
    from provguard.agent.adapter import guard_stats

    return guard_stats(guard.history)


def run_arm(
    spec: ArmSpec,
    pipeline: BasePipelineElement,
    client: LLMClient,
    *,
    logdir: Path = LOG_DIR,
    results_dir: Path = RESULTS_DIR,
    force_rerun: bool = False,
) -> ArmResult:
    suite = get_suite(spec.benchmark_version, spec.suite)
    started = dt.datetime.now(dt.UTC)
    with OutputLogger(str(logdir)):
        if spec.attack is None:
            results = benchmark_suite_without_injections(
                pipeline,
                suite,
                logdir,
                force_rerun,
                user_tasks=spec.user_tasks or None,
                benchmark_version=spec.benchmark_version,
            )
        else:
            attack = load_attack(spec.attack, suite, pipeline)
            results = benchmark_suite_with_injections(
                pipeline,
                suite,
                attack,
                logdir,
                force_rerun,
                user_tasks=spec.user_tasks or None,
                injection_tasks=spec.injection_tasks or None,
                benchmark_version=spec.benchmark_version,
            )
    cases = [
        Case(
            user_task=ut, injection_task=it or None, utility=u, security=results["security_results"][(ut, it)]
        )
        for (ut, it), u in results["utility_results"].items()
    ]
    arm = ArmResult(
        arm_id=spec.arm_id,
        spec=spec,
        meta={
            "git_sha": git_sha(),
            "started": started.isoformat(),
            "finished": dt.datetime.now(dt.UTC).isoformat(),
            "pipeline_name": pipeline.name,
            "attack_prose_model_name": prose_model_name(pipeline.name) if spec.attack else None,
            "versions": {
                "provguard": _version("provguard"),
                "agentdojo": _version("agentdojo"),
                "openai": _version("openai"),
            },
        },
        cases=cases,
        injection_tasks_as_user_tasks=dict(results["injection_tasks_utility_results"]),
        usage=client.summary.model_dump(),
        guard=_guard_stats(pipeline),
        metrics=compute_metrics(results, attacked=spec.attack is not None),
    )
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / f"{spec.file_stem}.json").write_text(arm.model_dump_json(indent=2))
    return arm
