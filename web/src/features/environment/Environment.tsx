import { type FormEvent, type ReactNode, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { geoPath } from 'd3-geo'
import { feature } from 'topojson-client'
import type { FeatureCollection, Geometry } from 'geojson'
import type { GeometryCollection, Topology } from 'topojson-specification'
import statesTopology from 'us-atlas/states-albers-10m.json'
import { client, OpportunityNeedUnavailableError, type Opportunity, type OpportunityMapWindow } from '../../api/client'
import { projectTitle } from '../opportunities/projectCards'
import { BuyingChain } from '../buyingChain/BuyingChain'
import { FactWorkflowPanel } from '../pursuits/FactWorkflowPanel'
import { QuickCallLog } from '../pursuits/QuickCallLog'
import { useEnvironmentNavigation, withEnvironmentReturn } from './navigation'
import { BrowseRecords } from './BrowseRecords'
import { CommercialPursuits, defaultCommercialNavigation, type CommercialNavigation, type Disposition } from '../pursuits/CommercialPursuits'
import { stateOf } from './usStates'

const tiers = ['Signals', 'Prospects', 'Leads'] as const
type TierName = typeof tiers[number]
const modes = ['nation', 'state', 'project', 'power', 'evidence', 'buyers', 'action', 'browse', 'pursuits'] as const
type Mode = typeof modes[number]
export type Scene = { mode: Mode; state: string | null; needId: string | null; tier: TierName; lens: string; search: string; depth: number; browseOffset?: number; commercial?: CommercialNavigation }

const UNMAPPED = 'Unmapped'
const modeLabel: Record<Mode, string> = {
  nation: 'Nationwide', state: 'State', project: 'Project', power: 'Power need',
  evidence: 'Evidence', buyers: 'Buying chain', action: 'Call brief', browse: 'All records', pursuits: 'Commercial pursuits',
}
const states = feature(
  statesTopology as unknown as Topology,
  (statesTopology as unknown as Topology).objects.states as GeometryCollection<{ name: string }>,
) as unknown as FeatureCollection<Geometry, { name: string }>
const path = geoPath()
const centroids = new Map(states.features.map((f) => [f.properties.name, path.centroid(f)]))
const bounds = new Map(states.features.map((f) => [f.properties.name, path.bounds(f)]))

export function sceneFromUrl(params: URLSearchParams): Scene {
  const mode = params.get('mode') as Mode | null
  const tier = params.get('level') as TierName | null
  return {
    mode: mode && modes.includes(mode) ? mode : 'nation',
    state: params.get('state'),
    needId: params.get('need'),
    tier: tier && tiers.includes(tier) ? tier : 'Signals',
    lens: params.get('lens') ?? '',
    search: params.get('q') ?? '',
    depth: 0,
    browseOffset: parseOffset(params.get('records')),
    commercial: { offset: parseOffset(params.get('pursuitPage')), query: params.get('pursuitQuery') ?? '', needId: params.get('pursuitNeed'), disposition: (['ACTION NOW', 'RESEARCH', 'WATCH', 'REJECT'].includes(params.get('disposition') ?? '') ? params.get('disposition') : 'ACTION NOW') as Disposition },
  }
}
function parseOffset(value: string | null) {
  const offset = Number(value)
  return Number.isSafeInteger(offset) && offset >= 0 && offset <= 100000 ? offset : 0
}
function urlFor(scene: Scene) {
  const query = new URLSearchParams({ view: 'environment' })
  if (scene.mode !== 'nation') query.set('mode', scene.mode)
  if (scene.state) query.set('state', scene.state)
  if (scene.needId) query.set('need', scene.needId)
  if (scene.tier !== 'Signals') query.set('level', scene.tier)
  if (scene.lens) query.set('lens', scene.lens)
  if (scene.search) query.set('q', scene.search)
  if (scene.browseOffset) query.set('records', String(scene.browseOffset))
  const commercial = scene.commercial
  if (commercial?.offset) query.set('pursuitPage', String(commercial.offset))
  if (commercial?.query) query.set('pursuitQuery', commercial.query)
  if (commercial?.needId) query.set('pursuitNeed', commercial.needId)
  if (commercial && commercial.disposition !== 'ACTION NOW') query.set('disposition', commercial.disposition)
  return `${location.pathname}?${query.toString()}`
}
const readable = (value: string | null | undefined) => (value ?? '').replaceAll('_', ' ').replaceAll('-', ' ')
const known = (value: string | number | null | undefined) => value === null || value === undefined || value === '' ? 'Unknown' : String(value)
function evidenceDate(evidence: Opportunity['evidence'][number]) {
  if (evidence.event_date) return `${evidence.event_date_label ?? 'Source event'} ${evidence.event_date}`
  return evidence.published_at ? `Published ${evidence.published_at}` : 'Publication date unknown'
}

export function Environment({ onSignOut, today }: { onSignOut: () => void; today?: (onOpen: () => void) => ReactNode }) {
  const { scene, surface, go, save } = useEnvironmentNavigation(() => sceneFromUrl(new URLSearchParams(location.search)), urlFor)
  const [page, setPage] = useState<OpportunityMapWindow | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [lensOptions, setLensOptions] = useState<string[]>([])
  const [health, setHealth] = useState<{ ok: number; total: number } | null>(null)
  const commercial = scene.commercial ?? defaultCommercialNavigation
  const [draft, setDraft] = useState(scene.mode === 'pursuits' ? commercial.query : scene.search)
  const [menuOpen, setMenuOpen] = useState(false)
  useLayoutEffect(() => setMenuOpen(surface?.menuOpen ?? false), [surface, scene])
  const [revision, setRevision] = useState(0)
  const headingRef = useRef<HTMLHeadingElement>(null)

  const [selection, setSelection] = useState<{ id: string; item?: Opportunity; error?: string }>({ id: '' })
  const [membership, setMembership] = useState<{ key: string; outside?: boolean; error?: string }>({ key: '' })
  const filterKey = JSON.stringify([scene.tier, scene.lens, scene.search])
  const selectionKey = `${scene.needId}:${filterKey}`
  const [pageKey, setPageKey] = useState('')
  useEffect(() => setDraft(scene.mode === 'pursuits' ? commercial.query : scene.search), [scene.mode, scene.search, commercial.query])
  useEffect(() => {
    if (!scene.needId) return
    const id = scene.needId
    const controller = new AbortController()
    client.opportunityNeed(id, undefined, controller.signal).then((item) => {
      if (!controller.signal.aborted) setSelection({ id, item })
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setSelection({ id, error: reason instanceof OpportunityNeedUnavailableError
        ? 'This opportunity is unavailable, deleted, or no longer eligible for opportunity views. Retained evidence may still be available in the ingestion inbox.'
        : reason instanceof Error ? reason.message : 'Could not load the selected opportunity.' })
    })
    return () => controller.abort()
  }, [scene.needId, revision])
  useEffect(() => {
    if (!scene.needId) return
    const controller = new AbortController()
    client.opportunityNeed(scene.needId, { tier: scene.tier.slice(0, -1), search: scene.search, decision: 'ALL', filters: { industry: scene.lens } }, controller.signal)
      .then(() => { if (!controller.signal.aborted) setMembership({ key: selectionKey, outside: false }) })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setMembership(reason instanceof OpportunityNeedUnavailableError
          ? { key: selectionKey, outside: true }
          : { key: selectionKey, error: reason instanceof Error ? reason.message : 'Could not check filters.' })
      })
    return () => controller.abort()
  }, [selectionKey, revision])

  useEffect(() => {
    const controller = new AbortController()
    if (scene.mode === 'browse' || scene.mode === 'pursuits') {
      setPage(null)
      setPageKey('')
      setLoading(false)
      setError('')
      return () => controller.abort()
    }
    setLoading(true)
    setPage(null)
    setError('')
    client.opportunityMapWindow(scene.tier.slice(0, -1), scene.search, { industry: scene.lens }, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return
        setPage(result)
        setPageKey(filterKey)
        setLensOptions((current) => [...new Set([...current, ...result.items.map((item) => item.asset_type).filter((value): value is string => Boolean(value))])].sort())
      })
      .catch((reason: unknown) => { if (!controller.signal.aborted) { setPageKey(filterKey); setError(reason instanceof Error ? reason.message : 'Opportunities are unavailable.') } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [scene.mode, scene.tier, scene.lens, scene.search, revision])

  useEffect(() => {
    client.health().then((result) => {
      const enabled = result.sources.filter((source) => source.enabled)
      setHealth({ ok: enabled.filter((source) => source.status === 'Updated' || source.status === 'Checked—No Change').length, total: enabled.length })
    }).catch(() => setHealth(null))
  }, [])

  // The API already orders by rank; this keeps rank order if records arrive without it.
  const items = useMemo(
    () => [...(pageKey === filterKey ? page?.items ?? [] : [])].sort((a, b) => (b.rank_score ?? -1) - (a.rank_score ?? -1)),
    [page, pageKey, filterKey],
  )
  const byState = useMemo(() => {
    const groups = new Map<string, Opportunity[]>()
    for (const item of items) {
      const key = stateOf(item.location) ?? UNMAPPED
      groups.set(key, [...(groups.get(key) ?? []), item])
    }
    return groups
  }, [items])
  const subject = selection.id === scene.needId ? selection.item ?? null : null
  const selectionError = selection.id === scene.needId ? selection.error : undefined
  // Featured = highest rank among loaded records; falls back to the newest record.
  const featured = items.reduce<Opportunity | null>(
    (best, item) => (best === null || (item.rank_score ?? -1) > (best.rank_score ?? -1) ? item : best),
    null,
  )
  const subjectState = subject ? stateOf(subject.location) : scene.state
  const collection = scene.mode === 'browse' || scene.mode === 'pursuits'
  const inFocus = scene.mode !== 'nation' && scene.mode !== 'state'
  const selectedFocus = inFocus && !collection
  const stateItems = scene.state ? byState.get(scene.state) ?? [] : []
  const mappedStates = [...byState.keys()].filter((key) => key !== UNMAPPED).length
  const unmapped = byState.get(UNMAPPED)?.length ?? 0

  const zoom = (() => {
    const box = scene.mode === 'state' && scene.state && bounds.get(scene.state)
    if (!box) return 'translate(0px,0px) scale(1)'
    const [[x0, y0], [x1, y1]] = box
    const scale = Math.min(6, 0.7 / Math.max((x1 - x0) / 975, (y1 - y0) / 610))
    return `translate(${487.5 - scale * (x0 + x1) / 2}px,${305 - scale * (y0 + y1) / 2}px) scale(${scale})`
  })()
  const markerScale = (() => {
    const match = zoom.match(/scale\(([\d.]+)\)/)
    return match ? 1 / Number(match[1]) : 1
  })()

  function submitCommand(event: FormEvent) {
    event.preventDefault()
    if (scene.mode === 'pursuits') go({ commercial: { ...commercial, query: draft.trim() } })
    else go({ search: draft.trim(), browseOffset: 0 })
  }
  const back = () => history.back()
  const scope = scene.mode === 'pursuits' ? 'Commercial pursuits' : scene.mode === 'browse' ? 'All records · national' : subject ? projectTitle(subject) : scene.state ?? 'United States'
  const crumbs = scene.mode === 'nation' ? ['United States', 'National perspective']
    : scene.mode === 'state' ? ['Nationwide', scene.state ?? '']
      : collection ? ['Previous view', modeLabel[scene.mode]]
      : [scene.mode === 'project' ? 'Nationwide' : modeLabel[modes[modes.indexOf(scene.mode) - 1] ?? 'project'], modeLabel[scene.mode]]

  const tierNote = scene.tier === 'Signals'
    ? 'A Signal is a reason to investigate, not a qualified power need.'
    : scene.tier === 'Prospects' ? 'Prospects have a supported requirement and a separate supply concern.'
      : 'Leads have evidence for MW range, start window, duration and an unresolved supply gap.'

  return <div className={`env env-${scene.mode}`} onClickCapture={(event) => { if ((event.target as Element).closest('a')) save() }}>
    <header className="env-header">
      <a className="env-brand" href="/" aria-label="GridLens home" onClick={(event) => { event.preventDefault(); go({ mode: 'nation', state: null, needId: null }) }}>
        <img src="/brand/lockup-horizontal-white.svg" alt="GridLens"/>
        <span>Infrastructure Intelligence</span>
      </a>
      <div className="env-menu">
        <button type="button" aria-expanded={menuOpen} aria-controls="env-menu" onClick={() => setMenuOpen((open) => !open)}>Menu</button>
        {menuOpen && <nav id="env-menu" aria-label="Workspace">
          <a href={urlFor({ ...scene, mode: 'browse' })} onClick={(event) => { event.preventDefault(); go({ mode: 'browse' }) }}>All records</a>
          <a href={urlFor({ ...scene, mode: 'pursuits' })} onClick={(event) => { event.preventDefault(); go({ mode: 'pursuits' }) }}>Today’s pursuits</a>
          <a href={withEnvironmentReturn(`/?tier=${scene.tier}`)}>Advanced record browser</a>
          <a href="/?view=editorial">Editorial review</a>
          <a href={withEnvironmentReturn("/?view=ingestion")}>Ingestion inbox</a>
          <a href={withEnvironmentReturn("/?view=ingestion&health=1")}>Source health</a>
          <button type="button" onClick={onSignOut}>Sign out</button>
        </nav>}
      </div>
    </header>

    <div className="env-context">
      <button type="button" className="env-back" onClick={back} disabled={scene.depth === 0} aria-label="Back to previous view">
        <span aria-hidden="true">←</span> {crumbs[0]}
      </button>
      <span className="env-crumb">{crumbs[1]}</span>
      {scene.mode !== 'pursuits' ? <div className="env-lens">
        <span>Lens</span>
        <label className="sr-only" htmlFor="env-lens">Industry lens</label>
        <select id="env-lens" value={scene.lens} onChange={(event) => go({ lens: event.target.value, browseOffset: 0 })}>
          <option value="">All sectors</option>
          {[...new Set([...lensOptions, ...(scene.lens ? [scene.lens] : [])])].map((option) => <option key={option} value={option}>{readable(option)}</option>)}
        </select>
        <label className="sr-only" htmlFor="env-tier">Tier</label>
        <select id="env-tier" value={scene.tier} onChange={(event) => go({ tier: event.target.value as TierName, browseOffset: 0 })}>
          {tiers.map((tier) => <option key={tier}>{tier}</option>)}
        </select>
      </div> : <span className="env-meta">Commercial disposition is separate from evidence tier.</span>}
    </div>

    <main className="env-stage">
      <section className="env-subject" aria-live="polite" data-context-loading={collection ? false : selectedFocus ? !subject && !selectionError : loading || pageKey !== filterKey}>
        {error && inFocus && scene.mode !== 'pursuits' && <p role="alert">Map results unavailable: {error} <button onClick={() => setRevision((value) => value + 1)}>Retry opportunities</button></p>}
        {error && !inFocus ? <div role="alert"><h1 ref={headingRef} tabIndex={-1}>Opportunities are unavailable.</h1><p>{error}</p><p>Collected evidence is unaffected. Try again or open source health from the menu.</p><button onClick={() => setRevision((value) => value + 1)}>Retry opportunities</button></div>
          : scene.mode === 'browse' ? <BrowseRecords tier={scene.tier} lens={scene.lens} search={scene.search} offset={scene.browseOffset ?? 0} onPage={(browseOffset) => go({ browseOffset })} onSelect={(item) => go({ mode: 'project', needId: item.id })}/>
          : scene.mode === 'pursuits' ? <CommercialPursuits navigation={commercial} onNavigate={(commercial) => go({ commercial })} onInvestigate={(needId) => go({ mode: 'project', needId })}/>
          : scene.mode === 'nation' ? <>
            <p className="env-eyebrow">See earlier · Predict the power gap</p>
            <h1 ref={headingRef} tabIndex={-1} className="env-display">A wider view.<br/>A sharper focus.</h1>
            <p className="env-lede">{loading ? 'Loading the national picture…' : `${page?.totalCount ?? 0} ${scene.tier.toLowerCase()}${scene.search ? ` matching “${scene.search}”` : ''} · ${mappedStates} states${unmapped ? ` · ${unmapped} unmapped` : ''}. Map geography counts cover the loaded subset.`} {tierNote}</p>
            {featured ? <div className="env-featured">
              <p className="env-eyebrow"><span className="env-dot"/>{featured.rank_score != null ? `Highest rank · ${featured.rank_score}` : 'Most recently updated'} · {featured.tier}</p>
              {featured.rank_reasons && featured.rank_reasons.length > 0 && <p className="env-meta">{featured.rank_reasons.join(' · ')}</p>}
              <h2>{projectTitle(featured)}</h2>
              <p className="env-meta">{featured.location ?? 'Location unknown'} · {readable(featured.activity)}</p>
              <dl className="env-facts env-facts-compact">
                <div><dt>Required power</dt><dd>{known(featured.required_mw)}</dd></div>
                <div><dt>Start</dt><dd>{known(featured.start_window)}</dd></div>
              </dl>
              <button type="button" className="env-go" onClick={() => go({ mode: 'project', needId: featured.id, state: stateOf(featured.location) })}>Explore this pursuit <span aria-hidden="true">→</span></button>
            </div> : !loading && <p className="env-empty">No {scene.tier.toLowerCase()} match this view. Nothing is invented to fill it.</p>}
            {scene.tier === 'Signals' && !scene.search && !scene.lens && today?.(() => go({ mode: 'pursuits' }))}
          </> : scene.mode === 'state' ? <>
            <p className="env-eyebrow">{scene.state} · {stateItems.length} {scene.tier.toLowerCase()} in the loaded subset</p>
            <h1 ref={headingRef} tabIndex={-1}>{scene.state}</h1>
            {stateItems.length ? <ul className="env-list" data-context-scroll="state-results">{stateItems.map((item) => <li key={item.id}>
              <button type="button" data-context-key={`need:${item.id}`} onClick={() => go({ mode: 'project', needId: item.id })}>
                <strong>{projectTitle(item)}</strong><span>{item.location ?? 'Location unknown'} · {readable(item.activity)}</span>
              </button></li>)}</ul>
              : <p className="env-empty">No {scene.tier.toLowerCase()} here in the current view.</p>}
          </> : !subject ? <>
            <h1 ref={headingRef} tabIndex={-1}>{selectionError ? 'Selected opportunity unavailable' : 'Loading selected opportunity…'}</h1>
            {selectionError && <><p role="alert">{selectionError}</p><button onClick={() => setRevision((value) => value + 1)}>Retry selected opportunity</button></>}
          </> : <>
            {membership.key === selectionKey && membership.outside && <aside role="status"><strong>Outside current filters</strong><p>This selected opportunity is retained for context. It is not included in matching results or map counts.</p></aside>}
            {membership.key === selectionKey && membership.error && <p role="alert">Filter membership unavailable: {membership.error} <button onClick={() => setRevision((value) => value + 1)}>Retry filter check</button></p>}
            <Focus key={subject.id} mode={scene.mode} item={subject} stateName={subjectState} headingRef={headingRef} go={go} onReadback={() => setRevision((value) => value + 1)}/>
          </>}

      </section>

      <section className={`env-map${inFocus ? ' env-map-recede' : ''}`} aria-label="United States map of current results" inert={inFocus}>
        <svg viewBox="0 0 975 610" role="img" aria-label={`${mappedStates} states with ${scene.tier.toLowerCase()} in this view`}>
          <g style={{ transform: zoom }} className="env-map-layer">
            {states.features.map((f) => <path key={f.properties.name} d={path(f) ?? ''}
              className={`env-state${byState.has(f.properties.name) ? ' env-state-has' : ''}${subjectState === f.properties.name ? ' env-state-on' : ''}`}/>)}
            {[...byState.entries()].filter(([name]) => name !== UNMAPPED && centroids.has(name)).map(([name, group]) => {
              const [x, y] = centroids.get(name) ?? [0, 0]
              const on = subjectState === name
              return <g key={name} transform={`translate(${x},${y}) scale(${markerScale})`} className={`env-marker${on ? ' env-marker-on' : ''}`}>
                <rect x={-5} y={-5} width={10} height={10} transform="rotate(45)"/>
                {on && <circle r={16}/>}
                <text x={10} y={4}>{name} · {group.length}</text>
              </g>
            })}
          </g>
        </svg>
        <div className="env-map-keys">
          {[...byState.entries()].filter(([name]) => name !== UNMAPPED).sort((a, b) => b[1].length - a[1].length).map(([name, group]) =>
            <button key={name} type="button" aria-pressed={scene.state === name} onClick={() => go({ mode: 'state', state: name, needId: null })}>{name} <span>{group.length}</span></button>)}
          {unmapped > 0 && <button type="button" onClick={() => go({ mode: 'state', state: UNMAPPED, needId: null })}>No mappable state <span>{unmapped}</span></button>}
        </div>
        <p className="env-map-note">Markers are counts per state from the loaded matching subset, not load, confidence or coverage. National scope is not a claim of complete source coverage.{page?.isSubset ? ` Showing the ${page.loadedCount} highest-ranked of ${page.totalCount}.` : ''}</p>
      </section>
    </main>

    <form className="env-command" onSubmit={submitCommand} role="search">
      <span className="env-scope"><span className="env-dot"/>{scope}</span>
      <label className="sr-only" htmlFor="env-search">{scene.mode === 'pursuits' ? 'Search commercial pursuits on this page' : 'Search projects, companies or places'}</label>
      <input id="env-search" value={draft} onChange={(event) => setDraft(event.target.value)} placeholder={scene.mode === 'pursuits' ? 'Search this commercial page…' : 'Search a project, company, city or permit ID…'}/>
      {(scene.mode === 'pursuits' ? commercial.query : scene.search) && <button type="button" className="env-clear" onClick={() => { setDraft(''); scene.mode === 'pursuits' ? go({ commercial: { ...commercial, query: '' } }) : go({ search: '', browseOffset: 0 }) }}>Clear</button>}
      <button type="submit" aria-label="Search">→</button>
    </form>
    <footer className="env-footer">
      <span>{collection ? modeLabel[scene.mode] : `${String(modes.indexOf(scene.mode) + 1).padStart(2, '0')} / ${modeLabel[scene.mode]}`}</span>
      <span>{health ? `${health.ok}/${health.total} sources healthy` : 'Source health unavailable'}</span>
    </footer>
  </div>
}

function Focus({ mode, item, stateName, headingRef, go, onReadback }: {
  mode: Mode; item: Opportunity; stateName: string | null
  headingRef: React.RefObject<HTMLHeadingElement | null>; go: (next: Partial<Scene>) => void
  onReadback: () => void
}) {
  const [factRevision, setFactRevision] = useState(0)
  const missing = item.missing_facts ?? []
  const prompt: Partial<Record<Mode, string>> = {
    project: item.assessment_reason ?? item.rationale,
    power: 'What does the evidence actually establish — and what is still unknown?',
    evidence: 'Keep the claim. Unfold the sources. Preserve the uncertainty.',
    buyers: 'The responsibility is the question. Involvement is not buying authority.',
    action: 'One specific question. Everything you need stays in view.',
  }
  return <>
    <p className="env-eyebrow"><span className="env-dot"/>{[stateName ?? 'Location unknown', readable(item.activity), item.tier].join(' / ')}</p>
    <h1 ref={headingRef} tabIndex={-1}>{projectTitle(item)}</h1>
    <p className="env-meta">{item.location ?? 'Location unknown'}{item.title_company_role ? ` · ${readable(item.title_company_role)}` : ''}</p>
    {item.rank_score != null && <p className="env-rank" title={`Ranking ${item.rank_version ?? ''}: published weights. Not a probability or confidence.`}>Rank {item.rank_score}/100{item.rank_reasons?.length ? ` · ${item.rank_reasons.join(' · ')}` : ''}</p>}
    {item.signal_evidence_state === 'source_listing_absent' && <p role="status" className="env-review">Status review needed: this filing is no longer in the source's current listing. It may have been issued, denied or withdrawn; its evidence is retained.</p>}
    <p className="env-lede">{prompt[mode]}</p>

    {(mode === 'project' || mode === 'power') && <dl className="env-facts">
      <div><dt>Required power</dt><dd>{known(item.required_mw)}</dd><small>{item.required_mw ? 'Activity-specific, not campus size.' : 'Not established by evidence.'}</small></div>
      <div><dt>Start window</dt><dd>{known(item.start_window)}</dd></div>
      <div><dt>Duration</dt><dd>{known(item.duration)}</dd></div>
      <div><dt>Suitable supply</dt><dd>{item.supply}</dd></div>
    </dl>}

    {mode === 'project' && <ol className="env-steps">
      <li><button type="button" onClick={() => go({ mode: 'power' })}><span>01</span>Follow the power need</button></li>
      <li><button type="button" onClick={() => go({ mode: 'evidence' })}><span>02</span>Reveal the evidence <em>{item.evidence.length}</em></button></li>
      <li><button type="button" onClick={() => go({ mode: 'buyers' })} disabled={!item.project_id}><span>03</span>Find the buying path</button></li>
      <li><button type="button" onClick={() => go({ mode: 'action' })}><span>04</span>Prepare the call</button></li>
    </ol>}

    {mode === 'power' && <>
      {item.time_to_power_window && <p className="env-note">Lifecycle estimate: {item.time_to_power_window}. Derived, not a reported date.</p>}
      {item.demand_quote && <blockquote>{item.demand_quote}</blockquote>}
      {item.supply_quote && <blockquote>{item.supply_quote}</blockquote>}
      <h2 className="env-h2">Still needed to qualify</h2>
      {missing.length ? <ul className="env-checklist">{missing.map((fact) => <li key={fact}>{fact}</li>)}</ul> : <p>No missing facts recorded.</p>}
      <button type="button" className="env-go" onClick={() => go({ mode: 'evidence' })}>Unfold the evidence <span aria-hidden="true">→</span></button>
    </>}

    {mode === 'evidence' && <>
      <div className="env-evidence">{item.evidence.map((evidence) => <article key={`${evidence.document_number}-${evidence.content_hash}`}>
        <p className="env-eyebrow">{evidence.source_id} · {evidenceDate(evidence)}</p>
        <h3><a href={evidence.url} target="_blank" rel="noreferrer">{evidence.title}</a></h3>
        <p>{(evidence.abstract ?? 'No abstract provided by the source.').slice(0, 420)}</p>
        <small>{evidence.extraction_location} · retrieved {new Date(evidence.retrieved_at).toLocaleDateString()} · {evidence.content_hash.slice(0, 12)}</small>
      </article>)}</div>
      <p className="env-note">Conflicts: {item.conflict_state}. A reason to investigate is not proof of a rental need.</p>
      <button type="button" className="env-go" onClick={() => go({ mode: 'buyers' })} disabled={!item.project_id}>Follow the buying path <span aria-hidden="true">→</span></button>
    </>}

    {mode === 'buyers' && <>
      <div className="env-surface">{item.project_id ? <BuyingChain key={item.project_id} projectId={item.project_id}/> : <p>No project identity is linked yet.</p>}</div>
      <p className="env-note">No guessed people. No fabricated contact details. No re-renters.</p>
      <button type="button" className="env-go" onClick={() => go({ mode: 'action' })}>Prepare the call <span aria-hidden="true">→</span></button>
    </>}

    {mode === 'action' && <div className="env-surface env-writing">
      <p className="env-eyebrow">Call brief · nothing is sent</p>
      <h2>Ask the question that moves this forward.</h2>
      <p>{item.next_action}</p>
      {missing.length > 0 && <ol>{missing.slice(0, 4).map((fact) => <li key={fact}>{fact}</li>)}</ol>}
      <QuickCallLog key={`quick-${item.id}`} item={item} onReadback={() => { setFactRevision((value) => value + 1); onReadback() }}/>
      <details className="env-full-facts"><summary>Full fact history, single-fact entry and corrections</summary>
        <FactWorkflowPanel key={`${item.id}-${factRevision}`} item={item} onReadback={onReadback}/>
      </details>
      <a href={withEnvironmentReturn(`/?tier=${item.tier}s#${encodeURIComponent(item.id)}`)}>Open the full record</a>
    </div>}
  </>
}
