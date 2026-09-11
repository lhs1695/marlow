"""Chinese HTML pages. Same gateway and ticket visibility as the JSON API."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from marlow.codes import (
    DECISION_APPROVE,
    DECISION_REJECT,
    NOT_ENOUGH_INFO,
    PERM_EDITOR,
    QUEUE_CHANGE,
    ROLE_ADMIN,
    RUN_CANCELLED,
    STATUS_WAITING_APPROVAL,
    SYSTEM_GRAFANA,
    TERMINAL_RUN_STATUSES,
    TICKET_NOT_FOUND,
    UNAUTHORIZED,
)
from marlow.comments import add_ticket_comment
from marlow.engine import claim_run_resume, create_run, http_fake_case_id, waiting_run_for_ticket
from marlow.gateway import apply_entitlement_change, entitlement_permission
from marlow.llm import want_real_llm
from marlow.models import AuditEvent, Run, Ticket
from marlow.runner import RunWorker
from marlow.tools.tickets import get_ticket, search_tickets
from marlow.web.auth import SESSION_ACTOR_KEY, actor_from_session
from marlow.web.deps import Db, enforce_limit
from marlow.web.display import (
    queue_zh,
    role_zh,
    run_status_zh,
    show_change_decisions,
    status_tone,
    status_zh,
)
from marlow.web.limits import MAX_INPUT_CHARS

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
TEMPLATES.env.globals.update(
    role_zh=role_zh,
    queue_zh=queue_zh,
    status_zh=status_zh,
    status_tone=status_tone,
    run_status_zh=run_status_zh,
)

_CHAT_SESSION_KEYS = (
    "chat_clarify",
    "chat_deny",
    "chat_answer",
    "chat_run_id",
    "chat_run_status",
    "chat_outcome",
    "chat_text",
)


def _page_ctx(request: Request, actor, db=None, **extra):
    query_role = request.query_params.get("role")
    ctx = {
        "request": request,
        "actor": actor,
        "query_role": query_role,
        "claim_mismatch": bool(query_role) and query_role != actor.role,
        "chat_clarify": request.session.get("chat_clarify"),
        "chat_deny": request.session.get("chat_deny"),
        "chat_answer": request.session.get("chat_answer"),
        "chat_run_id": request.session.get("chat_run_id"),
        "chat_run_status": request.session.get("chat_run_status"),
        "chat_outcome": request.session.get("chat_outcome"),
        "chat_text": request.session.get("chat_text"),
        "chat_run_done": False,
        **extra,
    }
    if db is not None:
        _hydrate_chat(request, db, actor, ctx)
    return ctx


def _hydrate_chat(request: Request, db, actor, ctx: dict) -> None:
    """Re-query Run on this request's session. Never use a worker-owned ORM object."""
    run_id = request.query_params.get("run_id") or request.session.get("chat_run_id")
    if not run_id:
        return
    run = db.get(Run, run_id)
    if run is None:
        return
    if run.actor_id != actor.id and actor.role != ROLE_ADMIN:
        return
    ctx["chat_run_id"] = run.id
    ctx["chat_run_status"] = run.status
    ctx["chat_outcome"] = run.outcome_code or ""
    if not ctx.get("chat_text"):
        ctx["chat_text"] = request.session.get("chat_text") or run.user_text
    ctx["chat_run_done"] = run.status in TERMINAL_RUN_STATUSES
    if run.status not in TERMINAL_RUN_STATUSES:
        ctx["chat_clarify"] = None
        ctx["chat_deny"] = None
        ctx["chat_answer"] = None
        return
    if run.outcome_code == NOT_ENOUGH_INFO:
        ctx["chat_clarify"] = run.final_answer or ""
        ctx["chat_deny"] = None
        ctx["chat_answer"] = None
    elif run.outcome_code == UNAUTHORIZED:
        ctx["chat_deny"] = run.final_answer or ""
        ctx["chat_clarify"] = None
        ctx["chat_answer"] = None
    else:
        ctx["chat_answer"] = run.final_answer or ""
        ctx["chat_clarify"] = None
        ctx["chat_deny"] = None
    if run.status == RUN_CANCELLED:
        ctx["chat_answer"] = run.final_answer or ""


def _with_run_id(nxt: str, run_id: str) -> str:
    if "run_id=" in nxt:
        return nxt
    sep = "&" if "?" in nxt else "?"
    return f"{nxt}{sep}run_id={run_id}"


def register_pages(app: FastAPI) -> None:
    @app.get("/")
    def login_page(request: Request):
        if request.session.get(SESSION_ACTOR_KEY):
            return RedirectResponse("/tickets", status_code=303)
        return TEMPLATES.TemplateResponse(request, "login.html")

    @app.get("/tickets")
    def ticket_list(request: Request, db: Db):
        actor = actor_from_session(request, db)
        obs = search_tickets(db, actor_id=actor.id, query="")
        tickets = (obs.data or {}).get("tickets") or []
        return TEMPLATES.TemplateResponse(request, "tickets.html", _page_ctx(request, actor, db, tickets=tickets))

    @app.get("/tickets/{ticket_id}")
    def ticket_detail(ticket_id: str, request: Request, db: Db):
        actor = actor_from_session(request, db)
        obs = get_ticket(db, actor_id=actor.id, ticket_id=ticket_id)
        if not obs.ok:
            if obs.code == TICKET_NOT_FOUND:
                raise HTTPException(status_code=404, detail=obs.code)
            if obs.code == UNAUTHORIZED:
                raise HTTPException(status_code=403, detail=obs.code)
            raise HTTPException(status_code=400, detail=obs.code)
        ticket = obs.data["ticket"]
        comments = obs.data["comments"]
        audits = list(
            db.scalars(
                select(AuditEvent)
                .where(AuditEvent.ticket_id == ticket_id)
                .order_by(AuditEvent.id.desc())
                .limit(30)
            )
        )
        permission = entitlement_permission(db, ticket["requester_id"], SYSTEM_GRAFANA)
        can_decide = show_change_decisions(
            role=actor.role,
            queue=ticket["queue"],
            status=ticket["status"],
        )
        return TEMPLATES.TemplateResponse(
            request,
            "ticket_detail.html",
            _page_ctx(
                request,
                actor,
                db,
                ticket=ticket,
                comments=comments,
                audits=audits,
                permission=permission,
                can_decide=can_decide,
            ),
        )

    @app.post("/tickets/{ticket_id}/comments")
    async def html_comment(ticket_id: str, request: Request, db: Db):
        actor = actor_from_session(request, db)
        form = await request.form()
        body = str(form.get("body") or "").strip()
        if not body or len(body) > MAX_INPUT_CHARS:
            raise HTTPException(status_code=400, detail="input_too_long" if body else "not_enough_info")
        result = add_ticket_comment(db, actor_id=actor.id, ticket_id=ticket_id, body=body)
        if not result.ok:
            status = 403 if result.code == UNAUTHORIZED else 400
            raise HTTPException(status_code=status, detail=result.code)
        db.commit()
        return RedirectResponse(f"/tickets/{ticket_id}", status_code=303)

    @app.get("/approvals")
    def approval_queue(request: Request, db: Db):
        actor = actor_from_session(request, db)
        if actor.role != ROLE_ADMIN:
            raise HTTPException(status_code=403, detail=UNAUTHORIZED)
        rows = list(
            db.scalars(
                select(Ticket)
                .where(Ticket.queue == QUEUE_CHANGE, Ticket.status == STATUS_WAITING_APPROVAL)
                .order_by(Ticket.id)
            )
        )
        return TEMPLATES.TemplateResponse(request, "approvals.html", _page_ctx(request, actor, db, tickets=rows))

    @app.post("/approvals")
    async def html_approval(request: Request, db: Db):
        actor = actor_from_session(request, db)
        if actor.role != ROLE_ADMIN:
            raise HTTPException(status_code=403, detail=UNAUTHORIZED)
        form = await request.form()
        ticket_id = str(form.get("ticket_id") or "")
        target = str(form.get("target_employee_id") or "")
        decision = str(form.get("decision") or "")
        if decision not in {DECISION_APPROVE, DECISION_REJECT}:
            raise HTTPException(status_code=400, detail="unauthorized")
        key = str(form.get("idempotency_key") or f"html-{ticket_id}-{decision}")
        waiting = waiting_run_for_ticket(db, ticket_id)
        result = apply_entitlement_change(
            db,
            actor_id=actor.id,
            ticket_id=ticket_id,
            target_employee_id=target,
            system=SYSTEM_GRAFANA,
            new_permission=PERM_EDITOR,
            decision=decision,
            idempotency_key=key,
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
            request.session["chat_run_id"] = resume_id
            return RedirectResponse(_with_run_id(f"/tickets/{ticket_id}", resume_id), status_code=303)
        return RedirectResponse(f"/tickets/{ticket_id}", status_code=303)

    @app.post("/chat")
    async def html_chat(request: Request):
        enforce_limit(request, "runs")
        form = await request.form()
        text = str(form.get("text") or "")
        nxt = str(form.get("next") or "/tickets")
        if not nxt.startswith("/"):
            nxt = "/tickets"
        if len(text) > MAX_INPUT_CHARS:
            raise HTTPException(status_code=400, detail="input_too_long")
        factory = request.app.state.session_factory
        with factory() as db:
            actor = actor_from_session(request, db)
            run = create_run(
                db,
                actor_id=actor.id,
                user_text=text,
                case_id=http_fake_case_id(text),
            )
            run_id = run.id
        worker: RunWorker = request.app.state.runner
        await worker.submit(run_id, real=want_real_llm())
        for key in _CHAT_SESSION_KEYS:
            request.session.pop(key, None)
        request.session["chat_run_id"] = run_id
        request.session["chat_text"] = text
        return RedirectResponse(_with_run_id(nxt, run_id), status_code=303)
