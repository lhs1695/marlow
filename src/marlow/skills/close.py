"""Close ticket: require ticket_id + citation + reason. Reflect blocks incomplete evidence."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from marlow.actions import Action
from marlow.codes import (
    KB_MISS,
    KB_VERSION_MISMATCH,
    NOT_ENOUGH_INFO,
    QUEUE_L1,
    SKILL_CLOSE,
    SKILL_VERSION,
    STATUS_RESOLVED,
    TICKET_NOT_FOUND,
    UNAUTHORIZED,
)
from marlow.comments import add_ticket_comment
from marlow.models import Ticket
from marlow.observation import Observation
from marlow.skills.types import SkillResult, SkillSpec
from marlow.tools import TOOL_GET_TICKET, TOOL_SEARCH_KB

SPEC = SkillSpec(
    name=SKILL_CLOSE,
    version=SKILL_VERSION,
    title="关单结案",
    skeleton="必须有 ticket_id、引用、结案原因；缺证据或版本对不上则不关单",
    draft_schema={
        "type": "object",
        "properties": {
            "ticket_id": {"type": "string"},
            "kb_doc_id": {"type": "string"},
            "kb_version": {"type": "string"},
            "reason": {"type": "string", "description": "模型补评论措辞"},
        },
        "required": ["ticket_id", "kb_doc_id", "kb_version", "reason"],
    },
)

RunTool = Callable[[Action], Observation]


def apply_close(
    session: Session,
    *,
    actor_id: str,
    run_tool: RunTool,
    arguments: dict[str, Any],
    ticket_id: str | None,
) -> SkillResult:
    chosen = str(arguments.get("ticket_id") or ticket_id or "")
    kb_doc_id = str(arguments.get("kb_doc_id") or "").strip() or None
    kb_version = str(arguments.get("kb_version") or "").strip() or None
    reason = str(arguments.get("reason") or "").strip()
    draft = {
        "ticket_id": chosen,
        "kb_doc_id": kb_doc_id,
        "kb_version": kb_version,
        "reason": reason,
    }

    if not chosen or not kb_doc_id or not kb_version or not reason:
        return SkillResult(
            finish=True,
            code=NOT_ENOUGH_INFO,
            answer="关单缺引用或结案原因，仍为 Investigating。",
            draft=draft,
        )

    ticket_obs = run_tool(Action(kind="tool", name=TOOL_GET_TICKET, arguments={"ticket_id": chosen}))
    if not ticket_obs.ok:
        return SkillResult(
            finish=True,
            code=ticket_obs.code or TICKET_NOT_FOUND,
            answer=f"关单失败：{ticket_obs.code}。",
            draft=draft,
        )
    ticket_data = (ticket_obs.data or {}).get("ticket") or {}
    row = session.get(Ticket, chosen)
    if row is None:
        return SkillResult(finish=True, code=TICKET_NOT_FOUND, answer="关单失败：ticket_not_found。", draft=draft)
    if row.queue != QUEUE_L1:
        return SkillResult(finish=True, code=UNAUTHORIZED, answer="关单失败：unauthorized。", draft=draft)

    kb_obs = run_tool(
        Action(kind="tool", name=TOOL_SEARCH_KB, arguments={"query": f"{kb_doc_id} {kb_version}"})
    )
    if not kb_obs.ok:
        return SkillResult(
            finish=True,
            code=kb_obs.code or KB_MISS,
            answer="手册无命中，不关单，仍为 Investigating。",
            draft=draft,
        )
    hits = (kb_obs.data or {}).get("hits") or []
    matched = [
        hit
        for hit in hits
        if hit.get("doc_id") == kb_doc_id and hit.get("version") == kb_version
    ]
    if not matched:
        return SkillResult(
            finish=True,
            code=KB_VERSION_MISMATCH,
            answer="引用与授权手册版本对不上，不关单，仍为 Investigating。",
            draft=draft,
        )

    ticket_doc = ticket_data.get("kb_doc_id") or row.kb_doc_id
    ticket_ver = ticket_data.get("kb_version") or row.kb_version
    if ticket_doc != kb_doc_id or ticket_ver != kb_version:
        return SkillResult(
            finish=True,
            code=KB_VERSION_MISMATCH,
            answer="引用与工单手册版本对不上，不关单，仍为 Investigating。",
            draft=draft,
        )

    body = f"{reason} ticket_id={chosen} kb={kb_doc_id}@{kb_version}"
    comment = add_ticket_comment(session, actor_id=actor_id, ticket_id=chosen, body=body)
    if not comment.ok:
        return SkillResult(
            finish=True,
            code=comment.code,
            answer=f"关单评论失败：{comment.code}。",
            draft=draft,
        )
    row.status = STATUS_RESOLVED
    session.flush()
    return SkillResult(
        finish=True,
        code="ok",
        answer=f"已关单 Resolved。{body}",
        draft=draft,
        verified_updates={
            "ticket_id": chosen,
            "ticket_status": STATUS_RESOLVED,
            "kb_doc_id": kb_doc_id,
            "kb_version": kb_version,
        },
    )
