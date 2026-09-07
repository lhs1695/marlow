"""Thin MCP shell: schema + call into domain tools. No second write path."""

from __future__ import annotations

import os
from collections.abc import Callable

from mcp.server.mcpserver import MCPServer
from sqlalchemy.orm import Session, sessionmaker

from marlow.db import make_session_factory
from marlow.faults import FaultHooks
from marlow.tools import (
    TOOL_ADD_TICKET_COMMENT,
    TOOL_APPLY_ENTITLEMENT_CHANGE,
    TOOL_GET_ASSET,
    TOOL_GET_TICKET,
    TOOL_SEARCH_KB,
    TOOL_SEARCH_TICKETS,
    execute_tool,
)


def build_ticket_mcp(
    session_factory: Callable[[], Session] | sessionmaker[Session] | None = None,
    faults: FaultHooks | None = None,
) -> MCPServer:
    factory = session_factory or make_session_factory(
        os.environ.get("MARLOW_DATABASE_URL", "sqlite:///:memory:")
    )
    hooks = faults or FaultHooks()
    mcp = MCPServer("marlow-tickets")

    def _call(name: str, actor_id: str, **arguments: object) -> dict[str, object]:
        session = factory()
        try:
            obs = execute_tool(
                session,
                name,
                actor_id=actor_id,
                faults=hooks,
                **arguments,
            )
            session.commit()
            return obs.as_dict()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @mcp.tool(description="Load one ticket. Missing id returns ticket_not_found and is not retryable.")
    def get_ticket(actor_id: str, ticket_id: str) -> dict[str, object]:
        return _call(TOOL_GET_TICKET, actor_id, ticket_id=ticket_id)

    @mcp.tool(description="Search tickets. Server filters by the actor role and queue.")
    def search_tickets(actor_id: str, query: str = "") -> dict[str, object]:
        return _call(TOOL_SEARCH_TICKETS, actor_id, query=query)

    @mcp.tool(description="Load asset config and owner.")
    def get_asset(actor_id: str, asset_id: str) -> dict[str, object]:
        return _call(TOOL_GET_ASSET, actor_id, asset_id=asset_id)

    @mcp.tool(description="Search handbook fixtures. Hits include doc_id and version and are untrusted.")
    def search_kb(query: str, actor_id: str = "") -> dict[str, object]:
        return _call(TOOL_SEARCH_KB, actor_id or "emp-l1", query=query)

    @mcp.tool(description="Low-risk write: add a ticket comment. Observation body is untrusted.")
    def add_ticket_comment(actor_id: str, ticket_id: str, body: str) -> dict[str, object]:
        return _call(TOOL_ADD_TICKET_COMMENT, actor_id, ticket_id=ticket_id, body=body)

    @mcp.tool(description="High-risk entitlement change. Always goes through the approval gateway.")
    def apply_entitlement_change(
        actor_id: str,
        ticket_id: str,
        target_employee_id: str,
        system: str,
        new_permission: str,
        decision: str,
        idempotency_key: str,
    ) -> dict[str, object]:
        return _call(
            TOOL_APPLY_ENTITLEMENT_CHANGE,
            actor_id,
            ticket_id=ticket_id,
            target_employee_id=target_employee_id,
            system=system,
            new_permission=new_permission,
            decision=decision,
            idempotency_key=idempotency_key,
        )

    return mcp


def list_tool_schemas(server: MCPServer | None = None) -> list[dict[str, object]]:
    mcp = server or build_ticket_mcp()
    return [
        {"name": tool.name, "description": tool.description, "parameters": tool.parameters}
        for tool in mcp._tool_manager.list_tools()
    ]


def main() -> None:
    build_ticket_mcp().run(transport="stdio")


if __name__ == "__main__":
    main()
