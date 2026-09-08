"""Unified tool Observation. Bodies and KB slices are always untrusted."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Observation:
    ok: bool
    code: str
    retryable: bool
    untrusted: bool
    data: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.untrusted:
            object.__setattr__(self, "untrusted", True)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "code": self.code,
            "retryable": self.retryable,
            "untrusted": self.untrusted,
            "data": self.data,
        }
