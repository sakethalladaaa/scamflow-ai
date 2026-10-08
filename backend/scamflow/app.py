"""FastAPI application factory for ScamFlow AI."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from .api_schemas import (
    AlertResponse,
    AppendEventsRequest,
    AssessCaseRequest,
    AssessmentEvidenceResponse,
    AssessmentResponse,
    CaseResponse,
    CreateCaseRequest,
    ErrorDetail,
    ErrorResponse,
    MutationResponse,
    SessionResponse,
    StoredEventResponse,
)
from .assessment_services import assess_case, get_latest_assessment
from .database import create_database, initialize_schema
from .detection import MOCK_EXTRACTION_MODE, DevelopmentMockExtractor, Extractor
from .schemas import HealthResponse
from .security import (
    CSRF_HEADER_NAME,
    SESSION_COOKIE_NAME,
    request_has_valid_csrf_context,
)
from .services import (
    Clock,
    ServiceError,
    append_events,
    authenticate_owner,
    bootstrap_session,
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
    if resolved_extractor is None and resolved_settings.environment is not Environment.PRODUCTION:
        resolved_extractor = DevelopmentMockExtractor()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = create_database(resolved_settings)
        initialize_schema(database)
        app.state.database = database
        try:
            yield
        finally:
            database.dispose()

    app = FastAPI(
        title="ScamFlow AI",
        version="0.3.0",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.clock = clock
    app.state.extractor = resolved_extractor

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
        return authenticate_owner(
            app.state.database,
            token=token,
            now=now(),
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

    @app.post(
        "/session",
        response_model=SessionResponse,
        responses={403: {"model": ErrorResponse}},
    )
    def session_bootstrap(request: Request, response: Response) -> SessionResponse:
        """Reuse a valid anonymous owner session or create an isolated replacement."""

        require_csrf(request)
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
        # API routes are registered first. StaticFiles' html fallback then
        # serves the production SPA from the same origin.
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

    return app


app = create_app()
