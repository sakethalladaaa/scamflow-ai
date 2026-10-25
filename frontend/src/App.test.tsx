import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import { api, type Assessment, type AssessmentState, type CaseRecord } from './api';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.history.replaceState({}, '', '/');
});

const jsonResponse = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status,
  headers: { 'Content-Type': 'application/json' },
});

function record(id = 'case-1', text = 'A source message.', revision = 1, state: AssessmentState = 'review'): CaseRecord {
  const current: Assessment = {
    id: `assessment-${id}-${revision}`,
    revision,
    state,
    reasons: ['Backend assessment explanation.'],
    evidence: [],
    nextAction: 'Verify independently.',
    limitations: ['This is not a safety guarantee.'],
    extractionMode: 'rules',
  };
  return {
    id,
    revision,
    channel: 'SMS',
    messages: [{ id: `event-${id}`, order: 1, sender: 'Submitted text', channel: 'SMS', text }],
    current,
    history: [current],
    answers: [],
  };
}

function backendCase(id: string, text: string, revision = 1) {
  return {
    case_id: id,
    revision,
    payment_context: { stated_purpose: 'Account verification', amount: null, recipient_reference: null },
    events: [{ event_id: `event-${id}`, channel: 'sms', text, source_order: 1 }],
  };
}

function backendAssessment(id: string, revision = 1) {
  return {
    assessment_id: `assessment-${id}-${revision}`,
    case_id: id,
    assessed_revision: revision,
    state: 'needs_clarification_or_review',
    reason_codes: ['review_required'],
    explanation: 'Review the source and verify independently.',
    evidence: [],
    alert: { visible: true, reason: 'assessment_updated', prior_warning_state: null },
    suggested_next_action: 'Verify independently.',
    limitations: ['This is not a safety guarantee.'],
    extraction_mode: 'rules',
    is_current: true,
  };
}

async function fillSubmission(user: ReturnType<typeof userEvent.setup>, text = 'A message that needs context.') {
  await user.type(screen.getByLabelText(/conversation text/i), text);
  await user.click(screen.getByText(/optional: add amount or recipient context/i));
  await user.type(screen.getByLabelText(/stated payment purpose/i), 'Account verification');
  await user.click(screen.getByRole('checkbox'));
}

it('requires consent and does not submit invalid intake', async () => {
  const create = vi.spyOn(api, 'createCase');
  render(<App />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText(/conversation text/i), 'A valid-length message.');
  await user.click(screen.getByRole('button', { name: /analyse conversation/i }));
  expect(screen.getByRole('alert')).toHaveTextContent(/confirm consent/i);
  expect(create).not.toHaveBeenCalled();
});

it('prevents a duplicate create mutation while the first is pending', async () => {
  let resolveCreate!: (value: CaseRecord) => void;
  const pending = new Promise<CaseRecord>((resolve) => { resolveCreate = resolve; });
  const create = vi.spyOn(api, 'createCase').mockReturnValue(pending);
  render(<App />);
  const user = userEvent.setup();
  await fillSubmission(user);
  const submit = screen.getByRole('button', { name: /analyse conversation/i });
  fireEvent.click(submit);
  fireEvent.click(submit);
  expect(create).toHaveBeenCalledTimes(1);
  resolveCreate(record());
  expect(await screen.findByText('Your conversation, in context.')).toBeInTheDocument();
});

it('renders HTML-like evidence as text in the current message timeline', async () => {
  const literal = '<script>window.bad=true</script>';
  vi.spyOn(api, 'createCase').mockResolvedValue(record('case-1', literal));
  render(<App />);
  const user = userEvent.setup();
  await fillSubmission(user, literal);
  await user.click(screen.getByRole('button', { name: /analyse conversation/i }));
  expect(await screen.findByText(literal)).toBeInTheDocument();
  expect(document.querySelector('script')).toBeNull();
});

it('retries failed create with the same idempotency key, body, and event ID', async () => {
  const calls: Array<{ path: string; init: RequestInit }> = [];
  let attempts = 0;
  const fetchMock = vi.fn(async (path: string, init: RequestInit = {}) => {
    calls.push({ path, init });
    if (path === '/session') return jsonResponse({ expires_at: '2030-01-01T00:00:00Z' });
    if (path === '/cases' && init.method === 'POST') {
      attempts += 1;
      if (attempts === 1) throw new TypeError('NetworkError: Failed to fetch');
      return jsonResponse({ case_id: 'case-retry', result_revision: 1, idempotent_replay: false }, 201);
    }
    if (path === '/cases/case-retry/assessments/latest') return jsonResponse({ detail: { code: 'assessment_not_found', message: 'No assessment exists for this case.' } }, 404);
    if (path === '/cases/case-retry/assess' && init.method === 'POST') return jsonResponse(backendAssessment('case-retry'));
    if (path === '/cases/case-retry') return jsonResponse(backendCase('case-retry', 'A message that needs context.'));
    return jsonResponse({ detail: { code: 'case_not_found', message: 'Case not found.' } }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
  render(<App />);
  const user = userEvent.setup();
  await fillSubmission(user);
  const submit = screen.getByRole('button', { name: /analyse conversation/i });
  await user.click(submit);
  expect(await screen.findByRole('alert')).toHaveTextContent(/could not reach the service/i);
  await user.click(submit);
  expect(await screen.findByText('Your conversation, in context.')).toBeInTheDocument();
  const creates = calls.filter(({ path, init }) => path === '/cases' && init.method === 'POST');
  expect(creates).toHaveLength(2);
  expect(new Headers(creates[0].init.headers).get('Idempotency-Key')).toBe(new Headers(creates[1].init.headers).get('Idempotency-Key'));
  expect(creates[0].init.body).toBe(creates[1].init.body);
  const payload = JSON.parse(creates[0].init.body as string);
  expect(payload.events[0].event_id).toBeTruthy();
  expect(payload.events[0].event_id).toBe(JSON.parse(creates[1].init.body as string).events[0].event_id);
  expect(payload.payment_context).not.toHaveProperty('currency');
});

it('uses a new idempotency key and event ID when the user changes the failed input', async () => {
  const calls: Array<{ path: string; init: RequestInit }> = [];
  let attempts = 0;
  const fetchMock = vi.fn(async (path: string, init: RequestInit = {}) => {
    calls.push({ path, init });
    if (path === '/session') return jsonResponse({ expires_at: '2030-01-01T00:00:00Z' });
    if (path === '/cases' && init.method === 'POST') {
      attempts += 1;
      if (attempts === 1) throw new TypeError('NetworkError: Failed to fetch');
      return jsonResponse({ case_id: 'case-edited', result_revision: 1, idempotent_replay: false }, 201);
    }
    if (path === '/cases/case-edited/assessments/latest') return jsonResponse({ detail: { code: 'assessment_not_found', message: 'No assessment exists for this case.' } }, 404);
    if (path === '/cases/case-edited/assess' && init.method === 'POST') return jsonResponse(backendAssessment('case-edited'));
    if (path === '/cases/case-edited') return jsonResponse(backendCase('case-edited', 'Edited message for review.'));
    return jsonResponse({ detail: { code: 'case_not_found', message: 'Case not found.' } }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
  render(<App />);
  const user = userEvent.setup();
  await fillSubmission(user, 'Initial message for review.');
  const textarea = screen.getByLabelText(/conversation text/i);
  const submit = screen.getByRole('button', { name: /analyse conversation/i });
  await user.click(submit);
  expect(await screen.findByRole('alert')).toHaveTextContent(/could not reach the service/i);
  await user.clear(textarea);
  await user.type(textarea, 'Edited message for review.');
  await user.click(submit);
  expect(await screen.findByText('Your conversation, in context.')).toBeInTheDocument();
  const creates = calls.filter(({ path, init }) => path === '/cases' && init.method === 'POST');
  expect(creates).toHaveLength(2);
  expect(new Headers(creates[0].init.headers).get('Idempotency-Key')).not.toBe(new Headers(creates[1].init.headers).get('Idempotency-Key'));
  expect(JSON.parse(creates[0].init.body as string).events[0].event_id).not.toBe(JSON.parse(creates[1].init.body as string).events[0].event_id);
});

it('retries failed append with the same key, payload, and event ID', async () => {
  const calls: Array<{ path: string; init: RequestInit }> = [];
  let appendAttempts = 0;
  const initial = backendCase('case-append', 'Original source message.');
  const fetchMock = vi.fn(async (path: string, init: RequestInit = {}) => {
    calls.push({ path, init });
    if (path === '/cases/case-append') return jsonResponse({ ...initial, revision: appendAttempts > 1 ? 2 : 1, events: appendAttempts > 1 ? [...initial.events, { event_id: 'appended-event', channel: 'sms', text: 'Additional source message.', source_order: 2 }] : initial.events });
    if (path === '/cases/case-append/assessments/latest') return jsonResponse({ detail: { code: 'assessment_not_found', message: 'No assessment exists for this case.' } }, 404);
    if (path === '/cases/case-append/events') {
      appendAttempts += 1;
      if (appendAttempts === 1) return jsonResponse({ detail: { code: 'internal_error', message: 'Transient backend error.' } }, 500);
      return jsonResponse({ case_id: 'case-append', result_revision: 2, idempotent_replay: true });
    }
    return jsonResponse({ detail: { code: 'case_not_found', message: 'Case not found.' } }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
  vi.spyOn(api, 'createCase').mockResolvedValue(record('case-append', 'Original source message.'));
  render(<App />);
  const user = userEvent.setup();
  await fillSubmission(user, 'Original source message.');
  await user.click(screen.getByRole('button', { name: /analyse conversation/i }));
  await screen.findByText('Your conversation, in context.');
  await user.type(screen.getByPlaceholderText(/paste the next message exactly/i), 'Additional source message.');
  const appendButton = screen.getByRole('button', { name: /add message/i });
  await user.click(appendButton);
  expect(await screen.findByRole('alert')).toHaveTextContent('Transient backend error.');
  await user.click(appendButton);
  await waitFor(() => expect(calls.filter(call => call.path === '/cases/case-append/events')).toHaveLength(2));
  const mutations = calls.filter(call => call.path === '/cases/case-append/events');
  expect(mutations[0].init.body).toBe(mutations[1].init.body);
  expect(new Headers(mutations[0].init.headers).get('Idempotency-Key')).toBe(new Headers(mutations[1].init.headers).get('Idempotency-Key'));
  expect(JSON.parse(mutations[0].init.body as string)).toMatchObject({ expected_revision: 1, events: [{ event_id: expect.any(String), channel: 'sms', text: 'Additional source message.', source_order: 2 }] });
});

it('surfaces a stale-revision conflict and reloads the latest case', async () => {
  let reads = 0;
  const fetchMock = vi.fn(async (path: string) => {
    if (path === '/cases/case-conflict') return jsonResponse({ ...backendCase('case-conflict', 'Original source message.', ++reads > 1 ? 2 : 1), revision: reads > 1 ? 2 : 1 });
    if (path === '/cases/case-conflict/assessments/latest') return jsonResponse({ detail: { code: 'assessment_not_found', message: 'No assessment exists for this case.' } }, 404);
    if (path === '/cases/case-conflict/events') return jsonResponse({ detail: { code: 'revision_conflict', message: 'The case revision changed before the event could be appended.' } }, 409);
    return jsonResponse({ detail: { code: 'case_not_found', message: 'Case not found.' } }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
  vi.spyOn(api, 'createCase').mockResolvedValue(record('case-conflict', 'Original source message.'));
  render(<App />);
  const user = userEvent.setup();
  await fillSubmission(user, 'Original source message.');
  await user.click(screen.getByRole('button', { name: /analyse conversation/i }));
  await screen.findByText('Your conversation, in context.');
  await user.type(screen.getByPlaceholderText(/paste the next message exactly/i), 'Late event submission.');
  await user.click(screen.getByRole('button', { name: /add message/i }));
  expect(await screen.findByRole('alert')).toHaveTextContent('The case revision changed before the event could be appended.');
  expect(await screen.findByRole('status')).toHaveTextContent(/latest case reloaded/i);
  expect(screen.getByText('Revision 2')).toBeInTheDocument();
});

it('surfaces a backend 400 message without inventing or hiding its contract error', async () => {
  const fetchMock = vi.fn(async (path: string, init: RequestInit = {}) => {
    if (path === '/session') return jsonResponse({ expires_at: '2030-01-01T00:00:00Z' });
    if (path === '/cases' && init.method === 'POST') return jsonResponse({ detail: { code: 'invalid_payload', message: 'Invalid field syntax.' } }, 400);
    return jsonResponse({ detail: { code: 'case_not_found', message: 'Case not found.' } }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
  render(<App />);
  const user = userEvent.setup();
  await fillSubmission(user, 'A message with enough context.');
  await user.click(screen.getByRole('button', { name: /analyse conversation/i }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Invalid field syntax.');
  expect(fetchMock.mock.calls.filter(([path]) => path === '/cases')).toHaveLength(1);
});

it('prevents a late response for an older deep-linked case from replacing the newer case', async () => {
  const deferred = new Map<string, (value: CaseRecord) => void>();
  vi.spyOn(api, 'getCase').mockImplementation((id) => new Promise(resolve => deferred.set(id, resolve)));
  window.history.replaceState({}, '', '/?case=case-1');
  const view = render(<App />);
  await waitFor(() => expect(api.getCase).toHaveBeenCalledWith('case-1'));
  window.history.replaceState({}, '', '/?case=case-2');
  view.rerender(<App />);
  await waitFor(() => expect(api.getCase).toHaveBeenCalledWith('case-2'));
  deferred.get('case-2')?.(record('case-2', 'Case 2 message.'));
  expect(await screen.findByText('Case 2 message.')).toBeInTheDocument();
  deferred.get('case-1')?.(record('case-1', 'Case 1 message.'));
  await new Promise(resolve => setTimeout(resolve, 0));
  expect(screen.getByText('Case 2 message.')).toBeInTheDocument();
  expect(screen.queryByText('Case 1 message.')).not.toBeInTheDocument();
});
