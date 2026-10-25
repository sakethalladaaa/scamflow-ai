"""FastAPI application factory for ScamFlow AI."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from .api_schemas import (
    AccountResponse,
    AlertResponse,
    AppendEventsRequest,
    AssessCaseRequest,
    AssessmentEvidenceResponse,
    AssessmentResponse,
    CaseResponse,
    CreateCaseRequest,
    CreateReviewRequestRequest,
    CreateReviewRequestResponse,
    ErrorDetail,
    ErrorResponse,
    LoginRequest,
    MutationResponse,
    RegisterRequest,
    ResolveReviewRequestRequest,
    ResolveReviewRequestResponse,
    ReviewerAssessmentSnapshotResponse,
    ReviewerEvidenceResponse,
    ReviewerQueueItemResponse,
    ReviewerQueueResponse,
    ReviewerReviewRequestDetailResponse,
    ReviewRequestStatusResponse,
    SessionResponse,
    StoredEventResponse,
)
from .assessment_services import assess_case, get_latest_assessment
from .auth_services import login_account, logout_account, register_account
from .database import create_database, initialize_schema, run_postgres_migrations
from .detection import MOCK_EXTRACTION_MODE, DevelopmentMockExtractor, Extractor, RulesOnlyExtractor
from .models import Account
from .review_services import (
    create_review_request,
    get_owner_review_request,
    get_reviewer_review_detail,
    list_open_review_requests,
    resolve_review_request,
)
from .schemas import HealthResponse
from .security import (
    CSRF_HEADER_NAME,
    REVIEWER_HEADER_NAME,
    SESSION_COOKIE_NAME,
    request_has_valid_csrf_context,
    reviewer_token_matches,
)
from .services import (
    Clock,
    ServiceError,
    append_events,
    authenticate_owner,
    bootstrap_session,
    cleanup_expired_data,
    create_case,
    delete_case,
    epoch_to_datetime,
    get_case,
    payment_context_from_case,
    system_clock,
)
from .settings import Environment, Settings

IDEMPOTENCY_KEY_MAX_CHARACTERS = 128


def create_app(
    settings: Settings | None = None,
    *,
    clock: Clock = system_clock,
    extractor: Extractor | None = None,
) -> FastAPI:
    """Create a ScamFlow AI FastAPI application instance."""

    resolved_settings = settings if settings is not None else Settings()

    if (
        resolved_settings.environment is Environment.PRODUCTION
        and extractor is not None
        and extractor.mode == MOCK_EXTRACTION_MODE
    ):
        raise ValueError("The development mock extractor cannot be used in production.")

    resolved_extractor: Extractor | None = extractor
    if resolved_extractor is None:
        if resolved_settings.extractor_mode == "rules":
            resolved_extractor = (
                DevelopmentMockExtractor()
                if resolved_settings.environment is not Environment.PRODUCTION
                else RulesOnlyExtractor()
            )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = create_database(resolved_settings)
        if database.engine.dialect.name == "postgresql":
            run_postgres_migrations(database)
        else:
            initialize_schema(database)
        app.state.database = database
        cleanup_expired_data(database, now=app.state.clock())

        async def cleanup_loop() -> None:
            while True:
                await asyncio.sleep(resolved_settings.cleanup_interval_seconds)
                cleanup_expired_data(database, now=app.state.clock())

        cleanup_task = asyncio.create_task(cleanup_loop())
        try:
            yield
        finally:
            cleanup_task.cancel()
            await asyncio.gather(cleanup_task, return_exceptions=True)
            database.dispose()

    app = FastAPI(
        title="ScamFlow AI",
        version="0.3.0",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.clock = clock
    app.state.extractor = resolved_extractor

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[resolved_settings.trusted_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Idempotency-Key", CSRF_HEADER_NAME, REVIEWER_HEADER_NAME],
    )

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > resolved_settings.max_request_bytes:
            return JSONResponse(
                status_code=413,
                content={
                    "detail": {"code": "request_too_large", "message": "Request is too large."}
                },
            )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'self'; frame-ancestors 'none'"
        )
        if resolved_settings.environment is Environment.PRODUCTION:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    @app.exception_handler(ServiceError)
    async def handle_service_error(
        _request: Request,
        exc: ServiceError,
    ) -> JSONResponse:
        body = ErrorResponse(detail=ErrorDetail(code=exc.code, message=exc.message)).model_dump(
            mode="json"
        )
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request,
        _exc: RequestValidationError,
    ) -> JSONResponse:
        body = ErrorResponse(
            detail=ErrorDetail(
                code="validation_error",
                message="The request is invalid.",
            )
        ).model_dump(mode="json")
        return JSONResponse(status_code=422, content=body)

    @app.exception_handler(SQLAlchemyError)
    async def handle_database_error(
        _request: Request,
        _exc: SQLAlchemyError,
    ) -> JSONResponse:
        body = ErrorResponse(
            detail=ErrorDetail(
                code="database_unavailable",
                message="The database operation could not be completed.",
            )
        ).model_dump(mode="json")
        return JSONResponse(status_code=503, content=body)

    def now() -> int:
        return app.state.clock()

    def require_csrf(request: Request) -> None:
        if not request_has_valid_csrf_context(
            request,
            app.state.settings.trusted_origin,
        ):
            raise ServiceError(
                403,
                "csrf_rejected",
                f"Unsafe requests require exact Origin and {CSRF_HEADER_NAME}.",
            )

    def require_owner(request: Request):
        token = request.cookies.get(SESSION_COOKIE_NAME)
        owner = authenticate_owner(
            app.state.database,
            token=token,
            now=now(),
        )
        if resolved_settings.environment is Environment.PRODUCTION and owner.account_id is None:
            raise ServiceError(401, "account_required", "Sign in is required.")
        return owner

    def require_reviewer(request: Request, presented_token: str | None) -> None:
        """Require a role-backed account in production, token only in local dev."""

        if resolved_settings.environment is Environment.PRODUCTION:
            account = account_from_request(request)
            if account.role not in {"reviewer", "admin"}:
                raise ServiceError(403, "reviewer_role_required", "Reviewer access is required.")
            return
        configured = app.state.settings.reviewer_token
        if configured is None or not configured.get_secret_value().strip():
            raise ServiceError(
                503,
                "reviewer_access_unconfigured",
                "Reviewer access is not configured.",
            )
        if presented_token is None or not reviewer_token_matches(
            presented_token,
            configured.get_secret_value(),
        ):
            raise ServiceError(
                401,
                "reviewer_auth_required",
                "Reviewer authorization is required.",
            )

    def account_from_request(request: Request) -> Account:
        owner = require_owner(request)
        if owner.account_id is None:
            raise ServiceError(401, "account_required", "Sign in is required.")
        with app.state.database.session_factory() as session:
            account = session.get(Account, owner.account_id)
            if account is None or not account.active:
                raise ServiceError(401, "account_invalid", "Sign in is required.")
            return account

    def set_session_cookie(response: Response, token: str, expires_at: int) -> None:
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=token,
            max_age=max(0, expires_at - now()),
            httponly=True,
            secure=app.state.settings.session_cookie_secure,
            samesite="strict",
            path="/",
        )

    def require_idempotency_key(
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> str:
        if idempotency_key is None:
            raise ServiceError(
                422,
                "idempotency_key_required",
                "Idempotency-Key is required.",
            )

        normalized = idempotency_key.strip()
        if not normalized or len(normalized) > IDEMPOTENCY_KEY_MAX_CHARACTERS:
            raise ServiceError(
                422,
                "idempotency_key_invalid",
                f"Idempotency-Key must contain 1-{IDEMPOTENCY_KEY_MAX_CHARACTERS} characters.",
            )
        return normalized

    def case_response(case, events) -> CaseResponse:
        return CaseResponse(
            case_id=case.id,
            consent_version=case.consent_version,
            consented_at=epoch_to_datetime(case.consented_at),
            payment_context=payment_context_from_case(case),
            revision=case.revision,
            created_at=epoch_to_datetime(case.created_at),
            updated_at=epoch_to_datetime(case.updated_at),
            expires_at=epoch_to_datetime(case.expires_at),
            events=[
                StoredEventResponse(
                    event_id=event.client_event_id,
                    channel=event.channel,
                    text=event.original_text,
                    source_order=event.source_order,
                    ingested_at=epoch_to_datetime(event.ingested_at),
                )
                for event in events
            ],
        )

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        """Return application liveness only."""

        return HealthResponse()

    @app.get("/ready", response_model=HealthResponse)
    def readiness() -> HealthResponse:
        """Verify database connectivity for deployment readiness checks."""

        with app.state.database.engine.connect() as connection:
            connection.execute(select(1))
        return HealthResponse()

    @app.post("/auth/register", response_model=AccountResponse, status_code=201)
    def register_route(
        request: Request, response: Response, body: RegisterRequest
    ) -> AccountResponse:
        require_csrf(request)
        result = register_account(
            app.state.database,
            app.state.settings,
            email=body.email,
            password=body.password,
            now=now(),
        )
        set_session_cookie(response, result.token, result.expires_at)
        return AccountResponse(
            account_id=result.account.id,
            email=result.account.email,
            role=result.account.role,
        )

    @app.post("/auth/login", response_model=AccountResponse)
    def login_route(request: Request, response: Response, body: LoginRequest) -> AccountResponse:
        require_csrf(request)
        client_key = request.client.host if request.client else "unknown"
        result = login_account(
            app.state.database,
            app.state.settings,
            email=body.email,
            password=body.password,
            client_key=client_key,
            now=now(),
        )
        set_session_cookie(response, result.token, result.expires_at)
        return AccountResponse(
            account_id=result.account.id,
            email=result.account.email,
            role=result.account.role,
        )

    @app.get("/auth/me", response_model=AccountResponse)
    def me_route(request: Request) -> AccountResponse:
        account = account_from_request(request)
        return AccountResponse(account_id=account.id, email=account.email, role=account.role)

    @app.post("/auth/logout", status_code=204)
    def logout_route(request: Request, response: Response) -> Response:
        require_csrf(request)
        logout_account(app.state.database, request.cookies.get(SESSION_COOKIE_NAME))
        response.delete_cookie(SESSION_COOKIE_NAME, path="/")
        response.status_code = 204
        return response

    @app.post(
        "/session",
        response_model=SessionResponse,
        responses={403: {"model": ErrorResponse}},
    )
    def session_bootstrap(request: Request, response: Response) -> SessionResponse:
        """Reuse a valid anonymous owner session or create an isolated replacement."""

        require_csrf(request)
        if resolved_settings.environment is Environment.PRODUCTION:
            raise ServiceError(401, "account_required", "Sign in is required.")
        result = bootstrap_session(
            app.state.database,
            app.state.settings,
            presented_token=request.cookies.get(SESSION_COOKIE_NAME),
            now=now(),
        )
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=result.token,
            max_age=app.state.settings.session_ttl_seconds,
            httponly=True,
            secure=app.state.settings.session_cookie_secure,
            samesite="strict",
            path="/",
        )
        return SessionResponse(expires_at=epoch_to_datetime(result.expires_at))

    @app.post(
        "/cases",
        response_model=MutationResponse,
        status_code=201,
        responses={
            401: {"model": ErrorResponse},
            403: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
        },
    )
    def create_case_route(
        request: Request,
        body: CreateCaseRequest,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> MutationResponse:
        """Create a consented case for the authenticated anonymous owner."""

        require_csrf(request)
        owner = require_owner(request)
        key = require_idempotency_key(idempotency_key)
        result = create_case(
            app.state.database,
            app.state.settings,
            owner_id=owner.id,
            request_key=key,
            request=body,
            now=now(),
        )
        return MutationResponse(
            case_id=result.case_id,
            result_revision=result.result_revision,
            idempotent_replay=result.idempotent_replay,
        )

    def assessment_response(result) -> AssessmentResponse:
        return AssessmentResponse(
            assessment_id=result.assessment_id,
            case_id=result.case_id,
            assessed_revision=result.assessed_revision,
            state=result.state,
            reason_codes=list(result.reason_codes),
            explanation=result.explanation,
            evidence=[
                AssessmentEvidenceResponse(
                    tactic=item.tactic,
                    event_id=item.event_id,
                    source_order=item.source_order,
                    quote=item.quote,
                    start_offset=item.start_offset,
                    end_offset=item.end_offset,
                    context=item.context,
                )
                for item in result.evidence
            ],
            alert=AlertResponse(
                visible=result.alert.visible,
                reason=result.alert.reason,
                prior_warning_state=result.alert.prior_warning_state,
            ),
            tactics_used=list(result.tactics_used),
            relationships=list(result.relationships),
            suggested_next_action=result.suggested_next_action,
            limitations=list(result.limitations),
            extraction_mode=result.extraction_mode,
            extraction_version=result.extraction_version,
            rule_version=result.rule_version,
            schema_version=result.schema_version,
            created_at=epoch_to_datetime(result.created_at),
            is_current=result.is_current,
            idempotent_replay=result.idempotent_replay,
        )

    def review_status_response(review_request) -> ReviewRequestStatusResponse:
        return ReviewRequestStatusResponse(
            review_request_id=review_request.id,
            case_id=review_request.case_id,
            assessment_id=review_request.assessment_id,
            assessed_revision=review_request.assessed_revision,
            status=review_request.status,
            submitted_at=epoch_to_datetime(review_request.submitted_at),
            resolved_at=(
                epoch_to_datetime(review_request.resolved_at)
                if review_request.resolved_at is not None
                else None
            ),
            outcome=review_request.outcome,
        )

    def reviewer_detail_response(detail) -> ReviewerReviewRequestDetailResponse:
        assessment = detail.assessment
        alert = detail.alert
        return ReviewerReviewRequestDetailResponse(
            **review_status_response(detail.request).model_dump(),
            reviewer_note=detail.request.reviewer_note,
            assessment=ReviewerAssessmentSnapshotResponse(
                assessment_id=assessment.id,
                case_id=assessment.case_id,
                assessed_revision=assessment.assessed_revision,
                state=assessment.state,
                reason_codes=list(json.loads(assessment.reason_codes_json)),
                explanation=assessment.explanation,
                evidence=[
                    ReviewerEvidenceResponse(
                        tactic=evidence.tactic,
                        event_id=evidence.event_id,
                        source_order=evidence.source_order,
                        quote=evidence.quote,
                        start_offset=evidence.start_offset,
                        end_offset=evidence.end_offset,
                        context=evidence.context,
                        channel=event.channel,
                        source_text=event.original_text,
                    )
                    for evidence, event in detail.evidence_and_sources
                ],
                alert=AlertResponse(
                    visible=alert.visible if alert is not None else False,
                    reason=alert.reason if alert is not None else "legacy_assessment",
                    prior_warning_state=(alert.prior_warning_state if alert is not None else None),
                ),
                tactics_used=list(json.loads(assessment.used_tactics_json)),
                relationships=list(json.loads(assessment.relationships_json)),
                suggested_next_action=assessment.suggested_next_action,
                limitations=list(json.loads(assessment.limitations_json)),
                extraction_mode=assessment.extraction_mode,
                extraction_version=assessment.extraction_version,
                rule_version=assessment.rule_version,
                schema_version=assessment.schema_version,
                created_at=epoch_to_datetime(assessment.created_at),
                is_current=detail.case.revision == assessment.assessed_revision,
                payment_context=payment_context_from_case(detail.case),
            ),
        )

    @app.get(
        "/cases/{case_id}",
        response_model=CaseResponse,
        responses={
            401: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
        },
    )
    def get_case_route(request: Request, case_id: str) -> CaseResponse:
        """Retrieve one owned, unexpired case."""

        owner = require_owner(request)
        case, events = get_case(
            app.state.database,
            owner_id=owner.id,
            case_id=case_id,
            now=now(),
        )
        return case_response(case, events)

    @app.post(
        "/cases/{case_id}/events",
        response_model=MutationResponse,
        responses={
            401: {"model": ErrorResponse},
            403: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
        },
    )
    def append_events_route(
        request: Request,
        case_id: str,
        body: AppendEventsRequest,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> MutationResponse:
        """Append evidence to one owned case."""

        require_csrf(request)
        owner = require_owner(request)
        key = require_idempotency_key(idempotency_key)
        result = append_events(
            app.state.database,
            owner_id=owner.id,
            case_id=case_id,
            request_key=key,
            request=body,
            now=now(),
        )
        return MutationResponse(
            case_id=result.case_id,
            result_revision=result.result_revision,
            idempotent_replay=result.idempotent_replay,
        )

    @app.post(
        "/cases/{case_id}/assess",
        response_model=AssessmentResponse,
        responses={
            401: {"model": ErrorResponse},
            403: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    def assess_case_route(
        request: Request,
        case_id: str,
        body: AssessCaseRequest,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> AssessmentResponse:
        """Assess one exact persisted case revision."""

        require_csrf(request)
        owner = require_owner(request)
        key = require_idempotency_key(idempotency_key)

        configured_extractor = app.state.extractor
        if configured_extractor is None:
            raise ServiceError(
                503,
                "assessment_unavailable",
                "No assessment extractor is configured for this environment.",
            )

        result = assess_case(
            app.state.database,
            app.state.settings,
            extractor=configured_extractor,
            owner_id=owner.id,
            case_id=case_id,
            request_key=key,
            request=body,
            clock=app.state.clock,
        )
        return assessment_response(result)

    @app.get(
        "/cases/{case_id}/assessments/latest",
        response_model=AssessmentResponse,
        responses={
            401: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
        },
    )
    def latest_assessment_route(request: Request, case_id: str) -> AssessmentResponse:
        """Return the newest persisted assessment and expose revision staleness."""

        owner = require_owner(request)
        result = get_latest_assessment(
            app.state.database,
            owner_id=owner.id,
            case_id=case_id,
            now=now(),
        )
        return assessment_response(result)

    @app.post(
        "/cases/{case_id}/review-requests",
        response_model=CreateReviewRequestResponse,
        status_code=201,
        responses={
            401: {"model": ErrorResponse},
            403: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    def create_review_request_route(
        request: Request,
        response: Response,
        case_id: str,
        body: CreateReviewRequestRequest,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> CreateReviewRequestResponse:
        """Create an owner-scoped request tied to one current persisted assessment."""

        require_csrf(request)
        owner = require_owner(request)
        key = require_idempotency_key(idempotency_key)
        result = create_review_request(
            app.state.database,
            owner_id=owner.id,
            case_id=case_id,
            request_key=key,
            request=body,
            now=now(),
        )
        response.status_code = (
            200 if result.idempotent_replay or result.existing_open_request else 201
        )
        return CreateReviewRequestResponse(
            **review_status_response(result.request).model_dump(),
            idempotent_replay=result.idempotent_replay,
            existing_open_request=result.existing_open_request,
        )

    @app.get(
        "/cases/{case_id}/review-requests/{review_request_id}",
        response_model=ReviewRequestStatusResponse,
        responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    def owner_review_request_status_route(
        request: Request,
        case_id: str,
        review_request_id: str,
    ) -> ReviewRequestStatusResponse:
        """Return status only when the caller owns the case and review request."""

        owner = require_owner(request)
        review_request = get_owner_review_request(
            app.state.database,
            owner_id=owner.id,
            case_id=case_id,
            review_request_id=review_request_id,
            now=now(),
        )
        return review_status_response(review_request)

    @app.get(
        "/reviewer/review-requests",
        response_model=ReviewerQueueResponse,
        responses={401: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    )
    def reviewer_queue_route(
        request: Request,
        reviewer_token: Annotated[str | None, Header(alias=REVIEWER_HEADER_NAME)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    ) -> ReviewerQueueResponse:
        """List open requests only for a caller with explicit reviewer authorization."""

        require_reviewer(request, reviewer_token)
        rows, total = list_open_review_requests(
            app.state.database,
            now=now(),
            limit=limit,
            offset=offset,
        )
        return ReviewerQueueResponse(
            items=[
                ReviewerQueueItemResponse(
                    review_request_id=review_request.id,
                    case_id=review_request.case_id,
                    assessment_id=review_request.assessment_id,
                    assessed_revision=review_request.assessed_revision,
                    assessment_state=assessment.state,
                    is_current=case_revision == review_request.assessed_revision,
                    submitted_at=epoch_to_datetime(review_request.submitted_at),
                )
                for review_request, assessment, case_revision in rows
            ],
            total=total,
            limit=limit,
            offset=offset,
        )

    @app.get(
        "/reviewer/review-requests/{review_request_id}",
        response_model=ReviewerReviewRequestDetailResponse,
        responses={
            401: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    def reviewer_review_request_detail_route(
        request: Request,
        review_request_id: str,
        reviewer_token: Annotated[str | None, Header(alias=REVIEWER_HEADER_NAME)] = None,
    ) -> ReviewerReviewRequestDetailResponse:
        """Return reviewer-only request, persisted assessment, and exact source evidence."""

        require_reviewer(request, reviewer_token)
        detail = get_reviewer_review_detail(
            app.state.database,
            review_request_id=review_request_id,
            now=now(),
        )
        return reviewer_detail_response(detail)

    @app.post(
        "/reviewer/review-requests/{review_request_id}/resolve",
        response_model=ResolveReviewRequestResponse,
        responses={
            401: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    def reviewer_resolve_request_route(
        request: Request,
        review_request_id: str,
        body: ResolveReviewRequestRequest,
        reviewer_token: Annotated[str | None, Header(alias=REVIEWER_HEADER_NAME)] = None,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> ResolveReviewRequestResponse:
        """Resolve one open workflow request; this never changes its assessment."""

        require_reviewer(request, reviewer_token)
        if resolved_settings.environment is Environment.PRODUCTION:
            require_csrf(request)
        key = require_idempotency_key(idempotency_key)
        result = resolve_review_request(
            app.state.database,
            review_request_id=review_request_id,
            request_key=key,
            request=body,
            now=now(),
        )
        return ResolveReviewRequestResponse(
            **review_status_response(result.request).model_dump(),
            reviewer_note=result.request.reviewer_note,
            idempotent_replay=result.idempotent_replay,
        )

    @app.delete(
        "/cases/{case_id}",
        status_code=204,
        responses={
            401: {"model": ErrorResponse},
            403: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
        },
    )
    def delete_case_route(request: Request, case_id: str) -> Response:
        """Hard-delete one owned case atomically."""

        require_csrf(request)
        owner = require_owner(request)
        delete_case(
            app.state.database,
            owner_id=owner.id,
            case_id=case_id,
            now=now(),
        )
        return Response(status_code=204)

    frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if frontend_dist.is_dir():
        @app.get("/reviewer", include_in_schema=False)
        def reviewer_spa_route() -> FileResponse:
            """Serve the SPA entrypoint so a reviewer refresh keeps its client route."""

            return FileResponse(frontend_dist / "index.html")

        # API routes are registered first. StaticFiles' html fallback then
        # serves the production SPA from the same origin.
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

    return app


app = create_app()
