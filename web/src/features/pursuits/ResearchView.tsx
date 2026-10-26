import { useEffect, useState } from 'react'
import { client, type WorkspaceNeed, type WorkspacePage } from '../../api/client'
import { projectTitle } from '../opportunities/projectCards'
import { AutonomousResearch } from './AutonomousResearch'
import '../../styles/research.css'

function gapLabel(item: WorkspaceNeed) {
  const value = item.qualified_remaining_gap
  if (!value || typeof value !== 'object') return 'Not established'
  const low = value.remaining_mw_min, high = value.remaining_mw_max
  return typeof low === 'string' && typeof high === 'string' ? `${low}–${high} MW` : 'Not established'
}

function safeContactHref(method: Record<string, string>) {
  if (!method.href || !method.kind) return undefined
  try {
    const { protocol } = new URL(method.href)
    if (method.kind === 'email' && protocol === 'mailto:') return method.href
    if (method.kind === 'phone' && protocol === 'tel:') return method.href
  } catch { /* malformed contact methods remain plain text */ }
  return undefined
}

export function ResearchView() {
  const [page, setPage] = useState<WorkspacePage | null>(null)
  const [selectedId, setSelectedId] = useState(() => new URLSearchParams(location.search).get('researchNeed') ?? '')
  const [search, setSearch] = useState(() => new URLSearchParams(location.search).get('q') ?? '')
  const [offset, setOffset] = useState(0)
  const [reload, setReload] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    setPage(null); setLoading(true); setError('')
    void client.workspace({ search, sort: 'priority', offset, cohort_token: undefined }, controller.signal)
      .then(value => { if (!controller.signal.aborted) setPage(value) })
      .catch((cause: unknown) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Research opportunities are unavailable.') })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [search, offset, reload])

  const items = page?.items ?? []
  const selected = items.find(item => item.id === selectedId)
  const selectedCompany = selected?.intelligence_card?.fields.find(field => field.key === 'customer' && field.value)?.value ?? selected?.commercial_organization ?? selected?.title_company
  const gapLabels = new Set((selected?.intelligence_card?.research_gaps ?? []).map(field => field.label.trim().toLocaleLowerCase()))
  const choose = (id: string) => {
    setSelectedId(id)
    const params = new URLSearchParams(location.search)
    params.set('view', 'pursuits'); params.set('researchNeed', id)
    history.replaceState(history.state, '', `/?${params}`)
  }
  const clearSelection = () => {
    setSelectedId('')
    const params = new URLSearchParams(location.search)
    params.delete('researchNeed')
    history.replaceState(history.state, '', `/?${params}`)
  }
  const changeSearch = (value: string) => {
    setSearch(value); setOffset(0); setPage(null); setSelectedId(''); setLoading(true); setError('')
    const params = new URLSearchParams(location.search)
    params.delete('researchNeed')
    if (value) params.set('q', value); else params.delete('q')
    history.replaceState(history.state, '', `/?${params}`)
  }
  const changeOffset = (value: number) => {
    setOffset(value); setPage(null); setSelectedId(''); setLoading(true); setError('')
    const params = new URLSearchParams(location.search)
    params.delete('researchNeed')
    history.replaceState(history.state, '', `/?${params}`)
  }

  return <main className={`research-view ${selected ? 'has-selection' : ''}`} aria-label="Automated research">
    <section className="research-list" aria-label="Research opportunities">
      <header><div><p className="wh-kicker">Autonomous intelligence</p><h1>Research</h1><p>Source-backed research progress, verified buying contacts and known gaps across current opportunities.</p></div></header>
      <label className="research-search">Search opportunities<input aria-label="Search research opportunities" value={search} onChange={event => changeSearch(event.target.value)} placeholder="Company, project or location"/></label>
      {error && <p role="alert">{error} <button onClick={() => setReload(value => value + 1)}>Retry</button></p>}
      {loading && <p role="status">Loading current opportunities…</p>}
      {!loading && !error && items.length === 0 && <p>No opportunities match this search.</p>}
      <ul className="research-opportunity-list">{items.map(item => {
        const title = projectTitle(item)
        const company = item.intelligence_card?.fields.find(field => field.key === 'customer' && field.value)?.value ?? item.title_company ?? 'Company unknown'
        const freshness = item.intelligence_card?.last_intelligence_update
        return <li key={item.id}><button type="button" aria-current={selectedId === item.id ? 'true' : undefined} onClick={() => choose(item.id)}>
          <span className="research-row-heading"><strong>{company}</strong><span>{item.rank_score == null ? 'Priority unavailable' : `Priority ${item.rank_score}`}</span></span>
          <span>{title}</span><small>{item.location ?? 'Location unknown'} · {item.activity.replaceAll('-', ' ')} · {gapLabel(item)}</small>
          <small>{freshness ? `Research updated ${new Date(freshness).toLocaleDateString()}` : 'Research freshness unknown'} · Confidence: not provided</small>
        </button></li>
      })}</ul>
      <footer><span>{page ? `${page.offset + 1}–${page.offset + items.length} of ${page.total}` : '—'}</span><button disabled={!page?.offset || loading} onClick={() => changeOffset(Math.max(0, offset - 25))}>Previous</button><button disabled={!page?.next_offset || loading} onClick={() => changeOffset(page?.next_offset ?? 0)}>Next</button></footer>
    </section>
    <section className="research-detail" aria-label="Selected automated research">
      {selected ? <>
        <button className="research-back" type="button" onClick={clearSelection}>Back to opportunities</button>
        <div className="research-detail-heading"><p className="wh-kicker">{selected.location ?? 'Location unknown'}</p><h2>{selected.intelligence_card?.fields.find(field => field.key === 'project' && field.value)?.value ?? projectTitle(selected)}</h2><p><strong>Company:</strong> {selectedCompany ?? 'Unknown'}</p><p>{selected.activity.replaceAll('-', ' ')} · {gapLabel(selected)} potential remaining gap · {selected.start_window ?? 'Timing unknown'} · {selected.duration ?? 'Duration unknown'}</p>
          <dl><div><dt>Priority</dt><dd>{selected.rank_score == null ? 'Not available' : selected.rank_score}</dd></div><div><dt>Confidence</dt><dd>Not provided</dd></div><div><dt>Last intelligence update</dt><dd>{selected.intelligence_card?.last_intelligence_update ? new Date(selected.intelligence_card.last_intelligence_update).toLocaleString() : 'Unknown'}</dd></div></dl>
        </div>
        <section className="research-contacts"><h3>Business contacts</h3>
          {(selected.intelligence_card?.contacts ?? []).length ? selected.intelligence_card!.contacts.map(contact => <article key={contact.claim_id}><strong>{contact.name ?? contact.company}</strong><p>{contact.title ?? contact.role} · {contact.responsibility} · {contact.purchasing_authority}</p>{(contact.methods ?? []).map((method, index) => <p key={`${method.kind}-${index}`}>{method.kind}: {safeContactHref(method) ? <a href={safeContactHref(method)}>{method.value}</a> : method.value}</p>)}<p>Source checked {contact.verified_at ? new Date(contact.verified_at).toLocaleDateString() : 'date unknown'}</p>{(contact.sources ?? []).map((source, index) => <p key={index}><a href={source.url ?? undefined} target="_blank" rel="noreferrer">{source.title}</a> · {source.verification_status} · {source.source_date ?? 'Source date unknown'}</p>)}</article>) : <p>No source-backed business contact is currently available. Buyer identity and contact methods remain unknown.</p>}
        </section>
        <section className="research-gaps"><h3>Unknowns and open research gaps</h3>{(selected.intelligence_card?.research_gaps ?? []).length ? <ul>{selected.intelligence_card!.research_gaps.map(field => <li key={field.key}><strong>{field.label}:</strong> {field.value ?? 'Unknown'} · {field.status}. {field.basis}</li>)}</ul> : <p>No explicit research gaps are available.</p>}{(selected.missing_facts ?? []).filter(value => !gapLabels.has(value.trim().toLocaleLowerCase())).length > 0 && <ul>{(selected.missing_facts ?? []).filter(value => !gapLabels.has(value.trim().toLocaleLowerCase())).map(value => <li key={value}>{value}</li>)}</ul>}</section>
        <AutonomousResearch key={selected.id} needId={selected.id}/>
      </> : <div className="research-empty"><h2>Select an opportunity</h2><p>Research history and contact evidence are shown for the selected opportunity. No status, timing, gap, or contact is inferred when evidence is missing.</p></div>}
    </section>
  </main>
}
