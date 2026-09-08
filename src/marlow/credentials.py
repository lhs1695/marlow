"""API key and local .env loading. No provider hostnames here."""

from __future__ import annotations

import os


def resolve_api_key() -> str:
    return os.environ.get("XAI_API_KEY", "").strip() or os.environ.get("OPENAI_API_KEY", "").strip()


def load_local_env() -> None:
    from dotenv import load_dotenv

    load_dotenv()
