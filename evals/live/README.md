# Live model reports

CI and `pytest` stay on Fake. Real-model numbers (p50/p95, token) belong in local reports here, with the **model name and date**, not in GitHub Actions.

```bash
uv sync --extra llm
# put OPENAI_API_KEY in .env (optional OPENAI_BASE_URL, MARLOW_CHAT_MODEL)
uv run python -m marlow.demo --case 2 --real --report evals/live/reports/case2.json
```

No Key → Fake automatically. Files under `reports/` are gitignored.
