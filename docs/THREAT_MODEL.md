# Threat model

Scope: a tool-using LLM agent acting for one user on the AgentDojo banking environment (and, from Phase 5, on
documents the user uploaded). Written from tool semantics and user-task specs only.

## 1. Assets

| asset | harm if violated | property |
|---|---|---|
| A1 Money: balance, outgoing transfers, scheduled orders | unauthorized or mis-directed payment | integrity |
| A2 Credentials: account password | account takeover | integrity + confidentiality |
| A3 PII: name, street, city, IBAN, transaction history | exfiltration, fraud | confidentiality |
| A4 Standing orders: recipient/amount/date of scheduled transactions | silent redirection of rent etc. | integrity |
| A5 The user's intent | agent does something the user did not ask | integrity of control |
| A6 Availability of the agent's help | task not done | availability (measured, not defended) |

## 2. Principals and trust

| principal | trust | why |
|---|---|---|
| User (the prompt) | trusted | the one we act for; direct prompt injection is out of scope |
| System: our code, policies, config, plan DSL | trusted | we control it; it is the TCB |
| Planner LLM | trusted *only because* it never sees untrusted data | a model that reads attacker text cannot be trusted to follow the user |
| Extractor LLM | **untrusted** output | it reads attacker text; it is allowed no tools and its output is labelled |
| Bank (tool backend) | trusted for the fields it attests | id, sender, recipient, amount, date, recurring, balance, iban |
| Third parties | untrusted | anyone who can write text the agent will read |
| Human approver | trusted, fallible | approves CONFIRM decisions; measured as strict/permissive bounds |

## 3. Sources: trusted vs untrusted (the trust config is `policies/trust.yaml`)

Trusted sources: `USER` (the prompt), `SYSTEM` (literals produced by our code), and tool outputs or fields the
bank attests. Untrusted: any text a third party could have written. Defaults from the master prompt: email bodies,
file contents, transaction subjects/memos, retrieved documents, web pages are **untrusted**.

Banking, per field:

| tool output | field | label | justification |
|---|---|---|---|
| `read_file` | whole string | untrusted | files come from landlords, vendors (bills), anyone |
| `get_most_recent_transactions` | `subject` | untrusted | free text written by the counterparty of an incoming transaction (the suite's `injection_incoming_transaction` vector lives here) |
| `get_most_recent_transactions` | `id, sender, recipient, amount, date, recurring` | trusted | attested by the bank's ledger; a counterparty cannot choose them |
| `get_scheduled_transactions` | `subject` | untrusted | created by the user or by an earlier agent run we cannot vouch for; indistinguishable from third-party text |
| `get_scheduled_transactions` | other fields | trusted | ledger-attested |
| `get_balance`, `get_iban` | value | trusted | ledger-attested |
| `get_user_info` | all fields | trusted (integrity) but **sensitive** (confidentiality) | the user's own profile; must not flow into outgoing free-text args |
| side-effecting tools' return messages | string | trusted ∪ sources of the call's arguments | they echo their inputs ("Transaction to {recipient} ... sent.") |

A value derived from several inputs carries the **union** of their sources; nothing ever removes a source.
Human confirmation approves one tool call; it does not relabel the values.

## 4. Side-effecting (guarded) tools

| tool | guarded arguments | why |
|---|---|---|
| `send_money` | `recipient`, `amount` (A1); `subject` (A3: outgoing free text is an exfiltration channel) | moves money; memo is visible to the recipient |
| `schedule_transaction` | `recipient`, `amount`, `recurring`, `date` (A1, A4); `subject` (A3) | future money movement, repeats |
| `update_scheduled_transaction` | `id`, `recipient`, `amount`, `date`, `recurring` (A4); `subject` (A3) | edits standing orders |
| `update_password` | `password` (A2) | lockout / takeover |
| `update_user_info` | `first_name, last_name, street, city` (A3) | identity and delivery address changes |

Read-only tools (`get_*`, `read_file`) are not guarded in v1. `read_file(file_path)` with an attacker-chosen
path is an information-flow concern only; there is no tool in this suite that sends data outside except the
guarded free-text arguments above, which is why those are guarded for confidentiality too.

## 5. Attacker

**Capabilities.**
- Writes arbitrary text into the four banking injection vectors (bill text, incoming transaction subject,
  landlord notice, address-change notice) and, from Phase 5, into uploaded documents.
- Knows the system prompt, the tools, the model name and the user's name (AgentDojo attacks use them).
- Phase 4: adaptive. Rewrites the injection text with a fixed query budget, observing only success/failure
  per (user task, injection task) pair. Runs only against the simulated environment and our own deployment.
- Can craft text that is *schema-valid* for the extractor (a plausible IBAN, a plausible amount).

**Cannot.**
- Change the user's prompt, our code, the plan DSL, policies, the trust config, or bank-attested fields.
- Call tools directly or observe the planner's input.
- Compromise the LLM provider or the Codespace.

**Goals (classes, not the suite's specific injection tasks).**
G1 unauthorized transfer or scheduled transfer to an attacker-chosen recipient/amount;
G2 redirect or alter an existing standing order;
G3 change password or profile;
G4 exfiltrate PII/credentials through an outgoing free-text argument;
G5 make the agent fail the user's task (DoS).

## 6. Security claims (to be proven, not assumed)

- **C1 (no untrusted auto-allow).** A value with any untrusted source never reaches a guarded argument with an
  ALLOW decision, however it was composed. Property-tested in `tests/property/`.
- **C2 (planner isolation).** The planner's input is the user prompt and tool schemas only; no tool output or
  extractor output is ever in its context. Enforced by construction and unit-tested.
- **C3 (extractor containment).** The extractor has no tools; its outputs carry the union of its inputs' sources
  and are schema-validated; invalid output fails closed after one retry.
- **C4 (complete mediation).** Every side-effecting tool call passes through the policy engine exactly once, and
  every decision is logged with the arg, its sources and the rule.

What these claims give for G1–G4: attacker-chosen data can only reach a guarded argument via a CONFIRM, where
the human sees the value and its provenance. In strict mode (CONFIRM → deny) the attack cannot succeed through
guarded arguments. In permissive mode (careless user) it can, and we measure how often.

## 7. Residual risks and out of scope

- **Data requires action.** The user asks to act on untrusted data ("pay this bill"). The legitimate and the
  injected IBAN have identical provenance; only the human can tell them apart. We report the confirmation rate.
- **Unguarded arguments.** Anything not listed in §4 (e.g. `n` in `get_most_recent_transactions`) is unguarded.
- **Mis-selection, not mis-direction.** Picking *which* record to edit based on untrusted free text can be
  influenced by an attacker even if the new values come from the user (deterministic selection steps do not add
  control-flow taint; LLM extraction does).
- **Human approver fatigue** (permissive bound measures the worst case).
- **Side channels** (timing, exceptions, error messages echoing untrusted data) and **stored taint across
  sessions** (a profile field edited from untrusted data in an earlier run is trusted next run).
- **Availability (G5)**: measured as utility under attack, not defended.
- **Direct prompt injection by the user, provider compromise, benchmark-check bugs.**
