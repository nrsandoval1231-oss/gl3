import { useEffect, useRef, useState } from 'react'
import { client, type CommercialPursuit, type PursuitStage, type PursuitTask } from '../../api/client'
import { applyPursuit } from '../../state/pursuitStore'
import { onPursuitDataEnded } from '../../state/sessionState'
import { FLOW_STAGES, formatDateTime, formatInstantDay, mailHref, powerNeed, powerTiming, telHref } from './pursuitFormat'
import { inApp, needHref, openNeed } from './pursuitNav'

type Kind = 'call' | 'email' | 'meeting' | 'note'
const KINDS: { id: Kind; label: string }[] = [{ id: 'call', label: 'Call' }, { id: 'email', label: 'Email' }, { id: 'meeting', label: 'Meeting' }, { id: 'note', label: 'Note' }]
const ACTIVITY_LABELS: Record<string, string> = { call: 'Call', email: 'Email', meeting: 'Meeting', note: 'Note', created: 'Added', stage_change: 'Stage', task_completed: 'Follow-up' }
const message = (cause: unknown, fallback: string) => cause instanceof Error && cause.message ? cause.message : fallback

type Props = { id: string; preview?: CommercialPursuit; onBack: () => void; onChanged: (updated: CommercialPursuit) => void }

export function PursuitDetail({ id, preview, onBack, onChanged }: Props) {
  const [detail, setDetail] = useState<CommercialPursuit | null>(null)
  const [loadError, setLoadError] = useState('')
  const [retry, setRetry] = useState(0)
  const [busy, setBusy] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [ended, setEnded] = useState(false)
  const writing = useRef(false)
  const endedRef = useRef(false)

  // An ended session removes contact data, notes and tasks from the screen immediately.
  useEffect(() => {
    const onEnded = () => { endedRef.current = true; setEnded(true); setDetail(null); setErrors({}); setLoadError('') }
    return onPursuitDataEnded(onEnded)
  }, [])

  useEffect(() => {
    if (ended) return
    const controller = new AbortController()
    setLoadError('')
    client.commercialPursuit(id, controller.signal)
      .then(value => { if (!controller.signal.aborted) setDetail(value) })
      .catch(cause => { if (!controller.signal.aborted) setLoadError(message(cause, 'This pursuit is unavailable.')) })
    return () => controller.abort()
  }, [id, retry, ended])

  /** One write at a time; resolves true on success so forms clear only then. */
  async function write(section: string, action: () => Promise<CommercialPursuit>): Promise<boolean> {
    if (writing.current) return false
    writing.current = true; setBusy(section); setErrors(current => ({ ...current, [section]: '' }))
    try {
      const updated = await action()
      if (endedRef.current) return false
      setDetail(updated); applyPursuit(updated); onChanged(updated)
      return true
    } catch (cause) {
      if (endedRef.current) return false
      setErrors(current => ({ ...current, [section]: message(cause, 'The change could not be saved. Try again.') }))
      return false
    } finally { writing.current = false; setBusy('') }
  }

  if (ended) return <div className="pu-detail"><div className="pu-state" role="alert"><p>Your session ended. Sign in again.</p></div></div>
  const head = detail ?? preview
  if (!head) {
    return <div className="pu-detail">
      <button type="button" className="pu-back" onClick={onBack}>← Pursuits</button>
      {loadError
        ? <div className="pu-state" role="alert"><p>{loadError}</p><button type="button" className="pu-btn" onClick={() => setRetry(value => value + 1)}>Retry</button></div>
        : <div className="pu-state" role="status" aria-busy="true"><p>Loading pursuit…</p></div>}
    </div>
  }

  const contact = head.contact
  const phone = contact?.phone ?? null, email = contact?.email ?? null
  const tel = telHref(phone), mail = mailHref(email)
  const hasContact = Boolean(phone || email)
  const tasks = detail?.tasks ?? null
  const openTasks = (tasks ?? []).filter(task => !task.completed_at)
  const doneTasks = (tasks ?? []).filter(task => task.completed_at)
  const setStage = (stage: PursuitStage) => { if (stage !== head.stage) void write('stage', () => client.setPursuitStage(head.id, stage)) }
  const stageIndex = FLOW_STAGES.indexOf(head.stage)

  return <div className="pu-detail" aria-busy={!detail}>
    <button type="button" className="pu-back" onClick={onBack}>← Pursuits</button>
    <header className="pu-detail-head">
      <div>
        <h2>{head.title}</h2>
        <p className="pu-detail-loc">{head.location || 'Location unavailable'}</p>
      </div>
      <span className={`pu-badge pu-stage-${head.stage.toLowerCase()}`}>{head.stage}</span>
    </header>
    {head.attention_labels.length > 0 && <p className="pu-attention" aria-label="Needs attention">{head.attention_labels.map(label => <span key={label} className="pu-attn-chip">{label}</span>)}</p>}
    {loadError && <p className="pu-error" role="alert">{loadError} <button type="button" className="pu-link" onClick={() => setRetry(value => value + 1)}>Retry</button></p>}

    <section className="pu-box pu-contact" aria-label="Contact">
      {contact && (contact.name || contact.company) && <div className="pu-contact-who"><strong>{contact.name || contact.company}</strong><span>{[contact.role, contact.name ? contact.company : null].filter(Boolean).join(' · ')}</span></div>}
      {hasContact
        ? <div className="pu-contact-actions">
          {tel ? <a className="pu-btn pu-btn-primary" href={tel} aria-label={`Call ${phone}`}>Call</a> : phone && <span className="pu-contact-value">{phone}</span>}
          {mail ? <a className="pu-btn pu-btn-primary" href={mail} aria-label={`Email ${email}`}>Email</a> : email && <span className="pu-contact-value">{email}</span>}
          <p className="pu-hint">{[tel ? phone : null, mail ? email : null].filter(Boolean).join(' · ')}</p>
        </div>
        : <div className="pu-no-contact">
          <strong>{head.contact_status === 'unknown' ? 'Contact status unavailable' : 'No usable contact method'}</strong>
          <span>{head.contact_status === 'unknown' ? 'Contact evidence could not be read just now.' : 'No phone or email is established in retained evidence.'}</span>
          <a className="pu-link" href={needHref(head.need_id)} onClick={event => inApp(event, () => openNeed(head.need_id))}>Review the opportunity evidence</a>
        </div>}
      <p className="pu-hint">Opening a call or email link does not log anything or change the stage.</p>
    </section>

    <dl className="pu-power">
      <div><dt>Power Need</dt><dd>{powerNeed(head.required_mw)}</dd></div>
      <div><dt>Power timing</dt><dd>{powerTiming(head.start_window)}</dd></div>
    </dl>

    <section className="pu-box" aria-label="Pursuit status">
      <h3>Pursuit Status</h3>
      <ol className="pu-stepper">
        {FLOW_STAGES.map((stage, index) => <li key={stage} className={index < stageIndex ? 'is-done' : index === stageIndex ? 'is-current' : ''}>
          <button type="button" aria-current={head.stage === stage ? 'step' : undefined} disabled={Boolean(busy) || !detail} onClick={() => setStage(stage)}>
            <span className="pu-step-dot" aria-hidden="true">{index < stageIndex ? '✓' : index + 1}</span>{stage}
          </button>
        </li>)}
      </ol>
      <div className="pu-stage-foot">
        <button type="button" className="pu-btn pu-lost" aria-pressed={head.stage === 'Lost'} disabled={Boolean(busy) || !detail || head.stage === 'Lost'} onClick={() => setStage('Lost')}>{head.stage === 'Lost' ? 'Closed as Lost' : 'Mark as Lost'}</button>
        {head.stage === 'Lost' && <span className="pu-hint">Choose a status above to reopen this pursuit.</span>}
        <span className="pu-hint">In stage since {formatInstantDay(head.stage_changed_at)}</span>
      </div>
      {errors.stage && <p className="pu-error" role="alert">{errors.stage}</p>}
    </section>

    <TasksCard tasks={tasks} openTasks={openTasks} doneTasks={doneTasks} busy={busy} error={errors.task ?? ''} onWrite={action => write('task', () => action(head.id))}/>
    <ActivityCard detail={detail} busy={busy} error={errors.activity ?? ''} onWrite={action => write('activity', () => action(head.id))}/>

    <section className="pu-box" aria-label="Project details">
      <h3>Project details</h3>
      <dl className="pu-details">
        <div><dt>Project</dt><dd>{head.title}</dd></div>
        <div><dt>Location</dt><dd>{head.location || 'Unknown'}</dd></div>
        <div><dt>Opportunity tier</dt><dd>{head.tier || 'Unknown'}</dd></div>
        <div><dt>Power Need</dt><dd>{powerNeed(head.required_mw)}</dd></div>
        <div><dt>Power timing</dt><dd>{powerTiming(head.start_window)}</dd></div>
        <div><dt>Added to Pursuits</dt><dd>{formatInstantDay(head.created_at)}</dd></div>
      </dl>
      <a className="pu-link" href={needHref(head.need_id)} onClick={event => inApp(event, () => openNeed(head.need_id))}>View opportunity and evidence</a>
    </section>
  </div>
}

type Write = (action: (id: string) => Promise<CommercialPursuit>) => Promise<boolean>

const validDue = (value: string) => { const year = Number(value.slice(0, 4)); return /^\d{4}-\d{2}-\d{2}$/.test(value) && year >= 2000 && year <= 2100 }

/** Saves on blur or Enter only, so typing a year never saves intermediate values like 0002. */
function DueDateInput({ task, busy, onWrite }: { task: PursuitTask; busy: string; onWrite: Write }) {
  const [draft, setDraft] = useState(task.due_date ?? '')
  const [invalid, setInvalid] = useState(false)
  useEffect(() => { setDraft(task.due_date ?? ''); setInvalid(false) }, [task.due_date])
  const commit = () => {
    if (draft === (task.due_date ?? '')) { setInvalid(false); return }
    if (draft && !validDue(draft)) { setInvalid(true); return }
    setInvalid(false)
    void onWrite(id => client.updatePursuitTask(id, task.id, draft ? { due_date: draft } : { clear_due_date: true }))
  }
  return <>
    <input type="date" value={draft} min="2000-01-01" max="2100-12-31" disabled={Boolean(busy)} aria-label={`Due date for: ${task.description}`} aria-invalid={invalid || undefined}
      onChange={event => { setDraft(event.target.value); setInvalid(false) }} onBlur={commit} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); commit() } }}/>
    {invalid && <small className="pu-error" role="alert">Choose a due date between 2000 and 2100.</small>}
  </>
}

function TasksCard({ tasks, openTasks, doneTasks, busy, error, onWrite }: { tasks: PursuitTask[] | null; openTasks: PursuitTask[]; doneTasks: PursuitTask[]; busy: string; error: string; onWrite: Write }) {
  const [description, setDescription] = useState('')
  const [due, setDue] = useState('')
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null)
  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    const text = description.trim()
    if (!text) return
    if (await onWrite(id => client.addPursuitTask(id, { description: text, due_date: due || null }))) { setDescription(''); setDue('') }
  }
  const row = (task: PursuitTask) => {
    const done = Boolean(task.completed_at)
    return <li key={task.id} className={done ? 'is-done' : ''}>
      <input type="checkbox" checked={done} disabled={Boolean(busy)} aria-label={`${done ? 'Reopen' : 'Complete'} follow-up: ${task.description}`}
        onChange={() => void onWrite(id => client.updatePursuitTask(id, task.id, { completed: !done }))}/>
      <div className="pu-task-body">
        {editing?.id === task.id
          ? <form className="pu-inline" onSubmit={async event => { event.preventDefault(); const text = editing.text.trim(); if (text && await onWrite(id => client.updatePursuitTask(id, task.id, { description: text }))) setEditing(null) }}>
            <input value={editing.text} maxLength={500} aria-label="Follow-up description" autoFocus onChange={event => setEditing({ id: task.id, text: event.target.value })}/>
            <button type="submit" className="pu-btn" disabled={Boolean(busy) || !editing.text.trim()}>Save</button>
            <button type="button" className="pu-btn" onClick={() => setEditing(null)}>Cancel</button>
          </form>
          : <><span className="pu-task-text">{task.description}</span>
            <button type="button" className="pu-link" aria-label={`Edit follow-up: ${task.description}`} onClick={() => setEditing({ id: task.id, text: task.description })}>Edit</button></>}
        <label className="pu-task-date"><span>Due</span>
          <DueDateInput task={task} busy={busy} onWrite={onWrite}/>
          {!task.due_date && <small>No due date</small>}
        </label>
      </div>
    </li>
  }
  return <section className="pu-box pu-next" aria-label="Next Action">
    <h3>Next Action</h3>
    {tasks === null ? <p className="pu-hint">Loading follow-ups…</p> : openTasks.length
      ? <ul className="pu-tasks">{openTasks.map(row)}</ul>
      : <p className="pu-hint">No follow-up scheduled.</p>}
    <form className="pu-form" onSubmit={event => void submit(event)} aria-label="Add follow-up">
      <input value={description} maxLength={500} placeholder="Add a follow-up task" aria-label="Follow-up description" onChange={event => setDescription(event.target.value)}/>
      <input type="date" value={due} aria-label="Follow-up due date (optional)" onChange={event => setDue(event.target.value)}/>
      <button type="submit" className="pu-btn pu-btn-primary" disabled={Boolean(busy) || !description.trim() || tasks === null}>Add follow-up</button>
    </form>
    {error && <p className="pu-error" role="alert">{error}</p>}
    {doneTasks.length > 0 && <details className="pu-done"><summary>Completed ({doneTasks.length})</summary><ul className="pu-tasks">{doneTasks.map(row)}</ul></details>}
  </section>
}

function ActivityCard({ detail, busy, error, onWrite }: { detail: CommercialPursuit | null; busy: string; error: string; onWrite: Write }) {
  const [kind, setKind] = useState<Kind>('call')
  const [summary, setSummary] = useState('')
  const [note, setNote] = useState('')
  // A retry of the same entry reuses its client_id so a lost response cannot record it twice.
  const attempt = useRef<{ signature: string; id: string } | null>(null)
  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    const text = summary.trim(), extra = note.trim()
    if (!text) return
    const signature = JSON.stringify([kind, text, extra])
    if (attempt.current?.signature !== signature) attempt.current = { signature, id: crypto.randomUUID() }
    const clientId = attempt.current.id
    if (await onWrite(id => client.logPursuitActivity(id, { kind, summary: text, detail: extra || null, client_id: clientId }))) {
      attempt.current = null; setSummary(''); setNote('')
    }
  }
  const entries = detail?.activity ?? null
  return <section className="pu-box" aria-label="Activity">
    <h3>Activity</h3>
    <form className="pu-form pu-activity-form" onSubmit={event => void submit(event)} aria-label="Log activity">
      <label><span>Type</span><select value={kind} onChange={event => setKind(event.target.value as Kind)}>{KINDS.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}</select></label>
      <label className="pu-grow"><span>Summary</span><input value={summary} maxLength={300} onChange={event => setSummary(event.target.value)} placeholder="What happened?"/></label>
      <label className="pu-full"><span>Details (optional)</span><textarea value={note} maxLength={4000} rows={2} onChange={event => setNote(event.target.value)}/></label>
      <div className="pu-full pu-activity-actions">
        <button type="submit" className="pu-btn pu-btn-primary" disabled={Boolean(busy) || !summary.trim() || !detail}>Log as happened</button>
        <span className="pu-hint">Record only what actually took place. Nothing is sent or logged until you confirm here.</span>
      </div>
    </form>
    {error && <p className="pu-error" role="alert">{error}</p>}
    {entries === null ? <p className="pu-hint">Loading activity…</p> : entries.length
      ? <ul className="pu-activity">{entries.map(entry => <li key={entry.id}>
        <span className="pu-activity-kind">{ACTIVITY_LABELS[entry.kind] ?? entry.kind}</span>
        <div><strong>{entry.summary}</strong>{entry.detail && <p>{entry.detail}</p>}<time dateTime={entry.occurred_at}>Logged {formatDateTime(entry.occurred_at)}</time></div>
      </li>)}</ul>
      : <p className="pu-hint">No activity recorded yet.</p>}
  </section>
}
