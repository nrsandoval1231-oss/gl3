import type { Opportunity, WorkspaceNeed } from '../../api/client'
import { client, type Brief, type BuyingChainResult, type PowerNeedTitle } from '../../api/client'
import { useEffect, useRef, useState } from 'react'
import { projectTitle } from '../opportunities/projectCards'
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
  onTitleReady: () => void
}

export function WorkspaceDetail({ item, pending, loading, error, tab, onTab, onBack, onRetry, onReadback, onTitleReady }: Props) {
  const [brief, setBrief] = useState<Brief | null>(null)
  const [briefBusy, setBriefBusy] = useState(false)
  const [briefError, setBriefError] = useState('')
  const activeBriefNeedId = useRef<string | null>(null)
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
  useEffect(() => {
    const id = item?.id
    activeBriefNeedId.current = id ?? null
    setBrief(null)
    setBriefError('')
    if (!id) return
    let cancelled = false
    void client.brief(id).then(value => { if (!cancelled && activeBriefNeedId.current === id) setBrief(value) })
      .catch((cause: unknown) => { if (!cancelled) setBriefError(cause instanceof Error ? cause.message : 'Brief status is unavailable.') })
    return () => { cancelled = true }
  }, [item?.id])
  useEffect(() => {
    if (!item?.id || brief?.status !== 'pending') return
    const id = item.id
    let cancelled = false
    let timer = 0
    const poll = () => { timer = window.setTimeout(() => {
      void client.brief(id).then(value => {
        if (cancelled || activeBriefNeedId.current !== id) return
        setBrief(value)
        if (value.status === 'pending') poll()
      }).catch((cause: unknown) => { if (!cancelled) setBriefError(cause instanceof Error ? cause.message : 'Brief status is unavailable.') })
    }, 1600) }
    poll()
    return () => { cancelled = true; window.clearTimeout(timer) }
  }, [item?.id, brief?.status])
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
    return <aside className="wh-detail wh-empty-detail" aria-label="Opportunity detail">
      <p>{pending || loading ? 'Loading verified opportunity detail…' : 'Select an opportunity to review its evidence and next action.'}</p>
      {error && <p role="alert">{error} <button onClick={onRetry}>Retry</button></p>}
    </aside>
  }

  const evidence = item.evidence ?? []
  const callEvidence = evidence.find(source => source.assessment_current) ?? evidence[0]
  const company = item.commercial_organization || item.title_company
  const currentTitleReady = titleState?.status === 'ready' && Boolean(titleState.result?.title)
  const titleStatus = titleState?.status ?? item.title_status
  const useDeterministicTitleFallback = ['pending', 'stale', 'failed', 'disabled', 'unavailable'].includes(titleStatus ?? '')
  const canonicalTitleFallback = projectTitle({
    ...item,
    browse_title: item.title_status === 'ready' ? undefined : item.browse_title,
  })
  const displayTitle = currentTitleReady
    ? titleState.result!.title
    : useDeterministicTitleFallback ? canonicalTitleFallback : item.browse_title || canonicalTitleFallback
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
    setBriefBusy(true); setBriefError('')
    try {
      const value = await client.requestBrief(id)
      if (activeBriefNeedId.current === id) setBrief(value)
    } catch (cause) {
      if (activeBriefNeedId.current === id) setBriefError(cause instanceof Error ? cause.message : 'GridLens could not request a brief.')
    } finally { if (activeBriefNeedId.current === id) setBriefBusy(false) }
  }
  const briefContent = brief?.result as { event_summary?: { text: string; evidence_id: string }[]; commercial_hypothesis?: { text: string; evidence_id: string }; unknowns?: string[]; next_step?: string } | null
  const briefStatements = [...(briefContent?.event_summary ?? []), ...(briefContent?.commercial_hypothesis ? [briefContent.commercial_hypothesis] : [])]

  return <aside className="wh-detail" aria-label="Opportunity detail">
    <button className="wh-back" autoFocus onClick={onBack}>← Back to power needs</button>
    <div className="wh-detail-head">
      <span>{item.tier} · {item.commercial_disposition ?? 'Disposition unavailable'}</span>
      <h2>{displayTitle}</h2>
      <p>{item.location ?? 'Location unknown'} · {item.activity}</p>
      {item.tier === 'Signal' && item.commercial_size_status === 'unknown' && <p className="wh-integrity"><strong>Activity size unknown.</strong> Retained for investigation; the 300 kW minimum is inclusive.</p>}
      {item.signal_evidence_state === 'planning_application_withdrawn' && <p className="wh-integrity"><strong>Planning application withdrawn · historical Signal.</strong> Current project viability is unknown.</p>}
      {item.signal_evidence_state === 'planning_status_unknown' && <p className="wh-integrity"><strong>Conflicting planning revision · historical Signal.</strong> Current application and project status are unknown.</p>}
      {item.signal_evidence_state === 'source_listing_absent' && <p className="wh-integrity"><strong>Status review needed.</strong> This filing is no longer in the source current listing; it may have been issued, denied, or withdrawn. Its evidence is retained.</p>}
      {item.group_total_filtered && item.group_total_filtered > 1 && <p className="wh-group-context">Part of a group with {item.group_total_filtered} retained records. Each record and its evidence remain separate and available.</p>}
      <section className="wh-next-action-featured" aria-label="Next action"><div><p className="wh-kicker">Next supported step</p><strong>{item.commercial_next_action || item.next_action || 'Review the retained evidence.'}</strong><p>{item.commercial_next_question || 'Open the evidence and confirm the unresolved project details.'}</p></div><button type="button" onClick={() => onTab('Next steps')}>Open next steps</button></section>
      <details className="wh-source-context"><summary>Source title and organization</summary>{displayTitle !== item.name && <p>Source record: {item.name}</p>}{company && <p>Source-supported organization: {company}{companyRole ? ` · ${companyRole}` : ''}. Listed role does not verify purchasing authority.</p>}</details>
      <div className="wh-facts">
        <span>Required power<strong>{item.required_mw ?? 'Unknown'}</strong><small>{factEvidenceState(item, 'demand')}</small></span>
        <span>Start<strong>{item.start_window ?? 'Unknown'}</strong><small>{factEvidenceState(item, 'start')}</small></span>
        <span>Duration<strong>{item.duration ?? 'Unknown'}</strong><small>{factEvidenceState(item, 'duration')}</small></span>
        <span>Suitable supply<strong>{item.supply ?? 'Unknown'}</strong><small>{factEvidenceState(item, 'supply')}</small></span>
      </div>
      {hasConflict(item.conflict_state) && <p role="status">Evidence conflict state: {item.conflict_state}. Review retained source claims before acting.</p>}
    </div>
    <section className="wh-title-enrichment" aria-label="Evidence-grounded title">
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
    </section>

    <nav ref={tabsRef} className="wh-tabs" aria-label="Opportunity detail">
      {workspaceTabs.map(value => <button key={value} className={value === tab ? 'active' : ''} onClick={() => onTab(value)}>{value}</button>)}
    </nav>
    <div className="wh-detail-content">
      {loading && <p role="status">Loading verified detail…</p>}
      {error && <p role="alert">{error} <button onClick={onRetry}>Retry</button></p>}
      {tab === 'Overview' && <>
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
        <section className="wh-panel wh-brief-panel" aria-label="Concise evidence brief">
          <div className="wh-briefing-head"><div><p className="wh-kicker">AI-assisted · source cited</p><h3>Concise evidence brief</h3></div><span>{brief?.status === 'pending' ? 'Generation pending' : brief?.status === 'stale' ? 'Stale evidence' : brief?.status === 'failed' ? 'Latest request failed' : brief?.generated_at ? `Generated ${new Date(brief.generated_at).toLocaleString()}` : 'Not generated'}</span></div>
          {brief?.status === 'pending' && <p role="status">Generating from retained public evidence…</p>}{briefError && <p role="alert">{briefError}</p>}
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
      {tab === 'Unknowns' && <ul>{unknowns.map(value => <li key={value}>{value}</li>)}</ul>}
    </div>
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
