import { useState } from 'react'
import { client, type Opportunity } from '../../api/client'
import './intelligence-card.css'

type Card = NonNullable<Opportunity['intelligence_card']>

export function IntelligenceCard({ card, onReadback, onReview }: {
  card: Card; onReadback: () => void; onReview: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  async function research() {
    setBusy(true); setMessage('')
    try {
      const result = await client.refreshAutonomousResearch(card.need_id, false, undefined, true)
      setMessage(result.items.length ? 'Targeted research queued. Results appear after the worker completes.' : 'No new work queued. Existing work, freshness and budget limits still apply.')
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Research request failed.') }
    finally { setBusy(false) }
  }
  const known = card.fields.filter(field => field.value !== null)
  const groups = [...new Set(card.research_gaps.map(field => field.research_category ?? 'other'))]
  return <section className="intelligence-card" aria-label="Commercial intelligence card">
    <header className="ic-heading"><div><p className="wh-kicker">Commercial intelligence</p><small>{card.last_intelligence_update ? `Evidence updated ${new Date(card.last_intelligence_update).toLocaleDateString()}` : 'Awaiting a retained evidence update'}</small></div><span>{card.completeness.supported} / {card.completeness.total} fields supported</span></header>
    <p className="ic-completeness">Research completeness is separate from {card.qualification} qualification.</p>
    {(['identity', 'power', 'commercial'] as const).map(section => {
      const fields = known.filter(field => field.section === section)
      return fields.length > 0 && <section key={section} aria-label={section === 'identity' ? 'Customer and project' : section === 'power' ? 'Power opportunity' : 'Commercial assessment'}>
        <h3>{section === 'identity' ? 'Customer & project' : section === 'power' ? 'Power opportunity' : 'Commercial assessment'}</h3>
        <dl className="ic-facts">{fields.map(field => <div key={field.key}><dt>{field.label}</dt><dd>{field.value}</dd><small>{field.status}</small><details><summary>Basis & sources</summary><p>{field.basis}</p>{(field.sources ?? []).map((source, index) => <div key={`${source.reference}-${index}`}><p>{source.url ? <a href={source.url} target="_blank" rel="noreferrer">{source.title}</a> : source.title}{source.source_date ? ` · ${source.source_date}` : ''}</p>{source.passage && <blockquote>{source.passage}</blockquote>}<small>{source.verification_status} · {source.reference}</small></div>)}</details></div>)}</dl>
      </section>
    })}
    {card.power_schedule && <section aria-label="Reported phased power schedule" className="ic-schedule">
      <h3>Reported phased schedule</h3>
      <p>{card.power_schedule.status.replaceAll('_', ' ')} · {card.power_schedule.basis}</p>
      {card.power_schedule.status === 'CONFLICT' && <p role="status">Accepted schedule versions conflict. Review attributed fact history before using a scenario.</p>}
      {(card.power_schedule.supplies ?? []).length > 0 && <section aria-label="Dated supply entries"><h4>Supply dates and type</h4><ul>{(card.power_schedule.supplies ?? []).map((supply) => <li key={supply.supply_id}>
        <strong>{supply.supply_id}</strong> · {supply.source_kind === 'utility_grid' ? 'Utility grid' : supply.source_kind === 'onsite' ? 'On-site generation' : 'Other / unspecified'} · {supply.state.replaceAll('_', ' ')} · {supply.suitability} · {supply.mw_min}–{supply.mw_max} MW · {supply.start_date} to {supply.end_date}
        {supply.service_ready_date && <span> · {supply.source_kind === 'utility_grid' ? 'Reported grid energization' : 'Reported service-ready date'}: {supply.service_ready_date}</span>}
        <small>{supply.date_basis} · {supply.basis}{supply.source_reference ? ` · ${supply.source_reference}` : ''}{supply.state === 'proposed' || supply.state === 'hypothetical' ? ' · scenario date, not committed service' : ''}</small>
      </li>)}</ul></section>}
      {card.power_schedule.segments.length === 0 && <p>No resolved schedule segments are available.</p>}
      {card.power_schedule.segments.length > 0 && <div className="ic-table-scroll"><table>
        <thead><tr><th scope="col">Phase</th><th scope="col">Date range</th><th scope="col">Demand</th><th scope="col">Known suitable supply</th><th scope="col">Scenario residual</th><th scope="col">Basis</th></tr></thead>
        <tbody>{card.power_schedule.segments.map((segment, index) => <tr key={`${segment.phase_id}:${segment.start_date}:${segment.end_date}:${segment.scenario}:${index}`}>
          <th scope="row">{segment.phase_id}{segment.scenario === 'alternative' ? ' · proposed / hypothetical' : ' · current reported'}</th>
          <td>{segment.start_date} to {segment.end_date}</td>
          <td>{segment.demand_min_mw}–{segment.demand_max_mw} MW</td>
          <td>{segment.supply_min_mw == null || segment.supply_max_mw == null ? `Unknown · ${segment.unresolved_reason ?? 'coverage is incomplete'}` : `${segment.supply_min_mw}–${segment.supply_max_mw} MW`}{(segment.unresolved_supply_ids ?? []).length > 0 && <small>Suitability unresolved: {(segment.unresolved_supply_ids ?? []).join(', ')}</small>}</td>
          <td>{segment.residual_min_mw == null || segment.residual_max_mw == null ? 'Unknown' : `${segment.residual_min_mw}–${segment.residual_max_mw} MW scenario`}</td>
          <td>{segment.demand_basis}<small>{(segment.supply_basis ?? []).join(' · ') || 'No dated suitable supply entry'}</small></td>
        </tr>)}</tbody>
      </table></div>}
      <details><summary>Schedule attribution and source</summary><p>{card.power_schedule.basis}</p>{card.power_schedule.fact_refs.map((reference, index) => <p key={`${reference.fact_version_id ?? 'fact'}:${index}`}>{reference.authority ?? 'Authority unknown'} · reported by {reference.reporter_name ?? 'reporter unknown'}{reference.reporter_organization ? `, ${reference.reporter_organization}` : ''}{reference.reporter_role ? ` · ${reference.reporter_role}` : ''} · {reference.source_reference ?? 'No source reference'} · confirmed {reference.confirmed_at ?? 'date unknown'}{reference.source_quote ? ` · “${reference.source_quote}”` : ''}</p>)}</details>
    </section>}
    {card.power_gap && <section className="ic-qualified-gap" aria-label="Current qualified power gap"><h3>Current qualified power gap</h3><p>This separate, server-qualified Lead calculation remains current: {String(card.power_gap.remaining_mw_min ?? card.power_gap.remaining_mw)}–{String(card.power_gap.remaining_mw_max ?? card.power_gap.remaining_mw)} MW.</p><details><summary>Qualification basis</summary><pre>{JSON.stringify(card.power_gap, null, 2)}</pre></details></section>}
    <section aria-label="Customer and buying chain"><h3>Customer & buying chain</h3>
      {card.contacts.map(person => <article className="ic-contact" key={person.claim_id}><strong>{person.name || person.company}</strong><p>{person.name ? `${person.title || person.role} · ${person.company}` : person.role}</p><small>{person.responsibility}. {person.purchasing_authority}.</small><div className="ic-contact-actions">{(person.methods ?? []).map(method => <a key={`${method.kind}:${method.value}`} href={method.href}>{method.kind === 'email' ? 'Email' : 'Call'} {method.value}</a>)}</div>{person.verified_at && <small>Verified {new Date(person.verified_at).toLocaleDateString()}</small>}<details><summary>Relationship evidence</summary>{(person.sources ?? []).map((source, index) => <p key={`${source.reference}-${index}`}><a href={source.url ?? undefined} target="_blank" rel="noreferrer">{source.passage || source.title}</a></p>)}</details></article>)}
      <p className="ic-contact-path">{card.next_contact_path}</p>
    </section>
    <section className="ic-next" aria-label="Intelligence next action"><h3>Next action</h3><p>{card.next_action}</p><button onClick={onReview}>Review or correct evidence</button></section>
    <section aria-label="Research gaps"><div className="ic-heading"><h3>Research gaps</h3><button disabled={busy || !card.research_enabled} onClick={() => void research()}>{busy ? 'Queuing…' : 'Research missing information'}</button></div>
      {!card.research_enabled && <p>Research execution is disabled. Existing evidence remains available.</p>}
      {groups.map(group => { const fields = card.research_gaps.filter(field => (field.research_category ?? 'other') === group); return <details key={group} className="ic-gap"><summary>{fields.map(field => field.label).join(' · ')} <small>{fields.some(field => field.status === 'Conflicting evidence') ? 'Conflicting evidence' : fields.some(field => ['QUEUED', 'SEARCHING', 'REVIEWING_EVIDENCE'].includes(field.research_status ?? '')) ? 'Research running' : 'Needs research'}</small></summary>{fields.map(field => <p key={field.key}><strong>{field.label}:</strong> {field.basis}</p>)}</details> })}
      {message && <div><p role="status">{message}</p><button onClick={onReadback}>Refresh research status</button></div>}
    </section>
    <details className="ic-evidence"><summary>Retained evidence ({card.evidence.length})</summary>{card.evidence.map(source => <article key={source.reference}><a href={source.url ?? undefined} target="_blank" rel="noreferrer">{source.title}</a><p>{source.source_date || 'Source date not established'}</p>{source.passage && <blockquote>{source.passage}</blockquote>}<small>{source.reference} · {source.extraction_method}</small></article>)}</details>
  </section>
}
