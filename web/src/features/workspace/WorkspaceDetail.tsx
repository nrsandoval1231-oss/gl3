import { IntelligenceCard } from "./IntelligenceCard"
import type { Opportunity, WorkspaceNeed } from '../../api/client'
import { client, type Brief, type BuyingChainResult, type PowerNeedTitle } from '../../api/client'
import { useEffect, useRef, useState } from 'react'
import { projectTitle } from '../opportunities/projectCards'
import { BuyingChain } from '../buyingChain/BuyingChain'
import { FactWorkflowPanel } from '../pursuits/FactWorkflowPanel'
import { QuickCallLog } from '../pursuits/QuickCallLog'
import { ReportedPowerSchedule } from './ReportedPowerSchedule'

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
  associationNotice?: string
  onTab: (tab: WorkspaceTab) => void
  onBack: () => void
  onRetry: () => void
  onReadback: (notice?: string) => void
  correctionNotice?: string
  onTitleReady: () => void
}
function associatedAccountBasisLabel(basis: string) {
  return basis === 'typed_rrc_operator_number_v1'
    ? 'Supported by retained RRC operator evidence.'
    : 'Supported by current retained evidence.'
}

export function WorkspaceDetail({ item, pending, loading, error, tab, associationNotice, onTab, onBack, onRetry, onReadback, onTitleReady, correctionNotice }: Props) {
  const [shareState, setShareState] = useState('')
  const [sourceFilter, setSourceFilter] = useState('All sources')
  const [brief, setBrief] = useState<Brief | null>(null)
  const [briefBusy, setBriefBusy] = useState(false)
  const [briefError, setBriefError] = useState('')
  const [briefPollRevision, setBriefPollRevision] = useState(0)
  const activeBriefNeedId = useRef<string | null>(null)
  const briefRequestSequence = useRef(0)
  const [titleState, setTitleState] = useState<PowerNeedTitle | null>(null)
  const [titleBusyNeedId, setTitleBusyNeedId] = useState<string | null>(null)
  const [titleStatusBusyNeedId, setTitleStatusBusyNeedId] = useState<string | null>(null)
  const titleRequestId = useRef<string | null>(null)
  const titleRequestSequence = useRef(0)
  const titleBusy = Boolean(item && titleBusyNeedId === item.id)
  const titleStatusCheckFailed = titleState?.status === 'failed' && titleState.error === 'status_check_failed'
  const titleStatusBusy = Boolean(item && titleStatusBusyNeedId === item.id)
  const onTitleReadyRef = useRef(onTitleReady)
  useEffect(() => { onTitleReadyRef.current = onTitleReady }, [onTitleReady])
  useEffect(() => { setShareState('') }, [item?.id])
  useEffect(() => { setSourceFilter('All sources') }, [item?.id])
  useEffect(() => {
    const id = item?.id
    const sequence = ++briefRequestSequence.current
    activeBriefNeedId.current = id ?? null
    setBrief(null)
    setBriefBusy(false)
    setBriefError('')
    if (!id) return
    let cancelled = false
    void client.brief(id).then(value => { if (!cancelled && briefRequestSequence.current === sequence && activeBriefNeedId.current === id) setBrief(value) })
      .catch((cause: unknown) => { if (!cancelled && briefRequestSequence.current === sequence && activeBriefNeedId.current === id) setBriefError(cause instanceof Error ? cause.message : 'Brief status is unavailable.') })
    return () => { cancelled = true }
  }, [item?.id])
  useEffect(() => {
    if (!item?.id || brief?.status !== 'pending') return
    const id = item.id
    const sequence = briefRequestSequence.current
    let cancelled = false
    let timer = 0
    const poll = () => { timer = window.setTimeout(() => {
      void client.brief(id).then(value => {
        if (cancelled || briefRequestSequence.current !== sequence || activeBriefNeedId.current !== id) return
        setBrief(value)
        if (value.status === 'pending') poll()
      }).catch((cause: unknown) => { if (!cancelled && briefRequestSequence.current === sequence && activeBriefNeedId.current === id) setBriefError(cause instanceof Error ? cause.message : 'Brief status is unavailable.') })
    }, 1600) }
    poll()
    return () => { cancelled = true; window.clearTimeout(timer) }
  }, [item?.id, brief?.status, briefPollRevision])
  useEffect(() => {
    const id = item?.id
    const sequence = ++titleRequestSequence.current
    titleRequestId.current = id ?? null
    setTitleBusyNeedId(null)
    setTitleStatusBusyNeedId(null)
    setTitleState(null)
    if (!id) return
    const controller = new AbortController()
    void client.powerNeedTitle(id, controller.signal).then(value => {
      if (!controller.signal.aborted && titleRequestSequence.current === sequence && titleRequestId.current === id) setTitleState(value)
    }).catch(() => {
      if (!controller.signal.aborted && titleRequestSequence.current === sequence && titleRequestId.current === id) {
        setTitleState({ status: 'failed', result: null, citations: [], generated_at: null, model: null, error: 'status_check_failed' })
      }
    })
    return () => controller.abort()
  }, [item?.id, item?.title_status, item?.browse_title])
  useEffect(() => {
    const id = item?.id
    if (!id || titleState?.status !== 'pending') return
    const sequence = titleRequestSequence.current
    const controller = new AbortController()
    let timer = 0
    const poll = () => {
      timer = window.setTimeout(() => {
        void client.powerNeedTitle(id, controller.signal).then(value => {
          if (controller.signal.aborted || titleRequestSequence.current !== sequence || titleRequestId.current !== id) return
          setTitleState(value)
          if (value.status === 'ready') onTitleReadyRef.current()
          else if (value.status === 'pending') poll()
        }).catch(() => {
          if (!controller.signal.aborted && titleRequestSequence.current === sequence && titleRequestId.current === id) {
            setTitleState({ status: 'failed', result: null, citations: [], generated_at: null, model: null, error: 'status_check_failed' })
          }
        })
      }, 1500)
    }
    poll()
    return () => { controller.abort(); window.clearTimeout(timer) }
  }, [item?.id, titleState?.status])
  const tabsRef = useRef<HTMLElement>(null)
  useEffect(() => {
    const nav = tabsRef.current
    if (!nav) return
    const reveal = () => {
      const active = nav.querySelector<HTMLElement>('.active')
      if (!active || nav.scrollWidth <= nav.clientWidth) return
      const bounds = nav.getBoundingClientRect(), selected = active.getBoundingClientRect()
      if (selected.left < bounds.left) nav.scrollLeft += selected.left - bounds.left
      else if (selected.right > bounds.right) nav.scrollLeft += selected.right - bounds.right
    }
    reveal()
    const observer = new ResizeObserver(reveal)
    observer.observe(nav)
    return () => observer.disconnect()
  }, [tab, item?.id])
  if (!item) {
    return <aside className={`wh-detail ${pending || loading ? 'wh-detail-loading' : 'wh-empty-detail'}`} aria-label="Opportunity detail">
      {(pending || loading || error) && <button type="button" className="wh-back" aria-label="Back to power needs" onClick={onBack}>Opportunities</button>}
      <p>{pending || loading ? 'Loading verified opportunity detail…' : 'Select an opportunity to review its evidence and next action.'}</p>
      {correctionNotice && <p role="status">{correctionNotice}</p>}
      {error && <p role="alert">{error} <button onClick={onRetry}>Retry</button></p>}
    </aside>
  }

  const evidence = item.evidence ?? []
  const cardEvidence = item.intelligence_card?.evidence ?? []
  const sourceFilters = [...new Set([...evidence.map(source => source.source_origin || source.source_id), ...cardEvidence.map(source => source.reference)].filter(Boolean))].sort()
  const visibleEvidence = sourceFilter === 'All sources' ? evidence : evidence.filter(source => (source.source_origin || source.source_id) === sourceFilter)
  const visibleCardEvidence = sourceFilter === 'All sources' ? cardEvidence : cardEvidence.filter(source => source.reference === sourceFilter)
  const callEvidence = evidence.find(source => source.assessment_current) ?? evidence[0]
  const customer = item.intelligence_card?.fields.find(field => field.key === 'customer' && field.value)?.value ?? null
  const displayOrganization = item.associated_account?.name ?? customer
  const intelligenceProject = item.intelligence_card?.fields.find(field => field.key === 'project' && field.value)?.value ?? null
  const intelligenceLocation = item.intelligence_card?.fields.find(field => field.key === 'location' && field.value)?.value ?? null
  const company = item.commercial_organization || item.title_company
  const currentTitleReady = titleState?.status === 'ready' && Boolean(titleState.result?.title)
  const titleStatus = titleState?.status ?? item.title_status
  const useDeterministicTitleFallback = ['pending', 'stale', 'failed', 'disabled', 'unavailable'].includes(titleStatus ?? '')
  const canonicalTitleFallback = projectTitle({
    ...item,
    browse_title: item.title_status === 'ready' ? undefined : item.browse_title,
  })
  const displayTitle = intelligenceProject || (currentTitleReady
    ? titleState.result!.title
    : useDeterministicTitleFallback ? canonicalTitleFallback : item.browse_title || canonicalTitleFallback)
  const displayLocation = intelligenceLocation || item.location || 'Location unknown'
  const companyRole = item.title_company_role
  const unverified = [
    ...(!item.start_window ? ['power start timing'] : []),
    ...(!item.duration ? ['duration'] : []),
    ...(item.supply === 'Unknown' ? ['suitable temporary supply'] : []),
    'current project assignment and purchasing authority',
  ]
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
  async function requestBrief() {
    if (!item) return
    const id = item.id
    const sequence = ++briefRequestSequence.current
    setBriefBusy(true); setBriefError('')
    try {
      const value = await client.requestBrief(id)
      if (briefRequestSequence.current === sequence && activeBriefNeedId.current === id) setBrief(value)
    } catch (cause) {
      if (briefRequestSequence.current === sequence && activeBriefNeedId.current === id) setBriefError(cause instanceof Error ? cause.message : 'GridLens could not request a brief.')
    } finally { if (briefRequestSequence.current === sequence && activeBriefNeedId.current === id) setBriefBusy(false) }
  }
  const briefContent = brief?.result as { event_summary?: { text: string; evidence_id: string }[]; commercial_hypothesis?: { text: string; evidence_id: string }; unknowns?: string[]; next_step?: string } | null
  const briefStatements = [...(briefContent?.event_summary ?? []), ...(briefContent?.commercial_hypothesis ? [briefContent.commercial_hypothesis] : [])]
  const supportedGap = qualifiedGap(item.qualified_remaining_gap)
  const cardGap = item.intelligence_card?.power_gap
  const cardGapRemaining = cardGap && typeof cardGap.remaining_mw === 'string' && cardGap.remaining_mw.trim() ? cardGap.remaining_mw : null
  const cardGapBasis = cardGap && typeof cardGap.status === 'string' ? cardGap.status.replaceAll('_', ' ') : 'Supported activity-specific bridge gap.'
  const facilityDemand = item.intelligence_card?.fields.find(field => field.key === 'facility_demand')
  const energization = item.intelligence_card?.fields.find(field => field.key === 'energization')
  const metrics = [
    { key: 'demand', label: 'Facility Demand', value: facilityDemand?.value ?? 'Not established', basis: facilityDemand?.basis ?? 'No facility-wide demand is supported by retained evidence.', icon: 'demand' },
    { key: 'gap', label: 'Potential Bridge-Power Gap', value: supportedGap ? `${supportedGap.remaining_mw_min}–${supportedGap.remaining_mw_max} MW` : cardGapRemaining ?? 'Not established', basis: supportedGap ? `${supportedGap.value_kind} · ${item.qualification_version ?? supportedGap.version}` : cardGapRemaining ? cardGapBasis : 'No supported remaining gap is available.', icon: 'gap' },
    { key: 'start', label: 'Power Needed By', value: item.start_window ?? 'Not established', basis: item.start_window ? factEvidenceState(item, 'start') : 'No supported power timing is available.', icon: 'calendar' },
    { key: 'duration', label: 'Expected Duration', value: item.duration ?? 'Not established', basis: item.duration ? factEvidenceState(item, 'duration') : 'No supported duration is available.', icon: 'clock' },
    { key: 'supply', label: 'Utility Energization', value: energization?.value ?? 'Not established', basis: energization?.value ? energization.basis : 'Utility energization timing is not supported by retained evidence.', icon: 'supply' },
  ] as const
  function openNextSteps() {
    onTab('Next steps')
    window.setTimeout(() => document.querySelector('.wh-tabs')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 0)
  }
  async function copyShareLink() {
    try { await navigator.clipboard.writeText(location.href); setShareState('Opportunity link copied.') }
    catch { setShareState('Link copying is unavailable in this browser.') }
  }

  return <aside className="wh-detail" aria-label="Opportunity detail">
    <div className="wh-detail-head">
      <div className="wh-identity-toolbar"><div className="wh-breadcrumb"><button className="wh-back" aria-label="Back to power needs" onClick={onBack}>Opportunities</button><span aria-hidden="true">/</span><span>{displayOrganization || 'Project'}</span><span aria-hidden="true">/</span><span>{displayTitle}</span></div><div className="wh-record-actions"><button className="wh-share" onClick={() => void copyShareLink()}><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M12.7 6.3 8.1 8.9m0 2.2 4.6 2.6"/><circle cx="14.8" cy="5.1" r="2.1"/><circle cx="5.3" cy="10" r="2.1"/><circle cx="14.8" cy="14.9" r="2.1"/></svg>Share</button><button className="wh-primary-action" onClick={openNextSteps}><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 4v12M4 10h12"/></svg>Update workflow</button>{shareState && <span role="status">{shareState}</span>}</div></div>
      <div className="wh-record-hero">
        <span className="wh-customer-monogram" aria-hidden="true">{(displayOrganization || displayTitle).split(/\s+/).filter(Boolean).slice(0, 2).map(word => word[0]).join('').toUpperCase()}</span>
        <div className="wh-record-identity">
          <h2>{displayOrganization || displayTitle}</h2>
          {displayOrganization && <p className="wh-record-project">{displayTitle}</p>}
          <p className="wh-record-subtitle">{displayLocation} · {item.activity.replaceAll('-', ' ')}</p>
        </div>
        <div className="wh-record-qualification"><span className="wh-tier-badge">{item.tier} · {item.commercial_disposition ?? item.intelligence_card?.disposition ?? 'Disposition unavailable'}</span><span>{item.intelligence_card?.last_intelligence_update ? `Evidence updated ${new Date(item.intelligence_card.last_intelligence_update).toLocaleDateString()}` : 'Evidence update date unavailable'}</span></div>
        {item.intelligence_card && <div className="wh-completeness"><span>Intelligence completeness</span><strong>{item.intelligence_card.completeness.supported}/{item.intelligence_card.completeness.total}</strong><progress aria-label="Intelligence completeness" max={item.intelligence_card.completeness.total} value={item.intelligence_card.completeness.supported}/></div>}
      </div>      {item.associated_account && <p className="wh-group-context"><strong>Current account association:</strong> {item.associated_account.name} · {item.associated_account.role.replaceAll('_', ' ')}. {associatedAccountBasisLabel(item.associated_account.basis)} Buying authority is not established by this project association.</p>}
      {associationNotice && <p role="status" className="wh-integrity">{associationNotice}</p>}
      {item.signal_evidence_state === 'planning_application_withdrawn' && <p className="wh-integrity"><strong>Planning application withdrawn · historical Signal.</strong> Current project viability is unknown.</p>}
      {item.signal_evidence_state === 'planning_status_unknown' && <p className="wh-integrity"><strong>Conflicting planning revision · historical Signal.</strong> Current application and project status are unknown.</p>}
      {item.signal_evidence_state === 'source_listing_absent' && <p className="wh-integrity"><strong>Status review needed.</strong> This filing is no longer in the source current listing; it may have been issued, denied, or withdrawn. Its evidence is retained.</p>}
      {item.group_total_filtered && item.group_total_filtered > 1 && <p className="wh-group-context">Part of a group with {item.group_total_filtered} retained records. Each record and its evidence remain separate and available.</p>}
      {hasConflict(item.conflict_state) && <p role="status" className="wh-integrity">Evidence conflict state: {item.conflict_state}. Review retained source claims before acting.</p>}    </div>
    <section className="wh-metrics" aria-label="Power need metrics">
      {metrics.map(metric => <article className="wh-metric" key={metric.key}><span className="wh-metric-icon" aria-hidden="true"><svg viewBox="0 0 24 24">{metric.icon === 'demand' ? <><path d="m13 2-8 11h6l-1 9 9-12h-6z"/></> : metric.icon === 'gap' ? <><path d="M4 19V9m5 10V5m5 14v-7m5 7V3"/></> : metric.icon === 'calendar' ? <><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4m10-4v4M3 10h18"/></> : metric.icon === 'clock' ? <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></> : <><path d="M4 21h16M6 18h12l-2-12H8zM9 3h6M10 10h4m-4 4h4"/></>}</svg></span><div><span className="wh-metric-label">{metric.label}</span><strong className={metric.value === 'Not established' ? 'wh-metric-unknown' : undefined}>{metric.value}</strong><small>{metric.basis}</small></div></article>)}
    </section>
    {item.intelligence_card ? <IntelligenceCard key={item.id} card={item.intelligence_card} opportunityName={displayTitle} customer={customer} location={item.location} activity={item.activity.replaceAll('-', ' ')} tier={item.tier} why={item.commercial_reason || item.assessment_reason || item.rationale || 'No assessment rationale is available.'} nextAction={item.commercial_next_action || item.next_action || item.commercial_next_question || 'Review retained evidence and confirm the unresolved details.'} onReadback={onReadback} onReview={openNextSteps} /> : <div className="wh-summary-columns">
      <section><h3>Project &amp; customer details</h3><dl><div><dt>Project</dt><dd>{displayTitle}</dd></div>{customer && <div><dt>Customer / end user</dt><dd>{customer}</dd></div>}<div><dt>Power activity</dt><dd>{item.activity.replaceAll('-', ' ')}</dd></div><div><dt>Location</dt><dd>{item.location ?? 'Unknown'}</dd></div></dl></section>
      <section><h3>Key contacts &amp; buying chain</h3><p>No current verified contact is available in the intelligence summary.</p>{item.project_id && <button onClick={() => onTab('Buying chain')}>Review buying chain</button>}</section>
      <section><h3>Why this opportunity matters</h3><p>{item.commercial_reason || item.assessment_reason || item.rationale || 'No assessment rationale is available.'}</p><h4>Recommended next action</h4><p>{item.commercial_next_action || item.next_action || item.commercial_next_question || 'Review retained evidence and confirm the unresolved details.'}</p><button onClick={() => onTab('Next steps')}>Update workflow</button></section>
    </div>}
    <nav ref={tabsRef} className="wh-tabs" aria-label="Opportunity detail">
      {(['Evidence', 'Power gap', 'Unknowns', 'Next steps'] as const).map(value => <button key={value} aria-pressed={value === tab} aria-label={value === 'Next steps' ? 'Next steps' : value === 'Power gap' ? 'Commercial Assessment' : value === 'Unknowns' ? 'Research Gaps' : 'Evidence'} className={value === tab ? 'active' : ''} onClick={() => onTab(value)}>{value === 'Power gap' ? 'Commercial Assessment' : value === 'Unknowns' ? 'Research Gaps' : value === 'Next steps' ? 'Notes & Activity' : 'Evidence'}</button>)}
      <details className="wh-more-tabs" open><summary>More</summary><div>{(['Overview', 'Buying chain', 'Timeline'] as const).map(value => <button key={value} aria-pressed={tab === value} onClick={() => onTab(value)}>{value}</button>)}</div></details>
    </nav>
    <div className="wh-detail-content">
      {loading && <p role="status">Loading verified detail…</p>}
      {correctionNotice && <p role="status">{correctionNotice}</p>}
      {error && <p role="alert">{error} <button onClick={onRetry}>Retry</button></p>}
      {tab === 'Overview' && !item.intelligence_card && <>
        <details className="wh-provenance-disclosure"><summary>Decision and evidence diagnostics</summary>
          {item.signal_admission_origin && <p>Signal admission origin: {item.signal_admission_origin}</p>}
          {item.signal_evidence_state && <p>Signal evidence state: {item.signal_evidence_state.replaceAll('_', ' ')}</p>}
          {item.commercial_size_status && <p>Activity size status: {item.commercial_size_status}</p>}
          {item.supported_subject && <p>Supported subject: {item.supported_subject}{item.supported_action ? ` · ${item.supported_action}` : ''}</p>}
          {item.demand_quote && <blockquote>{item.demand_quote}</blockquote>}{item.supply_quote && <blockquote>{item.supply_quote}</blockquote>}
          {item.reported_power_facts?.length ? <><strong>Reported power figures (source claims, not rental requirements)</strong><ul>{item.reported_power_facts.map((fact, i) => <li key={`${i}-${fact}`}>{fact}</li>)}</ul></> : null}
          {item.lifecycle_state && <p>Asset lifecycle: {item.asset_type?.replaceAll('_', ' ') ?? 'Unknown'} · {item.lifecycle_state.replaceAll('_', ' ')}. Expected next milestone: {item.expected_next_milestone ?? 'Unknown'}; expected power event: {item.expected_power_event ?? 'Unknown'}; estimated window: {item.time_to_power_window ?? 'Unknown'}.</p>}
          {item.estimate_version && <p>Derived lifecycle estimate · {item.estimate_version} · {String(item.estimate_basis?.confidence ?? 'confidence unknown')}. This is not a reported date, power requirement, or power gap.</p>}
          {item.lifecycle_timeline?.length ? <ol>{item.lifecycle_timeline.map((event, i) => <li key={`${event.event_type}-${i}`}><a href={event.evidence_url} target="_blank" rel="noreferrer">{event.date ?? 'Date unknown'} · {event.state.replaceAll('_', ' ')}</a> ({event.value_kind}{event.current ? '' : ', superseded'}{event.published_at ? ` · published ${event.published_at}` : ''})</li>)}</ol> : null}
          {item.monitoring_requirements?.length ? <p>Monitoring: {item.monitoring_requirements.join(' · ')}</p> : null}
          {item.lifecycle_open_questions?.length ? <p>Lifecycle evidence still missing: {item.lifecycle_open_questions.join(' · ')}</p> : null}
        </details>
        <p>{item.commercial_reason || item.assessment_reason || item.rationale || 'No assessment summary is available.'}</p>
        <section aria-label="Priority explanation"><strong>Priority</strong>{item.rank_score != null ? <p>Canonical rank score: {item.rank_score}{item.rank_version ? ` · ${item.rank_version}` : ''}</p> : <p>Canonical rank score unavailable.</p>}{item.rank_reasons?.length ? <ul>{item.rank_reasons.map((reason, index) => <li key={`${index}:${reason}`}>{reason}</li>)}</ul> : <p>No rank reasons were recorded.</p>}<small>Priority is separate from qualification and commercial disposition.</small></section>
        <p><strong>Next question:</strong> {item.commercial_next_question || 'Unknown'}</p>
        {evidence[0] && <p>Supporting source: <a href={evidence[0].url} target="_blank" rel="noreferrer">{evidence[0].title}</a> · {evidence[0].published_at ?? 'Publication date unknown'}</p>}
      </>}
      {tab === 'Overview' && item.intelligence_card && <>
        {(item.lifecycle_state || item.lifecycle_timeline?.length || item.lifecycle_open_questions?.length) && <details className="wh-provenance-disclosure"><summary>Asset lifecycle and monitoring</summary>
          {item.lifecycle_state && <p>Asset lifecycle: {item.asset_type?.replaceAll('_', ' ') ?? 'Unknown'} · {item.lifecycle_state.replaceAll('_', ' ')}. Expected next milestone: {item.expected_next_milestone ?? 'Unknown'}; expected power event: {item.expected_power_event ?? 'Unknown'}; estimated window: {item.time_to_power_window ?? 'Unknown'}.</p>}
          {item.estimate_version && <p>Derived lifecycle estimate · {item.estimate_version} · {String(item.estimate_basis?.confidence ?? 'confidence unknown')}. This is not a reported date, power requirement, or power gap.</p>}
          {item.lifecycle_timeline?.length ? <ol>{item.lifecycle_timeline.map((event, i) => <li key={`${event.event_type}-${i}`}><a href={event.evidence_url} target="_blank" rel="noreferrer">{event.date ?? 'Date unknown'} · {event.state.replaceAll('_', ' ')}</a> ({event.value_kind}{event.current ? '' : ', superseded'}{event.published_at ? ` · published ${event.published_at}` : ''})</li>)}</ol> : null}
          {item.monitoring_requirements?.length ? <p>Monitoring: {item.monitoring_requirements.join(' · ')}</p> : null}
          {item.lifecycle_open_questions?.length ? <p>Lifecycle evidence still missing: {item.lifecycle_open_questions.join(' · ')}</p> : null}
        </details>}
        <section aria-label="Priority explanation"><strong>Priority</strong>{item.rank_score != null ? <p>Canonical rank score: {item.rank_score}{item.rank_version ? ` · ${item.rank_version}` : ''}</p> : <p>Canonical rank score unavailable.</p>}{item.rank_reasons?.length ? <ul>{item.rank_reasons.map((reason, index) => <li key={`${index}:${reason}`}>{reason}</li>)}</ul> : <p>No rank reasons were recorded.</p>}<small>Priority is separate from qualification and commercial disposition.</small></section>
      </>}
      {tab === 'Evidence' && <div className="wh-evidence-section">
        <header className="wh-evidence-heading"><div><h2>Evidence &amp; Sources</h2><p>Retained records: {evidence.length} · Intelligence citations: {cardEvidence.length}. Citations may refer to records listed here.</p></div><label>Filter sources <select aria-label="Filter evidence sources" value={sourceFilter} onChange={event => setSourceFilter(event.target.value)}><option value="All sources">All sources</option>{sourceFilters.map(filter => <option key={filter} value={filter}>{filter}</option>)}</select></label></header>
        {evidence.length === 0 && <p>No retained evidence is attached to this opportunity.</p>}
        {evidence.length > 0 && <table className="wh-evidence-table"><thead><tr><th>Date</th><th>Source</th><th>Title</th><th>Key insight</th><th>Type</th></tr></thead><tbody>{visibleEvidence.map(source => <tr key={`${source.source_id}-${source.document_number}-${source.content_hash}`}>
          <td>{source.event_date ?? 'Date unknown'}</td><td>{source.source_id}</td><td><a href={source.url} target="_blank" rel="noreferrer">{source.title}</a><details><summary>Source record</summary><p>{source.document_number ?? 'Document number unknown'} · {source.event_date_label}: {source.event_date ?? 'Unknown'}</p><p>{source.published_at ? `Published ${source.published_at}` : 'Publication date unknown'} · Retrieved {new Date(source.retrieved_at).toLocaleString()}</p><p>{source.assessment_current ? 'Current assessment evidence' : 'Historical evidence version'} · {source.extraction_location} · {source.content_hash}</p>{source.permit_status && <p>Permit status: {source.permit_status}</p>}</details></td><td>{source.abstract ?? 'No source abstract.'}</td><td>{source.source_origin}</td>
        </tr>)}</tbody></table>}
        {visibleCardEvidence.length > 0 && <section className="wh-card-sources" aria-label="Intelligence card sources">{visibleCardEvidence.map(source => <article key={source.reference}><strong>{source.title}</strong><p>{source.reference} · {source.source_date ?? 'Source date unavailable'} · {source.verification_status} · {source.extraction_method}</p>{source.passage && <blockquote>{source.passage}</blockquote>}{source.url && <a href={source.url} target="_blank" rel="noreferrer">Open retained source</a>}</article>)}</section>}
      </div>}
      {tab === 'Evidence' && <section aria-label="Opportunity diagnostics">      {item.tier === 'Signal' && item.commercial_size_status === 'unknown' && <p className="wh-integrity">Activity size unknown. Retained for investigation; the 300 kW minimum is inclusive.</p>}
      <details className="wh-source-context"><summary>Source title and organization</summary><p>Source record: {item.name}</p>{company && <p>Source-listed organization: {company}{companyRole ? ` · ${companyRole}` : ''}. This role does not establish customer status or purchasing authority.</p>}</details>
{item.intelligence_card && <details><summary>Opportunity diagnostics</summary><p>Research completeness is separate from {item.intelligence_card.qualification} qualification.</p>{item.intelligence_card.fields.filter(field => field.value === null).map(field => <p key={field.key}><strong>{field.label}:</strong> Unknown · {field.basis}</p>)}</details>}<details className="wh-title-controls" open><summary>Evidence-grounded title</summary><section className="wh-title-enrichment" aria-label="Evidence-grounded title">
      <button disabled={titleBusy || titleState?.status === 'disabled' || titleStatusCheckFailed} onClick={() => {
        const id = item.id
        const sequence = ++titleRequestSequence.current
        titleRequestId.current = id
        setTitleBusyNeedId(id)
        void client.requestPowerNeedTitle(id).then(value => {
          if (titleRequestSequence.current !== sequence || titleRequestId.current !== id) return
          setTitleState(value)
          if (value.status === 'ready') onTitleReadyRef.current()
        }).catch(() => {
          if (titleRequestSequence.current === sequence && titleRequestId.current === id) setTitleState({ status: 'failed', result: null, citations: [], generated_at: null, model: null, error: 'request_failed' })
        }).finally(() => { if (titleRequestSequence.current === sequence && titleRequestId.current === id) setTitleBusyNeedId(null) })
      }}>{currentTitleReady ? 'Refresh title' : 'Enrich title'}</button>
      {titleStatusCheckFailed && <button disabled={titleStatusBusy} onClick={() => {
        const id = item.id
        const sequence = ++titleRequestSequence.current
        const controller = new AbortController()
        titleRequestId.current = id
        setTitleStatusBusyNeedId(id)
        void client.powerNeedTitle(id, controller.signal).then(value => {
          if (titleRequestSequence.current !== sequence || titleRequestId.current !== id) return
          setTitleState(value)
          if (value.status === 'ready') onTitleReadyRef.current()
        }).catch(() => {
          if (titleRequestSequence.current === sequence && titleRequestId.current === id) {
            setTitleState({ status: 'failed', result: null, citations: [], generated_at: null, model: null, error: 'status_check_failed' })
          }
        }).finally(() => {
          if (titleRequestSequence.current === sequence && titleRequestId.current === id) setTitleStatusBusyNeedId(null)
        })
      }}>{titleStatusBusy ? 'Checking status' : 'Retry status'}</button>}
      <span role="status">{titleBusy ? 'Requesting title.' : titleStatusBusy ? 'Checking current title status.' : titleStatus === 'disabled' ? 'Title enrichment is disabled; showing source-backed fallback.' : titleStatus === 'pending' ? 'Title request pending.' : currentTitleReady ? `Evidence-grounded title · ${titleState.model ?? 'model unknown'}` : titleStatus === 'stale' ? 'Saved title is stale; showing source-backed fallback.' : titleStatusCheckFailed ? 'Title status could not be checked. Check again before requesting a new title.' : titleState?.status === 'failed' ? 'Title request failed; showing source-backed fallback.' : 'Showing source-backed title fallback.'}</span>
      {currentTitleReady && titleState.citations.map(citation => <p key={`${citation.evidence_id}:${citation.role ?? ''}:${citation.quote}`}><a href={citation.url} target="_blank" rel="noreferrer">{citation.title}</a> · {citation.role ?? 'source activity'}: "{citation.quote}"</p>)}
    </section></details></section>}
      {tab === 'Buying chain' && item.project_id && <BuyingChain projectId={item.project_id} onReadback={onReadback}/>}
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
        {item.intelligence_card && <ReportedPowerSchedule schedule={item.intelligence_card.power_schedule} />}
      </div>}
      {tab === 'Timeline' && <div>
        {evidence.map(source => <p className="wh-evidence" key={source.id}>{source.event_date_label}: {source.event_date ?? 'Unknown'} · {source.published_at ? `Published ${source.published_at}` : 'Publication date unknown'} · Retrieved {new Date(source.retrieved_at).toLocaleString()}</p>)}
      </div>}
      {tab === 'Next steps' && <>
        <section className="wh-panel wh-brief-panel" aria-label="Concise evidence brief">
          <div className="wh-briefing-head"><div><p className="wh-kicker">AI-assisted · source cited</p><h3>Concise evidence brief</h3></div><span>{brief?.status === 'pending' ? 'Generation pending' : brief?.status === 'stale' ? 'Stale evidence' : brief?.status === 'failed' ? 'Latest request failed' : brief?.generated_at ? `Generated ${new Date(brief.generated_at).toLocaleString()}` : 'Not generated'}</span></div>
          {brief?.status === 'pending' && <p role="status">Generating from retained public evidence…</p>}{briefError && <p role="alert">{briefError}</p>}
          {brief?.status === 'pending' && briefError && <button type="button" onClick={() => { setBriefError(''); setBriefPollRevision(value => value + 1) }}>Retry brief status</button>}
          {brief?.error && <p role="status">The last request could not produce a new brief. Any displayed brief is the last successfully generated version.</p>}{brief?.stale && <p role="status">Source evidence or brief settings changed after generation. This cached text is stale.</p>}
          {brief?.question_context === 'different_question' && <p role="status">This saved answer was prepared for a different question. Review the exact-question result in Research.</p>}
          {briefStatements.map((statement, i) => { const citation = brief?.citations?.find(entry => entry.evidence_id === statement.evidence_id); return <p key={`${statement.evidence_id}-${i}`}>{statement.text} {citation && <a href={citation.url} target="_blank" rel="noreferrer">[{citation.title}]</a>}</p> })}
          {briefContent?.unknowns?.length ? <><strong>Unknown</strong><ul>{briefContent.unknowns.map(value => <li key={value}>{value}</li>)}</ul></> : null}{briefContent?.next_step && <p><strong>Next verification step:</strong> {briefContent.next_step}</p>}
          {!briefStatements.length && brief?.status !== 'pending' && <p>The brief has not been generated.</p>}
          <button type="button" disabled={briefBusy || brief?.status === 'pending'} onClick={() => void requestBrief()}>{briefBusy ? 'Requesting…' : brief?.status === 'ready' ? 'Refresh brief' : 'Generate or retry brief'}</button>
        </section>
        <section className="wh-call-brief" aria-label="Call preparation">
          <h3>Prepare the call</h3>
          <p><strong>Who to verify:</strong> {company || 'Company unknown'}{companyRole ? ` · ${companyRole}` : ''}. {company ? 'The source-listed role does not establish current assignment or buying authority.' : 'Review the retained buying chain for supported organizations.'}</p>
          {item.project_id && <CallBuyerSummary projectId={item.project_id}/>}
          <p><strong>Why investigate:</strong> {item.commercial_reason || item.assessment_reason || item.rationale || 'No dated reason is available.'}</p>
          {callEvidence && <p><strong>Source:</strong> <a href={callEvidence.url} target="_blank" rel="noreferrer">{callEvidence.title}</a> · {callEvidence.event_date_label}: {callEvidence.event_date ?? 'Date unknown'} · {callEvidence.published_at ? `Published ${callEvidence.published_at}` : 'Publication date unknown'} · {callEvidence.permit_status ? `Status ${callEvidence.permit_status}` : 'Status unknown'}</p>}
          <p><strong>Opening question:</strong> {item.commercial_next_question || 'Unknown; verify who handles the power package and whether suitable temporary supply is in place.'}</p>
          <p><strong>Still unverified:</strong> {unverified.join(', ')}.</p>
          <p>{item.commercial_next_action || item.next_action || 'Use the opening question to confirm the scope and next step.'}</p>
        </section>
        <h3>Record call facts</h3>
        <QuickCallLog item={item} onReadback={onReadback}/>
        <h3>Verified facts and workflow history</h3>
        <FactWorkflowPanel item={item} onReadback={onReadback}/>
      </>}
      {tab === 'Unknowns' && <><ul>{unknowns.map(value => <li key={value}>{value}</li>)}</ul>{item.intelligence_card?.research_gaps.map(field => <p key={field.key}><strong>{field.label}:</strong> {field.value ?? field.basis} · {field.status}{field.research_status ? ` · ${field.research_status.replaceAll('_', ' ').toLowerCase()}` : ''}</p>)}{item.tier === 'Signal' && item.commercial_size_status === 'unknown' && <p>Activity size unknown. Retained for investigation; the 300 kW minimum is inclusive.</p>}</>}
    </div>
    <section className="wh-mobile-workflow" aria-label="Next action"><button type="button" onClick={openNextSteps}>Update workflow</button></section>
  </aside>
}

function CallBuyerSummary({ projectId }: { projectId: string }) {
  const [result, setResult] = useState<BuyingChainResult | null>(null)
  const [error, setError] = useState(false)
  useEffect(() => {
    const controller = new AbortController()
    setResult(null); setError(false)
    void client.buyingChain(projectId, controller.signal).then(value => {
      if (controller.signal.aborted) return
      if (value.project_id !== projectId || !Array.isArray(value.candidates)) throw new Error('Mismatched buying-chain response')
      setResult(value)
    }).catch(() => { if (!controller.signal.aborted) setError(true) })
    return () => controller.abort()
  }, [projectId])
  if (error) return <p><strong>Contact path:</strong> Unavailable; retry in Buying chain.</p>
  if (!result || result.project_id !== projectId) return <p role="status"><strong>Source-listed contacts:</strong> Loading retained buying-chain evidence.</p>
  const candidate = result.candidates?.find(item => !item.stale && item.organization_relationship === 'DIRECT' && item.category !== 'rental_intermediary')
  const contact = candidate?.public_contacts?.[0]
  const permitFacts = (result.permit_summaries ?? []).flatMap(permit =>
    (permit.facts ?? [])
      .filter(fact => /^(applicant (full )?name|contact (full )?name|applicant phone|contact phone|phone|permit-listed contractor name|contractor permit-listed phone \(permit field\)|permit-listed applicant name|applicant permit-listed phone \(permit field\))$/i.test(fact.label))
      .map(fact => ({ ...fact, permit })),
  )
  const permitPerson = permitFacts.find(fact => /name$/i.test(fact.label))
  const permitPhone = permitFacts.find(fact => /phone(?: \(permit field\))?$/i.test(fact.label))
  const company = candidate?.organization
  return <>
    {company && <p><strong>Project organization:</strong> {company} ({candidate?.category.replaceAll('_', ' ')}; source-supported involvement, purchasing authority unverified).</p>}
    {contact && <p><strong>Source-listed contact:</strong> {contact.value} ({contact.kind}; identity and authority unverified) · {company} · <a href={contact.source_url} target="_blank" rel="noreferrer">Contact source</a></p>}
    {!contact && permitPerson && <p><strong>Permit-listed person:</strong> {permitPerson.value} ({permitPerson.label}; role, assignment and authority unverified) · <a href={permitPerson.permit.url} target="_blank" rel="noreferrer">{permitPerson.permit.title}</a></p>}
    {!contact && permitPhone && <p><strong>Permit-listed phone:</strong> {permitPhone.value} ({permitPhone.label}; contact assignment unverified) · <a href={permitPhone.permit.url} target="_blank" rel="noreferrer">{permitPhone.permit.title}</a></p>}
    {!contact && !permitPerson && !permitPhone && <p><strong>Source-listed contact:</strong> Unknown in current buying-chain evidence.</p>}
  </>
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
