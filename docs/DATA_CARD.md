# DATA_CARD.md — training and evaluation data for the Phase 3 injection detector

Status: **selection and design only** (2026-11-14). No dataset has been downloaded and no row has been
inspected yet; every row count that is not quoted from a source's own metadata is `[PENDING]` until the build
script writes `results/detector_data.json`. Licences were verified on 2026-11-14 from each source's live
metadata or licence file (Hugging Face `/api/datasets/<id>`, `datasets-server /info`, GitHub licence API), not
from memory.

## 1. Task the data must fit
Binary classification of a **piece of untrusted content as an agent would receive it from a tool** (an email
body, a document passage, a transaction note): label 1 if it contains text that tries to instruct the agent,
label 0 otherwise. This is indirect prompt injection (docs/THREAT_MODEL.md). It is not jailbreak detection
(a user attacking their own chatbot), which is why several popular jailbreak sets are excluded below.

A benign tool output is often imperative ("please pay the invoice by Friday"). The negatives therefore need
ordinary instructions and requests, not just encyclopaedic prose; otherwise the model learns "imperative =
attack" and destroys utility.

## 2. Selected sources

| # | Source (pinned revision) | Licence (where verified) | Used for | Size per source metadata |
|---|---|---|---|---|
| S1 | `microsoft/llmail-inject-challenge` on HF @ `1063bdf01ec8762b812d5e06ee768a06faa5a6f7`, files `data/labelled_unique_submissions_phase{1,2}.json`, `data/scenarios.json` | MIT (dataset card front matter) | Positives: attack emails (subject + body) submitted against an email assistant. Negatives: the benign emails of each scenario. Train/val/test. | 370,724 + 90,916 raw submissions; unique labelled files 448 MB + 69 MB; rows after our dedup `[PENDING]` |
| S2 | `microsoft/BIPIA` on GitHub @ `a004b69ec0dd446e0afd461d98cb5e96e120a5d0`, `benchmark/text_attack_{train,test}.json` and `benchmark/email/{train,test}.jsonl` only | Code and text attacks: MIT (repo `LICENSE`). Email contexts: from OpenAI Evals, MIT (stated in the same `LICENSE`). | Positives: an attack string inserted into an email context (start / middle / end). Negatives: the same contexts untouched (paired). Uses BIPIA's own train/test attack split. | `[PENDING]` (files are 6 KB + 6 KB attacks, 32 KB + 30 KB contexts) |
| S3 | `deepset/prompt-injections` on HF @ `4f61ecb038e9c3fb77e21034b22511b523772cdd` | Apache-2.0 on the dataset card; `datasets-server` info says `cc-by-4.0`. **Discrepancy recorded**; both permit this use with attribution, which the model card will give. | Both labels; short direct injections and benign prompts, English and German. Train/val/test (its own split is kept). | 546 train + 116 test |
| S4 | `databricks/databricks-dolly-15k` on HF @ `bdd27f4d94b9c1f951818a7da7fd7aeea5dbff1a` | CC BY-SA 3.0 (dataset card) | Negatives only: human-written instructions (imperative hard negatives) and reference passages. | 15,011 rows |
| S5 | `uiuc-kang-lab/InjecAgent` on GitHub @ `f19c9f2c79a41046eb13c03c51a24c567a8ffa07`, `data/test_cases_{dh,ds}_{base,enhanced}.json` | MIT (GitHub licence API) | **Held-out evaluation only, never trained on**: attacker instructions embedded in simulated tool responses. Out-of-distribution check closest to AgentDojo's setting. | 1,054 test cases per setting (repo README) |

Why these: S1 is the largest public set of *adaptive* indirect injections written by people trying to beat
real defenses, in the same medium (emails read by a tool-using assistant) as our threat model. S2 gives paired
positives and negatives that differ only by the injected span, which teaches the model to key on the injection
and not the topic. S3 adds short direct phrasing and a second language. S4 supplies the imperative negatives.
S5 is kept out of training so there is one evaluation set the model has never seen in any form.

## 3. Considered and excluded

| Source | Reason |
|---|---|
| AgentDojo (any suite, any version) | Master prompt rule 3: never train on benchmark strings. Enforced by section 5. |
| `xTRam1/safe-guard-prompt-injection`, `JasperLS/prompt-injections`, `imoxto/prompt_injection_cleaned_dataset-v2` | No licence declared in the card metadata. |
| `HumanCompatibleAI/tensor-trust-data` (GitHub) | No licence detected by the GitHub API. |
| `tatsu-lab/alpaca` | CC BY-NC 4.0; a non-commercial clause is avoided for a public model. |
| `hackaprompt/hackaprompt-dataset`, `allenai/wildjailbreak` | Gated (need a manual terms acceptance); jailbreak / prompt-hacking of a chatbot, not content read by a tool. |
| `jackhhao/jailbreak-classification`, `walledai/JailbreakHub` | Role-play jailbreaks; different threat. |
| `Lakera/gandalf_ignore_instructions`, `Lakera/mosscap_prompt_injection` | MIT, but one game with one goal (password extraction) and direct user prompts. Optional later as an extra evaluation set only. |
| `reshabhs/SPML_Chatbot_Prompt_Injection` | MIT, but the label depends on a paired system prompt; not a property of the text alone. |
| BIPIA table / code / web QA / summarisation contexts | CC BY-SA 4.0 (WikiTableQuestions, Stack Exchange) or must be fetched from the original publishers under their own terms. Email contexts are enough. |
| `rajpurkar/squad` | CC BY-SA 4.0; S4 already covers passages, and one share-alike source is easier to reason about than two. |
| `qualifire/prompt-injections-benchmark`, `Harelix/Prompt-Injection-Mixed-Techniques-2024` | Could not be verified through the public API on 2026-11-14. |

## 4. Known problems to handle in the build (all `[PENDING]` until measured)
- **S1 label noise.** Every submission is an attack attempt, including test messages and gibberish. Plan:
  label by intent (all are 1), drop bodies shorter than 5 words, and report results separately on the subset
  that reached the model (`email.retrieved`) as a sanity check. Do not label failed attacks 0.
- **S1 dominance and duplication.** Teams resubmitted near-identical emails hundreds of times. After dedup, cap
  S1 at a fixed number of rows per team and overall so it does not swamp S2–S4; caps are chosen from the
  measured distribution and written into the build config, not tuned on test metrics.
- **Group leakage.** Split S1 by `team_id` (all of a team's emails in one split). Split S2 by BIPIA's attack
  train/test files and by context id. Dedup runs across the whole pool before splitting, then a second pass
  removes any validation/test row whose near-duplicate is in train.
- **Class balance and length.** Positives in S1 are long emails; S3 rows are one line. Report metrics per
  source and per length bucket, not just pooled.
- **Benchmark format shift.** AgentDojo delivers injections inside YAML-like tool output. Inference will score
  each untrusted string field on its own (the same fields `policies/trust.yaml` marks untrusted), not the
  whole serialised tool result; this is a Phase 3 design decision to record in the detector ADR.
- **Personal data.** S1 emails are challenge submissions and simulated mailboxes; S2 emails come from a public
  eval set. We do not redistribute any rows: the repo ships the build script, pinned revisions and hashes.
- **Share-alike (S4).** We publish model weights and a build script, not the data. Whether weights are a
  derivative work of training text is legally unsettled; the model card will attribute Dolly and state the
  licence. If the human prefers zero share-alike exposure, replace S4 with synthetic benign instructions and
  say so here.
- **Languages.** Mostly English; S3 has German. No claim is made for other languages.

## 5. Leak check against AgentDojo (design; core implemented in `provguard.detector.leakcheck`)
Goal: after this check, no training, validation or test row contains, is contained in, or closely overlaps any
AgentDojo string. The check is mechanical, so nobody has to read injection task contents to run it (rule 3).

1. **Reference set** (`agentdojo_references()`), from the installed `agentdojo==0.1.35`, every registered suite
   (banking, slack, travel, workspace) and every benchmark version (v1 to v1.2.2):
   injection task `GOAL`s; injection-vector default strings; every string literal in `agentdojo/attacks/*.py`
   (attack templates such as `important_instructions`, extracted with `ast`); user task `PROMPT`s.
   Templates are split at `{placeholders}` so a filled-in template still matches its fixed parts.
   Measured 2026-11-14: 254 distinct fragments, 233 indexed (119 user prompts, 48 injection goals, 43 attack
   template fragments, 23 vector defaults). The 21 dropped fragments are shorter than 6 words (13 template
   fragments, 6 vector defaults, 2 user prompts; **no injection goal is dropped**).
2. **Normalisation**: NFKD, case-fold, strip accents, replace every non-alphanumeric run with one space. Case,
   punctuation, spacing and line-break edits cannot hide a copy.
3. **A row is a leak if any of these holds** against any reference:
   (a) the row contains the reference (word-boundary substring);
   (b) the row, if at least 6 words, is contained in the reference;
   (c) at least 50% of the reference's word 5-gram shingles occur in the row (catches light edits and partial
   copies). The maximum containment of every row is logged so the 0.5 threshold can be audited from the
   histogram instead of trusted.
4. **Action**: leaked rows are dropped from every split. The check runs after dedup and before splitting, and
   again on the final splits (must report zero).
5. **Evidence** written to `results/leak_check.json`: agentdojo version, number of references per category,
   rows checked and dropped per source × category × kind, containment histogram, threshold. Reports carry the
   reference's sha256 prefix, category and origin (`suite/version/task id`), never its text.
6. **The check must be shown to work, not just to pass** (a detector that reports zero leaks because it is
   broken is the dangerous case):
   - self-test at run time: every indexed reference must flag itself (233 of 233 on 2026-11-14), else abort;
   - unit and property tests (`tests/unit/detector/test_leakcheck.py`): verbatim, embedded, re-cased, truncated,
     lightly edited and template-filled copies are flagged; unrelated text is not;
   - a planted canary row per category in the Phase 3 pipeline test.
7. **Limits, stated honestly**: paraphrases that share no 5-word run with a reference and translations are not
   caught. Semantic similarity (an embedding check) is deliberately not used as a filter: removing everything
   that *means* "ignore previous instructions" would remove the task itself. The claim we can make is "no
   lexical overlap with benchmark strings", not "the benchmark's ideas are absent from public data".
   S5 (InjecAgent) and S1 were published by other groups; if the histogram shows clusters just under the
   threshold, they are reviewed by hash and count and the threshold decision is recorded here.

## 6. Build and provenance (Phase 3 tasks)
- Download and build happen on Colab/Kaggle (S1 is over 500 MB; the Codespace has no torch and little disk).
  The Codespace and CI run the same code on a small pinned sample.
- Every source is loaded at the revision pinned above; the build writes per-source row counts at each stage
  (raw → filtered → deduplicated → leak-checked → split) and sha256 of each split to
  `results/detector_data.json`. Numbers in this card are replaced from that file by `make report`.
- Dedup: exact match on the normalised text, then near-duplicate removal with the same 5-gram shingles
  (Jaccard ≥ 0.8), keeping the earliest row.
- Attribution for all five sources goes in the Hugging Face model card.

## 7. Open questions for the human
1. Accept S4's CC BY-SA 3.0 for negatives, or prefer synthetic negatives only?
2. S1 is 460k raw rows; is a capped subsample (order of 20–40k after dedup) acceptable for a free Colab T4
   session, with the cap fixed before any test metric is seen?
