from __future__ import annotations

from sqlalchemy.orm import Session

from marlow.codes import NON_RETRYABLE, ROLE_ADMIN, ROLE_L1, UNAUTHORIZED
from marlow.models import Asset, Employee
from marlow.observation import Observation


def get_asset(session: Session, *, actor_id: str, asset_id: str) -> Observation:
    actor = session.get(Employee, actor_id)
    if actor is None or actor.role not in (ROLE_L1, ROLE_ADMIN):
        return Observation(ok=False, code=UNAUTHORIZED, retryable=False, untrusted=True)
    asset = session.get(Asset, asset_id)
    if asset is None:
        return Observation(ok=False, code=NON_RETRYABLE, retryable=False, untrusted=True)
    return Observation(
        ok=True,
        code="ok",
        retryable=False,
        untrusted=True,
        data={
            "asset": {
                "id": asset.id,
                "name": asset.name,
                "kind": asset.kind,
                "owner_employee_id": asset.owner_employee_id,
                "config": asset.config,
            }
        },
    )
