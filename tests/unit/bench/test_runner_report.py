import json
from pathlib import Path

import pytest

from provguard.bench.pipelines import build_pipeline
from provguard.bench.report import render, write_report
from provguard.bench.runner import ArmSpec, run_arm
from provguard.bench.stats import Proportion, wilson
from provguard.llm.client import LLMClient
from provguard.llm.providers import Limits, ModelRef

REF = ModelRef(
    provider="groq", model="llama-3.3-70b-versatile", base_url="https://x", api_key_env="X", limits=Limits()
)


def test_wilson_known_values():
    lo, hi = wilson(0, 10)
    assert lo == 0.0 and abs(hi - 0.2775) < 0.001
    lo, hi = wilson(5, 10)
    assert abs(lo - 0.2366) < 0.001 and abs(hi - 0.7634) < 0.001
    lo, hi = wilson(10, 10)
    assert abs(hi - 1.0) < 1e-9 and lo > 0.7
    with pytest.raises(ValueError):
        wilson(1, 0)
    with pytest.raises(ValueError):
        wilson(5, 2)
    p = Proportion.of([])
    assert p.fmt() == "[PENDING]" and Proportion.of([True, False]).fmt().startswith("50.0%")


def resp(text=None, calls=None):
    msg = {"role": "assistant", "content": text}
    if calls:
        msg["tool_calls"] = [
            {"id": f"c{i}", "type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
            for i, (n, a) in enumerate(calls)
        ]
    return {
        "choices": [{"message": msg}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
    }


class Scripted:
    def __init__(self, responses):
        self.responses = list(responses)

    def __call__(self, payload):
        return self.responses.pop(0) if self.responses else resp("done")


def test_run_arm_benign_writes_results_file(tmp_path: Path):
    transport = Scripted([resp(calls=[("get_most_recent_transactions", {"n": 100})]), resp("1050")])
    client = LLMClient(REF, transport=transport)
    spec = ArmSpec(model="groq/llama-3.3-70b-versatile", user_tasks=["user_task_1"])
    arm = run_arm(
        spec,
        build_pipeline(client, "none"),
        client,
        logdir=tmp_path / "runs",
        results_dir=tmp_path / "results",
    )
    out = tmp_path / "results" / f"{spec.arm_id}.json"
    assert out.exists() and arm.metrics.benign_utility.k == 1 and arm.metrics.benign_utility.n == 1
    assert arm.metrics.targeted_asr.value is None and arm.usage["requests"] == 2
    assert (
        arm.meta["versions"]["agentdojo"] == "0.1.35" and len(arm.meta["git_sha"]) in (7, 40)
    ) or arm.meta["git_sha"] == "unknown"
    # resumable: a second run with a fresh (empty) transport reads AgentDojo's per-case log and makes no calls
    client2 = LLMClient(REF, transport=Scripted([]))
    arm2 = run_arm(
        spec,
        build_pipeline(client2, "none"),
        client2,
        logdir=tmp_path / "runs",
        results_dir=tmp_path / "results",
    )
    assert arm2.metrics.benign_utility.k == 1 and client2.summary.requests == 0
    md = render([arm])
    assert "100.0% [" in md and "groq/llama-3.3-70b-versatile" in md
    assert "[PENDING]" in render([])
    target = tmp_path / "RESULTS.md"
    write_report(tmp_path / "results", target)
    assert target.read_text().startswith("# Results")


def test_run_arm_with_attack_uses_named_important_instructions(tmp_path: Path):
    client = LLMClient(REF, transport=Scripted([]))  # always answers "done": no tools, nothing achieved
    spec = ArmSpec(
        model="groq/llama-3.3-70b-versatile",
        attack="important_instructions",
        user_tasks=["user_task_1"],
        injection_tasks=["injection_task_0"],
    )
    arm = run_arm(
        spec,
        build_pipeline(client, "none"),
        client,
        logdir=tmp_path / "runs",
        results_dir=tmp_path / "results",
    )
    assert arm.meta["attack_prose_model_name"] == "Llama"
    assert arm.metrics.targeted_asr.n == 1 and arm.metrics.targeted_asr.k == 0
    assert arm.metrics.utility_under_attack.k == 0 and arm.injection_tasks_as_user_tasks == {
        "injection_task_0": False
    }
    case = arm.cases[0]
    assert (
        case.user_task == "user_task_1"
        and case.injection_task == "injection_task_0"
        and case.security is False
    )
