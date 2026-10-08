"""Transactional Phase 2 case-management services."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .api_schemas import AppendEventsRequest, CreateCaseRequest
from .database import Database
from .models import (
    AssessmentIdempotencyRecord,
    Case,
    Event,
    IdempotencyRecord,
    OwnerSession,
)
from .schemas import MAX_EVENTS, MAX_TOTAL_INPUT_CHARACTERS, PaymentContext
from .security import generate_session_token, hash_session_token
from .settings import Settings

CONSENT_VERSION = "v1"
Clock = Callable[[], int]


def system_clock() -> int:
    """Return current UTC epoch seconds."""

    return int(time.time())


def epoch_to_datetime(value: int) -> datetime:
    """Convert stored UTC epoch seconds to an aware datetime."""

    return datetime.fromtimestamp(value, tz=UTC)


class ServiceError(Exception):
    """Safe service-layer error that can be mapped to an API response."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SessionResult:
    """Internal result for session bootstrap."""

    token: str
    expires_at: int
    reused: bool


@dataclass(frozen=True)
class MutationResult:
    """Logical outcome of an idempotent mutation."""

    case_id: str
    result_revision: int
    idempotent_replay: bool


def _new_public_id() -> str:
    return uuid.uuid4().hex


def _fingerprint(model: CreateCaseRequest | AppendEventsRequest) -> str:
    payload = model.model_dump(mode="json")
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _content_character_count(case: Case, event_texts: list[str]) -> int:
    recipient = case.recipient_reference or ""
    return sum(len(text) for text in event_texts) + len(case.stated_purpose) + len(recipient)


def _load_owned_case(
    session: Session,
    *,
    owner_id: str,
    case_id: str,
    now: int,
) -> Case:
    case = session.scalar(
        select(Case).where(
            Case.id == case_id,
            Case.owner_id == owner_id,
            Case.expires_at > now,
        )
    )
    if case is None:
        raise ServiceError(404, "case_not_found", "Case not found.")
    return case


def authenticate_owner(
    database: Database,
    *,
    token: str | None,
    now: int,
) -> OwnerSession:
    """Resolve a valid unexpired anonymous owner session."""

    if not token:
        raise ServiceError(401, "session_required", "A valid session is required.")

    token_hash = hash_session_token(token)
    with database.session_factory() as session:
        owner = session.scalar(
            select(OwnerSession).where(
                OwnerSession.token_hash == token_hash,
                OwnerSession.expires_at > now,
            )
        )
        if owner is None:
            raise ServiceError(401, "session_invalid", "A valid session is required.")
        return owner


def bootstrap_session(
    database: Database,
    settings: Settings,
    *,
    presented_token: str | None,
    now: int,
) -> SessionResult:
    """Reuse a valid anonymous session or create an isolated replacement."""

    if presented_token:
        token_hash = hash_session_token(presented_token)
        with database.session_factory() as session:
            owner = session.scalar(
                select(OwnerSession).where(
                    OwnerSession.token_hash == token_hash,
                    OwnerSession.expires_at > now,
                )
            )
            if owner is not None:
                return SessionResult(
                    token=presented_token,
                    expires_at=owner.expires_at,
                    reused=True,
                )

    # Hash collisions are cryptographically negligible, but keep retries bounded.
    for _attempt in range(3):
        token = generate_session_token()
        owner = OwnerSession(
            id=_new_public_id(),
            token_hash=hash_session_token(token),
            created_at=now,
            expires_at=now + settings.session_ttl_seconds,
        )
        try:
            with database.session_factory.begin() as session:
                session.add(owner)
            return SessionResult(
                token=token,
                expires_at=owner.expires_at,
                reused=False,
            )
        except IntegrityError:
            continue

    raise ServiceError(503, "session_unavailable", "Unable to create a session.")


def _existing_idempotency(
    session: Session,
    *,
    owner_id: str,
    operation_scope: str,
    request_key: str,
    fingerprint: str,
) -> MutationResult | None:
    record = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.owner_id == owner_id,
            IdempotencyRecord.operation_scope == operation_scope,
            IdempotencyRecord.request_key == request_key,
        )
    )
    if record is None:
        return None

    if record.request_fingerprint != fingerprint:
        raise ServiceError(
            409,
            "idempotency_conflict",
            "The idempotency key was already used with a different request.",
        )

    if record.resource_deleted or record.target_case_id is None:
        raise ServiceError(
            409,
            "idempotency_resource_deleted",
            "The original resource was deleted and cannot be replayed.",
        )

    if record.result_revision is None:
        raise ServiceError(409, "idempotency_conflict", "Stored mutation result is unavailable.")

    return MutationResult(
        case_id=record.target_case_id,
        result_revision=record.result_revision,
        idempotent_replay=True,
    )


def create_case(
    database: Database,
    settings: Settings,
    *,
    owner_id: str,
    request_key: str,
    request: CreateCaseRequest,
    now: int,
) -> MutationResult:
    """Create one consented case and its initial events atomically."""

    fingerprint = _fingerprint(request)
    operation_scope = "create_case"

    try:
        with database.session_factory.begin() as session:
            replay = _existing_idempotency(
                session,
                owner_id=owner_id,
                operation_scope=operation_scope,
                request_key=request_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return replay

            case_id = _new_public_id()
            payment = request.payment_context

            case = Case(
                id=case_id,
                owner_id=owner_id,
                consent_version=CONSENT_VERSION,
                consented_at=now,
                stated_purpose=payment.stated_purpose,
                amount_decimal=str(payment.amount) if payment.amount is not None else None,
                recipient_reference=payment.recipient_reference,
                revision=1,
                created_at=now,
                updated_at=now,
                expires_at=now + settings.case_retention_seconds,
            )
            session.add(case)

            session.add_all(
                [
                    Event(
                        case_id=case_id,
                        client_event_id=event.event_id,
                        channel=event.channel.value,
                        original_text=event.text,
                        source_order=event.source_order,
                        ingested_at=now,
                    )
                    for event in request.events
                ]
            )

            session.add(
                IdempotencyRecord(
                    owner_id=owner_id,
                    operation_scope=operation_scope,
                    request_key=request_key,
                    request_fingerprint=fingerprint,
                    target_case_id=case_id,
                    result_revision=1,
                    result_status_code=201,
                    resource_deleted=False,
                    created_at=now,
                )
            )

        return MutationResult(case_id=case_id, result_revision=1, idempotent_replay=False)
    except IntegrityError as exc:
        # A concurrent same-key create may have won the unique constraint.
        with database.session_factory() as session:
            replay = _existing_idempotency(
                session,
                owner_id=owner_id,
                operation_scope=operation_scope,
                request_key=request_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return replay
        raise ServiceError(409, "write_conflict", "The case could not be created.") from exc


def get_case(
    database: Database,
    *,
    owner_id: str,
    case_id: str,
    now: int,
) -> tuple[Case, list[Event]]:
    """Return an owned, unexpired case and explicitly ordered events."""

    with database.session_factory() as session:
        case = _load_owned_case(session, owner_id=owner_id, case_id=case_id, now=now)
        events = list(
            session.scalars(
                select(Event)
                .where(Event.case_id == case.id)
                .order_by(Event.source_order.asc(), Event.id.asc())
            )
        )
        session.expunge(case)
        for event in events:
            session.expunge(event)
        return case, events


def append_events(
    database: Database,
    *,
    owner_id: str,
    case_id: str,
    request_key: str,
    request: AppendEventsRequest,
    now: int,
) -> MutationResult:
    """Append evidence with revision, limit, and idempotency enforcement."""

    fingerprint = _fingerprint(request)
    operation_scope = f"append_events:{case_id}"

    def replay_after_race() -> MutationResult | None:
        # A competing SQLite writer can update the revision just before its
        # idempotency row becomes visible. Brief bounded retries close that
        # commit-visibility window without rerunning the mutation.
        for delay in (0.0, 0.005, 0.01, 0.02, 0.04):
            if delay:
                time.sleep(delay)
            with database.session_factory() as retry_session:
                replay_result = _existing_idempotency(
                    retry_session,
                    owner_id=owner_id,
                    operation_scope=operation_scope,
                    request_key=request_key,
                    fingerprint=fingerprint,
                )
                if replay_result is not None:
                    return replay_result
        return None

    try:
        with database.session_factory.begin() as session:
            # Exact retry must be recognized before the old expected revision
            # is compared with the case's now-current revision.
            replay = _existing_idempotency(
                session,
                owner_id=owner_id,
                operation_scope=operation_scope,
                request_key=request_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return replay

            case = _load_owned_case(session, owner_id=owner_id, case_id=case_id, now=now)

            if case.revision != request.expected_revision:
                raise ServiceError(
                    409,
                    "revision_conflict",
                    "The case revision does not match expected_revision.",
                )

            stored_events = list(session.scalars(select(Event).where(Event.case_id == case_id)))
            stored_ids = {event.client_event_id for event in stored_events}
            stored_orders = {event.source_order for event in stored_events}

            if any(event.event_id in stored_ids for event in request.events):
                raise ServiceError(
                    409,
                    "event_id_conflict",
                    "An event identifier already exists in this case.",
                )

            if any(event.source_order in stored_orders for event in request.events):
                raise ServiceError(
                    409,
                    "source_order_conflict",
                    "A source_order already exists in this case.",
                )

            resulting_count = len(stored_events) + len(request.events)
            if resulting_count > MAX_EVENTS:
                raise ServiceError(
                    422,
                    "event_limit_exceeded",
                    f"A case may contain at most {MAX_EVENTS} events.",
                )

            all_texts = [event.original_text for event in stored_events]
            all_texts.extend(event.text for event in request.events)
            if _content_character_count(case, all_texts) > MAX_TOTAL_INPUT_CHARACTERS:
                raise ServiceError(
                    422,
                    "content_limit_exceeded",
                    f"Case content may not exceed {MAX_TOTAL_INPUT_CHARACTERS} characters.",
                )

            new_revision = case.revision + 1
            result = session.execute(
                update(Case)
                .where(
                    Case.id == case_id,
                    Case.owner_id == owner_id,
                    Case.revision == request.expected_revision,
                    Case.expires_at > now,
                )
                .values(revision=new_revision, updated_at=now)
            )
            if result.rowcount != 1:
                raise ServiceError(
                    409,
                    "revision_conflict",
                    "The case revision changed before the append completed.",
                )

            session.add_all(
                [
                    Event(
                        case_id=case_id,
                        client_event_id=event.event_id,
                        channel=event.channel.value,
                        original_text=event.text,
                        source_order=event.source_order,
                        ingested_at=now,
                    )
                    for event in request.events
                ]
            )
            session.add(
                IdempotencyRecord(
                    owner_id=owner_id,
                    operation_scope=operation_scope,
                    request_key=request_key,
                    request_fingerprint=fingerprint,
                    target_case_id=case_id,
                    result_revision=new_revision,
                    result_status_code=200,
                    resource_deleted=False,
                    created_at=now,
                )
            )

        return MutationResult(
            case_id=case_id,
            result_revision=new_revision,
            idempotent_replay=False,
        )
    except ServiceError as exc:
        if exc.code in {"revision_conflict", "event_id_conflict", "source_order_conflict"}:
            # A concurrent same-key request may have committed after this
            # transaction's initial idempotency lookup. Depending on SQLite's
            # statement snapshots, the loser can first observe the revision,
            # event-id, or source-order effect. Re-check the exact key/payload
            # before surfacing that conflict.
            replay = replay_after_race()
            if replay is not None:
                return replay
        raise
    except IntegrityError as exc:
        # Handles a concurrent same-key retry or a database uniqueness race.
        replay = replay_after_race()
        if replay is not None:
            return replay
        raise ServiceError(409, "write_conflict", "The append could not be completed.") from exc


def delete_case(
    database: Database,
    *,
    owner_id: str,
    case_id: str,
    now: int,
) -> None:
    """Hard-delete an owned case while retaining only safe idempotency tombstones."""

    with database.session_factory.begin() as session:
        case = _load_owned_case(session, owner_id=owner_id, case_id=case_id, now=now)

        session.execute(
            update(IdempotencyRecord)
            .where(
                IdempotencyRecord.owner_id == owner_id,
                IdempotencyRecord.target_case_id == case.id,
            )
            .values(
                target_case_id=None,
                resource_deleted=True,
            )
        )
        session.execute(
            update(AssessmentIdempotencyRecord)
            .where(
                AssessmentIdempotencyRecord.owner_id == owner_id,
                AssessmentIdempotencyRecord.target_case_id == case.id,
            )
            .values(
                target_case_id=None,
                assessment_id=None,
                resource_deleted=True,
            )
        )
        session.delete(case)


def payment_context_from_case(case: Case) -> PaymentContext:
    """Reconstruct the validated public payment context."""

    return PaymentContext(
        stated_purpose=case.stated_purpose,
        amount=case.amount_decimal,
        recipient_reference=case.recipient_reference,
    )
