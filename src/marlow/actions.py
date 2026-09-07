from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from marlow.codes import ACTION_ANSWER, ACTION_SKILL, ACTION_TOOL


@dataclass(frozen=True)
class Action:
    kind: Literal["answer", "skill", "tool"]
    name: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    text: str = ""


def answer(text: str = "") -> Action:
    return Action(kind=ACTION_ANSWER, text=text)


def skill(name: str, **arguments: Any) -> Action:
    return Action(kind=ACTION_SKILL, name=name, arguments=dict(arguments))


def tool(name: str, **arguments: Any) -> Action:
    return Action(kind=ACTION_TOOL, name=name, arguments=dict(arguments))
