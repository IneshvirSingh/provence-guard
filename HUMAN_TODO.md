# HUMAN_TODO.md

Things only you can do.

## 1. Groq free tier — DONE 2026-11-13 except step 6
Key is a Codespaces secret, limits are in `config/providers.yaml`, no payment method verified by you. Still open:
**1.6** read https://groq.com/privacy-policy (retention / training on API data) and put the one-line answer in
`docs/COSTS.md` row "Groq". Original steps kept for reference:
1. Go to https://console.groq.com and sign in (GitHub or Google login; do **not** add a card anywhere).
2. Left menu → **API Keys** → *Create API Key* → name it `provenance-guard-codespace` → copy it once.
3. GitHub → your repo → **Settings → Secrets and variables → Codespaces → New repository secret** → name
   `GROQ_API_KEY`, paste the key. Rebuild/restart the Codespace so the env var appears (`echo ${GROQ_API_KEY:+set}`).
4. Console → **Settings → Limits** (https://console.groq.com/settings/limits). For `llama-3.3-70b-versatile`,
   `llama-3.1-8b-instant` and `openai/gpt-oss-120b` copy RPM, RPD, TPM, TPD into `config/providers.yaml` under
   `limits:`. Replace the `null`s. The quota guard refuses to run on `null`.
5. Console → **Settings → Billing**: confirm the plan is *Free* and no payment method exists. Then set
   `requires_payment_method: false   # human-verified: 2026-MM-DD` in `config/providers.yaml`.
6. Read https://groq.com/privacy-policy (data retention / training on API data). Write the one-line answer into
   `docs/COSTS.md` row "Groq".

## 2. Gemini — DONE 2026-11-13 (key set, then disabled in favour of qwen/qwen3.8-27b on Groq)
Nothing left to do unless Groq's qwen model disappears. Original steps kept for reference:
1. https://aistudio.google.com → *Get API key* → create key in a new project. No billing account.
2. Codespaces secret `GEMINI_API_KEY` (same steps as 1.3).
3. https://ai.google.dev/gemini-api/docs/rate-limits → copy the **Free tier** RPM/TPM/RPD for the model with
   tool calling you intend to use (e.g. the current Flash model) into `config/providers.yaml` → `gemini.models`.
4. Confirm in AI Studio that no billing is enabled; record it in `docs/COSTS.md`.

## 3. GATE 0 review — DONE ("go" 2026-11-12)
Read, in order: `docs/THREAT_MODEL.md`, `policies/trust.yaml`, `docs/adr/ADR-002-provenance-model.md`,
`docs/recon/agentdojo.md` §6–7. Decisions to confirm or overrule:
- D1 Per-field trust: ledger fields of transactions are trusted, `subject` untrusted.
- D2 Deterministic selection does not add control-flow taint (CaMeL NORMAL mode).
- D3 Self-hosted Langfuse dropped; Langfuse Cloud or OTel-only.
- D4 Phase order: design doc + core before the Phase 1 harness.
Reply "go" (optionally with overrides).

## Later (not yet needed)
- Phase 3: Hugging Face account (free) for the model repo; Colab/Kaggle account.
- Phase 6/7: Azure for Students with college email (first); Neon, Upstash, Qdrant Cloud, Langfuse Cloud signups —
  verify "no payment method" at each and record limits in `docs/COSTS.md`.
- Phase 7: add `ghcr.io/devcontainers/features/terraform:1` to `.devcontainer/devcontainer.json` and rebuild.
