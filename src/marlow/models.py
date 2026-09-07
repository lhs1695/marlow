from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    department: Mapped[str] = mapped_column(String(64), nullable=False)

    assets: Mapped[list[Asset]] = relationship(back_populates="owner")
    tickets_requested: Mapped[list[Ticket]] = relationship(
        back_populates="requester", foreign_keys="Ticket.requester_id"
    )


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), nullable=False)
    config: Mapped[str] = mapped_column(Text, nullable=False, default="")

    owner: Mapped[Employee] = relationship(back_populates="assets")
    tickets: Mapped[list[Ticket]] = relationship(back_populates="asset")


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    queue: Mapped[str] = mapped_column(String(32), nullable=False)
    requester_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), nullable=False)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    priority: Mapped[str | None] = mapped_column(String(8), nullable=True)
    kb_doc_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    kb_version: Mapped[str | None] = mapped_column(String(32), nullable=True)

    requester: Mapped[Employee] = relationship(
        back_populates="tickets_requested", foreign_keys=[requester_id]
    )
    asset: Mapped[Asset | None] = relationship(back_populates="tickets")
    comments: Mapped[list[TicketComment]] = relationship(back_populates="ticket")
    approvals: Mapped[list[Approval]] = relationship(back_populates="ticket")


class TicketComment(Base):
    __tablename__ = "ticket_comments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id"), nullable=False)
    author_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    ticket: Mapped[Ticket] = relationship(back_populates="comments")


class Entitlement(Base):
    __tablename__ = "entitlements"
    __table_args__ = (UniqueConstraint("employee_id", "system", name="uq_entitlement_employee_system"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), nullable=False)
    system: Mapped[str] = mapped_column(String(64), nullable=False)
    permission: Mapped[str] = mapped_column(String(32), nullable=False)


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id"), nullable=False)
    target_employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), nullable=False)
    system: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_permission: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    decided_by_id: Mapped[str | None] = mapped_column(ForeignKey("employees.id"), nullable=True)

    ticket: Mapped[Ticket] = relationship(back_populates="approvals")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    actor_id: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    ticket_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
