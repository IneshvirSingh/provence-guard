from pathlib import Path

import pytest

from provguard.bench import __main__ as cli
from provguard.bench.pipelines import DEFENSES
from provguard.bench.runner import ArmSpec
from provguard.llm.quota import QuotaExhausted


def test_committed_queue_is_valid() -> None:
    specs = cli.load_queue(Path("config/bench_queue.yaml"))
    assert specs and all(s.defense in DEFENSES for s in specs)
    assert len({s.file_stem for s in specs}) == len(specs)
    assert all(s.attack == "important_instructions" and s.suite == "banking" for s in specs)


def _queue(tmp_path: Path) -> Path:
    q = tmp_path / "queue.yaml"
    q.write_text(
        "suite: banking\nmodel: p/m\narms:\n  - {defense: none}\n  - {defense: tool_filter, label: r2}\n"
    )
    return q


class _Client:
    seed = 0
    summary = "usage"


def test_run_queue_skips_done_arms_and_stops_on_quota(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    results = tmp_path / "results"
    results.mkdir()
    (results / "banking__none__none__p_m.json").write_text("{}")
    ran: list[str] = []

    def fake_run_arm(spec: ArmSpec, *_: object, **kw: object) -> None:
        ran.append(spec.file_stem)
        assert kw["force_rerun"] is True
        raise QuotaExhausted("window full")

    monkeypatch.setattr(cli, "_client", lambda *a, **k: _Client())
    monkeypatch.setattr(cli, "build_pipeline", lambda *a, **k: object())
    monkeypatch.setattr(cli, "run_arm", fake_run_arm)
    code = cli.main(
        [
            "run-queue",
            "--queue",
            str(_queue(tmp_path)),
            "--state-dir",
            str(tmp_path),
            "--results-dir",
            str(results),
        ]
    )
    assert code == cli.EXIT_QUOTA
    assert ran == ["banking__tool_filter__none__p_m__r2"]
    assert "skip banking__none__none__p_m" in capsys.readouterr().out


def test_run_queue_complete_returns_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    results = tmp_path / "results"
    results.mkdir()
    for stem in ("banking__none__none__p_m", "banking__tool_filter__none__p_m__r2"):
        (results / f"{stem}.json").write_text("{}")
    monkeypatch.setattr(cli, "_client", lambda *a, **k: pytest.fail("no client needed"))
    assert cli.main(["run-queue", "--queue", str(_queue(tmp_path)), "--results-dir", str(results)]) == 0


def test_redis_and_state_dir_are_exclusive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class _Registry:
        def resolve(self, model: str) -> object:
            return type("Ref", (), {"provider": "p", "id": model, "limits": None})()

        def check_models(self, provider: str) -> list[str]:
            return []

    monkeypatch.setattr(cli.ProviderRegistry, "load", classmethod(lambda cls: _Registry()))
    with pytest.raises(SystemExit, match="not both"):
        cli._client("p/m", "replay", None, "redis://x", str(tmp_path))
    with pytest.raises(SystemExit, match="quota guard is mandatory"):
        cli._client("p/m", "live", None, None, None)
