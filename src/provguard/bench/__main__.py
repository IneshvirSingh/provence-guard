"""CLI: python -m provguard.bench run|run-queue|report|check-models (wrapped by the Makefile).

Exit code 75 (EX_TEMPFAIL) means "stopped cleanly on the daily quota; run the same command again later".
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from provguard.bench.pipelines import DEFENSES, build_pipeline
from provguard.bench.report import write_report
from provguard.bench.runner import ArmSpec, run_arm
from provguard.llm.client import CacheStore, LLMClient, RedisCache
from provguard.llm.filestore import CACHE_FILE, QUOTA_FILE, FileCache, FileCounterStore
from provguard.llm.providers import ProviderRegistry
from provguard.llm.quota import CounterStore, QuotaExhausted, QuotaGuard, RedisStore

SMOKE_USER_TASKS = ["user_task_1", "user_task_3", "user_task_4", "user_task_7", "user_task_14"]
SMOKE_INJECTION_TASKS = ["injection_task_0", "injection_task_1"]
EXIT_QUOTA = 75  # EX_TEMPFAIL: the daily quota stopped the run; state is saved, resume with the same command


def _client(
    model: str, mode: str, cassette: str | None, redis_url: str | None, state_dir: str | None = None
) -> LLMClient:
    registry = ProviderRegistry.load()
    ref = registry.resolve(model)
    if mode != "replay":  # startup check: the configured ID must exist on the provider's live /models
        registry.check_models(ref.provider)
    cache: CacheStore | None = None
    counters: CounterStore | None = None
    if redis_url and state_dir:
        raise SystemExit("use --redis-url or --state-dir, not both (two counters would each undercount)")
    if redis_url:
        import redis

        r = redis.Redis.from_url(redis_url)
        cache = RedisCache(r)
        counters = RedisStore(r)
    elif state_dir:  # file-backed state for runs without Redis (GitHub Actions chunks, ADR-005)
        cache = FileCache(Path(state_dir) / CACHE_FILE)
        counters = FileCounterStore(Path(state_dir) / QUOTA_FILE)
    elif mode == "live":
        raise SystemExit(
            "live mode needs --redis-url or --state-dir (the quota guard is mandatory before any LLM call)"
        )
    quota = QuotaGuard(ref.id, ref.limits, counters) if counters is not None else None
    return LLMClient(ref, cache=cache, quota=quota, mode=mode, cassette=Path(cassette) if cassette else None)  # type: ignore[arg-type]


def load_queue(path: Path) -> list[ArmSpec]:
    """Arms in the order they should run. Top-level keys are defaults for every entry under ``arms``."""
    raw: dict[str, Any] = yaml.safe_load(path.read_text())
    defaults = {k: v for k, v in raw.items() if k != "arms"}
    return [ArmSpec(**{**defaults, **entry}) for entry in raw["arms"]]


def run_queue(ns: argparse.Namespace) -> int:
    """Run queued arms in order until all have a results file or the daily quota stops the run.

    Finished arms are skipped by their results file. An interrupted arm restarts from its first case,
    but every request it already paid for is a cache hit, so only the missing cases cost tokens.
    """
    results_dir = Path(ns.results_dir)
    for spec in load_queue(Path(ns.queue)):
        if (results_dir / f"{spec.file_stem}.json").exists():
            print(f"skip {spec.file_stem}: results file exists")
            continue
        print(f"run  {spec.file_stem}", flush=True)
        client = _client(spec.model, "live", None, ns.redis_url, ns.state_dir)
        client.seed = spec.seed
        pipeline = build_pipeline(client, spec.defense, suite=spec.suite)
        try:
            arm = run_arm(
                spec, pipeline, client, logdir=Path(ns.logdir), results_dir=results_dir, force_rerun=True
            )
        except QuotaExhausted as exc:
            print(f"quota stop in {spec.file_stem}: {exc}")
            print(client.summary)
            return EXIT_QUOTA
        print(arm.metrics.model_dump_json(indent=2))
        print(arm.usage)
    print("queue complete")
    return 0


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
    run.add_argument("--state-dir", default=None, help="file-backed cache + quota counters instead of Redis")
    run.add_argument("--user-task", action="append", default=[])
    run.add_argument("--injection-task", action="append", default=[])
    run.add_argument("--smoke", action="store_true", help="the fixed ~10-case smoke subset")
    run.add_argument("--force-rerun", action="store_true")
    run.add_argument("--label", default=None, help="results file suffix; default smoke/partial/none")
    run.add_argument("--seed", type=int, default=0, help="request seed; protocol run k uses seed k-1")
    run.add_argument("--no-schemas", action="store_true", help="provguard only: hide tool output schemas")
    run.add_argument("--logdir", default="runs", help="AgentDojo per-case logs (resume source)")
    run.add_argument("--results-dir", default="results")
    queue = sub.add_parser("run-queue", help="run the arms of a queue file in order until the quota stops")
    queue.add_argument("--queue", default="config/bench_queue.yaml")
    queue.add_argument("--redis-url", default=None)
    queue.add_argument("--state-dir", default=None)
    queue.add_argument("--logdir", default="runs")
    queue.add_argument("--results-dir", default="results")
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
    if ns.cmd == "run-queue":
        return run_queue(ns)
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
        seed=ns.seed,
    )
    client = _client(ns.model, ns.mode, ns.cassette, ns.redis_url, ns.state_dir)
    client.seed = ns.seed
    pipeline = build_pipeline(client, ns.defense, suite=ns.suite, use_schemas=not ns.no_schemas)
    try:
        arm = run_arm(
            spec,
            pipeline,
            client,
            logdir=Path(ns.logdir),
            results_dir=Path(ns.results_dir),
            force_rerun=ns.force_rerun,
        )
    except QuotaExhausted as exc:
        print(f"quota stop in {spec.file_stem}: {exc}")
        print(client.summary)
        return EXIT_QUOTA
    print(arm.metrics.model_dump_json(indent=2))
    print(arm.usage)
    return 0


if __name__ == "__main__":
    sys.exit(main())
