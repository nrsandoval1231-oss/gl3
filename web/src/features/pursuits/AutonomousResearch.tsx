import { useEffect, useRef, useState } from 'react'
import { client, type AutonomousResearch as ResearchResponse, type ResearchQuestion, type ResearchRoute } from '../../api/client'

const active = (question: ResearchQuestion) => ['QUEUED', 'SEARCHING', 'REVIEWING_EVIDENCE'].includes(question.status)
const date = (value: string | null | undefined) => value ? new Date(value).toLocaleString() : 'Unknown'
const strings = (value: unknown): string[] => Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
const record = (value: unknown): Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
function checked(value: ResearchResponse): ResearchResponse {
  if (!value || !Array.isArray(value.items) || value.items.some((item) => !item || typeof item.id !== 'string' || typeof item.question !== 'string' || typeof item.status !== 'string' || !item.receipt || !item.context)) throw new Error('Research history returned incomplete data. Retry to inspect the saved result.')
  return value
}

const readOnlyRequests = new Map<string, Promise<ResearchResponse>>()
function readOnlyResearch(needId: string): Promise<ResearchResponse> {
  const existing = readOnlyRequests.get(needId)
  if (existing) return existing
  const request = client.autonomousResearch(needId).then(checked)
  readOnlyRequests.set(needId, request)
  void request.finally(() => {
    if (readOnlyRequests.get(needId) === request) readOnlyRequests.delete(needId)
  }).catch(() => undefined)
  return request
}

export function AutonomousResearch({ needId, readOnly = false, readOnlyLabel }: { needId: string; readOnly?: boolean; readOnlyLabel?: string }) {
  const [data, setData] = useState<ResearchResponse | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [reload, setReload] = useState(0)
  const request = useRef<AbortController | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    let timer: number | undefined
    setData(null)
    setError('')
    setBusy(false)
    async function load() {
      try {
        const result = readOnly
          ? await readOnlyResearch(needId)
          : checked(await client.autonomousResearch(needId, controller.signal))
        if (controller.signal.aborted) return
        setData(result)
        setError('')
        if (!readOnly && result.items.some(active)) timer = window.setTimeout(() => void load(), 1600)
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Research status is unavailable.')
      }
    }
    void load()
    return () => { controller.abort(); request.current?.abort(); request.current = null; if (timer !== undefined) window.clearTimeout(timer) }
  }, [needId, readOnly, reload])
  async function refresh() {
    if (request.current) return
    const controller = new AbortController()
    request.current = controller
    setBusy(true)
    try {
      checked(await client.refreshAutonomousResearch(needId, Boolean(data?.items.length), controller.signal))
      if (!controller.signal.aborted) setReload((value) => value + 1)
    } catch (cause) {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Research could not be requested.')
    } finally {
      if (!controller.signal.aborted) { setBusy(false); request.current = null }
    }
  }
  const pending = data?.items.filter(active) ?? []
  return <section className="commercial-action" aria-label="Autonomous pursuit research">
    <h3>Missing facts · autonomous research</h3>
    <p>Bounded public research with evidence admission and deterministic reevaluation. No commercial outreach occurs.</p>
    {readOnly && data && <p>{readOnlyLabel ?? 'Read-only research history for this power need, including attempts after the saved evaluation above.'}</p>}
    {readOnly && !data && error && <p>Later research attempt history is unavailable; status is UNKNOWN. Saved disposition and tier were not rechecked.</p>}
    {error && <p role="alert">{error}</p>}
    {!data && !error && <p role="status">Loading research history…</p>}
    {data && !data.items.length && <p>No autonomous research questions recorded.</p>}
    {pending.length > 0 && <p role="status">{pending.length} active blocker{pending.length === 1 ? '' : 's'} · queued or in progress; no completed result yet.</p>}
    {!readOnly && <button type="button" disabled={busy || pending.length > 0 || !data} onClick={() => void refresh()}>{busy ? 'Requesting research…' : pending.length ? 'Research in progress…' : data?.items.length ? 'Refresh missing facts' : 'Research missing facts'}</button>}
    {!readOnly && error && <button type="button" disabled={busy} onClick={() => setReload((value) => value + 1)}>Retry research status</button>}
    {data?.items.map((question) => <Question key={question.id} question={question}/>)}
  </section>
}

function Question({ question }: { question: ResearchQuestion }) {
  const receipt = question.receipt
  const context = record(question.context)
  const before = record(context.before)
  const facts = Array.isArray(context.known_facts) ? context.known_facts.map(record) : []
  const queries = receipt.queries_generated?.length ? receipt.queries_generated : strings(context.queries)
  return <article className="commercial-note" aria-label={`Research question: ${question.question}`}>
    <h4>{question.question}</h4>
    <p><b>{question.status.replaceAll('_', ' ')}</b> · Attempt {question.attempt_count} · Created {date(question.created_at)}{question.completed_at && ` · Completed ${date(question.completed_at)}`}</p>
    {typeof context.why === 'string' && <p>{context.why}</p>}
    {receipt.error && <p role="alert">{receipt.error}</p>}
    {question.status === 'UNRESOLVED' && <p>Insufficient evidence within this attempt. No result does not establish that the fact is false.</p>}
    <p><b>Reevaluation:</b> {receipt.reevaluation_status?.replaceAll('_', ' ') ?? 'NOT STARTED'}{receipt.before && receipt.after && <> · {receipt.before} → {receipt.after}</>}</p>
    {receipt.reason && <p><b>Why:</b> {receipt.reason}</p>}
    {receipt.next_action && <p><b>Next action:</b> {receipt.next_action}</p>}
    {receipt.tier && <p>Resulting evidence tier: {receipt.tier}</p>}
    {receipt.remaining_blockers?.length ? <><b>Still unknown</b><ul>{receipt.remaining_blockers.map((item, index) => <li key={index}>{item}</li>)}</ul></> : null}
    <details><summary>What GridLens knew before</summary>
      <p>Saved pursuit state: {typeof before.disposition === 'string' ? before.disposition : 'Unknown'} · Evidence tier: {typeof before.tier === 'string' ? before.tier : 'Unknown'}</p>
      {facts.length ? <ul>{facts.map((fact, index) => <li key={index}>{typeof fact.text === 'string' ? fact.text : 'Fact text unavailable'}{typeof fact.evidence_id === 'string' && ` [${fact.evidence_id}]`}</li>)}</ul> : <p>No known facts recorded.</p>}
      <b>Unknown at planning</b><ul>{strings(context.unknowns).map((item, index) => <li key={index}>{item}</li>)}</ul>
    </details>
    <details><summary>Research trail · sources and evidence decisions</summary>
      <Routes title="Planned source routes" routes={question.context.route_plan}/>
      <Routes title="Recorded routing states" routes={receipt.route_results}/>
      <p>Preferred source families: {strings(context.source_families).join(' → ') || 'Not recorded'}</p>
      <b>Queries generated · execution recorded separately</b>{queries?.length ? <ol>{queries.map((query, index) => <li key={index}>{query}</li>)}</ol> : <p>No queries recorded.</p>}
      <b>Queries attempted</b>{receipt.queries_attempted?.length ? <ol>{receipt.queries_attempted.map((query, index) => <li key={index}>{query}</li>)}</ol> : <p>No query attempts recorded.</p>}
      <b>Queries searched successfully</b>{receipt.queries_searched?.length ? <ol>{receipt.queries_searched.map((query, index) => <li key={index}>{query}</li>)}</ol> : <p>No successful searches recorded.</p>}
      <p>Searches executed: {receipt.searches ?? 0} · Retrieval attempts: {receipt.retrieval_attempts ?? 0} · Model calls: {receipt.model_calls ?? 0} · Actual cost: {receipt.cost_usd == null ? 'Unavailable' : `$${receipt.cost_usd}`} · Reserved cost: {receipt.reserved_cost_usd == null ? 'Not recorded' : `$${receipt.reserved_cost_usd}`} · Runtime: {receipt.runtime_seconds == null ? 'Unknown' : `${receipt.runtime_seconds}s`}</p>
      <h4>Sources actually checked</h4>{receipt.source_checks?.length ? <ul>{receipt.source_checks.map((source, index) => <li key={index}>
        <a href={/^https?:\/\//i.test(source.url) ? source.url : undefined} target="_blank" rel="noreferrer">{source.url}</a> · <b>{source.disposition}</b> · {source.label ?? 'Evidence label unknown'}
        {source.evidence_url && source.evidence_url !== source.url && <p>Canonical evidence citation: <a href={/^https?:\/\//i.test(source.evidence_url) ? source.evidence_url : undefined} target="_blank" rel="noreferrer">{source.evidence_url}</a></p>}
        {source.claim_type && <p>Claim type: {source.claim_type === 'project_organization_relationship' ? 'Project organization relationship' : source.claim_type === 'project_activity' ? 'Project activity' : source.claim_type.replaceAll('_', ' ')}</p>}
        <p>Publisher: {source.publisher ?? 'Unknown'} · Extraction location: {source.extraction_location ?? 'Unknown'}</p>
        {source.cache_reused && <p>Cached source result reused.</p>}{source.duplicate && <p>Duplicate evidence avoided.</p>}
        <p>{source.reason}</p>{source.excerpt && <blockquote>{source.excerpt}</blockquote>}
        {source.match_basis && <p>Project match basis: {source.match_basis}</p>}
        <p>Event date: {source.event_date ?? 'Unknown'} · Published: {source.published_at ?? 'Unknown'} · Retrieved: {date(source.retrieved_at)} · Checked: {date(source.checked_at)}{source.evidence_id && ` · Evidence ${source.evidence_id}`}</p>
      </li>)}</ul> : <p>No source checks recorded.</p>}
      {receipt.acquisition_limitations?.length ? <><h4>Research limitations</h4><ul>{receipt.acquisition_limitations.map((item, index) => <li key={index}>{item}</li>)}</ul></> : null}
      <p>Budget: {Object.entries(record(question.budget)).filter(([, value]) => typeof value === 'number' || typeof value === 'string').map(([key, value]) => `${key.replaceAll('_', ' ')}: ${String(value)}`).join(' · ') || 'Not recorded'}</p>
      <p>Next eligible retry: {date(question.retry_after)}</p>
      <p>Question fingerprint: {question.query_fingerprint} · Evidence fingerprint: {question.evidence_fingerprint}</p>
    </details>
  </article>
}

function Routes({ title, routes }: { title: string; routes?: ResearchRoute[] }) {
  return <><h4>{title}</h4>{routes?.length ? <ol>{routes.map((route, index) => <li key={index}>
    {route.kind} · {route.family} · <b>{route.status}</b>{route.source_id && ` · ${route.source_id}`}{route.external_id && ` · ${route.external_id}`}
    {route.query && <p>Query: {route.query}</p>}{route.reason && <p>{route.reason}</p>}{route.url && <a href={/^https?:\/\//i.test(route.url) ? route.url : undefined} target="_blank" rel="noreferrer">Route source</a>}
  </li>)}</ol> : <p>No routes recorded.</p>}<p>A planned route does not establish that a source was checked.</p></>
}
