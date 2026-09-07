"""Entitlement change Skill: draft only. Never UPDATE entitlements; HITL before gateway."""

from __future__ import annotations

from typing import Any

from marlow.codes import (
    APPROVAL_REQUIRED,
    NOT_ENOUGH_INFO,
    SKILL_ENTITLEMENT_CHANGE,
    SKILL_VERSION,
)
from marlow.skills.types import SkillResult, SkillSpec

SPEC = SkillSpec(
    name=SKILL_ENTITLEMENT_CHANGE,
    version=SKILL_VERSION,
    title="变更执行",
    skeleton="只出参数草案；执行前 HITL；不写 entitlements",
    draft_schema={
        "type": "object",
        "properties": {
            "ticket_id": {"type": "string"},
            "target_employee_id": {"type": "string"},
            "system": {"type": "string"},
            "new_permission": {"type": "string"},
            "note": {"type": "string", "description": "模型补变更说明"},
        },
        "required": ["ticket_id", "target_employee_id", "system", "new_permission"],
    },
)


def apply_change(*, arguments: dict[str, Any], ticket_id: str | None) -> SkillResult:
    draft = {
        "ticket_id": arguments.get("ticket_id") or ticket_id,
        "target_employee_id": arguments.get("target_employee_id"),
        "system": arguments.get("system"),
        "new_permission": arguments.get("new_permission"),
        "note": arguments.get("note") or "",
    }
    missing = [
        key
        for key in ("ticket_id", "target_employee_id", "system", "new_permission")
        if not draft.get(key)
    ]
    if missing:
        return SkillResult(
            finish=True,
            code=NOT_ENOUGH_INFO,
            answer="变更草案缺字段，未改权限表。",
            draft=draft,
        )
    return SkillResult(
        finish=True,
        code=APPROVAL_REQUIRED,
        answer="权限变更草案已提交，等待管理员审批。本 Run 不续跑。",
        hitl=True,
        draft=draft,
    )
