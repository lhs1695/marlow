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
    STATUS_WAITING_APPROVAL,
    SYSTEM_GRAFANA,
    TICKET_NOT_FOUND,
    UNAUTHORIZED,
)
from marlow.comments import add_ticket_comment
from marlow.engine import extract_ticket_id, start_run
from marlow.gateway import apply_entitlement_change, entitlement_permission
from marlow.llm import want_real_llm
from marlow.models import AuditEvent, Ticket
from marlow.tools.tickets import get_ticket, search_tickets
from marlow.web.auth import SESSION_ACTOR_KEY, actor_from_session
from marlow.web.deps import Db, enforce_limit
from marlow.web.limits import MAX_INPUT_CHARS

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _page_ctx(request: Request, actor, **extra):
    claim = request.query_params.get("role") or actor.role
    return {
        "request": request,
        "actor": actor,
        "page_claim": claim,
        "chat_clarify": request.session.pop("chat_clarify", None),
        "chat_deny": request.session.pop("chat_deny", None),
        "chat_answer": request.session.pop("chat_answer", None),
        **extra,
    }


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
        return TEMPLATES.TemplateResponse(request, "tickets.html", _page_ctx(request, actor, tickets=tickets))

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
        return TEMPLATES.TemplateResponse(
            request,
            "ticket_detail.html",
            _page_ctx(
                request,
                actor,
                ticket=ticket,
                comments=comments,
                audits=audits,
                permission=permission,
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
        return TEMPLATES.TemplateResponse(request, "approvals.html", _page_ctx(request, actor, tickets=rows))

    @app.post("/approvals")
    async def html_approval(request: Request, db: Db):
        actor = actor_from_session(request, db)
        form = await request.form()
        ticket_id = str(form.get("ticket_id") or "")
        target = str(form.get("target_employee_id") or "")
        decision = str(form.get("decision") or "")
        if decision not in {DECISION_APPROVE, DECISION_REJECT}:
            raise HTTPException(status_code=400, detail="unauthorized")
        key = str(form.get("idempotency_key") or f"html-{ticket_id}-{decision}")
        result = apply_entitlement_change(
            db,
            actor_id=actor.id,
            ticket_id=ticket_id,
            target_employee_id=target,
            system=SYSTEM_GRAFANA,
            new_permission=PERM_EDITOR,
            decision=decision,
            idempotency_key=key,
        )
        if not result.ok:
            status = 403 if result.code == UNAUTHORIZED else 400
            raise HTTPException(status_code=status, detail=result.code)
        return RedirectResponse(f"/tickets/{ticket_id}", status_code=303)

    @app.post("/chat")
    async def html_chat(request: Request, db: Db):
        actor = actor_from_session(request, db)
        enforce_limit(request, "runs")
        form = await request.form()
        text = str(form.get("text") or "")
        nxt = str(form.get("next") or "/tickets")
        if not nxt.startswith("/"):
            nxt = "/tickets"
        if len(text) > MAX_INPUT_CHARS:
            raise HTTPException(status_code=400, detail="input_too_long")
        case_id = str(form.get("case_id") or "").strip() or None
        if case_id is None and extract_ticket_id(text):
            case_id = "investigate"
        run = start_run(db, actor_id=actor.id, user_text=text, case_id=case_id, real=want_real_llm())
        if run.outcome_code == NOT_ENOUGH_INFO:
            request.session["chat_clarify"] = run.final_answer or ""
        elif run.outcome_code == UNAUTHORIZED:
            request.session["chat_deny"] = run.final_answer or ""
        else:
            request.session["chat_answer"] = run.final_answer or ""
        return RedirectResponse(nxt, status_code=303)
