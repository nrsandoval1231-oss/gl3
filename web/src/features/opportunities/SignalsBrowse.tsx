import { useEffect, useMemo, useRef, useState } from 'react'
import { client, OpportunityCohortChangedError, type Opportunity, type OpportunityBrowseFilters, type OpportunityNeedScope, type OpportunityPage } from '../../api/client'
import { projectTitle, serverProjectCards, signalDecisionCards, signalDisplayDecision, type SignalDisplayDecision } from './projectCards'

const pageSize = 25
type BrowseTier = 'Signal' | 'Prospect' | 'Lead'
const pluralTier = (tier: BrowseTier) => tier === 'Prospect' ? 'Prospects' : tier === 'Lead' ? 'Leads' : 'Signals'
const decisions: (SignalDisplayDecision | 'ALL')[] = ['ALL', 'SHOW', 'REVIEW', 'HOLD']
function paramsFromUrl() {
  const params = new URLSearchParams(location.search)
  const valid = (value: string | null) => value === 'KNOWN' || value === 'UNKNOWN' ? value : ''
  const tierParam = params.get('tier') ?? params.get('level')
  const tier: BrowseTier = ['Prospect', 'Prospects'].includes(tierParam ?? '') ? 'Prospect' : ['Lead', 'Leads'].includes(tierParam ?? '') ? 'Lead' : 'Signal'
  return {
    tier,
    search: params.get('q') ?? '', decision: (tier === 'Signal' && decisions.includes(params.get('decision') as SignalDisplayDecision | 'ALL') ? params.get('decision') : 'ALL') as SignalDisplayDecision | 'ALL',
    offset: Math.max(0, Number(params.get('offset') ?? params.get('records') ?? 0) || 0),
    filters: { geography: params.get('geography') ?? '', industry: params.get('industry') ?? params.get('lens') ?? '', activity: params.get('activity') ?? '', timing: valid(params.get('timing')), mwStatus: valid(params.get('mw_status')), mwMin: params.get('mw_min') ?? '', mwMax: params.get('mw_max') ?? '', prioritySegment: params.get('priority_segment') ?? '', status: params.get('status') ?? '' } as OpportunityBrowseFilters,
  }
}
function writeUrl(search: string, decision: SignalDisplayDecision | 'ALL', offset: number, filters: OpportunityBrowseFilters, replace = false, tier = paramsFromUrl().tier) {
  const params = new URLSearchParams({ view: 'signals', tier: pluralTier(tier), q: search, decision })
  if (offset) params.set('offset', String(offset))
  for (const [key, value] of Object.entries({ geography: filters.geography, industry: filters.industry, activity: filters.activity, timing: filters.timing, mw_status: filters.mwStatus, mw_min: filters.mwMin, mw_max: filters.mwMax, priority_segment: filters.prioritySegment, status: filters.status })) if (value) params.set(key, value)
  if (replace) history.replaceState(history.state, '', `/?${params}`); else history.pushState(null, '', `/?${params}`)
}

export function SignalsBrowse({ onSelect, onScope, refreshKey = 0 }: { onSelect: (item: Opportunity) => void; onScope: (scope: OpportunityNeedScope | null) => void; refreshKey?: number }) {
  const initial = paramsFromUrl()
  const [tier, setTier] = useState<BrowseTier>(initial.tier)
  const [search, setSearch] = useState(initial.search)
  const [decision, setDecision] = useState<SignalDisplayDecision | 'ALL'>(initial.decision)
  const [filters, setFilters] = useState<OpportunityBrowseFilters>(initial.filters)
  const [offset, setOffset] = useState(initial.offset)
  const [page, setPage] = useState<OpportunityPage | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState<Record<string, Opportunity[]>>({})
  const request = useRef(0)
  const expansion = useRef(0)
  const pendingGroup = useRef<string | null>(null)
  const cohort = useRef<{ key: string; token: string } | null>(null)
  const lastRefreshKey = useRef(refreshKey)
  const scopeKey = JSON.stringify([tier, search, decision, filters])
  useEffect(() => {
    const restore = () => { const value = paramsFromUrl(); setTier(value.tier); setSearch(value.search); setDecision(value.decision); setFilters(value.filters); setOffset(value.offset) }
    addEventListener('popstate', restore)
    return () => removeEventListener('popstate', restore)
  }, [])
  useEffect(() => {
    const reset = () => { ++expansion.current; pendingGroup.current = null; if (tier !== 'Signal' || offset !== 0 || decision !== 'ALL') { setPage(null); setTier('Signal'); setOffset(0); setDecision('ALL') }; setExpanded({}); writeUrl(search, 'ALL', 0, filters, true, 'Signal') }
    addEventListener('gridlens:signals-reset', reset)
    return () => removeEventListener('gridlens:signals-reset', reset)
  }, [tier, search, decision, offset, filters])
  useEffect(() => {
    const params = new URLSearchParams(location.search)
    if (tier !== 'Signal' && params.has('decision') && params.get('decision') !== 'ALL') { params.set('decision', 'ALL'); history.replaceState(history.state, '', `/?${params}`) }
    const refreshed = lastRefreshKey.current !== refreshKey
    lastRefreshKey.current = refreshKey
    if (refreshed) {
      cohort.current = null
      setExpanded({})
      onScope(null)
      if (offset !== 0) {
        setPage(null); setOffset(0); writeUrl(search, decision, 0, filters, true, tier)
        return
      }
    }
    const controller = new AbortController(), id = ++request.current
    ++expansion.current; onScope(null); setExpanded({}); setPage(null); setLoading(true); setError('')
    void (async () => {
      let token = cohort.current?.key === scopeKey ? cohort.current.token : undefined
      if (offset > 0 && !token) {
        const first = await client.opportunityPage(tier, search, decision, pageSize, 0, undefined, filters, controller.signal, 'rank')
        token = first.cohortToken
        if (!token) throw new Error('The first Signal page did not provide a cohort token.')
      }
      return client.opportunityPage(tier, search, decision, pageSize, offset, offset > 0 ? token : undefined, filters, controller.signal, 'rank')
    })().then(value => {
      if (controller.signal.aborted || request.current !== id) return
      cohort.current = { key: scopeKey, token: value.cohortToken }
      onScope({ tier, search, decision, cohortToken: value.cohortToken, filters })
      setPage(value); setLoading(false)
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted && request.current === id) {
        if (cause instanceof OpportunityCohortChangedError && offset > 0) { cohort.current = null; setOffset(0); writeUrl(search, decision, 0, filters); setError('The Signal cohort changed; restarted at page one.') }
        else setError(cause instanceof Error ? cause.message : 'Signals are unavailable.')
        setLoading(false)
      }
    })
    return () => { controller.abort(); ++expansion.current }
  }, [search, decision, offset, scopeKey, refreshKey])
  const cards = useMemo(() => page ? serverProjectCards(page.items) : [], [page])
  const visibleCards = useMemo(() => decision === 'ALL' ? cards : signalDecisionCards(cards, decision), [cards, decision])
  const change = (next: Partial<Pick<OpportunityBrowseFilters, 'geography'|'industry'|'activity'|'timing'|'mwStatus'|'mwMin'|'mwMax'|'prioritySegment'|'status'>>) => {
    const updated = { ...filters, ...next }
    if (JSON.stringify(updated) === JSON.stringify(filters)) return
    ++expansion.current; pendingGroup.current = null
    setFilters(updated); setOffset(0); setExpanded({}); setPage(null); writeUrl(search, decision, 0, updated)
  }
  const setSearchValue = (value: string) => { if (value === search) return; ++expansion.current; pendingGroup.current = null; setSearch(value); setOffset(0); setExpanded({}); setPage(null); writeUrl(value, decision, 0, filters) }
  const setDecisionValue = (value: SignalDisplayDecision | 'ALL') => { if (value === decision) return; ++expansion.current; pendingGroup.current = null; setDecision(value); setOffset(0); setExpanded({}); setPage(null); writeUrl(search, value, 0, filters) }
  async function showGroup(cardKey: string) {
    const wasPending = pendingGroup.current === cardKey
    const intent = ++expansion.current
    pendingGroup.current = null
    if (wasPending) return
    if (!page || expanded[cardKey]) { setExpanded(current => { const next = { ...current }; delete next[cardKey]; return next }); return }
    pendingGroup.current = cardKey
    try {
      const items: Opportunity[] = []
      let nextOffset: number | null = 0
      do {
        const group = await client.opportunityGroupPage(cardKey, tier, search, decision, page.cohortToken, 50, nextOffset, filters)
        if (intent !== expansion.current) return
        items.push(...group.items); nextOffset = group.next_offset
      } while (nextOffset !== null)
      pendingGroup.current = null
      setExpanded(current => ({ ...current, [cardKey]: items }))
    } catch (cause) { if (intent === expansion.current) pendingGroup.current = null; if (intent === expansion.current) setError(cause instanceof Error ? cause.message : 'Grouped Signal records are unavailable.') }
  }
  const countFor = (key: SignalDisplayDecision | 'ALL') => key === 'ALL' ? page?.groupTotalCount ?? '—' : page?.decisionCounts[key] ?? '—'
  return <main className="signals-browse" aria-label="Signals browser">
    <div className="signals-heading"><div><p className="wh-kicker">Evidence-led discovery</p><h1>{pluralTier(tier)}</h1><p>Records worth investigating. Qualification and commercial disposition remain separate.</p></div><span>{page ? `${page.groupTotalCount} project groups · ${page.totalCount} records` : 'Loading full cohort…'}</span></div>
    <div className="signals-toolbar"><label>Qualification tier<select aria-label="Qualification tier" value={tier} onChange={event => { const next = event.target.value as BrowseTier; if (next === tier) return; ++expansion.current; pendingGroup.current = null; setTier(next); setDecision('ALL'); setOffset(0); setExpanded({}); setPage(null); writeUrl(search, 'ALL', 0, filters, false, next) }}><option value="Signal">Signals</option><option value="Prospect">Prospects</option><option value="Lead">Leads</option></select></label><label>Search {pluralTier(tier)}<input aria-label="Search projects" value={search} onChange={event => setSearchValue(event.target.value)} placeholder="Project, company, site, or source"/></label>{page && !loading && !error && <a href={client.opportunityExportUrl(tier, search, decision, page.cohortToken, filters)} download>Download filtered CSV</a>}</div>
    {tier === 'Signal' && <nav className="signals-decisions" aria-label="Filter by evidence decision">{decisions.map(value => <button type="button" key={value} aria-pressed={decision === value} className={decision === value ? 'selected' : ''} onClick={() => setDecisionValue(value)}>{value === 'ALL' ? 'All' : value}<strong>{countFor(value)}</strong></button>)}</nav>}
    <details className="wh-filter-disclosure"><summary>Geography, industry, activity, timing, size, priority and status filters</summary><div className="wh-filters"><input aria-label="Geography" value={filters.geography ?? ''} placeholder="Geography" onChange={event => change({ geography: event.target.value })}/><input aria-label="Industry" value={filters.industry ?? ''} placeholder="Industry" onChange={event => change({ industry: event.target.value })}/><input aria-label="Activity" value={filters.activity ?? ''} placeholder="Activity" onChange={event => change({ activity: event.target.value })}/><select aria-label="Timing" value={filters.timing ?? ''} onChange={event => change({ timing: event.target.value as OpportunityBrowseFilters['timing'] })}><option value="">Any timing</option><option>KNOWN</option><option>UNKNOWN</option></select><select aria-label="MW status" value={filters.mwStatus ?? ''} onChange={event => change({ mwStatus: event.target.value as OpportunityBrowseFilters['mwStatus'] })}><option value="">Any MW status</option><option>KNOWN</option><option>UNKNOWN</option></select><input aria-label="Minimum MW" value={filters.mwMin ?? ''} placeholder="Min MW" onChange={event => change({ mwMin: event.target.value })}/><input aria-label="Maximum MW" value={filters.mwMax ?? ''} placeholder="Max MW" onChange={event => change({ mwMax: event.target.value })}/><input aria-label="Priority segment" value={filters.prioritySegment ?? ''} placeholder="Priority segment" onChange={event => change({ prioritySegment: event.target.value })}/><select aria-label="Workflow status" value={filters.status ?? ''} onChange={event => change({ status: event.target.value as OpportunityBrowseFilters['status'] })}><option value="">Any workflow status</option><option>UNKNOWN</option>{['New','Investigating','Contacted','Qualified','Won','Lost','Closed'].map(value => <option key={value} value={value.toUpperCase()}>{value}</option>)}</select></div></details>
    {error && <p className="wh-error" role="alert">{error}</p>}{loading && <p role="status">Loading current Signal cohort…</p>}{!loading && !error && visibleCards.length === 0 && (decision === 'SHOW' ? <div className="wh-empty"><h2>No SHOW decisions yet</h2><p>Check REVIEW ({page?.decisionCounts.REVIEW ?? '—'}) for uncertain or not-yet-adjudicated projects. An unavailable Jev decision stays visible there.</p></div> : <p className="wh-empty">No Signals match these filters.</p>)}
    <section className="signals-groups">{visibleCards.map(card => {
      const members = expanded[card.key] ?? card.members
      const open = Boolean(expanded[card.key])
      const choose = (item: Opportunity) => { ++expansion.current; pendingGroup.current = null; onSelect(item) }
      return <article className="signals-group" key={card.key}><header><div><p className="wh-kicker"><span data-review-decision>Decision: {signalDisplayDecision(card.members)}</span> · {card.grouped ? `${card.groupTotal} related records` : 'Power need'}</p><button type="button" data-opportunity-id={card.members[0]?.id} aria-expanded={card.grouped ? open : undefined} onClick={() => card.grouped ? (card.complete ? setExpanded(current => { const next = { ...current }; if (next[card.key]) delete next[card.key]; else next[card.key] = card.members; return next }) : void showGroup(card.key)) : choose(card.members[0])}><h2>{card.title}</h2><span>{card.members[0]?.location ?? 'Location unknown'} · {card.members[0]?.activity?.replaceAll('_',' ') ?? 'Activity unknown'}{card.members[0]?.reported_power_facts?.length ? ` · ${card.members[0].reported_power_facts.join(' · ')}` : ''}{card.members[0]?.commercial_size_status === 'unknown' ? ' · Activity size unknown · retained' : ''}</span></button></div><span>{card.members[0]?.tier ?? 'Signal'}</span></header>{members.some(item => item.signal_evidence_state === 'source_listing_absent') && <p className="wh-integrity">Status review needed: a retained filing is no longer in its source's current listing. Its outcome is unknown.</p>}<p className="signals-group-reason">{card.members[0]?.assessment_reason ?? card.members[0]?.rationale ?? 'Reason to investigate unavailable.'}</p>{card.grouped && open && <div className="signals-member-list"><p>{members.filter(item => item.matched_search !== false).length} matching · {card.groupTotal ?? members.length} related records</p>{members.map(item => <button type="button" className="project-member" data-opportunity-id={item.id} key={item.id} onClick={() => choose(item)}><strong>{projectTitle(item)}</strong><span data-review-decision>Decision: {signalDisplayDecision([item])}</span>{item.signal_evidence_state === 'source_listing_absent' && <span>Status review needed: no longer in the source's current listing; outcome unknown.</span>}<span>{item.activity.replaceAll('-', ' ')} · {item.required_mw ?? 'Power unknown'} · {item.start_window ?? 'Start unknown'}</span><small>{item.evidence[0]?.published_at ? `Published ${item.evidence[0].published_at}` : 'Publication date unknown'} · {item.evidence[0]?.event_date_label ?? 'Event date'} {item.evidence[0]?.event_date ?? 'unknown'}</small></button>)}</div>}</article>
    })}</section>
    <footer className="wh-paging"><span>Showing {page?.offset ? page.offset + 1 : page?.items.length ? 1 : 0}–{page ? page.offset + page.items.length : '—'} of {page?.totalCount ?? '—'} records · {page?.groupTotalCount ?? '—'} project groups</span><button disabled={!page?.offset || loading} onClick={() => { const value = Math.max(0, (page?.offset ?? 0) - pageSize); ++expansion.current; pendingGroup.current = null; setPage(null); setOffset(value); writeUrl(search, decision, value, filters) }}>Previous</button><button disabled={page?.nextOffset == null || loading} onClick={() => { const value = page?.nextOffset ?? 0; ++expansion.current; pendingGroup.current = null; setPage(null); setOffset(value); writeUrl(search, decision, value, filters) }}>Next</button></footer>
  </main>
}
