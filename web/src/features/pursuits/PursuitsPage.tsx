import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { client, type CommercialPursuit, type CommercialPursuitList } from '../../api/client'
import { onPursuitDataEnded } from '../../state/sessionState'
import { PursuitDetail } from './PursuitDetail'
import { contactLine, powerNeed, powerTiming } from './pursuitFormat'
import './pursuits.css'

type Filter = 'all' | 'active' | 'attention'
const FILTERS: { id: Filter; label: string }[] = [{ id: 'all', label: 'All Pursuits' }, { id: 'active', label: 'Active' }, { id: 'attention', label: 'Needs Attention' }]
// Survives unmount so leaving and returning to Pursuits keeps the list scroll.
const savedScroll = { list: 0, window: 0 }
const PAGE_SIZE = 200
const MAX_LIST_ITEMS = 2000

function readRoute() {
  // The URL is the source of truth: no filter in the URL means All.
  const params = new URLSearchParams(location.search), filter = params.get('filter')
  return { filter: (filter === 'active' || filter === 'attention' ? filter : 'all') as Filter, id: params.get('pursuit') ?? '' }
}
function routeUrl(filter: Filter, id: string) {
  const params = new URLSearchParams({ view: 'pursuits' })
  if (filter !== 'all') params.set('filter', filter)
  if (id) params.set('pursuit', id)
  return `/?${params}`
}

export function PursuitsPage() {
  const [route, setRoute] = useState(readRoute)
  const [lists, setLists] = useState<Partial<Record<Filter, CommercialPursuitList>>>({})
  const [ended, setEnded] = useState(false)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  const [more, setMore] = useState<'idle' | 'loading' | 'error'>('idle')
  const listRef = useRef<HTMLDivElement>(null)
  const source = route.filter
  const data = lists[source]

  useEffect(() => {
    const sync = () => setRoute(readRoute())
    addEventListener('popstate', sync); addEventListener('gl3-pursuits-route', sync)
    return () => { removeEventListener('popstate', sync); removeEventListener('gl3-pursuits-route', sync) }
  }, [])
  useEffect(() => {
    const onEnded = () => { setEnded(true); setLists({}); setError(''); setRoute(current => ({ ...current, id: '' })) }
    return onPursuitDataEnded(onEnded)
  }, [])

  useEffect(() => {
    if (ended) return
    const controller = new AbortController()
    setError(''); setMore('idle')
    client.commercialPursuits({ needsAttention: source === 'attention', activeOnly: source === 'active', limit: PAGE_SIZE }, controller.signal)
      .then(list => { if (!controller.signal.aborted) setLists(current => ({ ...current, [source]: list })) })
      .catch(cause => { if (!controller.signal.aborted) setError(cause instanceof Error && cause.message ? cause.message : 'Pursuits are unavailable.') })
    return () => controller.abort()
  }, [source, reload, ended])

  async function loadMore() {
    if (!data || data.next_offset == null || more === 'loading') return
    const filter = source, offset = data.next_offset
    setMore('loading')
    try {
      const list = await client.commercialPursuits({ needsAttention: filter === 'attention', activeOnly: filter === 'active', limit: PAGE_SIZE, offset })
      setLists(current => {
        const base = current[filter]
        if (!base || base.next_offset !== offset) return current
        const seen = new Set(base.items.map(item => item.id))
        return { ...current, [filter]: { ...list, items: [...base.items, ...list.items.filter(item => !seen.has(item.id))] } }
      })
      setMore('idle')
    } catch { setMore('error') }
  }

  const counts = data?.counts ?? lists.all?.counts ?? lists.active?.counts ?? lists.attention?.counts
  const items = data?.items ?? []

  // Restore list position after returning from a detail.
  const hadSelection = useRef(Boolean(route.id))
  useLayoutEffect(() => {
    if (route.id) { hadSelection.current = true; return }
    if (!hadSelection.current && !savedScroll.list && !savedScroll.window) return
    hadSelection.current = false
    if (listRef.current) listRef.current.scrollTop = savedScroll.list
    window.scrollTo(0, savedScroll.window)
  }, [route.id, Boolean(data)])

  const go = (filter: Filter, id: string, replace = false) => {
    history[replace ? 'replaceState' : 'pushState']({ ...history.state }, '', routeUrl(filter, id))
    setRoute({ filter, id })
  }
  const open = (id: string) => {
    savedScroll.list = listRef.current?.scrollTop ?? 0; savedScroll.window = window.scrollY
    go(route.filter, id)
    if (window.matchMedia('(max-width: 900px)').matches) { window.scrollTo(0, 0); requestAnimationFrame(() => document.querySelector<HTMLElement>('.pu-back')?.focus()) }
  }
  const close = () => {
    const id = route.id
    go(route.filter, '')
    requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-pursuit-card="${CSS.escape(id)}"]`)?.focus({ preventScroll: true }))
  }
  const changed = useCallback((updated: CommercialPursuit) => {
    setLists(current => {
      const patch = (list?: CommercialPursuitList) => list && { ...list, items: list.items.map(item => item.id === updated.id ? { ...item, ...updated, tasks: undefined, activity: undefined } : item) }
      return { all: patch(current.all), active: patch(current.active), attention: patch(current.attention) }
    })
    setReload(value => value + 1)
  }, [])

  const activeCount = counts?.active
  return <div className="pu-page" data-has-selection={route.id ? 'true' : 'false'}>
    <header className="pu-heading">
      <h1>Pursuits</h1>
      <p aria-live="polite">{activeCount === undefined ? ' ' : `${activeCount} active pursuit${activeCount === 1 ? '' : 's'}`}</p>
    </header>
    <div className="pu-layout">
      <section className="pu-list-panel" aria-label="Pursuit list">
        <div className="pu-filters" role="group" aria-label="Filter pursuits">
          {FILTERS.map(({ id, label }) => <button key={id} type="button" className="pu-chip" aria-pressed={route.filter === id} onClick={() => { if (id !== route.filter) go(id, route.id, true) }}>
            {label}{id === 'attention' && counts && <><span className="pu-count" data-testid="attention-count" aria-hidden="true">{counts.needs_attention}</span><span className="sr-only">{` ${counts.needs_attention} ${counts.needs_attention === 1 ? 'needs' : 'need'} attention`}</span></>}
          </button>)}
        </div>
        <div className="pu-list" ref={listRef} aria-busy={!data && !error}>
          {ended && <div className="pu-state" role="alert"><p>Your session ended. Sign in again.</p></div>}
          {!ended && error && <div className="pu-state" role="alert"><p>{error}</p><button type="button" className="pu-btn" onClick={() => setReload(value => value + 1)}>Retry</button></div>}
          {!ended && !data && !error && <div className="pu-skeletons" aria-label="Loading pursuits" role="status">{[0, 1, 2].map(index => <div key={index} className="pu-card pu-skeleton" aria-hidden="true"/>)}</div>}
          {data && !items.length && !error && <div className="pu-state"><p>{route.filter === 'attention' ? 'No pursuits need attention right now.' : route.filter === 'active' ? 'No active pursuits.' : 'No pursuits yet. Use Add to Pursuit on an opportunity to start one.'}</p></div>}
          {items.length > 0 && <ul className="pu-cards">{items.map(item => <li key={item.id}>
            <button type="button" className="pu-card" data-pursuit-card={item.id} aria-current={route.id === item.id ? 'true' : undefined} onClick={() => open(item.id)}>
              <span className="pu-card-title">{item.title}</span>
              <span className={`pu-badge pu-stage-${item.stage.toLowerCase()}`}>{item.stage}</span>
              <span className="pu-card-loc">{item.location || 'Location unavailable'}</span>
              <span className="pu-fact"><span className="pu-fact-label">Power Need</span><span className="pu-fact-value">{powerNeed(item.required_mw)}</span></span>
              <span className="pu-fact"><span className="pu-fact-label">Power timing</span><span className="pu-fact-value">{powerTiming(item.start_window)}</span></span>
              <span className="pu-fact"><span className="pu-fact-label">Contact</span><span className="pu-fact-value">{contactLine(item)}</span></span>
              {item.attention_labels.length > 0 && <span className="pu-attention">{item.attention_labels.map(label => <span key={label} className="pu-attn-chip">{label}</span>)}</span>}
              <span className="pu-arrow" aria-hidden="true">›</span>
            </button>
          </li>)}</ul>}
          {data && data.has_more && <div className="pu-more">
            <p role="status">Showing {items.length} of {data.total_matching ?? 'more'}{items.length >= MAX_LIST_ITEMS ? '. Use Active or Needs Attention to narrow the list.' : ''}</p>
            {items.length < MAX_LIST_ITEMS && <button type="button" className="pu-btn" disabled={more === 'loading'} aria-busy={more === 'loading'} onClick={() => void loadMore()}>{more === 'loading' ? 'Loading…' : 'Load more'}</button>}
            {more === 'error' && <p role="alert">More pursuits could not be loaded. Try again.</p>}
          </div>}
        </div>
      </section>
      <section className="pu-detail-panel" aria-label="Pursuit detail">
        {ended
          ? <div className="pu-state pu-placeholder"><p>Your session ended. Sign in again.</p></div>
          : route.id
          ? <PursuitDetail key={route.id} id={route.id} preview={(lists.all?.items ?? lists.active?.items ?? lists.attention?.items ?? []).find(item => item.id === route.id)} onBack={close} onChanged={changed}/>
          : <div className="pu-state pu-placeholder"><p>Select a pursuit to see its contact, status, follow-ups and activity.</p></div>}
      </section>
    </div>
  </div>
}
