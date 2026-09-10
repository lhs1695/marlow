"""Unified tool Observation. External data is untrusted_web_content; gateway results are internal_gateway."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from marlow.codes import SOURCE_TRUST_INTERNAL_GATEWAY, SOURCE_TRUST_UNTRUSTED_WEB_CONTENT


@dataclass(frozen=True)
class Observation:
    ok: bool
    code: str
    retryable: bool
    source_trust: str = SOURCE_TRUST_UNTRUSTED_WEB_CONTENT
    data: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.source_trust != SOURCE_TRUST_INTERNAL_GATEWAY:
            object.__setattr__(self, "source_trust", SOURCE_TRUST_UNTRUSTED_WEB_CONTENT)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "code": self.code,
            "retryable": self.retryable,
            "source_trust": self.source_trust,
            "data": self.data,
        }
