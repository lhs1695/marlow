"""Shared FastAPI dependencies. Avoid importing app from page modules."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session, sessionmaker

from marlow.web.auth import SESSION_ACTOR_KEY
from marlow.web.limits import MemoryRateLimiter


def get_db(request: Request) -> Iterator[Session]:
    factory: sessionmaker[Session] = request.app.state.session_factory
    db = factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


Db = Annotated[Session, Depends(get_db)]


def rate_key(request: Request, suffix: str) -> str:
    actor = request.session.get(SESSION_ACTOR_KEY)
    if not actor:
        actor = request.client.host if request.client else "anon"
    return f"{actor}:{suffix}"


def enforce_limit(request: Request, suffix: str) -> None:
    limiter_obj: MemoryRateLimiter = request.app.state.limiter
    if not limiter_obj.allow(rate_key(request, suffix)):
        raise HTTPException(status_code=429, detail="rate_limited")
