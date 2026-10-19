import { useEffect, useState } from 'react'
import { client, type IntelligenceOperations as Operations } from '../../api/client'

const stamp = (value: string | null) => value ? new Date(value).toLocaleString() : 'Unknown'

export function IntelligenceOperations() {
  const [data, setData] = useState<Operations | null>(null)
  const [error, setError] = useState('')
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    void client.intelligenceOperations(controller.signal).then(setData).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Intelligence operations are unavailable.')
    })
    return () => controller.abort()
  }, [open])
  return <details className="intelligence-operations" onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary>Intelligence operations · bounded status</summary>
    {!open && <p>Read-only status for saved jobs, source receipts and recorded provider usage.</p>}
    {open && error && <p role="alert">{error}</p>}
    {open && !data && !error && <p role="status">Loading persisted operations summary…</p>}
    {data && <>
      <p>All time · known cost subtotal {data.providers.known_cost_usd == null ? 'UNKNOWN' : `$${data.providers.known_cost_usd.toFixed(6)}`} across {data.providers.known_cost_calls} measured calls · reserved exposure {data.providers.reserved_cost_usd == null ? `UNKNOWN (known subtotal $${data.providers.reserved_known_subtotal_usd.toFixed(6)})` : `$${data.providers.reserved_cost_usd.toFixed(6)}`} · {data.providers.unknown_cost_calls_all_time} calls with unknown cost · {data.providers.outstanding_uncertain_calls_all_time} unresolved calls. {data.providers.detail_truncated ? `Recent detail capped at ${data.providers.detail_rows_30d} rows.` : ''} Provider completion does not mean a candidate was accepted.</p>
      <p>UTC day {data.providers.utc_day.date} · {data.providers.utc_day.calls} calls · known cost {data.providers.utc_day.known_cost_usd == null ? 'UNKNOWN' : `$${data.providers.utc_day.known_cost_usd.toFixed(6)}`} · reserved exposure {data.providers.utc_day.reserved_cost_usd == null ? `UNKNOWN (known subtotal $${data.providers.utc_day.reserved_known_subtotal_usd.toFixed(6)})` : `$${data.providers.utc_day.reserved_cost_usd.toFixed(6)}`} · unknown cost calls {data.providers.utc_day.unknown_cost_calls} · global daily cap {data.providers.utc_day.daily_budget_limits_calls.global} calls / ${data.providers.utc_day.daily_budget_limits_usd.global.toFixed(2)} · persisted per-scope ledger {data.providers.utc_day.daily_budget_status}</p>
      <p>Reviewed Signals: {data.reviewed_signals ?? 'UNKNOWN'} · independent Leads: {data.independent_leads ?? 'UNKNOWN'} · backup {data.backup} · restore {data.restore} · last verified restore {stamp(data.last_verified_restore_at)} · last reported comparison {stamp(data.last_reported_restore_at)}</p>
      <p>Commercial review receipt: {data.commercial_review_receipt.status} · reported cases {data.commercial_review_receipt.reported_case_count ?? 'UNKNOWN'} · independent labels {data.commercial_review_receipt.independent_labels} · quality {data.commercial_review_receipt.quality_verification} · acceptance {data.commercial_review_receipt.acceptance}{data.commercial_review_receipt.reviewer ? ` · reviewer ${data.commercial_review_receipt.reviewer} · reviewed ${stamp(data.commercial_review_receipt.reviewed_at)}` : ''}</p>
      {data.commercial_review_receipt.status === 'REPORTED' && <><p>Frozen sample SHA-256 {data.commercial_review_receipt.sample_sha256} · context SHA-256 {data.commercial_review_receipt.context_sha256} · reported decisions {Object.entries(data.commercial_review_receipt.decision_counts ?? {}).map(([decision, count]) => `${decision} ${count}`).join(' · ') || 'UNKNOWN'}</p><ul>{data.commercial_review_receipt.cases.map((item) => <li key={item.case_id}>{item.case_id} · need {item.need_id} · {item.decision} · evidence {item.evidence_refs.map((ref) => `${ref.evidence_id} (${ref.content_hash})`).join(', ')}</li>)}</ul></>}
      <h3>Source cycles</h3>
      {data.sources.length ? <ul>{data.sources.map((source) => <li key={source.source_id}><b>{source.source_id}</b> · {source.enabled ? 'enabled' : 'disabled'} · due {source.due_30d}, checked {source.checked_30d}, partial {source.partial_30d}, failed {source.failed_30d}, parse successes {source.parse_success_30d ?? 'UNKNOWN'}, parse failures {source.parse_failures_30d}, freshness {source.freshness_30d} · last attempt {stamp(source.last_attempt_at)} · last good {stamp(source.last_success_at)}{source.last_good_preserved ? ' · previous good data retained' : ' · no verified last-good receipt'}</li>)}</ul> : <p>Source-cycle data is unavailable.</p>}
      <h3>Queue</h3>
      {Object.keys(data.queue.by_kind_status).length ? <ul>{Object.entries(data.queue.by_kind_status).map(([kind, statuses]) => <li key={kind}>{kind}: {Object.entries(statuses).map(([status, count]) => `${status} ${count}`).join(' · ')}</li>)}</ul> : <p>No queue rows were found in the bounded window.</p>}
      <p>Oldest queued job: {stamp(data.queue.oldest_queued_at)} · retried jobs {data.queue.retried_jobs_30d} · failed after three attempts {data.queue.failed_after_three_attempts_30d}</p>
      <h3>Providers</h3>
      <ul>{Object.entries(data.providers.configured).map(([provider, configured]) => <li key={provider}>{provider}: configured {configured ? 'yes' : 'no'} · enabled {data.providers.enabled[provider] ? 'yes' : 'no'}</li>)}</ul>
      {data.providers.by_provider.map((provider) => <div key={provider.provider}><p>{provider.provider} · last 30 days: {provider.called} called · {provider.completed} completed · {provider.failed} failed · accepted {provider.accepted ?? 'UNKNOWN'} · known cost {provider.actual_cost_usd == null ? 'UNKNOWN' : `$${provider.actual_cost_usd.toFixed(6)}`} · reserved {provider.reserved_cost_usd == null ? 'UNKNOWN' : `$${provider.reserved_cost_usd.toFixed(6)}`} · token usage {provider.usage_known_calls ? `measured subtotal ${provider.input_tokens} input / ${provider.output_tokens} output across ${provider.usage_known_calls} calls` : 'UNKNOWN'} · {provider.usage_unknown_calls} calls with unknown token usage · p50 {provider.latency_p50_ms == null ? 'unmeasured' : `${provider.latency_p50_ms} ms`} · p95 {provider.latency_p95_ms == null ? 'unmeasured' : `${provider.latency_p95_ms} ms`}</p>{Object.entries(provider.models).map(([pinned, value]) => { const model = value as { called?: number; completed?: number; actual_models?: Record<string, number> }; return <p key={pinned}>Pinned model {pinned} · {model.called ?? 0} calls / {model.completed ?? 0} completed · actual model {Object.entries(model.actual_models ?? {}).map(([name, count]) => `${name} (${count})`).join(', ') || 'unknown'}</p> })}</div>)}
      <p>Question outcomes: {Object.entries(data.questions.outcomes_30d).map(([outcome, count]) => `${outcome} ${count}`).join(' · ') || 'No measured outcomes'} · material changes {data.material_changes_30d ?? 'UNKNOWN'} · owner notes {data.owner_review_notes_30d}, pending independent review.</p>
    </>}
  </details>
}
