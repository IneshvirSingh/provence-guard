# Recon: the two papers we build on

Read 2026-11-12 from the arXiv HTML versions. Numbers below are **the papers' numbers**, quoted for context;
none of them is a Provenance Guard result.

## AgentDojo (Debenedetti et al., arXiv:2406.13352v3, Nov 2024)

**What it is.** A dynamic benchmark for prompt-injection attacks on tool-calling agents. Four suites
(workspace, slack, travel, banking) of *user tasks* (benign goals with ground-truth tool sequences and
programmatic utility checks on the environment/trace) and *injection tasks* (attacker goals with programmatic
security checks). Injections are placed in the environment through named *injection vectors* that the agent
only sees if it reads the relevant data. Paper counts: 97 user tasks, 27 injection tasks, 629 security cases;
installed v1.2.2 has grown to 97 user tasks and 35 injection tasks (see `agentdojo.md` §3).

**Metrics (§3.4).** *Benign utility*: fraction of user tasks solved without attack. *Utility under attack*:
user task solved with no adversarial side effect. *Targeted ASR*: fraction of security cases where the
attacker's goal is met. We add Wilson 95% CIs and McNemar paired tests (the paper reports point estimates).

**Attacks.** The main one is "Important message": an `<INFORMATION>` block that impersonates the user by name
and addresses the model by name, asking it to do the injection goal first. Also "ignore previous instructions",
InjecAgent, "TODO", a "max" oracle over the four, and untargeted DoS variants. Paper finding: the targeted attack
derails the model at least as effectively as DoS attempts.

**Defenses and headline numbers (GPT-4o, paper Table 5).**

| defense | benign utility | utility under attack | targeted ASR |
|---|---|---|---|
| none | 69.0% | 50.0% | 57.7% |
| spotlighting (data delimiting) | 72.7% | 55.6% | 41.7% |
| PI detector (ProtectAI DeBERTa) | 41.5% | 21.1% | 8.0% |
| repeat user prompt (sandwiching) | 85.5% | 67.3% | 27.8% |
| tool filter | 73.1% | 56.3% | 6.8% |

Take-aways we use: (1) the detector buys security by destroying utility (false positives drop needed data);
(2) tool filter is strong only when the attack needs a tool the user task does not, which the paper says fails
in ~17% of cases; (3) utility without attack is already far from 100%, so our evaluation must always report the
benign baseline of the *same* model.

**Limitations the authors state.** Simple attacks and defenses; utility criteria hand-written; no multimodal
agents; the data card says the benchmark is "unsuitable for evaluating defenses using only default attacks",
which is exactly why Phase 4 runs an adaptive attacker.

**What we take.** The benchmark as-is (pinned), its metrics, its shipped defenses as baselines, and its
pipeline-element API for integration. **What we leave out.** Nothing is modified (rule 3). Slack is held out.

## CaMeL: Defeating Prompt Injections by Design (Debenedetti et al., arXiv:2503.18813v2, Jun 2025)

**Architecture.** Two LLMs plus a custom interpreter.
- *P-LLM (privileged)* sees only the user query and tool docs and writes a program in a restricted Python
  subset. It never sees tool outputs.
- *Q-LLM (quarantined)* parses untrusted data into a schema given by the P-LLM's program (pydantic), has no
  tools, and reports `have_enough_information`.
- *Interpreter* executes the program, builds a data-flow graph, attaches **capabilities** to every value and
  enforces **security policies** at each tool call. The P-LLM is re-prompted up to 10 times on errors, with
  error text redacted if it depends on untrusted data.

**Capabilities.** Two dimensions per value: *sources* (User for literals, CaMeL for derived values, a tool, with
tools able to name an inner source such as an email's sender) and *readers* (Public or a set of principals).
Propagation: a derived value's dependencies are the union of its inputs' dependencies. Control flow: in NORMAL
mode branch/loop conditions do not taint assigned values; in STRICT mode they do; after a Q-LLM call all later
statements depend on its inputs.

**Policies (Appendix E).** Hand-written Python per tool. Banking `send_money`: allow if the recipient comes from
the user, otherwise the recipient must be able to read all components of the transaction. Workspace
`delete_file`: the file id must come directly from the user. Violations block the call; the paper says a real
deployment would ask the user instead.

**Results (Tables 2–4, v2).** Utility without attack overall: Claude 4 Sonnet native 86.6% vs CaMeL 74.2%;
Gemini 2.5 Pro 73.2% vs 41.2%; o3 84.5% vs 77.3%. Banking: Claude 4 Sonnet native 75.0% vs CaMeL 75.0%;
Gemini 2.5 Flash 43.8% vs 31.2%. Successful attacks overall (counts): Claude 4 Sonnet 75 → 11 (all 11 in travel,
through a policy gap); Gemini 2.5 Flash 297 → 1; o3 11 → 0. Banking attacks with CaMeL: 0 for every model.
Policy-trigger rate without attack (Table 8): 33.9% NORMAL, 53.2% STRICT, i.e. a third to a half of benign tasks
would need a user confirmation. Token overhead vs native tool calling (Table 10): 2.7× input / 2.8× output at
the median, 7.2× / 6.2× at the mean.

**Limitations the authors state.** Utility loss from "data requires action" tasks (the user explicitly asks to act
on untrusted data), under-documented tool APIs, and the Q-LLM not being able to ask the P-LLM for more context;
user fatigue from confirmations; the burden of writing policies; side channels through exceptions and timing;
no atomicity/rollback; control-flow-hijacking by composing allowed operations is possible.

**What we take.**
1. The split: a planner that never sees untrusted data, a quarantined extractor with no tools, deterministic
   policy enforcement before every side effect.
2. Source labels with union propagation and no declassification.
3. The "policy violation → user confirmation" framing, measured honestly as two bounds (strict/permissive) plus
   the confirmation rate.
4. Their failure taxonomy as the seed of `docs/FAILURES.md`.

**What we deliberately leave out (and why).**
1. **No Python interpreter.** Plans are a small typed DSL validated by pydantic (`CallTool`, `Extract`, bounded
   `ForEach`, `Respond`) instead of a restricted Python subset. Far less code to secure, much easier to explain
   in an interview, provably no code execution; the cost is no data-dependent branching in v1 (ADR + measured).
2. **Sources only, no readers in v1.** Confidentiality (who may see a value) is approximated by naming allowed
   source sets per outgoing argument (e.g. a transfer `subject` may only come from the user). A full readers
   lattice is listed as future work.
3. **Per-field trust labels** on tool outputs (`policies/trust.yaml`) instead of tool-developer-assigned
   capabilities, because we cannot modify AgentDojo's tools.
4. **No STRICT-mode control-flow taint** for deterministic plan steps; LLM extraction already taints its output
   with every input it saw, which covers the cases that matter for integrity.
5. **Models:** open-weight models on free tiers rather than frontier APIs, so utility numbers will be lower than
   the paper's and must be compared only against the *same* model undefended.
