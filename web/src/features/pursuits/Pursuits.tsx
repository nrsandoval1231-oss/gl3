import { type FormEvent, useEffect, useRef, useState } from 'react'
import { client, type CallNoteBody, type Pursuit, type PursuitsResult } from '../../api/client'
import '../../styles/pursuits.css'

type RefreshReceipt = {
  job: PursuitsResult['jobs'][number]
  observation: 'waiting' | 'observed' | 'unknown'
}

function time(value: string | null) { return value ? new Date(value).toLocaleString() : 'No successful research yet' }
function Facts({ title, values }: { title: string; values: string[] }) {
  return <section className="pursuit-facts"><h3>{title}</h3>{values.length ? <ul>{values.map((value, index) => <li key={index}>{value}</li>)}</ul> : <p>Unknown</p>}</section>
}

export function Pursuits() {
  const [data, setData] = useState<PursuitsResult | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [fetching, setFetching] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [recheckUnchanged, setRecheckUnchanged] = useState(false)
  const [query, setQuery] = useState('')
  const [includeDropped, setIncludeDropped] = useState(false)
  const [offset, setOffset] = useState(0)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [poll, setPoll] = useState(0)
  const [refreshReceipt, setRefreshReceipt] = useState<RefreshReceipt | null>(null)
  const active = Boolean(refreshReceipt) || (data?.jobs.some((job) => ['queued', 'running', 'leased'].includes(job.status)) ?? false)
  useEffect(() => {
    const controller = new AbortController()
    setFetching(true)
    void client.pursuits(controller.signal, includeDropped, offset).then((result) => {
      setData(result)
      setError('')
      setRefreshReceipt((current) => {
        if (!current) return null
        const observed = result.jobs.find((job) => job.id === current.job.id)
        if (!observed) return { ...current, observation: 'unknown' }
        if (observed.status === 'succeeded' || observed.status === 'failed') return null
        return { job: observed, observation: 'observed' }
      })
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) {
        setError(cause instanceof Error ? cause.message : 'Could not load pursuits.')
        setRefreshReceipt((current) => current ? { ...current, observation: 'unknown' } : current)
      }
    }).finally(() => {
      if (!controller.signal.aborted) {
        setLoading(false)
        setFetching(false)
      }
    })
    return () => controller.abort()
  }, [poll, includeDropped, offset])
  useEffect(() => {
    if (!active || fetching) return
    const timer = window.setTimeout(() => setPoll((value) => value + 1), 3000)
    return () => window.clearTimeout(timer)
  }, [active, poll, data, fetching])
  async function refresh() {
    setRefreshing(true)
    try {
      const job = await client.refreshPursuits(recheckUnchanged)
      setRefreshReceipt({ job, observation: 'waiting' })
      setPoll((value) => value + 1)
      setError('')
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Research could not be queued.') }
    finally { setRefreshing(false) }
  }
  const items = data?.items.slice(0, 10).filter((item) => `${item.project} ${item.site} ${item.organization}`.toLowerCase().includes(query.toLowerCase())) ?? []
  return <section className="pursuits-view" aria-label="Today's Power Pursuits">
    <section className="hero"><div><p className="eyebrow">Project evidence · Daily qualification actions</p><h1>Today's Power Pursuits</h1><p>Specific projects to qualify for temporary power. Action status is separate from evidence tier; unknown demand, fuel and duration stay unknown.</p></div></section>
    <div className="list-toolbar"><div><h2>{includeDropped ? `${data?.total ?? 0} saved records · page ${Math.floor(offset / 10) + 1}` : `${data?.items.filter((item) => item.action_status !== 'Drop').length ?? 0} displayed pursuits · ${data?.total ?? 0} active saved`}</h2><p>{includeDropped ? 'Dropped records retain evidence and call outcomes; they are excluded from today’s active pursuits.' : 'Up to ten defensible projects.'} {data?.excluded_count ?? 0} saved pursuits excluded.</p></div><label className="search"><span className="sr-only">Search pursuits</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={includeDropped ? 'Search this history page' : 'Search pursuits, sites, organizations'}/></label><div className="pursuit-refresh-controls"><label className="pursuit-history-toggle"><input type="checkbox" checked={recheckUnchanged} disabled={refreshing || active} onChange={(event) => setRecheckUnchanged(event.target.checked)}/>Recheck unchanged sources</label><button className="primary pursuit-refresh" disabled={refreshing || active} onClick={() => void refresh()}>{refreshing ? 'Queuing…' : active ? 'Research in progress…' : 'Refresh pursuits'}</button></div></div>
    <label className="pursuit-history-toggle"><input type="checkbox" checked={includeDropped} onChange={(event) => { setIncludeDropped(event.target.checked); setOffset(0); setLoading(true); setExpanded(null) }}/>Include dropped pursuits and saved call history</label>
    <details className="pursuit-policy"><summary>How pursuits are ranked and refreshed</summary><p>{data?.ranking_policy ?? 'Ranking policy loading…'}</p><p>{data?.scheduler ?? 'Research requires a running worker.'}</p><p>Research requests today: {data?.usage?.fetch_requests_today ?? 0}/{data?.usage?.daily_fetch_limit ?? 0} retrievals · {data?.usage?.model_requests_today ?? 0}/{data?.usage?.daily_model_limit ?? 0} model requests. No model cost is inferred from these counts.</p><p>Refresh normally reuses fully successful research for unchanged candidates for 24 hours, keeping the original retrieval times. New, failed or deferred candidates are researched. Select “Recheck unchanged sources” to retrieve unchanged candidates again within the same daily request limits.</p><p>Call notes are owner-entered information and do not change Signal, Prospect or Lead tiers.</p></details>
    {error && <p className="error-banner" role="alert">{error} Previously saved findings remain available.</p>}
    {loading && <p role="status">Loading saved pursuits…</p>}
    {refreshReceipt?.observation === 'unknown' && <p role="status" className="loading-inline">Refresh was accepted, but research status is UNKNOWN or temporarily unavailable. Saved findings stay visible; refresh remains disabled until completion is confirmed.</p>}
    {refreshReceipt?.observation === 'waiting' && <p role="status" className="loading-inline">Bounded source research is queued or running. Refresh was accepted; status confirmation is pending. Saved findings stay visible until results arrive.</p>}
    {refreshReceipt?.observation === 'observed' && <p role="status" className="loading-inline">Bounded source research is queued or running. Refresh is accepted and research is still running. Saved findings stay visible until results arrive.</p>}
    {active && !refreshReceipt && <p role="status" className="loading-inline">Bounded source research is queued or running. Saved findings stay visible until results arrive.</p>}
    {data?.jobs.filter((job) => job.status === 'failed').slice(0, 3).map((job) => <p className="error-banner" role="alert" key={job.id}>Research job failed: {job.error ?? 'No error detail available'}. Previous findings retain their original research time.</p>)}
    {!loading && !items.length && <div className="empty"><h3>{query ? 'No matching pursuits' : 'No defensible pursuits saved yet'}</h3><p>{query ? 'Try a project, site or organization name.' : 'Refresh to screen existing Austin and RRC Signals and retrieve public project evidence. A running worker is required.'}</p></div>}
    <div className="pursuit-list">{items.map((item, index) => <article className="pursuit-card" key={item.id} data-pursuit-id={item.id}>
      <button className="pursuit-heading" onClick={() => setExpanded(expanded === item.id ? null : item.id)} aria-expanded={expanded === item.id}>
        <span className="pursuit-position">{item.action_status === 'Drop' ? '—' : offset + index + 1}</span><span className="pursuit-title"><strong>{item.project}</strong><span>{item.site}</span><span>{item.organization || 'Relevant organization unknown'}</span></span><span className="pursuit-badges"><span className="tier-pill">{item.action_status}</span><small>{item.tier} · evidence tier</small></span><span aria-hidden="true">{expanded === item.id ? '−' : '+'}</span>
      </button>
      <div className="pursuit-preview"><p><strong>Project trigger:</strong> {item.trigger}</p><p className="pursuit-meta">{item.trigger_date} · Last successful research {time(item.last_researched_at)}</p><p><strong>Next action:</strong> {item.next_action}</p></div>
      {expanded === item.id && <div className="pursuit-brief">
        <Facts title="Ranking reasons" values={item.ranking_reasons}/>
        <section className="pursuit-facts"><h3>Project organization</h3><p><strong>{item.organization || 'Unknown'}</strong> · {item.organization_involvement}</p></section>
        <Facts title="Construction / startup timing" values={item.timing}/>
        <div className="pursuit-fact-grid"><Facts title="Known load" values={item.load_facts}/><Facts title="Fuel facts" values={item.fuel_facts}/><Facts title="Utility facts" values={item.utility_facts}/></div>
        <section className="pursuit-facts"><h3>Buyer route and verified relationships</h3>{!item.people.length && <p>Person assignment and purchasing authority unknown.</p>}{item.people.map((person, i) => <div className="pursuit-person" key={i}><h4>{person.name} · {person.organization}</h4><dl><dt>Corporate role</dt><dd>{person.corporate_role}</dd><dt>Project assignment</dt><dd>{person.project_assignment}</dd><dt>Purchasing authority</dt><dd>{person.purchasing_authority}</dd></dl><a href={person.source_url} target="_blank" rel="noreferrer">Relationship evidence ↗</a></div>)}{!item.contacts.length && <p>Public business contact route unknown.</p>}{item.contacts.map((contact, i) => <p key={i}><strong>{contact.organization}</strong> · {contact.label} ({contact.kind}): {contact.value} · <a href={contact.source_url} target="_blank" rel="noreferrer">Contact source ↗</a></p>)}</section>
        <Facts title="Address-matched registrations · separate work context" values={item.registration_context ?? []}/><Facts title="Unknowns" values={item.unknowns}/>{item.conflicts.length > 0 && <div className="pursuit-conflict"><Facts title="Conflicting evidence — verify first" values={item.conflicts}/></div>}
        <section className="pursuit-facts"><h3>Research freshness and retrieval</h3><p>Status: {item.research_status} · Last attempt {item.last_attempt_at ? time(item.last_attempt_at) : 'None'} · Last successful research {time(item.last_researched_at)}</p>{item.research_errors.map((message, i) => <p role="alert" className="error" key={i}>{message}</p>)}</section>
        <section className="pursuit-facts"><h3>Public-source evidence</h3>{item.evidence.map((source, i) => <div className="evidence" key={`${source.url}-${i}`}><h4><a href={source.url} target="_blank" rel="noreferrer">{source.title} ↗</a></h4><p className="pursuit-meta">{source.source_date}{source.published_at ? ` · published ${source.published_at}` : ''} · Retrieved {time(source.retrieved_at)}</p><p>{source.match_reason}</p><details><summary>Supporting source excerpt</summary><blockquote>{source.excerpt}</blockquote></details></div>)}</section>
        <CallNotes item={item} onSaved={() => setPoll((value) => value + 1)}/>
      </div>}
    </article>)}</div>
    {includeDropped && <nav className="collection-pagination" aria-label="Pursuit history pages"><button disabled={loading || offset === 0} onClick={() => { setOffset(Math.max(0, offset - 10)); setExpanded(null); setLoading(true) }}>← Previous history page</button><span>Page {Math.floor(offset / 10) + 1} · {data?.total ?? 0} saved records</span><button disabled={loading || offset + 10 >= (data?.total ?? 0)} onClick={() => { setOffset(offset + 10); setExpanded(null); setLoading(true) }}>Next history page →</button></nav>}
  </section>
}

function CallNotes({ item, onSaved }: { item: Pursuit; onSaved: () => void }) {
  const [note, setNote] = useState('')
  const [outcome, setOutcome] = useState<CallNoteBody['outcome']>('Not reached')
  const [nextAction, setNextAction] = useState('')
  const [followUp, setFollowUp] = useState('')
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [failed, setFailed] = useState(false)
  const pending = useRef<CallNoteBody | null>(null)
  async function save(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    const body = pending.current ?? { client_id: crypto.randomUUID(), note, outcome, next_action: nextAction, follow_up: followUp || null }
    pending.current = body
    try {
      await client.savePursuitNote(item.id, body)
      pending.current = null
      setNote(''); setNextAction(''); setFollowUp(''); setOutcome('Not reached')
      setMessage('Call outcome saved. Evidence tier unchanged.'); setFailed(false)
      onSaved()
    } catch (cause) { setFailed(true); setMessage(cause instanceof Error ? cause.message : 'Call note could not be saved.') }
    finally { setSaving(false) }
  }
  return <section className="pursuit-facts pursuit-notes"><h3>Saved call outcomes · Owner-entered information</h3><p>Separate from public-source findings. Notes do not promote evidence tiers.</p>{item.notes.map((entry) => <article className="pursuit-note" key={entry.id}><p><strong>{entry.outcome}</strong> · {entry.owner} · {time(entry.created_at)}</p><p>{entry.note}</p><p><strong>Next action:</strong> {entry.next_action || 'Not recorded'} · Follow-up {entry.follow_up ?? 'Not set'}</p></article>)}<form onSubmit={(event) => void save(event)}><label>Call note<textarea required maxLength={5000} value={note} onChange={(event) => { setNote(event.target.value); pending.current = null }} disabled={saving}/></label><div className="pursuit-form-grid"><label>Outcome<select value={outcome} onChange={(event) => { setOutcome(event.target.value as CallNoteBody['outcome']); pending.current = null }} disabled={saving}>{['Not reached', 'Contacted', 'Needs follow-up', 'No requirement', 'Closed'].map((value) => <option key={value}>{value}</option>)}</select></label><label>Follow-up date<input type="date" value={followUp} onChange={(event) => { setFollowUp(event.target.value); pending.current = null }} disabled={saving}/></label></div><label>Next action<input value={nextAction} maxLength={1000} onChange={(event) => { setNextAction(event.target.value); pending.current = null }} disabled={saving}/></label><button className="primary" disabled={saving}>{saving ? 'Saving…' : 'Save call outcome'}</button>{message && <p role={failed ? 'alert' : 'status'} className={failed ? 'error' : ''}>{message}</p>}</form></section>
}
