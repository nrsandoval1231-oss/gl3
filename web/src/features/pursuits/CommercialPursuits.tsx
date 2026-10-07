import { type FormEvent, useEffect, useMemo, useState } from 'react'
import { client, type BriefRequest, type CallNoteBody, type CommercialResearchStatus, type CommercialTriage, type CommercialTriageCard, type CommercialTriageHistory, type CommercialTriageHistoryItem } from '../../api/client'
import { BuyingChain } from '../buyingChain/BuyingChain'
import { ResearchChanges } from './ResearchChanges'
import { AutonomousResearch } from './AutonomousResearch'
import { Pursuits } from './Pursuits'
import '../../styles/pursuits.css'

type Disposition = 'ACTION NOW' | 'RESEARCH' | 'WATCH' | 'REJECT'
type ResearchProgress = { question: string; brief: BriefRequest; message: string; failed: boolean }
type CommercialDraft = { question: string; note: string; outcome: CallNoteBody['outcome']; nextAction: string; clientId?: string; research?: ResearchProgress }
const dispositions: Disposition[] = ['ACTION NOW', 'RESEARCH', 'WATCH', 'REJECT']
const unknown = (value: unknown) => typeof value === 'string' || typeof value === 'number' ? String(value) || 'Unknown' : 'Unknown'
function enumLabel(value: unknown) {
  if (typeof value !== 'string' || !value.trim() || /^unknown$/i.test(value.trim())) return 'Unknown'
  const words = value.replace(/[_-]+/g, ' ').trim()
  return words.charAt(0).toUpperCase() + words.slice(1)
}
const power = (value: string | null) => !value || value.toLowerCase() === 'unknown' ? 'Unknown' : /\bmw\b/i.test(value) ? value : `${value} MW`
const emptyDraft = (item: CommercialTriageCard): CommercialDraft => ({ question: item.next_question, note: '', outcome: 'Not reached', nextAction: '' })
const isRecord = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value)

function checkedCommercialTriage(value: unknown): CommercialTriage {
  const invalid = () => new Error('Commercial pursuit queue returned incomplete data. Retry the view or return to Signals.')
  if (!isRecord(value)) throw invalid()
  const cohortCounts = value.cohort_counts
  const daily = value.daily
  if (typeof value.evaluated_at !== 'string' || typeof value.policy_version !== 'string' || typeof value.total !== 'number'
    || !isRecord(cohortCounts) || !isRecord(daily) || !Array.isArray(value.items)) throw invalid()
  if (!['action_now', 'research', 'watch', 'reject'].every((key) => typeof cohortCounts[key] === 'number')
    || !['evaluated', 'surfaced', 'contacted'].every((key) => typeof daily[key] === 'number')
    || (daily.metric_scope !== undefined && !Array.isArray(daily.metric_scope))
    || (daily.unavailable_metrics !== undefined && !Array.isArray(daily.unavailable_metrics))) throw invalid()
  for (const item of value.items) {
    if (!isRecord(item) || typeof item.id !== 'string' || typeof item.project_id !== 'string' || typeof item.name !== 'string'
      || typeof item.tier !== 'string' || typeof item.activity !== 'string' || typeof item.industry !== 'string'
      || typeof item.disposition !== 'string' || typeof item.reason !== 'string' || typeof item.supply !== 'string'
      || typeof item.next_question !== 'string' || typeof item.next_action !== 'string' || !isRecord(item.stage) || typeof item.stage.stage !== 'string') throw invalid()
    for (const key of ['related_project_ids', 'related_need_ids', 'lifecycle_timeline', 'contacts', 'facts', 'unknowns', 'blockers', 'sources', 'notes']) {
      if (item[key] !== undefined && !Array.isArray(item[key])) throw invalid()
    }
  }
  return value as unknown as CommercialTriage
}

function checkedCommercialHistory(value: unknown): CommercialTriageHistory {
  if (!isRecord(value) || !Array.isArray(value.items)) throw new Error('Saved commercial history returned incomplete data. Retry the history view.')
  for (const item of value.items) {
    if (!isRecord(item) || typeof item.pursuit_id !== 'string' || typeof item.need_id !== 'string' || typeof item.project_id !== 'string'
      || typeof item.disposition !== 'string' || !['saved_as_of', 'metadata_only'].includes(String(item.snapshot_status))
      || item.live_status !== 'not_rechecked' || (item.notes !== undefined && !Array.isArray(item.notes))) throw new Error('Saved commercial history returned incomplete data. Retry the history view.')
    if (item.saved_card !== undefined && item.saved_card !== null) {
      if (!isRecord(item.saved_card) || typeof item.saved_card.id !== 'string' || typeof item.saved_card.name !== 'string'
        || typeof item.saved_card.reason !== 'string' || !isRecord(item.saved_card.stage) || typeof item.saved_card.stage.stage !== 'string') throw new Error('A saved card snapshot is incomplete. Retry the history view.')
      for (const key of ['lifecycle_timeline', 'contacts', 'facts', 'unknowns', 'blockers', 'sources', 'notes']) {
        if (item.saved_card[key] !== undefined && !Array.isArray(item.saved_card[key])) throw new Error('A saved card snapshot is incomplete. Retry the history view.')
      }
    }
    const versions = (item as Record<string, unknown>).versions
    if (versions !== undefined && (!Array.isArray(versions) || versions.some((version) => !isRecord(version)
      || typeof version.version !== 'number' || typeof version.disposition !== 'string'
      || !['saved_as_of', 'metadata_only'].includes(String(version.snapshot_status)) || version.live_status !== 'not_rechecked'
      || (version.saved_card !== null && version.saved_card !== undefined && !isRecord(version.saved_card))))) throw new Error('Saved commercial history versions are incomplete. Retry the history view.')
  }
  return value as unknown as CommercialTriageHistory
}

export function CommercialPursuits() {
  const [data, setData] = useState<CommercialTriage | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<Disposition>('ACTION NOW')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [evaluating, setEvaluating] = useState(false)
  const [legacyOpen, setLegacyOpen] = useState(false)
  const [drafts, setDrafts] = useState<Record<string, CommercialDraft>>({})

  useEffect(() => {
    const controller = new AbortController()
    void client.commercialTriage(50, controller.signal).then((result) => { setData(checkedCommercialTriage(result)); setError('') }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Commercial pursuits are unavailable.')
    }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [])

  const visible = useMemo(() => (data?.items ?? []).filter((item) => item.disposition === filter && `${item.name} ${item.location ?? ''} ${item.industry} ${item.activity} ${item.stage.stage} ${item.organization ?? ''}`.toLowerCase().includes(query.trim().toLowerCase())), [data, filter, query])
  async function evaluate() {
    setEvaluating(true)
    try { setData(checkedCommercialTriage(await client.evaluateCommercialTriage())); setError('') }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Evaluation could not be saved.') }
    finally { setEvaluating(false) }
  }
  async function refreshTriage() {
    try { setData(checkedCommercialTriage(await client.commercialTriage())); setError('') }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Commercial metrics could not refresh.') }
  }
  function updateDraft(item: CommercialTriageCard, changes: Partial<CommercialDraft>) {
    setDrafts((current) => ({ ...current, [item.id]: { ...(current[item.id] ?? emptyDraft(item)), ...changes } }))
  }

  return <section className="pursuits-view commercial-view" aria-label="Commercial pursuits">
    <section className="hero commercial-hero"><div><p className="eyebrow">Retained Signals · Commercial work queue</p><h1>What should we work today?</h1><p>Evidence-backed pursuits with clear next steps. Power, supply, timing and buying roles stay unknown until sources support them.</p></div><button type="button" className="back-button" onClick={() => void evaluate()} disabled={evaluating}>{evaluating ? 'Evaluating…' : 'Evaluate Signals'}</button></section>
    {!data && error ? <section className="commercial-unavailable" role="alert"><h2>Commercial pursuits are unavailable</h2><p>{error}</p></section> : <>
    <section className="commercial-summary" aria-label="Current cohort summary">
      <div><span>Current cohort</span><strong>{data?.total ?? '—'}</strong></div>
      {dispositions.map((state) => <div key={state}><span>{state}</span><strong>{data?.cohort_counts[state.toLowerCase().replaceAll(' ', '_') as keyof CommercialTriage['cohort_counts']] ?? '—'}</strong></div>)}
      <div className="commercial-daily">Today · {data?.daily.evaluated ?? '—'} evaluated · {data?.daily.surfaced ?? '—'} surfaced · {data?.daily.contacted ?? '—'} contacted · {data?.daily.reached_buyer ?? '—'} buyer reached · {data?.daily.qualified ?? '—'} qualified · {data?.daily.promoted_prospects ?? '—'} Prospects · {data?.daily.promoted_leads ?? '—'} Leads · {data ? unknown(data.daily.supported_mw) : '—'} supported MW <details><summary>{data?.daily.unavailable_metrics?.length ?? '—'} metric limits</summary><span>{[...(data?.daily.metric_scope ?? []), ...(data?.daily.unavailable_metrics ?? [])].join('; ') || 'No additional metric limitations reported.'}</span></details></div>
    </section>
    <ResearchChanges overview={data?.research_overview}/>
    <div className="list-toolbar commercial-toolbar"><div><h2>{filter} · {visible.length} pursuits</h2><p>Showing up to 50 retained candidates · {data?.evaluated_at ? `queue refreshed ${new Date(data.evaluated_at).toLocaleString()}` : 'evaluation has not been saved'}</p></div><label className="search"><span className="sr-only">Search commercial pursuits</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search project, company, site"/></label></div>
    <div className="commercial-filters" role="group" aria-label="Filter pursuit state">{dispositions.map((state) => <button type="button" key={state} className={filter === state ? 'commercial-filter-active' : ''} aria-pressed={filter === state} onClick={() => setFilter(state)}>{state}<span>{data?.cohort_counts[state.toLowerCase().replaceAll(' ', '_') as keyof CommercialTriage['cohort_counts']] ?? '—'}</span></button>)}</div>
    {error && <p className="error-banner" role="alert">{error} Saved findings remain available.</p>}{loading && <p role="status">Loading retained commercial pursuits…</p>}
    {!loading && data && !visible.length && <div className="empty"><h3>{query ? 'No matching pursuits' : `No ${filter.toLowerCase()} pursuits`}</h3><p>{query ? 'Try another project, company or site.' : 'The current retained cohort has no candidates in this state.'}</p></div>}
    <div className="commercial-list">{visible.map((item, index) => <CommercialCard key={item.id} item={item} index={index} expanded={expanded === item.id} draft={drafts[item.id] ?? emptyDraft(item)} onDraftChange={(changes) => updateDraft(item, changes)} onToggle={() => setExpanded(expanded === item.id ? null : item.id)} onSaved={() => void refreshTriage()}/>)}</div>
    </>}
    <CommercialHistory currentNeedIds={(data?.items ?? []).map((item) => item.id)}/>
    <details className="commercial-legacy" onToggle={(event) => setLegacyOpen(event.currentTarget.open)}><summary>Saved research workspace and call history</summary>{legacyOpen && <><p>Existing source research and saved call outcomes remain available here.</p><Pursuits/></>}</details>
  </section>
}

function CommercialHistory({ currentNeedIds }: { currentNeedIds: string[] }) {
  const [history, setHistory] = useState<CommercialTriageHistory | null>(null)
  const [query, setQuery] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  async function load() {
    if (loading) return
    setLoading(true)
    try { setHistory(checkedCommercialHistory(await client.commercialTriageHistory())); setError('') }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Saved commercial history is unavailable.') }
    finally { setLoading(false) }
  }
  const current = new Set(currentNeedIds)
  const normalizedQuery = query.trim().toLowerCase()
  const rows = (history?.items ?? []).flatMap((item) => {
    const versions = (item as CommercialTriageHistoryItem & { versions?: CommercialHistoryVersion[] }).versions
    const entries = versions?.length ? versions : [legacyHistoryVersion(item)]
    const latest = Math.max(...entries.map((entry) => entry.version))
    return entries.map((version) => ({ item, version, latest })).filter(({ version, latest: latestVersion }) => !current.has(item.need_id) || version.version < latestVersion)
  }).filter(({ item, version }) => {
    const card = version.saved_card
    const haystack = [card?.name, card?.location, card?.industry, card?.activity, version.disposition, version.version, version.evaluated_at, version.evaluated_on, version.input_hash, item.need_id, item.project_id, item.pursuit_id, ...(item.notes ?? []).map((note) => `${note.note} ${note.outcome} ${note.next_action ?? ''}`)].join(' ').toLowerCase()
    return haystack.includes(normalizedQuery)
  })
  return <details className="commercial-history" onToggle={(event) => { if (event.currentTarget.open && !history && !loading) void load() }}>
    <summary>Saved evaluation history · closed and out-of-cohort work</summary>
    <p>Saved evaluations stay available after they leave the current 50. Every entry is an as-of snapshot; live status has not been rechecked.</p>
    <div className="commercial-history-tools"><label><span className="sr-only">Search saved evaluations</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search saved project, site, note or ID"/></label><button type="button" onClick={() => void load()} disabled={loading}>{loading ? 'Loading…' : history ? 'Refresh history' : 'Load saved history'}</button></div>
    {loading && <p role="status">Loading saved evaluations…</p>}{error && <p role="alert">{error}</p>}
    {history && !error && !rows.length && <p>{normalizedQuery ? 'No saved evaluations match this search.' : 'No saved versions outside the current cohort or earlier versions for current work.'}</p>}
    <div className="commercial-history-list">{rows.map(({ item, version }) => {
      const card = version.saved_card
      const key = `${item.pursuit_id}:${version.version}:${version.input_hash ?? version.evaluated_at ?? version.evaluated_on ?? 'date-unknown'}`
      const title = card?.name ?? `Saved work · ${item.need_id.slice(0, 8)}`
      const date = version.evaluated_at ? new Date(version.evaluated_at).toLocaleString() : version.evaluated_on ?? 'Saved date unknown'
      return <article className="commercial-history-card" key={key}>
        <button type="button" className="commercial-history-heading" aria-expanded={expanded === key} onClick={() => setExpanded(expanded === key ? null : key)}><span><strong>{title}</strong><small>{unknown(card?.location)} · {enumLabel(card?.industry)} · {enumLabel(card?.activity)}</small></span><span>Version {version.version} · {version.disposition} · {version.snapshot_status === 'saved_as_of' ? 'saved card' : 'metadata only'}<small>As of {date}</small></span></button>
        {expanded === key && <HistoricalDetail item={item} version={version}/>}
      </article>
    })}</div>
  </details>
}

type CommercialHistoryVersion = { version: number; disposition: string; evaluated_at?: string | null; evaluated_on?: string | null; input_hash?: string | null; snapshot_status: 'saved_as_of' | 'metadata_only'; live_status: 'not_rechecked'; saved_card?: CommercialTriageCard | null }
function legacyHistoryVersion(item: CommercialTriageHistoryItem): CommercialHistoryVersion { return { version: 1, disposition: item.disposition, evaluated_at: item.evaluated_at ?? null, evaluated_on: item.evaluated_on ?? null, input_hash: item.input_hash ?? null, snapshot_status: item.snapshot_status, live_status: item.live_status, saved_card: item.saved_card ?? null } }

function HistoricalDetail({ item, version }: { item: CommercialTriageHistoryItem; version: CommercialHistoryVersion }) {
  const card = version.saved_card
  const savedAt = version.evaluated_at ? new Date(version.evaluated_at).toLocaleString() : version.evaluated_on ?? 'date unknown'
  return <div className="commercial-history-detail">
    <p className="commercial-history-asof">Saved version {version.version}: {version.disposition} · as of {savedAt} · current status not rechecked{version.input_hash ? ` · input ${version.input_hash.slice(0, 12)}` : ''}</p>
    {card ? <>
      <section><h4>Saved project and power context</h4><p>{unknown(card.location)} · {enumLabel(card.industry)} · {enumLabel(card.activity)} · Stage {enumLabel(card.stage.stage)} ({unknown(card.stage.date)})</p><p>Required power: {power(card.required_mw)} · Start: {unknown(card.start_window)} · Duration: {unknown(card.duration)} · Supply: {unknown(card.supply)}</p><p>Buying organization: {unknown(card.organization)} · role: {enumLabel(card.organization_role)}</p><p><b>Why this saved state:</b> {card.reason}</p></section>
      <div className="commercial-evidence-grid"><section><h4>Saved supported facts</h4>{card.facts?.length ? <ul>{card.facts.map((fact, index) => <li key={`${fact.evidence_id}-${index}`}>{fact.text ?? 'Fact text unavailable.'} <Citation fact={fact}/></li>)}</ul> : <p>Unknown · this snapshot contains no supported facts.</p>}</section><section><h4>Saved hypothesis and unknowns</h4><p>{unknown(card.hypothesis)}</p>{card.unknowns?.length ? <ul>{card.unknowns.map((fact) => <li key={fact}>{fact}</li>)}</ul> : <p>No additional unknowns recorded in this snapshot.</p>}</section></div>
      <section><h4>Saved next step and blockers</h4><p>{card.next_action}</p>{card.blockers?.length ? <ul>{card.blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}</ul> : <p>No blockers recorded in this snapshot.</p>}</section>
      <section><h4>Saved buying-path evidence</h4>{card.contacts?.length ? card.contacts.map((contact, index) => <p key={`${contact.organization}-${contact.person}-${index}`}>{enumLabel(contact.role)} · {unknown(contact.organization)} · {unknown(contact.person)} · {unknown(contact.kind)}: {unknown(contact.value)}{contact.source_url && <> · <a href={contact.source_url} target="_blank" rel="noreferrer">Source ↗</a></>}</p>) : <p>Buying role and direct or intermediary path unknown in this snapshot.</p>}<p>Roles and contact routes do not establish personal purchasing authority.</p></section>
      <section><h4>Saved source citations</h4>{card.sources?.length ? <ul>{card.sources.map((fact, index) => <li key={`${fact.evidence_id}-${index}`}>{fact.text ?? 'Source text unavailable.'} <Citation fact={fact}/></li>)}</ul> : <p>No source citations saved in this snapshot.</p>}</section>
    </> : <p>This earlier receipt predates full-card snapshots. Only its saved disposition and operator notes are available; facts are not reconstructed.</p>}
    <AutonomousResearch key={item.need_id} needId={item.need_id} readOnly/>
    <section><h4>Operator notes</h4>{item.notes?.length ? item.notes.map((note) => <article className="commercial-note" key={note.id}><p><b>{note.outcome}</b> · {note.owner} · {new Date(note.created_at).toLocaleString()}</p><p>{note.note}</p>{note.next_action && <p><b>Next action:</b> {note.next_action}</p>}{note.follow_up && <p><b>Follow-up:</b> {note.follow_up}</p>}</article>) : <p>No operator notes were saved with this evaluation.</p>}</section>
  </div>
}

function CommercialCard({ item, index, expanded, draft, onDraftChange, onToggle, onSaved }: { item: CommercialTriageCard; index: number; expanded: boolean; draft: CommercialDraft; onDraftChange: (changes: Partial<CommercialDraft>) => void; onToggle: () => void; onSaved: () => void }) {
  return <article className="commercial-card" data-commercial-need-id={item.id}>
    <button className="commercial-card-heading" type="button" aria-expanded={expanded} onClick={onToggle}>
      <span className="pursuit-position">{index + 1}</span><span className="commercial-card-title"><strong>{item.name}</strong><span>{unknown(item.location)} · {enumLabel(item.industry)} · {enumLabel(item.activity)}</span><span>Stage {enumLabel(item.stage.stage)} · {unknown(item.organization)} · {enumLabel(item.organization_role)}</span></span><span className="commercial-card-state"><b>{item.disposition}</b><small>{item.tier} · evidence tier</small></span><span aria-hidden="true">{expanded ? '−' : '+'}</span>
    </button>
    <div className="commercial-card-facts"><span><b>Stage</b> {enumLabel(item.stage.stage)} · {unknown(item.stage.date)}</span><span><b>Power</b> {power(item.required_mw)}</span><span><b>Start</b> {unknown(item.start_window)}</span><span><b>Duration</b> {unknown(item.duration)}</span><span><b>Supply</b> {unknown(item.supply)}</span></div>
    <p className="commercial-why"><b>Why now:</b> {item.reason}</p><p className="commercial-why"><b>Next question:</b> {unknown(item.next_question)}</p>
    {(item.blockers?.length ?? 0) > 0 && <p className="commercial-blockers"><b>Blocking:</b> {item.blockers?.join(' · ')}</p>}
    {expanded && <CommercialDetail item={item} draft={draft} onDraftChange={onDraftChange} onSaved={onSaved}/>}
  </article>
}

function CommercialDetail({ item, draft, onDraftChange, onSaved }: { item: CommercialTriageCard; draft: CommercialDraft; onDraftChange: (changes: Partial<CommercialDraft>) => void; onSaved: () => void }) {
  return <div className="commercial-detail">
    <div className="commercial-evidence-grid"><section><h3>Supported facts</h3>{item.facts?.length ? <ul>{item.facts.map((fact, index) => <li key={`${fact.evidence_id}-${index}`}>{fact.text} <Citation fact={fact}/></li>)}</ul> : <p>Unknown · no supported facts recorded.</p>}</section>
      <section><h3>Commercial hypothesis</h3><p>{unknown(item.hypothesis)}</p><h3>Unknown</h3>{item.unknowns?.length ? <ul>{item.unknowns.map((fact) => <li key={fact}>{fact}</li>)}</ul> : <p>No additional unknowns recorded.</p>}</section></div>
    <section><h3>Why this state</h3><p>{item.reason}</p>{item.watch && <p><b>Watch trigger:</b> {unknown(item.watch.event)}{unknown(item.watch.date) !== 'Unknown' ? ` · ${unknown(item.watch.date)}` : ' · date unknown'}{typeof item.watch.source_url === 'string' && <> · <a href={item.watch.source_url} target="_blank" rel="noreferrer">Source ↗</a></>}</p>}{item.next_action && <p><b>Next action:</b> {item.next_action}</p>}{item.conflict_state && item.conflict_state !== 'clear' && <p className="integrity">Evidence conflict: {item.conflict_state}</p>}</section>
    {item.related_need_states?.length ? <section><h3>Related need states · identities retained separately</h3><p><b>Group review question:</b> {item.next_question}</p><ul className="commercial-related-needs">{item.related_need_states.map((need) => <li key={need.need_id}><b>{enumLabel(need.disposition)}</b> · {need.need_id}{need.held && ' · held'}{need.closed && ' · closed'}{need.conflict_state && need.conflict_state !== 'clear' ? ` · conflict: ${enumLabel(need.conflict_state)}` : ''}<p>{need.reason}</p></li>)}</ul></section> : null}
    <section><h3>Buying path evidence</h3>{item.contacts?.length ? item.contacts.map((contact, index) => <div className="commercial-role" key={`${contact.organization}-${contact.person}-${index}`}><b>{unknown(contact.role)}</b> · {unknown(contact.organization)} · {unknown(contact.person)}<p>{unknown(contact.kind)}: {unknown(contact.value)}</p>{contact.source_url && <a href={contact.source_url} target="_blank" rel="noreferrer">Relationship evidence ↗</a>}</div>) : <p>Buying role and direct or intermediary path unknown.</p>}<ProjectBuyingChains item={item}/></section>
    <section><h3>Project history</h3><p className="commercial-history-note">Source-backed project milestones; these dates do not establish a verified power start window.</p>{item.lifecycle_timeline?.length ? <ol className="commercial-timeline">{item.lifecycle_timeline.map((event, index) => <li key={`${event.event_type}-${event.date}-${index}`}><b>{event.state}</b> · {event.event_date_label ?? event.date ?? 'Date unknown'} · {event.event_type.replaceAll('_', ' ')}{event.value_kind && event.value_kind !== 'UNKNOWN' ? ` · ${event.value_kind.replaceAll('_', ' ')}` : ' · milestone type unknown'}{!event.current && <small> · superseded source state</small>}{event.published_at && <small> · published {event.published_at}</small>} · <a href={event.evidence_url} target="_blank" rel="noreferrer">Milestone source ↗</a></li>)}</ol> : <p>Project milestone history unknown · no lifecycle events retained for this project.</p>}</section>
    <section><h3>Source history</h3>{item.stage.source_url && <p>Stage source: <a href={item.stage.source_url} target="_blank" rel="noreferrer">{item.stage.stage} evidence ↗</a> · {unknown(item.stage.evidence_id)}</p>}{item.sources?.length ? <ul className="commercial-source-list">{item.sources.map((source, index) => <li key={`${source.evidence_id}-${index}`}>{source.text} <Citation fact={source}/>{source.date && <small> · {source.date}</small>}</li>)}</ul> : <p>Source citations unavailable.</p>}</section>
    <AutonomousResearch key={item.id} needId={item.id}/>
    <ResearchQuestion item={item} draft={draft} onDraftChange={onDraftChange}/><PursuitNote item={item} draft={draft} onDraftChange={onDraftChange} onSaved={onSaved}/>
  </div>
}

function ProjectBuyingChains({ item }: { item: CommercialTriageCard }) {
  const projectIds = [...new Set([item.project_id, ...(item.related_project_ids ?? [])])]
  const [selected, setSelected] = useState(item.project_id)
  return <div className="commercial-project-chains">
    {projectIds.length > 1 && <div className="commercial-project-chain-select" role="group" aria-label="Project relationship records">{projectIds.map((projectId, index) => <button key={projectId} type="button" aria-pressed={selected === projectId} onClick={() => setSelected(projectId)}>Project {index + 1} · {projectId === item.project_id ? 'primary record' : 'related record'}</button>)}</div>}
    <div className="commercial-project-chain"><p className="commercial-project-chain-label">{projectIds.length > 1 ? `Project relationship ${projectIds.indexOf(selected) + 1}` : 'Project relationship'} · {selected === item.project_id ? 'primary project record' : 'related project record'} · identities remain separate</p><BuyingChain projectId={selected}/></div>
  </div>
}

function Citation({ fact }: { fact: NonNullable<CommercialTriageCard['facts']>[number] }) {
  return <>{fact.url && <> <a href={fact.url} target="_blank" rel="noreferrer">Source ↗</a></>}{fact.evidence_id && <small> [{fact.evidence_id}{fact.hash ? ` · ${fact.hash.slice(0, 12)}` : ''}]</small>}</>
}

function ResearchQuestion({ item, draft, onDraftChange }: { item: CommercialTriageCard; draft: CommercialDraft; onDraftChange: (changes: Partial<CommercialDraft>) => void }) {
  const [busy, setBusy] = useState(false)
  const progress = draft.research?.question === draft.question ? draft.research : undefined
  useEffect(() => {
    if (!progress || progress.brief.status !== 'pending' || !progress.brief.job_id) return
    const controller = new AbortController()
    let timer: number | undefined
    let cancelled = false
    const schedule = (delay: number) => { timer = window.setTimeout(() => void poll(), delay) }
    const poll = async () => {
      try {
        const status = await client.commercialResearchStatus(item.id, progress.question, controller.signal)
        if (cancelled) return
        if (status.status === 'pending') {
          if (status.job_id && status.job_id !== progress.brief.job_id) {
            onDraftChange({ research: { ...progress, brief: researchBrief(status), message: 'This exact-question job was replaced before completion.', failed: true } })
            return
          }
          onDraftChange({ research: { ...progress, message: 'Research is queued or running; checking for the exact-question result.', failed: false } })
          schedule(1600)
          return
        }
        const brief = researchBrief(status)
        onDraftChange({ research: { ...progress, brief, message: researchStatusMessage(status), failed: status.status === 'failed' || status.status === 'superseded' || status.status === 'not_requested' } })
      } catch (cause) {
        if (!cancelled && !controller.signal.aborted) {
          onDraftChange({ research: { ...progress, message: `Research status is temporarily unavailable; retrying. ${cause instanceof Error ? cause.message : ''}`.trim(), failed: false } })
          schedule(3000)
        }
      }
    }
    schedule(1200)
    return () => { cancelled = true; controller.abort(); if (timer !== undefined) window.clearTimeout(timer) }
  }, [item.id, progress?.question, progress?.brief.job_id, progress?.brief.status])
  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    try {
      const brief = await client.researchCommercialNeed(item.id, { question: draft.question })
      const message = brief.job_id && brief.status === 'pending' ? 'Research is queued; checking for the exact-question result.' : brief.job_id === null && brief.status === 'ready' ? 'Existing brief unchanged; showing the saved result.' : brief.error ? `Research unavailable: ${brief.error}` : brief.stale ? 'Existing brief is stale; no current result was produced.' : brief.status === 'ready' ? 'Research result' : `Research ${brief.status}`
      onDraftChange({ research: { question: draft.question, brief, message, failed: Boolean(brief.error) || brief.status === 'failed' || brief.stale } })
    } catch (cause) { onDraftChange({ research: { question: draft.question, brief: { status: 'failed', stale: false, generated_at: null, result: null, citations: [], error: cause instanceof Error ? cause.message : 'Targeted research unavailable.', input_tokens: 0, output_tokens: 0, job_id: null }, message: cause instanceof Error ? cause.message : 'Targeted research unavailable.', failed: true } }) }
    finally { setBusy(false) }
  }
  const pending = progress?.brief.status === 'pending' && Boolean(progress.brief.job_id)
  return <section className="commercial-action"><h3>Targeted research</h3><form onSubmit={(event) => void submit(event)}><label>Exact missing-fact question<textarea required minLength={12} maxLength={300} value={draft.question} onChange={(event) => onDraftChange({ question: event.target.value, research: undefined })} disabled={busy || pending}/></label><button className="primary" disabled={busy || pending || draft.question.trim().length < 12}>{busy ? 'Queueing…' : pending ? 'Research in progress…' : 'Research this question'}</button></form>{progress?.message && <p role={progress.failed ? 'alert' : 'status'}>{progress.message}</p>}{progress?.brief.status === 'ready' && progress.brief.result && <ResearchResult brief={progress.brief}/>}</section>
}

function researchBrief(status: CommercialResearchStatus): BriefRequest {
  const result = checkedResearchContent(status.result)
  const citations = (status.citations ?? []).filter((citation): citation is NonNullable<BriefRequest['citations']>[number] => isRecord(citation) && typeof citation.evidence_id === 'string' && typeof citation.url === 'string' && typeof citation.title === 'string')
  return { status: status.status, stale: status.status === 'superseded', generated_at: status.generated_at ?? null, result, citations, error: status.error ?? null, input_tokens: 0, output_tokens: 0, job_id: status.job_id ?? null }
}
function checkedResearchContent(value: unknown): BriefRequest['result'] {
  if (value === null || value === undefined) return null
  if (!isRecord(value) || !Array.isArray(value.event_summary) || !value.event_summary.every((entry) => isRecord(entry) && typeof entry.text === 'string' && typeof entry.evidence_id === 'string')
    || !isRecord(value.commercial_hypothesis) || typeof value.commercial_hypothesis.text !== 'string' || typeof value.commercial_hypothesis.evidence_id !== 'string'
    || !Array.isArray(value.unknowns) || !value.unknowns.every((entry) => typeof entry === 'string') || typeof value.next_step !== 'string') return null
  return value as unknown as NonNullable<BriefRequest['result']>
}
function researchStatusMessage(status: CommercialResearchStatus) {
  if (status.status === 'ready') return 'Research result'
  if (status.status === 'failed') return `Research failed: ${status.error ?? 'No result was produced.'}`
  if (status.status === 'superseded') return 'This research request was superseded by a different question or evidence version; no result is attributed to this request.'
  return 'No targeted research result is available for this question.'
}

function ResearchResult({ brief }: { brief: BriefRequest }) {
  const content = brief.result
  const statements = [...(content?.event_summary ?? []), ...(content?.commercial_hypothesis ? [content.commercial_hypothesis] : [])]
  const unknowns = content?.unknowns ?? []
  return <div className="commercial-research-result" aria-label="Targeted research result">
    {statements.map((statement, index) => {
      const citation = brief.citations?.find((entry) => entry.evidence_id === statement.evidence_id)
      return <p key={`${statement.evidence_id}-${index}`}>{statement.text}{citation && <> <a href={citation.url} target="_blank" rel="noreferrer">{citation.title} ↗</a></>}</p>
    })}
    {Boolean(unknowns.length) && <><b>Still unknown</b><ul>{unknowns.map((value) => <li key={value}>{value}</li>)}</ul></>}
    {content?.next_step && <p><b>Next step:</b> {content.next_step}</p>}
    {!statements.length && !unknowns.length && !content?.next_step && <p>No sourced findings returned.</p>}
  </div>
}

function PursuitNote({ item, draft, onDraftChange, onSaved }: { item: CommercialTriageCard; draft: CommercialDraft; onDraftChange: (changes: Partial<CommercialDraft>) => void; onSaved: () => void }) {
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  async function save(event: FormEvent) {
    event.preventDefault()
    if (!item.pursuit_id) { setMessage('Save a pursuit snapshot before adding notes.'); return }
    setSaving(true)
    const clientId = draft.clientId ?? crypto.randomUUID()
    if (!draft.clientId) onDraftChange({ clientId })
    const body: CallNoteBody = { client_id: clientId, note: draft.note, outcome: draft.outcome, next_action: draft.nextAction, follow_up: null }
    try { await client.savePursuitNote(item.pursuit_id, body); onDraftChange({ note: '', nextAction: '', outcome: 'Not reached', clientId: undefined }); setMessage('Note saved to this pursuit. Evidence tier unchanged.'); onSaved() }
    catch (cause) { setMessage(cause instanceof Error ? cause.message : 'Note could not be saved.') }
    finally { setSaving(false) }
  }
  return <section className="commercial-action"><h3>Saved pursuit notes</h3>{item.notes?.length ? item.notes.map((entry) => <article className="commercial-note" key={entry.id}><p><b>{entry.outcome}</b> · {entry.owner} · {new Date(entry.created_at).toLocaleString()}</p><p>{entry.note}</p>{entry.next_action && <p><b>Next action:</b> {entry.next_action}</p>}{entry.follow_up && <p><b>Follow-up:</b> {entry.follow_up}</p>}</article>) : <p>No saved notes yet.</p>}<h3>Add operator note</h3><form onSubmit={(event) => void save(event)}><label>Note<textarea required maxLength={5000} value={draft.note} onChange={(event) => onDraftChange({ note: event.target.value, clientId: draft.clientId ? crypto.randomUUID() : undefined })} disabled={saving}/></label><label>Reported outcome<select value={draft.outcome} onChange={(event) => onDraftChange({ outcome: event.target.value as CallNoteBody['outcome'], clientId: draft.clientId ? crypto.randomUUID() : undefined })} disabled={saving}>{['Not reached', 'Contacted', 'Needs follow-up', 'No requirement', 'Closed', 'Reached buying organization', 'Qualified'].map((value) => <option key={value}>{value}</option>)}</select></label><label>Next action<input maxLength={1000} value={draft.nextAction} onChange={(event) => onDraftChange({ nextAction: event.target.value, clientId: draft.clientId ? crypto.randomUUID() : undefined })} disabled={saving}/></label><button className="primary" disabled={saving || !item.pursuit_id}>{saving ? 'Saving…' : 'Save note'}</button></form>{message && <p role="status">{message}</p>}{!item.pursuit_id && <p>Notes become available after an existing pursuit is linked.</p>}</section>
}
