import { type FormEvent, useEffect, useRef, useState } from 'react'
import { client, type Brief, type IngestionItem, type Opportunity } from '../api/client'
import { matchesOpportunity, projectCards, projectTitle, signalDecisionCards, signalDisplayDecision, type SignalDisplayDecision } from '../features/opportunities/projectCards'

import { Pursuits } from '../features/pursuits/Pursuits'

import { BuyingChain } from '../features/buyingChain/BuyingChain'

const tiers = ['Signals', 'Prospects', 'Leads'] as const
type Tier = typeof tiers[number]
type Health = Awaited<ReturnType<typeof client.health>>
type Change = Awaited<ReturnType<typeof client.changes>>[number]
type View = 'opportunities' | 'ingestion' | 'pursuits'
const pageSize = 25

function tierValue(tier: Tier) { return tier.slice(0, -1) }
function routeUrl(tier: Tier, search: string, hash = '') {
  const query = new URLSearchParams({ tier, q: search })
  return `${location.pathname}?${query.toString()}${hash}`
}
function ingestionUrl(view: 'ingestion', source: string, vertical: string, offset: number) {
  const query = new URLSearchParams({ view })
  if (source) query.set('source', source)
  if (vertical) query.set('vertical', vertical)
  if (offset) query.set('offset', String(offset))
  return `${location.pathname}?${query.toString()}`
}
function parseOffset(value: string | null) {
  const parsed = Number(value ?? 0)
  return Number.isInteger(parsed) && parsed >= 0 && parsed <= 100_000 ? parsed : 0
}
function memberDate(item: Opportunity) {
  const evidence = item.evidence[0]
  if (!evidence) return 'Date unknown'
  return sourceDateLabel(evidence, false)
}
function sourceDateLabel(evidence: Opportunity['evidence'][number], showPublication: boolean) {
  const airEvent = evidence.source_id === 'georgia-air-draft-title-v' && evidence.event_date
    ? `${evidence.event_date_label ?? 'Source event'} ${evidence.event_date}`
    : null
  if (airEvent) return showPublication ? `${airEvent} · publication date unknown` : airEvent
  if (evidence.source_id.endsWith('-building-permits')) {
    return `Permit issue date ${evidence.event_date ?? 'unknown'} ${showPublication ? '· publication date unknown' : ''}`.trim()
  }
  return evidence.published_at ? `Published ${evidence.published_at}` : 'Publication date unknown'
}

export function App() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null)
  const [password, setPassword] = useState('')
  const [tier, setTier] = useState<Tier>('Signals')
  const [signalFilter, setSignalFilter] = useState<SignalDisplayDecision>('SHOW')
  const [view, setView] = useState<View>('opportunities')
  const [search, setSearch] = useState('')
  const [items, setItems] = useState<Opportunity[]>([])
  const [selected, setSelected] = useState<Opportunity | null>(null)
  const [expandedCardKey, setExpandedCardKey] = useState<string | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [changes, setChanges] = useState<Change[]>([])
  const [ingestionItems, setIngestionItems] = useState<IngestionItem[]>([])
  const [ingestionTotal, setIngestionTotal] = useState(0)
  const [sourceFilter, setSourceFilter] = useState('')
  const [verticalFilter, setVerticalFilter] = useState('')
  const [offset, setOffset] = useState(0)
  const [showHealth, setShowHealth] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const requestSequence = useRef(0)
  const itemsRef = useRef(items)
  itemsRef.current = items

  useEffect(() => {
    void client.session().then((value) => setAuthenticated(value.authenticated)).catch(() => setAuthenticated(false))
    const params = new URLSearchParams(location.search)
    const initialTier = params.get('tier')
    if (tiers.includes(initialTier as Tier)) setTier(initialTier as Tier)
    setSearch(params.get('q') ?? '')
    const initialView = params.get('view')
    if (initialView === 'ingestion' || initialView === 'pursuits') setView(initialView)
    setSourceFilter(params.get('source') ?? '')
    setVerticalFilter(params.get('vertical') ?? '')
    setOffset(parseOffset(params.get('offset')))
  }, [])

  useEffect(() => {
    if (!authenticated) return
    const requestId = ++requestSequence.current
    setLoading(true)
    void (async () => {
      try {
        if (view === 'opportunities') {
          const [opportunities, digest, sourceHealth] = await Promise.all([
            client.opportunities(tierValue(tier), ''), client.changes(), client.health(),
          ])
          if (requestId !== requestSequence.current) return
          setItems(opportunities)
          setChanges(digest)
          setHealth(sourceHealth)
          if (selected) setSelected(opportunities.find((item) => item.id === selected.id) ?? null)
        } else if (view === 'pursuits') {
          const sourceHealth = await client.health()
          if (requestId !== requestSequence.current) return
          setHealth(sourceHealth)
          setSelected(null)
        } else {
          const [page, sourceHealth] = await Promise.all([
            client.ingestion(sourceFilter, verticalFilter, pageSize, offset),
            client.health(),
          ])
          if (requestId !== requestSequence.current) return
          setIngestionItems(page.items)
          setIngestionTotal(page.total)
          setHealth(sourceHealth)
          setSelected(null)
        }
        setError('')
      } catch (cause: unknown) {
        if (requestId === requestSequence.current) setError(cause instanceof Error ? cause.message : 'GridLens could not load this view.')
      } finally {
        if (requestId === requestSequence.current) setLoading(false)
      }
    })()
    const url = view === 'opportunities'
      ? routeUrl(tier, search, selected ? `#${encodeURIComponent(selected.id)}` : '')
      : view === 'pursuits' ? `${location.pathname}?view=pursuits` : ingestionUrl(view, sourceFilter, verticalFilter, offset)
    history.replaceState(
      { ...(history.state ?? {}), tier, search, view, sourceFilter, verticalFilter, offset, scrollY: window.scrollY },
      '',
      url,
    )
  }, [authenticated, tier, search, view, sourceFilter, verticalFilter, offset])

  useEffect(() => {
    function onPopState(event: PopStateEvent) {
      const state = event.state as { tier?: Tier; search?: string; id?: string; view?: View; sourceFilter?: string; verticalFilter?: string; offset?: number; scrollY?: number; focusedId?: string } | null
      const params = new URLSearchParams(location.search)
      if (state?.tier && tiers.includes(state.tier)) setTier(state.tier)
      else setTier('Signals')
      const restoredView = state?.view ?? params.get('view')
      setView(restoredView === 'ingestion' || restoredView === 'pursuits' ? restoredView : 'opportunities')
      setSearch(state?.search ?? '')
      setSourceFilter(state?.sourceFilter ?? params.get('source') ?? '')
      setVerticalFilter(state?.verticalFilter ?? params.get('vertical') ?? '')
      setOffset(state?.offset ?? parseOffset(params.get('offset')))
      setSelected(state?.id ? itemsRef.current.find((item) => item.id === state.id) ?? null : null)
      requestAnimationFrame(() => {
        window.scrollTo(0, state?.scrollY ?? 0)
        if (state?.focusedId) document.querySelector<HTMLButtonElement>(`[data-opportunity-id="${CSS.escape(state.focusedId)}"]`)?.focus()
      })
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  useEffect(() => {
    if (!selected) return
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') history.back()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [selected])

  async function onLogin(event: FormEvent) {
    event.preventDefault()
    try {
      await client.login(password)
      setAuthenticated(true)
      setPassword('')
      setError('')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Sign-in failed.')
    }
  }

  async function signOut() {
    await client.logout()
    setAuthenticated(false)
    setSelected(null)
  }

  function chooseTier(value: Tier) {
    setView('opportunities')
    setTier(value)
    setSelected(null)
    history.replaceState({ tier: value, search, scrollY: 0 }, '', routeUrl(value, search))
    window.scrollTo(0, 0)
  }

  function chooseView(value: View) {
    setView(value)
    setSelected(null)
    setOffset(0)
    history.pushState({ tier, search, view: value, sourceFilter, verticalFilter, offset: 0, scrollY: 0 }, '', value === 'opportunities' ? routeUrl(tier, search) : value === 'pursuits' ? `${location.pathname}?view=pursuits` : ingestionUrl('ingestion', sourceFilter, verticalFilter, 0))
    window.scrollTo(0, 0)
  }

  function chooseVertical(value: string) {
    setVerticalFilter(value)
    setSourceFilter('')
    setOffset(0)
  }

  function open(item: Opportunity) {
    history.replaceState({ tier, search, scrollY: window.scrollY, focusedId: item.id }, '', routeUrl(tier, search))
    history.pushState({ tier, search, id: item.id }, '', routeUrl(tier, search, `#${encodeURIComponent(item.id)}`))
    setSelected(item)
  }

  function moveTo(item: Opportunity) {
    history.replaceState({ tier, search, id: item.id }, '', routeUrl(tier, search, `#${encodeURIComponent(item.id)}`))
    setSelected(item)
  }

  function returnToBrowse() { history.back() }

  if (authenticated === null) return <main className="loading" aria-live="polite">Loading your private workspace…</main>
  if (!authenticated) return <main className="login-wrap"><form className="login" onSubmit={onLogin}><img src="/brand/lockup-horizontal-navy.svg" alt="GridLens"/><h1>Sign in</h1><p>Your private GridLens workspace.</p><label htmlFor="password">Password</label><input id="password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required/><button className="primary">Continue</button>{error && <p role="alert" className="error">{error}</p>}</form></main>

  const selectedIndex = selected ? items.findIndex((item) => item.id === selected.id) : -1
  const cards = projectCards(items)
  const searchedCards = cards.filter((card) => card.members.some((item) => matchesOpportunity(item, search)))
  const visibleCards = tier === 'Signals'
    ? signalDecisionCards(searchedCards, signalFilter)
    : searchedCards
  const signalCounts = Object.fromEntries((['SHOW', 'REVIEW', 'HOLD'] as const).map((decision) => [
    decision,
    signalDecisionCards(cards, decision).length,
  ])) as Record<SignalDisplayDecision, number>
  const matchingRecordCount = items.filter((item) => matchesOpportunity(item, search)).length
  const selectedGroup = selected && cards.find((card) => card.grouped && card.members.some((item) => item.id === selected.id))
  const selectedSharesProjectId = Boolean(selectedGroup && selected?.project_id && selectedGroup.members.every((member) => member.project_id === selected.project_id))
  return <div className="shell">
    <header className="topbar"><a className="brand" href={routeUrl('Signals', '')} aria-label="GridLens home" onClick={(event) => { event.preventDefault(); chooseTier('Signals') }}><img src="/brand/lockup-horizontal-navy.svg" alt="GridLens"/></a><nav aria-label="Workspace views">{tiers.map((name) => <button key={name} className={view === 'opportunities' && tier === name ? 'nav-active' : ''} aria-current={view === 'opportunities' && tier === name ? 'page' : undefined} onClick={() => chooseTier(name)}>{name}</button>)}<button className={view === 'pursuits' ? 'nav-active' : ''} aria-current={view === 'pursuits' ? 'page' : undefined} onClick={() => chooseView('pursuits')}>Today’s pursuits</button><button className={view === 'ingestion' ? 'nav-active' : ''} aria-current={view === 'ingestion' ? 'page' : undefined} onClick={() => chooseView('ingestion')}>Ingestion</button></nav><div className="header-actions"><button className="health-toggle" onClick={() => setShowHealth((value) => !value)} aria-expanded={showHealth}>Source health</button><button className="signout" onClick={() => void signOut()}>Sign out</button></div></header>
    <main className="workspace">
      {!selected && view === 'opportunities' && <div className="overview-grid"><section className="hero"><div><p className="eyebrow">Evidence-led project discovery</p><h1>{tier}</h1><p>{tier === 'Signals' ? 'SHOW means this project or event is worth investigating. It does not mean a qualified opportunity.' : 'Projects with sourced events that may warrant a power discovery conversation.'}</p></div></section><section className="today"><div><p className="eyebrow">Today</p><strong>{changes.length} material {changes.length === 1 ? 'change' : 'changes'}</strong></div>{changes.slice(0, 3).map((change, index) => <a href={change.url} key={`${change.kind}-${index}`} target="_blank" rel="noreferrer"><span>{change.kind}</span>{change.title}</a>)}{changes.length === 0 && <span className="today-empty">No material opportunity changes today.</span>}</section></div>}
      {!selected && view === 'ingestion' && <section className="hero"><div><p className="eyebrow">Retained evidence · Publisher and government sources</p><h1>Ingestion inbox</h1><p>Permits are primary project discovery; news is supplemental. Source evidence and qualification stay visible. City permit coverage is regional and limited to a rolling issue-date window.</p></div></section>}
      {selected && <section className="hero detail-hero"><div><p className="eyebrow">{selected.tier} · {selected.activity.replaceAll('-', ' ')}{selected.tier === 'Signal' ? ` · ${selected.signal_display_decision ?? 'REVIEW'}` : ''}</p><h1>{projectTitle(selected)}</h1>{selected.commercial_size_status === 'unknown' && selected.tier === 'Signal' && <p role="status" className="integrity"><strong>Activity size unknown.</strong> Retained for investigation; the 300 kW minimum is inclusive.</p>}{selected.signal_evidence_state === 'planning_application_withdrawn' && <p role="status" className="integrity"><strong>Planning application withdrawn · historical Signal.</strong> Current project viability is unknown.</p>}{selected.signal_evidence_state === 'planning_status_unknown' && <p role="status" className="integrity"><strong>Conflicting planning revision · historical Signal.</strong> Current application and project status are unknown.</p>}<p>{selected.rationale}</p>{selectedGroup && <p className="group-context">{selectedSharesProjectId ? `Part of a physical project group with ${selectedGroup.members.length} retained records. Each record and its evidence remain available.` : `Part of an exact-event permit group with ${selectedGroup.members.length} records. Each record and its evidence remain separate.`}</p>}</div><button className="back-button" onClick={returnToBrowse}>← Back to {tier}</button></section>}
      {showHealth && <HealthPanel health={health} />}
      {view === 'opportunities' && <div className="list-toolbar"><div><h2>{selected ? 'Opportunity brief' : `${tier} · ${visibleCards.length} project cards · ${items.length} opportunity records`}</h2>{!selected && <p>{tier === 'Signals' && search ? `${visibleCards.length} matching ${signalFilter} project cards · ${matchingRecordCount} matching Signal records across all decisions · ${items.length} total Signal records.` : tier === 'Signals' ? `${signalFilter} · ${visibleCards.length} project cards · ${items.length} retained Signal records. SHOW means worth investigating, not qualified.` : search ? `${visibleCards.length} matching project cards · ${matchingRecordCount} matching records · ${items.length} underlying records.` : 'Browse the evidence and open a project for its source details.'}</p>}</div><label className="search"><span className="sr-only">Search projects</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search projects, work, or permit ID"/></label></div>}
      {view === 'opportunities' && tier === 'Signals' && !selected && <div className="signal-filters" role="group" aria-label="Filter Signals by review decision">{(['SHOW', 'REVIEW', 'HOLD'] as const).map((decision) => <button key={decision} className={signalFilter === decision ? 'signal-filter-active' : ''} aria-pressed={signalFilter === decision} onClick={() => { setSignalFilter(decision); setSelected(null) }}>{decision} <span>{signalCounts[decision]}</span></button>)}</div>}
      {view === 'ingestion' && <div className="ingestion-tools"><label>Source<select aria-label="Filter by source" value={sourceFilter} onChange={(event) => { setSourceFilter(event.target.value); setOffset(0) }}><option value="">All sources</option>{sources.map((source) => <option value={source.id} key={source.id}>{source.name}</option>)}</select></label><label>Vertical<select aria-label="Filter by vertical" value={verticalFilter} onChange={(event) => chooseVertical(event.target.value)}><option value="">All verticals</option>{verticals.map((item) => <option key={item}>{item}</option>)}</select></label><span>{ingestionTotal} retained {ingestionTotal === 1 ? 'item' : 'items'} · page {Math.floor(offset / pageSize) + 1}</span></div>}
      {error && <p role="alert" className="error-banner">{error}</p>}
      {loading && <p className="loading-inline" role="status">Updating this view…</p>}
      {view === 'pursuits' ? <Pursuits/> : selected ? <><OpportunityDetail item={selected}/><div className="detail-navigation"><button disabled={selectedIndex <= 0} onClick={() => moveTo(items[selectedIndex - 1])}>← Previous</button><button disabled={selectedIndex < 0 || selectedIndex >= items.length - 1} onClick={() => moveTo(items[selectedIndex + 1])}>Next →</button></div></> : view === 'opportunities' ? visibleCards.length ? <div className="opportunity-list">{visibleCards.map((card) => {
        const matchingMembers = card.members.filter((item) => matchesOpportunity(item, search))
        const members = card.members
        const decision = signalDisplayDecision(card.members)
        const first = card.members.find((item) => decision === 'SHOW'
          ? item.signal_display_decision === 'SHOW'
          : decision === 'HOLD'
            ? item.signal_display_decision === 'HOLD'
            : item.signal_display_decision !== 'SHOW' && item.signal_display_decision !== 'HOLD') ?? card.members[0]
        const sameProject = Boolean(first.project_id && card.members.every((member) => member.project_id === first.project_id))
        const lifecycleEvents = new Map(card.members.flatMap((member) => member.lifecycle_timeline ?? []).map((event) => [`${event.event_type}:${event.date ?? ''}:${event.evidence_url}`, event]))
        const expanded = expandedCardKey === card.key
        return <div className="project-card" key={card.key}>
          <button key={first.id} data-opportunity-id={first.id} className="opportunity-row" aria-expanded={card.grouped ? expanded : undefined} onClick={() => card.grouped ? setExpandedCardKey(expanded ? null : card.key) : open(first)}>
            <span className="row-marker"/><span className="row-main"><strong>{projectTitle(first)}</strong><span>{first.location ?? 'Location unknown'}</span>{first.brief_summary && <small className={first.brief_stale ? 'brief-stale' : 'brief-preview'}>AI-assisted{first.brief_stale ? ' · stale' : ''}: {first.brief_summary}</small>}</span><span className="row-meta"><span>{first.signal_evidence_state === 'planning_application_withdrawn' ? 'Historical Signal · application withdrawn' : first.signal_evidence_state === 'planning_status_unknown' ? 'Historical Signal · status unknown' : first.tier}</span>{first.commercial_size_status === 'unknown' && <span>Activity size unknown · retained</span>}{first.reported_power_facts?.length ? <span>{first.reported_power_facts.slice(0, 2).join(' · ')}</span> : null}{card.grouped ? <span>{card.members.length} records</span> : null}</span><span className="arrow" aria-hidden="true">{card.grouped ? expanded ? '−' : '+' : '→'}</span>
          </button>
          {card.grouped && expanded && <div className="project-members"><p>{matchingMembers.length < card.members.length ? `${matchingMembers.length} matching record · ${card.members.length} related ${card.members.every((member) => member.evidence.some((evidence) => evidence.source_id.endsWith('-building-permits'))) ? 'permit ' : ''}records` : `${card.members.length} individual ${card.members.every((member) => member.evidence.some((evidence) => evidence.source_id.endsWith('-building-permits'))) ? 'permit ' : ''}records`}</p>{sameProject && <p>Grouped under the same stable physical project identity. Each source observation remains available below.</p>}{lifecycleEvents.size > 0 && <p>Lifecycle evidence: {[...lifecycleEvents.values()].map((event) => <span key={`${event.event_type}:${event.date ?? ''}:${event.evidence_url}`}>{event.event_type.replaceAll('_', ' ')}{event.date ? ` · ${event.date}` : ''}; </span>)}</p>}{members.map((member) => <button key={member.id} data-opportunity-id={member.id} className="project-member" onClick={() => open(member)}><strong>{projectTitle(member)}</strong><span>{memberDate(member)} · {member.location ?? 'Location unknown'}{matchesOpportunity(member, search) && search ? ' · Matches search' : ''}</span><span>Open this record and its evidence →</span></button>)}</div>}
        </div>
      })}</div> : !loading ? <div className="empty"><span className="empty-mark" aria-hidden="true">◇</span><h3>{search ? 'No matching projects' : tier === 'Signals' ? signalFilter === 'SHOW' ? 'No SHOW decisions yet' : `No ${signalFilter} Signals` : `No ${tier.toLowerCase()} yet`}</h3><p>{search ? tier === 'Signals' && matchingRecordCount > 0 ? `Matching Signal records exist outside the ${signalFilter} filter. Switch decision tabs to inspect them.` : 'No retained opportunity records match this search.' : tier === 'Signals' ? signalFilter === 'SHOW' ? `Check REVIEW (${signalCounts.REVIEW}) for uncertain or not-yet-adjudicated projects. An unavailable Jev decision stays visible there.` : `No project cards currently have a ${signalFilter} decision.` : `${tier} require additional supported facts. They will appear here when the evidence meets the qualification gate.`}</p></div> : null : <><IngestionList items={ingestionItems} loading={loading}/><div className="collection-pagination"><button disabled={offset <= 0 || loading} onClick={() => setOffset(Math.max(0, offset - pageSize))}>← Previous</button><button disabled={offset + pageSize >= ingestionTotal || loading} onClick={() => setOffset(offset + pageSize)}>Next →</button></div></>}
      </main><footer>Coverage is limited to configured and checked sources. Unknown project facts stay unknown.</footer>
  </div>
}

const newsSources = [
  { id: 'dcd-news', name: 'Data Center Dynamics' }, { id: 'utility-dive-news', name: 'Utility Dive' },
  { id: 'manufacturing-dive-news', name: 'Manufacturing Dive' }, { id: 'construction-dive-news', name: 'Construction Dive' },
  { id: 'ogj-exploration-news', name: 'Oil & Gas Journal' }, { id: 'mjbizdaily-news', name: 'MJBizDaily' },
]
const sources = [
  { id: 'austin-building-permits', name: 'Austin Building Permits' },
  { id: 'seattle-building-permits', name: 'Seattle Building Permits' },
  { id: 'chicago-building-permits', name: 'Chicago Building Permits' },
  { id: 'georgia-air-draft-title-v', name: 'Georgia EPD Draft Title V Permits' },
  { id: 'federal-register-eis', name: 'Federal Register' },
  { id: 'nc-commerce', name: 'North Carolina Department of Commerce' },
  { id: 'dallas-monthly-permits', name: 'Dallas Monthly Building Permits' },
  { id: 'el-paso-new-commercial-permits', name: 'El Paso New Commercial Permits' },
  { id: 'houston-weekly-permits', name: 'Houston Weekly Sold Permits' },
  ...newsSources,
]
const verticals = ['data centers', 'utilities', 'manufacturing', 'construction', 'healthcare', 'commercial facilities', 'oil and gas', 'cannabis', 'mining', 'energy', 'infrastructure']

function IngestionList({ items, loading }: { items: IngestionItem[]; loading: boolean }) {
  if (!items.length) return loading ? null : <div className="empty"><span className="empty-mark" aria-hidden="true">◇</span><h3>No retained source items</h3><p>Try another publisher or vertical filter.</p></div>
  return <div className="ingestion-list">{items.map((item) => <article className="ingestion-card" key={`${item.source_id}-${item.external_id}-${item.content_hash}`}><div className="ingestion-card-heading"><span>{item.source_origin ?? 'Source evidence'} · {item.publisher} · {item.verticals.join(', ')}</span><span>{item.collection_state} · {item.qualification_state}</span></div><h2><a href={item.citation_url} target="_blank" rel="noreferrer">{item.title}</a></h2><p className="ingestion-excerpt">{item.excerpt || 'Publisher supplied no short summary.'}</p>{(item.source_id.endsWith('-building-permits') || item.source_id === 'georgia-air-draft-title-v') && <p className="ingestion-assessment">Permit status: {item.permit_status ?? 'Unknown'}</p>}{item.assessment_current && item.assessment_reason && <p className="ingestion-assessment">{item.assessment_reason}{item.supported_subject ? ` Supported subject: ${item.supported_subject}.` : ''}{item.supported_action ? ` Action: ${item.supported_action}.` : ''}</p>}{item.demand_quote && <blockquote>{item.demand_quote}</blockquote>}{item.supply_quote && <blockquote>{item.supply_quote}</blockquote>}<div className="ingestion-meta"><span>{item.event_date ? `${item.event_date_label ?? 'Source event'} ${item.event_date} · publication date unknown` : item.published_at ? `Published ${item.published_at}` : 'Publication date unknown'}</span><span>{item.extraction_location}</span><span>First seen {new Date(item.first_seen_at).toLocaleString()}</span><span>Latest evidence {new Date(item.latest_evidence_at).toLocaleString()}</span><span>Scope: {item.source_scope}</span><span>Hash {item.content_hash.slice(0, 16)}</span></div></article>)}</div>
}

function HealthPanel({ health }: { health: Health | null }) {
  return <section className="health-panel" aria-label="Source health"><div className="health-heading"><div><p className="eyebrow">Collection status</p><h2>Source health</h2></div><span>{health?.backlog ?? 0} jobs · {health?.pending_interpretations ?? 0} interpretations waiting</span></div>{health?.sources.length ? health.sources.map((source) => <div className="health-row" key={source.id}><strong>{source.id}<small> · {source.enabled ? 'Enabled' : 'Disabled'}</small></strong><span className={`status status-${source.status === 'Failed' ? 'bad' : source.status === 'Overdue' ? 'warn' : 'ok'}`}>{source.status}</span><span>{source.last_attempt ? `Last attempt ${new Date(source.last_attempt).toLocaleString()}` : 'No attempts yet'}<br/>{source.last_success ? `Last success ${new Date(source.last_success).toLocaleString()}` : 'No verified success'}<br/>{source.id.endsWith('-building-permits') ? `Latest permit issue date ${source.latest_permit_issue_date ?? source.latest_publication_date ?? 'unknown'} · source publication time unknown · ${source.records_scanned ?? 0} rows scanned, ${source.permit_accepted ?? 0} Signals, ${source.permit_rejected ?? 0} held out` : source.id === 'georgia-air-draft-title-v' ? `Current draft Title V / SIP / synthetic-minor snapshot: ${source.snapshot_item_count ?? source.records_scanned ?? 0} rows · publication date unknown; application dates retained when stated · latest public-comment deadline ${source.latest_public_comment_deadline ?? 'unknown'} · ${source.permit_accepted ?? 0} Signals, ${source.permit_rejected ?? 0} held out · ${source.documents_extracted ?? 0} narrative/draft PDFs extracted · ${source.unextracted_public_notice_references ?? 0} public notices retained as unextracted references · ${source.generator_facts ?? 0} equipment excerpts, ${source.generator_excerpts_omitted ?? 0} omitted by cap · ${source.missing_application_documents ?? 0} application documents unavailable` : `Latest publication ${source.latest_publication_date ?? 'unknown'}`} · {source.new_records} new · {source.changed_records} changed · {source.parse_failures} parse failures{source.id === 'georgia-air-draft-title-v' ? <><br/>Collection scope: {source.collection_scope}<br/>Snapshot public-comment deadline range: {source.earliest_public_comment_deadline ?? 'unknown'}–{source.latest_public_comment_deadline ?? 'unknown'}<br/>{source.coverage_limitation}</> : source.snapshot_item_count !== undefined && source.snapshot_item_count !== null ? <><br/>Latest publisher snapshot: {source.snapshot_item_count} items, {source.snapshot_oldest_publication_date ?? 'unknown'}–{source.snapshot_newest_publication_date ?? 'unknown'}<br/>{source.coverage_limitation}</> : source.family === 'construction-permits' ? <><br/>{source.collection_scope ?? 'Regional city datasets; bounded issue-date and modification windows.'}<br/>{source.coverage_limitation ?? 'No national coverage claim.'}</> : null}{source.id === 'federal-register-eis' ? <><br/>PDF evidence {source.pdf_enriched}/{source.pdf_eligible} eligible; deferred {source.pdf_skipped_limit}</> : null}</span>{source.error && <span className="error">{source.error}</span>}</div>) : <p>Source health is not yet available.</p>}</section>
}

function missingFactCategory(fact: string) {
  const normalized = fact.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()
  if (/\b(location|site|city|state)\b/.test(normalized)) return 'location'
  if (/\b(supply|utility|service|interconnection)\b/.test(normalized)) return 'supply'
  if (/\b(power|mw|load|demand|electricity)\b/.test(normalized)) return 'power'
  if (/\b(start|timing|schedule)\b/.test(normalized)) return 'start'
  if (/\b(duration|term)\b/.test(normalized)) return 'duration'
  return normalized
}

function OpportunityDetail({ item }: { item: Opportunity }) {
  const activeNeedId = useRef(item.id)
  const [brief, setBrief] = useState<Brief | null>(null)
  const [briefBusy, setBriefBusy] = useState(false)
  const [briefError, setBriefError] = useState('')
  useEffect(() => {
    let cancelled = false
    activeNeedId.current = item.id
    setBrief(null)
    setBriefError('')
    void client.brief(item.id).then((value) => { if (!cancelled) setBrief(value) }).catch((cause: unknown) => {
      if (!cancelled) setBriefError(cause instanceof Error ? cause.message : 'Brief status is unavailable.')
    })
    return () => { cancelled = true }
  }, [item.id])
  useEffect(() => {
    if (brief?.status !== 'pending') return
    let cancelled = false
    let timer: number
    const poll = async () => {
      timer = window.setTimeout(async () => {
        try {
          const value = await client.brief(item.id)
          if (cancelled) return
          setBrief(value)
          if (value.status === 'pending') void poll()
        } catch (cause: unknown) {
          if (!cancelled) setBriefError(cause instanceof Error ? cause.message : 'Brief status is unavailable.')
        }
      }, 1600)
    }
    void poll()
    return () => { cancelled = true; window.clearTimeout(timer) }
  }, [item.id, brief?.status])
  async function requestBrief() {
    const needId = item.id
    setBriefBusy(true)
    setBriefError('')
    try {
      const value = await client.requestBrief(needId)
      if (activeNeedId.current === needId) setBrief(value)
    }
    catch (cause: unknown) {
      if (activeNeedId.current === needId) setBriefError(cause instanceof Error ? cause.message : 'GridLens could not request a brief.')
    }
    finally { setBriefBusy(false) }
  }
  const missingFactLabels: Record<string, string> = {
    location: 'Project location',
    power: 'Activity-specific power requirement',
    supply: 'Suitable utility supply',
    start: 'Start window',
    duration: 'Duration',
  }
  const missingFacts = [
    ...(item.missing_facts ?? []),
    ...(!item.location ? ['Project location'] : []),
    ...(!item.required_mw ? ['Activity-specific power requirement'] : []),
    ...(item.supply === 'Unknown' ? ['Utility service and suitable supply'] : []),
    ...(!item.start_window ? ['Start window'] : []),
    ...(!item.duration ? ['Duration'] : []),
  ]
  const stillUnknown = [...new Map(
    missingFacts.map((fact) => {
      const category = missingFactCategory(fact)
      return [category, missingFactLabels[category] ?? fact.trim()] as const
    }),
  ).values()]
  const content = brief?.result as { event_summary?: { text: string; evidence_id: string }[]; commercial_hypothesis?: { text: string; evidence_id: string }; unknowns?: string[]; next_step?: string } | null
  const statements = [...(content?.event_summary ?? []), ...(content?.commercial_hypothesis ? [content.commercial_hypothesis] : [])]
  const briefSection = <section className="detail-section brief-panel"><div className="evidence-heading"><div><p className="eyebrow">AI-assisted · source cited</p><h3>Concise evidence brief</h3></div><span>{brief?.status === 'pending' ? 'Generation pending' : brief?.status === 'stale' ? 'Stale evidence' : brief?.status === 'failed' ? 'Latest request failed' : brief?.generated_at ? `Generated ${new Date(brief.generated_at).toLocaleString()}` : 'Not generated'}</span></div>{brief?.status === 'pending' && <p role="status">Generating from retained public evidence…</p>}{briefError && <p className="error" role="alert">{briefError}</p>}{brief?.error && <p className="integrity">The last request could not produce a new brief. Any displayed brief is the last successfully generated version.</p>}{brief?.stale && <p className="integrity">Source evidence or brief settings changed after generation. This cached text is stale.</p>}{statements.map((statement, index) => { const citation = (brief?.citations ?? []).find((item) => item.evidence_id === statement.evidence_id); return <p key={`${statement.evidence_id}-${index}`}>{statement.text} {citation && <a href={citation.url} target="_blank" rel="noreferrer">[{citation.title}]</a>}</p> })}{content?.unknowns && content.unknowns.length > 0 && <><strong>Unknown</strong><ul>{content.unknowns.map((fact) => <li key={fact}>{fact}</li>)}</ul></>}{content?.next_step && <p><strong>Next verification step:</strong> {content.next_step}</p>}{!statements.length && brief?.status !== 'pending' && <p>The brief has not been generated.</p>}<button type="button" disabled={briefBusy || brief?.status === 'pending'} onClick={() => void requestBrief()}>{briefBusy ? 'Requesting…' : brief?.status === 'ready' ? 'Refresh brief' : 'Generate or retry brief'}</button></section>
  return <article className="detail">{briefSection}<div className="detail-summary"><div><span className="tier-pill">{item.tier}</span>{item.signal_admission_origin && <p>{item.signal_admission_origin}</p>}<p className="eyebrow">{item.activity.replaceAll('-', ' ')}</p><h2>{projectTitle(item)}</h2><p className="location">{item.location ?? 'Location unknown'}</p></div><div className="unknown-grid"><div><span>Required power</span><strong>{item.required_mw ?? 'Unknown'}</strong></div><div><span>Start</span><strong>{item.start_window ?? 'Unknown'}</strong></div><div><span>Duration</span><strong>{item.duration ?? 'Unknown'}</strong></div><div><span>Suitable supply</span><strong>{item.supply}</strong></div></div></div>{item.lifecycle_state && <section className="detail-section lifecycle"><p className="eyebrow">Asset lifecycle · separate from {item.tier} tier</p><h3>{(item.asset_type ?? 'unknown').replaceAll('_', ' ')} · {item.lifecycle_state.replaceAll('_', ' ')}</h3><p><strong>Expected next milestone:</strong> {item.expected_next_milestone ?? 'Unknown'}</p><p><strong>Expected power event:</strong> {item.expected_power_event ?? 'Unknown'}</p><p><strong>{item.asset_type === 'upstream_well' ? 'Estimated first production window' : 'Estimated lifecycle window'}:</strong> {item.time_to_power_window ?? 'Unknown'}</p>{item.estimate_version && <p className="integrity">Derived estimate · {item.estimate_version} · {String(item.estimate_basis?.confidence ?? 'confidence unknown')}. This is not a reported date, power requirement, or power gap.</p>}{(item.lifecycle_timeline?.length ?? 0) > 0 && <ol>{item.lifecycle_timeline?.map((event, index) => <li key={`${event.event_type}-${index}`}><a href={event.evidence_url} target="_blank" rel="noreferrer">{event.date ?? 'Date unknown'} · {event.state.replaceAll('_', ' ')}</a> <span>({event.value_kind}{event.current ? '' : ', superseded'}{event.published_at ? ` · published ${event.published_at}` : ''})</span></li>)}</ol>}{(item.monitoring_requirements?.length ?? 0) > 0 && <p><strong>Monitoring:</strong> {item.monitoring_requirements?.join(' · ')}</p>}{(item.lifecycle_open_questions?.length ?? 0) > 0 && <p><strong>Lifecycle evidence still missing:</strong> {item.lifecycle_open_questions?.join(' · ')}</p>}</section>}<section className="detail-section"><p className="eyebrow">Evidence-based assessment</p><p>{item.assessment_reason ?? item.rationale}</p>{item.supported_subject && <p>Supported subject: {item.supported_subject}{item.supported_action ? ` · ${item.supported_action}` : ''}</p>}{item.demand_quote && <blockquote>{item.demand_quote}</blockquote>}{item.supply_quote && <blockquote>{item.supply_quote}</blockquote>}{Boolean(item.reported_power_facts?.length) && <><p>Reported power figures (source claims; not rental requirements)</p><ul>{item.reported_power_facts?.map((fact, index) => <li key={`${index}-${fact}`}>{fact}</li>)}</ul></>}{item.tier === 'Signal' && <p className="integrity">Power need is not established. A Signal does not imply a power gap.</p>}</section><>{item.project_id && <BuyingChain key={item.project_id} projectId={item.project_id}/>}</><section className="detail-section"><p className="eyebrow">Next action</p><p>{item.next_action}</p></section><section className="detail-section"><div className="evidence-heading"><div><p className="eyebrow">Source evidence</p><h3>{item.evidence.length} {item.evidence.length === 1 ? 'record' : 'records'}</h3></div><span>Conflicts: {item.conflict_state}</span></div>{item.evidence.map((evidence) => <div className="evidence" key={`${evidence.document_number}-${evidence.content_hash}`}><h4><a href={evidence.url} target="_blank" rel="noreferrer">{evidence.title}</a></h4>{!evidence.assessment_current && <p className="integrity">{evidence.source_id === 'georgia-air-draft-title-v' ? 'Retained filing or supporting document; the current interpretation is bound to its parent filing version.' : 'Historical evidence version; the current assessment is bound to another retained version.'}</p>}<div className="evidence-meta"><span>{evidence.source_id === 'georgia-air-draft-title-v' ? `${evidence.event_date_label}: ${evidence.event_date ?? 'unknown'} · publication date unknown` : evidence.source_id.endsWith('-building-permits') ? `Permit issue date ${evidence.event_date ?? 'unknown'} · source publication time unknown` : evidence.published_at ? `Published ${evidence.published_at}` : 'Publication date unknown'}</span><span>Retrieved {new Date(evidence.retrieved_at).toLocaleString()}</span><span>{evidence.source_id === 'georgia-air-draft-title-v' ? `${evidence.event_date_label}: ${evidence.event_date ?? 'unknown'}` : `${evidence.source_id.endsWith('-building-permits') ? 'Permit event date' : 'Described event'}: ${evidence.source_id.endsWith('-building-permits') ? evidence.event_date ?? 'Unknown' : evidence.event_date_label}`}</span><span>{evidence.source_origin ?? 'Source evidence'} · {evidence.extraction_location}</span><span>{evidence.source_id} · {evidence.document_number} · {evidence.content_hash.slice(0, 12)}</span></div><p>{(evidence.source_id === 'texas-rrc-drilling-permits' ? evidence.abstract?.split('\nOpaque source bytes (base64; not interpreted): ')[0] : evidence.abstract) ?? 'No abstract provided by the source.'}</p></div>)}</section>{stillUnknown.length > 0 && <section className="detail-section missing"><h3>Still unknown</h3><ul>{stillUnknown.map((fact) => <li key={fact}>{missingFactLabels[missingFactCategory(fact)] ?? fact}</li>)}</ul></section>}</article>
}
