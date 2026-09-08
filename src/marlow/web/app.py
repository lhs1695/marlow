"""FastAPI app: cookie session, Run + SSE, ticket visibility. Entitlement writes still use the gateway."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from starlette.middleware.sessions import SessionMiddleware

from marlow.codes import (
    DECISION_APPROVE,
    ROLE_ADMIN,
    RUN_WAITING_APPROVAL,
    TICKET_NOT_FOUND,
    UNAUTHORIZED,
)
from marlow.db import make_engine, prepare_database
from marlow.engine import http_fake_case_id, http_fake_faults, start_run
from marlow.gateway import apply_entitlement_change
from marlow.llm import want_real_llm
from marlow.models import Employee, Run, RunEvent
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
    app = FastAPI(title="Marlow")
    app.add_middleware(SessionMiddleware, secret_key=secret)
    app.state.engine = engine
    app.state.session_factory = factory
    app.state.limiter = limiter or MemoryRateLimiter()

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
    def create_run(body: CreateRunBody, request: Request, db: Db) -> dict[str, Any]:
        actor = actor_from_session(request, db)
        enforce_limit(request, "runs")
        text = body.text
        if len(text) > MAX_INPUT_CHARS:
            raise HTTPException(status_code=400, detail="input_too_long")
        run = start_run(
            db,
            actor_id=actor.id,
            user_text=text,
            case_id=http_fake_case_id(text),
            faults=http_fake_faults(text),
            real=want_real_llm(),
        )
        return {
            "run_id": run.id,
            "request_id": run.request_id,
            "trace_id": run.trace_id,
            "status": run.status,
            "outcome_code": run.outcome_code,
            "final_answer": run.final_answer,
        }

    @app.get("/api/runs/{run_id}/events")
    def run_event_stream(run_id: str, request: Request, db: Db) -> StreamingResponse:
        actor = actor_from_session(request, db)
        run = db.get(Run, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="not_found")
        if run.actor_id != actor.id and actor.role != ROLE_ADMIN:
            raise HTTPException(status_code=403, detail=UNAUTHORIZED)
        rows = list(db.scalars(select(RunEvent).where(RunEvent.run_id == run.id).order_by(RunEvent.id)))
        frames = [_sse_frame(row.kind, row.payload, run.request_id, run.trace_id) for row in rows]
        if run.status == RUN_WAITING_APPROVAL:
            frames.append(
                _sse_frame(
                    "waiting_approval",
                    json.dumps({"status": run.status}, ensure_ascii=False),
                    run.request_id,
                    run.trace_id,
                )
            )

        def gen() -> Iterator[str]:
            for frame in frames:
                yield frame

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/api/entitlements")
    def entitlement_change(body: EntitlementBody, request: Request, db: Db) -> dict[str, Any]:
        actor = actor_from_session(request, db)
        result = apply_entitlement_change(
            db,
            actor_id=actor.id,
            ticket_id=body.ticket_id,
            target_employee_id=body.target_employee_id,
            system=body.system,
            new_permission=body.new_permission,
            decision=body.decision,
            idempotency_key=body.idempotency_key,
        )
        if not result.ok:
            status = 403 if result.code == UNAUTHORIZED else 400
            raise HTTPException(status_code=status, detail=result.code)
        return {"ok": result.ok, "code": result.code}

    return app


def _sse_event_name(kind: str) -> str:
    if kind in {"observation", "retry"}:
        return "tool"
    if kind == "waiting_approval":
        return "waiting_approval"
    if kind in {"state", "action", "skill", "brake", "clarify"}:
        return "step"
    return kind


def _sse_frame(kind: str, payload: str, request_id: str, trace_id: str) -> str:
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
    return f"event: {_sse_event_name(kind)}\ndata: {blob}\n\n"
