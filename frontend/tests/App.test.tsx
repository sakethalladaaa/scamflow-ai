import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../src/App';
import { api, ApiError, type Assessment, type CaseRecord, type CreatedReviewRequest, type Message, type ReviewerDetail, type ReviewRequestStatus } from '../src/api';

const messages: Message[] = [
  { id: 'm1', order: 1, sender: 'Sender', channel: 'SMS', text: 'Hi, please send your OTP 🔐 now.' },
  { id: 'm2', order: 2, sender: 'Sender', channel: 'SMS', text: 'Transfer the money today.' }
];
function assessment(revision = 1, state: Assessment['state'] = 'review'): Assessment {
  const quote = 'send your OTP 🔐 now';
  return { id: `a${revision}`, revision, state, reasons: ['Review the request carefully.'], evidence: [{ messageId: 'm1', quote, reason: 'Exact source excerpt.', startOffset: 11, endOffset: 11 + Array.from(quote).length }], nextAction: 'Verify independently.', limitations: ['This tool is not a safety guarantee.'], extractionMode: 'rules' };
}
function record(revision = 1, current = assessment(revision)): CaseRecord { return { id: 'case-1', revision, channel: 'SMS', messages, current, history: [current], answers: [] }; }
async function startCase(user = userEvent.setup()) {
  render(<App />);
  await user.type(screen.getByLabelText(/conversation text/i), 'Sender: please send your OTP 🔐 now.');
  await user.click(screen.getByText(/optional: add amount or recipient context/i));
  await user.type(screen.getByLabelText(/stated payment purpose/i), 'Account verification');
  await user.click(screen.getByRole('checkbox'));
  await user.click(screen.getByRole('button', { name: /analyse conversation/i }));
  return user;
}

afterEach(cleanup);
beforeEach(() => { vi.restoreAllMocks(); });

describe('ScamFlow journey', () => {
  it('requires consent before submission', async () => {
    render(<App />);
    await userEvent.type(screen.getByLabelText(/conversation text/i), 'Please send a code.');
    await userEvent.click(screen.getByRole('button', { name: /analyse conversation/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/confirm consent/i);
    const create = vi.spyOn(api, 'createCase');
    expect(create).not.toHaveBeenCalled();
  });

  it('submits after consent and prevents double submission while pending', async () => {
    let resolveGate!: (value: CaseRecord) => void;
    const gate = new Promise<CaseRecord>(resolve => { resolveGate = resolve; });
    const create = vi.spyOn(api, 'createCase').mockReturnValue(gate);
    render(<App />);
    await userEvent.type(screen.getByLabelText(/conversation text/i), 'Sender: transfer now.');
    await userEvent.click(screen.getByText(/optional: add amount or recipient context/i));
    await userEvent.type(screen.getByLabelText(/stated payment purpose/i), 'Account verification');
    await userEvent.click(screen.getByRole('checkbox'));
    const button = screen.getByRole('button', { name: /analyse conversation/i });
    fireEvent.click(button); fireEvent.click(button);
    expect(create).toHaveBeenCalledTimes(1);
    resolveGate(record());
    expect(await screen.findByText('Your conversation, in context.')).toBeInTheDocument();
  });

  it('renders exact evidence as text and highlights Unicode/emoji safely', async () => {
    vi.spyOn(api, 'createCase').mockResolvedValue(record());
    await startCase();
    const marks = await screen.findAllByText('send your OTP 🔐 now', { selector: 'mark' });
    expect(marks.length).toBeGreaterThan(0);
    expect(screen.getByText(/Exact source excerpt/)).toBeInTheDocument();
  });

  it('does not highlight a quote that is not an exact original substring', async () => {
    const bad = record(); bad.current!.evidence[0].quote = 'OTP now';
    vi.spyOn(api, 'createCase').mockResolvedValue(bad);
    await startCase();
    await screen.findByText('Your conversation, in context.');
    expect(document.querySelector('mark')).toBeNull();
  });

  it('keeps prefix replay unavailable because the backend assesses persisted revisions only', async () => {
    vi.spyOn(api, 'createCase').mockResolvedValue(record());
    const assess = vi.spyOn(api, 'assess');
    await startCase();
    expect(screen.getByText(/Prefix replay is unavailable: the backend assesses persisted case revisions only/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /replay one message at a time/i })).not.toBeInTheDocument();
    expect(assess).not.toHaveBeenCalled();
  });

  it('shows prior assessments as historical after appending a message', async () => {
    vi.spyOn(api, 'createCase').mockResolvedValue(record());
    vi.spyOn(api, 'appendMessage').mockResolvedValue({ ...record(2), current: assessment(1), history: [assessment(1)] });
    const user = await startCase();
    await user.type(screen.getByLabelText(/new message text/i), 'A new message.');
    await user.click(screen.getByRole('button', { name: /add message/i }));
    expect(await screen.findByRole('status')).toHaveTextContent(/historical/i);
    expect(screen.getByText('Revision 2')).toBeInTheDocument();
    expect(screen.getByText(/Revision 1/)).toBeInTheDocument();
    expect(document.body.textContent).toContain('This result is historical');
    expect(screen.getByRole('button', { name: /reassess current revision/i })).toBeInTheDocument();
  });

  it('suppresses repeated interruption text when the assessment state is unchanged', async () => {
    vi.spyOn(api, 'createCase').mockResolvedValue(record(1, assessment(1, 'unable_to_assess')));
    vi.spyOn(api, 'assess').mockResolvedValue(record(1, assessment(1, 'unable_to_assess')));
    const user = await startCase();
    await user.click(screen.getByRole('button', { name: /retry assessment/i }));
    expect(await screen.findByRole('status')).toHaveTextContent(/No new material change/i);
  });

  it('shows a material assessment change clearly', async () => {
    vi.spyOn(api, 'createCase').mockResolvedValue(record(1, assessment(1, 'unable_to_assess')));
    vi.spyOn(api, 'assess').mockResolvedValue(record(1, assessment(1, 'high_risk')));
    const user = await startCase();
    await user.click(screen.getByRole('button', { name: /retry assessment/i }));
    expect(await screen.findByRole('status')).toHaveTextContent(/What changed/i);
  });

  it('recovers from revision conflict by reloading latest case', async () => {
    vi.spyOn(api, 'createCase').mockResolvedValue(record());
    vi.spyOn(api, 'appendMessage').mockRejectedValue(new ApiError('Revision conflict.', 409));
    vi.spyOn(api, 'getCase').mockResolvedValue(record(2));
    const user = await startCase();
    await user.type(screen.getByLabelText(/new message text/i), 'Another message');
    await user.click(screen.getByRole('button', { name: /add message/i }));
    expect(await screen.findByRole('status')).toHaveTextContent(/Revision conflict/i);
    expect(screen.getAllByText('Revision 2').length).toBeGreaterThan(0);
  });

  it('requires explicit deletion confirmation', async () => {
    vi.spyOn(api, 'createCase').mockResolvedValue(record());
    const remove = vi.spyOn(api, 'deleteCase').mockResolvedValue();
    const user = await startCase();
    await user.click(screen.getByRole('button', { name: /delete case/i }));
    expect(remove).not.toHaveBeenCalled();
    const dialog = screen.getByRole('dialog', { name: /delete this case/i });
    await within(dialog).findByText(/cannot restore it/i);
    await user.click(within(dialog).getByRole('button', { name: /^delete case$/i }));
    expect(await screen.findByText('Case deleted')).toBeInTheDocument();
    expect(remove).toHaveBeenCalledWith('case-1');
  });

  it('supports keyboard submission and exposes the no-guarantee disclaimer', async () => {
    vi.spyOn(api, 'createCase').mockResolvedValue(record());
    render(<App />);
    const user = userEvent.setup();
    const input = screen.getByLabelText(/conversation text/i);
    input.focus(); await user.type(input, 'Sender: transfer now.');
    await user.click(screen.getByText(/optional: add amount or recipient context/i));
    await user.type(screen.getByLabelText(/stated payment purpose/i), 'Account verification');
    const consent = screen.getByRole('checkbox'); consent.focus(); await user.keyboard(' ');
    const button = screen.getByRole('button', { name: /analyse conversation/i }); button.focus(); await user.keyboard('{Enter}');
    expect(await screen.findByText('Your conversation, in context.')).toBeInTheDocument();
    expect(screen.getAllByText(/Sender identity is not verified. This tool is not a safety guarantee./i).length).toBeGreaterThan(0);
  });
});


async function openCheckpoint(caseRecord: CaseRecord) {
  vi.spyOn(api, 'createCase').mockResolvedValue(caseRecord);
  render(<App />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText(/conversation text/i), 'Sender: please send your OTP 🔐 now.');
  await user.type(screen.getByLabelText(/stated payment purpose/i), 'Account verification');
  await user.click(screen.getByRole('checkbox'));
  await user.click(screen.getByRole('button', { name: /analyse conversation/i }));
  await screen.findByText('Your conversation, in context.');
  await user.click(screen.getByRole('button', { name: /open simulated before you pay checkpoint/i }));
  return user;
}

it('shows a simulated checkpoint using loaded backend assessment fields and exact evidence only', async () => {
  const loaded = record(1, assessment(1, 'review'));
  loaded.current!.alert = { visible: true, reason: 'backend_review_alert' };
  const assess = vi.spyOn(api, 'assess');
  const append = vi.spyOn(api, 'appendMessage');
  const remove = vi.spyOn(api, 'deleteCase');
  const user = await openCheckpoint(loaded);

  expect(screen.getByRole('heading', { name: 'Before You Pay' })).toBeInTheDocument();
  expect(screen.getByText(/SIMULATION ONLY · NO PAYMENT ACTION/i)).toBeInTheDocument();
  expect(screen.getAllByRole('note')[0]).toHaveTextContent(/UPI, a bank, a wallet, payment links, recipient verification, OTP\/PIN entry, or money movement/i);
  expect(screen.getByText('Needs clarification or review')).toBeInTheDocument();
  expect(screen.getByText('Visible', { exact: true })).toBeInTheDocument();
  expect(screen.getByText('send your OTP 🔐 now', { selector: 'blockquote' })).toBeInTheDocument();
  expect(screen.getByText('Verify independently.')).toBeInTheDocument();
  expect(screen.getByText('This tool is not a safety guarantee.')).toBeInTheDocument();

  const returnButtons = screen.getAllByRole('button', { name: /return to case workspace/i });
  await user.click(returnButtons[0]);
  expect(screen.getByText('Your conversation, in context.')).toBeInTheDocument();
  expect(assess).not.toHaveBeenCalled();
  expect(append).not.toHaveBeenCalled();
  expect(remove).not.toHaveBeenCalled();
});

it('lets the user abandon the simulation without claiming a real payment was cancelled', async () => {
  const loaded = record(1, assessment(1, 'high_risk'));
  const assess = vi.spyOn(api, 'assess');
  const user = await openCheckpoint(loaded);

  expect(screen.getByText(/Pause before taking any payment action/i)).toBeInTheDocument();
  expect(screen.getByText(/Independently verify through an official channel/i)).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: /abandon simulation/i }));

  expect(screen.getByText(/Simulation abandoned\. No payment was started or attempted\./i)).toBeInTheDocument();
  expect(screen.getByText('Your conversation, in context.')).toBeInTheDocument();
  expect(assess).not.toHaveBeenCalled();
});

it('does not present a no-strong-indicators result as payment clearance', async () => {
  await openCheckpoint(record(1, assessment(1, 'no_strong_indicators')));

  expect(screen.getByText('No strong indicators found')).toBeInTheDocument();
  expect(screen.getByText(/not a safety guarantee or payment clearance/i)).toBeInTheDocument();
  expect(screen.getByText(/recipient and payment details have not been verified/i)).toBeInTheDocument();
});

it('shows unable-to-assess and missing-assessment cases as unavailable, not reassuring', async () => {
  await openCheckpoint(record(1, assessment(1, 'unable_to_assess')));
  expect(screen.getByText('Unable to assess')).toBeInTheDocument();
  expect(screen.getByText(/backend could not produce an assessment/i)).toBeInTheDocument();
  expect(screen.getByText(/not a safety guarantee or payment clearance/i)).toBeInTheDocument();

  cleanup();
  vi.restoreAllMocks();
  const unavailable: CaseRecord = {
    ...record(),
    current: undefined,
    history: [],
    assessmentFailure: 'Assessment service unavailable.',
  };
  await openCheckpoint(unavailable);
  expect(screen.getByRole('heading', { name: 'No assessment available' })).toBeInTheDocument();
  expect(screen.getByText(/Assessment service unavailable/i)).toBeInTheDocument();
  expect(screen.getByText(/Do not treat the missing result as reassurance/i)).toBeInTheDocument();
});


afterEach(() => window.history.replaceState({}, '', '/'));

describe('persisted review workflow UI', () => {
  it('offers owner review only for a current uncertain assessment and displays backend status', async () => {
    const current = record();
    current.current!.isCurrent = true;
    vi.spyOn(api, 'createCase').mockResolvedValue(current);
    const created: CreatedReviewRequest = { reviewRequestId: 'review-1', caseId: 'case-1', assessmentId: 'a1', assessedRevision: 1, status: 'open', submittedAt: '2030-01-02T03:04:05Z', resolvedAt: null, outcome: null, idempotentReplay: false, existingOpenRequest: false };
    const persisted: ReviewRequestStatus = { reviewRequestId: 'review-1', caseId: 'case-1', assessmentId: 'a1', assessedRevision: 1, status: 'open', submittedAt: '2030-01-02T03:04:05Z', resolvedAt: null, outcome: null };
    const createRequest = vi.spyOn(api, 'createReviewRequest').mockResolvedValue(created);
    const readStatus = vi.spyOn(api, 'getOwnerReviewRequest').mockResolvedValue(persisted);
    const user = await startCase();

    await user.click(screen.getByRole('button', { name: /request human review/i }));
    expect(createRequest).toHaveBeenCalledWith('case-1', 'a1', 1);
    expect(readStatus).toHaveBeenCalledWith('case-1', 'review-1');
    expect(await screen.findByText(/Status: open/)).toBeInTheDocument();
    expect(screen.getAllByText(/does not guarantee reviewer availability or notification/i).length).toBeGreaterThan(0);
  });

  it.each([
    ['high_risk', true],
    ['review', false],
  ] as const)('does not expose owner review for state=%s when the assessment is not current', async (state, currentRevision) => {
    const result = record(1, assessment(1, state));
    result.current!.isCurrent = currentRevision;
    vi.spyOn(api, 'createCase').mockResolvedValue(result);
    await startCase();
    expect(screen.queryByRole('button', { name: /request human review/i })).not.toBeInTheDocument();
  });

  it('keeps the reviewer token in page memory and displays an empty backend queue', async () => {
    window.history.replaceState({}, '', '/reviewer');
    const getQueue = vi.spyOn(api, 'getReviewerQueue').mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
    const storageWrite = vi.spyOn(Storage.prototype, 'setItem');
    render(<App />);
    const input = screen.getByLabelText(/reviewer token/i);
    expect(input).toHaveAttribute('type', 'password');
    expect(input).toHaveAttribute('autocomplete', 'off');
    const user = userEvent.setup();
    await user.type(input, 'temporary-test-token');
    await user.click(screen.getByRole('button', { name: /connect \/ refresh queue/i }));
    expect(getQueue).toHaveBeenCalledWith('temporary-test-token', 50, 0);
    expect(await screen.findByText(/No open review requests are available on this page/i)).toBeInTheDocument();
    expect(storageWrite).not.toHaveBeenCalled();
    expect(window.location.search).toBe('');
  });

  it('shows token rejection and backend-disabled errors without echoing the submitted token', async () => {
    const cases = [
      { status: 401, code: 'reviewer_auth_required', message: 'Reviewer authorization is required.', expected: /token was not accepted/i },
      { status: 503, code: 'reviewer_access_unconfigured', message: 'Reviewer access is not configured.', expected: /not configured or is currently unavailable/i },
    ] as const;
    for (const scenario of cases) {
      cleanup();
      window.history.replaceState({}, '', '/reviewer');
      vi.restoreAllMocks();
      vi.spyOn(api, 'getReviewerQueue').mockRejectedValue(new ApiError(scenario.message, scenario.status, scenario.code));
      render(<App />);
      const user = userEvent.setup();
      await user.type(screen.getByLabelText(/reviewer token/i), 'temporary-secret-fixture');
      await user.click(screen.getByRole('button', { name: /connect \/ refresh queue/i }));
      const alert = await screen.findByRole('alert');
      expect(alert).toHaveTextContent(scenario.expected);
      expect(alert).not.toHaveTextContent('temporary-secret-fixture');
    }
  });

  it('renders exact reviewer source evidence and records only the selected allowed workflow outcome', async () => {
    window.history.replaceState({}, '', '/reviewer');
    let isResolved = false;
    const queue = { items: [{ reviewRequestId: 'review-1', caseId: 'case-1', assessmentId: 'assessment-1', assessedRevision: 3, assessmentState: 'needs_clarification_or_review' as const, isCurrent: true, submittedAt: '2030-01-02T03:04:05Z' }], total: 1, limit: 50, offset: 0 };
    const getQueue = vi.spyOn(api, 'getReviewerQueue').mockImplementation(async () => isResolved ? { ...queue, items: [], total: 0 } : queue);
    const detail: ReviewerDetail = {
      reviewRequestId: 'review-1', caseId: 'case-1', assessmentId: 'assessment-1', assessedRevision: 3, status: 'open', submittedAt: '2030-01-02T03:04:05Z', resolvedAt: null, outcome: null, reviewerNote: null,
      assessment: {
        assessmentId: 'assessment-1', caseId: 'case-1', assessedRevision: 3, state: 'needs_clarification_or_review', reasonCodes: ['review_required'], explanation: 'Read the original message and verify independently.',
        evidence: [{ tactic: 'outgoing_payment', eventId: 'event-1', sourceOrder: 2, quote: '🔐', startOffset: 5, endOffset: 6, context: 'The exact quoted phrase is backend evidence.', channel: 'whatsapp', sourceText: 'GPay 🔐 now' }],
        alert: { visible: true, reason: 'assessment_updated', priorWarningState: null }, tacticsUsed: ['outgoing_payment'], relationships: [], suggestedNextAction: 'Verify independently.', limitations: ['Not a safety guarantee.'], extractionMode: 'rules', extractionVersion: 'v1', ruleVersion: 'v1', schemaVersion: 'v1', createdAt: '2030-01-02T03:04:05Z', isCurrent: true,
        paymentContext: { statedPurpose: 'Account support', amount: '20.00', recipientReference: 'Caller' },
      },
    };
    vi.spyOn(api, 'getReviewerDetail').mockResolvedValue(detail);
    const resolve = vi.spyOn(api, 'resolveReviewerRequest').mockImplementation(async (_token, _id, outcome, note) => {
      isResolved = true;
      return { reviewRequestId: 'review-1', caseId: 'case-1', assessmentId: 'assessment-1', assessedRevision: 3, status: 'resolved', submittedAt: detail.submittedAt, resolvedAt: '2030-01-02T04:00:00Z', outcome, reviewerNote: note ?? null, idempotentReplay: false };
    });
    render(<App />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/reviewer token/i), 'temporary-test-token');
    await user.click(screen.getByRole('button', { name: /connect \/ refresh queue/i }));
    await user.click(await screen.findByRole('button', { name: /Case case-1/i }));
    expect(await screen.findByText('🔐', { selector: 'mark' })).toBeInTheDocument();
    expect(screen.getByLabelText('Original source message 2').textContent).toBe('GPay 🔐 now');
    await user.selectOptions(screen.getByLabelText(/outcome/i), 'no_action');
    await user.type(screen.getByLabelText(/optional reviewer note/i), 'Assessment remains unchanged.');
    await user.click(screen.getByRole('button', { name: /record resolution/i }));
    await waitFor(() => expect(resolve).toHaveBeenCalledWith('temporary-test-token', 'review-1', 'no_action', 'Assessment remains unchanged.'));
    expect(await screen.findByText(/Backend recorded the workflow outcome “no_action”/i)).toBeInTheDocument();
    expect(screen.getByText(/does not change the assessment/i)).toBeInTheDocument();
    expect(getQueue).toHaveBeenCalledTimes(2);
  });

  it('explains when a selected reviewer request is no longer available', async () => {
    window.history.replaceState({}, '', '/reviewer');
    vi.spyOn(api, 'getReviewerQueue').mockResolvedValue({ items: [{ reviewRequestId: 'expired-1', caseId: 'case-1', assessmentId: 'assessment-1', assessedRevision: 1, assessmentState: 'unable_to_assess', isCurrent: true, submittedAt: '2030-01-02T03:04:05Z' }], total: 1, limit: 50, offset: 0 });
    vi.spyOn(api, 'getReviewerDetail').mockRejectedValue(new ApiError('Review request not found.', 404, 'review_request_not_found'));
    render(<App />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/reviewer token/i), 'temporary-test-token');
    await user.click(screen.getByRole('button', { name: /connect \/ refresh queue/i }));
    await user.click(await screen.findByRole('button', { name: /Case case-1/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/unavailable.*expired.*deleted/i);
    expect(screen.queryByRole('button', { name: /record resolution/i })).not.toBeInTheDocument();
  });
});
