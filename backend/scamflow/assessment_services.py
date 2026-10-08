"""Phase 3 assessment orchestration and persistence services."""

from __future__ import annotations

import hashlib
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .api_schemas import AssessCaseRequest
from .database import Database
from .detection import (
    DIGITAL_ARREST_RULE_VERSION,
    EXTRACTION_SCHEMA_VERSION,
    MOCK_EXTRACTION_MODE,
    CaseSnapshot,
    ExtractionValidationError,
    Extractor,
    PolicyDecision,
    SnapshotEvent,
    ValidatedObservation,
    decide_digital_arrest,
    validate_extraction,
)
from .models import (
    AlertMemory,
    Assessment,
    AssessmentAlert,
    AssessmentEvidence,
    AssessmentIdempotencyRecord,
    Case,
    Event,
    OwnerSession,
)
from .services import Clock, ServiceError
from .settings import Settings


@dataclass(frozen=True)
class AssessmentEvidenceView:
    """Public-safe persisted evidence reference."""

    tactic: str
    event_id: str
    source_order: int
    quote: str
    start_offset: int
    end_offset: int
    context: str


@dataclass(frozen=True)
class AlertView:
    """Persisted alert-display result for an assessment."""

    visible: bool
    reason: str
    prior_warning_state: str | None


@dataclass(frozen=True)
class AssessmentResult:
    """Public-safe persisted assessment result."""

    assessment_id: str
    case_id: str
    assessed_revision: int
    state: str
    reason_codes: tuple[str, ...]
    explanation: str
    evidence: tuple[AssessmentEvidenceView, ...]
    alert: AlertView
    tactics_used: tuple[str, ...]
    relationships: tuple[str, ...]
    suggested_next_action: str
    limitations: tuple[str, ...]
    extraction_mode: str
    extraction_version: str
    rule_version: str
    schema_version: str
    created_at: int
    is_current: bool
    idempotent_replay: bool


def _new_public_id() -> str:
    return uuid.uuid4().hex


def _fingerprint(request: AssessCaseRequest) -> str:
    payload = request.model_dump(mode="json")
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _require_live_owner(session: Session, *, owner_id: str, now: int) -> OwnerSession:
    owner = session.scalar(
        select(OwnerSession).where(
            OwnerSession.id == owner_id,
            OwnerSession.expires_at > now,
        )
    )
    if owner is None:
        raise ServiceError(401, "session_invalid", "A valid session is required.")
    return owner


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


def _assessment_result_from_row(
    session: Session,
    *,
    assessment: Assessment,
    current_revision: int,
    idempotent_replay: bool,
) -> AssessmentResult:
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
    alert_row = session.get(AssessmentAlert, assessment.id)

    return AssessmentResult(
        assessment_id=assessment.id,
        case_id=assessment.case_id,
        assessed_revision=assessment.assessed_revision,
        state=assessment.state,
        reason_codes=tuple(json.loads(assessment.reason_codes_json)),
        explanation=assessment.explanation,
        evidence=tuple(
            AssessmentEvidenceView(
                tactic=row.tactic,
                event_id=row.event_id,
                source_order=row.source_order,
                quote=row.quote,
                start_offset=row.start_offset,
                end_offset=row.end_offset,
                context=row.context,
            )
            for row in evidence_rows
        ),
        alert=AlertView(
            visible=alert_row.visible if alert_row is not None else False,
            reason=alert_row.reason if alert_row is not None else "legacy_assessment",
            prior_warning_state=(
                alert_row.prior_warning_state if alert_row is not None else None
            ),
        ),
        tactics_used=tuple(json.loads(assessment.used_tactics_json)),
        relationships=tuple(json.loads(assessment.relationships_json)),
        suggested_next_action=assessment.suggested_next_action,
        limitations=tuple(json.loads(assessment.limitations_json)),
        extraction_mode=assessment.extraction_mode,
        extraction_version=assessment.extraction_version,
        rule_version=assessment.rule_version,
        schema_version=assessment.schema_version,
        created_at=assessment.created_at,
        is_current=assessment.assessed_revision == current_revision,
        idempotent_replay=idempotent_replay,
    )


def _existing_idempotency(
    session: Session,
    *,
    owner_id: str,
    case: Case,
    request_key: str,
    fingerprint: str,
) -> AssessmentResult | None:
    operation_scope = f"assess_case:{case.id}"
    record = session.scalar(
        select(AssessmentIdempotencyRecord).where(
            AssessmentIdempotencyRecord.owner_id == owner_id,
            AssessmentIdempotencyRecord.operation_scope == operation_scope,
            AssessmentIdempotencyRecord.request_key == request_key,
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

    if record.resource_deleted or record.target_case_id is None or record.assessment_id is None:
        raise ServiceError(
            409,
            "idempotency_resource_deleted",
            "The original assessment resource was deleted and cannot be replayed.",
        )

    assessment = session.scalar(
        select(Assessment).where(
            Assessment.id == record.assessment_id,
            Assessment.case_id == case.id,
            Assessment.owner_id == owner_id,
        )
    )
    if assessment is None:
        raise ServiceError(
            409,
            "idempotency_conflict",
            "Stored assessment result is unavailable.",
        )

    return _assessment_result_from_row(
        session,
        assessment=assessment,
        current_revision=case.revision,
        idempotent_replay=True,
    )


def _failure_decision(
    *,
    reason_code: str,
    explanation: str,
    extraction_mode: str,
) -> PolicyDecision:
    limitations = [
        "The assessment did not complete successfully; unable_to_assess is not a low-risk result.",
        "No result authenticates a sender or conclusively proves criminal activity.",
    ]
    if extraction_mode == MOCK_EXTRACTION_MODE:
        limitations.insert(
            0,
            "This assessment uses a narrow development mock extractor, not production AI.",
        )

    return PolicyDecision(
        state="unable_to_assess",
        reason_codes=(reason_code,),
        explanation=explanation,
        used_tactics=(),
        relationships=(),
        suggested_next_action=(
            "Do not rely on this result as reassurance; review the interaction manually "
            "or make a fresh assessment attempt with a new idempotency key."
        ),
        limitations=tuple(limitations),
    )


def _material_signature(decision: PolicyDecision) -> str:
    payload = json.dumps(
        {
            "state": decision.state,
            "reason_codes": sorted(decision.reason_codes),
            "tactics": sorted(decision.used_tactics),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _apply_alert_policy(
    session: Session,
    *,
    case: Case,
    owner_id: str,
    assessment_id: str,
    assessed_revision: int,
    decision: PolicyDecision,
    now: int,
) -> AlertView:
    """Persist suppression/escalation state in the same assessment transaction."""

    memory = session.get(AlertMemory, case.id)
    prior_state = memory.warning_state if memory is not None else None
    warning_states = {"needs_clarification_or_review", "high_risk_indicators"}

    if decision.state == "unable_to_assess":
        alert = AlertView(
            visible=True,
            reason=(
                "extraction_failure_prior_warning_preserved"
                if memory is not None
                else "assessment_failure"
            ),
            prior_warning_state=prior_state,
        )
    elif decision.state not in warning_states:
        alert = AlertView(
            visible=False,
            reason="no_new_material_warning",
            prior_warning_state=prior_state,
        )
    else:
        signature = _material_signature(decision)
        if memory is None:
            alert = AlertView(True, "initial_material_warning", None)
        elif memory.material_signature == signature:
            alert = AlertView(False, "unchanged_warning_suppressed", prior_state)
        elif (
            memory.warning_state == "needs_clarification_or_review"
            and decision.state == "high_risk_indicators"
        ):
            alert = AlertView(True, "material_risk_escalation", prior_state)
        else:
            alert = AlertView(True, "material_warning_changed", prior_state)

        if memory is None:
            session.add(
                AlertMemory(
                    case_id=case.id,
                    owner_id=owner_id,
                    warning_state=decision.state,
                    material_signature=signature,
                    source_assessment_id=assessment_id,
                    source_revision=assessed_revision,
                    updated_at=now,
                )
            )
        else:
            memory.warning_state = decision.state
            memory.material_signature = signature
            memory.source_assessment_id = assessment_id
            memory.source_revision = assessed_revision
            memory.updated_at = now

    session.add(
        AssessmentAlert(
            assessment_id=assessment_id,
            visible=alert.visible,
            reason=alert.reason,
            prior_warning_state=alert.prior_warning_state,
        )
    )
    return alert


def _run_extractor(
    *,
    extractor: Extractor,
    snapshot: CaseSnapshot,
    timeout_seconds: float,
) -> tuple[object | None, str | None]:
    """Run extraction with a bounded caller wait and no database transaction held."""

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="scamflow-extraction")
    future = executor.submit(extractor.extract, snapshot)
    try:
        return future.result(timeout=timeout_seconds), None
    except FutureTimeoutError:
        future.cancel()
        return None, "extraction_timeout"
    except Exception:
        return None, "extraction_failed"
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _snapshot_for_assessment(
    database: Database,
    *,
    owner_id: str,
    case_id: str,
    request_key: str,
    request: AssessCaseRequest,
    now: int,
) -> tuple[CaseSnapshot | None, AssessmentResult | None]:
    fingerprint = _fingerprint(request)

    with database.session_factory() as session:
        _require_live_owner(session, owner_id=owner_id, now=now)
        case = _load_owned_case(
            session,
            owner_id=owner_id,
            case_id=case_id,
            now=now,
        )

        replay = _existing_idempotency(
            session,
            owner_id=owner_id,
            case=case,
            request_key=request_key,
            fingerprint=fingerprint,
        )
        if replay is not None:
            return None, replay

        if case.revision != request.expected_revision:
            raise ServiceError(
                409,
                "revision_conflict",
                "The case revision does not match expected_revision.",
            )

        events = list(
            session.scalars(
                select(Event)
                .where(Event.case_id == case.id)
                .order_by(Event.source_order.asc(), Event.id.asc())
            )
        )

        snapshot = CaseSnapshot(
            case_id=case.id,
            revision=case.revision,
            events=tuple(
                SnapshotEvent(
                    event_id=event.client_event_id,
                    channel=event.channel,
                    text=event.original_text,
                    source_order=event.source_order,
                )
                for event in events
            ),
            stated_purpose=case.stated_purpose,
            amount_decimal=case.amount_decimal,
            recipient_reference=case.recipient_reference,
        )
        return snapshot, None


def assess_case(
    database: Database,
    settings: Settings,
    *,
    extractor: Extractor,
    owner_id: str,
    case_id: str,
    request_key: str,
    request: AssessCaseRequest,
    clock: Clock,
) -> AssessmentResult:
    """Assess one fixed revision without holding a write lock during extraction."""

    fingerprint = _fingerprint(request)
    operation_scope = f"assess_case:{case_id}"

    snapshot, replay = _snapshot_for_assessment(
        database,
        owner_id=owner_id,
        case_id=case_id,
        request_key=request_key,
        request=request,
        now=clock(),
    )
    if replay is not None:
        return replay

    if snapshot is None:
        raise ServiceError(503, "assessment_unavailable", "Assessment could not be started.")

    raw_output, extraction_failure = _run_extractor(
        extractor=extractor,
        snapshot=snapshot,
        timeout_seconds=settings.assessment_timeout_seconds,
    )

    observations: tuple[ValidatedObservation, ...] = ()
    if extraction_failure == "extraction_timeout":
        decision = _failure_decision(
            reason_code="extraction_timeout",
            explanation="The extractor did not finish within the configured time limit.",
            extraction_mode=extractor.mode,
        )
    elif extraction_failure == "extraction_failed":
        decision = _failure_decision(
            reason_code="extraction_failed",
            explanation="The extractor failed before a validated result was available.",
            extraction_mode=extractor.mode,
        )
    else:
        try:
            validated = validate_extraction(
                snapshot=snapshot,
                raw_output=raw_output,
                extraction_mode=extractor.mode,
                extraction_version=extractor.version,
            )
            observations = validated.observations
            decision = decide_digital_arrest(validated)
        except ExtractionValidationError:
            decision = _failure_decision(
                reason_code="invalid_extraction_evidence",
                explanation=(
                    "The extractor output failed strict schema or evidence-span validation."
                ),
                extraction_mode=extractor.mode,
            )

    assessment_id = _new_public_id()
    commit_now = clock()
    source_orders = {event.event_id: event.source_order for event in snapshot.events}

    try:
        with database.session_factory.begin() as session:
            _require_live_owner(session, owner_id=owner_id, now=commit_now)
            case = _load_owned_case(
                session,
                owner_id=owner_id,
                case_id=case_id,
                now=commit_now,
            )

            replay = _existing_idempotency(
                session,
                owner_id=owner_id,
                case=case,
                request_key=request_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return replay

            if case.revision != request.expected_revision:
                raise ServiceError(
                    409,
                    "revision_conflict",
                    "The case revision changed before the assessment could be stored.",
                )

            assessment = Assessment(
                id=assessment_id,
                case_id=case.id,
                owner_id=owner_id,
                assessed_revision=request.expected_revision,
                state=decision.state,
                reason_codes_json=json.dumps(list(decision.reason_codes), separators=(",", ":")),
                explanation=decision.explanation,
                used_tactics_json=json.dumps(list(decision.used_tactics), separators=(",", ":")),
                relationships_json=json.dumps(
                    list(decision.relationships),
                    separators=(",", ":"),
                ),
                suggested_next_action=decision.suggested_next_action,
                limitations_json=json.dumps(list(decision.limitations), separators=(",", ":")),
                extraction_mode=extractor.mode,
                extraction_version=extractor.version,
                rule_version=DIGITAL_ARREST_RULE_VERSION,
                schema_version=EXTRACTION_SCHEMA_VERSION,
                created_at=commit_now,
            )
            session.add(assessment)
            # The alert migration has explicit foreign keys to this assessment;
            # materialize the parent before adding alert-memory rows.
            session.flush()

            alert = _apply_alert_policy(
                session,
                case=case,
                owner_id=owner_id,
                assessment_id=assessment_id,
                assessed_revision=request.expected_revision,
                decision=decision,
                now=commit_now,
            )

            session.add_all(
                [
                    AssessmentEvidence(
                        assessment_id=assessment_id,
                        event_id=observation.event_id,
                        source_order=source_orders[observation.event_id],
                        tactic=observation.tactic.value,
                        quote=observation.quote,
                        start_offset=observation.start,
                        end_offset=observation.end,
                        context=observation.context.value,
                    )
                    for observation in observations
                ]
            )

            session.add(
                AssessmentIdempotencyRecord(
                    owner_id=owner_id,
                    operation_scope=operation_scope,
                    request_key=request_key,
                    request_fingerprint=fingerprint,
                    target_case_id=case.id,
                    assessment_id=assessment_id,
                    assessed_revision=request.expected_revision,
                    result_status_code=200,
                    resource_deleted=False,
                    created_at=commit_now,
                )
            )

        return AssessmentResult(
            assessment_id=assessment_id,
            case_id=case_id,
            assessed_revision=request.expected_revision,
            state=decision.state,
            reason_codes=decision.reason_codes,
            explanation=decision.explanation,
            evidence=tuple(
                AssessmentEvidenceView(
                    tactic=observation.tactic.value,
                    event_id=observation.event_id,
                    source_order=source_orders[observation.event_id],
                    quote=observation.quote,
                    start_offset=observation.start,
                    end_offset=observation.end,
                    context=observation.context.value,
                )
                for observation in observations
            ),
            alert=alert,
            tactics_used=decision.used_tactics,
            relationships=decision.relationships,
            suggested_next_action=decision.suggested_next_action,
            limitations=decision.limitations,
            extraction_mode=extractor.mode,
            extraction_version=extractor.version,
            rule_version=DIGITAL_ARREST_RULE_VERSION,
            schema_version=EXTRACTION_SCHEMA_VERSION,
            created_at=commit_now,
            is_current=True,
            idempotent_replay=False,
        )
    except IntegrityError as exc:
        retry_now = clock()
        with database.session_factory() as session:
            _require_live_owner(session, owner_id=owner_id, now=retry_now)
            case = _load_owned_case(
                session,
                owner_id=owner_id,
                case_id=case_id,
                now=retry_now,
            )
            replay = _existing_idempotency(
                session,
                owner_id=owner_id,
                case=case,
                request_key=request_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return replay
        raise ServiceError(
            409,
            "write_conflict",
            "The assessment could not be stored.",
        ) from exc


def get_latest_assessment(
    database: Database,
    *,
    owner_id: str,
    case_id: str,
    now: int,
) -> AssessmentResult:
    """Return the latest persisted assessment without hiding revision staleness."""

    with database.session_factory() as session:
        _require_live_owner(session, owner_id=owner_id, now=now)
        case = _load_owned_case(
            session,
            owner_id=owner_id,
            case_id=case_id,
            now=now,
        )
        assessment = session.scalar(
            select(Assessment)
            .where(
                Assessment.case_id == case.id,
                Assessment.owner_id == owner_id,
            )
            .order_by(Assessment.created_at.desc(), Assessment.id.desc())
            .limit(1)
        )
        if assessment is None:
            raise ServiceError(
                404,
                "assessment_not_found",
                "No assessment exists for this case.",
            )

        return _assessment_result_from_row(
            session,
            assessment=assessment,
            current_revision=case.revision,
            idempotent_replay=False,
        )
