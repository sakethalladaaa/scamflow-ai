export type Channel = 'SMS' | 'WhatsApp' | 'Call transcript' | 'Email' | 'Other text';
export type AssessmentState = 'high_risk' | 'review' | 'no_strong_indicators' | 'unable_to_assess';
export type ExtractionMode = string;
export interface Message { id: string; order: number; sender: string; channel: Channel; text: string; }
export interface Evidence { messageId: string; quote: string; reason: string; startOffset?: number; endOffset?: number; }
export interface Assessment { id: string; revision: number; state: AssessmentState; reasons: string[]; evidence: Evidence[]; nextAction: string; limitations: string[]; extractionMode: ExtractionMode; isCurrent?: boolean; alert?: { visible: boolean; reason: string; priorWarningState?: string | null }; questions?: string[]; }
export interface CaseRecord { id: string; revision: number; channel: Channel; messages: Message[]; amount?: string; currency?: string; requestedAction?: string; recipient?: string; current?: Assessment; history: Assessment[]; answers: string[]; assessmentFailure?: string; }
export interface NewCase { channel: Channel; conversation: string; amount?: string; currency?: string; requestedAction?: string; recipient?: string; }
export type ReviewOutcome = 'follow_up' | 'escalated' | 'no_action' | 'inconclusive';
export type BackendAssessmentState = 'high_risk_indicators' | 'needs_clarification_or_review' | 'no_strong_indicators' | 'unable_to_assess';
export interface ReviewRequestStatus { reviewRequestId: string; caseId: string; assessmentId: string; assessedRevision: number; status: 'open' | 'resolved'; submittedAt: string; resolvedAt: string | null; outcome: ReviewOutcome | null; }
export interface CreatedReviewRequest extends ReviewRequestStatus { idempotentReplay: boolean; existingOpenRequest: boolean; }
export interface ReviewerQueueItem { reviewRequestId: string; caseId: string; assessmentId: string; assessedRevision: number; assessmentState: BackendAssessmentState; isCurrent: boolean; submittedAt: string; }
export interface ReviewerQueue { items: ReviewerQueueItem[]; total: number; limit: number; offset: number; }
export interface ReviewerEvidence { tactic: string; eventId: string; sourceOrder: number; quote: string; startOffset: number; endOffset: number; context: string; channel: BackendChannel; sourceText: string; }
export interface ReviewerAssessment { assessmentId: string; caseId: string; assessedRevision: number; state: BackendAssessmentState; reasonCodes: string[]; explanation: string; evidence: ReviewerEvidence[]; alert: { visible: boolean; reason: string; priorWarningState: string | null }; tacticsUsed: string[]; relationships: string[]; suggestedNextAction: string; limitations: string[]; extractionMode: string; extractionVersion: string; ruleVersion: string; schemaVersion: string; createdAt: string; isCurrent: boolean; paymentContext: { statedPurpose: string; amount: string | null; recipientReference: string | null }; }
export interface ReviewerDetail extends ReviewRequestStatus { reviewerNote: string | null; assessment: ReviewerAssessment; }
export interface ResolvedReviewRequest extends ReviewRequestStatus { reviewerNote: string | null; idempotentReplay: boolean; }
export interface ApiAdapter { createCase(input: NewCase): Promise<CaseRecord>; getCase(id: string): Promise<CaseRecord>; appendMessage(id: string, text: string, expectedRevision: number): Promise<CaseRecord>; addClarification(id: string, answers: string[], expectedRevision: number): Promise<CaseRecord>; assess(id: string, expectedRevision: number, messages?: Message[]): Promise<CaseRecord>; createReviewRequest(caseId: string, assessmentId: string, expectedRevision: number): Promise<CreatedReviewRequest>; getOwnerReviewRequest(caseId: string, reviewRequestId: string): Promise<ReviewRequestStatus>; getReviewerQueue(token: string, limit: number, offset: number): Promise<ReviewerQueue>; getReviewerDetail(token: string, reviewRequestId: string): Promise<ReviewerDetail>; resolveReviewerRequest(token: string, reviewRequestId: string, outcome: ReviewOutcome, note?: string): Promise<ResolvedReviewRequest>; deleteCase(id: string): Promise<void>; }

export class ApiError extends Error {
  constructor(message: string, public status: number, public code?: string) { super(message); this.name = 'ApiError'; }
}
const BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '');

type ErrorEnvelope = { detail?: { code?: string; message?: string } };
type BackendChannel = 'sms' | 'whatsapp' | 'call_transcript' | 'email' | 'other_text';
interface BackendEvent { event_id: string; channel: BackendChannel; text: string; source_order: number; ingested_at?: string; }
interface BackendCase { case_id: string; revision: number; payment_context: { stated_purpose: string; amount: string | number | null; recipient_reference: string | null }; events: BackendEvent[]; }
interface BackendMutation { case_id: string; result_revision: number; idempotent_replay: boolean; }
interface BackendEvidence { tactic: string; event_id: string; source_order: number; quote: string; start_offset: number; end_offset: number; context: string; }
interface BackendAssessment { assessment_id: string; case_id: string; assessed_revision: number; state: BackendAssessmentState; reason_codes: string[]; explanation: string; evidence: BackendEvidence[]; alert: { visible: boolean; reason: string; prior_warning_state?: string | null }; suggested_next_action: string; limitations: string[]; extraction_mode: string; is_current: boolean; }
interface BackendReviewStatus { review_request_id: string; case_id: string; assessment_id: string; assessed_revision: number; status: 'open' | 'resolved'; submitted_at: string; resolved_at: string | null; outcome: ReviewOutcome | null; }
interface BackendCreatedReview extends BackendReviewStatus { idempotent_replay: boolean; existing_open_request: boolean; }
interface BackendReviewerQueueItem { review_request_id: string; case_id: string; assessment_id: string; assessed_revision: number; assessment_state: BackendAssessmentState; is_current: boolean; submitted_at: string; }
interface BackendReviewerQueue { items: BackendReviewerQueueItem[]; total: number; limit: number; offset: number; }
interface BackendReviewerEvidence { tactic: string; event_id: string; source_order: number; quote: string; start_offset: number; end_offset: number; context: string; channel: BackendChannel; source_text: string; }
interface BackendReviewerAssessment { assessment_id: string; case_id: string; assessed_revision: number; state: BackendAssessmentState; reason_codes: string[]; explanation: string; evidence: BackendReviewerEvidence[]; alert: { visible: boolean; reason: string; prior_warning_state?: string | null }; tactics_used: string[]; relationships: string[]; suggested_next_action: string; limitations: string[]; extraction_mode: string; extraction_version: string; rule_version: string; schema_version: string; created_at: string; is_current: boolean; payment_context: { stated_purpose: string; amount: string | number | null; recipient_reference: string | null }; }
interface BackendReviewerDetail extends BackendReviewStatus { reviewer_note: string | null; assessment: BackendReviewerAssessment; }
interface BackendResolvedReview extends BackendReviewStatus { reviewer_note: string | null; idempotent_replay: boolean; }

const idempotencyKeys = new Map<string, string>();
const retryEventIds = new Map<string, string>();
const retryAppendOrders = new Map<string, number>();
function stableIdempotencyKey(scope: string, payload: unknown): string {
  const signature = `${scope}:${JSON.stringify(payload)}`;
  let key = idempotencyKeys.get(signature);
  if (!key) { key = crypto.randomUUID(); idempotencyKeys.set(signature, key); }
  return key;
}
function retryEventId(scope: string, text: string, revision: number): string {
  const signature = `${scope}:${revision}:${text}`;
  let eventId = retryEventIds.get(signature);
  if (!eventId) { eventId = crypto.randomUUID(); retryEventIds.set(signature, eventId); }
  return eventId;
}
interface RequestOptions { csrf?: boolean; idempotencyKey?: string; credentials?: RequestCredentials; reviewerToken?: string; }
async function request<T>(path: string, init: RequestInit = {}, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body !== undefined && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  if (options.csrf) headers.set('X-ScamFlow-CSRF', '1');
  if (options.idempotencyKey) headers.set('Idempotency-Key', options.idempotencyKey);
  if (options.reviewerToken) headers.set('X-ScamFlow-Reviewer-Token', options.reviewerToken);
  let response: Response;
  const redact = (message: string) => options.reviewerToken ? message.split(options.reviewerToken).join('[redacted]') : message;
  try { response = await fetch(`${BASE}${path}`, { ...init, headers, credentials: options.credentials ?? 'include', signal: AbortSignal.timeout(15000) }); }
  catch (error) { throw new ApiError(redact(error instanceof DOMException && error.name === 'TimeoutError' ? 'The request timed out. Please retry.' : 'Could not reach the service. Check your connection and retry.'), 0, 'request_failed'); }
  if (!response.ok) {
    let message = response.status === 409 ? 'This case has changed in another request. Reload the latest revision before retrying.' : response.status === 401 ? 'Your session has expired. Start a new session to continue.' : response.status === 404 ? 'This case could not be found.' : `The request failed (${response.status}). Please retry.`;
    let code = response.status === 502 ? 'request_failed' : undefined;
    try { const body = await response.json() as ErrorEnvelope; message = body.detail?.message ?? message; code = body.detail?.code ?? code; } catch { /* Keep safe status-based fallback. */ }
    throw new ApiError(redact(message), response.status, code);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

const backendChannels: Record<Channel, BackendChannel> = { SMS: 'sms', WhatsApp: 'whatsapp', 'Call transcript': 'call_transcript', Email: 'email', 'Other text': 'other_text' };
const displayChannels: Record<BackendChannel, Channel> = { sms: 'SMS', whatsapp: 'WhatsApp', call_transcript: 'Call transcript', email: 'Email', other_text: 'Other text' };
const stateMap: Record<BackendAssessment['state'], AssessmentState> = { high_risk_indicators: 'high_risk', needs_clarification_or_review: 'review', no_strong_indicators: 'no_strong_indicators', unable_to_assess: 'unable_to_assess' };
function mapAssessment(dto: BackendAssessment, source: BackendCase): Assessment {
  const eventById = new Map(source.events.map(event => [event.event_id, event]));
  const evidence: Evidence[] = [];
  for (const item of dto.evidence) {
    const event = eventById.get(item.event_id);
    if (!event || event.source_order !== item.source_order) continue;
    // Backend offsets count Unicode code points; convert in code-point space so emoji do not shift spans.
    const codePoints = Array.from(event.text);
    if (!Number.isInteger(item.start_offset) || !Number.isInteger(item.end_offset) || item.start_offset < 0 || item.end_offset <= item.start_offset || item.end_offset > codePoints.length) continue;
    const exactQuote = codePoints.slice(item.start_offset, item.end_offset).join('');
    if (exactQuote !== item.quote) continue;
    evidence.push({ messageId: item.event_id, quote: item.quote, reason: `${item.tactic}: ${item.context}`, startOffset: item.start_offset, endOffset: item.end_offset });
  }
  return { id: dto.assessment_id, revision: dto.assessed_revision, state: stateMap[dto.state], reasons: [...dto.reason_codes, dto.explanation].filter(Boolean), evidence, nextAction: dto.suggested_next_action, limitations: dto.limitations, extractionMode: dto.extraction_mode, isCurrent: dto.is_current, alert: dto.alert };
}
function mapCase(dto: BackendCase, assessment?: BackendAssessment): CaseRecord {
  const channel = dto.events[0] ? displayChannels[dto.events[0].channel] : 'Other text';
  const record: CaseRecord = {
    id: dto.case_id, revision: dto.revision, channel,
    messages: dto.events.slice().sort((a,b)=>a.source_order-b.source_order).map(event => ({ id: event.event_id, order: event.source_order, sender: 'Submitted text', channel: displayChannels[event.channel], text: event.text })),
    amount: dto.payment_context.amount == null ? undefined : String(dto.payment_context.amount),
    requestedAction: dto.payment_context.stated_purpose,
    recipient: dto.payment_context.recipient_reference ?? undefined,
    current: assessment ? mapAssessment(assessment, dto) : undefined,
    history: assessment ? [mapAssessment(assessment, dto)] : [], answers: []
  };
  return record;
}
function mapReviewStatus(dto: BackendReviewStatus): ReviewRequestStatus {
  return { reviewRequestId: dto.review_request_id, caseId: dto.case_id, assessmentId: dto.assessment_id, assessedRevision: dto.assessed_revision, status: dto.status, submittedAt: dto.submitted_at, resolvedAt: dto.resolved_at, outcome: dto.outcome };
}
function mapReviewerQueue(dto: BackendReviewerQueue): ReviewerQueue {
  return { items: dto.items.map(item => ({ reviewRequestId: item.review_request_id, caseId: item.case_id, assessmentId: item.assessment_id, assessedRevision: item.assessed_revision, assessmentState: item.assessment_state, isCurrent: item.is_current, submittedAt: item.submitted_at })), total: dto.total, limit: dto.limit, offset: dto.offset };
}
function mapReviewerDetail(dto: BackendReviewerDetail): ReviewerDetail {
  const assessment = dto.assessment;
  return {
    ...mapReviewStatus(dto),
    reviewerNote: dto.reviewer_note,
    assessment: {
      assessmentId: assessment.assessment_id,
      caseId: assessment.case_id,
      assessedRevision: assessment.assessed_revision,
      state: assessment.state,
      reasonCodes: assessment.reason_codes,
      explanation: assessment.explanation,
      evidence: assessment.evidence.map(item => ({ tactic: item.tactic, eventId: item.event_id, sourceOrder: item.source_order, quote: item.quote, startOffset: item.start_offset, endOffset: item.end_offset, context: item.context, channel: item.channel, sourceText: item.source_text })),
      alert: { visible: assessment.alert.visible, reason: assessment.alert.reason, priorWarningState: assessment.alert.prior_warning_state ?? null },
      tacticsUsed: assessment.tactics_used,
      relationships: assessment.relationships,
      suggestedNextAction: assessment.suggested_next_action,
      limitations: assessment.limitations,
      extractionMode: assessment.extraction_mode,
      extractionVersion: assessment.extraction_version,
      ruleVersion: assessment.rule_version,
      schemaVersion: assessment.schema_version,
      createdAt: assessment.created_at,
      isCurrent: assessment.is_current,
      paymentContext: { statedPurpose: assessment.payment_context.stated_purpose, amount: assessment.payment_context.amount == null ? null : String(assessment.payment_context.amount), recipientReference: assessment.payment_context.recipient_reference }
    }
  };
}
const realRecordCache = new Map<string, CaseRecord>();
async function fetchCaseWithLatest(id: string): Promise<CaseRecord> {
  const dto = await request<BackendCase>(`/cases/${encodeURIComponent(id)}`);
  let assessment: BackendAssessment | undefined;
  try { assessment = await request<BackendAssessment>(`/cases/${encodeURIComponent(id)}/assessments/latest`); }
  catch (error) { if (!(error instanceof ApiError && error.status === 404 && error.code === 'assessment_not_found')) throw error; }
  const mapped = mapCase(dto, assessment);
  const old = realRecordCache.get(id);
  if (old) mapped.history = [...old.history.filter(item => item.id !== mapped.current?.id), ...(mapped.current ? [mapped.current] : [])];
  realRecordCache.set(id, mapped);
  return structuredClone(mapped);
}
function eventFor(input: { id: string; channel: Channel; text: string; order: number }) {
  return { event_id: input.id, channel: backendChannels[input.channel], text: input.text, source_order: input.order };
}
export const realApi: ApiAdapter = {
  createCase: async (input) => {
    const statedPurpose = input.requestedAction?.trim();
    if (!statedPurpose) throw new ApiError('Enter the stated payment purpose to submit this case to the connected backend.', 422, 'stated_purpose_required');
    await request('/session', { method: 'POST' }, { csrf: true });
    const createScope = JSON.stringify({ channel: input.channel, amount: input.amount ?? null, recipient: input.recipient ?? null, purpose: statedPurpose });
    const event = eventFor({ id: retryEventId(`create:${createScope}`, input.conversation, 1), channel: input.channel, text: input.conversation, order: 1 });
    const payload = { consent: true, payment_context: { stated_purpose: statedPurpose, amount: input.amount?.trim() || null, recipient_reference: input.recipient?.trim() || null }, events: [event] };
    const mutation = await request<BackendMutation>('/cases', { method: 'POST', body: JSON.stringify(payload) }, { csrf: true, idempotencyKey: stableIdempotencyKey('POST:/cases', payload) });
    const record = await fetchCaseWithLatest(mutation.case_id);
    if (record.revision !== mutation.result_revision) throw new ApiError('The created case revision changed before it could be assessed. Reload the case and retry.', 409, 'revision_conflict');
    try { return await realApi.assess(mutation.case_id, mutation.result_revision); }
    catch (error) { const failed = { ...record, assessmentFailure: (error as Error).message }; realRecordCache.set(failed.id, failed); return structuredClone(failed); }
  },
  getCase: fetchCaseWithLatest,
  appendMessage: async (id, text, expectedRevision) => {
    const retryScope = `${id}:${expectedRevision}:${text}`;
    let order = retryAppendOrders.get(retryScope);
    let channel: Channel;
    if (order === undefined) {
      const before = await fetchCaseWithLatest(id);
      order = Math.max(0, ...before.messages.map(m => m.order)) + 1;
      channel = before.channel;
      retryAppendOrders.set(retryScope, order);
    } else {
      channel = realRecordCache.get(id)?.channel ?? 'Other text';
    }
    const eventId = retryEventId(`append:${id}`, text, expectedRevision);
    const event = eventFor({ id: eventId, channel, text, order });
    const payload = { expected_revision: expectedRevision, events: [event] };
    await request<BackendMutation>(`/cases/${encodeURIComponent(id)}/events`, { method: 'POST', body: JSON.stringify(payload) }, { csrf: true, idempotencyKey: stableIdempotencyKey(`POST:/cases/${id}/events`, payload) });
    const updated = await fetchCaseWithLatest(id);
    retryAppendOrders.delete(retryScope);
    return updated;
  },
  addClarification: async (id, answers, expectedRevision) => {
    // The backend contract has no clarification-answer field. Do not send it as a fabricated endpoint or event.
    void id; void answers; void expectedRevision;
    throw new ApiError('The connected backend has no clarification-answer API. No answer was sent or saved.', 501, 'clarification_not_supported');
  },
  assess: async (id, expectedRevision, messages) => {
    if (messages !== undefined) throw new ApiError('The connected backend assesses persisted case revisions only; prefix replay is not supported by its API contract.', 501, 'prefix_assessment_not_supported');
    const payload = { expected_revision: expectedRevision };
    const assessment = await request<BackendAssessment>(`/cases/${encodeURIComponent(id)}/assess`, { method: 'POST', body: JSON.stringify(payload) }, { csrf: true, idempotencyKey: stableIdempotencyKey(`POST:/cases/${id}/assess`, payload) });
    const dto = await request<BackendCase>(`/cases/${encodeURIComponent(id)}`);
    const mapped = mapCase(dto, assessment);
    const prior = realRecordCache.get(id);
    if (prior) mapped.history = [...prior.history.filter(item => item.id !== mapped.current?.id), ...(mapped.current ? [mapped.current] : [])];
    realRecordCache.set(id, mapped);
    return structuredClone(mapped);
  },
  createReviewRequest: async (caseId, assessmentId, expectedRevision) => {
    const payload = { assessment_id: assessmentId, expected_revision: expectedRevision };
    const path = `/cases/${encodeURIComponent(caseId)}/review-requests`;
    const dto = await request<BackendCreatedReview>(path, { method: 'POST', body: JSON.stringify(payload) }, { csrf: true, idempotencyKey: stableIdempotencyKey(`POST:${path}`, payload) });
    return { ...mapReviewStatus(dto), idempotentReplay: dto.idempotent_replay, existingOpenRequest: dto.existing_open_request };
  },
  getOwnerReviewRequest: async (caseId, reviewRequestId) => {
    const dto = await request<BackendReviewStatus>(`/cases/${encodeURIComponent(caseId)}/review-requests/${encodeURIComponent(reviewRequestId)}`);
    return mapReviewStatus(dto);
  },
  getReviewerQueue: async (token, limit, offset) => {
    if (!token.trim()) throw new ApiError('Enter the reviewer token to access the restricted queue.', 401, 'reviewer_auth_required');
    const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    const dto = await request<BackendReviewerQueue>(`/reviewer/review-requests?${query.toString()}`, {}, { reviewerToken: token, credentials: 'omit' });
    return mapReviewerQueue(dto);
  },
  getReviewerDetail: async (token, reviewRequestId) => {
    if (!token.trim()) throw new ApiError('Enter the reviewer token to access restricted request details.', 401, 'reviewer_auth_required');
    const dto = await request<BackendReviewerDetail>(`/reviewer/review-requests/${encodeURIComponent(reviewRequestId)}`, {}, { reviewerToken: token, credentials: 'omit' });
    return mapReviewerDetail(dto);
  },
  resolveReviewerRequest: async (token, reviewRequestId, outcome, note) => {
    if (!token.trim()) throw new ApiError('Enter the reviewer token to resolve a request.', 401, 'reviewer_auth_required');
    if (note !== undefined && Array.from(note).length > 1000) throw new ApiError('Reviewer notes must be 1,000 Unicode code points or fewer.', 422, 'validation_error');
    const path = `/reviewer/review-requests/${encodeURIComponent(reviewRequestId)}/resolve`;
    const payload = note === undefined || !note.trim() ? { outcome } : { outcome, reviewer_note: note };
    const dto = await request<BackendResolvedReview>(path, { method: 'POST', body: JSON.stringify(payload) }, { reviewerToken: token, credentials: 'omit', idempotencyKey: stableIdempotencyKey(`POST:${path}`, payload) });
    return { ...mapReviewStatus(dto), reviewerNote: dto.reviewer_note, idempotentReplay: dto.idempotent_replay };
  },
  deleteCase: async (id) => { await request<void>(`/cases/${encodeURIComponent(id)}`, { method: 'DELETE' }, { csrf: true }); realRecordCache.delete(id); }
};

export const api: ApiAdapter = realApi;
