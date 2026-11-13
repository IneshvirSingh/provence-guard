"""CLI: python -m provguard.bench run|report  (wrapped by `make bench` / `make report`)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from provguard.bench.pipelines import DEFENSES, build_pipeline
from provguard.bench.report import write_report
from provguard.bench.runner import ArmSpec, run_arm
from provguard.llm.client import LLMClient, RedisCache
from provguard.llm.providers import ProviderRegistry
from provguard.llm.quota import QuotaGuard, RedisStore

SMOKE_USER_TASKS = ["user_task_1", "user_task_3", "user_task_4", "user_task_7", "user_task_14"]
SMOKE_INJECTION_TASKS = ["injection_task_0", "injection_task_1"]


def _client(model: str, mode: str, cassette: str | None, redis_url: str | None) -> LLMClient:
    registry = ProviderRegistry.load()
    ref = registry.resolve(model)
    if mode != "replay":  # startup check: the configured ID must exist on the provider's live /models
        registry.check_models(ref.provider)
    cache = None
    quota = None
    if redis_url:
        import redis

        r = redis.Redis.from_url(redis_url)
        cache = RedisCache(r)
        quota = QuotaGuard(ref.id, ref.limits, RedisStore(r))
    elif mode == "live":
        raise SystemExit("live mode needs --redis-url (the quota guard is mandatory before any LLM call)")
    return LLMClient(ref, cache=cache, quota=quota, mode=mode, cassette=Path(cassette) if cassette else None)  # type: ignore[arg-type]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="provguard.bench")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="run one arm")
    run.add_argument("--suite", default="banking")
    run.add_argument("--attack", default=None)
    run.add_argument("--defense", default="none", choices=DEFENSES)
    run.add_argument("--model", required=True, help="provider/model from config/providers.yaml")
    run.add_argument("--mode", default="live", choices=["live", "replay", "record"])
    run.add_argument("--cassette", default=None)
    run.add_argument("--redis-url", default=None)
    run.add_argument("--user-task", action="append", default=[])
    run.add_argument("--injection-task", action="append", default=[])
    run.add_argument("--smoke", action="store_true", help="the fixed ~10-case smoke subset")
    run.add_argument("--force-rerun", action="store_true")
    run.add_argument("--label", default=None, help="results file suffix; default smoke/partial/none")
    run.add_argument("--logdir", default="runs", help="AgentDojo per-case logs (resume source)")
    run.add_argument("--results-dir", default="results")
    sub.add_parser("report", help="write docs/RESULTS.md from results/*.json")
    check = sub.add_parser(
        "check-models", help="verify every enabled provider's model IDs against its /models"
    )
    check.add_argument("--provider", default=None, help="default: all enabled providers")
    ns = parser.parse_args(argv)

    if ns.cmd == "report":
        print(f"wrote {write_report()}")
        return 0
    if ns.cmd == "check-models":
        registry = ProviderRegistry.load()
        names = [ns.provider] if ns.provider else [n for n, p in registry.providers.items() if p.enabled]
        for name in names:
            live = registry.check_models(name)
            n = len(registry.providers[name].models)
            print(f"{name}: all {n} configured model(s) present ({len(live)} live)")
        return 0
    user_tasks = SMOKE_USER_TASKS if ns.smoke else ns.user_task
    injection_tasks = SMOKE_INJECTION_TASKS if ns.smoke else ns.injection_task
    label = ns.label or ("smoke" if ns.smoke else "partial" if (user_tasks or injection_tasks) else None)
    spec = ArmSpec(
        suite=ns.suite,
        attack=ns.attack,
        defense=ns.defense,
        model=ns.model,
        mode=ns.mode,
        user_tasks=user_tasks,
        injection_tasks=injection_tasks,
        label=label,
    )
    client = _client(ns.model, ns.mode, ns.cassette, ns.redis_url)
    pipeline = build_pipeline(client, ns.defense, suite=ns.suite)
    arm = run_arm(
        spec,
        pipeline,
        client,
        logdir=Path(ns.logdir),
        results_dir=Path(ns.results_dir),
        force_rerun=ns.force_rerun,
    )
    print(arm.metrics.model_dump_json(indent=2))
    print(arm.usage)
    return 0


if __name__ == "__main__":
    sys.exit(main())
