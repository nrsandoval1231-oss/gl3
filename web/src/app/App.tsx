import { type FormEvent, useEffect, useRef, useState } from 'react'
import { client, type Opportunity } from '../api/client'

const tiers = ['Signals', 'Prospects', 'Leads'] as const
type Tier = typeof tiers[number]
type Health = Awaited<ReturnType<typeof client.health>>
type Change = Awaited<ReturnType<typeof client.changes>>[number]

function tierValue(tier: Tier) { return tier.slice(0, -1) }
function routeUrl(tier: Tier, search: string, hash = '') {
  const query = new URLSearchParams({ tier, q: search })
  return `${location.pathname}?${query.toString()}${hash}`
}

export function App() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null)
  const [password, setPassword] = useState('')
  const [tier, setTier] = useState<Tier>('Signals')
  const [search, setSearch] = useState('')
  const [items, setItems] = useState<Opportunity[]>([])
  const [selected, setSelected] = useState<Opportunity | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [changes, setChanges] = useState<Change[]>([])
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
  }, [])

  useEffect(() => {
    if (!authenticated) return
    const requestId = ++requestSequence.current
    setLoading(true)
    void Promise.all([
      client.opportunities(tierValue(tier), search),
      client.changes(),
      client.health(),
    ]).then(([opportunities, digest, sourceHealth]) => {
      if (requestId !== requestSequence.current) return
      setItems(opportunities)
      setChanges(digest)
      setHealth(sourceHealth)
      if (selected) setSelected(opportunities.find((item) => item.id === selected.id) ?? null)
      setError('')
    }).catch((cause: unknown) => {
      if (requestId === requestSequence.current) setError(cause instanceof Error ? cause.message : 'GridLens could not load this view.')
    }).finally(() => {
      if (requestId === requestSequence.current) setLoading(false)
    })
    history.replaceState({ ...(history.state ?? {}), tier, search, scrollY: window.scrollY }, '', routeUrl(tier, search, selected ? `#${encodeURIComponent(selected.id)}` : ''))
  }, [authenticated, tier, search])

  useEffect(() => {
    function onPopState(event: PopStateEvent) {
      const state = event.state as { tier?: Tier; search?: string; id?: string; scrollY?: number; focusedId?: string } | null
      if (state?.tier && tiers.includes(state.tier)) setTier(state.tier)
      else setTier('Signals')
      setSearch(state?.search ?? '')
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
    setTier(value)
    setSelected(null)
    history.replaceState({ tier: value, search, scrollY: 0 }, '', routeUrl(value, search))
    window.scrollTo(0, 0)
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
  return <div className="shell">
    <header className="topbar"><a className="brand" href={routeUrl('Signals', '')} aria-label="GridLens home" onClick={(event) => { event.preventDefault(); chooseTier('Signals') }}><img src="/brand/lockup-horizontal-navy.svg" alt="GridLens"/></a><nav aria-label="Opportunity tiers">{tiers.map((name) => <button key={name} className={tier === name ? 'nav-active' : ''} aria-current={tier === name ? 'page' : undefined} onClick={() => chooseTier(name)}>{name}</button>)}</nav><div className="header-actions"><button className="health-toggle" onClick={() => setShowHealth((value) => !value)} aria-expanded={showHealth}>Source health</button><button className="signout" onClick={() => void signOut()}>Sign out</button></div></header>
    <main className="workspace">
      {!selected && <div className="overview-grid"><section className="hero"><div><p className="eyebrow">Evidence-led project discovery</p><h1>{tier}</h1><p>Projects with sourced events that may warrant a power discovery conversation.</p></div></section><section className="today"><div><p className="eyebrow">Today</p><strong>{changes.length} material {changes.length === 1 ? 'change' : 'changes'}</strong></div>{changes.slice(0, 3).map((change, index) => <a href={change.url} key={`${change.kind}-${index}`} target="_blank" rel="noreferrer"><span>{change.kind}</span>{change.title}</a>)}{changes.length === 0 && <span className="today-empty">No material opportunity changes today.</span>}</section></div>}
      {selected && <section className="hero detail-hero"><div><p className="eyebrow">{selected.tier} · {selected.activity.replaceAll('-', ' ')}</p><h1>{selected.name}</h1><p>{selected.rationale}</p></div><button className="back-button" onClick={returnToBrowse}>← Back to {tier}</button></section>}
      {showHealth && <HealthPanel health={health} />}
      <div className="list-toolbar"><div><h2>{selected ? 'Opportunity brief' : `${tier} · ${items.length}`}</h2>{!selected && <p>Browse the evidence and open a project for its source details.</p>}</div><label className="search"><span className="sr-only">Search projects</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search projects"/></label></div>
      {error && <p role="alert" className="error-banner">{error}</p>}
      {loading && <p className="loading-inline" role="status">Updating this view…</p>}
      {selected ? <><OpportunityDetail item={selected}/><div className="detail-navigation"><button disabled={selectedIndex <= 0} onClick={() => moveTo(items[selectedIndex - 1])}>← Previous</button><button disabled={selectedIndex < 0 || selectedIndex >= items.length - 1} onClick={() => moveTo(items[selectedIndex + 1])}>Next →</button></div></> : items.length ? <div className="opportunity-list">{items.map((item) => <button key={item.id} data-opportunity-id={item.id} className="opportunity-row" onClick={() => open(item)}><span className="row-marker"/><span className="row-main"><strong>{item.name}</strong><span>{item.activity.replaceAll('-', ' ')} · {item.location ?? 'Location unknown'}</span><span>{item.rationale}</span><span>{item.evidence[0]?.source_id} · Published {item.evidence[0]?.published_at ?? 'date unknown'}</span></span><span className="row-meta"><span>{item.tier}</span><span>Load unknown</span></span><span className="arrow" aria-hidden="true">→</span></button>)}</div> : !loading ? <div className="empty"><span className="empty-mark" aria-hidden="true">◇</span><h3>{tier === 'Signals' ? 'No signals yet' : `No ${tier.toLowerCase()} yet`}</h3><p>{tier === 'Signals' ? 'A Signal appears when a dated source identifies a concrete project event that may create a reason to investigate power.' : `${tier} require additional supported facts. They will appear here when the evidence meets the qualification gate.`}</p></div> : null}
      </main><footer>Coverage is limited to configured and checked sources. Unknown project facts stay unknown.</footer>
  </div>
}

function HealthPanel({ health }: { health: Health | null }) {
  return <section className="health-panel" aria-label="Source health"><div className="health-heading"><div><p className="eyebrow">Collection status</p><h2>Source health</h2></div><span>{health?.backlog ?? 0} jobs · {health?.pending_interpretations ?? 0} interpretations waiting</span></div>{health?.sources.length ? health.sources.map((source) => <div className="health-row" key={source.id}><strong>{source.id}</strong><span className={`status status-${source.status === 'Failed' ? 'bad' : source.status === 'Overdue' ? 'warn' : 'ok'}`}>{source.status}</span><span>{source.last_attempt ? `Last attempt ${new Date(source.last_attempt).toLocaleString()}` : 'No attempts yet'}<br/>{source.last_success ? `Last success ${new Date(source.last_success).toLocaleString()}` : 'No verified success'}<br/>Latest publication {source.latest_publication_date ?? 'unknown'} · {source.new_records} new · {source.changed_records} changed · {source.parse_failures} parse failures{source.id === 'federal-register-eis' ? <><br/>PDF evidence {source.pdf_enriched}/{source.pdf_eligible} eligible; deferred {source.pdf_skipped_limit}</> : null}</span>{source.error && <span className="error">{source.error}</span>}</div>) : <p>Source health is not yet available.</p>}</section>
}

function OpportunityDetail({ item }: { item: Opportunity }) {
  return <article className="detail"><div className="detail-summary"><div><span className="tier-pill">{item.tier}</span><p className="eyebrow">{item.activity.replaceAll('-', ' ')}</p><h2>{item.name}</h2><p className="location">{item.location ?? 'Location unknown'}</p></div><div className="unknown-grid"><div><span>Required power</span><strong>{item.required_mw ?? 'Unknown'}</strong></div><div><span>Start</span><strong>{item.start_window ?? 'Unknown'}</strong></div><div><span>Duration</span><strong>{item.duration ?? 'Unknown'}</strong></div><div><span>Suitable supply</span><strong>{item.supply}</strong></div></div></div><section className="detail-section"><p className="eyebrow">Why this is a Signal</p><p>{item.rationale}</p><p className="integrity">Power need is not established. A Signal does not imply a power gap.</p></section><section className="detail-section"><p className="eyebrow">Next action</p><p>{item.next_action}</p></section><section className="detail-section"><div className="evidence-heading"><div><p className="eyebrow">Source evidence</p><h3>{item.evidence.length} {item.evidence.length === 1 ? 'record' : 'records'}</h3></div><span>Conflicts: {item.conflict_state}</span></div>{item.evidence.map((evidence) => <div className="evidence" key={`${evidence.document_number}-${evidence.content_hash}`}><h4><a href={evidence.url} target="_blank" rel="noreferrer">{evidence.title}</a></h4><div className="evidence-meta"><span>Published {evidence.published_at}</span><span>Retrieved {new Date(evidence.retrieved_at).toLocaleString()}</span><span>Described event: {evidence.event_date_label}</span><span>{evidence.extraction_location}</span><span>{evidence.source_id} · {evidence.document_number} · {evidence.content_hash.slice(0, 12)}</span></div><p>{evidence.abstract ?? 'No abstract provided by the source.'}</p></div>)}</section><section className="detail-section missing"><h3>Still unknown</h3><ul><li>Project location</li><li>Activity-specific power requirement</li><li>Utility service plan and suitable supply</li><li>Start window and duration</li><li>Responsible buyer or contractor</li></ul></section></article>
}
