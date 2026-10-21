import { useEffect, useState } from 'react'
import { client, type IngestionItem, type SourceHealth } from '../../api/client'
import { IntelligenceOperations } from './IntelligenceOperations'

const sectors = [
  ['data-centers', 'Data centers'], ['energy-and-utilities', 'Energy & utilities'], ['oil-and-gas', 'Oil & gas'],
  ['industrial-and-manufacturing', 'Industrial & manufacturing'], ['construction-and-facilities', 'Construction & facilities'],
  ['healthcare', 'Healthcare'], ['cannabis', 'Cannabis'], ['mining', 'Mining'], ['infrastructure', 'Infrastructure'],
] as const
const sectorAliases: Record<string, string> = {
  'data centers': 'data-centers',
  utilities: 'energy-and-utilities', energy: 'energy-and-utilities',
  'oil & gas': 'oil-and-gas', 'oil and gas': 'oil-and-gas', oil: 'oil-and-gas',
  manufacturing: 'industrial-and-manufacturing', 'industrial facilities': 'industrial-and-manufacturing',
  construction: 'construction-and-facilities', 'commercial construction': 'construction-and-facilities',
  'commercial facilities': 'construction-and-facilities',
  healthcare: 'healthcare', cannabis: 'cannabis', 'cannabis cultivation': 'cannabis',
  mining: 'mining', infrastructure: 'infrastructure',
}
const canonicalSector = (value: string) => sectorAliases[value.trim().toLowerCase()] ?? value.trim().toLowerCase()
const sourceLabel = (id: string) => {
  const acronyms: Record<string, string> = { ccc: 'CCC', dcd: 'DCD', eis: 'EIS', epd: 'EPD', ma: 'MA', mjbizdaily: 'MJBizDaily', nc: 'NC', ogj: 'OGJ', rrc: 'RRC' }
  return id.split('-').map(part => acronyms[part] ?? `${part[0]?.toUpperCase() ?? ''}${part.slice(1)}`).join(' ')
}

export function OperationsInbox() {
  const [health, setHealth] = useState<Awaited<ReturnType<typeof client.health>> | null>(null)
  const [items, setItems] = useState<IngestionItem[]>([])
  const [total, setTotal] = useState(0)
  const [source, setSource] = useState(() => new URLSearchParams(location.search).get('source') ?? '')
  const [vertical, setVertical] = useState(() => canonicalSector(new URLSearchParams(location.search).get('vertical') ?? ''))
  const [offset, setOffset] = useState(() => Number(new URLSearchParams(location.search).get('offset') ?? 0) || 0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const sourceOptions = (health?.sources ?? []).map(item => ({ id: item.id, label: sourceLabel(item.id) }))
  if (source && !sourceOptions.some(item => item.id === source)) sourceOptions.unshift({ id: source, label: `${sourceLabel(source)} (unavailable)` })
  useEffect(() => {
    const params = new URLSearchParams(location.search)
    const existing = params.get('vertical')
    const canonical = canonicalSector(existing ?? '')
    if (existing && canonical !== existing) { params.set('vertical', canonical); history.replaceState(history.state, '', `/?${params}`) }
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setError('')
    void Promise.all([client.health(), client.ingestion(source, vertical, 25, offset)]).then(([status, page]) => {
      if (controller.signal.aborted) return
      setHealth(status); setItems(page.items); setTotal(page.total)
    }).catch((cause: unknown) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Operations data is unavailable.') })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [source, vertical, offset])
  return <div className="operations-view"><div className="wh-view-heading"><div><p className="wh-kicker">Collection and evidence</p><h1>Operations</h1></div><p>{health ? `${health.backlog} queued jobs · ${health.pending_interpretations} interpretations waiting` : 'Source health unavailable'}</p></div>
    <section className="wh-panel"><h2>Source health</h2>{health?.sources.length ? health.sources.map((item: SourceHealth) => <article className="wh-source-row" key={item.id}><strong>{item.id}</strong><span>{item.status} · {item.enabled ? 'Enabled' : 'Disabled'} · {item.freshness}</span><p>{item.last_attempt ? `Last attempt ${new Date(item.last_attempt).toLocaleString()}` : 'No attempts yet'} · {item.last_success ? `Last success ${new Date(item.last_success).toLocaleString()}` : 'No verified success'} · {item.new_records} new · {item.changed_records} changed · {item.parse_failures} parse failures</p><details><summary>Coverage and collection diagnostics</summary><p>{item.id.endsWith('-building-permits') ? `Latest permit issue date ${item.latest_permit_issue_date ?? item.latest_publication_date ?? 'unknown'} · source publication time unknown · ${item.records_scanned} rows scanned, ${item.permit_accepted} Signals, ${item.permit_rejected} held out` : item.id === 'georgia-air-draft-title-v' ? `Current draft Title V / SIP / synthetic-minor snapshot: ${item.snapshot_item_count ?? item.records_scanned} rows · publication date unknown; application dates retained when stated · latest public-comment deadline ${item.latest_public_comment_deadline ?? 'unknown'} · ${item.permit_accepted} Signals, ${item.permit_rejected} held out · ${item.documents_extracted} narrative/draft PDFs extracted · ${item.unextracted_public_notice_references} public notices retained as unextracted references · ${item.generator_facts} equipment excerpts, ${item.generator_excerpts_omitted} omitted by cap · ${item.missing_application_documents} application documents unavailable` : `Latest publication ${item.latest_publication_date ?? 'unknown'} · ${item.snapshot_item_count ?? item.records_scanned} snapshot items`}</p>{item.snapshot_item_count != null && <p>Latest publisher snapshot: {item.snapshot_item_count} items, {item.snapshot_oldest_publication_date ?? 'unknown'}–{item.snapshot_newest_publication_date ?? 'unknown'}</p>}{item.collection_scope && <p>Collection scope: {item.collection_scope}</p>}{item.coverage_limitation && <p>{item.coverage_limitation}</p>}{item.family === 'construction-permits' && !item.coverage_limitation && <p>Regional city datasets; bounded issue-date and modification windows. No national coverage claim.</p>}<p>PDF evidence {item.pdf_enriched}/{item.pdf_eligible} eligible; {item.pdf_candidates} candidates; skipped {item.pdf_skipped_limit} by limit, {item.pdf_skipped_not_signal} not Signal.</p></details>{item.error && <p role="alert">{item.error}</p>}</article>) : <p>Source health is not yet available.</p>}<IntelligenceOperations/></section>
    <section className="wh-panel"><div className="wh-view-heading"><div><p className="wh-kicker">Preserved observations</p><h2>Ingestion inbox</h2></div><span>{total} matching records</span></div><div className="wh-ops-filters"><label>Publisher/source <select aria-label="Filter by source" value={source} onChange={event => { const value = event.target.value; setSource(value); setOffset(0); const params = new URLSearchParams(location.search); value ? params.set('source', value) : params.delete('source'); params.delete('offset'); history.replaceState(history.state, '', `/?${params}`) }}><option value="">All sources</option>{sourceOptions.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label><label>Source sector <select aria-label="Filter by source sector" value={canonicalSector(vertical)} onChange={event => { const value = event.target.value; setVertical(value); setOffset(0); const params = new URLSearchParams(location.search); value ? params.set('vertical', value) : params.delete('vertical'); params.delete('offset'); history.replaceState(history.state, '', `/?${params}`) }}><option value="">All source sectors</option>{sectors.map(([id, label]) => <option value={id} key={id}>{label}</option>)}</select></label></div>{error && <p role="alert">{error}</p>}{loading && <p role="status">Loading source records…</p>}{!loading && !error && items.length === 0 && <p>No retained source items match these filters.</p>}{items.map(item => <article className="wh-ingestion-row" key={`${item.source_id}-${item.external_id}-${item.content_hash}`}><p className="wh-kicker">{item.source_origin ?? 'Source evidence'} · {item.publisher} · Source tags: {item.verticals.join(', ') || 'none supplied'} · {item.collection_state} · {item.qualification_state}</p><h3><a href={item.citation_url} target="_blank" rel="noreferrer">{item.title}</a></h3><p>{item.excerpt || 'Publisher supplied no short summary.'}</p>{item.permit_status && <p>Permit status: {item.permit_status}</p>}{item.assessment_current && item.assessment_reason && <p>{item.assessment_reason} {item.supported_subject && `Supported subject: ${item.supported_subject}.`}{item.supported_action && ` Action: ${item.supported_action}.`}</p>}{item.demand_quote && <blockquote>{item.demand_quote}</blockquote>}{item.supply_quote && <blockquote>{item.supply_quote}</blockquote>}{(item.reported_power_facts ?? []).length > 0 && <details><summary>Reported power figures</summary><ul>{(item.reported_power_facts ?? []).map((fact, i) => <li key={`${i}-${fact}`}>{fact}</li>)}</ul></details>}<p className="wh-muted">{item.event_date ? `${item.event_date_label ?? 'Source event'} ${item.event_date} · publication date unknown` : item.published_at ? `Published ${item.published_at}` : 'Publication date unknown'} · {item.extraction_location} · First seen {new Date(item.first_seen_at).toLocaleString()} · Latest evidence {new Date(item.latest_evidence_at).toLocaleString()} · Scope: {item.source_scope} · Hash {item.content_hash.slice(0, 16)}</p></article>)}<footer className="wh-paging"><span>Showing {items.length ? offset + 1 : 0}–{offset + items.length} of {total}</span><button disabled={!offset || loading} onClick={() => { const value = Math.max(0, offset - 25); setOffset(value); const params = new URLSearchParams(location.search); value ? params.set('offset', String(value)) : params.delete('offset'); history.replaceState(history.state, '', `/?${params}`) }}>Previous</button><button disabled={offset + items.length >= total || loading} onClick={() => { const value = offset + 25; setOffset(value); const params = new URLSearchParams(location.search); params.set('offset', String(value)); history.replaceState(history.state, '', `/?${params}`) }}>Next</button></footer></section>
  </div>
}
