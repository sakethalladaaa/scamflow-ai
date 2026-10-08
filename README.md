# ScamFlow AI — Before-You-Pay Safety Copilot

ScamFlow AI is a consent-based application for analysing user-submitted
messages, transcripts, and payment context for suspicious financial-scam
progression.

Initial target scenarios:

- Digital Arrest
- Fake Refund

## Current scope — local and hosted development MVP

The repository now contains a locally runnable modular monolith:

- the preserved Phase 1–3 FastAPI case and Digital Arrest pipeline;
- a small Fake Refund rules extension based on suspicious combinations, not keywords alone;
- persisted alert memory with retry suppression, material escalation, and prior-warning retention;
- a React + TypeScript + Vite browser interface;
- synthetic incremental demos and a development-only evaluation runner;
- a replaceable real-provider contract adapter with no live provider calls;
- same-origin production build serving plus Docker and Compose packaging.

Every browser result produced by the deterministic extractor is visibly labelled
**“Development mock — not real AI inference.”** The hosted development build is
available at [scamflow-ai-production.up.railway.app](https://scamflow-ai-production.up.railway.app).
It is a pipeline demonstration, not a production AI service or a real-model
accuracy claim.

## Hosted development deployment

Railway currently runs one application replica with a 500 MB persistent volume
mounted at `/data`. HTTPS, an exact trusted origin, Secure cookies, and the
`/health` deployment health check are enabled. The hosted build deliberately uses
the disclosed deterministic development extractor; it has no model credentials
and makes no paid provider calls.

Railway infrastructure is captured in `.railway/railway.ts`. From an already
linked and authenticated Railway checkout:

    cd .railway && npm ci && cd ..
    railway config plan
    railway up --service scamflow-ai --ci

Review the current Railway plan and account usage before applying infrastructure
changes or redeploying.

## Quick local start

Backend terminal:

    SCAMFLOW_TRUSTED_ORIGIN=http://127.0.0.1:5173 .venv/bin/python -m uvicorn backend.scamflow.app:app --host 127.0.0.1 --port 8000

Frontend terminal (same-origin API calls are forwarded by Vite):

    cd frontend
    npm ci
    npm run dev

Open `http://127.0.0.1:5173`. The explicit trusted origin in the backend command
is required for the Vite proxy. The default `http://127.0.0.1:8000` is intended
for the same-origin production build.

For a production-style same-origin local build:

    cd frontend && npm ci && npm run build && cd ..
    .venv/bin/python -m uvicorn backend.scamflow.app:app --host 127.0.0.1 --port 8000

Then open `http://127.0.0.1:8000`.

Container start:

    docker compose up --build

The Compose volume stores SQLite at `/data/scamflow.sqlite3` outside the image.
SQLite packaging assumes exactly one application instance.

## Browser interface

The UI supports consented intake, exact ordered evidence, optional payment context,
assessment and reassessment, exact excerpt-to-source highlighting, historical result
labelling, revisioned clarification, deletion confirmation, and isolated synthetic
demo replay. It never uses `dangerouslySetInnerHTML`, never stores session secrets or
provider keys in browser storage, and converts Python code-point evidence offsets to
JavaScript UTF-16 offsets before highlighting.

The visual shell independently adapts the navigation/card idiom associated with the
requested Sneat template. The existing GitHub history contains `sneat template.zip`
in commit `42e29dad480175a977b5b0a87d91fc85a74cfb58`. The archive was inspected without
extraction (including paths, notices/manifests, and symlink entries); no template
source, script, asset, or symlink was copied into the application.

## Development checks

    .venv/bin/python -m pytest
    .venv/bin/ruff check .
    cd frontend && npm run typecheck && npm test && npm run build
    cd frontend && npx playwright install chromium && npm run test:e2e
    .venv/bin/python evaluation/run_development_eval.py

The evaluation command reports deterministic fixture conformance only. Development
and held-out scenario family files are separate under `evaluation/scenarios/`.

## Phase 3 foundation (preserved)

Phase 3 implements the **Digital Arrest backend assessment pipeline using a
disclosed deterministic development mock extractor**.

Implemented flow:

    owned, unexpired case
        -> fixed revision snapshot
        -> development mock extraction
        -> strict evidence validation
        -> deterministic Digital Arrest policy
        -> revision-safe persisted assessment
        -> owner-accessible assessment result

The development mock exists to validate pipeline correctness with controlled
synthetic inputs. It is **not production AI** and no real-world scam-detection
accuracy claim is made.

Phase 1/2 case-management behavior remains in place:

- FastAPI application factory
- validated `SCAMFLOW_*` settings
- exact `GET /health` liveness contract
- anonymous owner sessions
- HttpOnly, SameSite=Strict cookies
- Secure cookies in production
- exact-origin CSRF protection
- explicit consent before storage
- SQLite/SQLAlchemy persistence
- owner-scoped access
- ordered evidence events
- optimistic case revisions
- idempotent create/append operations
- hard case deletion
- session/case expiry enforcement
- safe error envelopes
- file-backed concurrency tests

## Python version

Use Python **3.11**.

Verified development interpreter:

    Python 3.11.16

## Setup

Create the virtual environment:

    /opt/homebrew/bin/python3.11 -m venv .venv

Install runtime and development dependencies:

    .venv/bin/python -m pip install -e '.[dev]'

Direct dependency versions are pinned in `pyproject.toml`.

Runtime dependencies:

- FastAPI 0.142.2
- Uvicorn 0.54.0
- Pydantic 2.13.5
- pydantic-settings 2.15.0
- SQLAlchemy 2.1.3

Development dependencies:

- pytest 9.1.1
- httpx 0.28.1
- Ruff 0.16.10

Phase 3 adds no new external dependency.

## Configuration

Settings use the `SCAMFLOW_` environment-variable prefix.

Local `.env` files are intentionally **not loaded automatically**.

Implemented settings:

    SCAMFLOW_ENVIRONMENT=development
    SCAMFLOW_LOG_LEVEL=INFO
    SCAMFLOW_DATABASE_PATH=data/scamflow.sqlite3
    SCAMFLOW_SQLITE_BUSY_TIMEOUT_MS=5000
    SCAMFLOW_SESSION_TTL_SECONDS=86400
    SCAMFLOW_CASE_RETENTION_SECONDS=86400
    SCAMFLOW_ASSESSMENT_TIMEOUT_SECONDS=2.0
    SCAMFLOW_TRUSTED_ORIGIN=http://127.0.0.1:8000

Supported environments:

- `development`
- `test`
- `production`

Production requires an HTTPS trusted origin and uses Secure session cookies.
`SCAMFLOW_SECURE_COOKIES=true` can also require Secure cookies for an HTTPS-hosted
development demonstration without enabling a real production extractor.

The built-in `DevelopmentMockExtractor` is automatically available only in
development/test. Passing that mock explicitly to a production application is
rejected. A production application without a configured real extractor can
start, but assessment requests fail safely with `assessment_unavailable`.

No AWS or model credentials are required in Phase 3.

## Database

The development database defaults to:

    data/scamflow.sqlite3

SQLite connections enable:

- foreign-key enforcement
- bounded busy timeout
- WAL mode

SQLite remains a single-writer datastore and is currently intended for the
single-server prototype.

### Schema setup and migration boundary

`initialize_schema()` currently uses SQLAlchemy `create_all()`.

For Phase 3 the schema change is **additive only**: new assessment tables are
created while existing Phase 2 tables and rows remain intact.

`create_all()` does **not** migrate existing columns. Any future change that
adds, removes, renames, or changes an existing column must use an explicit
migration mechanism rather than deleting or recreating the database.

Tests explicitly simulate an existing Phase 2 database and verify that Phase 3
tables can be added without losing an existing case.

## Data model

### Anonymous owner session

Stored server-side:

- internal owner ID
- SHA-256 hash of the opaque session token
- creation time
- expiry time

The raw session token is not stored in the database and is never returned in
JSON.

### Case

Stored fields include:

- server-generated case ID
- owner reference
- consent version
- server-recorded consent time
- stated payment purpose
- optional exact decimal amount
- optional recipient reference
- current evidence revision
- creation/update timestamps
- expiry timestamp

Generating an assessment does **not** increment the case evidence revision.

### Event

Stored fields include:

- internal database ID
- case reference
- client event identifier
- channel
- original evidence text
- explicit `source_order`
- server ingestion time

Original text is preserved exactly, including whitespace, newlines and Unicode.

### Assessment

Each persisted assessment stores:

- assessment ID
- case and owner references
- assessed case revision
- assessment state
- stable reason codes
- concise explanation
- tactics and relationships used by the policy
- suggested next action
- limitations
- extraction mode/version
- Digital Arrest rule version
- extraction schema version
- creation timestamp

### Assessment evidence

Only **validated evidence spans** are persisted.

Each evidence row stores:

- assessment reference
- source event identifier
- source order
- tactic
- exact quote
- start/end offsets
- evidence context

Invalid raw extractor payloads are not persisted.

### Idempotency records

Phase 2 mutation idempotency records remain unchanged.

Assessment requests have separate idempotency metadata containing request
fingerprints and persisted-result references, but not raw submitted evidence or
raw extractor payloads.

When a case is deleted, derived assessments/evidence are deleted and assessment
idempotency records are scrubbed to safe tombstones.

## Extraction contract

The extractor receives an immutable snapshot containing:

- case ID
- exact case revision
- ordered persisted events
- event identifiers
- payment context

The extractor returns observations, not a final scam verdict.

Supported Phase 3 observation types:

- `authority_claim`
- `investigation_allegation`
- `threat_coercion`
- `secrecy`
- `isolation`
- `verification_transfer_request`

Each observation contains:

- tactic
- source event identifier
- exact quote
- start offset
- end offset
- context

Supported evidence contexts:

- `asserted`
- `negated`
- `quoted_warning`

No confidence or probability score is invented.

## Evidence offset semantics

Evidence offsets are:

- zero-based
- end-exclusive
- Python Unicode string indices
- measured against the exact original stored event text

Validation requires:

    quote == original_text[start:end]

Offsets are not measured against normalized text, UTF-8 bytes, or model tokens.

The JavaScript frontend converts Python code-point offsets before highlighting.
JavaScript string indexing uses UTF-16 code units, so Python and JavaScript
indices are not guaranteed to be identical for characters outside the BMP.

## Strict evidence validation

All extractor output is treated as untrusted.

The validator checks:

- extraction schema
- supported tactic/context values
- event membership in the fixed snapshot
- strict integer offsets
- booleans rejected as offsets
- valid non-empty ranges
- exact quote equality
- bounded quote length
- bounded observation count
- deterministic duplicate handling

Invalid evidence is never fuzzy-repaired.

Malformed or untraceable extraction produces an explicit
`unable_to_assess` assessment and is never converted into a reassuring
`no_strong_indicators` result.

Exact span validation proves traceability to source text, not semantic
correctness.

## Development mock extractor

Phase 3 includes:

    development_mock / digital-arrest-patterns-v1

It is intentionally small and deterministic.

Its vocabulary currently recognizes selected synthetic phrases representing:

- official-authority claims
- investigation allegations
- coercive threats
- secrecy requests
- call isolation
- verification/resolution transfer requests

It also recognizes a small disclosed benign vocabulary so the pipeline can
distinguish a successfully processed empty observation set from unsupported
input.

Unknown content is explicitly returned as unsupported and becomes:

    unable_to_assess

The mock does not read expected fixture verdicts, held-out labels, client
scenario selections, or unrevealed messages.

The mock is for pipeline development only.

## Digital Arrest decision policy

Rule version:

    digital-arrest-v1

The policy is deterministic and transparent; it does not produce a probability
score.

### Decision table

| Active validated context | State |
| --- | --- |
| Authority claim alone | `no_strong_indicators` |
| Ordinary supported urgency/procedure without stronger scam context | `no_strong_indicators` |
| Authority + investigation but incomplete stronger context | `needs_clarification_or_review` |
| Threat, secrecy, isolation, or transfer demand without the complete high-risk combination | `needs_clarification_or_review` |
| Authority + coercion + secrecy and/or isolation | `high_risk_indicators` |
| Authority + coercion + verification/resolution transfer demand | `high_risk_indicators` |
| Negated or quoted-warning tactics only | not treated as active threat evidence |
| Unsupported mock input | `unable_to_assess` |
| Malformed/invalid extraction | `unable_to_assess` |
| Extractor failure or timeout | `unable_to_assess` |

Rules can combine tactics across ordered messages or within one message. They do
not require one rigid scam sequence.

## Assessment states

The stable states are:

- `high_risk_indicators`
- `needs_clarification_or_review`
- `no_strong_indicators`
- `unable_to_assess`

Important interpretation:

- `no_strong_indicators` is not a safety guarantee.
- `unable_to_assess` is not a low-risk result.
- an assessment does not authenticate the sender.
- an assessment does not conclusively prove criminal activity.

## API routes

### `GET /health`

Exact liveness response:

    {"status":"ok"}

This does not claim AI, database, or cloud readiness.

### `POST /session`

Creates or reuses an anonymous owner session.

The opaque token is sent only as the HttpOnly cookie and is never included in
JSON.

### `POST /cases`

Creates a consented case.

Requires:

- valid owner session
- exact Origin
- `X-ScamFlow-CSRF: 1`
- `Idempotency-Key`
- explicit `consent: true`

Success:

- `201 Created`
- initial revision `1`

### `GET /cases/{case_id}`

Returns one owned, unexpired case and ordered events.

Another owner's case, expired case, and nonexistent case are intentionally
indistinguishable and return `404`.

### `POST /cases/{case_id}/events`

Appends new evidence.

Requires:

- valid owner session
- CSRF context
- `Idempotency-Key`
- `expected_revision`

A successful append increments the case revision exactly once.

### `POST /cases/{case_id}/assess`

Assesses one exact persisted case revision.

Request JSON:

    {
      "expected_revision": 1
    }

Requires:

- valid unexpired owner session
- owned unexpired case
- exact Origin
- `X-ScamFlow-CSRF: 1`
- `Idempotency-Key`
- matching `expected_revision`

The server builds the extractor snapshot from persisted evidence. Clients cannot
submit extraction output or a verdict.

The database is not kept in a write transaction while extraction runs.

Before persistence, the service rechecks:

- session validity/expiry
- case existence
- ownership
- case expiry
- case revision
- assessment idempotency state

Validated extraction, assessment, evidence references, and idempotency metadata
are committed atomically.

Generating an assessment does not increment the evidence revision.

Success:

- `200 OK`

The response includes:

- assessment ID
- case ID
- assessed revision
- assessment state
- reason codes
- explanation
- validated evidence
- tactics/relationships used
- suggested next action
- limitations
- extraction mode/version
- rule/schema versions
- timestamp
- `is_current`
- `idempotent_replay`

### `GET /cases/{case_id}/assessments/latest`

Returns the newest persisted assessment for the owned case.

If no assessment exists:

- `404`
- `assessment_not_found`

If evidence has been appended after the assessment, the older assessment remains
historical and is returned with:

    "is_current": false

The API does not silently present an older assessment as current.

### `DELETE /cases/{case_id}`

Hard-deletes the owned case.

Cascade deletion removes:

- events
- assessments
- assessment evidence

Idempotency rows are reduced to safe tombstones so deleted private results cannot
be replayed.

## Assessment idempotency

Assessment keys are scoped by owner and case.

Behavior:

- same key + same request -> same logical persisted assessment
- same key + different request -> `409 idempotency_conflict`
- exact retry can replay the earlier result while access remains authorized
- a replayed historical result retains its original `assessed_revision`
- `is_current` is calculated against the current case revision
- persisted `unable_to_assess` results are replayed with the same key
- a fresh extraction attempt requires a new key
- concurrent identical requests converge to one persisted assessment

## Assessment race guarantees

Tests cover:

- append during extraction -> stale assessment is not committed
- case deletion during extraction -> no orphan assessment
- case expiry during extraction -> no commit/result disclosure
- session expiry during extraction -> no commit/result disclosure
- concurrent identical requests -> one logical persisted assessment
- assessment database failure -> complete rollback

Extraction runs outside the database write transaction.

## Development fixtures

Disclosed synthetic fixtures live at:

    backend/tests/fixtures/digital_arrest_phase3.json

They include:

- family ID
- ordered synthetic events
- payment context
- exact expected observations/spans where applicable
- expected policy states at selected prefixes
- rationale
- provenance
- offset semantics

Expected labels are used only by tests after extraction; they are not supplied
to the mock detector as input.

These fixtures are development data, not a frozen held-out evaluation set.

Independent families remain reserved for later Phase 7/8 evaluation.

## Validation and limits

Supported channels:

- `sms`
- `whatsapp`
- `call_transcript`
- `email`
- `other_text`

Case limits remain:

- maximum 20 events
- maximum 12,000 combined Python string characters

The combined count includes:

- all event text
- stated payment purpose
- recipient reference when present

Payment amounts must be positive finite decimal values.

## Errors and privacy

Expected public errors include:

- `401` missing/invalid/expired session
- `403` CSRF rejection
- `404` inaccessible/expired/nonexistent case or missing assessment
- `409` revision/idempotency/write conflict
- `422` invalid request or case-limit violation
- `503` database or assessment service unavailable

Validation/database errors use safe envelopes and do not expose:

- session tokens
- cookies
- raw invalid extraction payloads
- SQL statements
- private exception details

Extractor timeout/failure is represented as persisted `unable_to_assess`, not
`no_strong_indicators`.

## Run locally

From the repository root:

    .venv/bin/python -m uvicorn backend.scamflow.app:app --host 127.0.0.1 --port 8000

## Tests

Run the complete backend suite:

    .venv/bin/python -m pytest backend/tests

## Lint

    .venv/bin/python -m ruff check backend

## Formatting

Check formatting:

    .venv/bin/python -m ruff format --check backend

## Current limitations and next work

The MVP intentionally does not implement:

- production AI inference or a configured provider transport;
- AWS Bedrock/boto3;
- authenticated human-review and external-reporting workflows;
- background retention cleanup, backup/restore automation, or production
  monitoring;
- a general schema migration framework such as Alembic;
- horizontal database scaling; or
- real-world detection-accuracy claims.

The development mock has a deliberately limited vocabulary and returns
`unable_to_assess` for unknown inputs. The hosted demonstration uses this same
mock and must not be presented as a production detector. Production work requires
an approved real provider, an independent held-out evaluation set, privacy and
retention controls, operational monitoring, and a datastore suitable for the
chosen scale.
