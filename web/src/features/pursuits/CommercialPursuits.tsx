import { type ReactNode, type FormEvent, useEffect, useMemo, useRef, useState } from 'react'
import { client, type BriefRequest, type CallNoteBody, type CommercialResearchStatus, type CommercialTriage, type CommercialTriageCard, type CommercialTriageHistory, type CommercialTriageHistoryItem } from '../../api/client'
import { BuyingChain } from '../buyingChain/BuyingChain'
import { ResearchChanges } from './ResearchChanges'
import { AutonomousResearch } from './AutonomousResearch'
import { IntelligenceResearch } from './IntelligenceResearch'
import { Pursuits } from './Pursuits'
import '../../styles/pursuits.css'
import { useCommercialDraft, type CommercialDraft } from './commercialDrafts'

export type Disposition = 'ACTION NOW' | 'RESEARCH' | 'WATCH' | 'REJECT'
export type CommercialNavigation = { offset: number; query: string; disposition: Disposition; needId: string | null }
export const defaultCommercialNavigation: CommercialNavigation = { offset: 0, query: '', disposition: 'ACTION NOW', needId: null }
const dispositions: Disposition[] = ['ACTION NOW', 'RESEARCH', 'WATCH', 'REJECT']
const unknown = (value: unknown) => typeof value === 'string' || typeof value === 'number' ? String(value) || 'Unknown' : 'Unknown'
function enumLabel(value: unknown) {
  if (typeof value !== 'string' || !value.trim() || /^unknown$/i.test(value.trim())) return 'Unknown'
  const words = value.replace(/[_-]+/g, ' ').trim()
  return words.charAt(0).toUpperCase() + words.slice(1)
}
const power = (value: string | null) => !value || value.toLowerCase() === 'unknown' ? 'Unknown' : /\bmw\b/i.test(value) ? value : `${value} MW`
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
      for (const key of ['lifecycle_timeline', 'contacts', 'facts', 'unknowns', 'blockers', 'sources', 'notes', 'operator_fact_refs']) {
        if (item.saved_card[key] !== undefined && !Array.isArray(item.saved_card[key])) throw new Error('A saved card snapshot is incomplete. Retry the history view.')
      }
      const factRefs = item.saved_card.operator_fact_refs
      if (Array.isArray(factRefs) && factRefs.some((reference) => !isRecord(reference)
        || typeof reference.need_id !== 'string' || typeof reference.fact_version_id !== 'string'
        || typeof reference.content_hash !== 'string' || typeof reference.authority !== 'string')) throw new Error('Saved operator fact references are incomplete. Retry the history view.')
    }
    const versions = (item as Record<string, unknown>).versions
    if (versions !== undefined && (!Array.isArray(versions) || versions.some((version) => !isRecord(version)
      || typeof version.version !== 'number' || typeof version.disposition !== 'string'
      || !['saved_as_of', 'metadata_only'].includes(String(version.snapshot_status)) || version.live_status !== 'not_rechecked'
      || (version.operator_fact_provenance !== undefined && !['recorded', 'legacy_unknown'].includes(String(version.operator_fact_provenance)))
      || (version.saved_card !== null && version.saved_card !== undefined && !isRecord(version.saved_card))))) throw new Error('Saved commercial history versions are incomplete. Retry the history view.')
  }
  return value as unknown as CommercialTriageHistory
}

function QueueContext({ compact, children }: { compact: boolean; children: ReactNode }) {
  return compact ? <details className="env-queue-context" data-context-key="queue-context"><summary>Queue details and research updates</summary>{children}</details> : <>{children}</>
}

export function CommercialPursuits({ navigation, onNavigate, onInvestigate }: {
  navigation?: CommercialNavigation
  onNavigate?: (next: CommercialNavigation) => void
  onInvestigate?: (needId: string) => void
} = {}) {
  const [localNavigation, setLocalNavigation] = useState(() => {
    const pursuitNeed = new URLSearchParams(location.search).get('pursuitNeed')
    return pursuitNeed ? { ...defaultCommercialNavigation, needId: pursuitNeed } : defaultCommercialNavigation
  })
  const current = navigation ?? localNavigation
  const navigate = (patch: Partial<CommercialNavigation>) => {
    const next = { ...current, ...patch }
    if (onNavigate) onNavigate(next)
    else setLocalNavigation(next)
  }
  const { offset: pageOffset, query, disposition: filter, needId: expanded } = current
  const setPageOffset = (offset: number) => navigate({ offset, needId: null })
  const setQuery = (query: string) => navigate({ query })
  const setFilter = (disposition: Disposition) => navigate({ disposition })
  const setExpanded = (needId: string | null) => navigate({ needId })
  const [loadedData, setData] = useState<CommercialTriage | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [evaluating, setEvaluating] = useState(false)
  const [legacyOpen, setLegacyOpen] = useState(false)

  const [loadedOffset, setLoadedOffset] = useState<number | null>(null)
  const offsetRef = useRef(pageOffset)
  offsetRef.current = pageOffset
  const sequence = useRef(0)
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false; sequence.current += 1 } }, [])
  useEffect(() => {
    const controller = new AbortController()
    const request = ++sequence.current
    setLoading(true)
    setData(null)
    void client.commercialTriage(50, controller.signal, pageOffset).then((result) => {
      if (!controller.signal.aborted && request === sequence.current) { setData(checkedCommercialTriage(result)); setLoadedOffset(pageOffset); setError('') }
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted && request === sequence.current) { setLoadedOffset(pageOffset); setError(cause instanceof Error ? cause.message : 'Commercial pursuits are unavailable.') }
    }).finally(() => { if (!controller.signal.aborted && request === sequence.current) setLoading(false) })
    return () => controller.abort()
  }, [pageOffset])
  const data = loadedOffset === pageOffset ? loadedData : null
  const currentData = data
  const visible = useMemo(() => (currentData?.items ?? []).filter((item) => item.disposition === filter && `${item.name} ${item.location ?? ''} ${item.industry} ${item.activity} ${item.stage.stage} ${item.organization ?? ''}`.toLowerCase().includes(query.trim().toLowerCase())), [currentData, filter, query])
  const selectedOutside = navigation && currentData?.items.find((item) => item.id === expanded && !visible.includes(item))
  const ready = !loading && loadedOffset === pageOffset
  async function evaluate() {
    if (evaluating) return
    const request = ++sequence.current
    setEvaluating(true)
    try {
      const result = checkedCommercialTriage(await client.evaluateCommercialTriage(50, pageOffset))
      if (alive.current && request === sequence.current) { setData(result); setLoadedOffset(pageOffset); setError('') }
    } catch (cause) { if (alive.current && request === sequence.current) setError(cause instanceof Error ? cause.message : 'Evaluation could not be saved.') }
    finally { if (alive.current) setEvaluating(false) }
  }
  async function refreshTriage() {
    if (!alive.current || offsetRef.current !== pageOffset) return
    const request = ++sequence.current
    setLoading(true)
    try {
      const result = checkedCommercialTriage(await client.commercialTriage(50, undefined, pageOffset))
      if (alive.current && request === sequence.current) { setData(result); setLoadedOffset(pageOffset); setError('') }
    } catch (cause) { if (alive.current && request === sequence.current) { setLoadedOffset(pageOffset); setError(cause instanceof Error ? cause.message : 'Commercial metrics could not refresh.') } }
    finally { if (alive.current && request === sequence.current) setLoading(false) }
  }

  return <section className="pursuits-view commercial-view" aria-label="Commercial pursuits" data-context-loading={!ready}>
    <section className="hero commercial-hero"><div><p className="eyebrow">Retained Signals · Commercial work queue</p><h1 tabIndex={-1}>What should we work today?</h1><p>{navigation ? 'Choose a pursuit. Follow the next question.' : 'Evidence-backed pursuits with clear next steps. Power, supply, timing and buying roles stay unknown until sources support them.'}</p></div>{!navigation && <button type="button" className="back-button" onClick={() => void evaluate()} disabled={evaluating || loading}>{evaluating ? 'Evaluating…' : 'Evaluate Signals'}</button>}</section>
    {!data && error ? <section className="commercial-unavailable" role="alert"><h2>Commercial pursuits are unavailable</h2><p>{error}</p><button type="button" onClick={() => void refreshTriage()}>Retry commercial pursuits</button></section> : <>
    <QueueContext compact={!!navigation}>
    {navigation && <button type="button" onClick={() => void evaluate()} disabled={evaluating || loading}>{evaluating ? 'Evaluating…' : 'Evaluate Signals'}</button>}
    <section className="commercial-summary" aria-label="Current cohort summary">
      <div><span>All eligible groups</span><strong>{data?.grouped_total ?? '—'}</strong></div>
      {dispositions.map((state) => <div key={state}><span>{state} · this page</span><strong>{data?.cohort_counts[state.toLowerCase().replaceAll(' ', '_') as keyof CommercialTriage['cohort_counts']] ?? '—'}</strong></div>)}
      <div className="commercial-daily">Today · {data?.daily.evaluated ?? '—'} evaluated · {data?.daily.surfaced ?? '—'} surfaced · {data?.daily.contacted ?? '—'} contacted · {data?.daily.reached_buyer ?? '—'} buyer reached · {data?.daily.qualified ?? '—'} qualified · {data?.daily.promoted_prospects ?? '—'} Prospects · {data?.daily.promoted_leads ?? '—'} Leads · {data ? unknown(data.daily.supported_mw) : '—'} supported MW <details><summary>{data?.daily.unavailable_metrics?.length ?? '—'} metric limits</summary><span>{[...(data?.daily.metric_scope ?? []), ...(data?.daily.unavailable_metrics ?? [])].join('; ') || 'No additional metric limitations reported.'}</span></details></div>
    </section>
    <ResearchChanges overview={data?.research_overview}/>
    </QueueContext>
    <div className="list-toolbar commercial-toolbar"><div><h2>{filter} · {visible.length} pursuits on this page</h2><p>{navigation ? `Matching pursuits on this loaded page · ${data?.grouped_total ?? 0} eligible groups overall` : <>Page {data ? Math.floor((data.offset ?? pageOffset) / (data.limit ?? 50)) + 1 : 1} · {data?.total ?? 0} saved cards · {data?.grouped_total ?? 0} eligible groups overall · disposition counts below are page-scoped · {data?.evaluated_at ? `queue refreshed ${new Date(data.evaluated_at).toLocaleString()}` : 'evaluation has not been saved'}</>}</p></div>{!navigation && <label className="search"><span className="sr-only">Search commercial pursuits on this page</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search this page: project, company, site"/></label>}</div>
    <div className="commercial-filters" role="group" aria-label="Filter pursuit state">{dispositions.map((state) => <button type="button" key={state} data-context-key={`disposition:${state}`} className={filter === state ? 'commercial-filter-active' : ''} aria-pressed={filter === state} onClick={() => setFilter(state)}>{state}<span>{data?.cohort_counts[state.toLowerCase().replaceAll(' ', '_') as keyof CommercialTriage['cohort_counts']] ?? '—'}</span></button>)}</div>
    {error && <p className="error-banner" role="alert">{error} Saved findings remain available.</p>}{loading && <p role="status">Loading retained commercial pursuits…</p>}
    {!loading && data && !visible.length && <div className="empty"><h3>{query ? 'No matching pursuits' : `No ${filter.toLowerCase()} pursuits`}</h3><p>{query ? 'Try another project, company or site.' : 'The current retained cohort has no candidates in this state.'}</p></div>}
    {selectedOutside && <aside className="commercial-outside"><p role="status">Selected pursuit outside current page filters. It is not included in the matching list count.</p><StoredCommercialCard item={selectedOutside} index={pageOffset} expanded onToggle={() => setExpanded(null)} onSaved={() => void refreshTriage()} onInvestigate={onInvestigate}/></aside>}
    {expanded && ready && currentData && !currentData.items.some((item) => item.id === expanded) && <p role="status">The selected pursuit is no longer on this page. Its identity is retained; check saved evaluation history or another page.</p>}
    <div className="commercial-list">{visible.map((item, index) => <StoredCommercialCard key={item.id} item={item} index={index + pageOffset} expanded={expanded === item.id} onToggle={() => setExpanded(expanded === item.id ? null : item.id)} onSaved={() => void refreshTriage()} onInvestigate={onInvestigate}/>)}</div>
    <nav className="opportunity-pagination commercial-pagination" aria-label="Commercial pursuit pages">
      <button type="button" disabled={loading || pageOffset <= 0} onClick={() => { setPageOffset(Math.max(0, pageOffset - (data?.limit ?? 50))) }}>Previous page</button>
      <span>{data?.total ?? 0} cards on this page · {data?.grouped_total ?? 0} eligible groups overall</span>
      <button type="button" disabled={!ready || !currentData || currentData.next_offset == null} onClick={() => { setPageOffset(data?.next_offset ?? pageOffset) }}>Next page</button>
    </nav>
    </>}
    <CommercialHistory currentNeedIds={(data?.items ?? []).map((item) => item.id)}/>
    <details className="commercial-legacy" onToggle={(event) => setLegacyOpen(event.currentTarget.open)}><summary>Saved research workspace and call history</summary>{legacyOpen && <><p>Existing source research and saved call outcomes remain available here.</p><Pursuits/></>}</details>
  </section>
}

function CommercialHistory({ currentNeedIds }: { currentNeedIds: string[] }) {
  const [history, setHistory] = useState<CommercialTriageHistory | null>(null)
  const [historyOffset, setHistoryOffset] = useState(0)
  const [query, setQuery] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [historyDetails, setHistoryDetails] = useState<Record<string, CommercialTriageHistoryItem>>({})
  const [detailLoading, setDetailLoading] = useState<Record<string, boolean>>({})
  const [detailErrors, setDetailErrors] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  async function load(offset = historyOffset) {
    if (loading) return
    setLoading(true)
    try {
      const page = checkedCommercialHistory(await client.commercialTriageHistory(undefined, offset))
      setHistory(page)
      setHistoryOffset(page.offset ?? offset)
      setExpanded(null)
      setError('')
    }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Saved commercial history is unavailable.') }
    finally { setLoading(false) }
  }
  async function toggleHistoryDetail(key: string, pursuitId: string) {
    if (expanded === key) { setExpanded(null); return }
    setExpanded(key)
    if (historyDetails[pursuitId] || detailLoading[pursuitId]) return
    setDetailLoading((current) => ({ ...current, [pursuitId]: true }))
    setDetailErrors((current) => ({ ...current, [pursuitId]: '' }))
    try {
      const detail = checkedCommercialHistory({ items: [await client.commercialTriageHistoryDetail(pursuitId)] }).items[0]
      setHistoryDetails((current) => ({ ...current, [pursuitId]: detail }))
    } catch (cause) {
      setDetailErrors((current) => ({ ...current, [pursuitId]: cause instanceof Error ? cause.message : 'Saved detail is unavailable.' }))
    } finally {
      setDetailLoading((current) => ({ ...current, [pursuitId]: false }))
    }
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
    <summary>Saved evaluation history · snapshots and earlier versions</summary>
    <p>Saved evaluations stay available after they leave the current 50. Every entry is an as-of snapshot; live status has not been rechecked.</p>
    <div className="commercial-history-tools"><label><span className="sr-only">Search saved evaluations</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search saved project, site, note or ID"/></label><button type="button" onClick={() => void load()} disabled={loading}>{loading ? 'Loading…' : history ? 'Refresh history' : 'Load saved history'}</button></div>
    {loading && <p role="status">Loading saved evaluations…</p>}{error && <p role="alert">{error}</p>}
    {history && !error && !rows.length && <p>{normalizedQuery ? 'No saved evaluations match this search.' : 'No saved versions outside the current cohort or earlier versions for current work.'}</p>}
    <div className="commercial-history-list">{rows.map(({ item, version }) => {
      const card = version.saved_card
      const key = `${item.pursuit_id}:${version.version}:${version.input_hash ?? version.evaluated_at ?? version.evaluated_on ?? 'date-unknown'}`
      const title = card?.name ?? `Saved work · ${item.need_id.slice(0, 8)}`
      const date = version.evaluated_at ? new Date(version.evaluated_at).toLocaleString() : version.evaluated_on ?? 'Saved date unknown'
      const detailedItem = historyDetails[item.pursuit_id]
      const detailedVersion = detailedItem?.versions?.find((candidate) => candidate.version === version.version && candidate.input_hash === version.input_hash) ?? version
      return <article className="commercial-history-card" key={key}>
        <button type="button" className="commercial-history-heading" aria-expanded={expanded === key} onClick={() => void toggleHistoryDetail(key, item.pursuit_id)}><span><strong>{title}</strong><small>{unknown(card?.location)} · {enumLabel(card?.industry)} · {enumLabel(card?.activity)}</small></span><span>Version {version.version} · {version.disposition} · {version.snapshot_status === 'saved_as_of' ? 'saved card' : 'metadata only'}<small>As of {date}</small></span></button>
        {expanded === key && detailLoading[item.pursuit_id] && <p role="status">Loading saved as-of detail…</p>}
        {expanded === key && detailErrors[item.pursuit_id] && <p role="alert">{detailErrors[item.pursuit_id]}</p>}
        {expanded === key && detailedItem && <HistoricalDetail item={detailedItem} version={detailedVersion}/>}
      </article>
    })}</div>
    {history && !error && <nav className="opportunity-pagination commercial-pagination" aria-label="Saved evaluation history pages">
      <button type="button" disabled={loading || historyOffset <= 0} onClick={() => void load(Math.max(0, historyOffset - (history.limit ?? 50)))}>Previous page</button>
      <span>Showing {history.items.length ? historyOffset + 1 : 0}–{historyOffset + history.items.length} of {history.total ?? 0} saved workspaces · search applies to this page</span>
      <button type="button" disabled={loading || history.next_offset == null} onClick={() => void load(history.next_offset ?? historyOffset)}>Next page</button>
    </nav>}
  </details>
}

type CommercialHistoryVersion = { version: number; disposition: string; evaluated_at?: string | null; evaluated_on?: string | null; input_hash?: string | null; operator_fact_provenance?: 'recorded' | 'legacy_unknown'; snapshot_status: 'saved_as_of' | 'metadata_only'; live_status: 'not_rechecked'; saved_card?: CommercialTriageCard | null }
function legacyHistoryVersion(item: CommercialTriageHistoryItem): CommercialHistoryVersion { return { version: 1, disposition: item.disposition, evaluated_at: item.evaluated_at ?? null, evaluated_on: item.evaluated_on ?? null, input_hash: item.input_hash ?? null, operator_fact_provenance: 'legacy_unknown', snapshot_status: item.snapshot_status, live_status: item.live_status, saved_card: item.saved_card ?? null } }

function HistoricalDetail({ item, version }: { item: CommercialTriageHistoryItem; version: CommercialHistoryVersion }) {
  const [inspectLaterResearch, setInspectLaterResearch] = useState(false)
  const card = version.saved_card
  const savedAt = version.evaluated_at ? new Date(version.evaluated_at).toLocaleString() : version.evaluated_on ?? 'date unknown'
  return <div className="commercial-history-detail">
    <p className="commercial-history-asof">Saved version {version.version}: {version.disposition} · as of {savedAt} · current status not rechecked{version.input_hash ? ` · input ${version.input_hash.slice(0, 12)}` : ''}</p>
    <section><h4>Saved operator fact basis</h4>{version.operator_fact_provenance !== 'recorded'
      ? <p>Unknown · this legacy evaluation did not record its operator fact basis. Current facts were not reconstructed.</p>
      : card?.operator_fact_refs?.length
        ? <><p>User-confirmed fact references saved with this evaluation; these links identify the as-of basis and do not refresh current facts.</p><ul>{card.operator_fact_refs.map((reference) => <li key={`${reference.need_id}-${reference.fact_version_id}-${reference.content_hash}`}>Need {reference.need_id} · fact {reference.fact_version_id} · content reference {reference.content_hash.slice(0, 12)} · {reference.authority}</li>)}</ul></>
        : <p>Recorded empty · no accepted operator facts were included in this evaluation. Current facts were not reconstructed.</p>}</section>
    {card ? <>
      <section><h4>Saved project and power context</h4><p>{unknown(card.location)} · {enumLabel(card.industry)} · {enumLabel(card.activity)} · Stage {enumLabel(card.stage.stage)} ({unknown(card.stage.date)})</p><p>Required power: {power(card.required_mw)} · Start: {unknown(card.start_window)} · Duration: {unknown(card.duration)} · Supply: {unknown(card.supply)}</p><p>Buying organization: {unknown(card.organization)} · role: {enumLabel(card.organization_role)}</p><p><b>Why this saved state:</b> {card.reason}</p></section>
      <div className="commercial-evidence-grid"><section><h4>Saved supported facts</h4>{Array.isArray(card.facts) ? card.facts.length
        ? <ul>{card.facts.map((fact, index) => <li key={`${fact.evidence_id}-${index}`}>{fact.text ?? 'Fact text unavailable.'} <Citation fact={fact}/></li>)}</ul>
        : <p>Recorded empty · this saved evaluation contains no supported source facts.</p>
        : <p>Unknown · this legacy card did not record its supported source facts.</p>}</section><section><h4>Saved hypothesis and unknowns</h4><p>{unknown(card.hypothesis)}</p>{card.unknowns?.length ? <ul>{card.unknowns.map((fact) => <li key={fact}>{fact}</li>)}</ul> : <p>No additional unknowns recorded in this snapshot.</p>}</section></div>
      <section><h4>Saved next step and blockers</h4><p>{card.next_action}</p>{card.blockers?.length ? <ul>{card.blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}</ul> : <p>No blockers recorded in this snapshot.</p>}</section>
      <section><h4>Saved buying-path evidence</h4>{card.contacts?.length ? card.contacts.map((contact, index) => <p key={`${contact.organization}-${contact.person}-${index}`}>{enumLabel(contact.role)} · {unknown(contact.organization)} · {unknown(contact.person)} · {unknown(contact.kind)}: {unknown(contact.value)}{contact.source_url && <> · <a href={contact.source_url} target="_blank" rel="noreferrer">Source ↗</a></>}</p>) : <p>Buying role and direct or intermediary path unknown in this snapshot.</p>}<p>Roles and contact routes do not establish personal purchasing authority.</p></section>
      <section><h4>Saved source citations</h4>{card.sources?.length ? <ul>{card.sources.map((fact, index) => <li key={`${fact.evidence_id}-${index}`}>{fact.text ?? 'Source text unavailable.'} <Citation fact={fact}/></li>)}</ul> : <p>No source citations saved in this snapshot.</p>}</section>
    </> : <p>This earlier receipt predates full-card snapshots. Only its saved disposition and operator notes are available; facts are not reconstructed.</p>}
    <section><h4>Operator notes</h4>{item.notes?.length ? item.notes.map((note) => <article className="commercial-note" key={note.id}><p><b>{note.outcome}</b> · {note.owner} · {new Date(note.created_at).toLocaleString()}</p><p>{note.note}</p>{note.next_action && <p><b>Next action:</b> {note.next_action}</p>}{note.follow_up && <p><b>Follow-up:</b> {note.follow_up}</p>}</article>) : <p>No operator notes were saved with this evaluation.</p>}</section>
    <section aria-label="Later research attempts">
      <h4>Later research attempts</h4>
      <button type="button" aria-expanded={inspectLaterResearch} onClick={() => setInspectLaterResearch(true)}>Inspect later research attempts</button>
      {inspectLaterResearch && <AutonomousResearch
        key={`saved-ledger-${item.need_id}`}
        needId={item.need_id}
        readOnly
        readOnlyLabel="Research attempt history loaded now; it may include attempts after this saved evaluation. Saved disposition and tier were not rechecked."
      />}
    </section>
  </div>
}

function StoredCommercialCard({ item, index, expanded, onToggle, onSaved, onInvestigate }: {
  item: CommercialTriageCard; index: number; expanded: boolean; onToggle: () => void; onSaved: () => void; onInvestigate?: (id: string) => void
}) {
  const [draft, update] = useCommercialDraft(item)
  return <>
    <CommercialCard item={item} index={index} expanded={expanded} draft={draft} onDraftChange={update} onToggle={onToggle} onSaved={onSaved} onInvestigate={onInvestigate}/>
  </>
}

function CommercialCard({ item, index, expanded, draft, onDraftChange, onToggle, onSaved, onInvestigate }: { onInvestigate?: (id: string) => void; item: CommercialTriageCard; index: number; expanded: boolean; draft: CommercialDraft; onDraftChange: (changes: Partial<CommercialDraft>) => void; onToggle: () => void; onSaved: () => void }) {
  return <article className="commercial-card" data-commercial-need-id={item.id} data-context-owner={item.id}>
    <button className="commercial-card-heading" data-context-key={`pursuit:${item.id}`} type="button" aria-expanded={expanded} onClick={onToggle}>
      <span className="pursuit-position">{index + 1}</span><span className="commercial-card-title"><strong>{item.name}</strong><span>{unknown(item.location)} · {enumLabel(item.industry)} · {enumLabel(item.activity)}</span>{(!onInvestigate || expanded) && <span>Stage {enumLabel(item.stage.stage)} · {unknown(item.organization)} · {enumLabel(item.organization_role)}</span>}</span><span className="commercial-card-state"><b>{item.disposition}</b><small>{item.tier} · evidence tier</small></span><span aria-hidden="true">{expanded ? '−' : '+'}</span>
    </button>
    {(!onInvestigate || expanded) && <><div className="commercial-card-facts"><span><b>Stage</b> {enumLabel(item.stage.stage)} · {unknown(item.stage.date)}</span><span><b>Power</b> {power(item.required_mw)}</span><span><b>Start</b> {unknown(item.start_window)}</span><span><b>Duration</b> {unknown(item.duration)}</span><span><b>Supply</b> {unknown(item.supply)}</span></div>
    <p className="commercial-why"><b>Why now:</b> {item.reason}</p></>}<p className="commercial-why"><b>Next question:</b> {unknown(item.next_question)}</p>
    {(item.blockers?.length ?? 0) > 0 && <p className="commercial-blockers"><b>Blocking:</b> {item.blockers?.join(' · ')}</p>}
    {expanded && onInvestigate && <button className="env-go" data-context-key={`investigate:${item.id}`} onClick={() => onInvestigate(item.id)}>Investigate this need</button>}
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
    <IntelligenceResearch key={`intelligence-${item.id}`} needId={item.id}/>
  </div>
}

function ProjectBuyingChains({ item }: { item: CommercialTriageCard }) {
  const projectIds = [...new Set([item.project_id, ...(item.related_project_ids ?? [])])]
  const [selected, setSelected] = useState(item.project_id)
  return <div className="commercial-project-chains">
    {projectIds.length > 1 && <div className="commercial-project-chain-select" role="group" aria-label="Project relationship records">{projectIds.map((projectId, index) => <button key={projectId} type="button" aria-pressed={selected === projectId} onClick={() => setSelected(projectId)}>Project {index + 1} · {projectId === item.project_id ? 'primary record' : 'related record'}</button>)}</div>}
    <div className="commercial-project-chain"><p className="commercial-project-chain-label">{projectIds.length > 1 ? `Project relationship ${projectIds.indexOf(selected) + 1}` : 'Project relationship'} · {selected === item.project_id ? 'primary project record' : 'related project record'} · identities remain separate</p><BuyingChain key={selected} projectId={selected}/></div>
  </div>
}

function Citation({ fact }: { fact: NonNullable<CommercialTriageCard['facts']>[number] }) {
  return <>{fact.url && <> <a href={fact.url} target="_blank" rel="noreferrer">Source ↗</a></>}{fact.evidence_id && <small> [{fact.evidence_id}{fact.hash ? ` · ${fact.hash.slice(0, 12)}` : ''}]</small>}</>
}

function ResearchQuestion({ item, draft, onDraftChange }: { item: CommercialTriageCard; draft: CommercialDraft; onDraftChange: (changes: Partial<CommercialDraft>) => void }) {
  const busy = draft.researchSubmitting ?? false
  const setBusy = (researchSubmitting: boolean) => onDraftChange({ researchSubmitting })
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
    if (busy) return
    setBusy(true)
    onDraftChange({ researchInterrupted: false })
    try {
      const brief = await client.researchCommercialNeed(item.id, { question: draft.question })
      const message = brief.job_id && brief.status === 'pending' ? 'Research is queued; checking for the exact-question result.' : brief.job_id === null && brief.status === 'ready' ? 'Existing brief unchanged; showing the saved result.' : brief.error ? `Research unavailable: ${brief.error}` : brief.stale ? 'Existing brief is stale; no current result was produced.' : brief.status === 'ready' ? 'Research result' : `Research ${brief.status}`
      onDraftChange({ research: { question: draft.question, brief, message, failed: Boolean(brief.error) || brief.status === 'failed' || brief.stale } })
    } catch (cause) { onDraftChange({ research: { question: draft.question, brief: { status: 'failed', stale: false, question_context: 'current', generated_at: null, result: null, citations: [], error: cause instanceof Error ? cause.message : 'Targeted research unavailable.', input_tokens: 0, output_tokens: 0, job_id: null }, message: cause instanceof Error ? cause.message : 'Targeted research unavailable.', failed: true } }) }
    finally { setBusy(false) }
  }
  const pending = progress?.brief.status === 'pending' && Boolean(progress.brief.job_id)
  return <section className="commercial-action"><h3>Targeted research</h3>{draft.researchInterrupted && <p role="status">Research submission was interrupted by refresh. Submit the same question to check or resume its existing request.</p>}<form onSubmit={(event) => void submit(event)}><label>Exact missing-fact question<textarea aria-label="Exact missing-fact question" data-context-key="research-question" required minLength={12} maxLength={300} value={draft.question} onChange={(event) => onDraftChange({ question: event.target.value, research: undefined })} disabled={busy || pending}/></label><button className="primary" disabled={busy || pending || draft.question.trim().length < 12}>{busy ? 'Queueing…' : pending ? 'Research in progress…' : 'Research this question'}</button></form>{progress?.message && <p role={progress.failed ? 'alert' : 'status'}>{progress.message}</p>}{progress?.brief.status === 'ready' && progress.brief.result && <ResearchResult brief={progress.brief}/>}</section>
}

function researchBrief(status: CommercialResearchStatus): BriefRequest {
  const result = checkedResearchContent(status.result)
  const citations = (status.citations ?? []).filter((citation): citation is NonNullable<BriefRequest['citations']>[number] => isRecord(citation) && typeof citation.evidence_id === 'string' && typeof citation.url === 'string' && typeof citation.title === 'string')
  return { status: status.status, stale: status.status === 'superseded', question_context: 'current', generated_at: status.generated_at ?? null, result, citations, error: status.error ?? null, input_tokens: 0, output_tokens: 0, job_id: status.job_id ?? null }
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
  const saving = draft.savingNote ?? false
  const message = draft.noteMessage ?? ''
  const setSaving = (savingNote: boolean) => onDraftChange({ savingNote })
  const setMessage = (noteMessage: string) => onDraftChange({ noteMessage })
  async function save(event: FormEvent) {
    event.preventDefault()
    if (saving) return
    if (!item.pursuit_id) { setMessage('Save a pursuit snapshot before adding notes.'); return }
    setSaving(true)
    const clientId = draft.clientId ?? crypto.randomUUID()
    if (!draft.clientId) onDraftChange({ clientId })
    const body: CallNoteBody = { client_id: clientId, note: draft.note, outcome: draft.outcome, next_action: draft.nextAction, follow_up: null }
    try { await client.savePursuitNote(item.pursuit_id, body); onDraftChange({ note: '', nextAction: '', outcome: 'Not reached', clientId: undefined }); setMessage('Note saved to this pursuit. Evidence tier unchanged.'); onSaved() }
    catch (cause) { setMessage(cause instanceof Error ? cause.message : 'Note could not be saved.') }
    finally { setSaving(false) }
  }
  return <section className="commercial-action"><h3>Saved pursuit notes</h3>{item.notes?.length ? item.notes.map((entry) => <article className="commercial-note" key={entry.id}><p><b>{entry.outcome}</b> · {entry.owner} · {new Date(entry.created_at).toLocaleString()}</p><p>{entry.note}</p>{entry.next_action && <p><b>Next action:</b> {entry.next_action}</p>}{entry.follow_up && <p><b>Follow-up:</b> {entry.follow_up}</p>}</article>) : <p>No saved notes yet.</p>}<h3>Add operator note</h3><p>{draft.refreshSafe === false ? "Session storage is unavailable or full; this note may not survive refresh." : "Unsaved note input stays in this tab for up to eight hours. Sign out clears it."}</p><form onSubmit={(event) => void save(event)}><label>Note<textarea aria-label="Note" data-context-key="commercial-note" required maxLength={5000} value={draft.note} onChange={(event) => onDraftChange({ note: event.target.value, clientId: draft.clientId ? crypto.randomUUID() : undefined })} disabled={saving}/></label><label>Reported outcome<select data-context-key="commercial-outcome" value={draft.outcome} onChange={(event) => onDraftChange({ outcome: event.target.value as CallNoteBody['outcome'], clientId: draft.clientId ? crypto.randomUUID() : undefined })} disabled={saving}>{['Not reached', 'Contacted', 'Needs follow-up', 'No requirement', 'Closed', 'Reached buying organization', 'Qualified'].map((value) => <option key={value}>{value}</option>)}</select></label><label>Next action<input data-context-key="commercial-next-action" maxLength={1000} value={draft.nextAction} onChange={(event) => onDraftChange({ nextAction: event.target.value, clientId: draft.clientId ? crypto.randomUUID() : undefined })} disabled={saving}/></label><button className="primary" disabled={saving || !item.pursuit_id}>{saving ? 'Saving…' : 'Save note'}</button></form>{message && <p role="status">{message}</p>}{!item.pursuit_id && <p>Notes become available after an existing pursuit is linked.</p>}</section>
}
