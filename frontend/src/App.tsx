import { FormEvent, useEffect, useRef, useState } from 'react'
import { ApiError, api, newKey } from './api'
import { demos } from './demos'
import type { Assessment, AssessmentEvidence, CaseRecord, Channel, EventInput } from './types'
import { splitEvidence } from './unicode'
import './styles.css'

const MOCK_NOTICE = 'Development mock — not real AI inference.'
const stateLabels: Record<Assessment['state'], string> = {
  high_risk_indicators: 'High-risk indicators',
  needs_clarification_or_review: 'Needs clarification or review',
  no_strong_indicators: 'No strong indicators detected',
  unable_to_assess: 'Unable to assess',
}

function messageFrom(error: unknown) {
  if (error instanceof ApiError) return `${error.message} (${error.code})`
  return 'The request could not be completed. Check the local server and try again.'
}

export function EvidenceText({ text, evidence }: { text: string; evidence?: AssessmentEvidence }) {
  if (!evidence) return <>{text}</>
  const [before, match, after] = splitEvidence(text, evidence.start_offset, evidence.end_offset)
  return <>{before}<mark data-testid="selected-highlight">{match}</mark>{after}</>
}

function Timeline({ record, selected }: { record: CaseRecord; selected?: AssessmentEvidence }) {
  return (
    <section className="card timeline-card" aria-labelledby="timeline-heading">
      <div className="section-heading"><div><span className="eyebrow">Evidence</span><h2 id="timeline-heading">Conversation timeline</h2></div><span className="revision">Revision {record.revision}</span></div>
      <ol className="timeline">
        {record.events.map((event) => (
          <li key={event.event_id} id={`event-${event.event_id}`} className={selected?.event_id === event.event_id ? 'event selected' : 'event'}>
            <div className="event-meta"><span>{event.channel.replace('_', ' ')}</span><span>#{event.source_order}</span></div>
            <p><EvidenceText text={event.text} evidence={selected?.event_id === event.event_id ? selected : undefined} /></p>
          </li>
        ))}
      </ol>
    </section>
  )
}

function AssessmentPanel({ assessment, onSelect }: { assessment: Assessment; onSelect: (item: AssessmentEvidence) => void }) {
  const historical = !assessment.is_current
  return (
    <section className={`card assessment ${assessment.state}`} aria-labelledby="assessment-heading">
      <div className="section-heading"><div><span className="eyebrow">Assessment</span><h2 id="assessment-heading">{stateLabels[assessment.state]}</h2></div><span className="revision">Revision {assessment.assessed_revision}</span></div>
      <p className="mock-notice">{MOCK_NOTICE}</p>
      {historical && <p className="historical" role="status">Historical result — new evidence was added after this assessment.</p>}
      {assessment.alert.visible && <p className="alert" role="alert">Alert: {assessment.alert.reason.replaceAll('_', ' ')}{assessment.alert.prior_warning_state ? `; prior warning preserved: ${stateLabels[assessment.alert.prior_warning_state]}` : ''}.</p>}
      <p>{assessment.explanation}</p>
      <div className="action-box"><strong>Before you act</strong><p>{assessment.suggested_next_action}</p></div>
      <h3>Linked excerpts</h3>
      {assessment.evidence.length === 0 ? <p className="muted">No validated excerpt was used.</p> : (
        <ul className="quotes">
          {assessment.evidence.map((item, index) => (
            <li key={`${item.event_id}-${item.start_offset}-${index}`}>
              <button type="button" onClick={() => onSelect(item)} aria-label={`Highlight quote ${item.quote}`}>
                <q>{item.quote}</q><small>{item.tactic.replaceAll('_', ' ')} · {item.context}</small>
              </button>
            </li>
          ))}
        </ul>
      )}
      <details><summary>Limitations</summary><ul>{assessment.limitations.map((item) => <li key={item}>{item}</li>)}</ul></details>
    </section>
  )
}

export default function App() {
  const [ready, setReady] = useState(false)
  const [record, setRecord] = useState<CaseRecord | null>(null)
  const [assessment, setAssessment] = useState<Assessment | null>(null)
  const [selectedEvidence, setSelectedEvidence] = useState<AssessmentEvidence>()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')
  const [consent, setConsent] = useState(false)
  const [initialText, setInitialText] = useState('')
  const [channel, setChannel] = useState<Channel>('whatsapp')
  const [purpose, setPurpose] = useState('')
  const [amount, setAmount] = useState('')
  const [recipient, setRecipient] = useState('')
  const [appendText, setAppendText] = useState('')
  const [demoId, setDemoId] = useState(demos[0].id)
  const [demoCaseId, setDemoCaseId] = useState<string | null>(null)
  const [demoCount, setDemoCount] = useState(0)
  const activeCase = useRef<string | null>(null)
  const epoch = useRef(0)
  const retryKeys = useRef(new Map<string, string>())

  const selectCase = (caseId: string | null) => {
    activeCase.current = caseId
    epoch.current += 1
    const url = new URL(window.location.href)
    if (caseId) url.searchParams.set('case', caseId); else url.searchParams.delete('case')
    window.history.replaceState({}, '', url)
  }

  const loadCase = async (caseId: string) => {
    const requestEpoch = ++epoch.current
    activeCase.current = caseId
    const loaded = await api.getCase(caseId)
    if (requestEpoch !== epoch.current || activeCase.current !== caseId) return null
    setRecord(loaded)
    try {
      const latest = await api.latest(caseId)
      if (requestEpoch === epoch.current && activeCase.current === caseId) setAssessment(latest)
    } catch (loadError) {
      if (loadError instanceof ApiError && loadError.code === 'assessment_not_found') setAssessment(null)
      else throw loadError
    }
    return loaded
  }

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        await api.bootstrap()
        if (cancelled) return
        setReady(true)
        const caseId = new URL(window.location.href).searchParams.get('case')
        if (caseId) { selectCase(caseId); await loadCase(caseId) }
      } catch (bootstrapError) { if (!cancelled) setError(messageFrom(bootstrapError)) }
    })()
    return () => { cancelled = true; epoch.current += 1 }
  }, [])

  const assessRecord = async (target: CaseRecord) => {
    const scope = `assess:${target.case_id}:${target.revision}`
    const key = retryKeys.current.get(scope) ?? newKey('assess')
    retryKeys.current.set(scope, key)
    const requestEpoch = epoch.current
    const result = await api.assess(target.case_id, key, target.revision)
    if (requestEpoch === epoch.current && activeCase.current === target.case_id) {
      setAssessment(result); setSelectedEvidence(undefined)
    }
    retryKeys.current.delete(scope)
    return result
  }

  const create = async (event: FormEvent) => {
    event.preventDefault()
    if (busy) return
    setError('')
    if (!consent) { setError('Consent is required before evidence can be stored.'); return }
    const total = initialText.length + purpose.length + recipient.length
    if (!initialText.trim() || !purpose.trim()) { setError('Add an interaction and its stated payment purpose.'); return }
    if (total > 12000) { setError('Combined case content must not exceed 12,000 characters.'); return }
    setBusy('create')
    const scope = `create:${initialText}:${purpose}:${amount}:${recipient}`
    const key = retryKeys.current.get(scope) ?? newKey('create')
    retryKeys.current.set(scope, key)
    try {
      const created = await api.createCase(key, { stated_purpose: purpose, amount: amount || null, recipient_reference: recipient || null }, [{ event_id: crypto.randomUUID(), channel, text: initialText, source_order: 1 }])
      retryKeys.current.delete(scope)
      selectCase(created.case_id)
      await loadCase(created.case_id)
    } catch (createError) { setError(messageFrom(createError)) }
    finally { setBusy('') }
  }

  const append = async (event: FormEvent) => {
    event.preventDefault()
    if (!record || busy || !appendText.trim()) return
    setBusy('append'); setError('')
    const payload: EventInput = { event_id: crypto.randomUUID(), channel, text: appendText, source_order: Math.max(...record.events.map((item) => item.source_order), 0) + 1 }
    const scope = `append:${record.case_id}:${record.revision}:${appendText}`
    const key = retryKeys.current.get(scope) ?? newKey('append')
    retryKeys.current.set(scope, key)
    try {
      await api.append(record.case_id, key, record.revision, [payload])
      retryKeys.current.delete(scope); setAppendText('')
      await loadCase(record.case_id)
    } catch (appendError) { setError(messageFrom(appendError)) }
    finally { setBusy('') }
  }

  const runAssessment = async () => {
    if (!record || busy) return
    setBusy('assess'); setError('')
    try { await assessRecord(record) } catch (assessError) { setError(messageFrom(assessError)) }
    finally { setBusy('') }
  }

  const remove = async () => {
    if (!record || busy || !window.confirm('Permanently delete this case and its derived assessments?')) return
    setBusy('delete'); setError('')
    try {
      await api.deleteCase(record.case_id)
      if (demoCaseId === record.case_id) { setDemoCaseId(null); setDemoCount(0) }
      selectCase(null); setRecord(null); setAssessment(null); setSelectedEvidence(undefined)
    } catch (deleteError) { setError(messageFrom(deleteError)) }
    finally { setBusy('') }
  }

  const revealDemo = async () => {
    if (busy) return
    const scenario = demos.find((item) => item.id === demoId) ?? demos[0]
    if (demoCaseId && record?.case_id !== demoCaseId) { setError('Reset the current demo before starting another demo case.'); return }
    if (demoCount >= scenario.events.length) return
    setBusy('demo'); setError('')
    try {
      let target: CaseRecord
      if (!demoCaseId) {
        const first = scenario.events[0]
        const created = await api.createCase(newKey('demo-create'), scenario.payment, [first])
        setDemoCaseId(created.case_id); setDemoCount(1); selectCase(created.case_id)
        target = (await loadCase(created.case_id)) as CaseRecord
      } else {
        if (!record) throw new Error('Demo case is unavailable')
        const next = scenario.events[demoCount]
        await api.append(record.case_id, newKey('demo-append'), record.revision, [next])
        setDemoCount((value) => value + 1)
        target = (await loadCase(record.case_id)) as CaseRecord
      }
      if (target) await assessRecord(target)
    } catch (demoError) { setError(messageFrom(demoError)) }
    finally { setBusy('') }
  }

  const resetDemo = async () => {
    if (!demoCaseId || busy) return
    setBusy('demo-reset'); setError('')
    try {
      await api.deleteCase(demoCaseId)
      if (record?.case_id === demoCaseId) { selectCase(null); setRecord(null); setAssessment(null) }
      setDemoCaseId(null); setDemoCount(0)
    } catch (resetError) { setError(messageFrom(resetError)) }
    finally { setBusy('') }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar"><a className="brand" href="/" aria-label="ScamFlow AI home"><span>SF</span> ScamFlow AI</a><nav aria-label="Main navigation"><a href="#intake">New check</a><a href="#timeline-heading">Evidence</a><a href="#demo">Synthetic demos</a></nav><p className="privacy">Evidence stays in your configured local database. Session secrets remain in protected cookies.</p></aside>
      <main>
        <header className="topbar"><div><span className="eyebrow">Before-you-pay safety copilot</span><h1>Pause. Check the pattern. Keep control.</h1></div><span className={ready ? 'status ready' : 'status'}>{ready ? 'Local session ready' : 'Connecting…'}</span></header>
        <p className="mock-banner">{MOCK_NOTICE}</p>
        {error && <div className="error" role="alert">{error}</div>}
        <section id="demo" className="card demo-card" aria-labelledby="demo-heading"><div><span className="eyebrow">Guided test</span><h2 id="demo-heading">Incremental synthetic replay</h2><p>Each click reveals and submits exactly one event through the normal case APIs.</p></div><label>Scenario<select value={demoId} disabled={Boolean(demoCaseId)} onChange={(e) => setDemoId(e.target.value)}>{demos.map((item) => <option value={item.id} key={item.id}>{item.title}</option>)}</select></label><div className="button-row"><button type="button" onClick={revealDemo} disabled={Boolean(busy) || demoCount >= (demos.find((item) => item.id === demoId)?.events.length ?? 0)}>{busy === 'demo' ? 'Replaying…' : demoCaseId ? 'Reveal next & reassess' : 'Start demo'}</button><button className="secondary" type="button" onClick={resetDemo} disabled={!demoCaseId || Boolean(busy)}>Reset this demo</button></div></section>
        {!record ? (
          <form id="intake" className="card form-card" onSubmit={create} noValidate><span className="eyebrow">New case</span><h2>Check an interaction</h2><label>Message or transcript<textarea maxLength={12000} required value={initialText} onChange={(e) => setInitialText(e.target.value)} placeholder="Paste the exact text. Whitespace and emoji are preserved." /></label><div className="form-grid"><label>Channel<select value={channel} onChange={(e) => setChannel(e.target.value as Channel)}><option value="whatsapp">WhatsApp</option><option value="sms">SMS</option><option value="call_transcript">Call transcript</option><option value="email">Email</option><option value="other_text">Other text</option></select></label><label>Stated payment purpose<input required maxLength={12000} value={purpose} onChange={(e) => setPurpose(e.target.value)} /></label><label>Amount (optional)<input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="5000.00" /></label><label>Recipient reference (optional)<input maxLength={256} value={recipient} onChange={(e) => setRecipient(e.target.value)} /></label></div><label className="consent"><input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} /> I consent to storing this evidence locally for assessment.</label><button disabled={Boolean(busy)}>{busy === 'create' ? 'Creating…' : 'Create case'}</button></form>
        ) : (
          <div className="workspace"><div><Timeline record={record} selected={selectedEvidence} /><form className="card append" onSubmit={append}><h2>Add clarification or new evidence</h2><p className="muted">New text is appended as revisioned evidence; originals are never rewritten.</p><textarea required maxLength={12000} value={appendText} onChange={(e) => setAppendText(e.target.value)} placeholder="Add the exact next message or clarification" /><div className="button-row"><button disabled={Boolean(busy) || !appendText.trim()}>{busy === 'append' ? 'Appending…' : 'Append evidence'}</button><button type="button" className="secondary" onClick={runAssessment} disabled={Boolean(busy)}>{busy === 'assess' ? 'Assessing…' : assessment ? 'Reassess current revision' : 'Assess case'}</button><button type="button" className="danger" onClick={remove} disabled={Boolean(busy)}>Delete case</button></div></form></div><div>{assessment ? <AssessmentPanel assessment={assessment} onSelect={(item) => { setSelectedEvidence(item); document.getElementById(`event-${item.event_id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }) }} /> : <section className="card empty"><h2>No assessment yet</h2><p>Assess the current revision to see evidence-linked findings.</p><button onClick={runAssessment} disabled={Boolean(busy)}>Assess case</button></section>}</div></div>
        )}
      </main>
    </div>
  )
}
