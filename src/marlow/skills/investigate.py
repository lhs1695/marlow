"""Ticket investigation: frozen pull ticket → asset / history → KB gaps. Model fills conclusion."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from marlow.actions import Action
from marlow.codes import NOT_ENOUGH_INFO, SKILL_INVESTIGATE, SKILL_VERSION, TICKET_NOT_FOUND
from marlow.models import MemoryNote
from marlow.observation import Observation
from marlow.skills.types import SkillResult, SkillSpec
from marlow.tools import TOOL_GET_ASSET, TOOL_GET_TICKET, TOOL_SEARCH_KB, TOOL_SEARCH_TICKETS

SPEC = SkillSpec(
    name=SKILL_INVESTIGATE,
    version=SKILL_VERSION,
    title="工单调查",
    skeleton="拉单 → 资产 / 历史 → 对照规程缺口",
    draft_schema={
        "type": "object",
        "properties": {
            "ticket_id": {"type": "string"},
            "conclusion": {"type": "string", "description": "模型补调查结论"},
        },
        "required": ["ticket_id"],
    },
)

RunTool = Callable[[Action], Observation]


def load_memory_notes(
    session: Session, *, requester_id: str | None, asset_id: str | None
) -> list[str]:
    clauses = []
    if requester_id:
        clauses.append(MemoryNote.requester_id == requester_id)
    if asset_id:
        clauses.append(MemoryNote.asset_id == asset_id)
    if not clauses:
        return []
    rows = list(session.scalars(select(MemoryNote).where(or_(*clauses)).order_by(MemoryNote.id)))
    return [row.body for row in rows]


def apply_investigate(
    session: Session,
    *,
    run_tool: RunTool,
    arguments: dict[str, Any],
    ticket_id: str | None,
) -> SkillResult:
    chosen = str(arguments.get("ticket_id") or ticket_id or "")
    if not chosen:
        return SkillResult(finish=True, code=NOT_ENOUGH_INFO, answer="调查 Skill 缺 ticket_id。")

    ticket_obs = run_tool(Action(kind="tool", name=TOOL_GET_TICKET, arguments={"ticket_id": chosen}))
    if not ticket_obs.ok:
        code = ticket_obs.code or TICKET_NOT_FOUND
        return SkillResult(finish=True, code=code, answer=f"调查失败：{code}。")

    ticket = (ticket_obs.data or {}).get("ticket") or {}
    requester_id = ticket.get("requester_id")
    asset_id = ticket.get("asset_id")
    verified: dict[str, Any] = {
        "ticket_id": ticket.get("id", chosen),
        "ticket_status": ticket.get("status"),
        "requester_id": requester_id,
        "asset_id": asset_id,
    }
    if ticket.get("kb_doc_id"):
        verified["kb_doc_id"] = ticket["kb_doc_id"]
    if ticket.get("kb_version"):
        verified["kb_version"] = ticket["kb_version"]

    if asset_id:
        asset_obs = run_tool(Action(kind="tool", name=TOOL_GET_ASSET, arguments={"asset_id": asset_id}))
        if asset_obs.ok:
            asset = (asset_obs.data or {}).get("asset") or {}
            verified["asset"] = {
                "id": asset.get("id"),
                "owner_employee_id": asset.get("owner_employee_id"),
            }

    if requester_id:
        run_tool(
            Action(
                kind="tool",
                name=TOOL_SEARCH_TICKETS,
                arguments={"query": str(requester_id)},
            )
        )

    kb_query = str(ticket.get("kb_doc_id") or ticket.get("title") or chosen)
    kb_obs = run_tool(Action(kind="tool", name=TOOL_SEARCH_KB, arguments={"query": kb_query}))
    if kb_obs.ok:
        hits = (kb_obs.data or {}).get("hits") or []
        if hits:
            verified["kb_doc_id"] = hits[0].get("doc_id")
            verified["kb_version"] = hits[0].get("version")

    notes = load_memory_notes(session, requester_id=requester_id, asset_id=asset_id)
    verified["memory_notes_untrusted"] = notes

    conclusion = str(arguments.get("conclusion") or "对照规程后记录缺口。")
    parts = [
        conclusion,
        f"ticket_id={verified['ticket_id']}",
    ]
    if verified.get("kb_doc_id") and verified.get("kb_version"):
        parts.append(f"kb={verified['kb_doc_id']}@{verified['kb_version']}")
    if notes:
        parts.append("已注入同请求人/同资产笔记（untrusted）。")
    return SkillResult(
        finish=False,
        code="ok",
        answer=" ".join(parts),
        draft={"ticket_id": chosen, "conclusion": conclusion},
        verified_updates=verified,
        notes_untrusted=notes,
    )
