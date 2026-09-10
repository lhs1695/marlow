"""Four Skills: match by name + version, one-shot skeleton, parameter drafts. Not a nested Agent."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from marlow.actions import Action
from marlow.codes import (
    SKILL_CLOSE,
    SKILL_ENTITLEMENT_CHANGE,
    SKILL_INVESTIGATE,
    SKILL_KB_QA,
    SKILL_VERSION,
)
from marlow.evidence import EvidenceAssessment
from marlow.observation import Observation
from marlow.skills.change import SPEC as CHANGE_SPEC
from marlow.skills.change import apply_change
from marlow.skills.close import SPEC as CLOSE_SPEC
from marlow.skills.close import apply_close
from marlow.skills.investigate import SPEC as INVESTIGATE_SPEC
from marlow.skills.investigate import apply_investigate
from marlow.skills.kb_qa import SPEC as KB_QA_SPEC
from marlow.skills.kb_qa import apply_kb_qa
from marlow.skills.types import SkillResult, SkillSpec

SKILLS: dict[str, SkillSpec] = {
    SKILL_INVESTIGATE: INVESTIGATE_SPEC,
    SKILL_KB_QA: KB_QA_SPEC,
    SKILL_CLOSE: CLOSE_SPEC,
    SKILL_ENTITLEMENT_CHANGE: CHANGE_SPEC,
}

RunTool = Callable[[Action], Observation]
AssessEvidence = Callable[[dict[str, Any]], EvidenceAssessment | None]


def match_skill(name: str | None, version: str | None = None) -> SkillSpec | None:
    if not name:
        return None
    spec = SKILLS.get(name)
    if spec is None:
        return None
    if version and version != spec.version:
        return None
    return spec


def apply_skill(
    session: Session,
    *,
    actor_id: str,
    name: str | None,
    arguments: dict[str, Any],
    ticket_id: str | None,
    run_tool: RunTool,
    assess_evidence: AssessEvidence | None = None,
    reflect_rejections: int = 0,
) -> SkillResult:
    version = arguments.get("skill_version") or arguments.get("version") or SKILL_VERSION
    spec = match_skill(name, str(version) if version else None)
    if spec is None:
        return SkillResult(finish=True, code="non_retryable", answer="未知或不匹配的 Skill。")
    if spec.name == SKILL_INVESTIGATE:
        return apply_investigate(
            session, run_tool=run_tool, arguments=arguments, ticket_id=ticket_id
        )
    if spec.name == SKILL_KB_QA:
        return apply_kb_qa(run_tool=run_tool, arguments=arguments)
    if spec.name == SKILL_CLOSE:
        return apply_close(
            session,
            actor_id=actor_id,
            run_tool=run_tool,
            arguments=arguments,
            ticket_id=ticket_id,
            assess_evidence=assess_evidence,
            reflect_rejections=reflect_rejections,
        )
    if spec.name == SKILL_ENTITLEMENT_CHANGE:
        return apply_change(arguments=arguments, ticket_id=ticket_id)
    return SkillResult(finish=True, code="non_retryable", answer="未知或不匹配的 Skill。")


__all__ = [
    "SKILLS",
    "SkillResult",
    "SkillSpec",
    "apply_skill",
    "match_skill",
]
