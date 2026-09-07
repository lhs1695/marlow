"""Demo login. Role is always loaded from employees; never from query or spoofed headers."""

from __future__ import annotations

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from marlow.models import Employee
from marlow.seed import ADMIN_ID, L1_ID

SESSION_ACTOR_KEY = "actor_id"

DEMO_ACCOUNTS: dict[str, dict[str, str]] = {
    "l1": {"password": "l1-demo", "actor_id": L1_ID},
    "admin": {"password": "admin-demo", "actor_id": ADMIN_ID},
}


def login_actor_id(account: str, password: str) -> str:
    row = DEMO_ACCOUNTS.get(account.strip().lower())
    if row is None or row["password"] != password:
        raise HTTPException(status_code=401, detail="unauthorized")
    return row["actor_id"]


def actor_from_session(request: Request, db: Session) -> Employee:
    actor_id = request.session.get(SESSION_ACTOR_KEY)
    if not actor_id:
        raise HTTPException(status_code=401, detail="unauthorized")
    employee = db.get(Employee, actor_id)
    if employee is None:
        raise HTTPException(status_code=401, detail="unauthorized")
    return employee
