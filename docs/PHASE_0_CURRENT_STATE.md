# Phase 0: Current project verification and implementation planning

Audit date: **2026-10-25, Asia/Kolkata**  
Verdict: **COMPLETE for Phase 0, with findings and explicitly unverified operational areas.**

This is an audit of the existing MVP, not a rebuild or a production-readiness approval. No feature implementation or Phase 1 reference-repository audit was performed. Passing synthetic/mock checks does not establish real-world detection accuracy.

## 1. Repository identity and preservation

- Requested and resolved repository: `/Users/alladasakethsolomon/scamflow-ai` (`~/scamflow-ai`).
- Configured origin: `https://github.com/sakethalladaaa/scamflow-ai.git`.
- Inspected branch: `main`.
- Inspected commit: `c4f1b6b5f83e9669b8c8044c2da7ac42a0de89a1`.
- Initial `git status --short` and `git status --porcelain=v1 --untracked-files=all`: empty. There were no tracked modifications, staged changes, or non-ignored untracked files.
- `docs/PHASE_0_CURRENT_STATE.md` did not exist at the start. The existing `docs/LOCAL_MVP_COMPLETION_REPORT.md` was read as historical evidence and preserved in full.
- Existing ignored assets included `.venv`, frontend dependencies/build artifacts, test caches, `data/scamflow.sqlite3`, and `frontend/.e2e.sqlite3` with its WAL/SHM sidecars. Existing databases were neither opened nor queried; only filename, size and modification-time metadata were recorded for preservation checks.
- No pull/fetch, reset, clean, stage, commit, push, deployment, package installation, package upgrade, database deletion or recreation was performed. No reference-repository code was copied or installed.
- This report is the only repository addition. Test databases, copied frontend dependencies, generated assets and test outputs were confined to a new scratch directory outside the repository.
- Before report creation, all captured existing tracked-file hashes still matched, all four existing database-file metadata records matched, and Git still reported a clean tree. A final check after report creation verifies only this new report is untracked.

The scratch directory used below is:

```text
A=/Users/alladasakethsolomon/Documents/Codex/2026-10-25/work-on-scamflow-ai-before-you/work/phase0-sx44p07i
R=/Users/alladasakethsolomon/scamflow-ai
```

`A` and `R` are report abbreviations, not changes to system environment variables. Scratch databases contain only generated test fixtures and were left in place; no existing database was removed.

## 2. Instructions and workflow availability

No applicable `AGENTS.md` was found in the repository or its ancestor chain (`/`, `/Users`, `/Users/alladasakethsolomon`). No repository `CLAUDE.md`, `GEMINI.md`, vendored gstack workflow, or `.github` workflow was found in the inspected source inventory. Project guidance comes from `README.md`, `.railway/README.md`, manifests/configuration, source comments, and the historical completion report. The explicit Phase 0 constraints govern this audit.

The installed **Codex** gstack router was read at `/Users/alladasakethsolomon/.codex/skills/gstack/SKILL.md` as an availability/instructions audit. Codex skill files for `gstack-review`, `gstack-qa-only`, and `gstack-plan-eng-review` exist; router `bin` and `lib` resolve to `/Users/alladasakethsolomon/gstack`. The Claude installation at `/Users/alladasakethsolomon/.claude/skills/gstack` also exists and resolves to that source checkout, but its router file differs from the Codex router. Their host integration and instructions are not assumed equivalent. No gstack skill was found at the checked conventional Antigravity location `/Users/alladasakethsolomon/.gemini/antigravity/skills/gstack`; other possible locations were not exhaustively searched.

No gstack workflow runtime was invoked. The router describes startup, synchronization, telemetry and learning writes, while this task restricts repository changes to this report. Availability does not establish that browser bridges, credentials, or another host's workflow are operational. Ordinary source inspection and the project's own checks were sufficient; no gstack setup, upgrade, telemetry, delegation, or onboarding was needed.

## 3. Verified component status

| Component / historical claim | Status in current source | Evidence and practical limit |
| --- | --- | --- |
| React/TypeScript/Vite frontend | Implemented | `frontend/package.json`, `src/main.tsx`, `src/App.tsx`, `src/api.ts`, `vite.config.ts`. React 19.3.0, TypeScript 6.0.2, Vite 8.3.3; direct installed versions match manifest and lockfile. |
| FastAPI/Pydantic backend | Implemented | `backend/scamflow/app.py`, `schemas.py`, `api_schemas.py`, `settings.py`; strict request shapes, limits and safe public error envelopes. |
| SQLAlchemy/SQLite persistence | Implemented | `database.py`, `models.py`, `services.py`, `assessment_services.py`; foreign keys, WAL, busy timeout, transactions, exact decimal strings, ordered original evidence. |
| Consent and anonymous ownership | Implemented for MVP | `consent: Literal[True]`, recorded consent version/time, hashed opaque session token, HttpOnly/SameSite=Strict cookie. Production forces Secure; development can explicitly enable it. This is cookie possession, not authenticated identity. |
| CSRF | Implemented | Exact trusted Origin plus `X-ScamFlow-CSRF: 1` for session creation and mutations. No secret CSRF token is exposed. |
| Expiry and deletion | Partial lifecycle | Access expiry and hard case deletion/cascades exist. Idempotency tombstones remain. Expiry does not erase data; no automatic retention purge exists. |
| Idempotency and append revisions | Backend implemented; UI retries partial | Owner/operation/key uniqueness, request fingerprint, append compare-and-set revision update, bounded race reconciliation. Frontend regenerates event IDs during retries; see finding F1. Session bootstrap and DELETE do not require an idempotency key, contrary to the README's blanket mutation statement. |
| Fixed-revision snapshots | Implemented in memory | Frozen dataclasses copy ordered events and payment context before extraction. Original events persist; a separate complete immutable snapshot table is not implemented. |
| Exact evidence validation | Implemented | Strict extraction payload, tactic/context enums, event lookup, bounded code-point offsets, exact quote equality and duplicate removal. Traceability is checked; semantic truth is not. |
| Digital Arrest and Fake Refund | Implemented as narrow mock/rule behavior | Both families live in `detection.py`; active asserted tactic combinations determine risk, with literal negation/quoted-warning controls. No general language-understanding or authenticity claim is supported. |
| Commit guards and atomic assessment storage | Implemented, baseline tested | Recheck live owner, owned/unexpired case, request fingerprint/idempotency and revision after extraction; save assessment, evidence, alert and memory in one transaction. Race/rollback tests pass; this is not a multi-process load certification. |
| Development extraction | Implemented | `DevelopmentMockExtractor`, fixed phrase vocabulary, `development_mock` mode. Unsupported vocabulary yields `unable_to_assess`. |
| Real AI provider | Adapter only; live integration missing | `ProviderContractExtractor` requires an injected callable; no bundled network transport, provider SDK wiring, credential loader, model selector or endpoint. Production without an injected extractor returns 503. |
| Evidence highlighting | Implemented | `unicode.ts` converts Python code-point offsets to UTF-16; React text nodes and `<mark>` preserve original text without HTML interpretation. Unit and E2E checks pass. |
| Incremental replay | Implemented for synthetic demos | `demos.ts` and `App.tsx` reveal one event per action through normal case APIs. Progress is component state; reload restores case ID via URL, not full replay controls. Demo create/append uses fresh keys on retries. |
| Persisted alert memory | Implemented | `AssessmentAlert`, `AlertMemory`, `_apply_alert_policy`; suppress unchanged signatures, show material changes/escalations, preserve prior warning after extraction failure. Two focused alert tests pass as part of backend suite. |
| Latest assessment | Implemented with ordering defect | Orders by second-resolution timestamp then random UUID. Same-second requests can return an earlier result; see F2. |
| Evaluation | Partial development harness | Three synthetic development scenarios; empty held-out example. Quote/state checks work. Several metrics are placeholders or expected labels, not measured results. |
| Docker/Compose packaging | Source/config verified; runtime unverified | Multistage Node 24/Python 3.11 Dockerfile, FastAPI static serving, PORT, named SQLite volume; Compose config validation passes. Docker daemon unavailable. |
| Railway | Infrastructure declaration present; current service unverified | `.railway/railway.ts` declares one `sfo` replica, `/health`, 500 MB volume at `/data`, usage alerts and preserved variables. No remote state, deployment commit, secret values, health or volume was inspected. |
| Operational production features | Missing or unverified | No user/reviewer authentication, human-review queue, external reporting, automatic purge, provider budget control, production monitoring or backup/restore workflow in inspected application source. No repository CI workflow or Python transitive lockfile found. |

The Python environment is available and direct pins match: Python 3.11.16; FastAPI 0.142.2; Uvicorn 0.54.0; Pydantic 2.13.5; pydantic-settings 2.15.0; SQLAlchemy 2.1.3; pytest 9.1.1; httpx 0.28.1; Ruff 0.16.10. Node is 26.7.0 and npm is 11.19.0. These local checks therefore do not verify Docker's Node 24 runtime. The frontend lockfile is version 3; both dependency groups match the manifest. `.railway/package.json` pins Railway 3.13.1 and has a lockfile, but its IaC was not planned or applied.

### Persistence and migrations

`models.py` defines owner sessions, cases, events, mutation idempotency, assessments, assessment evidence, assessment idempotency, alert memory and assessment alerts. Ownership foreign keys/cascades and unique case/event/order constraints are present. Deletion clears derived content and retains deletion-safe retry metadata.

`initialize_schema()` uses `Base.metadata.create_all` for the earlier tables, then an explicit additive migration recorded as `0001_alert_memory` in `schema_migrations`. That migration creates `assessment_alerts`, `alert_memories` and the owner index with `IF NOT EXISTS`. There is no Alembic migration directory, general schema-version upgrade framework or downgrade path. The existing migration test constructs a synthetic Phase 2 schema and verifies added tables and retained case data. No migration was run against the existing local or hosted database.

## 4. Actual request flow

```text
Browser session bootstrap + explicit intake consent
  -> POST /session: exact Origin/custom-header CSRF; create/reuse owner cookie
  -> POST /cases: validate consent, payment context, event count/text/order
  -> atomic owner-scoped case + original events + idempotency record, revision 1
  -> POST /cases/{id}/assess with expected_revision + Idempotency-Key
  -> authenticate/authorize; check expiry and replay; copy fixed revision snapshot
  -> close snapshot session; run configured extractor outside write transaction
  -> strict schema + exact event/span/quote validation
  -> Digital Arrest / Fake Refund contextual rules (or unable_to_assess)
  -> begin transaction; recheck owner/case/expiry/revision/idempotency
  -> persist assessment + evidence + alert decision + alert memory + retry record
  -> response with versions, revision, state, evidence, limitations and alert
  -> React renders result, historical/current marker, linked exact highlights
```

Entry points: `app.py:create_app` and route handlers. Intake/mutation rules: `schemas.py`, `api_schemas.py`, `services.py`. Snapshot/extraction orchestration and commit boundary: `assessment_services.py:_snapshot_for_assessment`, `_run_extractor`, `assess_case`. Validation and policy: `detection.py:validate_extraction`, `decide_digital_arrest` (the latter also contains Fake Refund rules). Persistence: `models.py`/`database.py`. Presentation: `frontend/src/api.ts`, `App.tsx`, `unicode.ts`.

`POST /cases/{id}/events` increments revision with a conditional SQL update and preserves previous event text. `GET /cases/{id}` returns ordered evidence. `GET /cases/{id}/assessments/latest` marks staleness by comparing assessed/current revisions. `DELETE /cases/{id}` checks ownership/expiry and cascades deletion. There is no direct payment execution or payment interception in this product.

## 5. Provider/configuration verification without secrets

Inspected application source, declared dependencies, the adapter contract, deployment configuration names, and exported environment-variable **names only**. The only root dotenv-style file found was `.env.example`; only its variable names were emitted. No cookie, key value, private case content or environment value was printed. No provider call was made.

Recognized settings are `SCAMFLOW_ENVIRONMENT`, `SCAMFLOW_LOG_LEVEL`, `SCAMFLOW_DATABASE_PATH`, `SCAMFLOW_SQLITE_BUSY_TIMEOUT_MS`, `SCAMFLOW_SESSION_TTL_SECONDS`, `SCAMFLOW_CASE_RETENTION_SECONDS`, `SCAMFLOW_ASSESSMENT_TIMEOUT_SECONDS`, `SCAMFLOW_TRUSTED_ORIGIN`, `SCAMFLOW_SECURE_COOKIES`; container startup also uses `PORT`. `Settings` explicitly sets `env_file=None` and does not load local dotenv files.

No names matching the inspected `SCAMFLOW_`, `OPENAI_`, `ANTHROPIC_`, `GEMINI_`, `GOOGLE_API_`, `AZURE_OPENAI_`, `AWS_`, or `BEDROCK_` prefixes were present in the audit process environment before test overrides. This is limited to this process and these prefixes; it does not establish anything about remote secret stores or other applications.

`app = create_app()` automatically selects the mock only outside production. Production rejects an explicitly supplied mock, and no configured extractor produces `503 assessment_unavailable` on assess. There is no settings-based construction of `ProviderContractExtractor`. The adapter passes revision, events, payment context and fixed untrusted-evidence instructions to a supplied callable, omits the private case ID/expected labels, and propagates transport failures. Contract tests use local fake callables only. A real provider is **not implemented or wired in the inspected checkout**; hosted configuration was not checked.

## 6. Commands and actual outcomes

Read-only discovery included `pwd`, `git rev-parse --show-toplevel`, `git branch --show-current`, `git rev-parse HEAD`, both status commands, `git remote -v`, `git ls-files`, `rg --files --hidden` with secrets/databases/dependency directories excluded, targeted `rg -n`, `cat`/`sed` source reads, and filename-only workflow/tooling inventories. Source reads covered all application modules, test setup/cases, frontend scripts/configuration, manifests, migration code, evaluation runner, README/report and Docker/Railway configuration. No archive extraction was performed.

| Check and executed command | Actual outcome |
| --- | --- |
| `.venv/bin/python --version`; `node --version`; `npm --version`; package metadata comparison | Python 3.11.16, Node 26.7.0, npm 11.19.0; all inspected direct pins match installed packages. |
| `.venv/bin/python -m pip check` | **PASS**: no broken requirements. This is dependency consistency, not a Python vulnerability scan. |
| `PYTHONDONTWRITEBYTECODE=1 SCAMFLOW_ENVIRONMENT=test SCAMFLOW_DATABASE_PATH=$A/default-test.sqlite3 .venv/bin/python -m pytest -p no:cacheprovider --basetemp=$A/pytest` from R | **PASS**: 133 passed, 1 warning, 2.20 seconds; no skips reported. |
| `.venv/bin/ruff check --no-cache .` from R | **PASS**: all checks passed. |
| `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python evaluation/run_development_eval.py` from R | **PASS, mock conformance only**: 3 scenarios, all state comparisons and quote-validity fields true. p50 0.065 ms, p95 0.181 ms for this tiny in-process run; not provider latency. |
| `npm run typecheck` from `$A/frontend` | **PASS** after correcting the scratch dependency-copy issue described below. |
| `npm test` from `$A/frontend` | **PASS**: 4 files, 8 tests; 968 ms. |
| `npm run build` from `$A/frontend` | **PASS**: TypeScript and Vite; 19 modules, 397 ms Vite build. JS 234.13 kB / 73.29 kB gzip, CSS 4.74 kB / 1.72 kB gzip. Existing repository dist was untouched. |
| `npm audit --audit-level=high --cache $A/npm-cache` from `$A/frontend` | **FAIL**, exit 1: one high-severity vulnerable package, `undici` 8.11.2, with three advisories. No fix/install/upgrade was run. |
| `npm explain undici` from `$A/frontend` | Confirms development dependency path `jsdom@30.1.2 -> undici@8.11.2`; jsdom is used by Vitest. |
| `npm audit --omit=dev --audit-level=high --cache $A/npm-cache` from `$A/frontend` | **PASS**: zero reported vulnerabilities in the production dependency subset at audit time. |
| `docker compose config --quiet` from R | **PASS**, exit 0. No container created. |
| `docker version --format '{{.Server.Version}}'` | **BLOCKED**, exit 1: Docker API socket `/Users/alladasakethsolomon/.docker/run/docker.sock` does not exist. No Docker daemon was started. |
| `./node_modules/.bin/playwright test --config=playwright.phase0.config.ts` from `$A/frontend` | **PASS**: both existing Chromium E2E tests, 4.7 seconds, using installed browser tooling and a new scratch database. |
| Isolated synthetic API reproductions using `.venv/bin/python -` with `PYTHONDONTWRITEBYTECODE=1` and a new `$A/synthetic-repro.sqlite3` | Confirmed same-key regenerated-event-ID retry returns `409 idempotency_conflict`; controlled same-second UUID ordering returns the first assessment rather than the second. These are findings, not passing acceptance criteria. |
| Tracked-file SHA-256 comparison and existing DB size/mtime comparison | **PASS** before and after report creation: existing captured source files unchanged; existing database metadata unchanged. |

### Test isolation and audit setup details

The database-writing backend tests explicitly use pytest `tmp_path`. The health test uses an in-process ASGI transport without entering database lifespan. A scratch default database path also guarded import/default settings. Pytest's fresh basetemp did not exist previously; repository bytecode/cache writes were disabled. No SQL connection was made to the pre-existing database files.

The frontend source and already-installed dependencies were copied into `$A/frontend`; no `npm ci`, package install or browser download ran. The first copy excluded every directory named `dist`, inadvertently omitting dependency distribution files. The first typecheck therefore failed with missing Vitest/testing-library/plugin-react declarations and dependent TypeScript errors; chained unit/build commands did not run on that attempt. Filling the omitted files produced benign existing-symlink copy errors; a subsequent byte comparison verified **4,125 dependency files with zero mismatches**, plus matching symlink targets, before accepting the successful checks. These were audit staging errors, not a missing repository dependency or an application repair.

The repository Playwright config was **not executed unchanged**: it starts with `rm -f .e2e.sqlite3 .e2e.sqlite3-shm .e2e.sqlite3-wal`, while its configured database is `frontend/.e2e.sqlite3` relative to repository cwd. Besides being destructive, those paths do not target the same database. The scratch config retained the original tests, browser, ports, proxy and no-server-reuse behavior; removed the deletion command; set an absolute new `$A/e2e-new.sqlite3` path; set backend cwd to R; and disabled backend bytecode writes. Ports 8000 and 5173 were confirmed available. The Vite server ran from the scratch frontend. Only synthetic test cases were created/deleted in the new database. The two managed servers exited after the run.

Warnings: Starlette deprecates TestClient's httpx integration (suggesting httpx2); this warning was recorded without modifying pinned dependencies. Playwright emitted a non-failing NO_COLOR/FORCE_COLOR warning. npm advertised a newer npm version; no upgrade occurred.

### Checks not run or not claimed

- Docker image build, container startup, persistent-volume restart and restore: blocked by unavailable daemon; Compose syntax validation is not a substitute.
- Hosted Railway health/browser checks, deployment provenance, remote environment/volume state, account usage and remote data: not inspected. The historical healthy deployment statement is **not current verification**.
- Live AI calls, provider latency/token/cost/privacy validation, independent held-out accuracy, multilingual/OCR/audio/URL ingestion: no configured integration/dataset; not run.
- Historical 100-iteration same-key stress test: not repeated; current backend suite includes concurrency cases and passed once.
- Dedicated built-static HTTP smoke, multi-process/load tests, mobile assistive-technology audit, backup/restore drills, Python security-advisory scan and Railway IaC plan: not run.
- Reference repositories: not fetched, cloned, installed, copied or code/license-audited in Phase 0.

## 7. Findings, blockers and unresolved questions

**F1 — Frontend idempotency is incomplete.** `frontend/src/App.tsx:151` retains a key for manual creation, but line 155 constructs a fresh UUID for the event on every submit. Append similarly constructs a fresh UUID at line 167 before reusing the key. The backend fingerprint covers the complete payload (`services.py:_fingerprint`). After a server commit whose response is lost, resubmission therefore changes the request and conflicts. The synthetic reproduction changed only the event ID while retaining the create key and received 409. A complete frontend lost-response journey was not added to the suite. Existing pending-click prevention tests do not cover this case. Future repair should retain key **and exact payload** until the logical mutation is resolved; demo retries need the same consideration.

**F2 — Latest-result ordering is not chronological within a second.** `assessment_services.py:704` orders by `created_at DESC, id DESC`, with second-resolution `system_clock()` and random UUID IDs. A scratch reproduction fixed the clock, supplied descending UUIDs to two successive real assessment writes, and verified that latest returned the first. Same-second assessments across revisions could therefore display an older historical result after reload. Future repair needs a deterministic insertion/ordering contract and a regression case, not reliance on UUID lexical order.

**F3 — Current dependency audit fails.** The current npm registry response reports `undici` 8.11.2 under dev-only jsdom, with [EventSource memory exhaustion](https://github.com/advisories/GHSA-4qv8-2p9j-2685), [Subresource Integrity algorithm-token handling](https://github.com/advisories/GHSA-f72v-6w45-q472), and [excessive content-encoding error handling](https://github.com/advisories/GHSA-xjj6-f33q-929c). Production-only audit returns zero. Exploitability in this repository was not reproduced; do not equate this development dependency finding with a demonstrated browser-production exploit. A separately scoped dependency remediation is needed; versions were preserved here.

**F4 — Provider seam is not production integration.** Transport, server-side provider configuration, timeouts/cancellation, retry/cost limits and observability are missing. `_run_extractor` bounds caller wait but `future.cancel()` cannot stop an already-running thread; a future network transport needs its own enforced timeout. `detection.py:455` and `App.tsx` hard-code mock wording even for a future injected real provider. Version names also retain Digital Arrest/Phase 3 labels for both rule families. These need deliberate evolution before live inference; none was changed.

**F5 — Evaluation measurements are incomplete.** `evaluation/run_development_eval.py:60` assigns `first_warning_stage` directly from `expected_first_warning_stage`; it does not replay prefixes to measure it. Repeated alerts, missed escalations and token usage are null; recall/false positives are listed as prepared fields, not computed metrics. The CLI prints comparisons but does not explicitly fail the process on a false comparison. The held-out example contains zero scenarios. No accuracy or first-warning performance claim can be derived from the 3/3 result.

**F6 — Lifecycle and deployment claims need boundaries.** Expiry prevents access but does not purge stored evidence; an expired case also cannot be deleted through the normal owned/unexpired route. Data is plaintext SQLite. Hard deletion retains hashed retry metadata; it is not deletion of every metadata row or forensic erasure from storage/backups. The UI calls storage “local,” although in a hosted deployment it is server-side. The README says all mutations require idempotency keys, while bootstrap/DELETE do not. Historical deployment, security and test statements must be treated as dated observations.

**F7 — Default E2E command is unsafe for this audit.** Its deletion preamble and mismatched cleanup/database paths are documented above. Future test harness work should use per-run temporary paths and preserve existing databases.

Open decisions for later phases: target users/languages and supported scam families; provider/model, data region, retention/consent terms and spending ceiling; precise meaning of latest result and immutable snapshot guarantees; required review workflow; retention/purge and backup policy; current deployment ownership/provenance; and acceptable licenses for reference ideas/code/assets/data. None blocks completion of this source-and-baseline audit.

## 8. Recommended Phase 1 scope and implementation planning

The next concrete step is a **separate read-only reference-repository audit**, pinned to a recorded commit for each repository:

- `https://github.com/triveshsivnarain004/signalshield-africa`
- `https://github.com/KrinsKumar/Phone-a-Fraud`
- `https://github.com/knimu/NEXUS`

For each, first establish repository identity, actual purpose, branch/commit, maintenance state, LICENSE/NOTICE and any file-level exceptions. Do not infer purpose or suitability from its name. Inventory dependencies, runtime/network/provider requirements, build/install scripts, data/model provenance and asset licenses without running unreviewed scripts. Assess license compatibility and attribution/redistribution obligations for code, datasets, weights and UI assets separately; absent or ambiguous permission is not permission to copy.

Then map useful capabilities against this MVP: intake/consent, evidence preservation, extraction contracts, grounding/validation, scam-family rules, failure handling, alerts/replay, review workflows, accessibility, evaluation design and deployment assumptions. Assess prompt-injection boundaries, secrets/logging, data handling, dependency health, real test evidence and unsupported accuracy claims. Record a per-component decision: reject, learn conceptually, reimplement independently, or consider reuse after license review. Do not install/copy/integrate code as a side effect of discovery.

Phase 1 should produce a comparative evidence matrix, provenance/license notes and a bounded follow-on plan preserving this repository's ownership, CSRF, exact evidence, revision, idempotency, commit-guard and alert-memory contracts. Recommended later implementation order, subject to that audit and explicit scope:

1. Address verified retry/latest-ordering defects and isolate the test harness; remediate the development dependency finding in a reviewed version change.
2. Define provider-independent response wording/versioning and measured evaluation contracts; design real transport configuration, timeout, privacy and budget boundaries.
3. Add an approved provider transport with mocked contract/failure tests before any separately authorized live calls.
4. Build independent held-out families and measure progression, false positives, missed escalations, grounding, latency and cost.
5. Close retention, review, monitoring and deployment/backup verification gaps before any production claim.

**Stop boundary:** Phase 0 is complete. The reference repositories have not been audited, and no Phase 1 or feature implementation has begun.
