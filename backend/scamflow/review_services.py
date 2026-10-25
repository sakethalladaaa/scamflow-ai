"""Persisted owner review requests and token-gated reviewer operations."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .api_schemas import CreateReviewRequestRequest, ResolveReviewRequestRequest
from .database import Database
from .models import (
    Assessment,
    AssessmentAlert,
    AssessmentEvidence,
    Case,
    Event,
    ReviewRequest,
    ReviewRequestIdempotencyRecord,
)
from .schemas import AssessmentState
from .services import ServiceError


@dataclass(frozen=True)
class ReviewRequestMutation:
    request: ReviewRequest
    idempotent_replay: bool
    existing_open_request: bool


@dataclass(frozen=True)
class ReviewerDetail:
    request: ReviewRequest
    case: Case
    assessment: Assessment
    alert: AssessmentAlert | None
    evidence_and_sources: tuple[tuple[AssessmentEvidence, Event], ...]


def _new_public_id() -> str:
    return uuid.uuid4().hex


def _fingerprint(
    model: CreateReviewRequestRequest | ResolveReviewRequestRequest,
    *,
    resource_id: str,
) -> str:
    payload = model.model_dump(mode="json")
    payload["resource_id"] = resource_id
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _owned_live_case(
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


def _idempotency_replay(
    session: Session,
    *,
    owner_id: str,
    operation_scope: str,
    request_key: str,
    fingerprint: str,
) -> ReviewRequestMutation | None:
    record = session.scalar(
        select(ReviewRequestIdempotencyRecord).where(
            ReviewRequestIdempotencyRecord.owner_id == owner_id,
            ReviewRequestIdempotencyRecord.operation_scope == operation_scope,
            ReviewRequestIdempotencyRecord.request_key == request_key,
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
    if record.review_request_id is None:
        raise ServiceError(
            409, "idempotency_result_unavailable", "The stored result is unavailable."
        )
    review_request = session.get(ReviewRequest, record.review_request_id)
    if review_request is None:
        raise ServiceError(
            409, "idempotency_result_unavailable", "The stored result is unavailable."
        )
    return ReviewRequestMutation(
        request=review_request,
        idempotent_replay=True,
        existing_open_request=record.result_status_code == 200,
    )


def _record_idempotency(
    session: Session,
    *,
    owner_id: str,
    case_id: str,
    review_request_id: str,
    operation_scope: str,
    request_key: str,
    fingerprint: str,
    result_status_code: int,
    now: int,
) -> None:
    session.add(
        ReviewRequestIdempotencyRecord(
            owner_id=owner_id,
            operation_scope=operation_scope,
            request_key=request_key,
            request_fingerprint=fingerprint,
            target_case_id=case_id,
            review_request_id=review_request_id,
            result_status_code=result_status_code,
            resource_deleted=False,
            created_at=now,
        )
    )


def create_review_request(
    database: Database,
    *,
    owner_id: str,
    case_id: str,
    request_key: str,
    request: CreateReviewRequestRequest,
    now: int,
) -> ReviewRequestMutation:
    """Create or return the one open request for an exact uncertain assessment."""

    fingerprint = _fingerprint(request, resource_id=case_id)
    operation_scope = "create_review_request"

    try:
        with database.session_factory.begin() as session:
            # The no-op conditional update obtains SQLite's write lock before
            # checking revision and inserting the request, preventing an append
            # from racing the review snapshot.
            locked = session.execute(
                update(Case)
                .where(
                    Case.id == case_id,
                    Case.owner_id == owner_id,
                    Case.revision == request.expected_revision,
                    Case.expires_at > now,
                )
                .values(updated_at=Case.updated_at)
            )
            if locked.rowcount != 1:
                replay = _idempotency_replay(
                    session,
                    owner_id=owner_id,
                    operation_scope=operation_scope,
                    request_key=request_key,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    return replay
                case = session.scalar(
                    select(Case).where(
                        Case.id == case_id,
                        Case.owner_id == owner_id,
                        Case.expires_at > now,
                    )
                )
                if case is None:
                    raise ServiceError(404, "case_not_found", "Case not found.")
                raise ServiceError(
                    409,
                    "revision_conflict",
                    "The case revision does not match expected_revision.",
                )

            replay = _idempotency_replay(
                session,
                owner_id=owner_id,
                operation_scope=operation_scope,
                request_key=request_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return replay

            case = _owned_live_case(
                session,
                owner_id=owner_id,
                case_id=case_id,
                now=now,
            )
            assessment = session.scalar(
                select(Assessment).where(
                    Assessment.id == request.assessment_id,
                    Assessment.case_id == case_id,
                    Assessment.owner_id == owner_id,
                )
            )
            if assessment is None:
                raise ServiceError(404, "assessment_not_found", "Assessment not found.")
            if (
                case.revision != request.expected_revision
                or assessment.assessed_revision != request.expected_revision
            ):
                raise ServiceError(
                    409,
                    "assessment_not_current",
                    "Review can only be requested for an assessment of the current case revision.",
                )
            if assessment.state not in {
                AssessmentState.NEEDS_CLARIFICATION_OR_REVIEW.value,
                AssessmentState.UNABLE_TO_ASSESS.value,
            }:
                raise ServiceError(
                    409,
                    "review_not_available",
                    "Review requests are available only for uncertain or incomplete assessments.",
                )

            existing = session.scalar(
                select(ReviewRequest).where(
                    ReviewRequest.case_id == case_id,
                    ReviewRequest.assessed_revision == request.expected_revision,
                    ReviewRequest.status == "open",
                )
            )
            if existing is not None:
                result_status_code = 200
                review_request = existing
                duplicate = True
            else:
                result_status_code = 201
                review_request = ReviewRequest(
                    id=_new_public_id(),
                    case_id=case_id,
                    owner_id=owner_id,
                    assessment_id=assessment.id,
                    assessed_revision=assessment.assessed_revision,
                    status="open",
                    submitted_at=now,
                    resolved_at=None,
                    outcome=None,
                    reviewer_note=None,
                )
                session.add(review_request)
                duplicate = False

            _record_idempotency(
                session,
                owner_id=owner_id,
                case_id=case_id,
                review_request_id=review_request.id,
                operation_scope=operation_scope,
                request_key=request_key,
                fingerprint=fingerprint,
                result_status_code=result_status_code,
                now=now,
            )
            return ReviewRequestMutation(
                request=review_request,
                idempotent_replay=False,
                existing_open_request=duplicate,
            )
    except IntegrityError as exc:
        # A concurrent request can win the partial unique open-request index.
        # Re-read its result and persist this retry key against the winner.
        with database.session_factory.begin() as session:
            replay = _idempotency_replay(
                session,
                owner_id=owner_id,
                operation_scope=operation_scope,
                request_key=request_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return replay
            _owned_live_case(session, owner_id=owner_id, case_id=case_id, now=now)
            existing = session.scalar(
                select(ReviewRequest).where(
                    ReviewRequest.case_id == case_id,
                    ReviewRequest.assessed_revision == request.expected_revision,
                    ReviewRequest.status == "open",
                )
            )
            if existing is None:
                raise ServiceError(
                    409, "write_conflict", "The review request could not be created."
                ) from exc
            _record_idempotency(
                session,
                owner_id=owner_id,
                case_id=case_id,
                review_request_id=existing.id,
                operation_scope=operation_scope,
                request_key=request_key,
                fingerprint=fingerprint,
                result_status_code=200,
                now=now,
            )
            return ReviewRequestMutation(
                request=existing,
                idempotent_replay=False,
                existing_open_request=True,
            )


def get_owner_review_request(
    database: Database,
    *,
    owner_id: str,
    case_id: str,
    review_request_id: str,
    now: int,
) -> ReviewRequest:
    """Return only the lifecycle status of one request owned by this session."""

    with database.session_factory() as session:
        request = session.scalar(
            select(ReviewRequest)
            .join(Case, Case.id == ReviewRequest.case_id)
            .where(
                ReviewRequest.id == review_request_id,
                ReviewRequest.case_id == case_id,
                ReviewRequest.owner_id == owner_id,
                Case.owner_id == owner_id,
                Case.expires_at > now,
            )
        )
        if request is None:
            raise ServiceError(404, "review_request_not_found", "Review request not found.")
        session.expunge(request)
        return request


def list_open_review_requests(
    database: Database,
    *,
    now: int,
    limit: int,
    offset: int,
) -> tuple[list[tuple[ReviewRequest, Assessment, int]], int]:
    """Return oldest live open requests and their persisted assessment states."""

    with database.session_factory() as session:
        filters = (
            ReviewRequest.status == "open",
            Case.expires_at > now,
        )
        total = session.scalar(
            select(func.count(ReviewRequest.id))
            .join(Case, Case.id == ReviewRequest.case_id)
            .where(*filters)
        ) or 0
        rows = session.execute(
            select(ReviewRequest, Assessment, Case.revision)
            .join(Case, Case.id == ReviewRequest.case_id)
            .join(Assessment, Assessment.id == ReviewRequest.assessment_id)
            .where(*filters)
            .order_by(ReviewRequest.submitted_at.asc(), ReviewRequest.id.asc())
            .limit(limit)
            .offset(offset)
        ).all()
        results = [(row[0], row[1], row[2]) for row in rows]
        for request, assessment, _case_revision in results:
            session.expunge(request)
            session.expunge(assessment)
        return results, int(total)


def get_reviewer_review_detail(
    database: Database,
    *,
    review_request_id: str,
    now: int,
) -> ReviewerDetail:
    """Load an actual stored assessment and verify every evidence/source pairing."""

    with database.session_factory() as session:
        result = session.execute(
            select(ReviewRequest, Case, Assessment)
            .join(Case, Case.id == ReviewRequest.case_id)
            .join(Assessment, Assessment.id == ReviewRequest.assessment_id)
            .where(
                ReviewRequest.id == review_request_id,
                Case.expires_at > now,
            )
        ).first()
        if result is None:
            raise ServiceError(404, "review_request_not_found", "Review request not found.")

        review_request, case, assessment = result
        evidence_rows = list(
            session.scalars(
                select(AssessmentEvidence)
                .where(AssessmentEvidence.assessment_id == assessment.id)
                .order_by(
                    AssessmentEvidence.source_order.asc(),
                    AssessmentEvidence.start_offset.asc(),
                    AssessmentEvidence.id.asc(),
                )
            )
        )
        event_ids = {item.event_id for item in evidence_rows}
        source_events = list(
            session.scalars(
                select(Event).where(
                    Event.case_id == case.id,
                    Event.client_event_id.in_(event_ids),
                )
            )
        ) if event_ids else []
        events_by_id = {event.client_event_id: event for event in source_events}
        evidence_and_sources: list[tuple[AssessmentEvidence, Event]] = []
        for evidence in evidence_rows:
            event = events_by_id.get(evidence.event_id)
            if (
                event is None
                or event.source_order != evidence.source_order
                or evidence.start_offset < 0
                or evidence.end_offset <= evidence.start_offset
                or evidence.end_offset > len(event.original_text)
                or event.original_text[
                    evidence.start_offset : evidence.end_offset
                ] != evidence.quote
            ):
                raise ServiceError(
                    503,
                    "review_evidence_unavailable",
                    "Persisted assessment evidence could not be verified against its source.",
                )
            evidence_and_sources.append((evidence, event))

        alert = session.get(AssessmentAlert, assessment.id)
        session.expunge(review_request)
        session.expunge(case)
        session.expunge(assessment)
        if alert is not None:
            session.expunge(alert)
        for evidence, event in evidence_and_sources:
            session.expunge(evidence)
            session.expunge(event)
        return ReviewerDetail(
            request=review_request,
            case=case,
            assessment=assessment,
            alert=alert,
            evidence_and_sources=tuple(evidence_and_sources),
        )


def resolve_review_request(
    database: Database,
    *,
    review_request_id: str,
    request_key: str,
    request: ResolveReviewRequestRequest,
    now: int,
) -> ReviewRequestMutation:
    """Resolve one open request atomically and replay exact reviewer retries."""

    fingerprint = _fingerprint(request, resource_id=review_request_id)
    operation_scope = "resolve_review_request"
    try:
        with database.session_factory.begin() as session:
            updated = session.execute(
                update(ReviewRequest)
                .where(
                    ReviewRequest.id == review_request_id,
                    ReviewRequest.status == "open",
                    ReviewRequest.case_id.in_(
                        select(Case.id).where(Case.expires_at > now)
                    ),
                )
                .values(
                    status="resolved",
                    outcome=request.outcome,
                    reviewer_note=request.reviewer_note,
                    resolved_at=now,
                )
            )
            if updated.rowcount != 1:
                current = session.scalar(
                    select(ReviewRequest)
                    .join(Case, Case.id == ReviewRequest.case_id)
                    .where(
                        ReviewRequest.id == review_request_id,
                        Case.expires_at > now,
                    )
                )
                if current is None:
                    raise ServiceError(404, "review_request_not_found", "Review request not found.")
                replay = _idempotency_replay(
                    session,
                    owner_id=current.owner_id,
                    operation_scope=operation_scope,
                    request_key=request_key,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    return replay
                raise ServiceError(
                    409,
                    "review_request_already_resolved",
                    "The review request has already been resolved.",
                )
            review_request = session.get(ReviewRequest, review_request_id)
            if review_request is None:
                raise ServiceError(404, "review_request_not_found", "Review request not found.")
            replay = _idempotency_replay(
                session,
                owner_id=review_request.owner_id,
                operation_scope=operation_scope,
                request_key=request_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return replay
            _record_idempotency(
                session,
                owner_id=review_request.owner_id,
                case_id=review_request.case_id,
                review_request_id=review_request.id,
                operation_scope=operation_scope,
                request_key=request_key,
                fingerprint=fingerprint,
                result_status_code=204,
                now=now,
            )
            return ReviewRequestMutation(
                request=review_request,
                idempotent_replay=False,
                existing_open_request=False,
            )
    except IntegrityError as exc:
        with database.session_factory() as session:
            current = session.scalar(
                select(ReviewRequest)
                .join(Case, Case.id == ReviewRequest.case_id)
                .where(
                    ReviewRequest.id == review_request_id,
                    Case.expires_at > now,
                )
            )
            if current is None:
                raise ServiceError(
                    404, "review_request_not_found", "Review request not found."
                ) from exc
            replay = _idempotency_replay(
                session,
                owner_id=current.owner_id,
                operation_scope=operation_scope,
                request_key=request_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return replay
        raise ServiceError(
            409,
            "review_request_already_resolved",
            "The review request has already been resolved.",
        ) from exc
