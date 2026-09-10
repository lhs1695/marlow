"""Skill match result and one-shot outcome. Not an inner Run loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SkillSpec:
    name: str
    version: str
    title: str
    skeleton: str
    draft_schema: dict[str, Any]


@dataclass
class SkillResult:
    finish: bool
    code: str
    answer: str
    hitl: bool = False
    draft: dict[str, Any] = field(default_factory=dict)
    verified_updates: dict[str, Any] = field(default_factory=dict)
    notes_untrusted: list[str] = field(default_factory=list)
    reflect: dict[str, Any] | None = None
