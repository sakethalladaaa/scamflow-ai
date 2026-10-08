from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.exc import OperationalError

from backend.scamflow.app import create_app
from backend.scamflow.models import (
    AlertMemory,
    Assessment,
    AssessmentAlert,
    AssessmentEvidence,
    AssessmentIdempotencyRecord,
)
from backend.scamflow.security import CSRF_HEADER_NAME, SESSION_COOKIE_NAME
from backend.scamflow.settings import Environment, Settings

ORIGIN = "http://127.0.0.1:8000"
HEADERS = {"Origin": ORIGIN, CSRF_HEADER_NAME: "1"}


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        environment=Environment.TEST,
        database_path=tmp_path / "assessment-persistence.sqlite3",
        trusted_origin=ORIGIN,
    )


def bootstrap(client: TestClient) -> None:
    assert client.post("/session", headers=HEADERS).status_code == 200


def create_case(client: TestClient) -> str:
    response = client.post(
        "/cases",
        headers={**HEADERS, "Idempotency-Key": "create-1"},
        json={
            "consent": True,
            "payment_context": {
                "stated_purpose": "Verification",
                "amount": "5000",
            },
            "events": [
                {
                    "event_id": "evt-1",
                    "channel": "call_transcript",
                    "text": ("I am a police officer. You will be arrested. Stay on the call."),
                    "source_order": 1,
                }
            ],
        },
    )
    assert response.status_code == 201
    return response.json()["case_id"]


def assess(client: TestClient, case_id: str, *, key: str):
    return client.post(
        f"/cases/{case_id}/assess",
        headers={**HEADERS, "Idempotency-Key": key},
        json={"expected_revision": 1},
    )


def test_assessment_survives_application_recreation(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)

    first_app = create_app(settings)
    with TestClient(first_app) as first_client:
        bootstrap(first_client)
        case_id = create_case(first_client)

        assessed = assess(first_client, case_id, key="persist-assessment")
        assert assessed.status_code == 200
        assessment_id = assessed.json()["assessment_id"]

        session_cookie = first_client.cookies.get(SESSION_COOKIE_NAME)
        assert session_cookie is not None

    second_app = create_app(settings)
    with TestClient(second_app) as second_client:
        second_client.cookies.set(SESSION_COOKIE_NAME, session_cookie)

        latest = second_client.get(f"/cases/{case_id}/assessments/latest")

        assert latest.status_code == 200
        body = latest.json()
        assert body["assessment_id"] == assessment_id
        assert body["state"] == "high_risk_indicators"
        assert body["assessed_revision"] == 1
        assert body["is_current"] is True
        assert body["evidence"]


def test_database_failure_rolls_back_entire_assessment_write(
    tmp_path: Path,
) -> None:
    app = create_app(make_settings(tmp_path))

    with TestClient(app, raise_server_exceptions=False) as client:
        bootstrap(client)
        case_id = create_case(client)

        def fail_assessment_idempotency_insert(
            _conn,
            _cursor,
            statement,
            _parameters,
            _context,
            _executemany,
        ) -> None:
            if statement.lstrip().upper().startswith("INSERT INTO ASSESSMENT_IDEMPOTENCY_RECORDS"):
                raise OperationalError(
                    statement,
                    {},
                    RuntimeError("synthetic private assessment database failure"),
                )

        event.listen(
            app.state.database.engine,
            "before_cursor_execute",
            fail_assessment_idempotency_insert,
        )
        try:
            response = assess(client, case_id, key="assessment-db-failure")
        finally:
            event.remove(
                app.state.database.engine,
                "before_cursor_execute",
                fail_assessment_idempotency_insert,
            )

        assert response.status_code == 503
        assert response.json() == {
            "detail": {
                "code": "database_unavailable",
                "message": "The database operation could not be completed.",
            }
        }

        serialized = response.text.lower()
        assert "insert into" not in serialized
        assert "synthetic private assessment database failure" not in serialized

        with app.state.database.session_factory() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(Assessment)
                    .where(Assessment.case_id == case_id)
                )
                == 0
            )
            assert session.scalar(select(func.count()).select_from(AssessmentEvidence)) == 0
            assert session.scalar(select(func.count()).select_from(AssessmentAlert)) == 0
            assert session.scalar(select(func.count()).select_from(AlertMemory)) == 0
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AssessmentIdempotencyRecord)
                    .where(AssessmentIdempotencyRecord.target_case_id == case_id)
                )
                == 0
            )

        latest = client.get(f"/cases/{case_id}/assessments/latest")
        assert latest.status_code == 404
        assert latest.json()["detail"]["code"] == "assessment_not_found"
