# Live model reports

CI and `pytest` stay on Fake. Real-model numbers (p50/p95, token) belong in local reports here, with the **model name and date**, not in GitHub Actions.

The demo profile is xAI. Put keys and host in `.env` (see `.env.example`); do not hardcode the host in source. `XAI_API_KEY` is tried first, then `OPENAI_API_KEY`.

```bash
uv sync --extra llm
# .env: XAI_API_KEY, OPENAI_BASE_URL, MARLOW_CHAT_MODEL=grok-4.6
uv run python -m marlow.demo --case 2 --real --report evals/live/reports/case2.json
```

No Key → Fake automatically. Files under `reports/` are gitignored.

## Embeddings backend

Build and search must use the same embedding backend.

| `MARLOW_KB_EMBEDDINGS` | Index (`python -m marlow.kb`) and `search_kb` / `ensure_chroma_dir` |
| --- | --- |
| unset / empty | Hash fixture (same as today; CI) |
| `real` | OpenAI-compatible embeddings (`openai_compat_embeddings`) |

`python -m marlow.kb --real` also selects the compatible backend even if the env is unset; set `MARLOW_KB_EMBEDDINGS=real` when querying that persist dir (for example a later `chroma-xai/` tree). Hash `chroma/` and a real persist dir must not be mixed.
