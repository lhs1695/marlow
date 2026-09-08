"""Build a local Chroma persist directory from the pinned handbook. Default: hash embeddings, no API."""

from __future__ import annotations

import argparse
import sys

from marlow.credentials import load_local_env
from marlow.stdio import ensure_utf8_stdio


def main(argv: list[str] | None = None) -> int:
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Index pinned Grafana handbook into Chroma")
    parser.add_argument("--persist", default="chroma", help="Chroma persist directory (gitignored)")
    parser.add_argument(
        "--real",
        action="store_true",
        help="Use OpenAI-compatible embeddings (XAI_API_KEY or OPENAI_API_KEY). Default is hash embeddings.",
    )
    args = parser.parse_args(argv)
    load_local_env()

    from marlow.kb.embeddings import resolve_kb_embeddings
    from marlow.kb.split import split_handbook
    from marlow.kb.store import build_chroma

    chunks = split_handbook()
    embeddings = resolve_kb_embeddings(real=args.real)
    build_chroma(args.persist, embeddings=embeddings, chunks=chunks)
    print(f"indexed {len(chunks)} chunks into {args.persist} real={args.real}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
