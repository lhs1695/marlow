"""Live-model report collector. Not part of default pytest; numbers come from API usage."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import socket
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from marlow.credentials import load_local_env
from marlow.db import make_engine, prepare_database
from marlow.engine import ticket_status
from marlow.kb.embeddings import EMBEDDING_MODEL_ENV, KB_EMBEDDINGS_ENV
from marlow.llm import LLM_ENV, has_api_key, redact_secrets, resolve_chat_model, write_live_report
from marlow.models import Run, TicketComment
from marlow.stdio import ensure_utf8_stdio

ensure_utf8_stdio()

REPORT_DIR = Path("evals/live/reports")
KB_CITE_RE = re.compile(r"([\w.-]+@[\d.]+)")
DEFAULT_N = 10
APPENDIX_CASES = (1, 4, 5)
SSE_STOP_EVENTS = frozenset({"done", "waiting_approval"})


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


def error_run_record(
    *,
    case: int,
    case_id: str,
    latency_ms: float,
    error: str,
    first_event_ms: float | None = None,
) -> dict[str, Any]:
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
        "first_event_ms": None if first_event_ms is None else round(float(first_event_ms), 1),
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "assess_evidence_calls": 0,
        "assess_prompt_tokens": 0,
        "assess_completion_tokens": 0,
        "chat_model": "",
        "error": redact_secrets(error),
    }


def _sum_int(runs: list[dict[str, Any]], key: str) -> int:
    return sum(int(row.get(key) or 0) for row in runs)


def build_case2_report(
    runs: list[dict[str, Any]],
    *,
    date: str,
    chat_model: str,
    embedding_model: str,
    appendix: dict[str, Any] | None = None,
) -> dict[str, Any]:
    latencies = [float(row["latency_ms"]) for row in runs if row.get("latency_ms") is not None]
    first_events = [float(row["first_event_ms"]) for row in runs if row.get("first_event_ms") is not None]
    payload: dict[str, Any] = {
        "date": date,
        "chat_model": chat_model,
        "embedding_model": embedding_model,
        "provider": "openai-compat",
        "n": len(runs),
        "latencies_ms": [row.get("latency_ms") for row in runs],
        "p50_ms": round(percentile_ms(latencies, 50), 1),
        "p95_ms": round(percentile_ms(latencies, 95), 1),
        "first_event_ms": [row.get("first_event_ms") for row in runs],
        "p50_first_event_ms": round(percentile_ms(first_events, 50), 1),
        "p95_first_event_ms": round(percentile_ms(first_events, 95), 1),
        "prompt_tokens": _sum_int(runs, "prompt_tokens"),
        "completion_tokens": _sum_int(runs, "completion_tokens"),
        "assess_evidence_calls": _sum_int(runs, "assess_evidence_calls"),
        "assess_prompt_tokens": _sum_int(runs, "assess_prompt_tokens"),
        "assess_completion_tokens": _sum_int(runs, "assess_completion_tokens"),
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


class _ProviderUsage:
    """Collector-side probe. Does not change OpenAIActionProvider behavior, only wraps it."""

    def __init__(self) -> None:
        self.instances: list[Any] = []
        self.assess_calls = 0
        self.assess_prompt_tokens = 0
        self.assess_completion_tokens = 0

    def totals(self) -> SimpleNamespace:
        prompt = sum(int(getattr(row, "prompt_tokens", 0) or 0) for row in self.instances)
        completion = sum(int(getattr(row, "completion_tokens", 0) or 0) for row in self.instances)
        model = ""
        if self.instances:
            model = str(getattr(self.instances[-1], "model", "") or "")
        return SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion, model=model)


@contextmanager
def _track_openai_usage() -> Iterator[_ProviderUsage]:
    from marlow.llm import OpenAIActionProvider

    probe = _ProviderUsage()
    orig_init = OpenAIActionProvider.__init__
    orig_assess = OpenAIActionProvider.assess_evidence

    def init(provider: Any, *args: Any, **kwargs: Any) -> None:
        orig_init(provider, *args, **kwargs)
        probe.instances.append(provider)

    def assess(provider: Any, payload: dict[str, Any]) -> Any:
        before_prompt = int(getattr(provider, "prompt_tokens", 0) or 0)
        before_completion = int(getattr(provider, "completion_tokens", 0) or 0)
        try:
            return orig_assess(provider, payload)
        finally:
            probe.assess_calls += 1
            probe.assess_prompt_tokens += int(getattr(provider, "prompt_tokens", 0) or 0) - before_prompt
            probe.assess_completion_tokens += int(getattr(provider, "completion_tokens", 0) or 0) - before_completion

    OpenAIActionProvider.__init__ = init  # type: ignore[method-assign]
    OpenAIActionProvider.assess_evidence = assess  # type: ignore[method-assign]
    try:
        yield probe
    finally:
        OpenAIActionProvider.__init__ = orig_init  # type: ignore[method-assign]
        OpenAIActionProvider.assess_evidence = orig_assess  # type: ignore[method-assign]


def _sse_line_text(line: Any) -> str:
    if isinstance(line, bytes):
        return line.decode("utf-8")
    return str(line)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _QuietServer:
    """uvicorn.Server without signal handlers so it can run in a collector thread."""

    def __init__(self, app: Any, host: str, port: int) -> None:
        import uvicorn

        class _Server(uvicorn.Server):
            def install_signal_handlers(self) -> None:
                return

        self._server = _Server(
            uvicorn.Config(
                app,
                host=host,
                port=port,
                log_level="error",
                lifespan="on",
                timeout_graceful_shutdown=1,
            )
        )

    @property
    def started(self) -> bool:
        return bool(self._server.started)

    def run(self) -> None:
        self._server.run()

    def stop(self) -> None:
        self._server.should_exit = True


def _wait_until(predicate: Any, *, deadline: float, err: str) -> None:
    while time.perf_counter() < deadline:
        if predicate():
            return
    raise RuntimeError(err)


def _consume_run_sse(client: Any, run_id: str, started: float) -> tuple[float | None, float]:
    """Wall clock from submit until first SSE frame, then until done / waiting_approval."""
    first_event_ms: float | None = None
    with client.stream("GET", f"/api/runs/{run_id}/events") as response:
        if response.status_code != 200:
            raise RuntimeError(f"sse status {response.status_code}")
        for raw in response.iter_lines():
            line = _sse_line_text(raw)
            if first_event_ms is None and line.startswith(("id:", "event:", "data:")):
                first_event_ms = (time.perf_counter() - started) * 1000.0
            if line.startswith("event:"):
                name = line.split(":", 1)[1].strip()
                if name in SSE_STOP_EVENTS:
                    break
    latency_ms = (time.perf_counter() - started) * 1000.0
    return first_event_ms, latency_ms


def _case4_extra(session: Session) -> dict[str, Any]:
    from marlow.codes import DECISION_REJECT, PERM_EDITOR, SYSTEM_GRAFANA
    from marlow.gateway import apply_entitlement_change, entitlement_permission
    from marlow.seed import ADMIN_ID

    result = apply_entitlement_change(
        session,
        actor_id=ADMIN_ID,
        ticket_id="CHG-2003",
        target_employee_id="emp-006",
        system=SYSTEM_GRAFANA,
        new_permission=PERM_EDITOR,
        decision=DECISION_REJECT,
        idempotency_key="demo-case4-reject",
    )
    after = entitlement_permission(session, "emp-006", SYSTEM_GRAFANA)
    return {"admin_reject_code": result.code, "emp-006": after}


def _collect_http_case(engine: Engine, case: int, spec: dict[str, str], *, real: bool) -> dict[str, Any]:
    import httpx

    from marlow.web.app import create_app

    prev_llm = os.environ.get(LLM_ENV)
    if real:
        os.environ[LLM_ENV] = "real"
    started = 0.0
    first_event_ms: float | None = None
    server: _QuietServer | None = None
    thread: threading.Thread | None = None
    try:
        app = create_app(engine)
        port = _free_port()
        server = _QuietServer(app, "127.0.0.1", port)
        thread = threading.Thread(target=server.run, name=f"marlow-live-{port}", daemon=True)
        thread.start()
        _wait_until(
            lambda: server is not None and server.started,
            deadline=time.perf_counter() + 15,
            err="live uvicorn failed to start",
        )
        with _track_openai_usage() as probe:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=None, follow_redirects=True) as client:
                login = client.post("/login", json={"account": "l1", "password": "l1-demo"})
                if login.status_code != 200:
                    return error_run_record(
                        case=case,
                        case_id=spec["case_id"],
                        latency_ms=0,
                        error=f"login failed status={login.status_code} body={login.text}",
                    )
                started = time.perf_counter()
                created = client.post("/api/runs", json={"text": spec["text"]})
                if created.status_code != 202:
                    latency_ms = (time.perf_counter() - started) * 1000.0
                    return error_run_record(
                        case=case,
                        case_id=spec["case_id"],
                        latency_ms=latency_ms,
                        error=f"POST /api/runs status={created.status_code} body={created.text}",
                    )
                run_id = created.json()["run_id"]
                first_event_ms, latency_ms = _consume_run_sse(client, run_id, started)
            with Session(engine) as session:
                run = session.get(Run, run_id)
                if run is None:
                    return error_run_record(
                        case=case,
                        case_id=spec["case_id"],
                        latency_ms=latency_ms,
                        first_event_ms=first_event_ms,
                        error=f"run not found: {run_id}",
                    )
                extra: dict[str, Any] = {
                    "first_event_ms": None if first_event_ms is None else round(float(first_event_ms), 1),
                    "assess_evidence_calls": probe.assess_calls,
                    "assess_prompt_tokens": probe.assess_prompt_tokens,
                    "assess_completion_tokens": probe.assess_completion_tokens,
                }
                if case == 4:
                    extra.update(_case4_extra(session))
                    session.commit()
                return live_run_record(
                    session,
                    case=case,
                    case_id=spec["case_id"],
                    run=run,
                    latency_ms=latency_ms,
                    provider=probe.totals(),
                    extra=extra,
                )
    except Exception as exc:
        latency_ms = 0.0 if started == 0.0 else (time.perf_counter() - started) * 1000.0
        return error_run_record(
            case=case,
            case_id=spec["case_id"],
            latency_ms=latency_ms,
            first_event_ms=first_event_ms,
            error=str(exc),
        )
    finally:
        if server is not None:
            server.stop()
        if thread is not None:
            thread.join(timeout=15)
        if prev_llm is None:
            os.environ.pop(LLM_ENV, None)
        else:
            os.environ[LLM_ENV] = prev_llm


def collect_isolated_case(
    case: int,
    *,
    real: bool,
    llm_client: Any | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    from marlow.demo import DEMO_CASES

    del llm_client, verbose
    spec = DEMO_CASES[case]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "marlow.db"
        engine = make_engine("sqlite:///" + path.resolve().as_posix())
        prepare_database(engine)
        try:
            return _collect_http_case(engine, case, spec, real=real)
        finally:
            engine.dispose()


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
            f"first_event_ms={row.get('first_event_ms')} "
            f"prompt={row.get('prompt_tokens')} completion={row.get('completion_tokens')} "
            f"assess_calls={row.get('assess_evidence_calls')} "
            f"assess_prompt={row.get('assess_prompt_tokens')} "
            f"assess_completion={row.get('assess_completion_tokens')} "
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
                f"first_event_ms={row.get('first_event_ms')} "
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
