"""Fake Action provider: scripts keyed by eval case id. No API Key."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from marlow.actions import Action, answer, skill, tool
from marlow.codes import DECISION_APPROVE, PERM_EDITOR, SKILL_ENTITLEMENT_CHANGE, SYSTEM_GRAFANA


class ActionProvider(Protocol):
    def next_action(self, ticket_id: str | None) -> Action: ...


@dataclass
class ScriptProvider:
    script: list[Action]
    _index: int = field(default=0, init=False)

    def next_action(self, ticket_id: str | None) -> Action:
        if self._index >= len(self.script):
            return answer()
        item = self.script[self._index]
        self._index += 1
        return item


@dataclass
class LoopToolProvider:
    tool_name: str
    arguments: dict

    def next_action(self, ticket_id: str | None) -> Action:
        args = dict(self.arguments)
        if ticket_id and "ticket_id" in args:
            args["ticket_id"] = ticket_id
        return tool(self.tool_name, **args)


def provider_for_case(case_id: str) -> ActionProvider:
    if case_id == "max_steps":
        return LoopToolProvider("get_ticket", {"ticket_id": "INC-1008"})
    scripts: dict[str, list[Action]] = {
        "investigate": [
            tool("get_ticket", ticket_id="INC-1001"),
            tool("search_kb", query="grafana login"),
            answer(),
        ],
        "timeout": [
            tool("get_asset", asset_id="ast-laptop-casey"),
        ],
        "l1_deny": [
            tool(
                "apply_entitlement_change",
                ticket_id="CHG-2004",
                target_employee_id="emp-007",
                system=SYSTEM_GRAFANA,
                new_permission=PERM_EDITOR,
                decision=DECISION_APPROVE,
                idempotency_key="fake-l1-deny",
            ),
        ],
        "change_hitl": [
            skill(
                SKILL_ENTITLEMENT_CHANGE,
                ticket_id="CHG-2004",
                target_employee_id="emp-007",
                system=SYSTEM_GRAFANA,
                new_permission=PERM_EDITOR,
            ),
        ],
    }
    if case_id not in scripts:
        raise KeyError(f"unknown fake case: {case_id}")
    return ScriptProvider(scripts[case_id])
