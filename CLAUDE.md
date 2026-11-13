# CLAUDE.md — Provenance Guard

Start of every session: read `PLAN.md`, `PROGRESS.md`, `HUMAN_TODO.md`, then `docs/HANDOFF.md`. Continue from
the last unfinished task. The full brief is `docs/Master_Prompt.md`; this file condenses its rules.

## Environment (GitHub Codespaces, 2 cores, ~17 GB free disk, storage quota counts)
- Tools come from `.devcontainer/devcontainer.json` only. Need a tool? Add a dev-container feature and ask the
  human to rebuild. No ad-hoc `apt install`.
- Python 3.12 + `uv`. `make setup` installs the locked dev env and pre-commit. `make check` = ruff + mypy
  --strict + pytest (coverage ≥ 85% on `provguard.core`). `make up` / `make down` for Redis, Postgres, Qdrant.
- Heavy deps are extras: `uv sync --extra bench` for AgentDojo (~200 MB); `ml` (torch) is never installed here.
- Secrets are Codespaces secrets as env vars (`GROQ_API_KEY`, `GEMINI_API_KEY`). Never files. `.env.example` only.
- Scratch work goes in the session scratchpad, not in the repo.

## Non-negotiables (from the master prompt §2)
1. No fabricated numbers. Metrics come from `results/*.json` via `make report`; unknown = `[PENDING]`.
2. Verify third-party APIs against installed source; record versions in the ADR. AgentDojo names come from the
   installed package (`docs/recon/agentdojo.md`).
3. No benchmark gaming: never edit AgentDojo tasks/checks/injections; **never read injection task contents**
   (`default_suites/*/injection_tasks.py` GOAL/security bodies); policies come from tool semantics + user-task
   specs. Slack suite is held out until Phase 9. Detector is never trained on AgentDojo strings.
4. ₹0: only providers listed in `config/providers.yaml` with `requires_payment_method: false`; quota guard before
   the first LLM call. Never suggest anything needing a card. **Never write model IDs from memory**: `make
   check-models` compares the config with the provider's live `/models` (it also runs before every live run).
5. Secrets never committed; gitleaks in pre-commit and CI; OIDC in CI/CD.
6. GATEs: run `make check`, update `PROGRESS.md`, summarize built/measured/broken/next, **stop and wait**.
7. Human-only actions go in `HUMAN_TODO.md` with click-by-click steps.
8. Teach: `docs/learn/phase-N.md` per phase (5 interview Q&As referencing real code); ADRs in `docs/adr/`.
9. Quality: pinned deps, ruff, mypy --strict, pytest, hypothesis property tests for provenance + policies, small
   conventional commits. Commit and push at the end of every session and before every GATE. Never force-push,
   rewrite history or open PRs without asking.
10. Honesty over polish. 11. Defensive only; attacks run against the simulated env / our own deployment.
12. Boring where possible; every component justified in an ADR.

## Conventions
- Layout: `src/provguard/{core,agent,llm,bench,detector,rag,service,observability}`, `policies/`, `config/`,
  `tests/{unit,property,integration,e2e}`, `results/`, `docs/{adr,recon,learn,design}`.
- `provguard.core` depends only on pydantic + pyyaml. No LLM calls, no I/O beyond loading YAML.
- Commit messages: conventional (`feat(core): ...`, `docs(adr): ...`, `chore: ...`).
- AgentDojo result semantics: `security=True` means the attack **succeeded** (ASR = mean). Don't invert it.
- Groq quirks: rejects `messages[].name`; 403 to urllib's default User-Agent; headers expose only RPD/TPM.
- Known AgentDojo quirks: `important_instructions` needs `pipeline.name` to contain a `MODEL_NAMES` key;
  `OpenAILLM` sends system prompts as `role="developer"`; `TaskSuite.check()` injectability test is broken.

## Session end checklist
`make check` green → update `PROGRESS.md` (and `docs/HANDOFF.md` if anything for the next model changed) →
commit → `git push`.
