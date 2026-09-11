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
| `latencies_ms` | Wall clock of each complete Run (POST `/api/runs` through SSE `done` / `waiting_approval`; not a single HTTP call) |
| `p50_ms` / `p95_ms` | Linear interpolation over those n latencies |
| `first_event_ms` | Wall clock from POST `/api/runs` to the first SSE frame on that Run |
| `p50_first_event_ms` / `p95_first_event_ms` | Linear interpolation over those n first-event times |
| `prompt_tokens` / `completion_tokens` | Sum of API `usage` from the collector-wrapped `OpenAIActionProvider` |
| `assess_evidence_calls` / `assess_prompt_tokens` / `assess_completion_tokens` | Subset of that usage spent on `assess_evidence` (veto only; still included in the totals) |
| `runs[].assess_evidence` | Each veto call: the payload actually sent (ticket fields, draft reason, cited hit text) and the raw `sufficient` / `missing` / `reason` |
| `outcomes` / `ticket_statuses` | Per-run library end state (failures stay in the file) |
| `runs[]` | Each attempt: latency, first_event, tokens (incl. assess split), outcome, ticket_status, citation, comments |
| `appendix` | Only with `--appendix` |

Token counts are API usage, not Fake `run.token_used` and not estimates. The engine does not grow a usage global; the live collector wraps the provider and reads it after the SSE stream ends. `assess_*` is split out so the veto call is visible; it is also inside `prompt_tokens` / `completion_tokens`.

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

测于一期同步 Run，口径见 Phase H。

Command: `uv run python -m marlow.live --appendix`. File (gitignored): `evals/live/reports/2026-09-08-grok-4.6-jina-embeddings-v3.json`.

case 2 × 10 all `ok` / `Resolved` with `grafana-login@10.4`. Tokens are API `usage`. One Run wall-clock stalled (~451s); that sample stays in `latencies_ms` and p95. Appendix case 1 never calls chat (no ticket id → clarify before `bind_provider`, tokens 0). Cases 4/5: gateway `unauthorized`; demo admin reject left `emp-006` as Viewer. Resume numbers are stage G.

## Phase H collect (2026-09-10)

Command: `uv run python -m marlow.live --appendix`. File (gitignored): `evals/live/reports/2026-09-10-grok-4.6-jina-embeddings-v3.json`.

Collector now POSTs `/api/runs` (202) and times the first SSE frame (`first_event_ms`) plus full-run wall clock. `assess_evidence` usage is split out of the same API `usage` totals.

case 2 × 10: **none** `ok` / `Resolved` (all stay `Investigating`). 9× `not_enough_info` after `assess_evidence` vetoed twice and hit `max_reflect_rejections=2` (answer 证据复核已达上限). 1× `non_retryable` (run 4): model emitted `get_asset` without `asset_id`, worker `KeyError`, Run marked failed — kept in the file and in p95. Four runs still cited `grafana-login@10.4` in comments before the veto cap.

p50 / p95 latency `125900.2` / `169867.6` ms. p50 / p95 first_event `47.6` / `73.6` ms. Tokens: prompt `194664` / completion `9057`, of which assess `19` calls, prompt `24818` / completion `2300`. Slowest complete Run ~172s (run 1); no ~451s stall this round. The 172s is model turns + two assess calls, not a hung HTTP client.

Appendix case 1 never calls chat (no ticket id → clarify before bind, tokens 0). Cases 4/5: gateway `unauthorized`; demo admin reject left `emp-006` as Viewer.

## Phase I collect (2026-09-11)

Command: `uv run python -m marlow.live --appendix` with `MARLOW_KB_EMBEDDINGS=real`, `MARLOW_CHROMA_DIR=chroma-jina`, `MARLOW_CHAT_MODEL=grok-4.6`, `MARLOW_EMBEDDING_MODEL=jina-embeddings-v3`. File (gitignored): `evals/live/reports/2026-09-11-grok-4.6-jina-embeddings-v3.json`.

Diagnosed Phase H double-veto as (b): evidence payload already had ticket id, draft reason, and full cited hit text; the model was re-checking production RCA the rules do not require. Only `ASSESS_SYSTEM_PROMPT` changed (draft supported by cited snippet; do not re-check rules). `max_reflect_rejections` and fail-open unchanged.

case 2 × 10: 4× `ok` / `Resolved` (runs 2, 5, 9, 10, citation `grafana-login@10.4`). 5× `not_enough_info` / `Investigating` (runs 1, 3, 4, 6, 7). 1× `ok` / `Investigating` (run 8: one veto, then finished without a second close). No `get_asset` `non_retryable` this round (left for a later pass). Run 1 never reached assess (investigate-only). Samples stay in the file and in p95.

p50 / p95 latency `130101.6` / `378047.0` ms. p50 / p95 first_event `36.0` / `98.7` ms. Tokens: prompt `146220` / completion `7065`, of which assess `15` calls (11 veto / 4 allow), prompt `21401` / completion `1848`. Slowest complete Run ~564s (run 6); `first_event` was 55ms, so the stall is model/network turns, not a hung HTTP client. Phase H assess calls were 19, all vetoes.

Appendix case 1 never calls chat (no ticket id → clarify before bind, tokens 0). Cases 4/5: gateway `unauthorized`.
