import { useState } from 'react'
import type { ResearchOverview } from '../../api/client'
import './ResearchChanges.css'
import { AutonomousResearch } from './AutonomousResearch'

export function ResearchChanges({ overview }: { overview?: ResearchOverview | null }) {
  const [selected, setSelected] = useState<string | null>(null)
  const counts = overview?.summary.blocker_statuses ?? {}
  return <section className="commercial-history research-changes" aria-label="Research-related changes">
    <h2>Research-related changes</h2>
    {!overview ? <p>Research change history is unavailable in this response.</p> : <>
      <p>{overview.since ? `Since ${new Date(overview.since).toLocaleString()}` : 'All retained research history'} · {overview.summary.blockers_attempted} blockers attempted · {counts.RESOLVED ?? 0} resolved · {counts.PARTIALLY_RESOLVED ?? 0} partially resolved · {counts.UNRESOLVED ?? 0} unresolved · {counts.FAILED ?? 0} failed · {counts.BUDGET_EXCEEDED ?? 0} budget exceeded</p>
      <p>Each entry is one saved evaluation linked to a completed research attempt. Commercial state and evidence tier remain separate.</p>
      {!overview.items?.length && <p>No research-linked evaluation changes recorded in this time window.</p>}
      {overview.items?.map((change) => <article className="commercial-history-card" key={change.id}>
        <h3>{change.name}</h3>
        <p><b>{change.before} → {change.after}</b> · Version {change.version} · {change.evaluated_at ? new Date(change.evaluated_at).toLocaleString() : 'Evaluation date unknown'}</p>
        <p>Evidence tier: {change.before_tier ?? 'Unknown'} → {change.after_tier ?? 'Unknown'}</p>
        {change.reason && <p><b>Why:</b> {change.reason}</p>}
        {change.new_evidence?.length ? <><b>New evidence in this evaluation</b><ul>{change.new_evidence.map((evidence, index) => <li key={`${evidence.evidence_id}-${index}`}>
          {evidence.text ?? 'Claim text unavailable'} · {evidence.date ?? 'Date unknown'}{evidence.url && <> · <a href={/^https?:\/\//i.test(evidence.url) ? evidence.url : undefined} target="_blank" rel="noreferrer">Evidence source</a></>}
        </li>)}</ul></> : <p>No new source citations recorded in this evaluation.</p>}
        {change.next_action && <p><b>Next action:</b> {change.next_action}</p>}
        <div className="commercial-history-tools"><button type="button" aria-expanded={selected === change.id} onClick={() => setSelected(selected === change.id ? null : change.id)}>Inspect research history · {change.name}</button></div>
        {selected === change.id && <AutonomousResearch key={change.need_id} needId={change.need_id} readOnly/>}
      </article>)}
    </>}
  </section>
}
