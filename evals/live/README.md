# Live model reports

CI and `pytest` stay on Fake. Real-model numbers (p50/p95, token) belong in local reports here, with the **model name and date**, not in GitHub Actions.

Chat is xAI; embeddings are Jina. Put keys and hosts in `.env` (see `.env.example`); do not hardcode hosts in source. Chat tries `XAI_API_KEY` then `OPENAI_API_KEY`. Embeddings try `JINA_API_KEY` then `OPENAI_API_KEY`, never the xAI chat key.

```bash
uv sync --extra llm
# .env: XAI_API_KEY, OPENAI_BASE_URL, MARLOW_CHAT_MODEL=grok-4.6
#       JINA_API_KEY, MARLOW_EMBEDDING_BASE_URL, MARLOW_EMBEDDING_MODEL=jina-embeddings-v3
uv run python -m marlow.demo --case 2 --real --report evals/live/reports/case2.json
```

No chat Key → Fake automatically. Files under `reports/` are gitignored.

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
