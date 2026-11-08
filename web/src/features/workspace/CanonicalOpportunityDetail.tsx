import { useEffect, useState } from 'react'
import { client } from '../../api/client'
import { BuyingChain } from '../buyingChain/BuyingChain'
import { WorkspaceDetail, type WorkspaceTab } from './WorkspaceDetail'
import { CalendarDays, ChartNoAxesColumnIncreasing, FileText, Mail, Phone, Target, UserRound, Zap } from 'lucide-react'
import { AddToPursuit } from '../pursuits/AddToPursuit'
import { AUTH_SESSION_ENDED } from '../../state/sessionState'
import './canonical-opportunity-detail.css'

type Props = Parameters<typeof WorkspaceDetail>[0] & { accountFirst?: boolean }
type CanonicalTab = 'Overview' | 'Details' | 'Timeline' | 'Related'
type AccountDetailSource = {
  key: string
  title: string
  url: string | null
  date: string | null
  status: string
  excerpt: string | null
}

function firstSentence(value: string | null | undefined) {
  const text = value?.trim()
  if (!text) return 'No concise assessment is available from the retained evidence.'
  const end = text.search(/[.!?](?:\s|$)/)
  const result = end > 0 ? text.slice(0, end + 1) : text
  return result.length > 260 ? `${result.slice(0, 257).trimEnd()}…` : result
}

function displayDate(value: string | null | undefined) {
  if (!value) return 'Date unavailable'
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (dateOnly) {
    const year = Number(dateOnly[1]), month = Number(dateOnly[2]), day = Number(dateOnly[3])
    const localDate = new Date(year, month - 1, day)
    return localDate.getFullYear() === year && localDate.getMonth() === month - 1 && localDate.getDate() === day ? localDate.toLocaleDateString() : value
  }
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString()
}

type EquipmentDemandProjection = Record<string, unknown>

/** Read the equipment-only demand projection from the retained research card. */
function equipmentDemandProjection(card: NonNullable<Props['item']>['intelligence_card']): EquipmentDemandProjection | null {
  if (!card) return null
  const value = card.equipment_demand
  return value && typeof value === 'object' && !Array.isArray(value) ? value : null
}

/** Format a supported equipment power value, leaving unknown values explicit. */
function equipmentKw(demand: EquipmentDemandProjection | null, key: 'connected_kw' | 'coincident_kw' | 'incremental_kw') {
  const value = demand?.[key]
  const amount = typeof value === 'number' ? value : typeof value === 'string' && value.trim() ? Number(value) : NaN
  if (!Number.isFinite(amount)) return 'Unknown'
  if (amount > 0 && amount < 0.1) return '<0.1 kW'
  return `${amount.toLocaleString(undefined, { maximumFractionDigits: 1 })} kW`
}

/** Load and render selected opportunity detail using the active shortlist query mode. */
export function CanonicalOpportunityDetail(props: Props) {
  const { item, pending, loading, error, associationNotice, tab, onTab, onBack, onRetry, accountFirst = false } = props
  const canonicalTab: CanonicalTab = tabForWorkspace(tab)
  const detailShortlist = new URLSearchParams(window.location.search).get('shortlist') !== '0'
  const [projectState, setProjectState] = useState<{ needId: string | null; project: import('../../api/client').ProjectResult | null; validUntil: string | null }>({ needId: null, project: null, validUntil: null })
  const [projectStatus, setProjectStatus] = useState<{ needId: string | null; loading: boolean; error: string }>({ needId: null, loading: false, error: '' })
  const [projectRefreshNonce, setProjectRefreshNonce] = useState(0)
  const [needRefreshState, setNeedRefreshState] = useState<{ needId: string; item: NonNullable<Props['item']> } | null>(null)
  const needRefreshPending = Boolean(accountFirst && item && needRefreshState?.needId === item.id && needRefreshState.item === item)
  // Do not expose metadata from the previous selection during the render before the effect runs.
  const storedProject = projectState.needId === item?.id ? projectState.project : null
  const storedExpiry = projectState.needId === item?.id && projectState.validUntil ? Date.parse(projectState.validUntil) : NaN
  const project = storedProject && (!accountFirst || (!needRefreshPending && Number.isFinite(storedExpiry) && Date.now() < storedExpiry)) ? storedProject : null
  const projectLoading = projectStatus.needId === item?.id && projectStatus.loading
  const projectExpired = accountFirst && Boolean(storedProject) && Number.isFinite(storedExpiry) && Date.now() >= storedExpiry
  const projectError = projectStatus.needId === item?.id
    ? projectStatus.error || (projectExpired ? 'Prepared project details expired. Current project details are being refreshed.' : '')
    : ''

  useEffect(() => {
    if (!item?.project_id) {
      setProjectState({ needId: item?.id ?? null, project: null, validUntil: null })
      setProjectStatus({ needId: item?.id ?? null, loading: false, error: '' })
      return
    }
    const controller = new AbortController()
    const needId = item.id
    const shortlist = detailShortlist
    const abortForSessionChange = () => controller.abort()
    window.addEventListener(AUTH_SESSION_ENDED, abortForSessionChange)
    window.addEventListener('gl3-clear-continuity', abortForSessionChange)
    setProjectStatus({ needId, loading: true, error: '' })
    const loadProject = async () => {
      try {
        const query = { need_id: needId, sector: 'all' as const, limit: 25, offset: 0, sort: 'priority' as const, shortlist, include_signals: true }
        let page = await client.projectResults(query, controller.signal)
        let match = page.items.find(candidate => candidate.needs.some(need => need.id === needId))
        // A bookmarked legacy need may be outside today's shortlist. Preserve access to its sources.
        if (!match && shortlist && !controller.signal.aborted) {
          page = await client.projectResults({ ...query, shortlist: false }, controller.signal)
          match = page.items.find(candidate => candidate.needs.some(need => need.id === needId))
        }
        if (controller.signal.aborted) return
        const validUntil = typeof page.valid_until === 'string' ? page.valid_until : null
        const validUntilMs = validUntil ? Date.parse(validUntil) : NaN
        const currentPage = !accountFirst || (Number.isFinite(validUntilMs) && Date.now() < validUntilMs)
        const usableMatch = match && currentPage ? match : null
        setProjectState({ needId, project: usableMatch, validUntil: usableMatch ? validUntil : null })
        setProjectStatus({
          needId,
          loading: false,
          error: usableMatch ? '' : match && !currentPage
            ? 'The prepared project view expired before it could be displayed. Retry to load current details.'
            : 'Current project details could not be matched to this opportunity.',
        })
      } catch (cause) {
        if (!controller.signal.aborted) {
          setProjectState({ needId, project: null, validUntil: null })
          setProjectStatus({ needId, loading: false, error: cause instanceof Error ? cause.message : 'Current project details are unavailable.' })
        }
      }
    }
    void loadProject()
    return () => {
      window.removeEventListener(AUTH_SESSION_ENDED, abortForSessionChange)
      window.removeEventListener('gl3-clear-continuity', abortForSessionChange)
      controller.abort()
    }
  }, [item?.id, detailShortlist, projectRefreshNonce])

  useEffect(() => {
    const clearProject = () => {
      setProjectState({ needId: null, project: null, validUntil: null })
      setProjectStatus({ needId: null, loading: false, error: '' })
      setNeedRefreshState(null)
    }
    window.addEventListener('gl3-clear-continuity', clearProject)
    return () => window.removeEventListener('gl3-clear-continuity', clearProject)
  }, [])

  useEffect(() => {
    if (needRefreshState && item?.id !== needRefreshState.needId) setNeedRefreshState(null)
  }, [item?.id, needRefreshState])

  useEffect(() => {
    if (!accountFirst || !item?.id || !project || !projectState.validUntil) return
    const expiry = Date.parse(projectState.validUntil)
    if (!Number.isFinite(expiry)) return
    const maximumTimerDelay = 2_147_000_000
    let timer = 0
    const checkExpiry = () => {
      const remaining = expiry - Date.now()
      if (remaining > 0) {
        timer = window.setTimeout(checkExpiry, Math.min(remaining, maximumTimerDelay))
        return
      }
      setProjectState(current => current.needId === item.id ? { needId: item.id, project: null, validUntil: null } : current)
      setProjectStatus({ needId: item.id, loading: true, error: '' })
      setProjectRefreshNonce(value => value + 1)
      setNeedRefreshState({ needId: item.id, item })
      onRetry()
    }
    timer = window.setTimeout(checkExpiry, Math.min(Math.max(0, expiry - Date.now()), maximumTimerDelay))
    return () => window.clearTimeout(timer)
  }, [accountFirst, item, project, projectState.validUntil, onRetry])

  const retryProject = () => {
    if (item?.id) setProjectStatus({ needId: item.id, loading: true, error: '' })
    if (item?.id && item) setNeedRefreshState({ needId: item.id, item })
    setProjectRefreshNonce(value => value + 1)
    onRetry()
  }

  if (!item) return <aside className="cod-panel" aria-label="Opportunity detail">
    {(pending || loading || error) && <button type="button" className="cod-back" onClick={onBack}>{accountFirst ? '← Back to account' : 'Opportunities'}</button>}
    <p>{pending || loading ? 'Loading verified opportunity detail…' : accountFirst ? 'Select a project to review.' : 'Select an opportunity to review its evidence and next action.'}</p>
    {error && <p role="alert">{error} <button type="button" onClick={onRetry}>Retry</button></p>}
  </aside>
  if (!accountFirst && (tab === 'Evidence' || tab === 'Power gap' || tab === 'Research')) return <WorkspaceDetail {...workspaceDetailProps(props)} />

  const card = item.intelligence_card
  const equipmentDemand = equipmentDemandProjection(card)
  const fields = card?.fields ?? []
  const field = (key: string) => fields.find(candidate => candidate.key === key && candidate.value)
  const company = project?.company?.trim() || item.commercial_organization || item.title_company || null
  const fullTitle = project?.name || item.browse_title || item.name
  const title = company && fullTitle.startsWith(`${company} · `) ? fullTitle.slice(company.length + 3) : fullTitle
  const location = project?.location || item.location || field('location')?.value || null
  const accountSummarySource = item.commercial_reason || item.assessment_reason
  const summary = accountFirst
    ? project && accountSummarySource ? firstSentence(accountSummarySource) : null
    : firstSentence(item.commercial_reason || item.assessment_reason || item.rationale)
  const facilityDemand = field('facility_demand')
  const rawDemand = item.required_mw || facilityDemand?.value
  const demand = rawDemand
  const qualifiedGap = item.qualified_remaining_gap && typeof item.qualified_remaining_gap === 'object' ? item.qualified_remaining_gap as Record<string, unknown> : null
  const qualifiedMin = typeof qualifiedGap?.remaining_mw_min === 'string' ? qualifiedGap.remaining_mw_min : null
  const qualifiedMax = typeof qualifiedGap?.remaining_mw_max === 'string' ? qualifiedGap.remaining_mw_max : null
  const cardGap = card?.power_gap && typeof card.power_gap === 'object' ? card.power_gap as Record<string, unknown> : null
  const cardGapRemaining = typeof cardGap?.remaining_mw === 'string' && !/^(not established|unknown|unavailable)$/i.test(cardGap.remaining_mw.trim()) ? cardGap.remaining_mw : null
  const gap = qualifiedMin && qualifiedMax ? `${qualifiedMin}–${qualifiedMax} MW` : cardGapRemaining
  const gapBasis = qualifiedMin && qualifiedMax
    ? `${typeof qualifiedGap?.value_kind === 'string' ? qualifiedGap.value_kind : 'Supported'} qualification`
    : cardGapRemaining ? (typeof cardGap?.status === 'string' ? cardGap.status.replaceAll('_', ' ') : 'Source-reported estimate') : 'Not established · gap unknown'
  const timing = item.start_window || null
  const metrics = [
    { label: 'Power Need', value: demand || '—', basis: item.required_mw ? 'Activity-specific power requirement' : facilityDemand ? `${facilityDemand.status} · facility demand` : 'Not established · power requirement unknown', icon: 'demand' },
    { label: 'Power Gap', value: gap || '—', basis: gapBasis, icon: 'gap' },
    { label: 'Power timing', value: timing || '—', basis: timing ? 'Power timing from retained assessment' : 'Not established · timing unknown', icon: 'calendar' },
  ]
  const people = card?.contacts ?? []
  const renderedContactHrefs = new Set(people.flatMap(person => contactChannels(person.methods ?? [], person.sources ?? []).map(channel => normalizeContactHref(channel.href))))
  const evidence = item.evidence ?? []
  const sources = evidence.slice().sort((a, b) => (b.event_date || b.published_at || '').localeCompare(a.event_date || a.published_at || ''))
  const accountSources = accountFirst ? accountDetailSources(item, project) : []
  const additionalCardEvidence = (card?.evidence ?? []).filter(source => {
    const href = safeSourceUrl(source.url)
    return Boolean(href && !sources.some(itemSource => safeSourceUrl(itemSource.url) === href))
  }).slice(0, 2)
  const nextAction = item.tier === 'Signal' && (item.commercial_disposition ?? card?.disposition) === 'WATCH'
    ? 'Continue monitoring for verified power demand.'
    : item.commercial_next_action || item.next_action || item.commercial_next_question || project?.next_action || 'Review retained evidence and confirm the unresolved details.'
  const assetType = project?.asset_type?.replaceAll('_', ' ') || field('project_type')?.value || null
  const eyebrow = assetType || item.activity || null
  const currentSources = sources.filter(source => source.assessment_current === true).length
  const evidenceSummary = sources.length ? `${sources.length} evidence record${sources.length === 1 ? '' : 's'}${currentSources ? ` · ${currentSources} current` : ''}` : null
  const essentialDetails = [
    ['Company', company], ['Project type', assetType], ['Project scale', field('site_size')?.value], ['Evidence summary', evidenceSummary],
  ].filter((entry): entry is [string, string] => Boolean(entry[1]?.trim()))
  const moreDetails = [
    ['Project', title], ['Location', location],
    ['Power timing', item.start_window], ['Milestone date', project?.event?.date], ['Site status', item.lifecycle_state?.replaceAll('_', ' ') || field('site_status')?.value],
    ['Grid proximity', field('grid_proximity')?.value], ['Utility status', field('utility_status')?.value],
    ['Site control', field('site_control')?.value], ['Estimated project value', field('project_value')?.value],
    ['Development partner', field('development_partner')?.value],
    ['Last updated', card?.last_intelligence_update ? displayDate(card.last_intelligence_update) : null],
  ].filter((entry): entry is [string, string] => Boolean(entry[1]?.trim()))

  if (accountFirst) {
    const supportedPower = item.required_mw?.trim() || null
    const facilityDemandValue = facilityDemand?.value?.trim() || null
    const hasConflict = Boolean(item.conflict_state && /conflict/i.test(item.conflict_state))
    const hasHistoricalSupport = accountSources.some(source => /historical|withdrawn|superseded/i.test(source.status))
    const hasCurrentSupport = accountSources.some(source => /current|verified/i.test(source.status))
    const projectQualification = !project ? null : hasConflict
      ? `Current evidence is conflicting (${item.conflict_state}); review the source records before acting.`
      : hasHistoricalSupport && !hasCurrentSupport
        ? 'The available source support is historical; confirm it before acting.'
        : null
    const accountPeople = project ? people : []
    const selectedContact = accountPeople.find(person => contactChannels(person.methods ?? [], person.sources ?? []).length > 0) ?? accountPeople[0]
    const contactMethods = selectedContact
      ? prioritizePrimaryChannels(contactChannels(selectedContact.methods ?? [], selectedContact.sources ?? []))
      : []
    const phone = contactMethods.find(channel => channel.kind === 'phone')
    const email = contactMethods.find(channel => channel.kind === 'email')
    const renderedContactHrefs = new Set(contactMethods.map(channel => normalizeContactHref(channel.href)))
    const companyRoutes = (project?.contact ?? []).flatMap(action => {
      if (action.route_kind !== 'company_route') return []
      const href = safeContactAction(action.kind, action.href)
      const normalized = href ? normalizeContactHref(href) : ''
      if (!href || !normalized || renderedContactHrefs.has(normalized)) return []
      renderedContactHrefs.add(normalized)
      return [{ ...action, href }]
    })
    const explicitSources = tab === 'Evidence' || tab === 'Research' || tab === 'Timeline' || tab === 'Buying chain'

    return <aside className="cod-panel cod-account-first-detail" aria-label="Opportunity detail">
      <div className="cod-heading">
        <button type="button" className="cod-back" onClick={onBack}>← Back to account</button>
        <div className="cod-title-row"><div>
          <p className="cod-kicker">Project</p>
          <h2>{title}</h2>
          {(location || project?.event?.label) && <p className="cod-location">{[location, project?.event?.label, project?.event?.date ? displayDate(project.event.date) : null].filter(Boolean).join(' · ')}</p>}
        </div></div>
      </div>
      {(projectLoading || (needRefreshPending && loading)) && <p className="cod-status" role="status">Refreshing current project and opportunity details…</p>}
      {(projectError || error) && <p className="cod-status" role="alert">{projectError || error} <button type="button" onClick={retryProject}>Retry</button></p>}
      {associationNotice && <p className="cod-status" role="status">{associationNotice}</p>}
      {projectQualification && <p className="cod-status" role="status">{projectQualification}</p>}
      {summary && <section className="cod-why" aria-label="Why this project matters"><p>{summary}</p></section>}
      {project && (item.commercial_next_action || item.next_action) ? <section className="cod-next-action" aria-label="Recommended next action"><Target size={17} aria-hidden="true"/><div><strong>Next step</strong><p>{item.commercial_next_action || item.next_action}</p></div></section> : null}
      {project && (supportedPower || facilityDemandValue || timing) && <section className="cod-details cod-account-power" aria-label="Supported power and timing">
        <h3>Project scope</h3>
        <dl>{supportedPower && <div><dt>Activity-specific power need</dt><dd>{supportedPower}</dd></div>}
          {!supportedPower && facilityDemandValue && <div><dt>Facility demand · source reported</dt><dd>{facilityDemandValue}{facilityDemand?.status ? ` · ${facilityDemand.status}` : ''}</dd></div>}
          {timing && <div><dt>Power timing</dt><dd>{timing}</dd></div>}
        </dl>
      </section>}
      {project && <section className="cod-contacts" aria-label="Project contact">
        <h3><UserRound size={14} aria-hidden="true"/>Contact</h3>
        {selectedContact ? <article>
          <div className="cod-contact-row"><div className="cod-contact-id">
            <strong>{selectedContact.name || selectedContact.company}</strong>
            <p>{[selectedContact.title || selectedContact.role, selectedContact.name ? selectedContact.company : null].filter(Boolean).join(' · ')}</p>
          </div><div className="cod-contact-buttons">
            {phone && <a className="cod-contact-button" href={phone.href} aria-label={`Call ${phone.value}`}><Phone size={14} aria-hidden="true"/>Call</a>}
            {email && <a className="cod-contact-button" href={email.href} aria-label={`Email ${email.value}`}><Mail size={14} aria-hidden="true"/>Email</a>}
          </div></div>
          {(phone || email) && <ul className="cod-contact-methods">{phone && <li><span>{phone.value}</span><small>{phone.verifiedAt ? `Source checked ${displayDate(phone.verifiedAt)}` : 'Public-source method; deliverability and authority are unconfirmed.'}</small></li>}{email && <li><span>{email.value}</span><small>{email.verifiedAt ? `Source checked ${displayDate(email.verifiedAt)}` : 'Public-source method; deliverability and authority are unconfirmed.'}</small></li>}</ul>}
          {companyRoutes.map(action => <p className="cod-company-route" key={`${action.kind}:${action.href}`}><strong>{action.kind === 'call' ? 'Company phone' : action.kind === 'email' ? 'Company email' : 'Company contact page'}</strong> <a href={action.href} target={action.kind === 'contact' ? '_blank' : undefined} rel={action.kind === 'contact' ? 'noreferrer' : undefined}>{action.label}</a></p>)}
        </article> : companyRoutes.length ? <article>{companyRoutes.map(action => <p className="cod-company-route" key={`${action.kind}:${action.href}`}><strong>{action.kind === 'call' ? 'Company phone' : action.kind === 'email' ? 'Company email' : 'Company contact page'}</strong> <a href={action.href} target={action.kind === 'contact' ? '_blank' : undefined} rel={action.kind === 'contact' ? 'noreferrer' : undefined}>{action.label}</a></p>)}</article> : <p className="cod-contact-missing">No appropriate business phone or email is available in retained contact evidence.</p>}
      </section>}
      <details className="cod-more-details cod-account-sources" open={explicitSources}>
        <summary>Sources ({accountSources.length})</summary>
        {accountSources.length ? accountSources.map(source => <article className="cod-related-source" key={source.key}>
          {source.url ? <a href={source.url} target="_blank" rel="noreferrer">{source.title}</a> : <strong>{source.title}</strong>}
          <span>{source.date ? displayDate(source.date) : 'Date unavailable'} · {source.status}</span>
          {source.excerpt && <p>{source.excerpt}</p>}
        </article>) : <p>No project-scoped source records are available.</p>}
      </details>
      {project && <AddToPursuit key={item.id} needId={item.id}/>}
      {tab === 'Power gap' && <p className="cod-status">Only retained, supported project scope is shown above. Facility demand is not a rental-gap estimate.</p>}
    </aside>
  }

  return <aside className="cod-panel" aria-label="Opportunity detail">
    <div className="cod-heading">
      <button type="button" className="cod-back" onClick={onBack}>← Opportunities</button>
      <div className="cod-title-row">
        <div>{eyebrow && <p className="cod-kicker">{eyebrow}</p>}<span className="cod-tier">{item.tier || 'Opportunity'}</span><h2>{company && company !== title ? <>{company} <span>— {title}</span></> : title}</h2>
          <p className="cod-location">{location || 'Location not established'}{project?.event?.label ? ` · ${project.event.label}${project.event.date ? ` · ${project.event.date}` : ''}` : ''}</p>
        </div>
      </div>
    </div>

    <nav className="cod-tabs" aria-label="Project detail sections">
      {(['Overview', 'Details', 'Timeline', 'Related'] as const).map(value => <button key={value} type="button" aria-pressed={canonicalTab === value} className={canonicalTab === value ? 'active' : ''} onClick={() => onTab(workspaceTabFor(value))}>{value}</button>)}
    </nav>
    {canonicalTab !== 'Overview' && <p className="cod-summary">{summary}</p>}
    {projectLoading && <p className="cod-status" role="status">Loading current project details…</p>}
    {projectError && <p className="cod-status" role="alert">{projectError} <button type="button" onClick={onRetry}>Retry</button></p>}
    {associationNotice && <p className="cod-status" role="status">{associationNotice}</p>}

    {canonicalTab === 'Overview' && <>
      <div className="cod-overview-body">
      <section className="cod-metrics" aria-label="Power metrics">{metrics.map(metric => <article key={metric.label}>
        <span className="cod-metric-icon" aria-hidden="true">{metric.icon === 'demand' ? <Zap size={16} strokeWidth={1.6}/> : metric.icon === 'gap' ? <ChartNoAxesColumnIncreasing size={16} strokeWidth={1.6}/> : <CalendarDays size={16} strokeWidth={1.6}/>}</span>
        <div><strong title={metric.value} aria-label={metric.value}>{metric.value}</strong><span className="cod-metric-label">{metric.label}</span><small>{metric.basis}</small></div>
      </article>)}</section>
      <section className="cod-why" aria-label="Why this matters"><h3>Why this matters</h3><p>{summary}</p></section>
      <section className="cod-details" aria-label="Key project details"><h3>Key Details</h3>
        {essentialDetails.length ? <dl>{essentialDetails.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl> : <p>Project details are not established by current evidence.</p>}
        {moreDetails.length > 0 && <details className="cod-more-details"><summary>More details</summary><dl>{moreDetails.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl></details>}
      </section>
      {equipmentDemand && (() => {
        const demand = equipmentDemand.demand && typeof equipmentDemand.demand === 'object' && !Array.isArray(equipmentDemand.demand) ? equipmentDemand.demand as EquipmentDemandProjection : null
        const label = (value: unknown) => typeof value === 'string' ? value.replaceAll('_', ' ') : 'Unavailable'
        const lifecycle = Array.isArray(equipmentDemand.lifecycle) ? equipmentDemand.lifecycle.filter((value): value is string => typeof value === 'string' && value.length > 0) : []
        const plannedStates = lifecycle.filter(value => ['new', 'proposed'].includes(value.toLowerCase()))
        const plannedOnly = lifecycle.length > 0 && plannedStates.length === lifecycle.length
        const capacityLabel = (value: string) => plannedOnly ? `Planned ${value}` : plannedStates.length ? `${value} (includes planned equipment)` : value
        const expectedStarts = Array.isArray(equipmentDemand.expected_start) ? equipmentDemand.expected_start.filter((value): value is string => typeof value === 'string' && Boolean(value.trim())).map(displayDate) : []
        const asOf = typeof equipmentDemand.as_of === 'string' ? displayDate(equipmentDemand.as_of) : 'Unknown'
        const nativeProposal = equipmentDemand.scope === 'identified_equipment_assertion'
        const equipmentHeading = nativeProposal ? 'Source-reported equipment proposal' : 'Equipment schedule demand'
        const sourceAssertions = nativeProposal && Array.isArray(equipmentDemand.equipment) ? equipmentDemand.equipment.flatMap(value => value && typeof value === 'object' && typeof value.quote === 'string' && value.quote.trim() ? [value.quote] : []) : []
        return <details className="cod-equipment-demand"><summary>Equipment demand</summary><section aria-label={equipmentHeading}><h3>{equipmentHeading}</h3><p>{nativeProposal ? 'Historical source assertion. Current status and site demand remain unverified.' : 'Schedule-level capacity figures · not a site or portfolio total or metered demand.'}</p>{sourceAssertions.map((quote, index) => <p key={index}><strong>Equipment reported by source:</strong> {quote}</p>)}<dl><div><dt>Classification</dt><dd>{label(equipmentDemand.classification)}</dd></div><div><dt>Status</dt><dd>{label(equipmentDemand.status)}</dd></div><div><dt>Scope</dt><dd>{label(equipmentDemand.scope)}</dd></div><div><dt>Equipment state / lifecycle</dt><dd>{lifecycle.map(label).join(', ') || 'Unknown'}</dd></div><div><dt>{nativeProposal ? 'Source proposal as of' : 'Schedule as of'}</dt><dd>{asOf}</dd></div><div><dt>Documented expected start</dt><dd>{expectedStarts.join(', ') || 'Unknown'}</dd></div><div><dt>{capacityLabel('connected capacity')}</dt><dd>{equipmentKw(demand, 'connected_kw')}</dd></div><div><dt>{capacityLabel('coincident operating capacity')}</dt><dd>{equipmentKw(demand, 'coincident_kw')}</dd></div><div><dt>{plannedStates.length ? 'Planned incremental capacity' : 'Incremental capacity'}</dt><dd>{equipmentKw(demand, 'incremental_kw')}</dd></div></dl>{typeof equipmentDemand.next_action === 'string' && equipmentDemand.next_action.trim() && <p className="cod-equipment-next-action"><strong>Equipment next action:</strong> {equipmentDemand.next_action}</p>}</section></details>
      })()}
      <div className="cod-lower">
        <section className="cod-contacts" aria-label="Decision maker or contact"><h3><UserRound size={13} strokeWidth={1.6}/>Key Contacts</h3>
          {people.length ? people.map(person => {
            const channels = contactChannels(person.methods ?? [], person.sources ?? [])
            const primary = prioritizePrimaryChannels(channels)
            const phone = primary.find(channel => channel.kind === 'phone')
            const email = primary.find(channel => channel.kind === 'email')
            const extraSources = (person.sources ?? []).filter(source => !sources.some(itemSource => safeSourceUrl(itemSource.url) && safeSourceUrl(itemSource.url) === safeSourceUrl(source.url)))
            const note = (channel: typeof primary[number]) => channel.verifiedAt ? `Source checked ${displayDate(channel.verifiedAt)}` : <>Verification not established · <a href={channel.sourceUrl} target="_blank" rel="noreferrer">{channel.sourceTitle}</a></>
            return <article key={person.claim_id}>
            <div className="cod-contact-row">
              <div className="cod-contact-id"><strong>{person.name || person.company}</strong>
                <p>{[person.title || person.role, person.name ? person.company : null].filter(Boolean).join(' · ')}</p></div>
              {(phone || email) && <div className="cod-contact-buttons">
                {phone && <a className="cod-contact-button" href={phone.href} aria-label={`Call ${phone.value}`}><Phone size={14} strokeWidth={1.8} aria-hidden="true"/>Call</a>}
                {email && <a className="cod-contact-button" href={email.href} aria-label={`Email ${email.value}`}><Mail size={14} strokeWidth={1.8} aria-hidden="true"/>Email</a>}
              </div>}
            </div>
            {(phone || email) ? <ul className="cod-contact-methods">
              {phone && <li><span>{phone.value}</span><small>{note(phone)}</small></li>}
              {email && <li><span>{email.value}</span><small>{note(email)}</small></li>}
            </ul> : <p className="cod-contact-missing">No verified phone or email is available in retained contact evidence.</p>}
            <details className="cod-contact-more"><summary>{phone || email ? 'More' : 'Inspect contact evidence'}</summary>
              {person.responsibility && <p>{person.responsibility}</p>}
              <p>Purchasing authority: {person.purchasing_authority?.trim() || 'Authority not established'}</p>
              {primary.slice(2).map(channel => <span className="cod-verified-method" key={`${channel.kind}:${channel.value}`}><a href={channel.href}>{channel.kind === 'email' ? 'Email' : 'Call'} {channel.value}</a><small>{note(channel)}</small></span>)}
              {!phone && <small>Phone unavailable in retained contact evidence.</small>}
              {!email && <small>Email unavailable in retained contact evidence.</small>}
              {extraSources.map(source => safeSourceUrl(source.url) && <a key={`${source.reference}:${source.url}`} href={safeSourceUrl(source.url)!} target="_blank" rel="noreferrer">Contact source: {source.title}</a>)}
            </details>
          </article>}) : <p>No decision-maker or public company contact is available in retained evidence.</p>}
          {(project?.contact ?? []).filter(action => action.route_kind === 'company_route').map(action => {
            const href = safeContactAction(action.kind, action.href)
            const normalizedHref = href ? normalizeContactHref(href) : ''
            if (!href || !normalizedHref || renderedContactHrefs.has(normalizedHref)) return null
            renderedContactHrefs.add(normalizedHref)
            return <p className="cod-company-route" key={`${action.kind}:${href}`} title={[action.responsibility, action.support].filter(Boolean).join(' · ') || undefined}><strong>{action.kind === 'call' ? 'Company phone' : action.kind === 'email' ? 'Company email' : 'Company contact path'}</strong> <a href={href} target={action.kind === 'contact' ? '_blank' : undefined} rel={action.kind === 'contact' ? 'noreferrer' : undefined}>{action.label}</a></p>
          })}
        </section>
        <section className="cod-evidence" aria-label="Recent evidence"><h3><FileText size={13} strokeWidth={1.6}/>Evidence ({sources.length + additionalCardEvidence.length})</h3>
          {sources.length ? sources.slice(0, 4).map(source => safeSourceUrl(source.url) && <a className="cod-evidence-row" key={`${source.id}:${source.content_hash}`} href={safeSourceUrl(source.url)!} target="_blank" rel="noreferrer"><span>{source.title}</span><time title={source.event_date ? `${source.event_date_label}: ${source.event_date}` : `Published: ${source.published_at || "Unknown"}`}>{displayDate(source.event_date || source.published_at)}</time><small className="cod-source-status">{source.assessment_current === true ? "Current support" : source.assessment_current === false ? "Historical" : "Status unavailable"}</small></a>) : <p>No dated evidence is attached to this opportunity.</p>}
          {additionalCardEvidence.map(source => <a className="cod-evidence-row" key={source.reference} href={safeSourceUrl(source.url)!} target="_blank" rel="noreferrer"><span>{source.title}</span><time>{source.source_date || 'Date unavailable'}</time><small className="cod-source-status">{source.verification_status || "Status unavailable"}</small></a>)}
        </section>
      </div>
      <button type="button" className="cod-view-all-evidence" onClick={() => onTab('Evidence')}>View all evidence</button>
      <section className="cod-next-action" aria-label="Recommended next action"><Target size={19} strokeWidth={1.6}/><div><strong>Next Action</strong><p>{nextAction}</p></div><button type="button" onClick={() => onTab('Research')}>View research</button></section>
      </div>
      <AddToPursuit key={item.id} needId={item.id}><button type="button" className="cod-action-secondary" onClick={() => onTab('Evidence')}>View Details</button></AddToPursuit>
    </>}

    {canonicalTab === 'Details' && <section className="cod-tab-content">
      <h3>Project details</h3>
      <p>{summary}</p>
      <dl className="cod-intelligence-facts">{metrics.map(metric => <div key={metric.label}><dt>{metric.label}</dt><dd>{metric.value}<small>{metric.basis}</small></dd></div>)}</dl>
      {card?.fields.filter(value => value.value).map(value => <article className="cod-fact" key={value.key}><strong>{value.label}</strong><p>{value.value}</p><small>{value.status} · {value.basis}</small>{value.sources?.map(source => safeSourceUrl(source.url) && <a key={source.reference} href={safeSourceUrl(source.url)!} target="_blank" rel="noreferrer">{source.title}{source.source_date ? ` · ${source.source_date}` : ''}</a>)}</article>)}
      {card?.research_gaps?.length ? <p>{card.research_gaps.length} evidence gap{card.research_gaps.length === 1 ? '' : 's'} remain under automated research.</p> : null}
    </section>}

    {canonicalTab === 'Timeline' && <section className="cod-tab-content"><h3>Timeline</h3>
      {project?.event && <article className="cod-timeline-event"><time>{displayDate(project.event.date)}</time><strong>{project.event.label}</strong><span>{project.event.kind.replaceAll('_', ' ')}</span></article>}
      {sources.map(source => <article className="cod-timeline-event" key={source.id}><time>{displayDate(source.event_date || source.published_at)}</time>{safeSourceUrl(source.url) ? <a href={safeSourceUrl(source.url)!} target="_blank" rel="noreferrer">{source.title}</a> : <strong>{source.title}</strong>}<span>{source.event_date_label || source.source_origin}</span></article>)}
      {!project?.event && !sources.length && <p>No dated milestones or evidence are currently available.</p>}
    </section>}

    {canonicalTab === 'Related' && <section className="cod-tab-content"><h3>Related records</h3>
      {item.project_id ? <BuyingChain projectId={item.project_id} /> : <p>Project identity is not established, so related buying-chain records are unavailable.</p>}
      {project?.needs.filter(need => need.id !== item.id).length ? <section aria-label="Other source-backed records"><h4>Other source-backed records</h4>{project.needs.filter(need => need.id !== item.id).map(need => <button className="cod-related-need" type="button" key={need.id} onClick={() => dispatchEvent(new CustomEvent('gl3-open-need', { detail: need.id }))}>{need.browse_title || need.name || need.activity || 'Open related source-backed record'}{need.location ? ` · ${need.location}` : ''}</button>)}</section> : null}
      <h4>Sources</h4>{sources.length ? sources.map(source => <article className="cod-related-source" key={source.id}>{safeSourceUrl(source.url) ? <a href={safeSourceUrl(source.url)!} target="_blank" rel="noreferrer">{source.title}</a> : <strong>{source.title}</strong>}<span>{displayDate(source.event_date || source.published_at)} · {source.source_origin} · {source.assessment_current === true ? 'Current support' : source.assessment_current === false ? 'Historical support' : 'Support status unavailable'}</span><p>{source.abstract || 'No source summary is available.'}</p></article>) : <p>No source records are attached.</p>}
      <section aria-label="What's missing" className="cod-whats-missing"><h4>What’s missing</h4>{card?.research_gaps?.length ? <ul>{card.research_gaps.map(gap => <li key={gap.key}>{gap.label}</li>)}</ul> : item.missing_facts?.length ? <ul>{item.missing_facts.map(gap => <li key={gap}>{gap}</li>)}</ul> : <p>No explicit research gaps are recorded for this opportunity.</p>}</section>
    </section>}
  </aside>
}

/** Map legacy workspace detail tabs to the canonical detail navigation. */
function tabForWorkspace(tab: WorkspaceTab): CanonicalTab {
  if (tab === 'Timeline') return 'Timeline'
  if (tab === 'Evidence' || tab === 'Buying chain') return 'Related'
  if (tab === 'Unknowns' || tab === 'Power gap') return 'Details'
  return 'Overview'
}

/** Map canonical detail tabs back to the workspace detail interface. */
function workspaceTabFor(tab: CanonicalTab): WorkspaceTab {
  if (tab === 'Timeline') return 'Timeline'
  if (tab === 'Related') return 'Buying chain'
  if (tab === 'Details') return 'Unknowns'
  return 'Overview'
}

function safeSourceUrl(value: string | null | undefined): string | null {
  if (!value) return null
  try {
    const url = new URL(value)
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null
  } catch { return null }
}

/** Plain address only: no `%`, `?`, `&`, `=`, separators, whitespace, quotes or angle brackets, so a mailto: href cannot carry headers or encoded line breaks. */
const STRICT_EMAIL = /^[A-Za-z0-9._+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,63}$/

function contactChannels(methods: { [key: string]: string }[], sources: NonNullable<NonNullable<Props['item']>['intelligence_card']>['contacts'][number]['sources']) {
  const channels = new Map<string, { kind: 'phone' | 'email'; value: string; href: string; sourceTitle: string; sourceUrl: string; verifiedAt?: string }>()
  for (const method of methods) {
    const kind = /^(phone|telephone|call)$/i.test(method.kind || '') ? 'phone' : /^email$/i.test(method.kind || '') ? 'email' : null
    const value = method.value?.trim()
    if (!kind || !value) continue
    const valid = kind === 'phone'
      ? /^[+()\d][\d\s().-]{5,}$/.test(value) && (value.match(/\d/g)?.length ?? 0) >= 7
      : STRICT_EMAIL.test(value)
    if (!valid) continue
    const sourceUrl = safeSourceUrl(method.source_url)
    const methodSource = (sources ?? []).find(source => source.verification_status === 'Current retained support' && safeSourceUrl(source.url) === sourceUrl)
    const verifiedAt = method.verified_at && !Number.isNaN(Date.parse(method.verified_at)) ? method.verified_at : undefined
    if (!verifiedAt && (!methodSource || !sourceUrl)) continue
    const key = `${kind}:${value.toLowerCase()}`
    if (!channels.has(key)) channels.set(key, {
      kind, value, href: kind === 'phone' ? `tel:${value.replace(/[^+\d]/g, '')}` : `mailto:${value}`,
      sourceTitle: methodSource?.title ?? '', sourceUrl: sourceUrl ?? '', ...(verifiedAt ? { verifiedAt } : {}),
    })
  }
  return [...channels.values()]
}

function safeContactAction(kind: string, href: string | null | undefined): string | null {
  if (!href || /[\u0000-\u001f]/.test(href)) return null
  if (kind === 'call' && /^tel:\+?[0-9]{7,15}$/i.test(href)) return href
  if (kind === 'email' && href.length > 7 && STRICT_EMAIL.test(href.slice(7))) return href
  if (kind === 'contact') return safeSourceUrl(href)
  return null
}

function normalizeContactHref(href: string): string {
  if (href.toLowerCase().startsWith('mailto:')) return `mailto:${href.slice(7).toLowerCase()}`
  if (href.toLowerCase().startsWith('tel:')) return `tel:${href.slice(4).replace(/[^+\d]/g, '')}`
  try {
    const url = new URL(href)
    url.hash = ''
    url.pathname = url.pathname.replace(/\/$/, '') || '/'
    return url.href.toLowerCase()
  } catch { return href }
}

function prioritizePrimaryChannels<T extends { kind: 'phone' | 'email' }>(channels: T[]): T[] {
  const primaryPhone = channels.find(channel => channel.kind === 'phone')
  const primaryEmail = channels.find(channel => channel.kind === 'email')
  const primary = new Set([primaryPhone, primaryEmail])
  return [...[primaryPhone, primaryEmail].filter((channel): channel is T => Boolean(channel)), ...channels.filter(channel => !primary.has(channel))]
}

function workspaceDetailProps(props: Props): Props {
  const item = props.item
  if (!item) return props
  const safeSources = <T extends { url?: string | null }>(sources: T[] | undefined): T[] => (sources ?? []).filter(source => Boolean(safeSourceUrl(source.url)))
  const card = item.intelligence_card ? {
    ...item.intelligence_card,
    evidence: safeSources(item.intelligence_card.evidence),
    fields: item.intelligence_card.fields.map(field => ({ ...field, sources: safeSources(field.sources) })),
    contacts: item.intelligence_card.contacts.map(contact => ({ ...contact, sources: safeSources(contact.sources) })),
  } : item.intelligence_card
  return { ...props, item: { ...item, evidence: safeSources(item.evidence), intelligence_card: card } }
}

function accountDetailSources(
  item: NonNullable<Props['item']>,
  project: import('../../api/client').ProjectResult | null,
): AccountDetailSource[] {
  const sources = new Map<string, AccountDetailSource>()
  const add = (source: {
    id?: string | null
    reference?: string | null
    retained_evidence_id?: string | null
    content_hash?: string | null
    title?: string | null
    url?: string | null
    source_date?: string | null
    published_at?: string | null
    event_date?: string | null
    assessment_current?: boolean | null
    verification_status?: string | null
    status?: string | null
    abstract?: string | null
    source_origin?: string | null
  }) => {
    const title = source.title?.trim()
    if (!title) return
    const url = safeSourceUrl(source.url)
    const date = source.event_date || source.source_date || source.published_at || null
    const status = source.assessment_current === true
      ? 'Current support'
      : source.assessment_current === false
        ? 'Historical support'
        : source.verification_status || source.status || 'Support status unavailable'
    const versionKey = source.content_hash || source.retained_evidence_id || date || title
    const identity = url ? `${url}:${versionKey}` : `${source.reference || source.id || title}:${versionKey}`
    if (sources.has(identity)) return
    sources.set(identity, {
      key: identity,
      title,
      url,
      date,
      status,
      excerpt: source.abstract || source.source_origin || null,
    })
  }

  for (const source of item.evidence ?? []) add(source)
  for (const source of item.intelligence_card?.evidence ?? []) add(source)
  for (const field of item.intelligence_card?.fields ?? []) {
    for (const source of field.sources ?? []) add(source)
  }
  for (const contact of item.intelligence_card?.contacts ?? []) {
    for (const source of contact.sources ?? []) add(source)
  }
  if (project?.event?.source) {
    add({
      reference: `project-event:${project.event.kind}:${project.event.date ?? ''}`,
      title: project.event.label,
      url: project.event.source,
      source_date: project.event.date,
      status: 'Project event reference',
    })
  }
  return [...sources.values()].sort((a, b) => (b.date || '').localeCompare(a.date || '') || a.title.localeCompare(b.title))
}
