import { type FormEvent, type ReactNode, useEffect, useMemo, useRef, useState } from 'react'
import { geoPath } from 'd3-geo'
import { feature } from 'topojson-client'
import type { FeatureCollection, Geometry } from 'geojson'
import type { GeometryCollection, Topology } from 'topojson-specification'
import statesTopology from 'us-atlas/states-albers-10m.json'
import { client, type Opportunity, type OpportunityPage } from '../../api/client'
import { projectTitle } from '../opportunities/projectCards'
import { BuyingChain } from '../buyingChain/BuyingChain'
import { FactWorkflowPanel } from '../pursuits/FactWorkflowPanel'
import { stateOf } from './usStates'

const tiers = ['Signals', 'Prospects', 'Leads'] as const
type TierName = typeof tiers[number]
const modes = ['nation', 'state', 'project', 'power', 'evidence', 'buyers', 'action'] as const
type Mode = typeof modes[number]
export type Scene = { mode: Mode; state: string | null; needId: string | null; tier: TierName; lens: string; search: string; depth: number }

const UNMAPPED = 'Unmapped'
const modeLabel: Record<Mode, string> = {
  nation: 'Nationwide', state: 'State', project: 'Project', power: 'Power need',
  evidence: 'Evidence', buyers: 'Buying chain', action: 'Call brief',
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
  }
}
function urlFor(scene: Scene) {
  const query = new URLSearchParams({ view: 'environment' })
  if (scene.mode !== 'nation') query.set('mode', scene.mode)
  if (scene.state) query.set('state', scene.state)
  if (scene.needId) query.set('need', scene.needId)
  if (scene.tier !== 'Signals') query.set('level', scene.tier)
  if (scene.lens) query.set('lens', scene.lens)
  if (scene.search) query.set('q', scene.search)
  return `${location.pathname}?${query.toString()}`
}
const readable = (value: string | null | undefined) => (value ?? '').replaceAll('_', ' ').replaceAll('-', ' ')
const known = (value: string | number | null | undefined) => value === null || value === undefined || value === '' ? 'Unknown' : String(value)
function evidenceDate(evidence: Opportunity['evidence'][number]) {
  if (evidence.event_date) return `${evidence.event_date_label ?? 'Source event'} ${evidence.event_date}`
  return evidence.published_at ? `Published ${evidence.published_at}` : 'Publication date unknown'
}

// The API serves at most 50 records per page. Load a bounded number of pages for the map.
const PAGE_SIZE = 50
const MAX_PAGES = 4
async function loadPages(scene: Scene, signal: AbortSignal): Promise<OpportunityPage> {
  const filters = { industry: scene.lens }
  const tier = scene.tier.slice(0, -1)
  const first = await client.opportunityPage(tier, scene.search, 'ALL', PAGE_SIZE, 0, undefined, filters, signal)
  let page = first
  const items = [...first.items]
  for (let n = 1; n < MAX_PAGES && page.nextOffset != null; n += 1) {
    page = await client.opportunityPage(tier, scene.search, 'ALL', PAGE_SIZE, page.nextOffset, first.cohortToken, filters, signal)
    items.push(...page.items)
  }
  return { ...first, items }
}

export function Environment({ onSignOut, today }: { onSignOut: () => void; today?: ReactNode }) {
  const [scene, setScene] = useState<Scene>(() => sceneFromUrl(new URLSearchParams(location.search)))
  const [page, setPage] = useState<OpportunityPage | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [lensOptions, setLensOptions] = useState<string[]>([])
  const [health, setHealth] = useState<{ ok: number; total: number } | null>(null)
  const [draft, setDraft] = useState(scene.search)
  const [menuOpen, setMenuOpen] = useState(false)
  const [revision, setRevision] = useState(0)
  const headingRef = useRef<HTMLHeadingElement>(null)

  // Back is restoration: every transition is a history entry carrying the full scene.
  useEffect(() => {
    history.replaceState({ gl3env: scene }, '', urlFor(scene))
    const onPop = (event: PopStateEvent) => {
      const restored = (event.state as { gl3env?: Scene } | null)?.gl3env ?? sceneFromUrl(new URLSearchParams(location.search))
      setScene(restored)
      setDraft(restored.search)
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  function go(next: Partial<Scene>) {
    const merged = { ...scene, ...next, depth: scene.depth + 1 }
    history.pushState({ gl3env: merged }, '', urlFor(merged))
    setScene(merged)
  }
  useEffect(() => { headingRef.current?.focus({ preventScroll: true }) }, [scene.mode, scene.needId, scene.state])

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError('')
    loadPages(scene, controller.signal)
      .then((result) => {
        setPage(result)
        setLensOptions((current) => [...new Set([...current, ...result.items.map((item) => item.asset_type).filter((value): value is string => Boolean(value))])].sort())
      })
      .catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Opportunities are unavailable.') })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [scene.tier, scene.lens, scene.search, revision])

  useEffect(() => {
    client.health().then((result) => {
      const enabled = result.sources.filter((source) => source.enabled)
      setHealth({ ok: enabled.filter((source) => source.status === 'Updated' || source.status === 'Checked—No Change').length, total: enabled.length })
    }).catch(() => setHealth(null))
  }, [])

  const items = useMemo(() => page?.items ?? [], [page])
  const byState = useMemo(() => {
    const groups = new Map<string, Opportunity[]>()
    for (const item of items) {
      const key = stateOf(item.location) ?? UNMAPPED
      groups.set(key, [...(groups.get(key) ?? []), item])
    }
    return groups
  }, [items])
  const subject = scene.needId ? items.find((item) => item.id === scene.needId) ?? null : null
  const featured = items[0] ?? null
  const subjectState = subject ? stateOf(subject.location) : scene.state
  const inFocus = scene.mode !== 'nation' && scene.mode !== 'state'
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
    go({ search: draft.trim(), mode: 'nation', state: null, needId: null })
  }
  const back = () => history.back()
  const scope = subject ? projectTitle(subject) : scene.state ?? 'United States'
  const crumbs = scene.mode === 'nation' ? ['United States', 'National perspective']
    : scene.mode === 'state' ? ['Nationwide', scene.state ?? '']
      : [scene.mode === 'project' ? 'Nationwide' : modeLabel[modes[modes.indexOf(scene.mode) - 1] ?? 'project'], modeLabel[scene.mode]]

  const tierNote = scene.tier === 'Signals'
    ? 'A Signal is a reason to investigate, not a qualified power need.'
    : scene.tier === 'Prospects' ? 'Prospects have a supported requirement and a separate supply concern.'
      : 'Leads have evidence for MW range, start window, duration and an unresolved supply gap.'

  return <div className={`env env-${scene.mode}`}>
    <header className="env-header">
      <a className="env-brand" href="/" aria-label="GridLens home" onClick={(event) => { event.preventDefault(); go({ mode: 'nation', state: null, needId: null }) }}>
        <img src="/brand/lockup-horizontal-white.svg" alt="GridLens"/>
        <span>Infrastructure Intelligence</span>
      </a>
      <div className="env-menu">
        <button type="button" aria-expanded={menuOpen} aria-controls="env-menu" onClick={() => setMenuOpen((open) => !open)}>Menu</button>
        {menuOpen && <nav id="env-menu" aria-label="Workspace">
          <a href={`/?tier=${scene.tier}`}>All records</a>
          <a href="/?view=pursuits">Today’s pursuits</a>
          <a href="/?view=ingestion">Ingestion inbox</a>
          <button type="button" onClick={onSignOut}>Sign out</button>
        </nav>}
      </div>
    </header>

    <div className="env-context">
      <button type="button" className="env-back" onClick={back} disabled={scene.depth === 0} aria-label="Back to previous view">
        <span aria-hidden="true">←</span> {crumbs[0]}
      </button>
      <span className="env-crumb">{crumbs[1]}</span>
      <div className="env-lens">
        <span>Lens</span>
        <label className="sr-only" htmlFor="env-lens">Industry lens</label>
        <select id="env-lens" value={scene.lens} onChange={(event) => go({ lens: event.target.value, mode: 'nation', state: null, needId: null })}>
          <option value="">All sectors</option>
          {lensOptions.map((option) => <option key={option} value={option}>{readable(option)}</option>)}
        </select>
        <label className="sr-only" htmlFor="env-tier">Tier</label>
        <select id="env-tier" value={scene.tier} onChange={(event) => go({ tier: event.target.value as TierName, mode: 'nation', state: null, needId: null })}>
          {tiers.map((tier) => <option key={tier}>{tier}</option>)}
        </select>
      </div>
    </div>

    <main className="env-stage">
      <section className="env-subject" aria-live="polite">
        {error ? <div role="alert"><h1 ref={headingRef} tabIndex={-1}>Opportunities are unavailable.</h1><p>{error}</p><p>Collected evidence is unaffected. Try again or open source health from the menu.</p></div>
          : scene.mode === 'nation' ? <>
            <p className="env-eyebrow">See earlier · Predict the power gap</p>
            <h1 ref={headingRef} tabIndex={-1} className="env-display">A wider view.<br/>A sharper focus.</h1>
            <p className="env-lede">{loading ? 'Loading the national picture…' : `${page?.totalCount ?? 0} ${scene.tier.toLowerCase()}${scene.search ? ` matching “${scene.search}”` : ''} · ${mappedStates} states${unmapped ? ` · ${unmapped} unmapped` : ''}.`} {tierNote}</p>
            {featured ? <div className="env-featured">
              <p className="env-eyebrow"><span className="env-dot"/>Most recently updated · {featured.tier}</p>
              <h2>{projectTitle(featured)}</h2>
              <p className="env-meta">{featured.location ?? 'Location unknown'} · {readable(featured.activity)}</p>
              <dl className="env-facts env-facts-compact">
                <div><dt>Required power</dt><dd>{known(featured.required_mw)}</dd></div>
                <div><dt>Start</dt><dd>{known(featured.start_window)}</dd></div>
              </dl>
              <button type="button" className="env-go" onClick={() => go({ mode: 'project', needId: featured.id, state: stateOf(featured.location) })}>Explore this pursuit <span aria-hidden="true">→</span></button>
            </div> : !loading && <p className="env-empty">No {scene.tier.toLowerCase()} match this view. Nothing is invented to fill it.</p>}
            {scene.tier === 'Signals' && !scene.search && !scene.lens && today}
          </> : scene.mode === 'state' ? <>
            <p className="env-eyebrow">{scene.state} · {stateItems.length} {scene.tier.toLowerCase()} in this view</p>
            <h1 ref={headingRef} tabIndex={-1}>{scene.state}</h1>
            {stateItems.length ? <ul className="env-list">{stateItems.map((item) => <li key={item.id}>
              <button type="button" onClick={() => go({ mode: 'project', needId: item.id })}>
                <strong>{projectTitle(item)}</strong><span>{item.location ?? 'Location unknown'} · {readable(item.activity)}</span>
              </button></li>)}</ul>
              : <p className="env-empty">No {scene.tier.toLowerCase()} here in the current view.</p>}
          </> : !subject ? <>
            <h1 ref={headingRef} tabIndex={-1}>{loading ? 'Loading…' : 'Outside current filters'}</h1>
            {!loading && <p>This record is not in the current result set. Change the lens or tier, or return to the nation.</p>}
          </> : <Focus mode={scene.mode} item={subject} stateName={subjectState} headingRef={headingRef} go={go} onReadback={() => setRevision((value) => value + 1)}/>}
      </section>

      <section className={`env-map${inFocus ? ' env-map-recede' : ''}`} aria-label="United States map of current results">
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
        <p className="env-map-note">Markers are counts per state from the current results, not load, confidence or coverage. National scope is not a claim of complete source coverage.{page && page.totalCount > items.length ? ` Showing the ${items.length} most recently updated of ${page.totalCount}.` : ''}</p>
      </section>
    </main>

    <form className="env-command" onSubmit={submitCommand} role="search">
      <span className="env-scope"><span className="env-dot"/>{scope}</span>
      <label className="sr-only" htmlFor="env-search">Search projects, companies or places</label>
      <input id="env-search" value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Search a project, company, city or permit ID…"/>
      {scene.search && <button type="button" className="env-clear" onClick={() => { setDraft(''); go({ search: '', mode: 'nation', state: null, needId: null }) }}>Clear</button>}
      <button type="submit" aria-label="Search">→</button>
    </form>
    <footer className="env-footer">
      <span>{String(modes.indexOf(scene.mode) + 1).padStart(2, '0')} / {modeLabel[scene.mode]}</span>
      <span>{health ? `${health.ok}/${health.total} sources healthy` : 'Source health unavailable'}</span>
    </footer>
  </div>
}

function Focus({ mode, item, stateName, headingRef, go, onReadback }: {
  mode: Mode; item: Opportunity; stateName: string | null
  headingRef: React.RefObject<HTMLHeadingElement | null>; go: (next: Partial<Scene>) => void
  onReadback: () => void
}) {
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
      <div className="env-surface">{item.project_id ? <BuyingChain projectId={item.project_id}/> : <p>No project identity is linked yet.</p>}</div>
      <p className="env-note">No guessed people. No fabricated contact details. No re-renters.</p>
      <button type="button" className="env-go" onClick={() => go({ mode: 'action' })}>Prepare the call <span aria-hidden="true">→</span></button>
    </>}

    {mode === 'action' && <div className="env-surface env-writing">
      <p className="env-eyebrow">Call brief · nothing is sent</p>
      <h2>Ask the question that moves this forward.</h2>
      <p>{item.next_action}</p>
      {missing.length > 0 && <ol>{missing.slice(0, 4).map((fact) => <li key={fact}>{fact}</li>)}</ol>}
      <FactWorkflowPanel key={item.id} item={item} onReadback={onReadback}/>
      <a href={`/?tier=${item.tier}s#${encodeURIComponent(item.id)}`}>Open the full record</a>
    </div>}
  </>
}
