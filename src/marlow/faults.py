"""In-process fault injection for tool fixtures. Not real network chaos."""

from __future__ import annotations

from marlow.codes import NON_RETRYABLE, RETRYABLE_TIMEOUT
from marlow.observation import Observation

FAULT_TIMEOUT = "timeout"
FAULT_HTTP_200_BUSINESS_FAIL = "http_200_business_fail"


class FaultHooks:
    def __init__(self) -> None:
        self._by_tool: dict[str, str] = {}
        self._by_target: dict[tuple[str, str], str] = {}

    def set_tool(self, tool: str, kind: str) -> None:
        self._by_tool[tool] = kind

    def set_target(self, tool: str, target_id: str, kind: str) -> None:
        self._by_target[(tool, target_id)] = kind

    def clear(self) -> None:
        self._by_tool.clear()
        self._by_target.clear()

    def check(self, tool: str, target_id: str | None = None) -> Observation | None:
        kind: str | None = None
        if target_id is not None:
            kind = self._by_target.get((tool, target_id))
        if kind is None:
            kind = self._by_tool.get(tool)
        if kind == FAULT_TIMEOUT:
            return Observation(
                ok=False,
                code=RETRYABLE_TIMEOUT,
                retryable=True,
                untrusted=True,
            )
        if kind == FAULT_HTTP_200_BUSINESS_FAIL:
            return Observation(
                ok=False,
                code=NON_RETRYABLE,
                retryable=False,
                untrusted=True,
                data={"http_status": 200},
            )
        return None
