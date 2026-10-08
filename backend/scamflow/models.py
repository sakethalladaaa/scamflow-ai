"""SQLAlchemy persistence models for Phase 2 case management."""

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class OwnerSession(Base):
    """Anonymous owner session identified externally only by an opaque token."""

    __tablename__ = "owner_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    cases: Mapped[list["Case"]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Case(Base):
    """A consented, owner-scoped evidence case."""

    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("owner_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    consent_version: Mapped[str] = mapped_column(String(32), nullable=False)
    consented_at: Mapped[int] = mapped_column(Integer, nullable=False)

    stated_purpose: Mapped[str] = mapped_column(Text, nullable=False)
    # Canonical Decimal text avoids imprecise SQLite floating-point storage.
    amount_decimal: Mapped[str | None] = mapped_column(Text, nullable=True)
    recipient_reference: Mapped[str | None] = mapped_column(Text, nullable=True)

    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    owner: Mapped[OwnerSession] = relationship(back_populates="cases")
    events: Mapped[list["Event"]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    assessments: Mapped[list["Assessment"]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    alert_memory: Mapped["AlertMemory | None"] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )


class Event(Base):
    """Original evidence event stored exactly as submitted."""

    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("case_id", "client_event_id", name="uq_events_case_client_event_id"),
        UniqueConstraint("case_id", "source_order", name="uq_events_case_source_order"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_order: Mapped[int] = mapped_column(Integer, nullable=False)
    ingested_at: Mapped[int] = mapped_column(Integer, nullable=False)

    case: Mapped[Case] = relationship(back_populates="events")


class IdempotencyRecord(Base):
    """Owner-scoped mutation result metadata and deletion tombstone."""

    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "operation_scope",
            "request_key",
            name="uq_idempotency_owner_scope_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("owner_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    operation_scope: Mapped[str] = mapped_column(String(96), nullable=False)
    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    target_case_id: Mapped[str | None] = mapped_column(
        ForeignKey("cases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    result_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    resource_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)


class Assessment(Base):
    """One persisted assessment of a fixed case revision."""

    __tablename__ = "assessments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("owner_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assessed_revision: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    state: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_codes_json: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    used_tactics_json: Mapped[str] = mapped_column(Text, nullable=False)
    relationships_json: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_next_action: Mapped[str] = mapped_column(Text, nullable=False)
    limitations_json: Mapped[str] = mapped_column(Text, nullable=False)

    extraction_mode: Mapped[str] = mapped_column(String(64), nullable=False)
    extraction_version: Mapped[str] = mapped_column(String(96), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(96), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(96), nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)

    case: Mapped[Case] = relationship(back_populates="assessments")
    evidence: Mapped[list["AssessmentEvidence"]] = relationship(
        back_populates="assessment",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    alert: Mapped["AssessmentAlert | None"] = relationship(
        back_populates="assessment",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )


class AssessmentEvidence(Base):
    """Validated evidence span used by one persisted assessment."""

    __tablename__ = "assessment_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assessment_id: Mapped[str] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_order: Mapped[int] = mapped_column(Integer, nullable=False)
    tactic: Mapped[str] = mapped_column(String(64), nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    context: Mapped[str] = mapped_column(String(32), nullable=False)

    assessment: Mapped[Assessment] = relationship(back_populates="evidence")


class AssessmentIdempotencyRecord(Base):
    """Assessment retry metadata with deletion-safe tombstone behavior."""

    __tablename__ = "assessment_idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "operation_scope",
            "request_key",
            name="uq_assessment_idempotency_owner_scope_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("owner_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    operation_scope: Mapped[str] = mapped_column(String(96), nullable=False)
    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    target_case_id: Mapped[str | None] = mapped_column(
        ForeignKey("cases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    assessment_id: Mapped[str | None] = mapped_column(
        ForeignKey("assessments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    assessed_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    resource_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)


class AlertMemory(Base):
    """Latest material warning retained for one owned case."""

    __tablename__ = "alert_memories"

    case_id: Mapped[str] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), primary_key=True
    )
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("owner_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    warning_state: Mapped[str] = mapped_column(String(64), nullable=False)
    material_signature: Mapped[str] = mapped_column(String(64), nullable=False)
    source_assessment_id: Mapped[str] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False
    )
    source_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)

    case: Mapped[Case] = relationship(back_populates="alert_memory")


class AssessmentAlert(Base):
    """Stable alert-policy result attached to a persisted assessment."""

    __tablename__ = "assessment_alerts"

    assessment_id: Mapped[str] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), primary_key=True
    )
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str] = mapped_column(String(96), nullable=False)
    prior_warning_state: Mapped[str | None] = mapped_column(String(64), nullable=True)

    assessment: Mapped[Assessment] = relationship(back_populates="alert")
