# ScamFlow AI — Before-You-Pay Safety Copilot

Responsive frontend-only React + TypeScript package. It does not include or change backend code. The app uses the verified FastAPI adapter only; it does not generate local risk verdicts or use fabricated API routes. Without a compatible backend, requests fail visibly instead of showing a simulated assessment.

## Install and run

Requirements: Node.js 20+ and npm.

```sh
npm ci
npm test
npm run build
npm run dev
```

Vitest runs every `src/**/*.test.*` and `tests/**/*.test.*` file. Playwright runs the separate `e2e/` suite through `npm test`; the E2E backend uses a unique operating-system temporary SQLite path and never touches repository databases.

## Backend contract verified against the ScamFlow repository

`src/api.ts` maps the current FastAPI contract and calls only these existing case operations:

| Method and route | Contract behavior used by this client |
| --- | --- |
| `POST /session` | No JSON body; sends `X-ScamFlow-CSRF: 1`; uses cookie credentials. |
| `POST /cases` | Sends `{ consent: true, payment_context: { stated_purpose, amount, recipient_reference }, events: [{ event_id, channel, text, source_order }] }`; sends CSRF and `Idempotency-Key`; reads `{ case_id, result_revision, idempotent_replay }`. |
| `GET /cases/{case_id}` | Maps `payment_context`, `revision`, and stored `events` into the UI model. |
| `POST /cases/{case_id}/events` | Sends `{ expected_revision, events: [{ event_id, channel, text, source_order }] }`; sends CSRF and a stable idempotency key. No `If-Match` header or invented event type is sent. |
| `POST /cases/{case_id}/assess` | Sends only `{ expected_revision }`, plus CSRF and idempotency key. |
| `GET /cases/{case_id}/assessments/latest` | Reads persisted assessment details; `404 assessment_not_found` means no assessment exists yet. |
| `DELETE /cases/{case_id}` | Sends CSRF header and cookie credentials; handles the empty `204` response. |

The backend error envelope is `{ detail: { code, message } }`; the client preserves its message and code and maps a non-JSON `502` to `request_failed`. Browser requests include credentials for owner operations. The browser supplies `Origin`; the client uses the backend's fixed, non-secret CSRF header value. No frontend session token or secret is added.

The backend `PaymentContext` requires `stated_purpose`, supports `amount` and `recipient_reference`, and has no currency field. Assessment states and content come from the backend; the frontend does not infer a risk result. Evidence is highlighted only when the returned event ID, source order, offsets, and exact quote match the original event text. The adapter validates evidence offsets in Unicode code-point space.

## Persisted review workflow

The owner workspace offers **Request human review** only when the loaded backend assessment is current for the case revision and its state is `needs_clarification_or_review` or `unable_to_assess`. It sends the actual `POST /cases/{case_id}/review-requests` body `{ assessment_id, expected_revision }`, plus the existing owner cookie credentials, `X-ScamFlow-CSRF: 1`, and an idempotency key. Backend duplicate-open-request and retry flags are preserved. The owner status panel reads only the safe lifecycle fields from `GET /cases/{case_id}/review-requests/{review_request_id}`; it does not expose reviewer notes.

The reviewer dashboard is available at `/reviewer`. It uses the verified routes:

| Method and route | Contract behavior used by this client |
| --- | --- |
| `GET /reviewer/review-requests?limit={limit}&offset={offset}` | Loads the backend's paginated open queue. |
| `GET /reviewer/review-requests/{review_request_id}` | Loads the persisted assessment snapshot, payment context, alert, limitations, and evidence with exact source text. |
| `POST /reviewer/review-requests/{review_request_id}/resolve` | Sends only one backend-allowed `outcome` (`follow_up`, `escalated`, `no_action`, or `inconclusive`) and an optional bounded `reviewer_note`, with `Idempotency-Key`. |

The reviewer must paste a server-configured token manually. It is kept in React memory only, sent only as `X-ScamFlow-Reviewer-Token`, never placed in a URL or request body, and reviewer API requests omit browser cookie credentials. The backend administrator must configure `SCAMFLOW_REVIEWER_TOKEN` server-side; this package contains no token or secret. Missing/invalid tokens, unconfigured reviewer access, unavailable/expired requests, and network errors are surfaced without fabricating reviewer data. Evidence excerpts are highlighted only when their backend code-point offsets exactly match the supplied source text.

Reviewer resolution changes only the persisted workflow request status; it does not alter the assessment, its risk state, or evidence. The backend exposes no owner endpoint to list a case's review requests, so after a full reload the frontend cannot rediscover the request ID and its owner status unless that ID is otherwise available. The reviewer queue lists open requests only, not a history of resolved requests. A stored request does not guarantee that a person has been notified or will respond; this frontend does not claim otherwise.

The verified API has no clarification-answer operation and assesses persisted case revisions only, not an arbitrary revealed-message prefix. Those capabilities remain unavailable in the UI, and no unsupported request is sent. The UI can retain results observed during the current frontend session; the backend exposes only the latest-assessment endpoint, not an assessment-list endpoint. A `?case={case_id}` deep link loads through existing case and latest-assessment routes; stale responses from an earlier deep link are ignored.

## Configuration

Copy `.env.example` to `.env.local` only if needed. Set `VITE_API_BASE_URL` to the backend origin/base path; leave it empty if the app and API share an origin. The browser origin must be trusted by the backend CSRF policy. Never commit `.env.local` or place service-role keys, secret API keys, reviewer tokens, or session secrets in frontend variables.

## Test coverage and import behavior

The repository keeps both the original `src/` tests and the current `tests/` suite enabled. TypeScript type-checks the application and test configuration, and Playwright is installed only as a development dependency.

Final QA commands to run from this package directory (not run during this phase):

```sh
npm ci
npm test
npm run build
```
