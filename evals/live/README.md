# Live model reports

CI and `pytest` stay on Fake. Real-model numbers (p50/p95, token) belong in local reports here, with the **chat model, embedding model id, and date**, not in GitHub Actions.

Chat is xAI; embeddings are Jina. Put keys and hosts in `.env` (see `.env.example`); do not hardcode hosts in source. Chat tries `XAI_API_KEY` then `OPENAI_API_KEY`. Embeddings try `JINA_API_KEY` then `OPENAI_API_KEY`, never the xAI chat key.

One collector: `python -m marlow.live` (not a second competing `--report` schema). `demo --report` still writes **one** run (latency + API usage, no p50).

```bash
uv sync --extra llm
# .env: XAI_API_KEY, OPENAI_BASE_URL, MARLOW_CHAT_MODEL=grok-4.6
#       JINA_API_KEY, MARLOW_EMBEDDING_BASE_URL, MARLOW_EMBEDDING_MODEL=jina-embeddings-v3
#       MARLOW_KB_EMBEDDINGS=real, MARLOW_CHROMA_DIR=chroma-jina
uv run python -m marlow.live
# optional appendix (cases 1, 4, 5 once each; 4/5 final state is still the gateway):
uv run python -m marlow.live --appendix
```

Writes `evals/live/reports/{date}-{chat_model}-{embedding_model}.json` (gitignored). No chat Key → exit 1, no file. Not part of default `pytest`.

## Report fields

| Field | Source |
| --- | --- |
| `date` | Local calendar date |
| `chat_model` | `MARLOW_CHAT_MODEL` |
| `embedding_model` | `MARLOW_EMBEDDING_MODEL` when `MARLOW_KB_EMBEDDINGS=real`, else `hash-fixture` |
| `provider` | `openai-compat` |
| `n` | case 2 repeats (default 10) |
| `latencies_ms` | Wall clock of each complete Run (not a single HTTP call) |
| `p50_ms` / `p95_ms` | Linear interpolation over those n latencies |
| `prompt_tokens` / `completion_tokens` | Sum of API `usage` from the caller-held `OpenAIActionProvider` |
| `outcomes` / `ticket_statuses` | Per-run library end state (failures stay in the file) |
| `runs[]` | Each attempt: latency, tokens, outcome, ticket_status, citation, comments |
| `appendix` | Only with `--appendix` |

Token counts are API usage, not Fake `run.token_used` and not estimates. The engine does not grow a usage global; the live caller holds the provider and reads it after `start_run`.

## Embeddings backend

Build and search must use the same embedding backend.

| `MARLOW_KB_EMBEDDINGS` | Index (`python -m marlow.kb`) and `search_kb` / `ensure_chroma_dir` |
| --- | --- |
| unset / empty | Hash fixture (same as today; CI) |
| `real` | OpenAI-compatible embeddings (`openai_compat_embeddings`) |

`python -m marlow.kb --real` also selects the compatible backend even if the env is unset; set `MARLOW_KB_EMBEDDINGS=real` when querying that persist dir (`chroma-jina/`). Hash `chroma/` and a real persist dir must not be mixed.

Real embeddings send Jina `task=retrieval.passage` on documents and `task=retrieval.query` on queries (hash fixture does not). Tasks are request metadata only, not Observation / prompt text. Do not prepend `query:` / `passage:` string prefixes for Jina.

## Phase E smoke (2026-09-08)

Chat remains xAI `grok-4.6` (`chat.completions` + `emit_action` earlier the same day). Embeddings are Jina, not xAI.

| Call | Result |
| --- | --- |
| Jina `embed_query` / `embed_documents` `jina-embeddings-v3` | 1024-dim vectors |
| `python -m marlow.kb --persist chroma-jina --real` | 8 chunks |
| `search_kb` query `grafana-login` on `chroma-jina` | hit `grafana-login@10.4` first (untrusted) |

Hash `chroma/` was not written. `MARLOW_KB_EMBEDDINGS=real` and `MARLOW_CHROMA_DIR=chroma-jina` belong in local `.env` together so search uses the same backend.

## Phase F collect (2026-09-08)

Command: `uv run python -m marlow.live --appendix`. File (gitignored): `evals/live/reports/2026-09-08-grok-4.6-jina-embeddings-v3.json`.

case 2 × 10 all `ok` / `Resolved` with `grafana-login@10.4`. Tokens are API `usage`. One Run wall-clock stalled (~451s); that sample stays in `latencies_ms` and p95. Appendix case 1 never calls chat (no ticket id → clarify before `bind_provider`, tokens 0). Cases 4/5: gateway `unauthorized`; demo admin reject left `emp-006` as Viewer. Resume numbers are stage G.
