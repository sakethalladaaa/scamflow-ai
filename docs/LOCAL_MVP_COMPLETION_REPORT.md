# ScamFlow AI local MVP completion report

Date: 2026-10-08 (Asia/Kolkata)

## Outcome

A reproducible local MVP is implemented in `/Users/alladasakethsolomon/scamflow-ai`
and its development build is deployed at
`https://scamflow-ai-production.up.railway.app`. It preserves the Phase 1–3
backend and adds the browser experience, Fake Refund rules, persisted alert
memory, explicit additive migration, provider seam, development evaluation
harness, and single-service packaging requested for the MVP milestone.

This is a **development mock**, not real AI inference. No provider credentials
were read and no paid model call was made. Railway hosts one application replica
and a persistent SQLite volume; no AWS, Cloudflare, IAM, EBS, Budgets, or Bedrock
resource was configured.

## Implemented scope

### Browser application

- React 19 + TypeScript + Vite application with a responsive Bootstrap/Sneat-like
  navigation and card layout.
- Explicit consent, validated intake, ordered timeline, optional decimal amount
  and recipient context, append/reassess, current-versus-historical result state,
  and confirmed case deletion.
- All four assessment states are rendered. `no_strong_indicators` is never called
  “Safe”; no probability or confidence score is shown.
- Every assessment panel and global workspace show “Development mock — not real
  AI inference.”
- Exact evidence buttons scroll to and highlight the original source span. Python
  code-point offsets are converted to JavaScript UTF-16 offsets, including emoji,
  combining marks, and repeated text.
- Evidence is rendered as React text nodes; `dangerouslySetInnerHTML` is not used.
- Loading, empty, validation, authorization/server failure, stale/historical, and
  `unable_to_assess` states are visible. Native buttons, labels, form controls,
  focus styles, and disclosure controls are keyboard accessible.
- Mutation buttons are disabled while pending. A logical request retains its
  idempotency key after a lost/failing response and discards it only after a
  successful response. Case/revision request epochs ignore late results.
- Anonymous session secrets remain HttpOnly cookies. The client stores no session
  token or provider key. The selected non-secret case ID is kept in the URL so a
  reload can restore the case without browser storage.
- Synthetic replay creates a normal case, reveals one event per click, and uses
  normal append/assessment routes. Only the revealed prefix is submitted. Reset
  deletes only the tracked demo case and does not rotate the owner session.

### Backend detection and alerts

- Preserved exact health, session, ownership, expiry, case limits, decimal storage,
  ordering, idempotency, hard deletion, fixed-revision extraction, validation,
  assessment atomicity, and historical/current semantics.
- Extended the deterministic extractor with Fake Refund observations for claimed
  refunds, advance fees, sensitive credentials, remote access, excess-refund
  repayment, and recipient mismatch.
- Fake Refund warnings require contextual combinations. A refund keyword alone is
  not high risk. Legitimate refund language, quotation, negation, and warnings are
  controls.
- Unsupported vocabulary and malformed/provider failures remain
  `unable_to_assess`; there is no reassuring fallback.
- Persisted alert policy records one stable result per assessment and one current
  material-warning memory per case. Exact idempotent replays reuse the same alert,
  unchanged warnings are suppressed, changed/escalated warnings are visible, and
  extraction failures preserve and disclose prior warning state.
- Alert rows share the assessment transaction, ownership, revision, concurrency,
  cascade deletion, and rollback boundaries.
- The previously reported same-key append race reproduced. The cause was a narrow
  SQLite visibility sequence where the losing transaction could observe the
  committed event ID/source order before its initial idempotency lookup observed
  the companion record. Bounded fresh-session checks now reconcile revision,
  event-ID, and source-order conflict paths. A subsequent 100-run same-key stress
  check passed.

### Persistence and provider seam

- `schema_migrations` records additive migration `0001_alert_memory`.
- The migration creates `assessment_alerts`, `alert_memories`, and its owner index
  with `IF NOT EXISTS`; it does not reset the database. Existing Phase 2 data is
  retained while Phase 3 and Phase 4 tables are added.
- `ProviderContractExtractor` accepts an injected provider transport and passes
  only revisioned events, payment context, and fixed contract instructions. It
  does not send expected labels/family metadata or the private case ID.
- Provider exceptions propagate into the existing safe assessment failure path.
  The adapter never silently calls the development mock.
- No live transport, provider SDK, endpoint, API key, or model is configured.

### Evaluation preparation

- `evaluation/scenarios/development.json` contains labelled, synthetic development
  families; `held_out.example.json` is a separate empty held-out boundary.
- Detector inputs and expected behaviour metadata remain separate at runtime.
- The runner prepares recall, false-positive, first-warning, repeated-alert,
  missed-escalation, quote-validity, interpretation, p50/p95 latency, and token-use
  fields. Unsupported measurements remain `null` instead of being invented.
- The observed 3/3 development-fixture conformance is explicitly labelled as
  deterministic mock conformance, not model accuracy.

### Packaging

- Multi-stage Dockerfile builds the locked frontend, installs the pinned Python
  package, serves the frontend from FastAPI, honors `PORT`, and stores SQLite at
  `/data/scamflow.sqlite3`.
- Compose defines one application instance and a named persistent volume.
- The same-origin production frontend is served after API routes. `/health`, `/`,
  and the generated JavaScript asset returned HTTP 200 in a local static smoke.
- `.env.example` is secret-free and documents only local/runtime values.
- Railway infrastructure-as-code records the single replica, `/health` deployment
  health check, 500 MB `/data` volume, preserved environment variables, and volume
  usage alerts.
- The public HTTPS deployment requires Secure cookies even though it deliberately
  remains in development mode for the deterministic mock extractor.

## Architecture and changed files

Request flow:

    React/Vite browser
      -> same-origin FastAPI routes and protected cookie/CSRF checks
      -> owner-scoped SQLite case and exact ordered evidence
      -> immutable revision snapshot (outside write transaction)
      -> injected extractor
      -> strict schema/event/span/quote validation
      -> Digital Arrest + Fake Refund contextual policy
      -> ownership/session/expiry/revision/idempotency recheck
      -> atomic assessment, evidence, alert result, and alert-memory commit
      -> evidence-linked response

Key existing files updated:

- `backend/scamflow/app.py`: response mapping and optional same-origin static app.
- `backend/scamflow/api_schemas.py`: persisted alert response contract.
- `backend/scamflow/detection.py`: Fake Refund vocabulary and contextual rules.
- `backend/scamflow/assessment_services.py`: transactional alert policy.
- `backend/scamflow/models.py`: alert ORM models and cascades.
- `backend/scamflow/database.py`: explicit recorded additive migration.
- `backend/scamflow/services.py`: same-key append race reconciliation.
- `README.md`, `.env.example`, `.gitignore`.

New implementation groups:

- `backend/scamflow/extractors.py` and focused backend tests.
- `frontend/src/` application, API client, Unicode helper, demo data, and Vitest tests.
- `frontend/e2e/` and `playwright.config.ts`.
- `frontend/package.json` and locked `package-lock.json`.
- `evaluation/` runner and separate scenario-family files.
- `Dockerfile`, `compose.yaml`, and `.dockerignore`.
- `.railway/railway.ts` plus its pinned Railway IaC SDK lockfile.
- This report.

The remote repository already contained `sneat template.zip` in commit
`42e29dad480175a977b5b0a87d91fc85a74cfb58`. Its archive paths,
notices/manifests, and symlink entries were inspected without extraction. No
external template scripts, assets, symlinks, or license files were imported into
the application; the requested visual direction was implemented independently.

## Verification results

Final successful checks:

| Command | Observed result |
| --- | --- |
| `.venv/bin/python -m pytest` | 133 passed in 2.19 s; one upstream Starlette/httpx deprecation warning |
| `.venv/bin/ruff check .` | All checks passed |
| `.venv/bin/python -m pip check` | No broken requirements |
| `npm ci` | 108 packages installed; lockfile reproduced; 0 vulnerabilities |
| `npm run typecheck` | Passed |
| `npm test` | 4 files, 8 tests passed |
| `npm run build` | Passed; production assets generated |
| `npm audit --audit-level=high` | 0 vulnerabilities |
| `npm run test:e2e` | 2 Chromium browser tests passed in 3.2 s on the final run |
| 100-run same-key append stress script | 100/100 passed after the race fix |
| `.venv/bin/python evaluation/run_development_eval.py` | 3 scenarios processed; quotes valid; labelled mock-only output |
| `docker compose config` | Configuration rendered successfully |
| local built-static smoke | `/health`, `/`, and built JS asset returned HTTP 200 |
| Railway deployment health check | Successful HTTPS deployment; `/health` returned `{"status":"ok"}` |
| hosted browser smoke | Session, Secure cookie/CSRF mutation flow, unsupported assessment, and deletion passed |

Browser coverage exercised session creation, demo create/assessment, linked quote
highlight, append, historical display, reassessment, reload, deletion, a second
isolated browser owner receiving 404, missing-CSRF rejection through the actual
proxy, and the visible unable-to-assess journey.

Failures, blocked checks, warnings, and flake history:

- The baseline before changes was 120 passed and Ruff clean.
- The known same-key append concurrency failure reproduced in the first full run
  and again at stress iteration 19 after an incomplete first fix. The second fix
  covers all observed SQLite conflict shapes; final full tests and 100 stress runs
  passed. It is no longer hidden or merely rerun, but SQLite remains a
  single-writer database and production load testing is still required.
- `docker compose build` was attempted locally and blocked before any build step
  because the local Docker daemon socket did not exist. Railway's cloud builder
  subsequently built and ran the Dockerfile successfully. This does not replace a
  local Docker/Compose runtime test.
- Pytest emits one upstream `StarletteDeprecationWarning` about TestClient's httpx
  integration. It does not fail tests.
- `npm ci` emits an informational install-script review warning for optional
  `fsevents`; installation, tests, build, and audit succeed.
- The first Railway build rejected Dockerfile `VOLUME` metadata; removing that
  unsupported directive fixed the packaging and the following deployments passed
  the `/health` gate.
- No tests were reported as skipped. Real-provider, persistent-volume restart,
  multi-process, mobile assistive-technology, and real-world accuracy checks were
  not run and are not claimed.

## Local demo and startup

Vite development:

    cd /Users/alladasakethsolomon/scamflow-ai
    SCAMFLOW_TRUSTED_ORIGIN=http://127.0.0.1:5173 \
      .venv/bin/python -m uvicorn backend.scamflow.app:app \
      --host 127.0.0.1 --port 8000

In a second terminal:

    cd /Users/alladasakethsolomon/scamflow-ai/frontend
    npm ci
    npm run dev

Open `http://127.0.0.1:5173`. Use Digital Arrest, Fake Refund, or Assessment
failure under “Incremental synthetic replay.” Each click submits only one newly
revealed event and reassesses the persisted current revision.

Production-style local same origin:

    cd /Users/alladasakethsolomon/scamflow-ai/frontend
    npm ci && npm run build
    cd ..
    .venv/bin/python -m uvicorn backend.scamflow.app:app \
      --host 127.0.0.1 --port 8000

Open `http://127.0.0.1:8000`.

Docker, once a Docker daemon is running:

    cd /Users/alladasakethsolomon/scamflow-ai
    docker compose up --build

## Security, privacy, and operating limitations

- This is an anonymous local prototype, not identity authentication. Possession of
  the protected owner cookie controls access.
- CSRF uses exact Origin plus a required custom header. Production settings require
  an HTTPS trusted origin and Secure cookies.
- Submitted evidence is sensitive and stored unencrypted in SQLite. Host access,
  filesystem permissions, backups, retention, and device encryption remain the
  operator's responsibility.
- The browser deliberately logs no evidence. Public database/provider failures use
  safe envelopes rather than raw exception content.
- Evidence validation proves source traceability, not semantic correctness.
- Deterministic patterns cover disclosed synthetic vocabulary only. Unknown input
  is unable-to-assess, not safe.
- SQLite deployment is limited to one application instance with a persistent
  volume. Container-local storage must not be assumed to survive redeployment.
- Human reviewer authentication, queues, external reporting, real-model monitoring,
  and incident-response workflows remain roadmap items; the UI does not claim a
  review was submitted.

## Remaining real integration and operations work

1. Select a real provider and model, review its data-use and regional/privacy
   terms, implement the injected transport, and add server-side secret loading.
2. Run provider contract, malformed output, timeout, prompt-injection, evidence
   traceability, and explicit no-fallback tests against mocked transport first.
3. Build a genuinely independent held-out family set and measure the prepared
   metrics. Do not reuse deterministic development conformance as accuracy.
4. Exercise controlled live calls only with explicit credentials and budget/data
   approval. Verify failures remain `unable_to_assess` and never invoke the mock.
5. Start a local Docker daemon, build with Compose, and repeat health, UI,
   migration, deletion, and persistent-volume restart checks locally.
6. Define production monitoring, backups and restore drills, retention automation,
   custom-domain policy, usage alerts, and an operating budget before treating the
   Railway service as production.
7. Recheck current Railway documentation and pricing before scaling or changing
   the service; SQLite requires this deployment to remain at one replica.

## Git state

The implementation is committed on top of the existing remote Sneat archive
commit and pushed to `origin/main` after the user explicitly requested the GitHub
upload. The upload uses a normal fast-forward push; no history rewrite or force
push is used and no pull request is opened.
