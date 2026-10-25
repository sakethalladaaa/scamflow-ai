# ScamFlow AI — Phase 1B Stabilization Report
## Correctness & Dependency Stabilization

**Document:** `docs/PHASE_1B_STABILIZATION.md`  
**Phase:** Phase 1B (Completed)  
**Date:** October 25, 2026  
**Repository:** `/Users/alladasakethsolomon/scamflow-ai`  

---

## 1. Initial State

- **Branch:** `main`
- **Commit:** `c4f1b6b5f83e9669b8c8044c2da7ac42a0de89a1`
- **Working Tree:** Clean baseline at start of Phase 1; existing documentation files from Phase 0 and Phase 1 were untracked.
- **Relevant Pre-existing Untracked Files:**
  - `docs/PHASE_0_CURRENT_STATE.md` (preserved from Phase 0)
  - `docs/REFERENCE_REPO_AUDIT.md` (created during Phase 1 audit)
  - `docs/PRODUCT_IMPLEMENTATION_PLAN.md` (created during Phase 1 planning)

---

## 2. Task A — Retry / Idempotency Correctness

### Confirmed Root Cause
In `frontend/src/App.tsx`, user actions (`create`, `append`) previously maintained retry state using a map of idempotency keys (`retryKeys: Map<string, string>`). However:
1. On each submit invocation, a new payload was generated containing a fresh `crypto.randomUUID()` for `event_id`.
2. When a network error or interrupted request occurred, the retry mechanism reused the same `Idempotency-Key` string from `retryKeys` but passed a newly generated payload with a different `event_id`.
3. Because the backend calculates an SHA-256 fingerprint over `canonical_json({"events": events, "payment": payment})` for the idempotency record, re-submitting with a new `event_id` mismatched the stored fingerprint, causing the backend to reject the retry with HTTP `409 Conflict` (`idempotency_conflict`).
4. In addition, late asynchronous responses across case switching or rapid actions could overwrite state from newer user interactions, and double-clicks were vulnerable to partial state race conditions.

### Implementation
- **Immutable Retry Operations (`retryOperations`):** Replaced `retryKeys` with a ref storing immutable logical operations:
  ```typescript
  type RetryOperation =
    | { type: 'create'; key: string; payment: PaymentContext; events: EventInput[] }
    | { type: 'append'; key: string; caseId: string; expectedRevision: number; events: EventInput[] }
    | { type: 'assess'; key: string; caseId: string; expectedRevision: number }
  ```
- **Scoped Invariant Guarantee:** Scopes are partitioned by action, target identifiers, and payload content (e.g., `append:${caseId}:${expectedRevision}:${channel}:${text}`). If an operation for this exact scope already exists in `retryOperations`, the retry reuses the identical `key`, `payment`, and `events` array (including the exact, immutable `event_id`).
- **New Operations Receive New Identity:** When the user initiates a genuinely new submission (or modifies the text/channel), a new scope is computed, generating a fresh idempotency key and new event IDs.
- **Double-Click Protection:** Synchronously sets and guards `busy` state (`create`, `append`, `assess`, `delete`, `demo-step`, `demo-reset`) preventing concurrent execution.
- **Epoch & Case Guarding:** Employs `epoch` references (`requestEpoch === epoch.current && activeCase.current === targetCaseId`) to prevent delayed or out-of-order network responses from mutating newer or different case UI states.
- **Durability Limitation:** Retry state is explicitly in-memory for the active browser session tab; refreshing or reloading intentionally clears in-flight retry state.
- **Stale Revisions:** Preserves genuine backend `409` revision conflicts without suppressing or misinterpreting them as retry successes.

### Affected Files
- `frontend/src/App.tsx`
- `frontend/src/App.test.tsx`

### Behavioral Guarantees
- **Interrupted Network Request:** Re-attempting sends identical `Idempotency-Key` and identical payload with identical `event_id`, allowing idempotent backend recovery without `409 idempotency_conflict`.
- **Double Click:** Blocked by synchronous `busy` gate and form disabled states.
- **Explicit New Submission:** Generates fresh UUIDs for both idempotency key and event identifiers.
- **Late Responses:** Discarded if user has navigated away or if a newer request epoch has completed.

### Tests Added
Added comprehensive unit tests in `frontend/src/App.test.tsx`:
1. `same logical operation retried with identical idempotency key`
2. `same logical operation retried with identical payload and stable event_id`
3. `new operation gets a new identity`
4. `double-click protection prevents duplicate submissions`
5. `stale revision conflict remains visible`
6. `retryable network failure followed by retry succeeds with original identity`
7. `late responses do not overwrite newer UI state`
- **Result:** All 9 tests in `src/App.test.tsx` and all 14 frontend tests pass.

---

## 3. Task B — Deterministic Latest-Assessment Selection

### Confirmed Root Cause
In `backend/scamflow/assessment_services.py` (lines 698–704), `get_latest_assessment()` queried:
```python
select(Assessment)
.where(Assessment.case_id == case.id, Assessment.owner_id == owner_id)
.order_by(Assessment.created_at.desc(), Assessment.id.desc())
.limit(1)
```
- `Assessment.id` is a randomly generated hex UUID (`_new_public_id()`).
- Lexicographical ordering on random UUIDs has no correlation with temporal or semantic sequence.
- Because `created_at` records timestamps with one-second resolution (`int(clock())`), multiple assessments created within the same second (e.g., automated assessments, rapid appends, or re-assessment attempts) relied on `Assessment.id DESC`. An older assessment whose random UUID started with `"z"` would incorrectly be selected over a newer assessment whose UUID started with `"a"`.

### Exact Semantic Definition of "Latest"
In ScamFlow, the "latest assessment" for a case represents:
1. The assessment created at the latest timestamp (`created_at DESC`),
2. For the highest case revision (`assessed_revision DESC`),
3. For multiple assessments on the same revision in the same second, the most recently persisted database record.

### Chosen Deterministic Ordering Strategy
- Used **Option A** (schema-preserving deterministic query enhancement). No database migration was required.
- Query order clauses:
  ```python
  order_by_clauses = [
      Assessment.created_at.desc(),
      Assessment.assessed_revision.desc(),
  ]
  if session.get_bind().dialect.name == "sqlite":
      order_by_clauses.append(text("assessments.rowid DESC"))
  else:
      order_by_clauses.append(Assessment.id.desc())
  ```
- **Portability & Determinism:** SQLite's hidden monotonic `rowid` guarantees absolute insertion order for same-second, same-revision ties on SQLite without altering the schema or requiring table rewrites. On alternative engines (e.g., PostgreSQL with bigserial/identity sequences), engine-specific sequence/row ordering can be leveraged cleanly.

### Migration Required?
**NO.** Existing fields (`created_at`, `assessed_revision`) combined with SQLite monotonic physical insertion identity (`rowid`) provide complete, deterministic ordering without requiring a schema migration or data transformation.

### Tests Added
Added regression tests in `backend/tests/test_assessments.py`:
1. `test_latest_assessment_deterministic_ordering_same_second_across_revisions`:
   - Evaluated revisions 1 and 2 in the exact same second (`fixed_time = 1_800_000_000`).
   - Mocked UUIDs such that rev 1 received `"zzzz..."` and rev 2 received `"aaaa..."`.
   - Verified that revision 2 (`"aaaa..."`) is deterministically returned as latest, whereas the old query returned revision 1.
2. `test_latest_assessment_deterministic_ordering_same_second_same_revision`:
   - Evaluated two re-assessment attempts for revision 1 in the exact same second.
   - Mocked UUIDs such that attempt 1 received `"zzzz..."` and attempt 2 received `"aaaa..."`.
   - Verified that attempt 2 is deterministically returned.
- **Result:** All 135 backend tests pass.

---

## 4. Task C — Dependency Advisory Remediation

### Verified Advisory Information
- **Package:** `undici`
- **Initial Installed Version:** `undici@8.11.2`
- **Dependency Path:** `scamflow-ai-frontend -> devDependencies -> jsdom@30.1.2 -> undici@8.11.2`
- **Advisory Identifiers:**
  - `GHSA-4qv8-2p9j-2685` (Moderate: Re-DoS in `getGlobalOrigin`)
  - `GHSA-f72v-6w45-q472` (Moderate: CRLF Injection in fetch / request headers)
  - `GHSA-xjj6-f33q-929c` (Moderate: Host header spoofing / proxy bypass)
- **Production Impact:** None. `undici` is strictly a transitive dependency of `jsdom`, which is used exclusively in `devDependencies` for the Vitest test environment.

### Remediation Used
- Added targeted package override in `frontend/package.json`:
  ```json
  "overrides": {
    "undici": "8.12.3"
  }
  ```
- Ran standard non-destructive `npm install` (avoiding `npm audit fix --force`).
- **Resolved Version:** `undici@8.12.3` (satisfies `jsdom@30.1.2` dependency specifier `"undici": "^8.11.2"`).
- **Audit Results:**
  - `npm audit`: `found 0 vulnerabilities`
  - `npm audit --omit=dev`: `found 0 vulnerabilities`
  - `npm ls undici`: `undici@8.12.3 overridden`
- **Compatibility:** All Vitest unit tests, Playwright E2E tests, TypeScript compilation, and Vite production builds pass cleanly.

---

## 5. Regression Results

| Suite / Tool | Command | Result | Details |
|---|---|---|---|
| **Backend Tests** | `.venv/bin/pytest backend/tests/` | **PASS** | 135 passed, 0 failed (1.80s) |
| **Frontend Unit Tests** | `npm run test` (in `frontend/`) | **PASS** | 4 test files passed, 14 tests passed (1.62s) |
| **Frontend E2E Tests** | `npm run test:e2e` (in `frontend/`) | **PASS** | 2 tests passed (Chromium headless, 3.4s) |
| **TypeScript Typecheck & Build** | `npm run build` (in `frontend/`) | **PASS** | `tsc -b` and `vite build` succeeded with 0 errors |
| **Backend Ruff Linter** | `.venv/bin/ruff check backend/` | **PASS** | All checks passed |
| **npm Full Audit** | `npm audit` (in `frontend/`) | **PASS** | found 0 vulnerabilities |
| **npm Production Audit** | `npm audit --omit=dev` (in `frontend/`) | **PASS** | found 0 vulnerabilities |

---

## 6. Security and Privacy Review

1. **Session Ownership & Tenant Isolation:** Untouched. All case, append, assess, and delete operations strictly enforce authenticated session ownership (`owner_id`).
2. **CSRF Protection:** Preserved. Double-submit cookie with custom header validation is active and verified by existing API and E2E suites.
3. **Idempotency Integrity:** Strengthened. Frontend now enforces stable `event_id` and payload matching per idempotency key, preventing invalid cache collisions and preventing `409` errors on valid retries.
4. **Evidence Sanitization & Redaction:** Intact. Exact byte-slice evidence quoting, zero-byte redaction, and revision checks remain strictly enforced.
5. **No Secret Leaks:** No credentials, API tokens, or personal identifiers have been committed or logged.

---

## 7. Remaining Risks

1. **In-Memory Retry Lifetime:** Retry state is deliberately held in client memory (`useRef`). A browser page refresh or hard reload clears in-flight retry tokens. This is an accepted and documented trade-off that avoids leaking sensitive evidence payloads to `localStorage` or `sessionStorage`.
2. **Multi-Tab Replay:** Independent browser tabs operating on the same case share session cookies but maintain independent in-memory retry state. If two tabs submit conflicting appends, the backend revision guard cleanly rejects the stale submission with HTTP `409`.
3. **Database Portability:** While SQLite `rowid` ordering guarantees strict tie-breaking in SQLite, switching to PostgreSQL or MySQL in production would require ensuring an equivalent monotonic sequence column or microsecond timestamp resolution.

---

## 8. Phase 2 Prerequisites

- Base application is fully stabilized:
  - Frontend retry lifecycle is correct and verified.
  - Latest-assessment queries are deterministic.
  - Zero npm vulnerabilities remain across the dependency tree.
  - All unit, integration, and end-to-end tests pass cleanly.
- The repository is completely stable and ready for Phase 2 (Real AI Integration Design & Interface Preparation).
