"""Six ticket tools. MCP and later FastAPI call this layer, not SQL."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from marlow.faults import FaultHooks
from marlow.observation import Observation
from marlow.tools.assets import get_asset
from marlow.tools.kb import search_kb
from marlow.tools.tickets import get_ticket, search_tickets
from marlow.tools.writes import add_ticket_comment, apply_entitlement_change

TOOL_GET_TICKET = "get_ticket"
TOOL_SEARCH_TICKETS = "search_tickets"
TOOL_GET_ASSET = "get_asset"
TOOL_SEARCH_KB = "search_kb"
TOOL_ADD_TICKET_COMMENT = "add_ticket_comment"
TOOL_APPLY_ENTITLEMENT_CHANGE = "apply_entitlement_change"

TOOL_NAMES = (
    TOOL_GET_TICKET,
    TOOL_SEARCH_TICKETS,
    TOOL_GET_ASSET,
    TOOL_SEARCH_KB,
    TOOL_ADD_TICKET_COMMENT,
    TOOL_APPLY_ENTITLEMENT_CHANGE,
)


def execute_tool(
    session: Session,
    name: str,
    *,
    actor_id: str,
    faults: FaultHooks | None = None,
    **arguments: Any,
) -> Observation:
    hooks = faults or FaultHooks()
    target_id = arguments.get("ticket_id") or arguments.get("asset_id")
    if target_id is None and "query" in arguments:
        target_id = arguments.get("query")
    injected = hooks.check(name, None if target_id is None else str(target_id))
    if injected is not None:
        return injected
    if name == TOOL_GET_TICKET:
        return get_ticket(session, actor_id=actor_id, ticket_id=arguments["ticket_id"])
    if name == TOOL_SEARCH_TICKETS:
        return search_tickets(session, actor_id=actor_id, query=arguments.get("query", ""))
    if name == TOOL_GET_ASSET:
        return get_asset(session, actor_id=actor_id, asset_id=arguments["asset_id"])
    if name == TOOL_SEARCH_KB:
        return search_kb(query=arguments.get("query", ""))
    if name == TOOL_ADD_TICKET_COMMENT:
        return add_ticket_comment(
            session,
            actor_id=actor_id,
            ticket_id=arguments["ticket_id"],
            body=arguments["body"],
        )
    if name == TOOL_APPLY_ENTITLEMENT_CHANGE:
        return apply_entitlement_change(
            session,
            actor_id=actor_id,
            ticket_id=arguments["ticket_id"],
            target_employee_id=arguments["target_employee_id"],
            system=arguments["system"],
            new_permission=arguments["new_permission"],
            decision=arguments["decision"],
            idempotency_key=arguments["idempotency_key"],
        )
    raise ValueError(f"unknown tool: {name}")


__all__ = [
    "TOOL_NAMES",
    "add_ticket_comment",
    "apply_entitlement_change",
    "execute_tool",
    "get_asset",
    "get_ticket",
    "search_kb",
    "search_tickets",
]
