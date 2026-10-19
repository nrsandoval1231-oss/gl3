import type { Opportunity, WorkspaceNeed } from '../../api/client'
import { BuyingChain } from '../buyingChain/BuyingChain'
import { FactWorkflowPanel } from '../pursuits/FactWorkflowPanel'
import { QuickCallLog } from '../pursuits/QuickCallLog'

export const workspaceTabs = ['Overview', 'Evidence', 'Buying chain', 'Power gap', 'Timeline', 'Next steps', 'Unknowns'] as const
export type WorkspaceTab = typeof workspaceTabs[number]
type WorkspaceDetailItem = Opportunity & Partial<Pick<WorkspaceNeed, 'commercial_disposition' | 'commercial_reason' | 'commercial_next_question' | 'commercial_next_action' | 'commercial_organization'>>
type QualifiedGap = { required_mw_min: string; required_mw_max: string; available_mw_min: string; available_mw_max: string; remaining_mw_min: string; remaining_mw_max: string; start_window: string; duration: string; basis_quote: string; value_kind: string; calculation: string; version: string }
function qualifiedGap(value: WorkspaceDetailItem['qualified_remaining_gap']): QualifiedGap | null {
  if (!value || typeof value !== 'object') return null
  const keys = ['required_mw_min', 'required_mw_max', 'available_mw_min', 'available_mw_max', 'remaining_mw_min', 'remaining_mw_max', 'start_window', 'duration', 'basis_quote', 'value_kind', 'calculation', 'version'] as const
  if (!keys.every(key => typeof value[key] === 'string' && value[key].length > 0)) return null
  return value as QualifiedGap
}

type Props = {
  item: WorkspaceDetailItem | null
  pending: boolean
  loading: boolean
  error: string
  tab: WorkspaceTab
  onTab: (tab: WorkspaceTab) => void
  onBack: () => void
  onRetry: () => void
  onReadback: () => void
}

export function WorkspaceDetail({ item, pending, loading, error, tab, onTab, onBack, onRetry, onReadback }: Props) {
  if (!item) {
    return <aside className="wh-detail wh-empty-detail" aria-label="Opportunity detail">
      <p>{pending || loading ? 'Loading verified opportunity detail…' : 'Select a power need to review its evidence, verified facts, and next action.'}</p>
      {error && <p role="alert">{error} <button onClick={onRetry}>Retry</button></p>}
    </aside>
  }

  const evidence = item.evidence ?? []
  const gap = qualifiedGap(item.qualified_remaining_gap)
  const unknowns = [...new Set([
    ...(item.missing_facts ?? []),
    ...(!item.required_mw ? ['Activity-specific required MW'] : []),
    ...(item.supply === 'Unknown' ? ['Suitable supply'] : []),
    ...(!item.start_window ? ['Start window'] : []),
    ...(!item.duration ? ['Duration'] : []),
    ...(item.commercial_organization ? [] : ['Buying organization']),
    'Buying authority: not evaluated in this summary; review the buying chain.',
    'Fuel and site constraints: not evaluated in this summary; review dated evidence.',
  ])]

  return <aside className="wh-detail" aria-label="Opportunity detail">
    <button className="wh-back" autoFocus onClick={onBack}>← Back to power needs</button>
    <div className="wh-detail-head">
      <span>{item.tier} · {item.commercial_disposition ?? 'Disposition unavailable'}</span>
      <h2>{item.name}</h2>
      <p>{item.location ?? 'Location unknown'} · {item.activity}</p>
      <div className="wh-facts">
        <span>Required power<strong>{item.required_mw ?? 'Unknown'}</strong><small>{factEvidenceState(item, 'demand')}</small></span>
        <span>Start<strong>{item.start_window ?? 'Unknown'}</strong><small>{factEvidenceState(item, 'start')}</small></span>
        <span>Duration<strong>{item.duration ?? 'Unknown'}</strong><small>{factEvidenceState(item, 'duration')}</small></span>
        <span>Suitable supply<strong>{item.supply ?? 'Unknown'}</strong><small>{factEvidenceState(item, 'supply')}</small></span>
      </div>
      {hasConflict(item.conflict_state) && <p role="status">Evidence conflict state: {item.conflict_state}. Review retained source claims before acting.</p>}
    </div>
    <nav className="wh-tabs" aria-label="Opportunity detail">
      {workspaceTabs.map(value => <button key={value} className={value === tab ? 'active' : ''} onClick={() => onTab(value)}>{value}</button>)}
    </nav>
    <div className="wh-detail-content">
      {loading && <p role="status">Loading verified detail…</p>}
      {error && <p role="alert">{error} <button onClick={onRetry}>Retry</button></p>}
      {tab === 'Overview' && <>
        <p>{item.commercial_reason || item.assessment_reason || item.rationale || 'No assessment summary is available.'}</p>
        <p><strong>Next question:</strong> {item.commercial_next_question || 'Unknown'}</p>
        {evidence[0] && <p>Supporting source: <a href={evidence[0].url} target="_blank" rel="noreferrer">{evidence[0].title}</a> · {evidence[0].published_at ?? 'Publication date unknown'}</p>}
      </>}
      {tab === 'Evidence' && <div>
        {evidence.length === 0 && <p>No retained evidence is attached to this opportunity.</p>}
        {evidence.map(source => <article className="wh-evidence" key={`${source.source_id}-${source.document_number}-${source.content_hash}`}>
          <a href={source.url} target="_blank" rel="noreferrer">{source.title}</a>
          <p>{source.source_id} · {source.document_number} · {source.source_origin}</p>
          <p>{source.event_date_label}: {source.event_date ?? 'Unknown'} · {source.published_at ? `Published ${source.published_at}` : 'Publication date unknown'} · Retrieved {new Date(source.retrieved_at).toLocaleString()}</p>
          <p>{source.assessment_current ? 'Current assessment evidence' : 'Historical evidence version'} · {source.extraction_location} · {source.content_hash}</p>
          {source.permit_status && <p>Permit status: {source.permit_status}</p>}
          <p>{source.abstract ?? 'No source abstract.'}</p>
        </article>)}
      </div>}
      {tab === 'Buying chain' && item.project_id && <BuyingChain projectId={item.project_id}/>}
      {tab === 'Buying chain' && !item.project_id && <p>Project identity is unavailable, so a buying chain cannot be resolved.</p>}
      {tab === 'Power gap' && <div>
        {gap ? <>
          <p><strong>Qualified remaining gap:</strong> {gap.remaining_mw_min}–{gap.remaining_mw_max} MW ({gap.value_kind})</p>
          <p>Supported required power: {gap.required_mw_min}–{gap.required_mw_max} MW · Available suitable supply: {gap.available_mw_min}–{gap.available_mw_max} MW</p>
          <p>Start window: {gap.start_window} · Duration: {gap.duration}</p>
          <p>Basis: {gap.basis_quote}</p>
          <p>Calculation: {gap.calculation} · Qualification {item.qualification_version ?? gap.version}</p>
        </> : <p>Supply unknown or no supported remaining gap is available for this need.</p>}
        <p>Fuel and site constraints: not evaluated in this summary; review dated evidence.</p>
        <button onClick={() => onTab('Evidence')}>Review dated evidence</button>
      </div>}
      {tab === 'Timeline' && <div>
        {evidence.map(source => <p className="wh-evidence" key={source.id}>{source.event_date_label}: {source.event_date ?? 'Unknown'} · {source.published_at ? `Published ${source.published_at}` : 'Publication date unknown'} · Retrieved {new Date(source.retrieved_at).toLocaleString()}</p>)}
      </div>}
      {tab === 'Next steps' && <>
        <p>{item.commercial_next_action || item.next_action || item.commercial_next_question || 'No next action is available.'}</p>
        <h3>Record call facts</h3>
        <QuickCallLog item={item} onReadback={onReadback}/>
        <h3>Verified facts and workflow history</h3>
        <FactWorkflowPanel item={item} onReadback={onReadback}/>
      </>}
      {tab === 'Unknowns' && <ul>{unknowns.map(value => <li key={value}>{value}</li>)}</ul>}
    </div>
  </aside>
}

function factEvidenceState(item: WorkspaceDetailItem, field: 'demand' | 'start' | 'duration' | 'supply') {
  if (field === 'demand' && item.demand_quote) return 'Source-reported'
  if (field === 'supply' && item.supply_quote) return 'Source-reported'
  if ((field === 'start' || field === 'duration') && item.qualified_remaining_gap && qualifiedGap(item.qualified_remaining_gap)?.value_kind) {
    return `${qualifiedGap(item.qualified_remaining_gap)?.value_kind} qualification`
  }
  const value = field === 'demand' ? item.required_mw : field === 'start' ? item.start_window : field === 'duration' ? item.duration : item.supply
  return value && value !== 'Unknown' ? 'Evidence status unavailable' : 'Unknown'
}

function hasConflict(value: string | null | undefined) {
  return new Set(['conflict', 'unresolved conflict', 'contradictory same-work need states']).has((value ?? '').trim().toLowerCase())
}
