import { useRef, useState, type FormEvent, type ReactNode } from 'react';
import { AlertCircle, ArrowLeft, ChevronLeft, ChevronRight, CircleHelp, LockKeyhole, RefreshCw, ShieldCheck, TriangleAlert } from 'lucide-react';
import { api, ApiError, type BackendAssessmentState, type ReviewerDetail, type ReviewerEvidence, type ReviewerQueue, type ReviewOutcome } from './api';

const PAGE_SIZE = 50;
const stateLabels: Record<BackendAssessmentState, string> = {
  high_risk_indicators: 'High-risk indicators detected',
  needs_clarification_or_review: 'Needs clarification or review',
  no_strong_indicators: 'No strong indicators found',
  unable_to_assess: 'Unable to assess',
};
const outcomes: Array<{ value: ReviewOutcome; label: string }> = [
  { value: 'follow_up', label: 'Follow up' },
  { value: 'escalated', label: 'Escalated' },
  { value: 'no_action', label: 'No action' },
  { value: 'inconclusive', label: 'Inconclusive' },
];

function failureMessage(error: unknown, kind: 'queue' | 'detail' | 'resolve'): string {
  if (!(error instanceof ApiError)) return 'The reviewer request could not be completed. No additional action was confirmed.';
  if (error.status === 401) return 'Reviewer token was not accepted. Check that the manually entered token is correct.';
  if (error.status === 503 || error.code === 'reviewer_access_unconfigured') return 'Reviewer access is not configured or is currently unavailable on the backend. Contact the backend administrator; entering a token here cannot enable it.';
  if (error.status === 404) return kind === 'detail'
    ? 'This request is unavailable. It may have expired, been deleted, or no longer be visible to the reviewer.'
    : 'The requested review resource is unavailable. Refresh the queue and try again.';
  if (error.status === 0) return 'The backend could not be reached. The request may have been received; retry the same action to safely reuse its idempotency key.';
  if (error.status === 502 || error.code === 'request_failed') return 'The backend or gateway could not confirm the request result. Retry the same action to reuse its idempotency key safely.';
  if (error.status === 409) return `The backend rejected this stale or conflicting workflow action: ${error.message}`;
  return error.message;
}

function formatDate(value: string): string {
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? new Date(timestamp).toLocaleString() : value;
}

function hasExactEvidenceSpan(item: ReviewerEvidence): boolean {
  const source = Array.from(item.sourceText);
  return Number.isInteger(item.startOffset)
    && Number.isInteger(item.endOffset)
    && item.startOffset >= 0
    && item.endOffset > item.startOffset
    && item.endOffset <= source.length
    && source.slice(item.startOffset, item.endOffset).join('') === item.quote;
}

function EvidenceSource({ item }: { item: ReviewerEvidence }) {
  const source = Array.from(item.sourceText);
  const valid = hasExactEvidenceSpan(item);
  let content: ReactNode = item.sourceText;
  if (valid) {
    content = <>{source.slice(0, item.startOffset).join('')}<mark className="evidence-mark">{item.quote}</mark>{source.slice(item.endOffset).join('')}</>;
  }
  return <article className="reviewer-evidence">
    <div className="reviewer-evidence-heading"><b>{item.tactic}</b><span>Message {item.sourceOrder} · {item.channel}</span></div>
    {valid ? <blockquote>{item.quote}</blockquote> : <p className="inline-error" role="note">The stored quote does not match its source offsets; no excerpt is highlighted.</p>}
    <p className="reviewer-evidence-context">{item.context}</p>
    <div className="reviewer-source" aria-label={`Original source message ${item.sourceOrder}`}>{content}</div>
  </article>;
}

export default function ReviewerDashboard({ onReturn }: { onReturn: () => void }) {
  const [token, setToken] = useState('');
  const tokenRef = useRef('');
  const [queue, setQueue] = useState<ReviewerQueue | null>(null);
  const [offset, setOffset] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ReviewerDetail | null>(null);
  const [outcome, setOutcome] = useState<ReviewOutcome>('follow_up');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  async function loadQueue(nextOffset = offset) {
    const requestToken = token;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const result = await api.getReviewerQueue(requestToken, PAGE_SIZE, nextOffset);
      if (tokenRef.current !== requestToken) return;
      setQueue(result);
      setOffset(result.offset);
      setSelectedId(null);
      setDetail(null);
      setNotice('Queue refreshed from the backend. Only open requests are listed.');
    } catch (reason) {
      if (tokenRef.current === requestToken) {
        setQueue(null);
        setSelectedId(null);
        setDetail(null);
        setError(failureMessage(reason, 'queue'));
      }
    } finally {
      if (tokenRef.current === requestToken) setBusy(false);
    }
  }

  async function openRequest(reviewRequestId: string) {
    const requestToken = token;
    setSelectedId(reviewRequestId);
    setDetail(null);
    setError('');
    setNotice('');
    setBusy(true);
    try {
      const result = await api.getReviewerDetail(requestToken, reviewRequestId);
      if (tokenRef.current === requestToken) setDetail(result);
    } catch (reason) {
      if (tokenRef.current === requestToken) setError(failureMessage(reason, 'detail'));
    } finally {
      if (tokenRef.current === requestToken) setBusy(false);
    }
  }

  async function resolveRequest(event: FormEvent) {
    event.preventDefault();
    if (!detail || detail.status !== 'open') return;
    const requestToken = token;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const result = await api.resolveReviewerRequest(requestToken, detail.reviewRequestId, outcome, note || undefined);
      if (tokenRef.current !== requestToken) return;
      setDetail(previous => previous ? { ...previous, status: result.status, resolvedAt: result.resolvedAt, outcome: result.outcome, reviewerNote: result.reviewerNote } : previous);
      setNotice(`Backend recorded the workflow outcome “${result.outcome ?? outcome}”. This does not change the assessment.`);
      try {
        const updatedQueue = await api.getReviewerQueue(requestToken, PAGE_SIZE, offset);
        setQueue(updatedQueue);
      } catch (reason) {
        setError(failureMessage(reason, 'queue'));
      }
    } catch (reason) {
      if (tokenRef.current === requestToken) setError(failureMessage(reason, 'resolve'));
    } finally {
      if (tokenRef.current === requestToken) setBusy(false);
    }
  }

  const totalPages = queue ? Math.max(1, Math.ceil(queue.total / PAGE_SIZE)) : 0;
  const pageNumber = queue ? Math.floor(queue.offset / PAGE_SIZE) + 1 : 0;
  const canGoBack = queue !== null && queue.offset > 0;
  const canGoForward = queue !== null && queue.offset + queue.items.length < queue.total && queue.offset + PAGE_SIZE <= 100_000;

  return <div className="app-shell reviewer-app">
    <header className="topbar"><div className="topbar-inner"><a className="brand" href="/" onClick={event => { event.preventDefault(); onReturn(); }}><span className="brand-mark"><ShieldCheck size={20}/></span><span>scamflow<span className="brand-ai"> AI</span></span></a><button className="back-link" type="button" onClick={onReturn}><ArrowLeft size={15}/> Return to ScamFlow</button></div></header>
    <main className="reviewer-page wrap">
      <div className="reviewer-intro"><div className="step-label"><span><LockKeyhole size={13}/></span> RESTRICTED REVIEW WORKFLOW</div><h1>Reviewer dashboard</h1><p>This view retrieves persisted review requests and assessment snapshots from the connected backend. It does not create a new assessment or alter its state.</p></div>
      <section className="reviewer-security-note" role="note"><LockKeyhole size={18}/><div><b>Reviewer access is separately authorized.</b><p>Use a signed-in reviewer account in production. Local development may use a manually entered token; it stays in this page's React memory and is never stored in browser storage, a URL, or a request body.</p></div></section>
      <form className="reviewer-connect" onSubmit={event => { event.preventDefault(); void loadQueue(0); }}>
        <label className="field" htmlFor="reviewer-token">Reviewer token<input id="reviewer-token" type="password" value={token} disabled={busy} onChange={event => { tokenRef.current=event.target.value;setToken(event.target.value);setQueue(null);setDetail(null);setSelectedId(null);setError('');setNotice(''); }} autoComplete="off" spellCheck={false} autoCapitalize="none" /></label>
        <button className="button button-primary" type="submit" disabled={busy}><LockKeyhole size={15}/>{busy?'Connecting…':'Connect / refresh queue'}</button>
      </form>
      {error&&<div className="inline-error reviewer-message" role="alert"><AlertCircle size={17}/>{error}</div>}
      {notice&&<div className="inline-notice reviewer-message" role="status">{notice}</div>}
      {!queue&&<section className="reviewer-empty"><CircleHelp size={20}/><div><h2>Queue not loaded</h2><p>Reviewer access may be disabled on the backend. A token must be configured server-side before this page can retrieve requests.</p></div></section>}
      {queue&&<div className="reviewer-grid">
        <section className="reviewer-queue-panel" aria-labelledby="reviewer-queue-title">
          <div className="reviewer-panel-heading"><div><div className="panel-overline">PERSISTED BACKEND DATA</div><h2 id="reviewer-queue-title">Open review requests</h2></div><button className="icon-button" type="button" onClick={()=>void loadQueue(offset)} disabled={busy} aria-label="Refresh queue"><RefreshCw size={16}/></button></div>
          <p className="muted-copy">{queue.total} open request{queue.total===1?'':'s'} reported by the backend.</p>
          {queue.items.length===0?<p className="reviewer-empty-inline">No open review requests are available on this page.</p>:<div className="reviewer-queue-list">{queue.items.map(item=><button className={`reviewer-queue-item ${selectedId===item.reviewRequestId?'selected':''}`} type="button" key={item.reviewRequestId} onClick={()=>void openRequest(item.reviewRequestId)} disabled={busy}>
            <span className="reviewer-queue-title">Case {item.caseId}</span><span className="reviewer-queue-state">{stateLabels[item.assessmentState]}</span><span className="reviewer-queue-meta">Revision {item.assessedRevision} · {formatDate(item.submittedAt)}</span>{!item.isCurrent&&<span className="reviewer-stale">Assessment is historical for the current case</span>}
          </button>)}</div>}
          <div className="reviewer-pagination"><button className="button button-quiet" type="button" onClick={()=>void loadQueue(Math.max(0,offset-PAGE_SIZE))} disabled={busy||!canGoBack}><ChevronLeft size={15}/>Previous</button><span>{queue.total?`Page ${pageNumber} of ${totalPages}`:'Page 0 of 0'}</span><button className="button button-quiet" type="button" onClick={()=>void loadQueue(offset+PAGE_SIZE)} disabled={busy||!canGoForward}>Next<ChevronRight size={15}/></button></div>
        </section>
        <section className="reviewer-detail-panel" aria-labelledby="reviewer-detail-title">
          {!detail?<div className="reviewer-empty"><CircleHelp size={20}/><div><h2 id="reviewer-detail-title">Select a request</h2><p>Reviewer-only details are fetched from the backend when selected. Requests that expire or are deleted may no longer be available.</p></div></div>:<>
            <div className="reviewer-panel-heading"><div><div className="panel-overline">REQUEST {detail.reviewRequestId}</div><h2 id="reviewer-detail-title">Case {detail.caseId}</h2></div><span className={`reviewer-status ${detail.status}`}>{detail.status}</span></div>
            {!detail.assessment.isCurrent&&<div className="reviewer-stale-banner" role="note"><TriangleAlert size={17}/> This persisted assessment is not for the current case revision. Review the snapshot as historical.</div>}
            <p className="reviewer-detail-meta">Submitted {formatDate(detail.submittedAt)} · Assessment revision {detail.assessedRevision}</p>
            <section className="reviewer-snapshot state-review"><div className="panel-overline">BACKEND ASSESSMENT SNAPSHOT</div><h3>{stateLabels[detail.assessment.state]}</h3><p>{detail.assessment.explanation}</p><div className="reviewer-field"><b>Backend alert status</b><span>{detail.assessment.alert.visible?'Visible':'Not visible'} · {detail.assessment.alert.reason}</span></div><div className="reviewer-field"><b>Safe next action</b><span>{detail.assessment.suggestedNextAction}</span></div><div className="reviewer-field"><b>Stated payment purpose</b><span>{detail.assessment.paymentContext.statedPurpose}</span></div>{detail.assessment.paymentContext.amount&&<div className="reviewer-field"><b>Amount (as submitted)</b><span>{detail.assessment.paymentContext.amount}</span></div>}{detail.assessment.paymentContext.recipientReference&&<div className="reviewer-field"><b>Recipient reference</b><span>{detail.assessment.paymentContext.recipientReference}</span></div>}
              {detail.assessment.reasonCodes.length>0&&<div className="reviewer-field"><b>Backend reason codes</b><span>{detail.assessment.reasonCodes.join(', ')}</span></div>}
              <div className="reviewer-field"><b>Backend limitations</b><ul>{detail.assessment.limitations.map((limitation,index)=><li key={index}>{limitation}</li>)}</ul></div>
              <p className="reviewer-noguarantee">This snapshot is not a safety guarantee, and reviewer workflow actions do not change its assessment.</p>
            </section>
            <section className="reviewer-evidence-panel"><h3>Persisted evidence and exact source messages</h3>{detail.assessment.evidence.length===0?<p className="muted-copy">The backend returned no evidence records for this persisted assessment.</p>:detail.assessment.evidence.map((item,index)=><EvidenceSource key={`${item.eventId}-${item.sourceOrder}-${item.startOffset}-${index}`} item={item}/>)}</section>
            {detail.reviewerNote&&<section className="reviewer-note-readonly"><h3>Reviewer-only note</h3><p>{detail.reviewerNote}</p></section>}
            {detail.status==='open'?<form className="reviewer-resolution" onSubmit={resolveRequest}><h3>Record workflow resolution</h3><p>This submits one of the backend's allowed workflow outcomes. It does not modify, override, or replace the assessment.</p><label className="field" htmlFor="review-outcome">Outcome<select id="review-outcome" value={outcome} onChange={event=>setOutcome(event.target.value as ReviewOutcome)}>{outcomes.map(option=><option value={option.value} key={option.value}>{option.label}</option>)}</select></label><label className="field" htmlFor="review-note">Optional reviewer note<textarea id="review-note" rows={3} maxLength={1000} value={note} onChange={event=>setNote(event.target.value)} placeholder="Up to 1,000 Unicode code points" /></label><button className="button button-primary" type="submit" disabled={busy}>{busy?'Saving…':'Record resolution'}</button></form>:<section className="reviewer-resolution"><h3>Workflow resolved</h3><p>Backend outcome: <b>{detail.outcome??'not provided'}</b>{detail.resolvedAt?` · ${formatDate(detail.resolvedAt)}`:''}. The assessment snapshot remains unchanged.</p></section>}
          </>}
        </section>
      </div>}
      <p className="reviewer-footnote">No reviewer identity is inferred. Do not paste this token into a shared device or public browser. This frontend does not save it after leaving this page.</p>
    </main>
  </div>;
}
