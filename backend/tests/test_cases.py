from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.scamflow.app import create_app
from backend.scamflow.models import Case, Event, OwnerSession
from backend.scamflow.security import CSRF_HEADER_NAME, SESSION_COOKIE_NAME
from backend.scamflow.settings import Environment, Settings

ORIGIN = "http://127.0.0.1:8000"
CSRF_HEADERS = {"Origin": ORIGIN, CSRF_HEADER_NAME: "1"}


class FakeClock:
    def __init__(self, value: int = 1_800_000_000) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += seconds


def make_settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": Environment.TEST,
        "database_path": tmp_path / "test.sqlite3",
        "trusted_origin": ORIGIN,
    }
    values.update(overrides)
    return Settings(**values)


def make_create_body(
    *,
    consent: bool = True,
    event_id: str = "evt-1",
    source_order: int = 1,
    text: str = "  First line\nരണ്ടാം വരി\t  ",
    amount: str = "1500.50",
) -> dict[str, object]:
    return {
        "consent": consent,
        "payment_context": {
            "stated_purpose": "Refund verification",
            "amount": amount,
            "recipient_reference": "merchant-42",
        },
        "events": [
            {
                "event_id": event_id,
                "channel": "whatsapp",
                "text": text,
                "source_order": source_order,
            }
        ],
    }


def bootstrap(client: TestClient) -> None:
    response = client.post("/session", headers=CSRF_HEADERS)
    assert response.status_code == 200
    assert "expires_at" in response.json()
    assert SESSION_COOKIE_NAME not in response.json()


def create_case_request(
    client: TestClient,
    *,
    key: str = "create-1",
    body: dict[str, object] | None = None,
):
    return client.post(
        "/cases",
        headers={**CSRF_HEADERS, "Idempotency-Key": key},
        json=body if body is not None else make_create_body(),
    )


def test_create_retrieve_append_and_delete_round_trip(tmp_path: Path) -> None:
    clock = FakeClock()
    app = create_app(make_settings(tmp_path), clock=clock)

    with TestClient(app) as client:
        bootstrap(client)

        created = create_case_request(client)
        assert created.status_code == 201
        assert created.json()["result_revision"] == 1
        assert created.json()["idempotent_replay"] is False
        case_id = created.json()["case_id"]

        retrieved = client.get(f"/cases/{case_id}")
        assert retrieved.status_code == 200
        body = retrieved.json()
        assert body["revision"] == 1
        assert body["payment_context"]["amount"] == "1500.50"
        assert body["events"][0]["text"] == "  First line\nരണ്ടാം വരി\t  "

        appended = client.post(
            f"/cases/{case_id}/events",
            headers={**CSRF_HEADERS, "Idempotency-Key": "append-1"},
            json={
                "expected_revision": 1,
                "events": [
                    {
                        "event_id": "evt-2",
                        "channel": "sms",
                        "text": "Second event",
                        "source_order": 2,
                    }
                ],
            },
        )
        assert appended.status_code == 200
        assert appended.json() == {
            "case_id": case_id,
            "result_revision": 2,
            "idempotent_replay": False,
        }

        retrieved_again = client.get(f"/cases/{case_id}")
        assert retrieved_again.status_code == 200
        assert retrieved_again.json()["revision"] == 2
        assert [event["event_id"] for event in retrieved_again.json()["events"]] == [
            "evt-1",
            "evt-2",
        ]

        deleted = client.delete(f"/cases/{case_id}", headers=CSRF_HEADERS)
        assert deleted.status_code == 204
        assert client.get(f"/cases/{case_id}").status_code == 404

        with app.state.database.session_factory() as session:
            assert (
                session.scalar(select(func.count()).select_from(Case).where(Case.id == case_id))
                == 0
            )
            assert (
                session.scalar(
                    select(func.count()).select_from(Event).where(Event.case_id == case_id)
                )
                == 0
            )


def test_events_are_returned_by_source_order_not_insert_order(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))

    body = make_create_body()
    body["events"] = [
        {
            "event_id": "evt-2",
            "channel": "sms",
            "text": "Second",
            "source_order": 2,
        },
        {
            "event_id": "evt-1",
            "channel": "sms",
            "text": "First",
            "source_order": 1,
        },
    ]

    with TestClient(app) as client:
        bootstrap(client)
        created = create_case_request(client, body=body)
        assert created.status_code == 201

        retrieved = client.get(f"/cases/{created.json()['case_id']}")
        assert retrieved.status_code == 200
        assert [event["source_order"] for event in retrieved.json()["events"]] == [1, 2]


def test_false_or_missing_consent_is_rejected_without_writes(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))

    with TestClient(app) as client:
        bootstrap(client)

        false_body = make_create_body(consent=False)
        false_response = create_case_request(client, key="false", body=false_body)
        assert false_response.status_code == 422

        missing_body = make_create_body()
        del missing_body["consent"]
        missing_response = create_case_request(client, key="missing", body=missing_body)
        assert missing_response.status_code == 422

        with app.state.database.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(Case)) == 0


def test_two_clients_are_isolated_and_other_owner_gets_not_found(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))

    with TestClient(app) as owner, TestClient(app) as stranger:
        bootstrap(owner)
        bootstrap(stranger)

        created = create_case_request(owner)
        case_id = created.json()["case_id"]

        assert stranger.get(f"/cases/{case_id}").status_code == 404

        append = stranger.post(
            f"/cases/{case_id}/events",
            headers={**CSRF_HEADERS, "Idempotency-Key": "stranger-append"},
            json={
                "expected_revision": 1,
                "events": [
                    {
                        "event_id": "other",
                        "channel": "sms",
                        "text": "No access",
                        "source_order": 2,
                    }
                ],
            },
        )
        assert append.status_code == 404
        assert stranger.delete(f"/cases/{case_id}", headers=CSRF_HEADERS).status_code == 404


def test_missing_forged_and_expired_sessions_are_rejected(tmp_path: Path) -> None:
    clock = FakeClock()
    app = create_app(
        make_settings(tmp_path, session_ttl_seconds=60),
        clock=clock,
    )

    with TestClient(app) as client:
        assert client.get("/cases/does-not-exist").status_code == 401

        client.cookies.set(SESSION_COOKIE_NAME, "forged-token")
        assert client.get("/cases/does-not-exist").status_code == 401

        client.cookies.clear()
        bootstrap(client)
        clock.advance(61)
        assert client.get("/cases/does-not-exist").status_code == 401


def test_session_replacement_does_not_inherit_cases(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))

    with TestClient(app) as client:
        bootstrap(client)
        created = create_case_request(client)
        case_id = created.json()["case_id"]

        client.cookies.clear()
        bootstrap(client)

        assert client.get(f"/cases/{case_id}").status_code == 404

        with app.state.database.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(OwnerSession)) == 2


def test_cookie_flags_and_csrf_are_enforced(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))

    with TestClient(app) as client:
        missing_csrf = client.post("/session")
        assert missing_csrf.status_code == 403

        wrong_origin = client.post(
            "/session",
            headers={"Origin": "http://evil.example", CSRF_HEADER_NAME: "1"},
        )
        assert wrong_origin.status_code == 403

        response = client.post("/session", headers=CSRF_HEADERS)
        assert response.status_code == 200

        set_cookie = response.headers["set-cookie"].lower()
        assert "httponly" in set_cookie
        assert "samesite=strict" in set_cookie
        assert "secure" not in set_cookie
        assert SESSION_COOKIE_NAME not in response.json()

        no_csrf_create = client.post(
            "/cases",
            headers={"Idempotency-Key": "create-no-csrf"},
            json=make_create_body(),
        )
        assert no_csrf_create.status_code == 403


def test_expired_case_is_inaccessible(tmp_path: Path) -> None:
    clock = FakeClock()
    app = create_app(
        make_settings(tmp_path, case_retention_seconds=60),
        clock=clock,
    )

    with TestClient(app) as client:
        bootstrap(client)
        created = create_case_request(client)
        case_id = created.json()["case_id"]

        clock.advance(61)

        assert client.get(f"/cases/{case_id}").status_code == 404
        assert client.delete(f"/cases/{case_id}", headers=CSRF_HEADERS).status_code == 404


def test_data_survives_application_recreation(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)

    first_app = create_app(settings)
    with TestClient(first_app) as first_client:
        bootstrap(first_client)
        created = create_case_request(first_client)
        case_id = created.json()["case_id"]
        session_cookie = first_client.cookies.get(SESSION_COOKIE_NAME)
        assert session_cookie is not None

    second_app = create_app(settings)
    with TestClient(second_app) as second_client:
        second_client.cookies.set(SESSION_COOKIE_NAME, session_cookie)
        retrieved = second_client.get(f"/cases/{case_id}")
        assert retrieved.status_code == 200
        assert retrieved.json()["case_id"] == case_id
