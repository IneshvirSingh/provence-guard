# COSTS.md — ₹0 ledger

Every external service, whether it needs a payment method (verified by the human, not assumed), and its free
limits. `[PENDING]` until verified.

| service | purpose | payment method required? | free limits (copied from console) | data used for training? | verified on |
|---|---|---|---|---|---|
| GitHub Codespaces (personal) | dev environment | no (included quota) | 120 core-hours + 15 GB-month storage/month | n/a | 2026-11-12 (master prompt) |
| GitHub Actions (public repo) | CI/CD, maybe long runs | no | unlimited minutes for public repos | n/a | [PENDING] |
| Groq | agent-under-test LLM + Prompt Guard classifier | no (human-verified: no card requested anywhere) | gpt-oss-120b / qwen3.8-27b: 30 RPM, 1000 RPD, 8000 TPM, 200k TPD; prompt-guard-2: 30 RPM, 14400 RPD, 15000 TPM, 500k TPD (console; RPD+TPM header-confirmed) | [PENDING] (HUMAN_TODO 1.6) | 2026-11-13 |
| Gemini API (AI Studio) | (disabled 2026-11-13; qwen on Groq is the second family) | no (human-verified) | not needed | [PENDING] | 2026-11-13 |
| ~~GitHub Models~~ | – | retired 2026-07-30 | – | – | 2026-11-12 |
| Google Colab / Kaggle | detector training | no | T4 time-limited sessions | n/a | [PENDING] |
| Hugging Face Hub | model repo | no | public repos free | n/a | [PENDING] |
| Langfuse Cloud | traces | [PENDING] | [PENDING] | [PENDING] | [PENDING] |
| Neon | Postgres | [PENDING] | [PENDING] | n/a | [PENDING] |
| Upstash | Redis | [PENDING] | [PENDING] | n/a | [PENDING] |
| Qdrant Cloud | vectors | [PENDING] | [PENDING] | n/a | [PENDING] |
| Azure for Students | hosting | no card (student verification) | USD 100 credit + always-free services | n/a | [PENDING] |

Running total spent: ₹0.
