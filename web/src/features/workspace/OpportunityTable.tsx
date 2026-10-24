import type { WorkspaceNeed } from '../../api/client'
import { projectTitle } from '../opportunities/projectCards'

// Required demand is not remaining power gap; never substitute one for the other.
export function remainingGap(item: WorkspaceNeed): string {
  const gap = item.qualified_remaining_gap
  if (gap && typeof gap.remaining_mw_min === 'string' && typeof gap.remaining_mw_max === 'string') {
    return `${gap.remaining_mw_min}–${gap.remaining_mw_max} MW`
  }
  const projected = item.intelligence_card?.power_gap?.remaining_mw
  return typeof projected === 'string' && projected.trim() ? projected : 'Not established'
}

export function OpportunityTable({ items, selectedId, onSelect, onAccount }: {
  items: WorkspaceNeed[]; selectedId?: string; onSelect: (item: WorkspaceNeed) => void; onAccount?: (item: WorkspaceNeed) => void
}) {
  return <div className="opportunity-table-wrap"><table className="opportunity-table">
    <caption className="sr-only">Opportunity power needs</caption>
    <thead><tr>{['Company / Project', 'Location', 'Estimated Gap', 'Need Date', 'Confidence', 'Priority', 'Status'].map(label => <th scope="col" key={label}>{label}</th>)}</tr></thead>
    <tbody>{items.map(item => <tr key={item.company_identity_id ?? item.id} className={`wh-queue-item ${selectedId === item.id ? 'selected' : ''}`}>
      <td><div className="opportunity-company"><button className="opportunity-select" data-need-row={item.id} aria-current={selectedId === item.id ? 'true' : undefined} onClick={() => onSelect(item)}>
        <strong>{item.account_name || item.commercial_organization || projectTitle(item)}</strong>
        <span>{projectTitle(item)}</span>
      </button>{onAccount && <button className="opportunity-projects" aria-label={`${item.project_count ?? '—'} projects · ${item.need_count ?? '—'} needs`} onClick={() => onAccount(item)}>{item.project_count ?? '—'} projects</button>}</div></td>
      <td data-label="Location">{item.location || 'Not established'}</td>
      <td data-label="Estimated Gap">{remainingGap(item)}</td>
      <td data-label="Need Date">{item.start_window || 'Not established'}</td>
      <td data-label="Confidence"><span title="The API does not provide a calibrated confidence score. Completeness and qualification are separate.">Unavailable</span></td>
      <td data-label="Priority"><span title="Canonical priority score; not a confidence percentage">{item.rank_score ?? 'Unavailable'}</span></td>
      <td data-label="Status"><span className="wh-queue-meta"><span className="opportunity-status">{item.commercial_disposition || item.workflow_status || 'Unavailable'}</span><span>{item.tier}</span></span></td>
    </tr>)}</tbody>
  </table></div>
}
