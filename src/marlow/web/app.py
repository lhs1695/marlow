"""FastAPI app: cookie session, Run + SSE, ticket visibility. Entitlement writes still use the gateway."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.middleware.sessions import SessionMiddleware

from marlow.codes import (
    DECISION_APPROVE,
    ROLE_ADMIN,
    RUN_WAITING_APPROVAL,
    TERMINAL_RUN_STATUSES,
    TICKET_NOT_FOUND,
    UNAUTHORIZED,
)
from marlow.db import make_engine, prepare_database
from marlow.engine import claim_run_resume, create_run, http_fake_case_id, waiting_run_for_ticket
from marlow.gateway import apply_entitlement_change
from marlow.llm import want_real_llm
from marlow.models import Employee, Run, RunEvent
from marlow.runner import RunWorker
from marlow.tools.tickets import get_ticket
from marlow.web.auth import SESSION_ACTOR_KEY, actor_from_session, login_actor_id
from marlow.web.deps import Db, enforce_limit
from marlow.web.limits import MAX_INPUT_CHARS, MemoryRateLimiter

SESSION_SECRET_ENV = "MARLOW_SESSION_SECRET"
DATABASE_URL_ENV = "MARLOW_DATABASE_URL"
DEFAULT_SESSION_SECRET = "marlow-demo-secret-not-for-production"


class LoginBody(BaseModel):
    account: str
    password: str


class CreateRunBody(BaseModel):
    text: str
    case_id: str | None = Field(default=None, description="ignored; Fake case is not client-chosen")
    role: str | None = Field(default=None, description="ignored; role comes from session")


class EntitlementBody(BaseModel):
    ticket_id: str
    target_employee_id: str
    system: str
    new_permission: str
    decision: str = DECISION_APPROVE
    idempotency_key: str
    role: str | None = None


def _ensure_sqlite_dir(url: str) -> None:
    if not url.startswith("sqlite:///"):
        return
    path = url.removeprefix("sqlite:///")
    if not path or path == ":memory:":
        return
    parent = Path(path).parent
    if str(parent) not in {".", ""}:
        parent.mkdir(parents=True, exist_ok=True)


def create_app(
    engine: Engine | None = None,
    *,
    session_secret: str | None = None,
    limiter: MemoryRateLimiter | None = None,
) -> FastAPI:
    url = os.environ.get(DATABASE_URL_ENV, "sqlite:///data/marlow.db")
    if engine is None:
        _ensure_sqlite_dir(url)
        engine = make_engine(url)
        prepare_database(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    secret = session_secret or os.environ.get(SESSION_SECRET_ENV, DEFAULT_SESSION_SECRET)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        worker: RunWorker = app.state.runner
        await worker.start()
        yield
        await worker.stop()

    app = FastAPI(title="Marlow", lifespan=lifespan)
    app.add_middleware(SessionMiddleware, secret_key=secret)
    app.state.engine = engine
    app.state.session_factory = factory
    app.state.limiter = limiter or MemoryRateLimiter()
    app.state.runner = RunWorker(engine)

    from marlow.web.pages import register_pages

    register_pages(app)

    @app.post("/login")
    async def login(request: Request, db: Db) -> Any:
        enforce_limit(request, "login")
        ctype = request.headers.get("content-type", "")
        if "application/json" in ctype:
            payload = LoginBody.model_validate(await request.json())
            html = False
        else:
            form = await request.form()
            payload = LoginBody(
                account=str(form.get("account") or ""),
                password=str(form.get("password") or ""),
            )
            html = True
        actor_id = login_actor_id(payload.account, payload.password)
        employee = db.get(Employee, actor_id)
        if employee is None:
            raise HTTPException(status_code=401, detail="unauthorized")
        request.session[SESSION_ACTOR_KEY] = actor_id
        if html:
            return RedirectResponse("/tickets", status_code=303)
        return {"actor_id": employee.id, "role": employee.role}

    @app.post("/logout")
    def logout(request: Request) -> RedirectResponse:
        request.session.clear()
        return RedirectResponse("/", status_code=303)

    @app.get("/me")
    def me(request: Request, db: Db) -> dict[str, str]:
        actor = actor_from_session(request, db)
        return {"actor_id": actor.id, "role": actor.role}

    @app.get("/api/tickets/{ticket_id}")
    def ticket_detail_api(ticket_id: str, request: Request, db: Db) -> dict[str, Any]:
        actor = actor_from_session(request, db)
        obs = get_ticket(db, actor_id=actor.id, ticket_id=ticket_id)
        if not obs.ok:
            if obs.code == TICKET_NOT_FOUND:
                raise HTTPException(status_code=404, detail=obs.code)
            if obs.code == UNAUTHORIZED:
                raise HTTPException(status_code=403, detail=obs.code)
            raise HTTPException(status_code=400, detail=obs.code)
        return {"ticket": obs.data["ticket"], "comments": obs.data["comments"]}

    @app.post("/api/runs")
    async def create_run_api(body: CreateRunBody, request: Request) -> JSONResponse:
        enforce_limit(request, "runs")
        text = body.text
        if len(text) > MAX_INPUT_CHARS:
            raise HTTPException(status_code=400, detail="input_too_long")
        factory: sessionmaker[Session] = request.app.state.session_factory
        with factory() as db:
            actor = actor_from_session(request, db)
            run = create_run(
                db,
                actor_id=actor.id,
                user_text=text,
                case_id=http_fake_case_id(text),
            )
            payload = {
                "run_id": run.id,
                "request_id": run.request_id,
                "trace_id": run.trace_id,
            }
        worker: RunWorker = request.app.state.runner
        await worker.submit(payload["run_id"], real=want_real_llm())
        return JSONResponse(payload, status_code=202)

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str, request: Request, db: Db) -> dict[str, Any]:
        actor = actor_from_session(request, db)
        run = _run_for_actor(db, run_id, actor)
        return {
            "run_id": run.id,
            "request_id": run.request_id,
            "trace_id": run.trace_id,
            "status": run.status,
            "outcome_code": run.outcome_code,
            "final_answer": run.final_answer,
            "cancel_requested": bool(run.cancel_requested),
        }

    @app.post("/api/runs/{run_id}/cancel")
    def cancel_run(run_id: str, request: Request, db: Db) -> dict[str, Any]:
        actor = actor_from_session(request, db)
        run = _run_for_actor(db, run_id, actor)
        run.cancel_requested = True
        db.commit()
        return {
            "run_id": run.id,
            "cancel_requested": True,
            "status": run.status,
        }

    @app.get("/api/runs/{run_id}/events")
    async def run_event_stream(run_id: str, request: Request) -> StreamingResponse:
        factory: sessionmaker[Session] = request.app.state.session_factory
        with factory() as db:
            actor = actor_from_session(request, db)
            run = _run_for_actor(db, run_id, actor)
            request_id = run.request_id
            trace_id = run.trace_id
        last_id = _last_event_id(request)
        worker: RunWorker = request.app.state.runner
        engine: Engine = request.app.state.engine

        async def gen() -> AsyncIterator[str]:
            async for frame in iter_run_sse(
                worker,
                engine,
                run_id,
                last_id=last_id,
                request_id=request_id,
                trace_id=trace_id,
            ):
                yield frame

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    @app.post("/api/entitlements")
    async def entitlement_change(body: EntitlementBody, request: Request, db: Db) -> dict[str, Any]:
        actor = actor_from_session(request, db)
        waiting = waiting_run_for_ticket(db, body.ticket_id)
        result = apply_entitlement_change(
            db,
            actor_id=actor.id,
            ticket_id=body.ticket_id,
            target_employee_id=body.target_employee_id,
            system=body.system,
            new_permission=body.new_permission,
            decision=body.decision,
            idempotency_key=body.idempotency_key,
            run_id=None if waiting is None else waiting.id,
        )
        if not result.ok:
            status = 403 if result.code == UNAUTHORIZED else 400
            raise HTTPException(status_code=status, detail=result.code)
        claimed = False
        resume_id = None if waiting is None else waiting.id
        if resume_id is not None:
            claimed = claim_run_resume(db, resume_id)
        db.commit()
        if claimed and resume_id is not None:
            worker: RunWorker = request.app.state.runner
            await worker.submit(resume_id, real=want_real_llm())
        return {"ok": result.ok, "code": result.code}

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    return app


def _run_for_actor(db: Session, run_id: str, actor: Employee) -> Run:
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="not_found")
    if run.actor_id != actor.id and actor.role != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail=UNAUTHORIZED)
    return run


def _last_event_id(request: Request) -> int:
    raw = request.headers.get("last-event-id") or "0"
    try:
        value = int(raw)
    except ValueError:
        return 0
    return value if value > 0 else 0


def _is_terminal_status(status: str | None) -> bool:
    return status in TERMINAL_RUN_STATUSES


def _status_from_payload(kind: str, payload: str, fallback: str | None = None) -> str | None:
    if kind != "state":
        return fallback
    try:
        data = json.loads(payload) if payload else {}
    except json.JSONDecodeError:
        return fallback
    if isinstance(data, dict) and isinstance(data.get("status"), str):
        return data["status"]
    return fallback


async def iter_run_sse(
    worker: RunWorker,
    engine: Engine,
    run_id: str,
    *,
    last_id: int,
    request_id: str,
    trace_id: str,
) -> AsyncIterator[str]:
    queue = worker.subscribe(run_id)
    seen: set[int] = set()
    try:
        with Session(engine) as session:
            rows = list(
                session.scalars(
                    select(RunEvent)
                    .where(RunEvent.run_id == run_id, RunEvent.id > last_id)
                    .order_by(RunEvent.id)
                )
            )
            run = session.get(Run, run_id)
            status = None if run is None else run.status
        for row in rows:
            yield _sse_frame(row.kind, row.payload, request_id, trace_id, event_id=row.id)
            seen.add(row.id)
            status = _status_from_payload(row.kind, row.payload, status)
        if status == RUN_WAITING_APPROVAL:
            yield _sse_frame(
                "waiting_approval",
                json.dumps({"status": status}, ensure_ascii=False),
                request_id,
                trace_id,
            )
        if _is_terminal_status(status):
            yield _sse_done_frame(request_id, trace_id)
            return
        while True:
            item = await queue.get()
            event_id = item.get("id")
            if isinstance(event_id, int):
                if event_id <= last_id or event_id in seen:
                    continue
                seen.add(event_id)
            kind = str(item.get("kind") or "")
            payload = str(item.get("payload") or "{}")
            yield _sse_frame(
                kind,
                payload,
                request_id,
                trace_id,
                event_id=event_id if isinstance(event_id, int) else None,
            )
            status = _status_from_payload(kind, payload, str(item.get("status") or status) or None)
            if status == RUN_WAITING_APPROVAL:
                yield _sse_frame(
                    "waiting_approval",
                    json.dumps({"status": status}, ensure_ascii=False),
                    request_id,
                    trace_id,
                )
            if _is_terminal_status(status):
                yield _sse_done_frame(request_id, trace_id)
                return
    finally:
        worker.unsubscribe(run_id, queue)


def _sse_event_name(kind: str) -> str:
    if kind in {"observation", "retry"}:
        return "tool"
    if kind == "waiting_approval":
        return "waiting_approval"
    if kind in {"state", "action", "skill", "brake", "clarify"}:
        return "step"
    return kind


def _sse_frame(
    kind: str,
    payload: str,
    request_id: str,
    trace_id: str,
    event_id: int | None = None,
) -> str:
    try:
        data = json.loads(payload) if payload else {}
    except json.JSONDecodeError:
        data = {"raw": payload}
    if not isinstance(data, dict):
        data = {"raw": payload}
    data["kind"] = kind
    data["request_id"] = request_id
    data["trace_id"] = trace_id
    blob = json.dumps(data, ensure_ascii=False)
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {_sse_event_name(kind)}")
    lines.append(f"data: {blob}")
    lines.append("")
    return "\n".join(lines) + "\n"


def _sse_done_frame(request_id: str, trace_id: str) -> str:
    blob = json.dumps({"kind": "done", "request_id": request_id, "trace_id": trace_id}, ensure_ascii=False)
    return f"event: done\ndata: {blob}\n\n"
