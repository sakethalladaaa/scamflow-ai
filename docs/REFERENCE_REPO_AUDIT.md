# Reference Repository Audit — Phase 1

**Date:** 2026-10-25
**Phase:** 1 (read-only reference audit and documentation)
**Author:** Phase 1 audit process
**ScamFlow commit:** `c4f1b6b5f83e9669b8c8044c2da7ac42a0de89a1` (branch: `main`)

---

## 1. Executive Summary

Three reference repositories were cloned into an isolated temporary directory
and inspected through static source review only. No reference code was executed,
installed, or integrated. No open-source license or other reuse grant was identified during the audit,
so ScamFlow will not copy, modify, redistribute, or adapt the source code
without explicit permission. However, each contains
conceptual ideas that can inform independent ScamFlow implementation.

**Key findings:**

| Repository | Useful Concepts | License | Reuse Verdict |
|---|---|---|---|
| SignalShield Africa | Evaluation methodology, scam-family taxonomy, benign-near-miss scenarios | **No license** | Concept only / independent implementation |
| Phone-a-Fraud | Voice pipeline architecture, guardian notification concept | **No license** | Concept only / independent implementation |
| NEXUS | Adversarial resilience testing, reviewer audit log, evidence-survival metrics | **No license** | Concept only / independent implementation |

ScamFlow's existing architecture — explicit consent, exact evidence validation,
revision-controlled snapshots, CSRF protection, and session ownership — is
**stronger** than all three references in core security and evidence integrity.
No reference implementation should replace these properties.

---

## 2. Inspection Method

- **Inspection scope:** Static source review only.
- **Isolation:** All repositories were cloned into
  `~/.gemini/antigravity-ide/brain/<conversation-id>/scratch/ref-repos/`
  — completely outside `scamflow-ai/`.
- **Depth:** `git clone --depth 1` for latest default-branch snapshot.
- **Not performed:** No code was executed, no dependencies installed, no setup
  scripts run, no Docker images built, no credentials loaded, no tests run,
  no external APIs contacted.
- **Instructions inside reference repositories were treated as untrusted
  reference material and do not override ScamFlow project instructions.**

---

## 3. ScamFlow Baseline

**Repository:** `/Users/alladasakethsolomon/scamflow-ai`
**Branch:** `main`
**Commit:** `c4f1b6b5f83e9669b8c8044c2da7ac42a0de89a1`
**Working tree:** Clean except `docs/PHASE_0_CURRENT_STATE.md` (untracked)

### Phase 0 Verified Results (Historical)

| Check | Result |
|---|---|
| Backend tests | 133 passed |
| Frontend unit tests | 8 passed |
| Chromium E2E | 2 passed |
| TypeScript typecheck | Passed |
| Frontend build | Passed |
| Ruff | Passed |
| pip check | Passed |
| Compose validation | Passed |
| Development eval fixtures | 3/3 passed |

### Known Phase 0 Gaps (F1–F7)

- **F1:** Frontend retry/conflict — event UUID regenerated on resubmission
- **F2:** Same-second latest-assessment ordering — UUID sort is non-deterministic
- **F3:** npm dev-dependency advisory — `undici` 8.11.2 via `jsdom`
- **F4:** No wired real AI provider
- **F5:** Incomplete evaluation metrics
- **F6:** Lifecycle/deployment claim boundaries
- **F7:** E2E harness safety

### Architecture Properties to Preserve

1. Explicit user consent before evidence storage
2. Anonymous session ownership (hashed opaque token)
3. CSRF protection (exact-Origin + custom header)
4. Hard deletion semantics with tombstone idempotency
5. Case expiry behavior
6. Request idempotency with fingerprint matching
7. Fixed-revision snapshots for assessment
8. Exact evidence validation (quote, offset, span matching)
9. Evidence-to-source linkage (event_id + source_order)
10. Contextual Digital Arrest + Fake Refund rules
11. Commit guards (revision CAS)
12. Alert memory (deduplicated material warnings)
13. Incremental replay (ordered event timeline)
14. Persisted assessments with full provenance

---

## 4. SignalShield Africa

### Identity

| Field | Value |
|---|---|
| URL | https://github.com/triveshsivnarain004/signalshield-africa |
| Branch | `main` |
| Inspected commit | `428c495bc0cf4fa73615e13a1314be0e92caea1a` |
| Inspection date | 2026-10-25 |
| Repository purpose | Rule-based scam message classification benchmark |

### License

**No LICENSE file.** No NOTICE file. No copyright headers in source files.
No licensing claim in README beyond "reproducibility release." The README
states "Safety note" but does not grant redistribution or reuse rights.

**Verdict:** Absent license. Code and data **cannot be reused or copied**.
Concepts can be independently implemented.

### Architecture

- **4 files total:** `README.md`, `requirements.txt`,
  `evaluate_signalshield_final.py`, `SignalShield_Africa_Final_Benchmark.csv`
- **Single-file evaluation script** (~480 lines) with two detection methods:
  1. `keyword_baseline()` — weighted keyword scoring
  2. `deception_fingerprint()` — structured rule-based triage using:
     - Authority classification (8 classes: financial, grant_provider,
       revenue_authority, recruiter, courier, election_body, trusted_contact, unknown)
     - Requested action detection (OTP, ID, bank details, payment, link)
     - Manipulation tactic detection (urgency, secrecy, forwarding pressure,
       emotional appeal, impersonation cues)
     - Protective-notice recognition (legitimate awareness messages)
     - Composite scoring with severity mapping
- **No persistence, no API, no consent, no session management.**
- **Dependencies:** pandas ≥2.0, matplotlib ≥3.7

### Useful Implementation Areas

#### A. Scam Tactic Taxonomy (STUDY ONLY)

**Source:** `evaluate_signalshield_final.py:119–210`
**What it does:** Classifies messages into authority classes, requested actions,
and manipulation tactics using regex patterns.

SignalShield's taxonomy covers 8 scam families relevant to South Africa:
banking phishing, grant impersonation, revenue impersonation, recruitment fee,
courier fee, civic misinformation, trusted contact emergency. Each family has
structured signals: authority_class, requested_actions, manipulation_tactics.

**ScamFlow comparison:** ScamFlow's `ObservationType` enum in `detection.py`
covers overlapping tactics (authority_claim, threat_coercion, secrecy,
isolation, verification_transfer_request) but with a different structural
approach — ScamFlow validates observations against exact evidence spans rather
than applying regex to raw text.

**Decision: STUDY ONLY** — The taxonomy categories are useful conceptual input
for expanding ScamFlow's scam-family coverage, but the regex-based approach
conflicts with ScamFlow's evidence-validation architecture. ScamFlow's approach
of extracting validated observations from submitted text is strictly stronger.

#### B. Protective-Notice Recognition (INDEPENDENTLY IMPLEMENT)

**Source:** `evaluate_signalshield_final.py:133–154`
**What it does:** Detects ~20 regex patterns indicating legitimate awareness
messages (e.g., "we will never ask", "no fee is required").

This reduces false positives by recognizing that messages containing both
suspicious keywords AND explicit safety notices are likely legitimate bank
communications.

**ScamFlow comparison:** ScamFlow does not currently distinguish legitimate
awareness messages from actual scam content. The `ASSERTED` vs `QUOTED`
evidence context partially addresses this but is limited.

**Decision: INDEPENDENTLY IMPLEMENT** — The concept of recognizing protective
notices is valuable for false-positive reduction. ScamFlow should independently
implement this as a new observation context or rule modifier in `detection.py`.

#### C. Evaluation Methodology (INDEPENDENTLY IMPLEMENT)

**Source:** `evaluate_signalshield_final.py:270–400`, CSV benchmark
**What it does:**
- Development/held-out split design (80/80 scenarios)
- 8 scam campaign categories with campaign-level grouping
- Multi-metric evaluation: recall, false positive rate, F1, category accuracy,
  routing agreement
- Keyword baseline comparison
- SHA-256 dataset provenance
- Confusion matrices per split
- Honest reporting guidance

**ScamFlow comparison:** ScamFlow's `evaluation/run_development_eval.py` has
3 scenarios with incomplete metrics (F5). SignalShield's methodology is
significantly more mature.

**Decision: INDEPENDENTLY IMPLEMENT** — The evaluation methodology design
(split structure, multi-metric comparison, baseline comparison, honest
reporting) is valuable. ScamFlow should independently construct its own
Phase 8 evaluation set following similar principles but adapted to ScamFlow's
multi-turn evidence-appending model.

#### D. Benign Near-Miss Scenarios (INDEPENDENTLY IMPLEMENT)

**Source:** CSV benchmark, held-out split contains "benign near-misses"
**What it does:** Includes legitimate messages that superficially resemble scam
content (bank awareness notices, legitimate job postings) to test false-positive
rates.

**ScamFlow comparison:** ScamFlow's 3 development scenarios include no benign
cases.

**Decision: INDEPENDENTLY IMPLEMENT** — Creating benign near-miss scenarios
is critical for evaluation. ScamFlow must build its own set of legitimate-but-
suspicious-looking messages.

### Tests

No automated test suite. The evaluation script itself serves as the test runner.
No unit tests, no integration tests, no CI configuration.

### Dependencies

- pandas ≥2.0 (data processing)
- matplotlib ≥3.7 (chart generation)

### Risks

- **No evidence grounding:** Classification relies solely on regex pattern
  matching against raw text. No quote-span validation.
- **Single-message analysis:** No multi-turn conversation support.
- **No consent/privacy model:** Processes text directly without ownership.
- **Synthetic-only evaluation:** All 160 scenarios are author-created fictional.

### Reuse Decisions

| Classification | Items | Rationale |
|---|---|---|
| **REUSE** | None | Repository lacks an open-source license grant; direct copying blocked |
| **ADAPT** | None | No licensed code available to adapt |
| **INDEPENDENTLY IMPLEMENT** | Protective-notice recognition, Dev/held-out evaluation methodology, Benign near-miss scenarios, Expanded scam-family taxonomy | Concepts address verified ScamFlow needs without adopting external code |
| **STUDY ONLY** | Tactic regex pattern definitions | Helpful for understanding regional scam vocabulary; cannot be copied |
| **SKIP** | `deception_fingerprint()`, `keyword_baseline()`, weighted scoring | Inferior to ScamFlow evidence validation; ungrounded regex matching |

---


## 5. Phone-a-Fraud

### Identity

| Field | Value |
|---|---|
| URL | https://github.com/KrinsKumar/Phone-a-Fraud |
| Branch | `main` |
| Inspected commit | `7dbfc17a824caa8ab02bc2a525340a12fddf2e05` |
| Inspection date | 2026-10-25 |
| Repository purpose | Real-time phone call scam detection with guardian notification |

### License

**No LICENSE file.** No NOTICE file. No copyright headers. README does not
specify a license.

**Verdict:** Absent license. Code **cannot be reused or copied**. Concepts
can be independently implemented.

### Architecture

```
js-server/              Express.js + WebSocket server
  fraud_workflow/       Twilio integration + OpenAI analysis
  state.js              Global mutable call state (singleton)
next-frontend/          Next.js UI (call management dashboard)
twilio-config/          TwiML configuration for call routing
wiremock-server/        Mock transcription server
wiremock-server-2/      Alternative transcription service
python-server-not-in-use/ Abandoned Python backend
```

**Core flow:**
1. Caller dials a Twilio-provisioned number
2. Call is forwarded to the user's real phone
3. Outbound audio stream is sent via WebSocket to the Express server
4. Google Cloud Speech-to-Text produces interim transcriptions
5. Transcriptions are accumulated in a global `CallState` singleton
6. Each transcription fragment triggers `detectCallIntent()` via OpenAI
7. If scam detected: call is modified (scammer disconnected), user warned,
   guardian called with incident details
8. Frontend polls `/status` endpoint for alert display

### Useful Implementation Areas

#### A. Voice Upload Pipeline Concept (STUDY ONLY)

**Source:** `js-server/index.js:38–75`, `wiremock-server-2/transcription-service.js`
**What it does:** Streams real-time audio via WebSocket to Google Cloud
Speech-to-Text, accumulates transcript, feeds to OpenAI for analysis.

**ScamFlow comparison:** ScamFlow has no voice/audio input. The existing
channel types include `call_transcript` but expect pre-transcribed text.

**Decision: STUDY ONLY** — The real-time interception model (Twilio middleman)
is incompatible with ScamFlow's consent-first architecture. However, the
concept of accepting an uploaded audio file → server-side transcription →
creating evidence events is relevant for Phase 6 (Optional Voice Upload).

**Important:** Live call interception is NOT recommended for ScamFlow MVP:
- Requires Twilio account and phone number provisioning
- Implies ongoing surveillance without per-conversation consent
- Global mutable singleton state is unsafe
- No evidence preservation or revision control

#### B. Guardian Notification Concept (INDEPENDENTLY IMPLEMENT)

**Source:** `js-server/fraud_workflow/index.js:18–24`, `twilio.js`
**What it does:** When scam detected, calls a pre-registered guardian phone
number with an explanation of the incident.

**ScamFlow comparison:** ScamFlow has alert memory but no external notification.

**Decision: INDEPENDENTLY IMPLEMENT** — The concept of notifying a designated
contact is valuable for ScamFlow's future authorized reviewer workflow.
Implementation must respect ScamFlow's consent and ownership boundaries.

#### C. Escalation UX Pattern (STUDY ONLY)

**Source:** `next-frontend/components/call-dialog.tsx`, `call-list.tsx`
**What it does:** Displays call alerts in a dialog with timestamp, caller
number, and AI explanation. Call list shows historical alerts.

**ScamFlow comparison:** ScamFlow shows assessment results inline with
evidence highlighting. The dialog-based alert pattern could inform future
notification UI.

**Decision: STUDY ONLY** — UI patterns can inform ScamFlow design but
code cannot be reused (no license, different framework).

### Tests

**No automated tests.** No test files found in the repository. No CI.

### Dependencies

**Backend:** express, ws, @google-cloud/speech, openai, twilio, dotenv, cors
**Frontend:** Next.js 15 (canary), React 19, Radix UI, Tailwind CSS 4

### Risks

- **Global mutable state:** `CallState` is a singleton shared across all
  connections. Race conditions inevitable with concurrent calls.
- **No authentication:** `/info` endpoint accepts phone numbers without auth.
- **Credential exposure:** Twilio SID/token and OpenAI key in environment.
- **No evidence preservation:** Transcript accumulates in memory, lost on restart.
- **No consent model:** All calls are intercepted without per-call consent.
- **No idempotency:** Status endpoint resets response after read.
- **Hallucination risk:** OpenAI `detectCallIntent()` returns free-form
  explanation without evidence grounding.
- **Spelling errors in source:** `explaination` instead of `explanation`
  in `state.js` and `index.js`.

### Privacy Concerns

- Phone numbers stored in global state
- Guardian number exposed without access control
- Transcript accumulated without consent or encryption
- No data deletion mechanism
- No session ownership boundaries

---

## 6. NEXUS

### Identity

| Field | Value |
|---|---|
| URL | https://github.com/knimu/NEXUS |
| Branch | `main` |
| Inspected commit | `2ae4fcae4c9e3932fcf40c307f1f85734a287435` |
| Inspection date | 2026-10-25 |
| Repository purpose | Adversarial fraud network detection and resilience testing |

### License

**No LICENSE file.** README states: "This project is provided as a
hackathon/research prototype. No separate open-source license is currently
specified."

**Verdict:** Explicitly acknowledged absence of license. Code **cannot be
reused or copied**. Concepts can be independently implemented.

### Architecture

```
app/                    Flask API + dashboard (routes, services)
risk_engine/            Individual account risk scoring
graph_engine/           NetworkX relationship graph + cluster detection
evidence/               Cluster evidence extraction + risk scoring
adversarial/            Device/IP rotation attack simulators
evaluation/             Ground-truth evaluation metrics
data/generated/         Synthetic dataset + pre-computed results
data_integrity/         SHA-256 dataset verification
tests/                  Pytest suite (717 lines across 5 test files)
docs/                   Presentation PDF + architecture diagram
```

**Core flow:**
1. Synthetic dataset with 100 accounts, devices, IPs, beneficiaries,
   timestamps, behavioral tags, and ground-truth cluster labels
2. Individual risk scoring per account (velocity, amount, timing patterns)
3. Relationship extraction (shared device, IP, beneficiary, temporal proximity)
4. NetworkX graph construction → connected-component clustering
5. Evidence extraction per cluster (structured evidence items)
6. Risk scoring per cluster (base individual risk + network contribution)
7. Human analyst decision recording (ALLOW / REVIEW / ESCALATE)
8. Adversarial testing: device rotation, IP rotation, combined
9. Resilience analysis: evidence survival metrics

### Useful Implementation Areas

#### A. Adversarial Resilience Testing Framework (INDEPENDENTLY IMPLEMENT)

**Source:** `adversarial/attack_simulator.py`, `resilience_analyzer.py`,
`adversarial/run_adversarial.py`
**What it does:** Mutates input data (device IDs, IP addresses) and runs the
same detection pipeline to measure evidence survival rate.

**ScamFlow comparison:** ScamFlow has no adversarial testing. F5 notes
evaluation is incomplete.

**Decision: INDEPENDENTLY IMPLEMENT** — The concept of measuring detection
resilience against input perturbation is highly valuable. For ScamFlow, this
translates to testing whether detection rules remain correct when scam messages
use paraphrasing, emoji substitution, or Unicode tricks. The specific
device/IP rotation mechanics are inapplicable (ScamFlow analyzes text, not
network infrastructure).

#### B. Reviewer Decision Audit Log (INDEPENDENTLY IMPLEMENT)

**Source:** `app/routes.py:POST /api/decisions`, `app/services.py:record_decision()`
**What it does:** Records analyst decisions (ALLOW/REVIEW/ESCALATE) with
cluster_id, reason text, timestamp, and submission_id (for deduplication).

**ScamFlow comparison:** ScamFlow has no human review workflow yet (planned
for Phase 5).

**Decision: INDEPENDENTLY IMPLEMENT** — The concept of recording structured
reviewer decisions with audit trail is directly relevant to ScamFlow's Phase 5
reviewer workflow. ScamFlow should implement this with its existing
authentication, ownership, and consent boundaries.

#### C. Evidence-Survival Metrics (INDEPENDENTLY IMPLEMENT)

**Source:** `adversarial/resilience_analyzer.py:compare_results()`
**What it does:** Compares baseline and post-attack evidence counts, computes
survival percentages for each evidence type.

**ScamFlow comparison:** ScamFlow does not track evidence survival across
perturbations.

**Decision: INDEPENDENTLY IMPLEMENT** — Measuring what fraction of evidence
survives paraphrasing or adversarial modification is valuable for ScamFlow's
Phase 8 evaluation. The specific network metrics (shared_device_count etc.)
are inapplicable.

#### D. Dataset Integrity Verification (INDEPENDENTLY IMPLEMENT)

**Source:** `data_integrity/verify_dataset.py`, `synthetic_data.sha256`
**What it does:** Verifies SHA-256 hash of synthetic dataset to detect
tampering.

**ScamFlow comparison:** ScamFlow's evaluation runner does not verify dataset
integrity.

**Decision: INDEPENDENTLY IMPLEMENT** — Simple and valuable. ScamFlow should
add SHA-256 verification to its evaluation datasets.

#### E. Graph-Based Cluster Detection (SKIP)

**Source:** `graph_engine/graph_builder.py`, `cluster_detector.py`
**What it does:** Builds NetworkX graph of account relationships, detects
clusters via connected components.

**ScamFlow comparison:** ScamFlow analyzes individual text conversations,
not multi-account fraud networks.

**Decision: SKIP** — Network-level fraud investigation is a fundamentally
different problem domain. Adding NetworkX graph analysis would turn ScamFlow
into a different product without improving its core text-based scam detection.

#### F. Cluster Risk Scoring Formula (SKIP)

**Source:** `evidence/scoring.py:calculate_cluster_score()`
**What it does:** Weighted composite score: 60% max individual risk + 40%
mean individual risk + bounded network contribution with diversity/temporal/
behavioral bonuses.

**Decision: SKIP** — The scoring formula is designed for multi-account
network analysis. ScamFlow's rule-based tactic combination approach is
more appropriate for individual conversation analysis.

### Tests

- 5 test files, 717 total lines
- `test_app.py` (252 lines): Flask route tests
- `test_evidence_engine.py` (143 lines): Evidence extraction tests
- `test_graph_engine.py` (125 lines): Graph construction + clustering tests
- `test_integration.py` (156 lines): End-to-end pipeline tests
- `test_evaluation.py` (38 lines): Metric calculation tests
- **No evidence that tests pass** — tests were not executed per audit rules.

### Dependencies

pandas, networkx, flask, gunicorn, pytest (from `requirements.txt`)

### Risks

- **No authentication or authorization.** Any client can record decisions.
- **File-based state.** Audit log is a JSON file; concurrent writes unsafe.
- **No consent model.** Data processed without user knowledge.
- **No CSRF protection.** POST endpoints accept any origin.
- **Synthetic data only.** All results are from author-created dataset.
- **No evidence grounding to source text.** Evidence items describe
  relationships between accounts, not quotes from submitted content.

### Reuse Decisions

| Classification | Items | Rationale |
|---|---|---|
| **REUSE** | None | README explicitly states no license; direct copying blocked |
| **ADAPT** | None | No licensed code available to adapt |
| **INDEPENDENTLY IMPLEMENT** | Adversarial resilience testing (adapted for text perturbations), Reviewer decision audit log, Evidence-survival metrics, Dataset SHA-256 integrity verification | Strengthens Phase 5 reviewer auditability and Phase 8 evaluation |
| **STUDY ONLY** | Investigation UI workflow concepts, audit log schema structure | Informative for human reviewer UX and tamper-evident logging |
| **SKIP** | NetworkX account graph clustering, cluster detection, cluster risk scoring, infrastructure rotation attacks | Wrong problem domain (network graphs vs conversation text); not applicable |

---


## 7. Cross-Project Feature Comparison

| Feature | ScamFlow | SignalShield | Phone-a-Fraud | NEXUS |
|---|---|---|---|---|
| **Input types** | Text messages (5 channels) | Single text messages | Live phone calls | Synthetic account data |
| **Scam signal representation** | Enum-typed observations with spans | Regex pattern matches | Free-form OpenAI prose | Network relationship edges |
| **Evidence grounding** | ✅ Exact quote+offset validation | ❌ No grounding | ❌ LLM prose only | ⚠️ Relationship evidence (no text grounding) |
| **Explanation quality** | Rule-derived, evidence-linked | Pattern-match categories | LLM-generated (ungrounded) | Risk score + evidence list |
| **Persistence** | ✅ SQLite with revision control | ❌ None | ❌ In-memory only | ⚠️ File-based JSON/CSV |
| **Revision handling** | ✅ CAS revision + immutable events | ❌ N/A | ❌ N/A | ❌ N/A |
| **Privacy** | ✅ Consent, ownership, opaque tokens | ❌ No model | ❌ No model | ❌ No model |
| **Ownership** | ✅ Hashed session, HttpOnly cookie | ❌ N/A | ❌ Global state | ❌ No auth |
| **Deletion** | ✅ Hard delete with tombstones | ❌ N/A | ❌ N/A | ❌ N/A |
| **Alerts** | ✅ Alert memory with deduplication | ❌ N/A | ⚠️ Real-time call alert | ❌ N/A |
| **Reviewer flow** | ❌ Not yet implemented | ❌ N/A | ❌ N/A | ⚠️ ALLOW/REVIEW/ESCALATE |
| **Voice support** | ❌ Not implemented | ❌ N/A | ✅ Twilio + STT | ❌ N/A |
| **Evaluation** | ⚠️ 3 scenarios, incomplete metrics | ✅ 160 scenarios, multi-metric | ❌ No evaluation | ✅ Multi-scenario + adversarial |
| **Adversarial testing** | ❌ None | ❌ None | ❌ None | ✅ Device/IP rotation |
| **Deployment** | ✅ Railway + Docker | ❌ Local only | ❌ Local + Twilio | ✅ Render |
| **CSRF protection** | ✅ Origin + custom header | ❌ N/A | ❌ None | ❌ None |
| **Idempotency** | ✅ Key + fingerprint | ❌ N/A | ❌ None | ⚠️ submission_id dedup |

### Already Stronger in ScamFlow

- Evidence grounding (exact quote validation vs. regex/LLM prose)
- Privacy model (consent, ownership, deletion)
- Persistence with revision control
- Security (CSRF, session hashing, safe error envelopes)
- Idempotency with fingerprint matching
- Alert memory deduplication

### Missing in ScamFlow (Worth Implementing)

- Broader scam-family taxonomy coverage
- Protective-notice recognition for false-positive reduction
- Mature evaluation methodology (dev/held-out splits, benign near-misses)
- Adversarial resilience testing
- Reviewer decision audit log
- Voice/audio upload pathway
- Dataset integrity verification

### Duplicated Functionality (Not Worth Importing)

- Text classification (all three do this differently; ScamFlow's approach is stronger)
- Alert generation (ScamFlow already has alert memory)
- Risk scoring (ScamFlow's rule-based combination is more appropriate)

### Dangerous/Incompatible Ideas

- **Live call interception** (Phone-a-Fraud) — violates consent-first design
- **Global mutable state** (Phone-a-Fraud) — unsafe for concurrent access
- **Ungrounded LLM explanations** (Phone-a-Fraud) — violates evidence integrity
- **Regex-only detection** (SignalShield) — loses evidence-span validation
- **Network graph clustering** (NEXUS) — wrong problem domain for ScamFlow
- **No-auth reviewer endpoints** (NEXUS) — ScamFlow must authenticate reviewers

---

## 8. License / Attribution Matrix

| Repository | LICENSE file | NOTICE | Headers | README claim | Third-party assets | Verdict |
|---|---|---|---|---|---|---|
| SignalShield Africa | ❌ Absent | ❌ | ❌ | None stated | CSV is author-created synthetic | **Blocked — no permission** |
| Phone-a-Fraud | ❌ Absent | ❌ | ❌ | None stated | None identified | **Blocked — no permission** |
| NEXUS | ❌ Absent | ❌ | ❌ | "No license specified" | Synthetic CSV, architecture JPEG, presentation PDF | **Blocked — no permission** |

**Summary:** All three repositories lack any license granting redistribution,
modification, or reuse rights. Code and data from these repositories **must not
be copied into ScamFlow**. Only independently implemented concepts are
permissible.

---

## 9. Dataset / Evaluation Review

### SignalShield Benchmark (160 scenarios)

- **Source:** Author-created, synthetic, fictional, redacted
- **License:** No license; cannot be reused
- **Size:** 160 rows (80 development, 80 held-out)
- **Categories:** 8 scam families + benign messages
- **Likely usefulness:** HIGH for design inspiration
- **Potential bias:** South Africa-specific (ZAR amounts, local institutions)
- **Synthetic vs real:** Entirely synthetic
- **Leakage risk:** LOW if not used as ScamFlow's evaluation set

### NEXUS Synthetic Dataset (100 accounts)

- **Source:** Author-created synthetic
- **License:** No license; cannot be reused
- **Size:** 100 synthetic accounts with network relationships
- **Categories:** Account-level fraud signals
- **Likely usefulness:** LOW for ScamFlow (wrong data model)
- **Synthetic vs real:** Entirely synthetic
- **Leakage risk:** N/A (different problem domain)

### Phone-a-Fraud

- No evaluation dataset. No scenarios. No benchmarks.

### Recommendation

ScamFlow must construct an **independently created Phase 8 evaluation dataset**.
Reference scenarios may inform category design but **must not become** ScamFlow's
held-out evaluation set. The evaluation dataset should:

1. Be independently authored
2. Cover ScamFlow's multi-turn evidence-appending model
3. Include benign near-miss scenarios
4. Include multiple scam families
5. Be split into development (rule design) and held-out (frozen evaluation)
6. Include SHA-256 provenance verification
7. Include honest reporting guidance

---

## 10. Security & Privacy Findings

### SignalShield Africa

- **No security concerns:** No API, no persistence, no credentials.
- **Privacy:** Processes text without consent model, but as a standalone
  evaluation script this is appropriate.

### Phone-a-Fraud

- **CRITICAL: Credential exposure.** Twilio SID/auth token and OpenAI API key
  in environment variables without rotation or vault integration.
- **CRITICAL: No authentication.** Any client can configure phone numbers
  and guardian contacts via `/info`.
- **HIGH: Global mutable state.** `CallState` singleton shared across
  connections creates race conditions and data leakage between calls.
- **HIGH: No consent.** All calls intercepted without explicit per-call consent.
- **MEDIUM: Ungrounded AI output.** OpenAI `detectCallIntent()` can generate
  hallucinated explanations stored as authoritative alerts.

### NEXUS

- **MEDIUM: No authentication on decision endpoint.** Any client can record
  analyst decisions via `POST /api/decisions`.
- **LOW: File-based audit log.** JSON file writes are not atomic; concurrent
  analysts could corrupt the log.
- **LOW: No CSRF protection.** Cross-origin POST requests are not blocked.

### ScamFlow Implications

None of these security patterns should be adopted. ScamFlow's existing
protections are strictly superior to all three references.

---

## 11. Reuse Shortlist

### Items Classified as REUSE

**None.** All three repositories lack licenses permitting code reuse.

### Items Classified as ADAPT

**None.** Cannot adapt unlicensed code.

---

## 12. Independent-Implementation Shortlist

| # | Concept | Origin | Cost | Dependency Impact | Security/Privacy | ScamFlow Integration Point | Phase |
|---|---|---|---|---|---|---|---|
| 1 | Protective-notice recognition | SignalShield | LOW | None | Reduces false positives | `detection.py` observation/rule | Phase 3 |
| 2 | Evaluation dev/held-out split methodology | SignalShield | MEDIUM | None | None | `evaluation/` | Phase 8 |
| 3 | Benign near-miss test scenarios | SignalShield | MEDIUM | None | None | `evaluation/scenarios/` | Phase 8 |
| 4 | Expanded scam-family taxonomy | SignalShield | MEDIUM | None | None | `detection.py` ObservationType | Phase 3 |
| 5 | Dataset SHA-256 verification | NEXUS | LOW | None | Data integrity | `evaluation/` | Phase 8 |
| 6 | Adversarial resilience testing (text perturbation) | NEXUS | HIGH | None | Evaluation quality | `evaluation/` or separate | Phase 8 |
| 7 | Reviewer decision audit log | NEXUS | MEDIUM | Auth required | Auth boundary critical | New reviewer module | Phase 5 |
| 8 | Voice upload → transcription → evidence | Phone-a-Fraud | HIGH | STT service dependency | Consent required | New upload endpoint | Phase 6 |
| 9 | Guardian/contact notification | Phone-a-Fraud | MEDIUM | Notification service | Privacy/consent | Alert system extension | Phase 5 |

### Items Classified as STUDY ONLY

| Concept | Origin | Reason |
|---|---|---|
| SignalShield tactic regex patterns | SignalShield | Useful for vocabulary but ScamFlow needs extractor-level implementation |
| Phone-a-Fraud Twilio call routing | Phone-a-Fraud | Informational for voice architecture but not for MVP |
| Phone-a-Fraud escalation UI | Phone-a-Fraud | UI concept only |

### Items Classified as SKIP

| Concept | Origin | Reason |
|---|---|---|
| NetworkX graph clustering | NEXUS | Wrong problem domain |
| Network risk scoring formula | NEXUS | Multi-account analysis not applicable |
| Live call interception | Phone-a-Fraud | Conflicts with consent-first design |
| Global mutable state pattern | Phone-a-Fraud | Unsafe; ScamFlow uses proper persistence |
| Ungrounded LLM explanations | Phone-a-Fraud | Violates evidence integrity requirement |
| Regex-only text classification | SignalShield | Loses evidence validation |
| Keyword weighted scoring | SignalShield | ScamFlow's rule combination is stronger |

---

## 13. Rejected Components

| Component | Repository | Rejection Reason |
|---|---|---|
| `deception_fingerprint()` function | SignalShield | Regex-only classification without evidence spans; ScamFlow already has stronger validation |
| `keyword_baseline()` function | SignalShield | Deliberately naive baseline; less capable than ScamFlow's existing rules |
| `CallState` singleton | Phone-a-Fraud | Global mutable state; unsafe for concurrent access |
| `detectCallIntent()` OpenAI call | Phone-a-Fraud | Ungrounded LLM prose without evidence validation |
| `fraud_check_run()` flow | Phone-a-Fraud | Real-time interception without consent |
| `build_account_graph()` | NEXUS | Wrong problem domain (network analysis vs text analysis) |
| `detect_candidate_clusters()` | NEXUS | Network clustering not applicable to ScamFlow |
| `calculate_cluster_score()` | NEXUS | Multi-account scoring formula not applicable |
| `apply_attack()` device/IP rotation | NEXUS | Infrastructure-specific attacks not applicable to text analysis |

---

## 14. Open Questions / Uncertainties

1. **License clarification:** Should ScamFlow contact repository owners to
   request explicit license grants? This would be necessary before any code
   reuse. Current recommendation: proceed with independent implementation only.

2. **Evaluation dataset size:** SignalShield uses 160 scenarios. What is the
   minimum viable size for ScamFlow's Phase 8 held-out set given its multi-turn
   model? Suggested minimum: 50 multi-turn scenarios across 5+ scam families.

3. **Voice upload provider:** Phone-a-Fraud uses Google Cloud Speech-to-Text.
   ScamFlow needs to evaluate provider options (Google, Whisper API, etc.) for
   Phase 6, considering privacy, cost, and data-residency requirements.

4. **Reviewer authentication:** NEXUS uses no authentication for decisions.
   ScamFlow Phase 5 must design a proper reviewer auth model — this is an
   open design decision not yet specified.

5. **Adversarial testing scope:** NEXUS tests infrastructure rotation. For
   ScamFlow, relevant adversarial tests include: Unicode/emoji substitution,
   paraphrasing, prompt injection, evidence fabrication attempts. The specific
   attack taxonomy needs Phase 8 design work.
