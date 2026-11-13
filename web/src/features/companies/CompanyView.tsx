import { useEffect, useMemo, useRef, useState } from 'react'
import { browseUpdatingNotice, client, OpportunityBrowsePendingError, OpportunityCohortChangedError, OpportunityGroupUnavailableError, type CommercialCustomerIntelligence, type CustomerRollupFilters, type CustomerRollupSort, type OpportunityGroup, type OpportunityGroupOpen, type ProjectResult } from '../../api/client'
import { usePursuitStore } from '../../state/pursuitStore'
import { AddToPursuit } from '../pursuits/AddToPursuit'
import { downloadProjectPage } from '../workspace/opportunityExport'
import { groupDescription } from './groupKind'

const sectorLabel = (value: string) => value === 'oil_gas' ? 'Oil & Gas' : value === 'data_centers' ? 'Data Centers' : value.replaceAll('_', ' ')
const assetTypeLabel = (value: string) => value === 'data_center' ? 'Data center' : value === 'oil_gas' ? 'Oil & Gas' : value.replaceAll('_', ' ')
const MAX_PENDING_RETRIES = 3
const MAX_TIMER_DELAY_MS = 2_147_483_647

export function reportedCommercialTarget(intel?: CommercialCustomerIntelligence | null) {
  const timing = intel?.priority?.priority_basis?.timing
  const target = intel?.timelines?.reported_target ?? (timing?.kind === 'reported_timing_proxy' ? timing : null)
  const labels: Record<string, string> = { operational_target: 'Operational target', full_operational_target: 'Full operational target', ready_for_service: 'Ready-for-service target' }
  const label = target?.event_type ? labels[target.event_type] : undefined
  return label && typeof target?.label === 'string' && target.label.trim() && target.label.length <= 200 ? { label, value: target.label } : null
}

function waitForRetry(signal: AbortSignal, delayMs: number) {
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) { reject(new DOMException('Aborted', 'AbortError')); return }
    const timer = window.setTimeout(() => { signal.removeEventListener('abort', abort); resolve() }, Math.max(50, Math.min(delayMs, 30_000)))
    const abort = () => { window.clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')) }
    signal.addEventListener('abort', abort, { once: true })
  })
}

async function projectsWithRetry<T>(signal: AbortSignal, maxRetries: number, request: (attempt: number) => Promise<T>): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    try { return await request(attempt) }
    catch (cause) {
      if (!(cause instanceof OpportunityBrowsePendingError) || attempt >= maxRetries) throw cause
      await waitForRetry(signal, cause.retryAfterMs)
    }
  }
}

type DetailState = {
  groupId: string
  group: OpportunityGroup
  projects: ProjectResult[]
  total: number
  cohort: string
  parent: string
  validUntil?: string
  status: 'ready' | 'gone' | 'error'
  error: string
  more: 'idle' | 'loading' | 'error'
  notice: string
  /** "Showing results as of …" while the server serves its last complete snapshot. */
  snapshot?: string
}

type AccountProjectPageIntent = { groupId: string; filterKey: string; loadedCount: number; total: number; cohort: string }
const accountProjectPageIntentKey = 'accountProjectPageIntent'
function readAccountProjectPageIntent(): AccountProjectPageIntent | null {
  const raw = history.state?.[accountProjectPageIntentKey] as Partial<AccountProjectPageIntent> | undefined
  return raw && typeof raw.groupId === 'string' && typeof raw.filterKey === 'string' && Number.isSafeInteger(raw.loadedCount) && Number.isSafeInteger(raw.total) && typeof raw.cohort === 'string'
    ? raw as AccountProjectPageIntent : null
}
function writeAccountProjectPageIntent(intent: AccountProjectPageIntent | null) {
  const state = { ...history.state }
  if (intent) state[accountProjectPageIntentKey] = intent
  else delete state[accountProjectPageIntentKey]
  history.replaceState(state, '', location.href)
}

function safeContactHref(href?: string | null) {
  if (!href) return null
  if (/^tel:\+?[\d().\-\s;=]+$/i.test(href)) return href
  if (!/^mailto:[^\s<>]+$/i.test(href)) return null
  const address = href.slice(7).split('?')[0]
  return /^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9-]*[A-Z0-9])?(?:\.[A-Z0-9](?:[A-Z0-9-]*[A-Z0-9])?)+$/i.test(address) ? href : null
}

function contactOrder(contact: ProjectResult['contact'][number]) {
  const label = `${contact.label} ${contact.route_kind ?? ''} ${contact.responsibility ?? ''}`.toLowerCase()
  const general = /general|main line|switchboard|company/.test(label)
  const responsibility = contact.responsibility?.trim().toLowerCase()
  const responsibilityRank = responsibility === 'verified project responsibility' ? 0
    : responsibility === 'verified organizational responsibility' ? 1
      : responsibility === 'inferred likely role' ? 2
        : responsibility === 'general company contact path' ? 3 : 4
  return responsibilityRank * 100 + Number(!contact.name) * 4 + Number(!contact.title) * 2 + Number(general)
}

export function bestProjectContactRoutes(contacts: ProjectResult['contact']) {
  const valid = contacts.map(contact => ({ contact, href: safeContactHref(contact.href) }))
    .filter((item): item is { contact: ProjectResult['contact'][number]; href: string } => Boolean(item.href))
    .sort((left, right) => contactOrder(left.contact) - contactOrder(right.contact))
  const best = valid[0]?.contact
  if (!best) return []
  const sameContact = valid.filter(({ contact }) => compatibleContact(best, contact))
  const chosen: typeof sameContact = []
  for (const protocol of ['tel:', 'mailto:']) {
    const route = sameContact.find(item => item.href.toLowerCase().startsWith(protocol))
    if (route) chosen.push(route)
  }
  return chosen
}

function normalizedContactValue(value?: string | null) {
  return value?.trim().replace(/\s+/g, ' ').toLocaleLowerCase() ?? ''
}

function compatibleContact(primary: ProjectResult['contact'][number], candidate: ProjectResult['contact'][number]) {
  const primaryExtra = primary as typeof primary & { person_identity_id?: string | null; company_identity_id?: string | null; role?: string | null }
  const candidateExtra = candidate as typeof candidate & { person_identity_id?: string | null; company_identity_id?: string | null; role?: string | null }
  const primaryName = normalizedContactValue(primary.name), candidateName = normalizedContactValue(candidate.name)
  if (primaryName ? primaryName !== candidateName : Boolean(candidateName)) return false
  const primaryCompany = normalizedContactValue(primary.company), candidateCompany = normalizedContactValue(candidate.company)
  if (primaryCompany ? primaryCompany !== candidateCompany : Boolean(candidateCompany)) return false
  for (const field of ['person_identity_id', 'company_identity_id'] as const) {
    const left = normalizedContactValue(primaryExtra[field]), right = normalizedContactValue(candidateExtra[field])
    if ((left || right) && left !== right) return false
  }
  for (const field of ['title', 'responsibility', 'support', 'source_url', 'route_kind'] as const) {
    const left = normalizedContactValue(primary[field]), right = normalizedContactValue(candidate[field])
    if (left && right && left !== right) return false
  }
  const primaryRole = normalizedContactValue(primaryExtra.role), candidateRole = normalizedContactValue(candidateExtra.role)
  return !(primaryRole && candidateRole && primaryRole !== candidateRole)
}

export function generalCompanyContactRoutes(contacts: ProjectResult['contact'], primaryRoutes: ReturnType<typeof bestProjectContactRoutes>) {
  const primary = primaryRoutes[0]?.contact
  if (primary?.route_kind === 'company_route' && !primary.name) return []
  const general = contacts.filter(contact => contact.route_kind === 'company_route' && !contact.name)
  const valid = bestProjectContactRoutes(general)
  const primaryProtocols = new Set(primaryRoutes.map(({ href }) => href.toLowerCase().startsWith('mailto:') ? 'mailto:' : 'tel:'))
  return valid.filter(({ href }) => !primaryProtocols.has(href.toLowerCase().startsWith('mailto:') ? 'mailto:' : 'tel:'))
}

function validAccountContactProject(value: unknown): value is ProjectResult {
  if (!value || typeof value !== 'object') return false
  const candidate = value as { project_id?: unknown; name?: unknown; contact?: unknown }
  if (typeof candidate.project_id !== 'string' || typeof candidate.name !== 'string' || !Array.isArray(candidate.contact)) return false
  const stringFields = ['href', 'name', 'title', 'company', 'route_kind', 'responsibility', 'support', 'source_url', 'verified_at', 'person_identity_id', 'company_identity_id', 'role'] as const
  const validMethods = candidate.contact.every((contact: unknown) => {
    if (!contact || typeof contact !== 'object') return false
    const action = contact as Record<string, unknown>
    return typeof action.kind === 'string' && typeof action.label === 'string' && stringFields.every(field => action[field] == null || typeof action[field] === 'string')
  })
  const people = (candidate as { contact_people?: unknown }).contact_people
  if (people != null && (!Array.isArray(people) || !people.every((person: unknown) => {
    if (!person || typeof person !== 'object') return false
    const row = person as Record<string, unknown>
    return ['record_type', 'company_identity_id', 'person_identity_id', 'company', 'name', 'title', 'role', 'responsibility', 'purchasing_authority', 'source_url'].every(field => row[field] == null || typeof row[field] === 'string')
  }))) return false
  return validMethods
}

/** An explicit null/malformed API selection is authoritative; only older responses may fall back. */
export function selectAccountContactProject(group: OpportunityGroup, fallback: ProjectResult | null): ProjectResult | null {
  if (!Object.prototype.hasOwnProperty.call(group, 'account_contact_project')) return fallback
  return validAccountContactProject(group.account_contact_project) ? group.account_contact_project : null
}

const verifiedContactResponsibilities = new Set(['verified project responsibility', 'verified organizational responsibility'])
export function verifiedContactPeople(project: ProjectResult | null) {
  if (!project?.customer_identity_id) return []
  return (project.contact_people ?? []).filter(person => Boolean(person.name?.trim()) && verifiedContactResponsibilities.has((person.responsibility ?? '').trim().toLocaleLowerCase()) && person.company_identity_id === project.customer_identity_id && Boolean(safeContactSourceUrl(person.source_url)))
}

export function VerifiedContactPeople({ people }: { people: ReturnType<typeof verifiedContactPeople> }) {
  if (!people.length) return <p className="cmp-note">No verified business contact is currently available. Contact research is needed.</p>
  return <div className="cmp-verified-people"><strong>Verified business contacts</strong><ul>{people.map((person, index) => <li key={`${person.person_identity_id ?? person.name}:${index}`}>
    <p><strong>{person.name}</strong>{person.title && ` · ${person.title}`}{person.role && ` · ${person.role}`}</p>
    <small>Verified {person.responsibility?.replace('Verified ', '').toLowerCase()}. Professional contact details unavailable.</small>
    {safeContactSourceUrl(person.source_url) && <a href={safeContactSourceUrl(person.source_url)!} target="_blank" rel="noreferrer">Contact source</a>}
  </li>)}</ul><p className="cmp-note">Research a permitted business route before outreach.</p></div>
}

function AccountContacts({ project }: { project: ProjectResult | null }) {
  const contacts = bestProjectContactRoutes(project?.contact ?? [])
  const people = verifiedContactPeople(project)
  if (!contacts.length) return <div aria-label="Verified business contacts"><VerifiedContactPeople people={people}/></div>
  const best = contacts[0].contact
  const generalRoutes = generalCompanyContactRoutes(project?.contact ?? [], contacts)
  const companyLine = /general|main line|switchboard|company/i.test(`${best.label} ${best.route_kind ?? ''}`)
  const contactSource = safeContactSourceUrl(best.source_url)
  return <div aria-label="Best available contact">
    {project && <span>Contact associated with {project.name}</span>}
    <strong>{best.name ?? best.company ?? (companyLine ? 'Company line' : best.label)}</strong>
    {best.title && <span> · {best.title}</span>}
    {companyLine && <span> · General company route</span>}
    {best.responsibility && <p className="cmp-note">{best.responsibility}. Public-source attribution does not confirm purchasing authority.</p>}
    <p>{contacts.map(({ contact, href }) => <a key={`${contact.kind}:${href}`} href={href}>{/^mailto:/i.test(href) ? 'Email' : 'Call'} {contact.name ?? (contact.route_kind === 'company_route' ? 'company' : 'contact')}</a>)}</p>
    {contactSource && <details><summary>Contact source</summary><a href={contactSource} target="_blank" rel="noreferrer">Open source</a></details>}
    {generalRoutes.length > 0 && <p><span>General company route · </span>{generalRoutes.map(({ contact, href }) => <a key={`general:${contact.kind}:${href}`} href={href}>{/^mailto:/i.test(href) ? 'Email' : 'Call'} company</a>)}</p>}
  </div>
}

function projectNeeds(project: ProjectResult, shortlist: boolean) {
  const unique = new Map<string, string>()
  const eligible = new Set(project.eligible_need_ids ?? [])
  for (const need of project.needs) {
    if (shortlist && !eligible.has(need.id)) continue
    unique.set(need.id, need.activity ?? need.browse_title ?? need.name ?? project.name)
  }
  if (!shortlist && !unique.size && project.representative_need_id) unique.set(project.representative_need_id, project.name)
  return [...unique].map(([id, label]) => ({ id, label }))
}

function ProjectPursuitAction({ project, shortlist }: { project: ProjectResult; shortlist: boolean }) {
  const needs = projectNeeds(project, shortlist)
  const [selected, setSelected] = useState(needs[0]?.id ?? '')
  useEffect(() => setSelected(needs[0]?.id ?? ''), [project.id])
  if (!needs.length) return null
  if (needs.length === 1) return <AddToPursuit key={needs[0].id} needId={needs[0].id} deferLookup />
  const choice = needs.find(need => need.id === selected) ?? needs[0]
  return <div className="cmp-project-action">
    <label><span className="cmp-sr">Choose an opportunity for {project.name}</span><select value={choice.id} onChange={event => setSelected(event.target.value)}>
      {needs.map(need => <option key={need.id} value={need.id}>{need.label}</option>)}
    </select></label>
    <AddToPursuit key={choice.id} needId={choice.id} deferLookup />
  </div>
}

function sourceUrl(value?: string | null) {
  if (!value) return null
  try { const url = new URL(value); return url.protocol === 'https:' || url.protocol === 'http:' ? url.toString() : null } catch { return null }
}
export function safeContactSourceUrl(value?: string | null) { return sourceUrl(value) }

function earliestValidUntil(...values: (string | undefined)[]) {
  const dates = values.map(value => value ? Date.parse(value) : NaN).filter(Number.isFinite)
  return dates.length ? new Date(Math.min(...dates)).toISOString() : undefined
}
function isUnavailableAccountRead(cause: unknown) {
  return cause instanceof OpportunityGroupUnavailableError
}

export function commercialCapacityUnavailableMessage(status?: string) {
  if (status === 'unknown_overlap') return 'Overlapping project or phase claims prevent a supported combined capacity total.'
  if (status === 'mixed_bounds') return 'Capacity claims mix upper and lower bounds, so no single supported total is available.'
  return 'No supported build-capacity total is available.'
}

function CommercialAnalysis({ group }: { group: OpportunityGroup | null }) {
  const intel: CommercialCustomerIntelligence | null = group?.commercial_intelligence ?? null
  if (!intel) return null
  const show = (value: unknown) => {
    if (typeof value === 'string' || typeof value === 'number') return String(value)
    if (!value || typeof value !== 'object') return ''
    const row = value as Record<string, unknown>
    if (typeof row.display_label === 'string') return row.display_label
    return [row.display_label, row.summary, row.title, row.name, row.label, row.value, row.text, row.date, row.precision].filter((part): part is string | number => typeof part === 'string' || typeof part === 'number').join(' · ')
  }
  const totals = intel.capacity?.totals?.filter(item => item.value_mw != null && item.status !== 'unknown') ?? []
  const commissioning = intel.commissioning
  const asRows = (value: unknown): Record<string, unknown>[] => Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object' && !Array.isArray(item))) : []
  const claims = asRows(intel.capacity.claims)
  const timelineClaims = asRows(intel.timelines?.claims)
  const reportedTarget = reportedCommercialTarget(intel)
  const capacityConflicts = asRows(intel.capacity.conflicts)
  const timelineConflicts = asRows(intel.timelines?.conflicts)
  const claimById = new Map(claims.map(claim => [String(claim.fact_id ?? ''), claim]))
  const timelineClaimById = new Map(timelineClaims.map(claim => [String(claim.fact_id ?? ''), claim]))
  const factScope = (value: unknown) => {
    const scope = typeof value === 'string' ? value : ''
    if (scope.endsWith(':site')) return 'Site-wide'
    const phase = scope.match(/:phase:([^:]+)$/)
    return phase ? `Phase ${phase[1]}` : 'Project scope'
  }
  const eventLabel = (value: unknown) => ({ actual_construction_start: 'Actual construction start', announced_construction_start: 'Announced construction start', expected_first_energization: 'Expected first energization', phase_energization: 'Phase energization', full_operational_target: 'Full operational target', operational_target: 'Operational target', ready_for_service: 'Ready for service' } as Record<string, string>)[String(value)] ?? 'Lifecycle event'
  const capacityBasis = (value: unknown) => ({ campus_development: 'Campus development', it_load: 'IT load', utility_service: 'Utility service', generation: 'Generation', individual_phase: 'Individual phase' } as Record<string, string>)[String(value)] ?? (typeof value === 'string' ? value.replaceAll('_', ' ') : 'Capacity')
  const citedSource = (value: unknown) => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
  const sourceLink = (value: unknown) => {
    const source = citedSource(value)
    const url = sourceUrl(typeof source.url === 'string' ? source.url : typeof source.source_url === 'string' ? source.source_url : null)
    const title = [source.title, source.name, source.label].find((part): part is string => typeof part === 'string' && Boolean(part.trim())) ?? 'Open cited source'
    return <>{url ? <a href={url} target="_blank" rel="noreferrer">{title}</a> : <span>{title}</span>}{typeof source.published_at === 'string' && <small> · Published {source.published_at}</small>}</>
  }
  const claimIds = (value: unknown) => Array.isArray(value) ? value.filter((id): id is string => typeof id === 'string') : []
  const claimQuote = (claim: Record<string, unknown>) => typeof claim.quote === 'string' ? claim.quote : ''
  const scenarioText = () => {
    if (!commissioning) return ''
    const low = commissioning.low_mw, base = commissioning.base_mw, high = commissioning.high_mw
    if (low != null && high != null) return `${low}–${high} MW${base != null ? ` · base ${base} MW` : ''}`
    if (base != null) return `${base} MW base engineering scenario`
    if (low != null) return `Low scenario bound · ${low} MW`
    if (high != null) return `High scenario bound · ${high} MW`
    return ''
  }
  return <details className="cmp-commercial-analysis"><summary>Commercial analysis</summary>
    <div className="cmp-commercial-grid">
      <section><h4>Build capacity</h4>{totals.length ? totals.map((item, index) => { const detail = item as typeof item & { qualifier?: string; complete?: boolean }; const basis = ({ campus_development:'Campus development', it_load:'IT load', utility_service:'Utility service', generation:'Generation', individual_phase:'Individual phase' } as Record<string,string>)[item.basis] ?? item.basis.replaceAll('_',' '); const qualifier = detail.qualifier === 'up_to' || item.status === 'upper_bound' ? 'Up to ' : detail.qualifier === 'approximate' ? 'Approximately ' : detail.qualifier === 'more_than' ? 'More than ' : detail.qualifier === 'at_least' || item.status === 'lower_bound' ? 'At least ' : ''; return <p key={index}>{qualifier}{item.value_mw} MW · {basis}{detail.complete === false ? ' · partial coverage' : ''}</p> }) : <p>{commercialCapacityUnavailableMessage(intel.capacity.status)}</p>}{intel.capacity.coverage && <small>{String(intel.capacity.coverage.projects_with_capacity ?? 0)} of {String(intel.capacity.coverage.projects_total ?? '?')} projects with supported capacity</small>}{asRows((intel.capacity as CommercialCustomerIntelligence['capacity'] & { conflict_count?: number }).conflicts).length > 0 && <p role="status">Conflicting capacity claims require review.</p>}</section>
      <section><h4>Timing</h4>{show(intel.timelines?.construction_start) && <p>Construction start · {show(intel.timelines?.construction_start)}</p>}{show(intel.timelines?.expected_energization) && <p>Expected energization · {show(intel.timelines?.expected_energization)}</p>}{reportedTarget && <p>{reportedTarget.label} · {reportedTarget.value} · source-reported; energization unverified</p>}{!show(intel.timelines?.construction_start) && !show(intel.timelines?.expected_energization) && !reportedTarget && <p>{timelineClaims.length ? 'Construction and energization dates are not established; reported milestones are available below.' : 'No supported timeline is available.'}</p>}{asRows((intel.timelines as CommercialCustomerIntelligence['timelines'] & { conflict_count?: number }).conflicts).length > 0 && <p role="status">Conflicting timeline claims require review.</p>}</section>
      <section><h4>Commissioning scenario</h4>{scenarioText() ? <p>{scenarioText()}</p> : <p>Insufficient data for an engineering scenario.</p>}{commissioning?.limitations?.map((item, index) => <small key={index}>{item}</small>)}</section>
      <section><h4>Recent developments</h4>{intel.recent_developments?.length ? intel.recent_developments.map((item, index) => <p key={index}>{show(item)}</p>) : <p>No material recent development is available.</p>}</section>
    </div>
    {capacityConflicts.length > 0 && <details><summary>Conflicting capacity claims ({capacityConflicts.length})</summary><ul>{capacityConflicts.map((conflict, index) => <li key={index}><p><strong>{capacityBasis(conflict.basis)}</strong> · {factScope(conflict.scope_id)}</p>{typeof conflict.reason === 'string' && <p>{conflict.reason}</p>}<ul>{claimIds(conflict.claim_ids).map((id, claimIndex) => { const claim = claimById.get(id); if (!claim) return null; const qualifier = typeof claim.qualifier === 'string' && claim.qualifier !== 'exact' ? `${claim.qualifier.replaceAll('_', ' ')} ` : ''; return <li key={claimIndex}><p>{qualifier}{String(claim.value_mw ?? 'Unknown')} MW · {capacityBasis(claim.basis)}</p>{claimQuote(claim) && <blockquote>{claimQuote(claim)}</blockquote>}<details><summary>Source evidence</summary><p>{sourceLink(claim.source)}</p></details></li> })}</ul></li>)}</ul></details>}
    {intel.priority && <section><h4>Priority rationale</h4><p>Potential {intel.priority.potential} · evidence confidence {intel.priority.confidence}</p>{Object.entries(intel.priority.components ?? {}).map(([key, value]) => <p key={key}>{key.replaceAll('_', ' ')}: {show(value)}</p>)}</section>}
    {intel.limitations?.map((item, index) => <p className="cmp-note" key={index}>{item}</p>)}
    {intel.sources?.length ? <section><h4>Sources</h4>{intel.sources.map((item, index) => { const url = sourceUrl(typeof item.url === 'string' ? item.url : null); const named = [item.title, item.name, item.label].find((value): value is string => typeof value === 'string' && Boolean(value.trim())); const title = named || String(item.evidence_id ?? 'Evidence source'); return <p key={index}>{url ? <a href={url} target="_blank" rel="noreferrer">{title}</a> : title}</p> })}</section> : null}
    {timelineClaims.length > 0 && <details><summary>Timeline claims</summary><ul>{timelineClaims.map((claim, index) => <li key={index}><p><strong>{eventLabel(claim.event_type)}</strong> · {claim.status === 'actual' ? 'Actual' : 'Expected'} · {factScope(claim.scope_id)}</p><p>{typeof claim.display_label === 'string' ? claim.display_label : String(claim.label ?? 'Timing not specified')}{typeof claim.precision === 'string' && <small> · {claim.precision.replaceAll('_', ' ')}</small>}</p>{claimQuote(claim) && <blockquote>{claimQuote(claim)}</blockquote>}<details><summary>Source evidence</summary><p>{sourceLink(claim.source)}</p></details></li>)}</ul></details>}
    {timelineConflicts.length > 0 && <details><summary>Conflicting timeline claims ({timelineConflicts.length})</summary><ul>{timelineConflicts.map((conflict, index) => <li key={index}><p><strong>{eventLabel(conflict.event_type)}</strong> · {factScope(conflict.scope_id)}</p><ul>{claimIds(conflict.claim_ids).map((id, claimIndex) => { const claim = timelineClaimById.get(id); if (!claim) return null; return <li key={claimIndex}><p>{claim.status === 'actual' ? 'Actual' : 'Expected'} · {factScope(claim.scope_id)} · {typeof claim.display_label === 'string' ? claim.display_label : String(claim.label ?? 'Timing not specified')} · {String(claim.precision ?? 'precision unknown').replaceAll('_', ' ')}</p>{claimQuote(claim) && <blockquote>{claimQuote(claim)}</blockquote>}<details><summary>Source evidence</summary><p>{sourceLink(claim.source)}</p></details></li> })}</ul></li>)}</ul></details>}
    {commissioning && <details><summary>Engineering scenario inputs and calculation</summary><p>Calculation version · {String(commissioning.calculation_version ?? commissioning.version ?? 'Not provided')}</p><p>Scenario confidence · {String(commissioning.confidence ?? 'Not provided')}</p>{Array.isArray(commissioning.assumptions) && commissioning.assumptions.map((assumption, index) => <p key={`assumption:${index}`}>{String(assumption)}</p>)}{asRows(commissioning.input_evidence).length > 0 ? <ul>{asRows(commissioning.input_evidence).map((reference, index) => <li key={index}>{typeof reference.quote === 'string' && <blockquote>{reference.quote}</blockquote>}<p>{sourceLink(reference)}</p></li>)}</ul> : <p className="cmp-note">No admitted engineering input evidence is available.</p>}</details>}
  </details>
}

/** Shared account detail for the Opportunities and Companies account routes. */
export function CompanyView({ groupId, summary, onBack, onNeed, backLabel, shortlist = false, canonicalOnly = false, search = '', sector = 'all', region = '', stage = '', priority = '', sort = 'priority', matchedProjectId, matchedNeedId, accountContextStatus = 'valid' }: { groupId: string; summary?: OpportunityGroup; onBack: () => void; onNeed: (needId: string, projectId?: string) => void; backLabel?: string; shortlist?: boolean; canonicalOnly?: boolean; search?: string; sector?: 'all' | 'oil_gas' | 'data_centers'; region?: string; stage?: string; priority?: CustomerRollupFilters['priority']; sort?: CustomerRollupSort; matchedProjectId?: string | null; matchedNeedId?: string | null; accountContextStatus?: 'valid' | 'pending' | 'unavailable' }) {
  const [detail, setDetail] = useState<DetailState | null>(null)
  const [retry, setRetry] = useState(0)
  const openAbort = useRef<AbortController | null>(null)
  const moreAbort = useRef<AbortController | null>(null)
  const expiredSnapshot = useRef<string | null>(null)
  const pursuits = usePursuitStore()
  const pageFilterKey = JSON.stringify({ shortlist, canonicalOnly, search, sector, region, stage, priority, sort })
  useEffect(() => {
    const clearSessionData = () => {
      openAbort.current?.abort()
      moreAbort.current?.abort()
      setDetail(null)
      writeAccountProjectPageIntent(null)
    }
    window.addEventListener('gl3-clear-continuity', clearSessionData)
    return () => window.removeEventListener('gl3-clear-continuity', clearSessionData)
  }, [])
  useEffect(() => {
    openAbort.current?.abort()
    const controller = new AbortController()
    openAbort.current = controller
    moreAbort.current?.abort()
    setDetail(null)
    const openWithRetry = async () => {
      for (let attempt = 0; ; attempt++) {
        try { return await client.openOpportunityGroup(groupId, { search, sector, region, stage, priority, limit: 25, sort, shortlist, canonical_only: canonicalOnly }, controller.signal) }
        catch (cause) {
          if (!(cause instanceof OpportunityBrowsePendingError) || attempt >= MAX_PENDING_RETRIES) throw cause
          await waitForRetry(controller.signal, cause.retryAfterMs)
        }
      }
    }
    openWithRetry().then(async value => {
      if (controller.signal.aborted) return
      const initial = fromOpen(groupId, value)
      let next = initial
      const intent = readAccountProjectPageIntent()
      if (next.status === 'ready' && intent?.groupId === groupId && intent.filterKey === pageFilterKey && intent.loadedCount > next.projects.length) {
        const targetCount = Math.min(intent.loadedCount, next.total)
        if (intent.total !== next.total || intent.cohort !== next.cohort) {
          next = { ...next, notice: 'The account project list changed. Showing the first page; load more projects to continue.' }
          writeAccountProjectPageIntent(null)
        } else {
          while (next.projects.length < targetCount && !controller.signal.aborted) {
            try {
              const page = await projectsWithRetry(controller.signal, MAX_PENDING_RETRIES, () => client.groupProjects(groupId, { search, sector, region, stage, priority, limit: 25, offset: next.projects.length, cohort_token: next.cohort, parent_cohort_token: next.parent, sort, shortlist, canonical_only: canonicalOnly }, controller.signal))
              if (page.total !== intent.total || page.cohort_token !== intent.cohort || !page.items.length) {
                next = { ...initial, notice: 'The account project list changed. Showing the first page; load more projects to continue.' }
                writeAccountProjectPageIntent(null)
                break
              }
              const projects = appendDistinct(next.projects, page.items)
              if (projects.length === next.projects.length) {
                next = { ...initial, notice: 'The account project list changed. Showing the first page; load more projects to continue.' }
                writeAccountProjectPageIntent(null)
                break
              }
              next = { ...next, projects, validUntil: earliestValidUntil(next.validUntil, page.valid_until) }
            } catch (cause) {
              if (controller.signal.aborted) return
              if (cause instanceof OpportunityCohortChangedError) {
                writeAccountProjectPageIntent(null)
                try {
                  const fresh = await projectsWithRetry(controller.signal, MAX_PENDING_RETRIES, () => client.openOpportunityGroup(groupId, { search, sector, region, stage, priority, limit: 25, sort, shortlist, canonical_only: canonicalOnly }, controller.signal))
                  if (controller.signal.aborted) return
                  next = { ...fromOpen(groupId, fresh), notice: 'The account project list changed. Showing the current first page; load more projects to continue.' }
                } catch {
                  if (controller.signal.aborted) return
                  next = { ...initial, projects: [], total: 0, cohort: '', parent: '', status: 'error', error: 'The account project list changed and could not be refreshed. Retry to load current projects.', notice: '' }
                }
              } else if (isUnavailableAccountRead(cause)) {
                next = { ...next, status: 'gone', projects: [], total: 0, cohort: '', parent: '', error: '', notice: '' }
                writeAccountProjectPageIntent(null)
              } else {
                next = { ...next, notice: 'Some previously loaded projects could not be restored. Load more projects to continue.' }
                writeAccountProjectPageIntent(null)
              }
              break
            }
          }
        }
      }
      if (controller.signal.aborted) return
      setDetail(next)
    }).catch((cause: unknown) => {
      if (controller.signal.aborted) return
      setDetail({ groupId, group: summary?.id === groupId ? summary : { id: groupId, name: 'Account', role: 'unresolved', project_count: 0, need_count: 0, sectors: [] }, projects: [], total: 0, cohort: '', parent: '', status: cause instanceof OpportunityGroupUnavailableError ? 'gone' : 'error', error: cause instanceof Error ? cause.message : 'Account details are unavailable.', more: 'idle', notice: '' })
    })
    return () => { controller.abort(); if (openAbort.current === controller) openAbort.current = null; moreAbort.current?.abort() }
  }, [groupId, retry, shortlist, search, sector, region, stage, priority, sort, pageFilterKey])

  function fromOpen(id: string, value: OpportunityGroupOpen): DetailState {
    const validUntil = earliestValidUntil(value.valid_until, value.projects.valid_until)
    const expiry = validUntil ? Date.parse(validUntil) : NaN
    if (!Number.isFinite(expiry) || Date.now() >= expiry) {
      return {
        groupId: id,
        group: { id, name: value.group.name, role: value.group.role, group_kind: value.group.group_kind, project_count: value.group.project_count, need_count: value.group.need_count, sectors: value.group.sectors },
        projects: [], total: 0, cohort: '', parent: '', validUntil,
        status: 'error', error: Number.isFinite(expiry) ? 'Account project results expired before they could be displayed.' : 'Account project results have no valid expiry. Retry to load a current account snapshot.', more: 'idle', notice: '',
      }
    }
    return { groupId: id, group: value.group, projects: value.projects.items, total: value.projects.total, cohort: value.projects.cohort_token, parent: value.parent_cohort_token, validUntil, status: 'ready', error: '', more: 'idle', notice: '', snapshot: browseUpdatingNotice(value.projects) }
  }

  const current = detail?.groupId === groupId && (detail.status === 'error' || !detail.validUntil || Date.now() < Date.parse(detail.validUntil)) ? detail : null
  useEffect(() => {
    if (!detail || detail.groupId !== groupId || !detail.validUntil) return
    const expiry = Date.parse(detail.validUntil)
    const snapshotKey = `${groupId}:${detail.validUntil}`
    const refreshExpired = () => {
      moreAbort.current?.abort()
      if (expiredSnapshot.current === snapshotKey) {
        setDetail(old => old?.groupId === groupId && old.validUntil === detail.validUntil ? { ...old, status: 'error', projects: [], total: 0, cohort: '', parent: '', validUntil: undefined, more: 'idle', error: 'Account project results expired again. Retry to load a current account snapshot.' } : old)
        return
      }
      expiredSnapshot.current = snapshotKey
      setDetail(old => old?.groupId === groupId && old.validUntil === detail.validUntil ? null : old)
      setRetry(value => value + 1)
    }
    if (!Number.isFinite(expiry)) { refreshExpired(); return }
    let timer = 0
    const scheduleExpiryCheck = () => {
      const delay = expiry - Date.now()
      if (delay <= 0) { refreshExpired(); return }
      timer = window.setTimeout(scheduleExpiryCheck, Math.min(delay, MAX_TIMER_DELAY_MS))
    }
    scheduleExpiryCheck()
    return () => window.clearTimeout(timer)
  }, [detail?.groupId, detail?.validUntil, groupId])
  useEffect(() => { expiredSnapshot.current = null }, [groupId, search, shortlist])
  const group = current?.group ?? (summary?.id === groupId ? summary : null)
  const projects = current?.projects ?? []
  const complete = current !== null && projects.length >= current.total
  const linked = useMemo(() => {
    if (!current || current.status !== 'ready') return []
    const projectIds = new Set<string>(), needIds = new Set<string>()
    for (const project of projects) { projectIds.add(project.project_id); project.project_ids?.forEach(id => projectIds.add(id)); project.needs.forEach(need => needIds.add(need.id)) }
    return pursuits.items.filter(item => projectIds.has(item.project_id) || needIds.has(item.need_id))
  }, [current, projects, pursuits.items])
  const pursuitByProject = (project: ProjectResult) => linked.filter(item => item.project_id === project.project_id || project.project_ids?.includes(item.project_id) || project.needs.some(need => need.id === item.need_id))
  const featured = group?.featured_project ?? projects[0] ?? null
  const accountContactProject = group ? selectAccountContactProject(group, featured) : featured
  const brief = featured?.commercial_brief
  const whyNow = brief ? brief.why_now.text : featured?.shortlist_assessment?.why_now
  const nextStep = brief ? brief.next_action.text : featured?.shortlist_assessment?.next_step ?? featured?.next_action
  const isGroup = group ? group.group_kind === 'same_name_unconfirmed' || group.group_kind === 'unresolved' : false
  const description = group ? groupDescription(group) : null
  const name = group?.name ?? 'Account'
  useEffect(() => {
    if (!current || current.status !== 'ready' || !matchedProjectId) return
    const target = document.querySelector<HTMLElement>(`[data-project-id="${CSS.escape(matchedProjectId)}"]`)
    if (!target) return
    target.scrollIntoView({ block: 'center' })
    target.focus({ preventScroll: true })
  }, [current, projects.length, matchedProjectId])

  function openNeed(needId: string, projectId: string) {
    const params = new URLSearchParams(location.search)
    params.set('view', 'workspace'); params.set('groupBrowse', '1'); params.set('account', groupId); params.set('project', projectId); params.delete('matchedNeed')
    history.replaceState(history.state, '', `/?${params}`)
    onNeed(needId, projectId)
  }

  async function loadMore() {
    if (!current || current.status !== 'ready' || current.more === 'loading') return
    const controller = new AbortController(); moreAbort.current?.abort(); moreAbort.current = controller
    const targetOffset = current.projects.length
    setDetail({ ...current, more: 'loading' })
    try {
      const page = await projectsWithRetry(controller.signal, MAX_PENDING_RETRIES, () => client.groupProjects(groupId, { search, sector, region, stage, priority, limit: 25, offset: targetOffset, cohort_token: current.cohort, parent_cohort_token: current.parent, sort, shortlist, canonical_only: canonicalOnly }, controller.signal))
      if (controller.signal.aborted) return
      const projects = appendDistinct(current.projects, page.items)
      const next = { ...current, projects, total: page.total, cohort: page.cohort_token, validUntil: earliestValidUntil(current.validUntil, page.valid_until), more: 'idle' as const }
      writeAccountProjectPageIntent({ groupId, filterKey: pageFilterKey, loadedCount: projects.length, total: next.total, cohort: next.cohort })
      setDetail(old => old?.groupId === groupId ? next : old)
    } catch (cause) {
      if (controller.signal.aborted) return
      if (cause instanceof OpportunityCohortChangedError) {
        try {
          const fresh = await projectsWithRetry(controller.signal, MAX_PENDING_RETRIES, () => client.openOpportunityGroup(groupId, { search, sector, region, stage, priority, limit: 25, sort, shortlist, canonical_only: canonicalOnly }, controller.signal))
          if (controller.signal.aborted) return
          const freshState = fromOpen(groupId, fresh)
          if (targetOffset >= freshState.total) { setDetail({ ...freshState, notice: 'The project list changed and has been refreshed.' }); return }
          if (targetOffset > 25) { setDetail({ ...freshState, notice: 'The project list changed. It has been refreshed; continue from the refreshed list.' }); return }
          const page = await projectsWithRetry(controller.signal, MAX_PENDING_RETRIES, () => client.groupProjects(groupId, { search, sector, region, stage, priority, limit: 25, offset: targetOffset, cohort_token: freshState.cohort, parent_cohort_token: freshState.parent, sort, shortlist, canonical_only: canonicalOnly }, controller.signal))
          if (controller.signal.aborted) return
          const projects = appendDistinct(freshState.projects, page.items)
          const refreshed = { ...freshState, projects, total: page.total, cohort: page.cohort_token, validUntil: earliestValidUntil(freshState.validUntil, page.valid_until), more: 'idle' as const, notice: 'The project list changed and has been refreshed.' }
          writeAccountProjectPageIntent({ groupId, filterKey: pageFilterKey, loadedCount: projects.length, total: refreshed.total, cohort: refreshed.cohort })
          setDetail(refreshed)
        } catch (refreshCause) {
          if (controller.signal.aborted) return
          if (isUnavailableAccountRead(refreshCause)) { writeAccountProjectPageIntent(null); setDetail(old => old?.groupId === groupId ? { ...old, status: 'gone', projects: [], total: 0, cohort: '', parent: '', error: '' } : old) }
          else setDetail(old => old?.groupId === groupId ? { ...old, more: 'error' } : old)
        }
      } else if (isUnavailableAccountRead(cause)) {
        writeAccountProjectPageIntent(null)
        setDetail(old => old?.groupId === groupId ? { ...old, status: 'gone', projects: [], total: 0, cohort: '', parent: '', error: '' } : old)
      } else setDetail(old => old?.groupId === groupId ? { ...old, more: 'error' } : old)
    }
  }

  if (accountContextStatus !== 'valid') return <section className="cmp-company" aria-label="Account context verification" aria-live="polite">
    <button type="button" className="cmp-back" onClick={onBack}>{backLabel ?? 'Back'}</button>
    <p role="status">{accountContextStatus === 'unavailable' ? 'Account membership could not be confirmed. The selected project remains open.' : 'Checking the selected project’s account…'}</p>
  </section>
  return <section className="cmp-company" aria-label={`${isGroup ? 'Group' : 'Company'} ${name}`}>
    <button type="button" className="cmp-back" onClick={onBack}>{backLabel ?? (isGroup ? '← Back to the directory' : '← Back to companies')}</button>
    <h2>{name}</h2>
    {group && <p className="cmp-meta">{group.sectors.length ? group.sectors.map(sectorLabel).join(', ') : groupDescription(group).text} · {shortlist ? group.relevant_project_count ?? 0 : group.total_known_project_count ?? group.project_count} {shortlist ? 'relevant' : 'known'} {((shortlist ? group.relevant_project_count ?? 0 : group.total_known_project_count ?? group.project_count) === 1) ? 'project' : 'projects'}</p>}
    {group && isGroup && description && (group.sectors.length > 0 || description.identities) && <p className="cmp-note" role="status">{group.sectors.length > 0 ? description.text : null}{description.identities && <> {description.identities}.</>}</p>}
    {current?.status === 'error' && <p role="alert" className="cmp-error">{current.error} <button type="button" onClick={() => setRetry(value => value + 1)}>Retry</button></p>}
    {current?.status === 'gone' && <p role="alert" className="cmp-error">This account is no longer available in the current results.</p>}
    {!current && <p role="status">Loading account details…</p>}
    {current?.status === 'ready' && <>
      {matchedProjectId && matchedNeedId && <button type="button" onClick={() => openNeed(matchedNeedId, matchedProjectId)}>Open matching opportunity</button>}
      <section className="cmp-block" aria-label="Account overview">
        {whyNow && <p>{whyNow}</p>}
        {nextStep && <p>{nextStep}</p>}
        {(!group?.group_kind || group.group_kind === 'resolved_identity') ? <AccountContacts project={accountContactProject}/> : <p className="cmp-note">Select a project to see its supported business contact.</p>}
      </section>
      <CommercialAnalysis group={group} />
      <section aria-label="Linked pursuits" className="cmp-block">
        <h3>Linked pursuits</h3>
        {!pursuits.loaded ? <p role="status">Checking your pursuits…</p> : pursuits.error ? <p>Pursuits are unavailable: {pursuits.error}</p> : <>
          <ul>{linked.map(item => <li key={item.id}><button type="button" onClick={() => dispatchEvent(new CustomEvent('gl3-open-pursuit', { detail: item.id }))}>{item.title}</button> · {item.stage}</li>)}</ul>
          {!complete && <p className="cmp-note">Pursuit links are shown for the loaded projects.</p>}
          {pursuits.truncated && <p className="cmp-note" role="status">Only the first {pursuits.items.length} pursuits could be checked; links may be incomplete.</p>}
          {complete && linked.length === 0 && <p className="cmp-note">No pursuits are linked to this account’s projects.</p>}
        </>}
      </section>
      <section aria-label="Account projects" className="cmp-block">
        <h3>Projects</h3>
        {current.snapshot && <p className="cmp-note" role="status">{current.snapshot}</p>}
        {current.notice && <p className="cmp-note" role="status">{current.notice}</p>}
        {projects.length > 0 && <button type="button" onClick={() => downloadProjectPage(projects, group?.name, `Loaded projects (${projects.length} of ${current.total})`)}>Export loaded projects</button>}
        <ul className="cmp-projects">{projects.map(project => {
          const needId = project.representative_need_id ?? project.needs[0]?.id ?? null
          const own = pursuitByProject(project)
          const source = sourceUrl(project.event?.source)
          const development = project.shortlist_assessment?.why_now ?? project.event?.label
          const usefulPower = project.power_summary && !['unknown', 'source_context'].includes(project.power_summary_kind ?? '')
          const matchingNeedId = matchedNeedId && project.needs.some(need => need.id === matchedNeedId) ? matchedNeedId : null
          return <li key={project.id} data-project-id={project.project_id} tabIndex={matchedProjectId === project.project_id ? -1 : undefined} aria-current={matchedProjectId === project.project_id ? 'location' : undefined}>
            <strong>{project.name}</strong>
            <span>{[project.location, project.asset_type ? assetTypeLabel(project.asset_type) : null, project.sector ? sectorLabel(project.sector) : null].filter(Boolean).join(' · ')}</span>
            {project.event?.date && <span>Evidence event · {project.event.date}</span>}
            {development && <span>{development}</span>}
            {usefulPower && <span>{project.power_summary}{project.power_summary_kind === 'activity_requirement' ? ' · reported activity requirement' : ''}</span>}
            {own.length > 0 && <span className="cmp-badge">In Pursuits · {own.map(item => item.stage).join(', ')}</span>}
            <div className="cmp-project-links">
              {needId ? <button type="button" onClick={() => openNeed(matchingNeedId ?? needId, project.project_id)}>{matchingNeedId ? 'Open matching opportunity' : 'Open project detail'}<span className="cmp-sr"> {project.name}</span></button> : <span>No opportunity is linked to this project.</span>}
              <ProjectPursuitAction key={project.id} project={project} shortlist={shortlist}/>
            </div>
            {(source || project.event?.label) && <details><summary>Sources</summary><p>{project.event?.label ?? development ?? 'Project source'}</p>{source && <a href={source} target="_blank" rel="noreferrer">Open source</a>}</details>}
          </li>
        })}</ul>
        {projects.length === 0 && <p>No projects are listed for this account.</p>}
        {!complete && <p><button type="button" disabled={current.more === 'loading'} onClick={() => void loadMore()}>{current.more === 'loading' ? 'Loading…' : 'Load more projects'}</button>{current.more === 'error' && <span role="alert"> Could not refresh this project page. Try again.</span>}</p>}
      </section>
    </>}
  </section>
}

function appendDistinct(existing: ProjectResult[], incoming: ProjectResult[]) {
  const seen = new Set(existing.map(item => item.id))
  return [...existing, ...incoming.filter(item => !seen.has(item.id))]
}
