from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.exc import OperationalError

from backend.scamflow.api_schemas import CreateCaseRequest
from backend.scamflow.database import create_database, initialize_schema
from backend.scamflow.models import Case, Event
from backend.scamflow.schemas import PaymentContext, ScamEvent
from backend.scamflow.security import CSRF_HEADER_NAME
from backend.scamflow.services import (
    authenticate_owner,
    bootstrap_session,
    create_case,
)
from backend.scamflow.settings import Environment, Settings

LOCAL_ORIGIN = "http://127.0.0.1:8000"
LOCAL_HEADERS = {"Origin": LOCAL_ORIGIN, CSRF_HEADER_NAME: "1"}


def local_settings(tmp_path: Path) -> Settings:
    return Settings(
        environment=Environment.TEST,
        database_path=tmp_path / "failures.sqlite3",
        trusted_origin=LOCAL_ORIGIN,
    )


def bootstrap(client: TestClient, headers: dict[str, str] | None = None) -> None:
    response = client.post("/session", headers=headers or LOCAL_HEADERS)
    assert response.status_code == 200


def create_body() -> dict[str, object]:
    return {
        "consent": True,
        "payment_context": {
            "stated_purpose": "Refund verification",
            "amount": "99.01",
        },
        "events": [
            {
                "event_id": "evt-1",
                "channel": "sms",
                "text": "Original private evidence",
                "source_order": 1,
            }
        ],
    }


def test_production_session_cookie_is_secure(tmp_path: Path) -> None:
    origin = "https://scamflow.example"
    settings = Settings(
        environment=Environment.PRODUCTION,
        database_path=tmp_path / "production.sqlite3",
        trusted_origin=origin,
    )

    from backend.scamflow.app import create_app

    app = create_app(settings)

    with TestClient(app, base_url=origin) as client:
        response = client.post(
            "/session",
            headers={"Origin": origin, CSRF_HEADER_NAME: "1"},
        )

        assert response.status_code == 200
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie
        assert "samesite=strict" in cookie
        assert "secure" in cookie


def test_database_failure_rolls_back_append_and_returns_safe_error(tmp_path: Path) -> None:
    from backend.scamflow.app import create_app

    app = create_app(local_settings(tmp_path))

    with TestClient(app, raise_server_exceptions=False) as client:
        bootstrap(client)

        created = client.post(
            "/cases",
            headers={**LOCAL_HEADERS, "Idempotency-Key": "create-ok"},
            json=create_body(),
        )
        assert created.status_code == 201
        case_id = created.json()["case_id"]

        def fail_idempotency_insert(
            _conn,
            _cursor,
            statement,
            _parameters,
            _context,
            _executemany,
        ) -> None:
            if statement.lstrip().upper().startswith("INSERT INTO IDEMPOTENCY_RECORDS"):
                raise OperationalError(
                    statement,
                    {},
                    RuntimeError("synthetic database failure with private evidence"),
                )

        event.listen(
            app.state.database.engine,
            "before_cursor_execute",
            fail_idempotency_insert,
        )
        try:
            response = client.post(
                f"/cases/{case_id}/events",
                headers={**LOCAL_HEADERS, "Idempotency-Key": "append-fails"},
                json={
                    "expected_revision": 1,
                    "events": [
                        {
                            "event_id": "evt-2",
                            "channel": "sms",
                            "text": "Sensitive evidence must not leak",
                            "source_order": 2,
                        }
                    ],
                },
            )
        finally:
            event.remove(
                app.state.database.engine,
                "before_cursor_execute",
                fail_idempotency_insert,
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
        assert "synthetic database failure" not in serialized
        assert "sensitive evidence" not in serialized

        current = client.get(f"/cases/{case_id}")
        assert current.status_code == 200
        assert current.json()["revision"] == 1
        assert [item["event_id"] for item in current.json()["events"]] == ["evt-1"]

        with app.state.database.session_factory() as session:
            assert (
                session.scalar(
                    select(func.count()).select_from(Event).where(Event.case_id == case_id)
                )
                == 1
            )


def test_concurrent_same_key_case_creation_is_one_logical_mutation(tmp_path: Path) -> None:
    settings = local_settings(tmp_path)
    database = create_database(settings)
    initialize_schema(database)
    now = 1_800_000_000

    session_result = bootstrap_session(
        database,
        settings,
        presented_token=None,
        now=now,
    )
    owner = authenticate_owner(
        database,
        token=session_result.token,
        now=now,
    )

    request = CreateCaseRequest(
        consent=True,
        payment_context=PaymentContext(stated_purpose="Refund verification"),
        events=[
            ScamEvent(
                event_id="evt-1",
                channel="sms",
                text="same request",
                source_order=1,
            )
        ],
    )
    barrier = Barrier(2)

    def worker():
        barrier.wait()
        return create_case(
            database,
            settings,
            owner_id=owner.id,
            request_key="same-create-key",
            request=request,
            now=now,
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(worker),
                executor.submit(worker),
            ]
            results = [future.result() for future in futures]

        assert {result.case_id for result in results}.__len__() == 1
        assert sorted(result.idempotent_replay for result in results) == [False, True]

        with database.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(Case)) == 1
            assert session.scalar(select(func.count()).select_from(Event)) == 1
    finally:
        database.dispose()


def test_validation_errors_do_not_echo_private_evidence(tmp_path: Path) -> None:
    from backend.scamflow.app import create_app

    app = create_app(local_settings(tmp_path))
    secret_text = "PRIVATE-EVIDENCE-DO-NOT-ECHO"

    with TestClient(app, raise_server_exceptions=False) as client:
        bootstrap(client)

        response = client.post(
            "/cases",
            headers={**LOCAL_HEADERS, "Idempotency-Key": "invalid-private"},
            json={
                "consent": True,
                "payment_context": {"stated_purpose": "Refund"},
                "events": [
                    {
                        "event_id": "evt-1",
                        "channel": "unsupported-channel",
                        "text": secret_text,
                        "source_order": 1,
                    }
                ],
            },
        )

        assert response.status_code == 422
        assert secret_text not in response.text
        assert response.json() == {
            "detail": {
                "code": "validation_error",
                "message": "The request is invalid.",
            }
        }
