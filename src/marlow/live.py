"""Live-model report collector. Not part of default pytest; numbers come from API usage."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from marlow.credentials import load_local_env
from marlow.db import make_engine, prepare_database
from marlow.engine import ticket_status
from marlow.kb.embeddings import EMBEDDING_MODEL_ENV, KB_EMBEDDINGS_ENV
from marlow.llm import has_api_key, redact_secrets, resolve_chat_model, write_live_report
from marlow.models import TicketComment
from marlow.stdio import ensure_utf8_stdio

ensure_utf8_stdio()

REPORT_DIR = Path("evals/live/reports")
KB_CITE_RE = re.compile(r"([\w.-]+@[\d.]+)")
DEFAULT_N = 10
APPENDIX_CASES = (1, 4, 5)


def percentile_ms(values: list[float], p: float) -> float:
    """Linear interpolation percentile. p is 0–100. Empty → 0."""
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (p / 100.0) * (len(ordered) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    frac = rank - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def embedding_model_label() -> str:
    flag = os.environ.get(KB_EMBEDDINGS_ENV, "").strip().lower()
    model = os.environ.get(EMBEDDING_MODEL_ENV, "").strip()
    if flag in {"real", "openai", "1", "true"} and model:
        return model
    return "hash-fixture"


def _closing_comments(session: Session, ticket_id: str | None) -> list[str]:
    if not ticket_id:
        return []
    rows = session.scalars(select(TicketComment).where(TicketComment.ticket_id == ticket_id).order_by(TicketComment.id))
    return [redact_secrets(row.body) for row in rows]


def _citation(text: str, comments: list[str]) -> str | None:
    blob = " ".join([text, *comments])
    match = KB_CITE_RE.search(blob)
    return match.group(1) if match else None


def live_run_record(
    session: Session,
    *,
    case: int,
    case_id: str,
    run: Any,
    latency_ms: float,
    provider: Any | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prompt_tokens = int(getattr(provider, "prompt_tokens", 0) or 0) if provider is not None else 0
    completion_tokens = int(getattr(provider, "completion_tokens", 0) or 0) if provider is not None else 0
    chat_model = str(getattr(provider, "model", "") or "") if provider is not None else ""
    comments = _closing_comments(session, run.ticket_id)
    answer = redact_secrets(run.final_answer or "")
    record: dict[str, Any] = {
        "case": case,
        "case_id": case_id,
        "outcome_code": run.outcome_code,
        "status": run.status,
        "ticket_id": run.ticket_id,
        "ticket_status": ticket_status(session, run.ticket_id) if run.ticket_id else None,
        "citation": _citation(answer, comments),
        "closing_comments": comments,
        "final_answer": answer,
        "latency_ms": round(float(latency_ms), 1),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "chat_model": chat_model,
    }
    if extra:
        record.update(extra)
    return record


def error_run_record(*, case: int, case_id: str, latency_ms: float, error: str) -> dict[str, Any]:
    return {
        "case": case,
        "case_id": case_id,
        "outcome_code": None,
        "status": None,
        "ticket_id": None,
        "ticket_status": None,
        "citation": None,
        "closing_comments": [],
        "final_answer": None,
        "latency_ms": round(float(latency_ms), 1),
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "chat_model": "",
        "error": redact_secrets(error),
    }


def build_case2_report(
    runs: list[dict[str, Any]],
    *,
    date: str,
    chat_model: str,
    embedding_model: str,
    appendix: dict[str, Any] | None = None,
) -> dict[str, Any]:
    latencies = [float(row["latency_ms"]) for row in runs if row.get("latency_ms") is not None]
    payload: dict[str, Any] = {
        "date": date,
        "chat_model": chat_model,
        "embedding_model": embedding_model,
        "provider": "openai-compat",
        "n": len(runs),
        "latencies_ms": [row.get("latency_ms") for row in runs],
        "p50_ms": round(percentile_ms(latencies, 50), 1),
        "p95_ms": round(percentile_ms(latencies, 95), 1),
        "prompt_tokens": sum(int(row.get("prompt_tokens") or 0) for row in runs),
        "completion_tokens": sum(int(row.get("completion_tokens") or 0) for row in runs),
        "outcomes": [row.get("outcome_code") for row in runs],
        "ticket_statuses": [row.get("ticket_status") for row in runs],
        "runs": runs,
    }
    if appendix:
        payload["appendix"] = appendix
    return payload


def _report_path(date: str, chat_model: str, embedding_model: str, dest: Path | None) -> Path:
    if dest is not None:
        return dest
    safe_chat = chat_model.replace("/", "-") or "chat"
    safe_embed = embedding_model.replace("/", "-") or "embed"
    return REPORT_DIR / f"{date}-{safe_chat}-{safe_embed}.json"


def collect_isolated_case(
    case: int,
    *,
    real: bool,
    llm_client: Any | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    from marlow.demo import DEMO_CASES, run_demo_case

    spec = DEMO_CASES[case]
    engine = make_engine("sqlite:///:memory:")
    prepare_database(engine)
    with Session(engine) as session:
        try:
            row = run_demo_case(
                session,
                case,
                real=real,
                llm_client=llm_client,
                verbose=verbose,
            )
            session.commit()
        except Exception as exc:
            return error_run_record(case=case, case_id=spec["case_id"], latency_ms=0, error=str(exc))
        if row is None:
            return error_run_record(
                case=case,
                case_id=spec["case_id"],
                latency_ms=0,
                error="not a live OpenAI run",
            )
        return row


def main(argv: list[str] | None = None) -> int:
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Collect a live-model report (case 2 × n). Not CI.")
    parser.add_argument("--n", type=int, default=DEFAULT_N, help="case 2 repeats (default 10)")
    parser.add_argument(
        "--appendix",
        action="store_true",
        help="Also run demo cases 1, 4, 5 once each",
    )
    parser.add_argument("--out", type=Path, help="Report JSON path (gitignored)")
    args = parser.parse_args(argv)
    load_local_env()
    if not has_api_key():
        print("live requires XAI_API_KEY or OPENAI_API_KEY", file=sys.stderr)
        return 1
    if args.n < 1:
        print("--n must be >= 1", file=sys.stderr)
        return 1

    date = dt.date.today().isoformat()
    chat_model = resolve_chat_model()
    embedding_model = embedding_model_label()
    print(
        f"live case=2 n={args.n} chat_model={chat_model} embedding_model={embedding_model} provider=openai-compat"
    )

    runs: list[dict[str, Any]] = []
    for i in range(args.n):
        row = collect_isolated_case(2, real=True, verbose=False)
        runs.append(row)
        outcome = row.get("outcome_code") or row.get("error") or "?"
        ticket = row.get("ticket_status")
        print(
            f"case2 {i + 1}/{args.n} latency_ms={row.get('latency_ms')} "
            f"prompt={row.get('prompt_tokens')} completion={row.get('completion_tokens')} "
            f"outcome={outcome} ticket_status={ticket}"
        )

    appendix: dict[str, Any] | None = None
    if args.appendix:
        appendix = {}
        for case in APPENDIX_CASES:
            row = collect_isolated_case(case, real=True, verbose=False)
            appendix[str(case)] = row
            print(
                f"appendix case={case} latency_ms={row.get('latency_ms')} "
                f"outcome={row.get('outcome_code') or row.get('error')}"
            )

    payload = build_case2_report(
        runs,
        date=date,
        chat_model=chat_model,
        embedding_model=embedding_model,
        appendix=appendix,
    )
    path = _report_path(date, chat_model, embedding_model, args.out)
    write_live_report(path, payload)
    print(f"report={path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
