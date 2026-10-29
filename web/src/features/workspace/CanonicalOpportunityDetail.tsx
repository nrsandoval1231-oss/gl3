import { useEffect, useState } from 'react'
import { client } from '../../api/client'
import { BuyingChain } from '../buyingChain/BuyingChain'
import { WorkspaceDetail, type WorkspaceTab } from './WorkspaceDetail'
import { CalendarDays, ChartNoAxesColumnIncreasing, FileText, Target, UserRound, Zap } from 'lucide-react'
import './canonical-opportunity-detail.css'

type Props = Parameters<typeof WorkspaceDetail>[0]
type CanonicalTab = 'Overview' | 'Intelligence' | 'Timeline' | 'Related'

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

export function CanonicalOpportunityDetail(props: Props) {
  const { item, pending, loading, error, associationNotice, tab, onTab, onBack, onRetry } = props
  const canonicalTab: CanonicalTab = tabForWorkspace(tab)
  const [project, setProject] = useState<import('../../api/client').ProjectResult | null>(null)
  const [projectLoading, setProjectLoading] = useState(false)
  const [projectError, setProjectError] = useState('')

  useEffect(() => {
    if (!item?.project_id) { setProject(null); setProjectLoading(false); return }
    const controller = new AbortController()
    setProjectLoading(true)
    setProjectError('')
    client.projectResults({ need_id: item.id, sector: 'all', limit: 1, offset: 0, sort: 'priority' }, controller.signal)
      .then(page => {
        if (controller.signal.aborted) return
        const match = page.items.find(candidate => candidate.needs.some(need => need.id === item.id))
        setProject(match ?? null)
        if (!match) setProjectError('Current project details could not be matched to this opportunity.')
      })
      .catch(cause => {
        if (!controller.signal.aborted) setProjectError(cause instanceof Error ? cause.message : 'Current project details are unavailable.')
      })
      .finally(() => { if (!controller.signal.aborted) setProjectLoading(false) })
    return () => controller.abort()
  }, [item?.id])

  if (!item) return <aside className="cod-panel" aria-label="Opportunity detail">
    {(pending || loading || error) && <button type="button" className="cod-back" onClick={onBack}>Opportunities</button>}
    <p>{pending || loading ? 'Loading verified opportunity detail…' : 'Select an opportunity to review its evidence and next action.'}</p>
    {error && <p role="alert">{error} <button type="button" onClick={onRetry}>Retry</button></p>}
  </aside>
  if (tab === 'Evidence' || tab === 'Power gap' || tab === 'Research') return <WorkspaceDetail {...workspaceDetailProps(props)} />

  const card = item.intelligence_card
  const fields = card?.fields ?? []
  const field = (key: string) => fields.find(candidate => candidate.key === key && candidate.value)
  const company = project?.company?.trim() || item.commercial_organization || item.title_company || null
  const fullTitle = project?.name || item.browse_title || item.name
  const title = company && fullTitle.startsWith(`${company} · `) ? fullTitle.slice(company.length + 3) : fullTitle
  const location = project?.location || item.location || field('location')?.value || null
  const summary = firstSentence(item.commercial_reason || item.assessment_reason || item.rationale)
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
    { label: 'Estimated Power Need', value: demand || '—', basis: item.required_mw ? 'Activity-specific power requirement' : facilityDemand ? `${facilityDemand.status} · facility demand` : 'Not established · power requirement unknown', icon: 'demand' },
    { label: 'Estimated Power Gap', value: gap || '—', basis: gapBasis, icon: 'gap' },
    { label: 'Needed By', value: timing || '—', basis: timing ? 'Power timing from retained assessment' : 'Not established · timing unknown', icon: 'calendar' },
  ]
  const people = card?.contacts ?? []
  const evidence = item.evidence ?? []
  const sources = evidence.slice().sort((a, b) => (b.event_date || b.published_at || '').localeCompare(a.event_date || a.published_at || ''))
  const additionalCardEvidence = (card?.evidence ?? []).filter(source => {
    const href = safeSourceUrl(source.url)
    return Boolean(href && !sources.some(itemSource => safeSourceUrl(itemSource.url) === href))
  }).slice(0, 2)
  const nextAction = item.tier === 'Signal' && (item.commercial_disposition ?? card?.disposition) === 'WATCH'
    ? 'Continue monitoring for verified power demand.'
    : item.commercial_next_action || item.next_action || item.commercial_next_question || project?.next_action || 'Review retained evidence and confirm the unresolved details.'
  const details = [
    ['Company', company], ['Project', title], ['Location', location],
    ['Project type', project?.asset_type?.replaceAll('_', ' ') || field('project_type')?.value],
    ['Power timing', item.start_window], ['Milestone date', project?.event?.date], ['Site status', item.lifecycle_state?.replaceAll('_', ' ') || field('site_status')?.value],
    ['Grid proximity', field('grid_proximity')?.value], ['Utility status', field('utility_status')?.value],
    ['Site control', field('site_control')?.value], ['Estimated project value', field('project_value')?.value],
    ['Site size', field('site_size')?.value], ['Development partner', field('development_partner')?.value],
    ['Last intelligence update', card?.last_intelligence_update ? displayDate(card.last_intelligence_update) : null],
  ].filter((entry): entry is [string, string] => Boolean(entry[1]?.trim()))

  return <aside className="cod-panel" aria-label="Opportunity detail">
    <div className="cod-heading">
      <button type="button" className="cod-back" onClick={onBack}>← Opportunities</button>
      <div className="cod-title-row">
        <div><span className="cod-tier">{item.tier || 'Opportunity'}</span><h2>{company && company !== title ? <>{company} <span>— {title}</span></> : title}</h2>
          <p className="cod-location">{location || 'Location not established'}{project?.event?.label ? ` · ${project.event.label}${project.event.date ? ` · ${project.event.date}` : ''}` : ''}</p>
        </div>
      </div>
    </div>

    <nav className="cod-tabs" aria-label="Project detail sections">
      {(['Overview', 'Intelligence', 'Timeline', 'Related'] as const).map(value => <button key={value} type="button" aria-pressed={canonicalTab === value} className={canonicalTab === value ? 'active' : ''} onClick={() => onTab(workspaceTabFor(value))}>{value}</button>)}
    </nav>
    <p className="cod-summary">{summary}</p>
    {(projectLoading || projectError || associationNotice) && <p className="cod-status" role={projectError ? 'status' : undefined}>{projectLoading ? 'Loading current project details…' : projectError || associationNotice}</p>}

    {canonicalTab === 'Overview' && <>
      <div className="cod-overview-body">
      <section className="cod-metrics" aria-label="Power metrics">{metrics.map(metric => <article key={metric.label}>
        <span className="cod-metric-icon" aria-hidden="true">{metric.icon === 'demand' ? <Zap size={16} strokeWidth={1.6}/> : metric.icon === 'gap' ? <ChartNoAxesColumnIncreasing size={16} strokeWidth={1.6}/> : <CalendarDays size={16} strokeWidth={1.6}/>}</span>
        <div><strong title={metric.value} aria-label={metric.value}>{metric.value}</strong><span className="cod-metric-label">{metric.label}</span><small>{metric.basis}</small></div>
      </article>)}</section>
      <section className="cod-details" aria-label="Key project details"><h3>Project details</h3><dl>{details.length ? details.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>) : <p>Project details are not established by current evidence.</p>}</dl></section>
      <div className="cod-lower">
        <section className="cod-contacts" aria-label="Decision maker or contact"><h3><UserRound size={13} strokeWidth={1.6}/>Decision Maker / Contact</h3>
          {people.length ? people.slice(0, 2).map(person => <article key={person.claim_id}>
            <strong>{person.name || person.company}</strong><p>{[person.title || person.role, person.name ? person.company : null].filter(Boolean).join(' · ')}</p>
            {person.responsibility && <p>{person.responsibility}</p>}
            <p>Purchasing authority: {person.purchasing_authority?.trim() || 'Authority not established'}</p>
            {(person.methods ?? []).filter(isVerifiedContactMethod).map(method => <span className="cod-verified-method" key={`${method.kind}:${method.value}`}><a href={method.href!}>{method.kind === 'email' ? 'Email' : 'Call'} {method.value}</a><small>Source checked {displayDate(method.verified_at)}</small></span>)}
            {!(person.methods ?? []).some(isVerifiedContactMethod) && <small>No verified direct method is available.</small>}
            {(person.sources ?? []).filter(source => !sources.some(itemSource => safeSourceUrl(itemSource.url) && safeSourceUrl(itemSource.url) === safeSourceUrl(source.url))).map(source => safeSourceUrl(source.url) && <a key={`${source.reference}:${source.url}`} href={safeSourceUrl(source.url)!} target="_blank" rel="noreferrer">Contact source: {source.title}</a>)}
          </article>) : <p>No verified decision-maker contact is available in retained evidence.</p>}
        </section>
        <section className="cod-evidence" aria-label="Recent evidence"><h3><FileText size={13} strokeWidth={1.6}/>Evidence ({sources.length + additionalCardEvidence.length})</h3>
          {sources.length ? sources.slice(0, 4).map(source => safeSourceUrl(source.url) && <a className="cod-evidence-row" key={`${source.id}:${source.content_hash}`} href={safeSourceUrl(source.url)!} target="_blank" rel="noreferrer"><span>{source.title}</span><time title={source.event_date ? `${source.event_date_label}: ${source.event_date}` : `Published: ${source.published_at || "Unknown"}`}>{displayDate(source.event_date || source.published_at)}</time><small className="cod-source-status">{source.assessment_current === true ? "Current support" : source.assessment_current === false ? "Historical" : "Status unavailable"}</small></a>) : <p>No dated evidence is attached to this opportunity.</p>}
          {additionalCardEvidence.map(source => <a className="cod-evidence-row" key={source.reference} href={safeSourceUrl(source.url)!} target="_blank" rel="noreferrer"><span>{source.title}</span><time>{source.source_date || 'Date unavailable'}</time><small className="cod-source-status">{source.verification_status || "Status unavailable"}</small></a>)}
        </section>
      </div>
      <button type="button" className="cod-view-all-evidence" onClick={() => onTab('Evidence')}>View all evidence</button>
      </div>
      <section className="cod-next-action" aria-label="Recommended next action"><Target size={19} strokeWidth={1.6}/><div><strong>Next Action</strong><p>{nextAction}</p></div><button type="button" onClick={() => onTab('Research')}>View research</button></section>
    </>}

    {canonicalTab === 'Intelligence' && <section className="cod-tab-content">
      <h3>Commercial intelligence</h3>
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
      <h4>Source records</h4>{sources.length ? sources.map(source => <article className="cod-related-source" key={source.id}>{safeSourceUrl(source.url) ? <a href={safeSourceUrl(source.url)!} target="_blank" rel="noreferrer">{source.title}</a> : <strong>{source.title}</strong>}<span>{displayDate(source.event_date || source.published_at)} · {source.source_origin}</span><p>{source.abstract || 'No source summary is available.'}</p></article>) : <p>No source records are attached.</p>}
    </section>}
  </aside>
}

function tabForWorkspace(tab: WorkspaceTab): CanonicalTab {
  if (tab === 'Timeline') return 'Timeline'
  if (tab === 'Evidence' || tab === 'Buying chain') return 'Related'
  if (tab === 'Unknowns' || tab === 'Power gap') return 'Intelligence'
  return 'Overview'
}

function workspaceTabFor(tab: CanonicalTab): WorkspaceTab {
  if (tab === 'Timeline') return 'Timeline'
  if (tab === 'Related') return 'Buying chain'
  if (tab === 'Intelligence') return 'Unknowns'
  return 'Overview'
}

function safeSourceUrl(value: string | null | undefined): string | null {
  if (!value) return null
  try {
    const url = new URL(value)
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null
  } catch { return null }
}

function isVerifiedContactMethod(method: { [key: string]: string }) {
  if (!/^(tel:|mailto:)/i.test(method.href || '')) return false
  const stamp = method.verified_at
  return Boolean(stamp && !Number.isNaN(Date.parse(stamp)))
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
