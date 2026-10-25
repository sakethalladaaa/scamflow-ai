import { afterEach, describe, expect, it, vi } from 'vitest';
import { realApi } from '../src/api';

afterEach(() => vi.unstubAllGlobals());
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const backendCase = {
  case_id: 'case-1', revision: 1,
  payment_context: { stated_purpose: 'Account verification', amount: '20.00', recipient_reference: 'Caller claiming to be my bank' },
  events: [{ event_id: 'event-1', channel: 'whatsapp', text: 'Send OTP 🔐 now', source_order: 1, ingested_at: '2030-01-01T00:00:00Z' }]
};
const assessment = (offsets = { start_offset: 5, end_offset: 10 }) => ({
  assessment_id: 'assessment-1', case_id: 'case-1', assessed_revision: 1, state: 'high_risk_indicators',
  reason_codes: ['urgent_payment'], explanation: 'The message contains a request that merits review.',
  evidence: [{ tactic: 'urgency', event_id: 'event-1', source_order: 1, quote: 'OTP 🔐', ...offsets, context: 'request for a verification code' }],
  alert: { visible: true, reason: 'material_escalation', prior_warning_state: null }, tactics_used: ['urgency'], relationships: [],
  suggested_next_action: 'Pause and verify independently.', limitations: ['Not a safety guarantee.'], extraction_mode: 'rules',
  extraction_version: 'v1', rule_version: 'v1', schema_version: 'v1', created_at: '2030-01-01T00:00:00Z', is_current: true, idempotent_replay: false
});

describe('verified FastAPI contract adapter', () => {
  it('uses only existing routes and request schemas and maps the backend assessment', async () => {
    const calls: Array<{ path: string; init: RequestInit }> = [];
    const fetchMock = vi.fn(async (path: string, init: RequestInit = {}) => {
      calls.push({ path, init });
      if (path === '/session') return json({ expires_at: '2030-01-01T00:00:00Z' });
      if (path === '/cases' && init.method === 'POST') return json({ case_id: 'case-1', result_revision: 1, idempotent_replay: false }, 201);
      if (path === '/cases/case-1' && init.method !== 'POST') return json(backendCase);
      if (path === '/cases/case-1/assessments/latest') return json({ detail: { code: 'assessment_not_found', message: 'No assessment exists for this case.' } }, 404);
      if (path === '/cases/case-1/assess' && init.method === 'POST') return json(assessment());
      return json({ detail: { code: 'case_not_found', message: 'Case not found.' } }, 404);
    });
    vi.stubGlobal('fetch', fetchMock);

    const result = await realApi.createCase({ channel: 'WhatsApp', conversation: 'Send OTP 🔐 now', amount: '20.00', currency: 'USD', requestedAction: 'Account verification', recipient: 'Caller claiming to be my bank' });
    expect(calls.map(c => `${c.init.method ?? 'GET'} ${c.path}`)).toEqual([
      'POST /session', 'POST /cases', 'GET /cases/case-1', 'GET /cases/case-1/assessments/latest', 'POST /cases/case-1/assess', 'GET /cases/case-1'
    ]);
    expect(new Headers(calls[0].init.headers).get('X-ScamFlow-CSRF')).toBe('1');
    expect(calls[0].init.body).toBeUndefined();
    expect(new Headers(calls[1].init.headers).get('X-ScamFlow-CSRF')).toBe('1');
    expect(new Headers(calls[1].init.headers).get('Idempotency-Key')).toBeTruthy();
    const payload = JSON.parse(calls[1].init.body as string);
    expect(payload).toEqual({ consent: true, payment_context: { stated_purpose: 'Account verification', amount: '20.00', recipient_reference: 'Caller claiming to be my bank' }, events: [{ event_id: expect.any(String), channel: 'whatsapp', text: 'Send OTP 🔐 now', source_order: 1 }] });
    expect(payload).not.toHaveProperty('currency');
    expect(calls[4].init.body).toBe(JSON.stringify({ expected_revision: 1 }));
    expect(new Headers(calls[4].init.headers).get('X-ScamFlow-CSRF')).toBe('1');
    expect(result.id).toBe('case-1');
    expect(result.messages[0].text).toBe('Send OTP 🔐 now');
    expect(result.current?.state).toBe('high_risk');
    expect(result.current?.extractionMode).toBe('rules');
    expect(result.current?.evidence[0]).toMatchObject({ quote: 'OTP 🔐', startOffset: 5, endOffset: 10, messageId: 'event-1' });
  });

  it('requires the backend-required stated purpose before sending requests', async () => {
    const fetchMock = vi.fn(); vi.stubGlobal('fetch', fetchMock);
    await expect(realApi.createCase({ channel: 'SMS', conversation: 'A message long enough' })).rejects.toMatchObject({ status: 422, code: 'stated_purpose_required' });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('preserves the backend mutation contract for appended evidence and expected revision', async () => {
    const calls: Array<{ path: string; init: RequestInit }> = [];
    vi.stubGlobal('fetch', vi.fn(async (path: string, init: RequestInit = {}) => {
      calls.push({ path, init });
      if (path === '/cases/case-1') return json(backendCase);
      if (path === '/cases/case-1/assessments/latest') return json({ detail: { code: 'assessment_not_found', message: 'No assessment exists for this case.' } }, 404);
      if (path === '/cases/case-1/events') return json({ case_id: 'case-1', result_revision: 2, idempotent_replay: false });
      return json({ ...backendCase, revision: 2, events: [...backendCase.events, { event_id: expect.any(String), channel: 'whatsapp', text: 'New source event', source_order: 2 }] });
    }));
    await realApi.appendMessage('case-1', 'New source event', 1);
    const mutation = calls.find(c => c.path === '/cases/case-1/events')!;
    expect(new Headers(mutation.init.headers).get('X-ScamFlow-CSRF')).toBe('1');
    expect(new Headers(mutation.init.headers).get('Idempotency-Key')).toBeTruthy();
    expect(JSON.parse(mutation.init.body as string)).toMatchObject({ expected_revision: 1, events: [{ channel: 'whatsapp', text: 'New source event', source_order: 2, event_id: expect.any(String) }] });
  });

  it('retries an uncertain append with the identical idempotency key and event payload', async () => {
    const calls: Array<{ path: string; init: RequestInit }> = [];
    let mutationAttempts = 0;
    let committedEvent: Record<string, unknown> | undefined;
    vi.stubGlobal('fetch', vi.fn(async (path: string, init: RequestInit = {}) => {
      calls.push({ path, init });
      if (path === '/cases/case-1') return json({ ...backendCase, revision: mutationAttempts > 1 ? 2 : 1, events: mutationAttempts > 1 ? [...backendCase.events, committedEvent] : backendCase.events });
      if (path === '/cases/case-1/assessments/latest') return json({ detail: { code: 'assessment_not_found', message: 'No assessment exists for this case.' } }, 404);
      if (path === '/cases/case-1/events') {
        mutationAttempts++;
        const body = JSON.parse(init.body as string) as { events: Record<string, unknown>[] };
        if (mutationAttempts === 1) return new Response('gateway error', { status: 502 });
        committedEvent = body.events[0];
        return json({ case_id: 'case-1', result_revision: 2, idempotent_replay: true });
      }
      return json({ detail: { code: 'case_not_found', message: 'Case not found.' } }, 404);
    }));
    await expect(realApi.appendMessage('case-1', 'retry this event', 1)).rejects.toMatchObject({ status: 502, code: 'request_failed' });
    await realApi.appendMessage('case-1', 'retry this event', 1);
    const mutations = calls.filter(c => c.path === '/cases/case-1/events');
    expect(mutations).toHaveLength(2);
    expect(mutations[0].init.body).toBe(mutations[1].init.body);
    expect(new Headers(mutations[0].init.headers).get('Idempotency-Key')).toBe(new Headers(mutations[1].init.headers).get('Idempotency-Key'));
  });

  it('does not send unsupported clarification or prefix-replay requests', async () => {
    const fetchMock = vi.fn(); vi.stubGlobal('fetch', fetchMock);
    await expect(realApi.addClarification('case-1', ['Yes'], 1)).rejects.toMatchObject({ code: 'clarification_not_supported' });
    await expect(realApi.assess('case-1', 1, [])).rejects.toMatchObject({ code: 'prefix_assessment_not_supported' });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('drops evidence if backend offsets do not match the exact original Unicode text', async () => {
    const calls: Array<{ path: string; init: RequestInit }> = [];
    vi.stubGlobal('fetch', vi.fn(async (path: string, init: RequestInit = {}) => {
      calls.push({ path, init });
      if (path === '/session') return json({ expires_at: '2030-01-01T00:00:00Z' });
      if (path === '/cases') return json({ case_id: 'case-1', result_revision: 1, idempotent_replay: false }, 201);
      if (path === '/cases/case-1' && init.method !== 'POST') return json(backendCase);
      if (path === '/cases/case-1/assessments/latest') return json({ detail: { code: 'assessment_not_found', message: 'No assessment exists for this case.' } }, 404);
      if (path === '/cases/case-1/assess') return json(assessment({ start_offset: 0, end_offset: 3 }));
      return json(backendCase);
    }));
    const result = await realApi.createCase({ channel: 'WhatsApp', conversation: 'Send OTP 🔐 now', requestedAction: 'Account verification' });
    expect(result.current?.evidence).toEqual([]);
  });

  it('maps a non-JSON 502 response to the safe request_failed error code', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('gateway error', { status: 502 })));
    await expect(realApi.getCase('case-1')).rejects.toMatchObject({ status: 502, code: 'request_failed' });
  });
});


describe('persisted review workflow contract', () => {
  const status = {
    review_request_id: 'review-1', case_id: 'case-1', assessment_id: 'assessment-1', assessed_revision: 3,
    status: 'open', submitted_at: '2030-01-02T03:04:05Z', resolved_at: null, outcome: null,
  };

  it('creates an owner-scoped request with the current assessment/revision and reads safe persisted status', async () => {
    const calls: Array<{ url: string; init: RequestInit }> = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
      calls.push({ url, init });
      if (url === '/cases/case-1/review-requests' && init.method === 'POST') return json({ ...status, idempotent_replay: false, existing_open_request: false }, 201);
      if (url === '/cases/case-1/review-requests/review-1') return json(status);
      return json({ detail: { code: 'not_found', message: 'Not found.' } }, 404);
    }));

    const created = await realApi.createReviewRequest('case-1', 'assessment-1', 3);
    const firstMutation = calls[0];
    expect(firstMutation.url).toBe('/cases/case-1/review-requests');
    expect(firstMutation.init.credentials).toBe('include');
    expect(new Headers(firstMutation.init.headers).get('X-ScamFlow-CSRF')).toBe('1');
    expect(new Headers(firstMutation.init.headers).get('Idempotency-Key')).toBeTruthy();
    expect(JSON.parse(firstMutation.init.body as string)).toEqual({ assessment_id: 'assessment-1', expected_revision: 3 });
    expect(created).toMatchObject({ reviewRequestId: 'review-1', status: 'open', idempotentReplay: false, existingOpenRequest: false });

    await realApi.createReviewRequest('case-1', 'assessment-1', 3);
    expect(new Headers(calls[0].init.headers).get('Idempotency-Key')).toBe(new Headers(calls[1].init.headers).get('Idempotency-Key'));
    const persisted = await realApi.getOwnerReviewRequest('case-1', 'review-1');
    expect(calls[2].url).toBe('/cases/case-1/review-requests/review-1');
    expect(calls[2].init.credentials).toBe('include');
    expect(new Headers(calls[2].init.headers).get('X-ScamFlow-CSRF')).toBeNull();
    expect(persisted).toMatchObject({ reviewRequestId: 'review-1', caseId: 'case-1', status: 'open', outcome: null });
  });

  it('uses only the reviewer header, omits cookies, maps exact detail, and resolves with an idempotent bounded outcome', async () => {
    const token = 'ephemeral-test-token';
    const calls: Array<{ url: string; init: RequestInit }> = [];
    const detail = {
      ...status,
      reviewer_note: null,
      assessment: {
        assessment_id: 'assessment-1', case_id: 'case-1', assessed_revision: 3, state: 'needs_clarification_or_review',
        reason_codes: ['review_required'], explanation: 'Read the source and verify independently.',
        evidence: [{ tactic: 'outgoing_payment', event_id: 'event-1', source_order: 2, quote: '🔐', start_offset: 8, end_offset: 9, context: 'Exact source excerpt.', channel: 'whatsapp', source_text: 'Pay now 🔐' }],
        alert: { visible: true, reason: 'assessment_updated', prior_warning_state: null }, tactics_used: ['outgoing_payment'], relationships: [],
        suggested_next_action: 'Verify independently.', limitations: ['Not a safety guarantee.'], extraction_mode: 'rules',
        extraction_version: 'v1', rule_version: 'v1', schema_version: 'v1', created_at: '2030-01-02T03:04:05Z', is_current: true,
        payment_context: { stated_purpose: 'Account support', amount: '20.00', recipient_reference: 'Caller' },
      },
    };
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
      calls.push({ url, init });
      if (url === '/reviewer/review-requests?limit=50&offset=0') return json({ items: [{ review_request_id: 'review-1', case_id: 'case-1', assessment_id: 'assessment-1', assessed_revision: 3, assessment_state: 'needs_clarification_or_review', is_current: true, submitted_at: status.submitted_at }], total: 1, limit: 50, offset: 0 });
      if (url === '/reviewer/review-requests/review-1' && init.method !== 'POST') return json(detail);
      if (url === '/reviewer/review-requests/review-1/resolve' && init.method === 'POST') return json({ ...status, status: 'resolved', resolved_at: '2030-01-02T04:00:00Z', outcome: 'follow_up', reviewer_note: 'Check the original source.', idempotent_replay: true });
      return json({ detail: { code: 'not_found', message: 'Not found.' } }, 404);
    }));

    const queue = await realApi.getReviewerQueue(token, 50, 0);
    const loaded = await realApi.getReviewerDetail(token, 'review-1');
    expect(queue).toMatchObject({ total: 1, items: [{ reviewRequestId: 'review-1', assessmentState: 'needs_clarification_or_review', isCurrent: true }] });
    expect(loaded.assessment.evidence[0]).toMatchObject({ eventId: 'event-1', sourceOrder: 2, quote: '🔐', startOffset: 8, endOffset: 9, sourceText: 'Pay now 🔐' });
    expect(loaded.assessment.paymentContext).toEqual({ statedPurpose: 'Account support', amount: '20.00', recipientReference: 'Caller' });

    const resolved = await realApi.resolveReviewerRequest(token, 'review-1', 'follow_up', 'Check the original source.');
    expect(resolved).toMatchObject({ status: 'resolved', outcome: 'follow_up', idempotentReplay: true });
    for (const call of calls) {
      expect(call.init.credentials).toBe('omit');
      expect(new Headers(call.init.headers).get('X-ScamFlow-Reviewer-Token')).toBe(token);
      expect(new Headers(call.init.headers).get('Authorization')).toBeNull();
      expect(new Headers(call.init.headers).get('X-ScamFlow-CSRF')).toBeNull();
      expect(call.url).not.toContain(token);
      expect(JSON.stringify(call.init.body ?? '')).not.toContain(token);
    }
    const resolution = calls[2];
    expect(JSON.parse(resolution.init.body as string)).toEqual({ outcome: 'follow_up', reviewer_note: 'Check the original source.' });
    expect(new Headers(resolution.init.headers).get('Idempotency-Key')).toBeTruthy();
  });

  it('rejects over-limit notes by Unicode code point before a network request', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    await expect(realApi.resolveReviewerRequest('token', 'review-1', 'inconclusive', '🔐'.repeat(1001))).rejects.toMatchObject({ status: 422, code: 'validation_error' });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});


it.each(['follow_up', 'escalated', 'no_action', 'inconclusive'] as const)('sends the backend-allowed resolution outcome %s unchanged', async (outcome) => {
  let submitted: RequestInit | undefined;
  vi.stubGlobal('fetch', vi.fn(async (_url: string, init: RequestInit = {}) => {
    submitted = init;
    return json({ ...{
      review_request_id: 'review-outcome', case_id: 'case-1', assessment_id: 'assessment-1', assessed_revision: 1,
      status: 'resolved', submitted_at: '2030-01-02T03:04:05Z', resolved_at: '2030-01-02T04:00:00Z', outcome,
    }, reviewer_note: null, idempotent_replay: false });
  }));
  await realApi.resolveReviewerRequest('temporary-test-token', 'review-outcome', outcome);
  expect(JSON.parse(submitted?.body as string)).toEqual({ outcome });
  expect(new Headers(submitted?.headers).get('Idempotency-Key')).toBeTruthy();
});

it('sends the reviewer queue page limit and offset as backend query parameters', async () => {
  let requestedUrl = '';
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    requestedUrl = url;
    return json({ items: [], total: 51, limit: 50, offset: 50 });
  }));
  const result = await realApi.getReviewerQueue('temporary-test-token', 50, 50);
  expect(requestedUrl).toBe('/reviewer/review-requests?limit=50&offset=50');
  expect(result).toEqual({ items: [], total: 51, limit: 50, offset: 50 });
});
