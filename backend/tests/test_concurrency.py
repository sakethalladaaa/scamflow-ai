from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from backend.scamflow.api_schemas import AppendEventsRequest, CreateCaseRequest
from backend.scamflow.database import create_database, initialize_schema
from backend.scamflow.schemas import PaymentContext, ScamEvent
from backend.scamflow.services import (
    ServiceError,
    append_events,
    authenticate_owner,
    bootstrap_session,
    create_case,
    get_case,
)
from backend.scamflow.settings import Environment, Settings


def make_database(tmp_path: Path):
    settings = Settings(
        environment=Environment.TEST,
        database_path=tmp_path / "concurrency.sqlite3",
        sqlite_busy_timeout_ms=5_000,
    )
    database = create_database(settings)
    initialize_schema(database)
    return settings, database


def prepare_case(
    tmp_path: Path,
    *,
    initial_event_count: int = 1,
):
    settings, database = make_database(tmp_path)
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
                event_id=f"evt-{index}",
                channel="sms",
                text="x",
                source_order=index,
            )
            for index in range(1, initial_event_count + 1)
        ],
    )
    created = create_case(
        database,
        settings,
        owner_id=owner.id,
        request_key="create",
        request=request,
        now=now,
    )
    return database, owner.id, created.case_id, now


def run_append(
    barrier: Barrier,
    *,
    database,
    owner_id: str,
    case_id: str,
    key: str,
    expected_revision: int,
    event_id: str,
    source_order: int,
    now: int,
):
    request = AppendEventsRequest(
        expected_revision=expected_revision,
        events=[
            ScamEvent(
                event_id=event_id,
                channel="sms",
                text="concurrent",
                source_order=source_order,
            )
        ],
    )
    barrier.wait()
    try:
        result = append_events(
            database,
            owner_id=owner_id,
            case_id=case_id,
            request_key=key,
            request=request,
            now=now,
        )
        return ("ok", result.result_revision, result.idempotent_replay)
    except ServiceError as exc:
        return ("error", exc.status_code, exc.code)


def test_two_same_revision_appends_cannot_both_mutate(tmp_path: Path) -> None:
    database, owner_id, case_id, now = prepare_case(tmp_path)
    barrier = Barrier(2)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    run_append,
                    barrier,
                    database=database,
                    owner_id=owner_id,
                    case_id=case_id,
                    key="append-a",
                    expected_revision=1,
                    event_id="evt-a",
                    source_order=2,
                    now=now,
                ),
                executor.submit(
                    run_append,
                    barrier,
                    database=database,
                    owner_id=owner_id,
                    case_id=case_id,
                    key="append-b",
                    expected_revision=1,
                    event_id="evt-b",
                    source_order=3,
                    now=now,
                ),
            ]
            results = [future.result() for future in futures]

        assert sum(result[0] == "ok" for result in results) == 1
        assert (
            sum(
                result[0] == "error"
                and result[1] == 409
                and result[2] in {"revision_conflict", "write_conflict"}
                for result in results
            )
            == 1
        )

        case, events = get_case(
            database,
            owner_id=owner_id,
            case_id=case_id,
            now=now,
        )
        assert case.revision == 2
        assert len(events) == 2
    finally:
        database.dispose()


def test_concurrent_same_key_is_one_logical_mutation(tmp_path: Path) -> None:
    database, owner_id, case_id, now = prepare_case(tmp_path)
    barrier = Barrier(2)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    run_append,
                    barrier,
                    database=database,
                    owner_id=owner_id,
                    case_id=case_id,
                    key="same-key",
                    expected_revision=1,
                    event_id="evt-2",
                    source_order=2,
                    now=now,
                )
                for _ in range(2)
            ]
            results = [future.result() for future in futures]

        assert all(result[0] == "ok" for result in results)
        assert sorted(result[2] for result in results) == [False, True]
        assert {result[1] for result in results} == {2}

        case, events = get_case(
            database,
            owner_id=owner_id,
            case_id=case_id,
            now=now,
        )
        assert case.revision == 2
        assert len(events) == 2
    finally:
        database.dispose()


def test_concurrent_near_limit_appends_never_exceed_twenty(tmp_path: Path) -> None:
    database, owner_id, case_id, now = prepare_case(
        tmp_path,
        initial_event_count=19,
    )
    barrier = Barrier(2)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    run_append,
                    barrier,
                    database=database,
                    owner_id=owner_id,
                    case_id=case_id,
                    key="limit-a",
                    expected_revision=1,
                    event_id="evt-20-a",
                    source_order=20,
                    now=now,
                ),
                executor.submit(
                    run_append,
                    barrier,
                    database=database,
                    owner_id=owner_id,
                    case_id=case_id,
                    key="limit-b",
                    expected_revision=1,
                    event_id="evt-20-b",
                    source_order=21,
                    now=now,
                ),
            ]
            results = [future.result() for future in futures]

        assert sum(result[0] == "ok" for result in results) == 1
        assert sum(result[0] == "error" for result in results) == 1

        case, events = get_case(
            database,
            owner_id=owner_id,
            case_id=case_id,
            now=now,
        )
        assert case.revision == 2
        assert len(events) == 20
    finally:
        database.dispose()
