# ScamFlow AI

### Before-You-Pay Safety Copilot

ScamFlow AI helps people inspect suspicious messages, call transcripts, and
payment requests **before sending money**. It preserves the original conversation,
tracks how risk signals develop over time, and links every finding back to the
exact submitted evidence.

[Open the hosted development demo](https://scamflow-ai-production.up.railway.app)
· [View the completion report](docs/LOCAL_MVP_COMPLETION_REPORT.md)
· [Check service health](https://scamflow-ai-production.up.railway.app/health)

> [!IMPORTANT]
> The current detector is an explicitly labelled deterministic development mock.
> It is **not real AI inference**, a fraud guarantee, or a substitute for advice
> from a bank, payment provider, or law-enforcement authority.

## Why ScamFlow AI?

Scam attempts often become dangerous through a sequence of messages rather than
one obvious keyword. ScamFlow AI is designed around that progression:

1. A user consents and submits the exact interaction and payment context.
2. The server stores an ordered, revisioned evidence timeline.
3. An extractor identifies traceable observations rather than issuing a verdict.
4. Contextual rules assess combinations such as authority, coercion, secrecy,
   isolation, advance-payment requests, and recipient mismatch.
5. The result links back to exact source excerpts and suggests a cautious next
   step.
6. New evidence creates a new revision, allowing reassessment without rewriting
   the original record.

The MVP currently demonstrates two scam families:

- **Digital Arrest** — authority impersonation, investigation allegations,
  coercion, secrecy, isolation, and “verification” transfer requests.
- **Fake Refund** — claimed refunds combined with advance fees, sensitive
  credential requests, remote access, excess-refund repayment, or recipient
  mismatch.

A keyword alone is never treated as proof of a scam. Legitimate refund language,
negation, and quoted warnings are included as controls.

## What is implemented

- Consent-based case intake with optional payment amount and recipient context.
- Ordered conversation timeline for SMS, WhatsApp, call transcripts, email, and
  other text.
- Incremental synthetic demos that reveal and assess one message at a time.
- Four explicit assessment states with no invented probability score.
- Exact quote-to-source highlighting, including emoji and combining characters.
- Append-and-reassess workflow with current versus historical result labelling.
- Persisted alert memory that suppresses unchanged warnings while preserving
  material escalations and prior warnings after extraction failures.
- Account roles (`user`, `reviewer`, `admin`) with Argon2 password hashing and
  protected HttpOnly sessions in production. Anonymous sessions remain local-only.
- Revision control, idempotent mutations, concurrency guards, and atomic
  assessment persistence.
- Hard case deletion with confirmation.
- Replaceable real-provider adapter contract with safe failure behaviour and no
  automatic fallback to the development mock.
- Responsive React interface and same-origin FastAPI deployment.

## Assessment states

| State | Meaning |
| --- | --- |
| **High-risk indicators** | A strong contextual combination of suspicious tactics was found. |
| **Needs clarification or review** | Some concerning signals exist, but the available evidence is incomplete. |
| **No strong indicators** | The supported detector did not find a strong combination. This does **not** mean “safe.” |
| **Unable to assess** | The input is unsupported, invalid, or the assessment process failed. This is never treated as low risk. |

## Try the demo

Open the [hosted development demo](https://scamflow-ai-production.up.railway.app)
and use **Incremental synthetic replay**:

- **Digital Arrest** progresses from an authority claim to a high-risk coercive
  transfer pattern.
- **Fake Refund** demonstrates a refund claim followed by an advance-payment
  request.
- **Assessment failure** shows the visible unable-to-assess journey for
  unsupported content.

You can highlight linked evidence, reveal the next message, append a
clarification, reassess the current revision, reload the case, and delete it.
Demo data uses the same case and assessment APIs as manual input.

## Architecture

~~~text
React + TypeScript browser
        │
        ▼
Same-origin FastAPI API
        │
        ├── session, consent, CSRF and input validation
        ├── owner-scoped PostgreSQL (production) or SQLite (local) case evidence
        └── immutable revision snapshot
                    │
                    ▼
            configured extractor
                    │
                    ▼
      schema + exact-evidence validation
                    │
                    ▼
 Digital Arrest + Fake Refund contextual rules
                    │
                    ▼
 access/revision/idempotency commit guard
                    │
                    ▼
 atomic assessment + alert-memory persistence
                    │
                    ▼
       evidence-linked user response
~~~

Extraction runs outside the database write transaction. Before saving a result,
the backend rechecks session validity, ownership, case existence, expiry, evidence
revision, and idempotency state.

## Technology

| Layer | Technology |
| --- | --- |
| Frontend | React 19, TypeScript 6, Vite 8 |
| Backend | Python 3.11, FastAPI, Pydantic |
| Persistence | SQLAlchemy + Alembic, PostgreSQL in production, SQLite locally |
| Testing | Pytest, Vitest, React Testing Library, Playwright |
| Packaging | Multi-stage Docker build, Docker Compose |
| Hosting | Railway, one application replica with a persistent /data volume |

## Run locally

### Prerequisites

- Python 3.11
- Node.js 24 or a compatible current Node release
- npm

### Same-origin local build

From the repository root:

~~~bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'

cd frontend
npm ci
npm run build
cd ..

python -m uvicorn backend.scamflow.app:app --host 127.0.0.1 --port 8000
~~~

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

### Frontend development mode

Start the API:

~~~bash
SCAMFLOW_TRUSTED_ORIGIN=http://127.0.0.1:5173 \
  .venv/bin/python -m uvicorn backend.scamflow.app:app \
  --host 127.0.0.1 --port 8000
~~~

In another terminal:

~~~bash
cd frontend
npm ci
npm run dev
~~~

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). Vite forwards same-origin
API requests to the local backend.

### Docker Compose

~~~bash
docker compose up --build
~~~

The Compose configuration runs one application instance and stores local SQLite
in a named volume at /data/scamflow.sqlite3. Railway production uses PostgreSQL
through `DATABASE_URL` and applies the checked-in Alembic head.

## Configuration

Settings use the **SCAMFLOW_** prefix. Local .env files are intentionally not
loaded automatically; export values through the shell or deployment environment.
See [.env.example](.env.example) for a secret-free example.

| Variable | Default | Purpose |
| --- | --- | --- |
| SCAMFLOW_ENVIRONMENT | development | development, test, or production |
| SCAMFLOW_LOG_LEVEL | INFO | Application log level |
| SCAMFLOW_DATABASE_PATH | data/scamflow.sqlite3 | SQLite database location |
| DATABASE_URL | unset | Railway PostgreSQL connection string in production |
| SCAMFLOW_SQLITE_BUSY_TIMEOUT_MS | 5000 | SQLite contention timeout |
| SCAMFLOW_SESSION_TTL_SECONDS | 86400 | Anonymous session lifetime |
| SCAMFLOW_CASE_RETENTION_SECONDS | 86400 | Case access lifetime |
| SCAMFLOW_ASSESSMENT_TIMEOUT_SECONDS | 2.0 | Extractor timeout |
| SCAMFLOW_EXTRACTOR_MODE | rules | rules, provider, or none |
| SCAMFLOW_MAX_REQUEST_BYTES | 1000000 | Maximum API request body |
| SCAMFLOW_RATE_LIMIT_PER_MINUTE | 60 | Per-process API request budget |
| SCAMFLOW_AUTH_RATE_LIMIT_PER_MINUTE | 10 | Login attempt budget |
| SCAMFLOW_CLEANUP_INTERVAL_SECONDS | 3600 | Expired-case cleanup interval |
| SCAMFLOW_TRUSTED_ORIGIN | http://127.0.0.1:8000 | Exact accepted browser origin |
| SCAMFLOW_SECURE_COOKIES | environment-derived | Require Secure session cookies |
| PORT | 8000 | Container/deployment listener |

Production mode requires an HTTPS trusted origin and Secure cookies. Rules-only
mode is deterministic, credential-free, and clearly disclosed in assessments;
an optional provider adapter can be configured without silently falling back to
the development mock.

## API

| Method | Route | Purpose |
| --- | --- | --- |
| GET | /health | Exact liveness response: {"status":"ok"} |
| GET | /ready | Database readiness response |
| POST | /auth/register | Register and start a user session |
| POST | /auth/login | Authenticate a user session |
| POST | /auth/logout | Revoke the current session |
| GET | /auth/me | Return the signed-in account and role |
| POST | /session | Create or reuse a local anonymous owner session |
| POST | /cases | Create a consented case and initial evidence |
| GET | /cases/{case_id} | Read an owned, unexpired case |
| POST | /cases/{case_id}/events | Append revision-controlled evidence |
| POST | /cases/{case_id}/assess | Assess one exact persisted revision |
| GET | /cases/{case_id}/assessments/latest | Read the latest owned assessment |
| DELETE | /cases/{case_id} | Hard-delete the owned case and derived records |

Mutation routes require the owner session, an exact trusted Origin,
**X-ScamFlow-CSRF: 1**, and an idempotency key. Inaccessible, expired, and
nonexistent cases are intentionally indistinguishable.

## Security and privacy boundaries

- Evidence is accepted only after explicit consent.
- The opaque owner token is hashed server-side and sent only in an HttpOnly,
  SameSite=Strict cookie; production and hosted HTTPS use Secure cookies.
- The browser stores no session token, provider credential, or private evidence
  in local/session storage.
- Exact-Origin and custom-header CSRF protections cover mutations.
- Extractor output is treated as untrusted and must match exact event IDs, spans,
  offsets, and quotes before persistence.
- Evidence is rendered as text, never through dangerouslySetInnerHTML.
- Another anonymous owner receives 404 rather than learning whether a case
  exists.
- Safe API envelopes do not expose SQL, raw invalid model output, cookies, or
  internal exception details.

Submitted evidence is stored unencrypted at the application layer unless the
selected database and host provide encryption. PostgreSQL is the production
datastore; host security, backups, retention enforcement, and incident response
remain operator responsibilities.

## Verification

The latest local verification on 2026-10-25 completed with these results:

| Check | Result |
| --- | --- |
| Backend test suite | 161 passed |
| Ruff | Passed |
| Python dependency check | No broken requirements |
| Frontend unit tests | 6 files, 51 tests passed |
| TypeScript typecheck | Passed |
| Production frontend build | Passed |
| npm audit | Failed: 6 development-toolchain advisories; production dependency audit remains separate |
| Chromium E2E | 3 tests passed |
| Same-key append stress check | Not rerun in this release pass |
| Development evaluation fixtures | 3/3 deterministic mock conformance |
| Hosted browser smoke | Passed: synthetic registration, sign-in state, rules-only case submission and evidence-backed assessment |
| Railway deployment health | Passed: application and PostgreSQL services online; `/health` and `/ready` returned 200; Alembic initial schema applied |

Run the checks:

~~~bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/python -m pip check
.venv/bin/python evaluation/run_development_eval.py
docker compose config --quiet

cd frontend
npm ci
npm run typecheck
npm test
npm run build
npm audit --audit-level=high
npx playwright install chromium
npm run test:e2e
~~~

The evaluation fixtures measure deterministic mock contract conformance only.
They are not real-model recall, precision, or accuracy results.

## Deployment

Railway beta topology uses a PostgreSQL service and one same-origin application
service. Set `DATABASE_URL`, `SCAMFLOW_ENVIRONMENT=production`,
`SCAMFLOW_TRUSTED_ORIGIN` to the exact HTTPS domain, and the remaining names in
[.env.example](.env.example) through Railway variables only. The container runs
the checked-in Alembic head before serving traffic and exposes `/health` for
liveness and `/ready` for database readiness. The verified beta deployment is
[scamflow-ai-production.up.railway.app](https://scamflow-ai-production.up.railway.app).

Follow [the deployment runbook](docs/DEPLOYMENT_RUNBOOK.md) and keep
[incident/rollback notes](docs/INCIDENT_ROLLBACK.md) with the release record.
Do not apply the legacy `.railway/railway.ts` plan without reviewing its diff;
it describes the old SQLite volume topology.

## Project structure

~~~text
backend/scamflow/       FastAPI app, security, persistence, extraction and rules
backend/tests/          Backend, race, migration and provider-contract tests
frontend/src/           React application, API client and unit tests
frontend/e2e/           Playwright browser journeys
evaluation/             Synthetic development evaluation runner and scenarios
.railway/               Railway infrastructure-as-code
docs/                   Consolidated implementation and verification report
Dockerfile              Production-style same-origin container build
compose.yaml            Single-instance local container setup
~~~

## Current limitations

- The detector is a small, disclosed development mock with limited vocabulary.
- No real model provider, API key, live inference, or production accuracy claim
  is included.
- Optional real-provider credentials and model evaluation remain operator choices;
  rules-only mode is the safe default.
- A shared external rate limiter, backup/restore drill, and assistive-technology
  validation remain deployment responsibilities.
- Production monitoring, backup/restore drills, and mobile assistive-technology
  validation remain pending.
- **No strong indicators** is not a safety guarantee, and **unable to assess** is
  not a reassuring result.

## Roadmap

1. Approve a real provider after reviewing privacy, regional, and data-use terms.
2. Implement the injected provider transport with server-side secret loading.
3. Validate malformed output, timeout, injection, evidence traceability, and
   explicit no-fallback behaviour against a mocked transport.
4. Build a genuinely independent held-out scenario-family set and measure recall,
   false positives, first-warning stage, repeated alerts, missed escalations,
   quote validity, latency, and token use.
5. Add authenticated human review, retention automation, monitoring, and tested
   backup/restore operations before any production claim.

## Design attribution

The responsive interface was independently adapted from the general navigation
and card idiom associated with the Sneat dashboard reference. The repository's
historical **sneat template.zip** was inspected without extraction; no template
source, script, asset, symlink, or licensed file was copied into the application.

For implementation details, exact test observations, known warnings, and blocked
checks, read the
[local MVP completion report](docs/LOCAL_MVP_COMPLETION_REPORT.md).
