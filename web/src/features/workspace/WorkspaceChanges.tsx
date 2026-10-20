import { useEffect, useRef, useState } from 'react'
import { client, type WorkspaceChanges, type WorkspaceChangeNeed, type WorkspaceHistoricalNeed } from '../../api/client'

const categories = [
  ['discovered', 'New'],
  ['changed', 'Changed'],
  ['promoted', 'Promoted'],
  ['closed', 'Closed'],
  ['review_exception', 'Review exception'],
] as const

export function WorkspaceChanges({ onSelectActiveNeed }: { onSelectActiveNeed: (need: WorkspaceChangeNeed) => void }) {
  const [offset, setOffset] = useState(0)
  const [reload, setReload] = useState(0)
  const [result, setResult] = useState<WorkspaceChanges | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [reviewing, setReviewing] = useState(false)
  const [historyNeedId, setHistoryNeedId] = useState<string | null>(null)
  const [history, setHistory] = useState<WorkspaceHistoricalNeed | null>(null)
  const [historyError, setHistoryError] = useState('')
  const historySequence = useRef(0)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setError(''); setResult(null)
    void client.workspaceChanges(50, offset, controller.signal).then(value => {
      if (!controller.signal.aborted) setResult(value)
    }).catch((failure: Error) => {
      if (!controller.signal.aborted) setError(failure.message)
    }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [offset, reload])

  useEffect(() => {
    if (!historyNeedId) { setHistory(null); setHistoryError(''); return }
    const controller = new AbortController(), sequence = ++historySequence.current
    setHistory(null); setHistoryError('')
    void client.workspaceHistoricalNeed(historyNeedId, controller.signal).then(value => {
      if (!controller.signal.aborted && sequence === historySequence.current) setHistory(value)
    }).catch((failure: Error) => {
      if (!controller.signal.aborted && sequence === historySequence.current) setHistoryError(failure.message)
    })
    return () => controller.abort()
  }, [historyNeedId])

  async function markDisplayedReviewed() {
    if (!result || reviewing) return
    setReviewing(true); setError('')
    try {
      await client.reviewWorkspaceChanges({
        baseline_identity: result.baseline_identity,
        token: result.token,
        limit: result.limit,
        offset: result.offset,
      })
      setReload(value => value + 1)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Could not mark the displayed changes reviewed.')
      setReload(value => value + 1)
    } finally { setReviewing(false) }
  }

  return <section className="wh-changes" aria-label="Material changes">
    <details>
      <summary>Material changes · {loading ? 'Loading' : result?.total_unreviewed ?? 'Unavailable'} unreviewed items</summary>
      <p>Global retained changes · counts are material change items. Reviewing this page leaves source-health exceptions visible.</p>
      {result && <>
        <p>{result.first_use ? 'Changes since tracking began · your first review records the baseline.' : `Since your last review${result.baseline_reviewed_at ? ` · last reviewed ${new Date(result.baseline_reviewed_at).toLocaleString()}` : ''}.`}</p>
        <ul className="wh-change-counts">{categories.map(([category, label]) => <li key={category}>{label}: {result.counts[category]}</li>)}</ul>
      </>}
      {loading && <p role="status">Loading retained material changes…</p>}
      {error && <p role="alert">{error} <button onClick={() => setReload(value => value + 1)}>Reload changes</button></p>}
      {!loading && result?.items.length === 0 && <p>No unreviewed material changes on this page.</p>}
      {result?.items.map(item => <article className="wh-change-item" key={item.event_key}>
        <h3>{item.title}</h3>
        <p><strong>{item.category.replace('_', ' ')}</strong> · Recorded {new Date(item.created_at).toLocaleString()}{item.source_date ? ` · Source date ${item.source_date}` : ''}</p>
        <p>{item.detail}</p>
        {item.needs.length > 0 && <p>Related power needs: {item.needs.map(need => { const context = Object.keys(item.transitions ?? {}).join(', ') || item.fact_type || item.title; return <span key={need.id}><button onClick={() => { if (need.active) onSelectActiveNeed(need); else setHistoryNeedId(need.id) }}>{need.name} · {need.location ?? 'Location unknown'} · {need.active ? context : 'closed historical need'}</button>{' '}</span> })}</p>}
        {item.fact_version_id && <p>{item.decision === 'retracted' ? 'Retracted' : item.decision === 'corrected' ? 'Corrected' : 'Accepted'} {item.fact_type} assertion · version {item.before_version ?? '—'} → {item.after_version ?? '—'} · confirmed {item.confirmed_at ? new Date(item.confirmed_at).toLocaleString() : 'date unknown'} · recorded by {item.actor ?? 'unknown'}{item.reason ? ` · ${item.reason}` : ''}</p>}
        {item.source_reference && <details><summary>Call-record reference</summary><p>{item.source_reference}</p></details>}
        {item.sources.length > 0 && <details><summary>Retained source records</summary>{item.sources.map(source => <p key={`${source.url}:${source.content_hash}`}><a href={source.url} target="_blank" rel="noreferrer">{source.title}</a> · Published {source.published_at ?? 'date unknown'} · Event {source.event_date ?? 'date unknown'} · Retrieved {source.retrieved_at ? new Date(source.retrieved_at).toLocaleString() : 'date unknown'}</p>)}</details>}
        {item.before_state !== null && <details><summary>Preserved before state</summary><pre>{JSON.stringify(item.before_state, null, 2)}</pre></details>}
        {item.after_state !== null && <details><summary>Preserved after state</summary><pre>{JSON.stringify(item.after_state, null, 2)}</pre></details>}
      </article>)}
      {historyNeedId && <section className="wh-historical-need" aria-label="Historical power need">
        <button onClick={() => setHistoryNeedId(null)}>Close historical detail</button>
        {historyError && <p role="alert">{historyError}</p>}
        {!history && !historyError && <p role="status">Loading authenticated historical need…</p>}
        {history && <><h3>{history.name} · {history.activity}</h3><p>{history.location ?? 'Location unknown'} · Inactive historical need · Stored state updated {new Date(history.updated_at).toLocaleString()}</p><p>{history.rationale}</p><p>Required power {history.required_mw ?? 'Unknown'} · Start {history.start_window ?? 'Unknown'} · Duration {history.duration ?? 'Unknown'} · Supply {history.supply}</p>{history.evidence.length > 0 && <details><summary>Preserved historical evidence</summary>{history.evidence.map(evidence => <p key={`${evidence.url}:${evidence.content_hash}`}><a href={evidence.url} target="_blank" rel="noreferrer">{evidence.title}</a> · Published {evidence.published_at ?? 'date unknown'} · Event {evidence.event_date ?? 'date unknown'} · Retrieved {new Date(evidence.retrieved_at).toLocaleString()} · {evidence.content_hash}</p>)}</details>}</>}
      </section>}
      {result?.source_health_exceptions.length ? <section aria-label="Source health exceptions"><h3>Source-health exceptions</h3><ul>{result.source_health_exceptions.map(item => <li key={item.source_id}>{item.source_id} · {item.status}{item.error ? ` · ${item.error}` : ''}{item.parse_failures ? ` · ${item.parse_failures} parse failures` : ''}</li>)}</ul></section> : null}
      {result && <footer className="wh-change-footer"><span>Showing {result.items.length ? result.offset + 1 : 0}–{result.offset + result.items.length} of {result.total_unreviewed} unreviewed</span><button aria-label="Previous changes" disabled={result.offset === 0 || loading} onClick={() => setOffset(Math.max(0, result.offset - result.limit))}>Previous changes</button><button aria-label="Next changes" disabled={result.next_offset === null || loading} onClick={() => setOffset(result.next_offset ?? 0)}>Next changes</button><button disabled={reviewing || loading || result.items.length === 0} onClick={() => void markDisplayedReviewed()}>{reviewing ? 'Saving review…' : 'Mark these displayed changes reviewed'}</button></footer>}
    </details>
  </section>
}
