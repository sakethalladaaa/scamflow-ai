from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.scamflow.app import create_app
from backend.scamflow.models import Case, Event, IdempotencyRecord
from backend.scamflow.security import CSRF_HEADER_NAME
from backend.scamflow.settings import Environment, Settings

ORIGIN = "http://127.0.0.1:8000"
HEADERS = {"Origin": ORIGIN, CSRF_HEADER_NAME: "1"}


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        environment=Environment.TEST,
        database_path=tmp_path / "mutations.sqlite3",
        trusted_origin=ORIGIN,
    )


def bootstrap(client: TestClient) -> None:
    assert client.post("/session", headers=HEADERS).status_code == 200


def create_body(
    *,
    event_id: str = "evt-1",
    source_order: int = 1,
    text: str = "Initial evidence",
    amount: str = "1234567890.123456789",
) -> dict[str, object]:
    return {
        "consent": True,
        "payment_context": {
            "stated_purpose": "Refund verification",
            "amount": amount,
            "recipient_reference": "recipient-1",
        },
        "events": [
            {
                "event_id": event_id,
                "channel": "sms",
                "text": text,
                "source_order": source_order,
            }
        ],
    }


def create_case(
    client: TestClient,
    *,
    key: str = "create-1",
    body: dict[str, object] | None = None,
):
    return client.post(
        "/cases",
        headers={**HEADERS, "Idempotency-Key": key},
        json=body if body is not None else create_body(),
    )


def append(
    client: TestClient,
    case_id: str,
    *,
    key: str,
    expected_revision: int,
    event_id: str,
    source_order: int,
    text: str = "Additional evidence",
):
    return client.post(
        f"/cases/{case_id}/events",
        headers={**HEADERS, "Idempotency-Key": key},
        json={
            "expected_revision": expected_revision,
            "events": [
                {
                    "event_id": event_id,
                    "channel": "whatsapp",
                    "text": text,
                    "source_order": source_order,
                }
            ],
        },
    )


def test_create_idempotency_replays_same_logical_result(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))

    with TestClient(app) as client:
        bootstrap(client)

        first = create_case(client, key="same-create")
        second = create_case(client, key="same-create")

        assert first.status_code == 201
        assert second.status_code == 201
        assert second.json() == {
            "case_id": first.json()["case_id"],
            "result_revision": 1,
            "idempotent_replay": True,
        }

        with app.state.database.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(Case)) == 1
            assert session.scalar(select(func.count()).select_from(Event)) == 1
            assert session.scalar(select(func.count()).select_from(IdempotencyRecord)) == 1


def test_same_create_key_with_changed_payload_conflicts(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))

    with TestClient(app) as client:
        bootstrap(client)

        assert create_case(client, key="same-create").status_code == 201

        changed = create_body(text="Different evidence")
        response = create_case(client, key="same-create", body=changed)

        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "idempotency_conflict"


def test_append_idempotency_is_checked_before_old_revision(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))

    with TestClient(app) as client:
        bootstrap(client)
        case_id = create_case(client).json()["case_id"]

        first = append(
            client,
            case_id,
            key="append-1",
            expected_revision=1,
            event_id="evt-2",
            source_order=2,
        )
        assert first.status_code == 200
        assert first.json()["result_revision"] == 2

        later = append(
            client,
            case_id,
            key="append-2",
            expected_revision=2,
            event_id="evt-3",
            source_order=3,
        )
        assert later.status_code == 200
        assert later.json()["result_revision"] == 3

        retry = append(
            client,
            case_id,
            key="append-1",
            expected_revision=1,
            event_id="evt-2",
            source_order=2,
        )
        assert retry.status_code == 200
        assert retry.json() == {
            "case_id": case_id,
            "result_revision": 2,
            "idempotent_replay": True,
        }

        current = client.get(f"/cases/{case_id}")
        assert current.status_code == 200
        assert current.json()["revision"] == 3
        assert len(current.json()["events"]) == 3


def test_same_append_key_with_changed_payload_conflicts(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))

    with TestClient(app) as client:
        bootstrap(client)
        case_id = create_case(client).json()["case_id"]

        assert (
            append(
                client,
                case_id,
                key="same-append",
                expected_revision=1,
                event_id="evt-2",
                source_order=2,
            ).status_code
            == 200
        )

        changed = append(
            client,
            case_id,
            key="same-append",
            expected_revision=1,
            event_id="evt-changed",
            source_order=3,
        )
        assert changed.status_code == 409
        assert changed.json()["detail"]["code"] == "idempotency_conflict"


def test_stale_revision_fails_without_mutating_case(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))

    with TestClient(app) as client:
        bootstrap(client)
        case_id = create_case(client).json()["case_id"]

        response = append(
            client,
            case_id,
            key="stale",
            expected_revision=2,
            event_id="evt-2",
            source_order=2,
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "revision_conflict"

        current = client.get(f"/cases/{case_id}").json()
        assert current["revision"] == 1
        assert len(current["events"]) == 1


def test_duplicate_event_id_or_order_fails_without_revision_change(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))

    with TestClient(app) as client:
        bootstrap(client)
        case_id = create_case(client).json()["case_id"]

        duplicate_id = append(
            client,
            case_id,
            key="dup-id",
            expected_revision=1,
            event_id="evt-1",
            source_order=2,
        )
        assert duplicate_id.status_code == 409
        assert duplicate_id.json()["detail"]["code"] == "event_id_conflict"

        duplicate_order = append(
            client,
            case_id,
            key="dup-order",
            expected_revision=1,
            event_id="evt-2",
            source_order=1,
        )
        assert duplicate_order.status_code == 409
        assert duplicate_order.json()["detail"]["code"] == "source_order_conflict"

        current = client.get(f"/cases/{case_id}").json()
        assert current["revision"] == 1
        assert len(current["events"]) == 1


def test_whole_case_twenty_event_boundary_and_rejection(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))

    initial = create_body()
    initial["events"] = [
        {
            "event_id": f"evt-{index}",
            "channel": "sms",
            "text": "x",
            "source_order": index,
        }
        for index in range(1, 20)
    ]

    with TestClient(app) as client:
        bootstrap(client)
        created = create_case(client, body=initial)
        assert created.status_code == 201
        case_id = created.json()["case_id"]

        twentieth = append(
            client,
            case_id,
            key="twentieth",
            expected_revision=1,
            event_id="evt-20",
            source_order=20,
            text="x",
        )
        assert twentieth.status_code == 200
        assert twentieth.json()["result_revision"] == 2

        twenty_first = append(
            client,
            case_id,
            key="twenty-first",
            expected_revision=2,
            event_id="evt-21",
            source_order=21,
            text="x",
        )
        assert twenty_first.status_code == 422
        assert twenty_first.json()["detail"]["code"] == "event_limit_exceeded"

        current = client.get(f"/cases/{case_id}").json()
        assert current["revision"] == 2
        assert len(current["events"]) == 20


def test_whole_case_character_limit_rejection_rolls_back(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))

    body = create_body(text="x" * 11_960)
    body["payment_context"] = {
        "stated_purpose": "p",
        "recipient_reference": "r",
    }

    with TestClient(app) as client:
        bootstrap(client)
        created = create_case(client, body=body)
        assert created.status_code == 201
        case_id = created.json()["case_id"]

        accepted = append(
            client,
            case_id,
            key="chars-ok",
            expected_revision=1,
            event_id="evt-2",
            source_order=2,
            text="y" * 38,
        )
        assert accepted.status_code == 200

        rejected = append(
            client,
            case_id,
            key="chars-too-many",
            expected_revision=2,
            event_id="evt-3",
            source_order=3,
            text="z",
        )
        assert rejected.status_code == 422
        assert rejected.json()["detail"]["code"] == "content_limit_exceeded"

        current = client.get(f"/cases/{case_id}").json()
        assert current["revision"] == 2
        assert len(current["events"]) == 2


def test_decimal_value_is_preserved_without_float_storage(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    amount = "1234567890.123456789"

    with TestClient(app) as client:
        bootstrap(client)
        created = create_case(client, body=create_body(amount=amount))
        case_id = created.json()["case_id"]

        retrieved = client.get(f"/cases/{case_id}")
        assert retrieved.status_code == 200
        assert retrieved.json()["payment_context"]["amount"] == amount

        with app.state.database.session_factory() as session:
            stored = session.get(Case, case_id)
            assert stored is not None
            assert stored.amount_decimal == amount
            assert isinstance(stored.amount_decimal, str)


def test_idempotency_keys_are_isolated_across_owners_and_cases(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))

    with TestClient(app) as owner_a, TestClient(app) as owner_b:
        bootstrap(owner_a)
        bootstrap(owner_b)

        create_a = create_case(owner_a, key="shared-key")
        create_b = create_case(owner_b, key="shared-key")
        assert create_a.status_code == 201
        assert create_b.status_code == 201
        assert create_a.json()["case_id"] != create_b.json()["case_id"]

        case_a2 = create_case(owner_a, key="second-case").json()["case_id"]

        first_append = append(
            owner_a,
            create_a.json()["case_id"],
            key="append-shared",
            expected_revision=1,
            event_id="evt-a",
            source_order=2,
        )
        second_append = append(
            owner_a,
            case_a2,
            key="append-shared",
            expected_revision=1,
            event_id="evt-b",
            source_order=2,
        )
        assert first_append.status_code == 200
        assert second_append.status_code == 200


def test_retry_after_delete_does_not_recreate_or_replay_private_case(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))

    with TestClient(app) as client:
        bootstrap(client)
        original_body = create_body()
        created = create_case(client, key="create-delete", body=original_body)
        case_id = created.json()["case_id"]

        assert client.delete(f"/cases/{case_id}", headers=HEADERS).status_code == 204

        retry = create_case(client, key="create-delete", body=original_body)
        assert retry.status_code == 409
        assert retry.json()["detail"]["code"] == "idempotency_resource_deleted"

        with app.state.database.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(Case)) == 0
            record = session.scalar(
                select(IdempotencyRecord).where(IdempotencyRecord.request_key == "create-delete")
            )
            assert record is not None
            assert record.target_case_id is None
            assert record.resource_deleted is True
