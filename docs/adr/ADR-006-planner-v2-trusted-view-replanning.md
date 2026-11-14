# ADR-006: planner-v2 — one bounded second planning round over a trusted view

Status: **accepted by the human on 2026-11-14 with the changes recorded in section 7; nothing built**
(written by Claude Fable 5.2). Implementation is for Claude Opus 5.5 after 2026-11-17. Section 5 is the
pre-registered evaluation plan, written before any v2 code exists. **Section 5, including the decision rule
5.5, is frozen as of 2026-11-14.** Later changes go only in dated addenda that say what changed and why, and
the original text stays.

## 1. Why (the trigger)
The human set the rule: if `provguard_strict` utility is below half of the undefended agent's, propose the
smallest version of "option 4". On 2026-11-14 the human decided the **audited** column governs and that the
trigger is met. Interim v1 numbers (2 of 3 protocol runs, `docs/RESULTS.md`): audited real completion
4/22 = 18.2% [7.3, 38.5] for strict against 11/22 = 50.0% [30.7, 69.3] undefended. Final v1 numbers: `[PENDING]`
run 3; they are reported first and unchanged whatever v2 does.

What the v1 failures say (`docs/FAILURES.md`, protocol runs): most strict misses are not policy denials. They
are plans written blind that do not fit the data: asking the user for a value that is in the ledger (F10),
wrong arithmetic direction (F15), paths that do not match the result's shape (F16), an incomplete or read-only
plan (F15 r2, F17), no data-dependent judgement (F6), malformed multi-goal plans (F12). The planner never sees
any tool result, including results that are fully trusted.

## 2. Decision: the one change
**Two-phase planning.** v1: `plan → run`. v2: `gather plan → run read-only → trusted view → final plan → run`.

1. **Round 1 (gather).** From the user request and tool schemas alone (as in v1), the planner emits a plan
   restricted to read-only tools plus `select / filter / reduce`. A static check rejects any side-effecting
   tool, `extract`, `foreach` and `respond` in this round. Bound: at most 4 calls.
2. **Trusted view.** The runner executes round 1 and renders its results for the planner under these rules:
   - a value is shown only if its provenance label contains **no untrusted source** (the same labels C1 uses);
   - a shown string must also have a **constrained format** declared in the output schema (date, IBAN-like
     identifier, enum, id) and match it within a length bound; numbers and booleans are shown as is;
   - everything else, including every field `policies/trust.yaml` marks untrusted, every `read_file` result and
     every free-text string from a trusted tool, is replaced by a typed placeholder such as
     `<untrusted:str>`. No length, no prefix, no hash.
3. **Round 2 (final plan).** The planner receives the user request, the schemas and the trusted view, and
   emits the final plan in the unchanged v1 plan language. It may reference round-1 results by name.
4. **Everything after that is v1, unchanged**: the same `PlanRunner`, the same policies, the same extractor,
   the same strict/permissive modes. Exactly one extra round; no loop, no third call.

Shipped as new defense names (`provguard_v2_strict`, `provguard_v2_permissive`) so every v1 arm stays
runnable from tag `planner-v1`. v2 is tagged `planner-v2` when frozen.

## 3. Security argument and what gets weaker
- **Kept:** the plan is still a function of trusted inputs only (user, system, trusted-labelled tool values),
  and every side-effecting call is still mediated by the same policy check. The C1 property tests must pass
  unmodified against the v2 path. New property test required: for arbitrary tool outputs, changing any
  untrusted-labelled value (or any unconstrained string) never changes the rendered trusted view.
- **Weaker 1 — `trust.yaml` matters more.** In v1 a wrongly trusted field could flow into an argument. In v2 it
  could steer the plan. The format rule limits this to typed, bounded values, but the trusted computing base
  grows and the threat model must say so.
- **Weaker 2 — attacker-influenced trusted fields.** Anyone can send the user a transaction, so the amount,
  sender and date of incoming rows are attacker-chosen even though the bank vouches for them. In v2 these typed
  values reach the planner. They cannot carry text, but they can bias a judgement (for example, which
  transaction "looks suspicious"). To be listed in `docs/THREAT_MODEL.md` as a residual risk.
- **Weaker 3 — existence and count channels.** The view shows how many records exist and which trusted fields
  they have. A few bits, attacker-influenced where the attacker can create records.
- **Weaker 4 — reads happen before the final plan.** Round 1 executes read-only tools chosen blind. Read tools
  must be side-effect free and the set is declared in policy, not inferred.
- Not claimed: v2 does nothing for attacks that work through the extractor's output values; those stay
  governed by the policies exactly as in v1.

## 4. Alternatives considered
- **Fix v1's individual failures (extractor robustness F13, respond templates F14).** Cheaper and probably
  worth more tasks per line of code, but that is the fix-and-rerun cycle the stop rule ended, on 11 informative
  tasks. Deliberately out of scope for v2: **v2 changes nothing but the planning rounds.**
- **Show the planner everything and rely on policies** (a guarded ReAct loop): gives up the property that
  untrusted text cannot influence control flow, which is the point of the project.
- **Unbounded re-planning:** harder to reason about, more quota, more attack surface.
- **Ship strict v1 as is and report the cost:** always available; it is the fallback in section 5.5.

## 5. Evaluation plan (pre-registered 2026-11-14, before any v2 code)

### 5.1 What is compared
`none`, `provguard_strict` (v1, tag `planner-v1`), `provguard_v2_strict`. Model `groq/openai/gpt-oss-120b`,
temperature 0, seeds 0–2. v1 results are the first reported result in every table; v2 is labelled as a later
architecture change motivated by v1's measured failures.

### 5.2 Development budget for v2 (to limit tuning on the 16 banking tasks)
- Development uses the banking **benign** arm only. No attacked run, no Slack run, during development.
- At most **two** full benign development runs of v2, each logged in `PROGRESS.md` with what changed after it.
  Then freeze: tag `planner-v2`. The stop rule applies again: after the freeze, failures are documented, not
  fixed. If a third development run seems necessary, stop and ask the human.
- Nothing task-specific in prompts, schemas or policies (unchanged rule).
- **Consequence, to be stated wherever v2 numbers appear:** v2 is developed on banking, so its banking numbers
  are in-sample. Any claim that v2 generalises rests on the Slack run alone.

### 5.3 Measurements after the freeze
1. **Banking benign, same protocol** (`docs/PROTOCOL.md`): 3 runs of `provguard_v2_strict`, same audit rule,
   same vacuous set (tasks 5, 6, 8, 9, 10). v1 and `none` numbers are reused from the v1 protocol files, not
   rerun.
2. **Banking attacked** (`important_instructions`): `provguard_v2_strict` through the Actions queue, after the
   v1 attacked arms exist. Reported: targeted ASR, utility under attack, confirmation rate, requests reaching
   a guarded call.
3. **Held-out Slack suite: frozen v1 and frozen v2, once each, side by side, after v2 is final.**
   Arms: `provguard_strict` (tag `planner-v1`) and `provguard_v2_strict` (tag `planner-v2`), plus `none` as the
   reference. "Once" means one execution of the fixed protocol per arm (benign with seeds 0–2, one attacked arm
   with `important_instructions`) and no repeat. v1 and v2 use the same Slack trust entries, policies and
   schemas.
   Preconditions, all committed and tagged (`slack-eval-v1`) **before the first Slack request**:
   Slack trust entries, policies and output schemas written from tool signatures and docstrings only (no Slack
   user-task or injection-task content is read, by the human or the agent); the vacuous-task set computed
   mechanically by `vacuous_user_tasks`. After the first Slack request nothing in prompts, schemas, policies
   or code may change for this evaluation, and there is no rerun except for infrastructure failures
   (quota stop, provider error), which resume from cache.
   Accepted consequence: this spends the Slack suite. After it, Slack is no longer held out for anything that
   comes later, and the write-up must say so. **The workspace and travel suites remain unseen**: no run, no
   policy, no schema and no task content from them has been used, and they stay that way unless the human
   decides otherwise.

### 5.4 Metrics and analysis
- **Primary:** audited real completion, benign, pooled over 3 runs with Wilson 95% intervals and per-run
  counts; per-task pass counts for all arms side by side.
- **Paired view:** for each non-vacuous task, passes out of 3 for v1 and v2; tasks gained and tasks lost are
  both listed. With 11 informative banking tasks no significance test has useful power, so none is used to
  claim an improvement; the intervals and the task table are the evidence.
- **Safety:** targeted ASR for v2 next to v1 with intervals. **Every** successful attack on v2 gets an
  individual entry in `docs/FAILURES.md` with the mechanism, even if the rate is within noise.
- **Cost:** tokens and requests per benign run for v1 and v2 (v2 adds one planner call per request).
- Official AgentDojo utility is reported next to the audited column everywhere, as in v1.

### 5.5 Decision rule (frozen 2026-11-14)
v2 becomes the shipped default only if **all three** hold. Counts are pooled over the 3 protocol runs.

(a) **Audited real completion improves by a stated margin.** On banking benign, v2 strict passes at least
    **6 more audited task-runs out of 33** than v1 strict (11 informative tasks × 3 runs; an average of two
    more tasks per run, about 18 percentage points). In addition v2 must reach at least half of the undefended
    arm's pooled audited completion, which was the original trigger for this ADR. The margin was chosen on
    2026-11-14 from v1's interim result (2 of 11 per run) and before any v2 result.
(b) **Targeted ASR no higher than v1.** On banking and on Slack separately, the number of successful attacks
    against v2 strict is less than or equal to the number against v1 strict on the same cases. Every successful
    attack on v2 is written up individually in `docs/FAILURES.md` whether or not (b) holds.
(c) **Slack utility no worse than v1.** On Slack benign, v2 strict's pooled audited real completion is greater
    than or equal to v1 strict's. Official utility is reported next to it but does not decide.

If any of the three fails, v1 stays the default and v2 is reported as a negative or mixed result with the same
tables. Either way both versions appear in the final report, v1 first.

### 5.6 Predictions (written before any v2 result, to be scored afterwards)
From the v1 failure table, which misses the trusted view could plausibly fix:
- Expected to help: F10 (task 11, amount is in the ledger), F15 (task 3), F16 (tasks 6, 15), F17 (task 12 only
  as far as planning; its file is untrusted so extraction still decides), F12 (task 15), F6 partly (task 14:
  judgement over amounts, dates and recipients, without subjects).
- Not expected to help: F13 (extractor returns no recipient: tasks 0, 2, 12), F5 (task 7, the match is on the
  untrusted subject), F18 (task 13, denied by design in strict mode). F14 (respond templates) may or may not
  improve.
- Stated guess: v2 strict lands between 3 and 6 of 11 audited tasks per run on banking (v1: 2 of 11). If the
  result is outside that range in either direction, the write-up says the prediction was wrong.

### 5.7 Quota
`[PENDING]` until one v2 run is measured. Expectation: roughly twice v1's planner tokens per request, so about
two benign runs per day. Attacked runs go through the Actions queue (ADR-005).

## 6. Work list for the implementer (not started)
Threat model update (section 3 residual risks) → format annotations in the planner-facing schemas → trusted
view renderer in `provguard.core` with the property test from section 3 → round-1 static check → second prompt
(fictional worked example only) → adapter and `DEFENSES` entries → unit tests → development runs (5.2) → freeze
→ measurements (5.3).

## 7. Decisions by the human (2026-11-14)
1. Spending the Slack suite: accepted, with the change that frozen v1 and frozen v2 both run on Slack, once
   each, side by side after v2 is final (5.3). Workspace and travel remain unseen.
2. Development budget of two benign runs: accepted. v2 is developed on banking, so generalisation claims rest
   on Slack only (5.2).
3. Decision rule: must require all three of (a) improvement in audited real completion by a stated margin
   pooled over 3 runs, (b) targeted ASR no higher than v1, (c) Slack utility no worse than v1. Rule 5.5 was
   rewritten to that and frozen. The margin in (a) (6 of 33 task-runs) was set by the author, not the human;
   the human can replace it by a dated addendum before v2 development starts, not after.
