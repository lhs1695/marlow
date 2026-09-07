"""Procedure QA: only authorized handbook. Model rewrites the query; refuse if KB miss."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from marlow.actions import Action
from marlow.codes import KB_MISS, NOT_ENOUGH_INFO, SKILL_KB_QA, SKILL_VERSION
from marlow.observation import Observation
from marlow.skills.types import SkillResult, SkillSpec
from marlow.tools import TOOL_SEARCH_KB

SPEC = SkillSpec(
    name=SKILL_KB_QA,
    version=SKILL_VERSION,
    title="规程问答",
    skeleton="只检索授权手册；不足则拒答",
    draft_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "模型改写后的问法"},
        },
        "required": ["query"],
    },
)

RunTool = Callable[[Action], Observation]


def apply_kb_qa(*, run_tool: RunTool, arguments: dict[str, Any]) -> SkillResult:
    query = str(arguments.get("query") or "").strip()
    if not query:
        return SkillResult(finish=True, code=NOT_ENOUGH_INFO, answer="规程问答缺问法，未编造规程。")

    obs = run_tool(Action(kind="tool", name=TOOL_SEARCH_KB, arguments={"query": query}))
    if not obs.ok:
        return SkillResult(
            finish=True,
            code=obs.code or KB_MISS,
            answer="手册无命中，拒答，未编造规程。",
            draft={"query": query},
        )
    hits = (obs.data or {}).get("hits") or []
    if not hits:
        return SkillResult(
            finish=True,
            code=KB_MISS,
            answer="手册无命中，拒答，未编造规程。",
            draft={"query": query},
        )
    hit = hits[0]
    doc_id = hit.get("doc_id")
    version = hit.get("version")
    return SkillResult(
        finish=True,
        code="ok",
        answer=f"按授权手册作答。kb={doc_id}@{version}",
        draft={"query": query},
        verified_updates={"kb_doc_id": doc_id, "kb_version": version},
    )
