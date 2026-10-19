import { useEffect, useRef, useState } from 'react'
import { client, type IntelligenceHistoryItem, type IntelligenceTasks, type OwnerFeedbackBody } from '../../api/client'

type Candidate = Record<string, unknown> & {
  field?: string; value?: string; unit?: string | null; evidence_id?: string; evidence_hash?: string
  quote?: string; section?: string; page?: number | null; publisher?: string; published_date?: string | null
  original_value?: string | null; original_unit?: string | null; precision?: number | null; date_precision?: string | null
  speaker?: string | null; speaker_organization?: string | null; speaker_role?: string | null
  source_url?: string; support?: string; status?: string
  verification_status?: string
}

const text = (value: unknown, fallback = 'Unknown') => typeof value === 'string' && value ? value : fallback
const list = (value: unknown): string[] => Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
const questionTitles: Record<string, string> = {
  UTILITY_ONLINE_DATE: 'Utility service timing',
  TEMP_LOAD_MW: 'Temporary electrical load',
  CONSTRUCTION_START: 'Construction start timing',
  COMMISSIONING_WINDOW: 'Commissioning or test-power timing',
  NATURAL_GAS_AVAILABILITY: 'Natural gas availability',
  DIRECT_BUYER_AUTHORITY: 'Direct buyer and purchasing authority',
}

export function IntelligenceResearch({ needId }: { needId: string }) {
  const [tasks, setTasks] = useState<IntelligenceTasks | null>(null)
  const [history, setHistory] = useState<IntelligenceHistoryItem[]>([])
  const [choice, setChoice] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    let timer: number | undefined
    let active = true
    setTasks(null); setHistory([]); setError(''); setNotice('')
    const load = async () => {
      try {
        const [available, result] = await Promise.all([
          client.intelligenceTasks(controller.signal), client.intelligenceHistory(needId, controller.signal),
        ])
        if (!active) return
        setTasks(available); setHistory(result.items); setError('')
        if (result.items.some((job) => job.status === 'queued' || job.status === 'running')) {
          timer = window.setTimeout(() => void load(), 1800)
        }
      } catch (cause) {
        if (active && !controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Intelligence history is unavailable.')
      }
    }
    void load()
    return () => { active = false; controller.abort(); if (timer !== undefined) window.clearTimeout(timer) }
  }, [needId, revision])

  const choices = tasks?.items.filter((item) => item.question_id && questionTitles[item.question_id]) ?? []
  const selected = choices.find((item) => `${item.task_type}|${item.question_id ?? ''}` === choice) ?? choices.find((item) => item.eligible) ?? choices[0]
  const selectedKey = selected ? `${selected.task_type}|${selected.question_id ?? ''}` : ''
  async function request() {
    if (!selected?.eligible || busy) return
    setBusy(true); setError(''); setNotice('')
    try {
      await client.requestIntelligence(needId, selected.task_type, selected.question_id ?? undefined)
      setNotice('Research request saved. Its outcome will appear here.')
      setRevision((value) => value + 1)
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Research could not be requested.') }
    finally { setBusy(false) }
  }

  return <section className="commercial-action intelligence-research" aria-label="Advisory intelligence research">
    <h3>Evidence candidates · advisory research</h3>
    <p>Every candidate remains unaccepted until reviewed. Results do not change evidence tier or commercial status.</p>
    {!tasks && !error && <p role="status">Loading task availability…</p>}
    {error && <p role="alert">{error}</p>}
    {tasks && <div className="intelligence-controls">
      <label>Research task<select value={selectedKey} onChange={(event) => setChoice(event.target.value)}>
        {choices.map((item) => <option key={`${item.task_type}|${item.question_id ?? ''}`} value={`${item.task_type}|${item.question_id ?? ''}`}>{questionTitles[item.question_id!]}</option>)}
      </select></label>
      <button type="button" disabled={busy || !selected?.eligible} onClick={() => void request()}>{busy ? 'Requesting…' : 'Research retained evidence'}</button>
    </div>}
    {tasks && selected && !selected.eligible && <p role="status">Research is unavailable for {questionTitles[selected.question_id!]}: {selected.reason || 'provider configuration or budget controls are incomplete'}.</p>}
    {tasks && choices.length === 0 && <p>No commercial research questions are available.</p>}
    {notice && <p role="status">{notice}</p>}
    {history.length === 0 && tasks && <p>No saved intelligence jobs for this need.</p>}
    {history.map((job) => <article className="commercial-note" key={job.job_id}>
      <h4>{job.task_type === 'GROUNDED_DOSSIER' || job.task_type === 'GROUNDED_EXTRACTION' ? 'Grounded evidence review' : 'Advisory research'} · {job.status.toUpperCase()}</h4>
      <p>Created {job.created_at ? new Date(job.created_at).toLocaleString() : 'Unknown'} · {job.logical_call_id ? `Call ${job.logical_call_id}` : 'No provider call reserved'}{job.uncertain && ' · Provider outcome UNKNOWN; retry blocked.'}</p>
      {job.error && <p role="alert">{job.error}</p>}
      {job.usage && <p>Usage: {job.usage.input_tokens ?? 'Unknown'} input / {job.usage.output_tokens ?? 'Unknown'} output tokens · Cost {job.usage.cost_usd == null ? 'Unknown' : `$${job.usage.cost_usd}`}</p>}
      <Candidates needId={needId} job={job}/>
      {job.result && !Array.isArray(job.result.candidates) && <p>Advisory result: {text(job.result.choice, 'Structured result recorded')} · This is not accepted evidence.</p>}
    </article>)}
  </section>
}

function Candidates({ needId, job }: { needId: string; job: IntelligenceHistoryItem }) {
  const result = job.result as Record<string, unknown> | null
  const candidates = (Array.isArray(result?.candidates) ? result.candidates : []) as Candidate[]
  if (!result || !Array.isArray(result.candidates)) return null
  return <div>
    {job.result_status === 'OCR_UNVERIFIED' && <p role="status">OCR-derived candidates remain unverified and cannot be accepted or promoted. Independently check each quote against the original source.</p>}
    {job.status === 'stale' && <p role="status">This response is retained for audit, but its source context changed while the review was running. It is stale and cannot support a current decision.</p>}
    {candidates.length > 0 && <><h4>Unaccepted source candidates</h4>{candidates.map((candidate, index) => <CandidateReview key={`${job.job_id}-${index}`} needId={needId} job={job} candidate={candidate}/>)}</>}
    {candidates.length === 0 && <p>No source-supported candidate was returned. Unknowns remain unresolved.</p>}
    {list(result?.unresolved_questions).length > 0 && <><b>Still unknown</b><ul>{list(result?.unresolved_questions).map((value) => <li key={value}>{value}</li>)}</ul></>}
    {list(result?.contradictions).length > 0 && <><b>Conflicts requiring review</b><ul>{list(result?.contradictions).map((value) => <li key={value}>{value}</li>)}</ul></>}
    {list(result?.hypotheses).length > 0 && <><b>Advisory hypotheses</b><ul>{list(result?.hypotheses).map((value) => <li key={value}>{value}</li>)}</ul></>}
  </div>
}

function CandidateReview({ needId, job, candidate }: { needId: string; job: IntelligenceHistoryItem; candidate: Candidate }) {
  const [decision, setDecision] = useState<OwnerFeedbackBody['decision']>('SUPPORTED')
  const [note, setNote] = useState('')
  const [nextAction, setNextAction] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const clientId = useRef(crypto.randomUUID())
  const exactCitation = Boolean(job.status === 'completed' && job.result_status !== 'OCR_UNVERIFIED' && candidate.evidence_id && candidate.evidence_hash && candidate.source_url && candidate.quote)
  async function save(event: React.FormEvent) {
    event.preventDefault()
    if (!job.logical_call_id || !exactCitation || !note.trim()) return
    setBusy(true); setMessage('')
    try {
      await client.saveIntelligenceFeedback(needId, {
        client_id: clientId.current, job_id: job.job_id, logical_call_id: job.logical_call_id,
        decision, note: note.trim(), next_action: nextAction,
        candidate: {
          field: text(candidate.field, ''), value: text(candidate.value, ''), unit: candidate.unit,
          original_value: candidate.original_value, original_unit: candidate.original_unit,
          precision: candidate.precision, date_precision: candidate.date_precision,
          speaker: candidate.speaker, speaker_organization: candidate.speaker_organization,
          speaker_role: candidate.speaker_role,
          evidence_id: text(candidate.evidence_id, ''), evidence_hash: text(candidate.evidence_hash, ''),
          quote: text(candidate.quote, ''), section: text(candidate.section, ''), page: candidate.page,
          span_start: typeof candidate.span_start === 'number' ? candidate.span_start : 0,
          span_end: typeof candidate.span_end === 'number' ? candidate.span_end : 0,
          publisher: text(candidate.publisher, ''), published_date: typeof candidate.published_date === 'string' ? candidate.published_date : null,
          support: text(candidate.support, ''), status: text(candidate.status, ''),
          source_url: text(candidate.source_url, ''), source_id: typeof candidate.source_id === 'string' ? candidate.source_id : null,
        },
        evidence_refs: [{ evidence_id: candidate.evidence_id!, content_hash: candidate.evidence_hash!, source_url: candidate.source_url! }],
      })
      setMessage('Owner review saved as attributed pending-review material. It did not accept a fact or change tier.')
      setNote(''); setNextAction(''); clientId.current = crypto.randomUUID()
    } catch (cause) { setMessage(cause instanceof Error ? cause.message : 'Owner review could not be saved.') }
    finally { setBusy(false) }
  }
  return <article className="intelligence-candidate">
    <p><b>{text(candidate.field, 'Candidate')}:</b> {text(candidate.value)}{candidate.unit ? ` ${candidate.unit}` : ''} · {text(candidate.support)} support · {text(candidate.status, 'candidate').toUpperCase()}</p>
    <blockquote>{text(candidate.quote, 'Quoted source passage unavailable.')}</blockquote>
    <p>{text(candidate.publisher)} · {text(candidate.source_id, 'Source ID unknown')} · {text(candidate.published_date, 'Publication date unknown')} · {text(candidate.section)}{candidate.page ? ` · page ${candidate.page}` : ''}</p>
    <p>Evidence {text(candidate.evidence_id)} · hash {text(candidate.evidence_hash)} · exact source citation {candidate.source_url ? <a href={candidate.source_url} target="_blank" rel="noreferrer">open source</a> : 'Unavailable'}</p>
    {job.logical_call_id && exactCitation ? <form onSubmit={(event) => void save(event)}>
      <label>Owner review<select value={decision} onChange={(event) => setDecision(event.target.value as OwnerFeedbackBody['decision'])}><option value="SUPPORTED">Supported</option><option value="CONFLICT">Conflict</option><option value="UNRESOLVED">Unresolved</option><option value="OTHER">Other</option></select></label>
      <label>Review note<textarea required maxLength={5000} value={note} onChange={(event) => { setNote(event.target.value); clientId.current = crypto.randomUUID() }}/></label>
      <label>Next action<input maxLength={1000} value={nextAction} onChange={(event) => { setNextAction(event.target.value); clientId.current = crypto.randomUUID() }}/></label>
      <button type="submit" disabled={busy || !note.trim()}>{busy ? 'Saving…' : 'Save attributed review'}</button>
      {message && <p role="status">{message}</p>}
    </form> : <p>Owner review is unavailable until this candidate has an exact retained-source citation and call reference.</p>}
  </article>
}
