import type { Opportunity } from '../../api/client'
import './reported-power-schedule.css'

type Schedule = NonNullable<NonNullable<Opportunity['intelligence_card']>['power_schedule']>

export function ReportedPowerSchedule({ schedule }: { schedule: Schedule | null | undefined }) {
  if (!schedule) return <p>No reported phase schedule is available.</p>
  return <section className="reported-power-schedule" aria-label="Reported phased power schedule">
    <h3>Reported phased schedule</h3>
    <p>{schedule.status.replaceAll('_', ' ')} · {schedule.basis}</p>
    {schedule.status === 'CONFLICT' && <p role="status">Accepted schedule versions conflict. Review attributed fact history before using a scenario.</p>}
    {schedule.supplies?.length ? <section aria-label="Dated supply entries"><h4>Supply dates and type</h4><ul>{schedule.supplies.map(supply => <li key={supply.supply_id}>
      <strong>{supply.supply_id}</strong> · {supply.source_kind === 'utility_grid' ? 'Utility grid' : supply.source_kind === 'onsite' ? 'On-site generation' : 'Other / unspecified'} · {supply.state.replaceAll('_', ' ')} · {supply.suitability} · {supply.mw_min}–{supply.mw_max} MW · {supply.start_date} to {supply.end_date}
      {supply.service_ready_date && <span> · {supply.source_kind === 'utility_grid' ? 'Reported grid energization' : 'Reported service-ready date'}: {supply.service_ready_date}</span>}
      <small>{supply.date_basis} · {supply.basis}{supply.source_reference ? ` · ${supply.source_reference}` : ''}{supply.state === 'proposed' || supply.state === 'hypothetical' ? ' · scenario date, not committed service' : ''}</small>
    </li>)}</ul></section> : null}
    {schedule.segments.length === 0 && <p>No resolved schedule segments are available.</p>}
    {schedule.segments.length > 0 && <div className="rps-table-scroll"><table>
      <thead><tr><th scope="col">Phase</th><th scope="col">Date range</th><th scope="col">Demand</th><th scope="col">Known suitable supply</th><th scope="col">Scenario residual</th><th scope="col">Basis</th></tr></thead>
      <tbody>{schedule.segments.map((segment, index) => <tr key={`${segment.phase_id}:${segment.start_date}:${segment.end_date}:${segment.scenario}:${index}`}>
        <th scope="row">{segment.phase_id}{segment.scenario === 'alternative' ? ' · proposed / hypothetical' : ' · current reported'}</th>
        <td>{segment.start_date} to {segment.end_date}</td>
        <td>{segment.demand_min_mw}–{segment.demand_max_mw} MW</td>
        <td>{segment.supply_min_mw == null || segment.supply_max_mw == null ? `Unknown · ${segment.unresolved_reason ?? 'coverage is incomplete'}` : `${segment.supply_min_mw}–${segment.supply_max_mw} MW`}{(segment.unresolved_supply_ids ?? []).length > 0 && <small>Suitability unresolved: {(segment.unresolved_supply_ids ?? []).join(', ')}</small>}</td>
        <td>{segment.residual_min_mw == null || segment.residual_max_mw == null ? 'Unknown' : `${segment.residual_min_mw}–${segment.residual_max_mw} MW scenario`}</td>
        <td>{segment.demand_basis}<small>{(segment.supply_basis ?? []).join(' · ') || 'No dated suitable supply entry'}</small></td>
      </tr>)}</tbody>
    </table></div>}
    <details><summary>Schedule attribution and source</summary><p>{schedule.basis}</p>{schedule.fact_refs.map((reference, index) => <p key={`${reference.fact_version_id ?? 'fact'}:${index}`}>{reference.authority ?? 'Authority unknown'} · reported by {reference.reporter_name ?? 'reporter unknown'}{reference.reporter_organization ? `, ${reference.reporter_organization}` : ''}{reference.reporter_role ? ` · ${reference.reporter_role}` : ''} · {reference.source_reference ?? 'No source reference'} · confirmed {reference.confirmed_at ?? 'date unknown'}{reference.source_quote ? ` · “${reference.source_quote}”` : ''}</p>)}</details>
  </section>
}
