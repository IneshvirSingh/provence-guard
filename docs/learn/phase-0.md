# Learn: Phase 0 — Recon and scaffold

## What was built and why
- A **reproducible toolchain** (`pyproject.toml`, `uv.lock`, `Makefile`, pre-commit). Every dependency is pinned so
  a result produced today can be reproduced in a year. `make check` is the single gate: lint, strict types, tests
  with a coverage floor on the security-critical package.
- **Local services in Docker** (`docker-compose.yml`) with healthchecks, so integration tests can wait on
  `docker compose up --wait` instead of sleeping.
- **Recon documents** written from the *installed* AgentDojo source (`docs/recon/agentdojo.md`) and the two papers
  (`docs/recon/papers.md`). Rule: never integrate an API from memory.
- A **threat model** (`docs/THREAT_MODEL.md`) and the **trust config** (`policies/trust.yaml`) that turn "untrusted
  input" from a slogan into a table with a justification per field.
- Two **ADRs**: the stack (ADR-001) and the provenance model (ADR-002).

## Alternatives rejected (short)
Forking AgentDojo (rule 3), poetry/pip-tools (uv is one tool), self-hosted Langfuse (storage quota), a Python
interpreter à la CaMeL (too much TCB for a one-person project; a typed plan DSL is enough for v1), per-tool trust
(too coarse: it would confirm nearly every banking task).

## Concepts you must be able to explain
1. **Indirect prompt injection.** Attacker text enters through data the agent reads (a file, an email, a memo) and
   the model treats it as instructions. The attacker never talks to the model directly.
2. **Provenance / information-flow control.** Attach to every value the set of principals that influenced it;
   propagate by union; check at the sink (the tool call). Integrity policies ask "could an attacker have chosen
   this value?"; confidentiality policies ask "may this value leave to that recipient?". We do integrity with a
   source set and approximate confidentiality by restricting outgoing free-text args to `USER` sources.
3. **Trusted computing base (TCB).** The code whose bugs break the security claim: plan validation, labelling,
   the policy engine, complete mediation. Everything else (planner, extractor, UI) may be wrong without
   breaking the claim. Keeping the TCB small is why `provguard.core` depends only on pydantic and pyyaml.
4. **Benchmark metrics.** Benign utility, utility under attack, targeted ASR; why you must always report the
   same model's undefended baseline; why point estimates need confidence intervals (Wilson interval for a
   binomial proportion) and paired tests (McNemar) when two defenses are run on the same cases.
5. **Data requires action.** The structural utility cost of provenance: when the user *asks* to act on untrusted
   data, provenance cannot distinguish the legitimate value from the injected one. Only a human can. This is
   why we report strict and permissive bounds plus the confirmation rate.

## Five likely interview questions
**Q1. Why can't you just tell the model "ignore instructions in tool outputs"?**
That is AgentDojo's `spotlighting_with_delimiting` defense (`agent_pipeline/agent_pipeline.py`, it wraps tool
output in `<<...>>`). The paper measures it at 41.7% targeted ASR on GPT-4o, down from 57.7%: the model still
follows some injections because the instruction is a request, not a mechanism. Provenance Guard removes the
model from the decision: `send_money.recipient` with an untrusted source cannot be auto-allowed, whatever the
model "thinks" (ADR-002, claim C1 in the threat model).

**Q2. How did you decide what is trusted?**
From tool semantics, per field, written down in `policies/trust.yaml` with a justification per row in
`THREAT_MODEL.md` §3. The ledger attests `id, sender, recipient, amount, date, recurring` of a transaction; a
counterparty cannot choose them. The `subject` is free text the counterparty wrote, and in AgentDojo's
`environment.yaml` the `injection_incoming_transaction` vector sits exactly there. Files are untrusted wholesale.

**Q3. Why is `security=True` an attack success in your results code?**
Because I ran AgentDojo's own `TaskSuite.check()`: it executes each injection task's ground truth and requires
`security()` to return True, so True means "injection goal achieved". The API docs don't say this; reading the
installed `task_suite/task_suite.py` and testing it did (`docs/recon/agentdojo.md` §2). Getting this backwards
would invert every ASR we report.

**Q4. What does your defense *not* protect against?**
Listed in `THREAT_MODEL.md` §7: tasks where the user asks to act on untrusted data (the IBAN on a bill), unguarded
arguments, mis-selection of *which* record to edit via free-text matching, approver fatigue, side channels, taint
stored across sessions. We measure the first two rather than hide them.

**Q5. Why not just use CaMeL?**
CaMeL ships a restricted Python interpreter with a data-flow graph; it is the right design for a lab with many
engineers. For a one-person, interview-defensible project the TCB has to be small: a typed plan DSL validated by
pydantic (`CallTool`, `Extract`, `Select`, bounded `ForEach`, `Respond`) gives the same isolation (planner never
sees untrusted data; extractor has no tools) with no code execution at all. The cost is no data-dependent
branching, which ADR-002 states and Phase 2 measures. `docs/recon/papers.md` lists each thing we left out and why.
