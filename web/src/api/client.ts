import { authenticatedSessionStarted, clearContinuity, currentSessionGeneration, endPursuitsSession, expireSession } from '../state/sessionState'
import type { components } from './generated'

export type EvidenceContent = {
  evidence_id: string
  content_hash: string
  source_url: string
  offset: number
  total_chars: number
  content: string
  next_offset: number | null
}

export type IntelligenceOperations = {
  window_days: number; sources: { source_id: string; enabled: boolean; last_attempt_at: string | null; last_success_at: string | null; last_good_preserved: boolean; checked_30d: number; failed_30d: number; partial_30d: number; parse_failures_30d: number; parse_success_30d: number | null; freshness_30d: string; due_30d: number }[]
  queue: { by_kind_status: Record<string, Record<string, number>>; oldest_queued_at: string | null; retried_jobs_30d: number; failed_after_three_attempts_30d: number }
  providers: { utc_day: { date: string; timezone: string; calls: number; known_cost_usd: number | null; reserved_cost_usd: number | null; reserved_known_subtotal_usd: number; unknown_cost_calls: number; daily_budget_status: string; daily_budget_rows: { scope: string; calls: number; reserved_usd: number }[]; daily_budget_limits_usd: Record<string, number>; daily_budget_limits_calls: Record<string, number> }; configured: Record<string, boolean>; enabled: Record<string, boolean>; by_provider: { provider: string; called: number; completed: number; accepted: number | null; models: Record<string, unknown>; actual_cost_usd: number | null; reserved_cost_usd: number | null; uncertain: number; failed: number; input_tokens: number; output_tokens: number; usage_known_calls: number; usage_unknown_calls: number; unknown_cost_calls: number; latency_p50_ms: number | null; latency_p95_ms: number | null }[]; reserved_cost_usd: number | null; reserved_known_subtotal_usd: number; known_cost_usd: number | null; known_cost_calls: number; unknown_cost_calls_all_time: number; total_cost_status: string; detail_rows_30d: number; detail_truncated: boolean; outstanding_uncertain_calls_all_time: number; uncertain_calls: number; accepted: number | null; accepted_reason: string }
  questions: { outcomes_30d: Record<string, number> }; material_changes_30d: number | null; reviewed_signals: number | null; independent_leads: number | null; backup: string; restore: string; last_verified_restore_at: string | null; last_reported_restore_at: string | null; operational_receipt: Record<string, unknown>; commercial_review_receipt: { status: string; reported_case_count: number | null; decision_counts: Record<string, number> | null; reviewer: string | null; reviewed_at: string | null; sample_sha256: string | null; context_sha256: string | null; cases: { case_id: string; need_id: string; decision: string; evidence_refs: { evidence_id: string; content_hash: string }[] }[]; independent_labels: string; quality_verification: string; acceptance: string }; owner_review_notes_30d: number
}
export type BuyingChainResult = components['schemas']['BuyingChainOut']
export type GlobalSearchResult = {
  query: string
  companies_status?: 'current' | 'qualification_pending'
  opportunities_status?: 'current' | 'qualification_pending'
  projects: { project_id: string; need_id: string; name: string; location: string | null; region_state: string | null; tier?: string | null; updated_at: string | null }[]
  companies: { company_identity_id: string; name: string; aliases?: string[]; project_count?: number; need_count?: number; supporting_evidence_count?: number; last_evidence_update?: string | null; qualification_tiers?: string[]; highest_priority_need?: Record<string, unknown> | null }[]
  contacts: { company_identity_id: string | null; project_id: string; need_id?: string | null; name: string | null; title: string | null; organization: string; methods: { kind: string; value: string }[]; sources: Record<string, unknown>[]; verification_status: string }[]
  opportunities: Record<string, unknown>[]
}
export type CommercialBriefSource = { title: string | null; url: string | null; evidence_id: string | null; date: string | null }
export type CommercialBrief = {
  version: string
  why_now: { text: string | null; source_date: string | null; scope: string | null; sources: CommercialBriefSource[] }
  power_need: { amount_class: 'documented' | 'calculated' | 'estimated' | 'inferred' | 'unknown'; scope: string | null; value: string | null; unit: string | null; status: string; limitations: string[] }
  best_contact: { contact: string; href?: string | null; kind: 'call' | 'email' | 'contact'; route_kind: 'person_method' | 'company_route'; authority: string; deliverability: string; sources: CommercialBriefSource[] } | null
  next_action: { text: string; kind: string; source: CommercialBriefSource | null }
  freshness: { as_of: string | null; status: string; source_date: string | null }
  limitations: string[]
  sources: CommercialBriefSource[]
}
export type Opportunity = components['schemas']['OpportunityOut'] & { commercial_brief?: CommercialBrief | null }
export type WorkspaceNeed = components['schemas']['PursuitWorkspaceItemOut'] & { commercial_brief?: CommercialBrief | null }
export type WorkspacePage = components['schemas']['PursuitWorkspacePageOut']
export type ProjectResultNeed = { id: string; project_id?: string; name?: string | null; browse_title?: string | null; location?: string | null; activity?: string | null; tier?: 'Signal' | 'Prospect' | 'Lead' | null; commercial_brief?: CommercialBrief | null; commercial_preview?: { disposition?: string | null; reason?: string | null; next_question?: string | null; next_action?: string | null; organization?: string | null } }
export type PursuitStage = 'New' | 'Contacted' | 'Engaged' | 'Proposal' | 'Won' | 'Lost'
export const PURSUIT_STAGES: PursuitStage[] = ['New', 'Contacted', 'Engaged', 'Proposal', 'Won', 'Lost']
export type PursuitTask = { id: string; description: string; due_date: string | null; completed_at: string | null }
export type PursuitActivity = { id: string; kind: string; summary: string; detail: string | null; occurred_at: string }
export type PursuitContact = { name: string | null; role: string | null; company: string | null; phone: string | null; email: string | null }
export type CommercialPursuit = {
  id: string; need_id: string; need_alias_ids?: string[]; project_id: string; account_id?: string | null; account_name?: string | null; stage: PursuitStage; title: string; location: string | null; tier: string
  required_mw: string | null; start_window: string | null; contact: PursuitContact | null; contact_status: 'available' | 'missing' | 'unknown'
  attention: string[]; attention_labels: string[]; next_task: PursuitTask | null; created_at: string; stage_changed_at: string
  tasks?: PursuitTask[] | null; activity?: PursuitActivity[] | null
}
export type CommercialPursuitList = { items: CommercialPursuit[]; counts: { total: number; active: number; needs_attention: number }; total_matching?: number; has_more?: boolean; next_offset?: number | null }
export type ProjectResultContactPerson = { record_type?: 'contact_person'; company_identity_id?: string | null; person_identity_id?: string | null; company?: string | null; name?: string | null; title?: string | null; role?: string | null; responsibility?: string | null; purchasing_authority?: string | null; source_url?: string | null }
export type ShortlistAssessment = { eligible: boolean; reasons: string[]; evidence_refs: string[]; why_now: string | null; next_step: string | null; source_subject?: string | null; scope?: string | null }
export type ProjectResultsSort = 'priority' | 'priority_asc' | 'company' | 'project' | 'updated'
export type ProjectResult = { eligible_need_ids?: string[]; id: string; project_id: string; project_ids?: string[]; customer_identity_id?: string | null; name: string; company: string | null; location: string | null; sector: 'oil_gas' | 'data_centers' | null; asset_type: string | null; priority_score: number | null; representative_need_id: string | null; commercial_brief?: CommercialBrief | null; needs: ProjectResultNeed[]; need_count: number; event: { kind: string; label: string; date: string | null; source?: string | null; evidence_refs?: unknown[] } | null; contact: { kind: string; label: string; href?: string | null; name?: string | null; title?: string | null; company?: string | null; route_kind?: string | null; responsibility?: string | null; support?: string | null; source_url?: string | null; verified_at?: string | null }[]; contact_people?: ProjectResultContactPerson[]; power_summary: string | null; power_amount_class?: 'documented' | 'calculated' | 'estimated' | 'inferred' | 'unknown'; power_summary_kind?: 'supported_gap' | 'activity_requirement' | 'facility_demand' | 'source_context' | 'unknown'; next_action: string | null; shortlist_assessment?: ShortlistAssessment | null; updated_at: string | null }
export type BrowseGenerationMetadata = { generation_id?: string; as_of?: string; valid_until?: string; qualification_state?: 'current' | string; refresh_state?: 'current' | 'updating' | string }
/** The server may serve its last complete snapshot while newer source data is republished. */
export const browseRefreshIsServable = (state?: string) => !state || state === 'current' || state === 'updating'
/** Tell the reader how old the visible snapshot is; empty when results are current. */
export function browseUpdatingNotice(value: BrowseGenerationMetadata): string {
  if (value.refresh_state !== 'updating') return ''
  const asOf = value.as_of ? Date.parse(value.as_of) : NaN
  return Number.isFinite(asOf)
    ? `Showing results as of ${new Date(asOf).toLocaleString()}. Newer source data is still being processed.`
    : 'Showing the last prepared results. Newer source data is still being processed.'
}
/** Reject browse metadata that has expired before the client can display it. */
function requireCurrentBrowseGeneration(value: BrowseGenerationMetadata) {
  if ((value.qualification_state && value.qualification_state !== 'current') || !browseRefreshIsServable(value.refresh_state)) {
    throw new Error('Current operator/customer results could not be confirmed.')
  }
  if (value.valid_until) {
    const validUntil = Date.parse(value.valid_until)
    if (!Number.isFinite(validUntil) || Date.now() >= validUntil) throw new Error('These prepared results have expired and must be refreshed.')
  }
}
export type ProjectResultsPage = BrowseGenerationMetadata & { items: ProjectResult[]; total: number; count_unit: 'projects'; limit: number; offset: number; cohort_token: string; generation: string; results_scope?: 'qualified' | 'discovery' }
export type DemandSummary = { counts_complete?: boolean; availability: 'available' | 'unavailable'; sector: 'all' | 'oil_gas' | 'data_centers'; as_of: string | null; totals: { identified_records: number; known_mw_records: number; unknown_records: number; conflicted_records: number }; classes: { documented: { mw: number | null; record_count: number }; calculated: { mw: number | null; record_count: number }; estimated: { mw: number | null; record_count: number } }; provenance: { contract: string; source_count: number; latest_evidence_at: string | null }; limitations: string[] }
/** Validate an API demand summary and bind it to the requested sector. */
function parseDemandSummary(value: unknown, requestedSector: DemandSummary['sector']): DemandSummary {
  const record = (input: unknown): input is Record<string, unknown> => typeof input === 'object' && input !== null && !Array.isArray(input)
  const count = (input: unknown) => Number.isSafeInteger(input) && (input as number) >= 0
  const nullableNumber = (input: unknown) => input === null || (typeof input === 'number' && Number.isFinite(input) && input >= 0)
  const nullableDate = (input: unknown) => input === null || (typeof input === 'string' && Number.isFinite(Date.parse(input)))
  const invalid = (): never => { throw new Error('Demand summary response is invalid.') }
  const body = record(value) ? value : invalid()
  const totals = body.totals
  const classes = body.classes
  const provenance = body.provenance
  if (body.sector !== requestedSector || !['available', 'unavailable'].includes(String(body.availability)) ||
      (body.counts_complete !== undefined && typeof body.counts_complete !== 'boolean') || !nullableDate(body.as_of) ||
      !record(totals) || !['identified_records', 'known_mw_records', 'unknown_records', 'conflicted_records'].every(key => count(totals[key])) ||
      !record(classes) || !(['documented', 'calculated', 'estimated'] as const).every(key => record(classes[key]) && nullableNumber(classes[key].mw) && count(classes[key].record_count)) ||
      !record(provenance) || typeof provenance.contract !== 'string' || !count(provenance.source_count) || !nullableDate(provenance.latest_evidence_at) ||
      !Array.isArray(body.limitations) || !body.limitations.every(item => typeof item === 'string')) invalid()
  return body as unknown as DemandSummary
}
export type CommercialCustomerIntelligence = {
  version: string
  capacity: { status: string; totals: Array<{ basis: string; value_mw: string | null; status: string; qualifier?: string; complete?: boolean; claim_ids?: string[] }>; coverage?: Record<string, unknown>; claims?: Array<Record<string, unknown>>; conflicts?: unknown[]; conflict_count?: number }
  timelines: { construction_start?: { label: string; precision?: string; event_type?: string } | null; expected_energization?: { label: string; precision?: string; event_type?: string } | null; claims?: Array<Record<string, unknown>>; conflicts?: unknown[]; conflict_count?: number }
  commissioning?: { status: string; version?: string; base_mw?: string | null; low_mw?: string | null; high_mw?: string | null; assumptions?: string[]; limitations?: string[]; [key: string]: unknown }
  recent_developments: Array<Record<string, unknown>>
  priority: { potential: number; confidence: number; score: number; components?: Record<string, unknown>; version: string }
  recommended_next_action: string
  source_count?: number
  details_available?: boolean
  sources?: Array<Record<string, unknown>>
  limitations: string[]
}
export type OpportunityGroup = { commercial_intelligence?: CommercialCustomerIntelligence; pursued_eligible_need_count?: number; matched_need_id?: string | null; matched_project_id?: string | null; eligible_need_count?: number; featured_project?: ProjectResult | null; account_contact_project?: ProjectResult | null; relevant_project_count?: number; total_known_project_count?: number; id: string; name: string; role: 'operator' | 'customer' | 'unresolved'; group_kind?: 'resolved_identity' | 'same_name_unconfirmed' | 'unresolved'; identity_count?: number; operator_number?: string | null; project_count: number; need_count: number; priority_score?: number | null; sectors: string[] }
export type OpportunityGroupsPage = BrowseGenerationMetadata & { totals?: { accounts: number; projects: number; needs: number }; items: OpportunityGroup[]; total: number; count_unit: 'groups'; limit: number; offset: number; cohort_token: string; generation: string; facets?: { regions: string[]; stages: string[] } }
export type CustomerRollupFilters = { region?: string; stage?: string; priority?: 'ranked' | 'unranked' | '' }
export type CustomerRollupSort = 'priority' | 'priority_asc' | 'company' | 'updated'
export type OpportunityGroupOpen = BrowseGenerationMetadata & { group: OpportunityGroup; projects: ProjectResultsPage; parent_cohort_token: string; generation: string }
export class OpportunityGroupUnavailableError extends Error {
  constructor() { super('This operator/customer group is no longer available in the current results.'); this.name = 'OpportunityGroupUnavailableError' }
}
export type CustomerAccount = components['schemas']['CustomerAccountOut']
export type CustomerProjectsPage = components['schemas']['CustomerProjectsPageOut']
export type UnresolvedCustomerProjectsPage = components['schemas']['UnresolvedCustomerProjectsPageOut']
export type WorkspaceChanges = components['schemas']['WorkspaceChangesOut']
export type WorkspaceChangeNeed = components['schemas']['WorkspaceChangeNeedOut']
export type WorkspaceHistoricalNeed = components['schemas']['WorkspaceHistoricalNeedOut']
export type WorkspaceFilters = { search?: string; tier?: 'Signal' | 'Prospect' | 'Lead'; disposition?: string; geography?: string; industry?: string; industry_group?: 'industrial'; activity?: string; timing?: 'KNOWN' | 'UNKNOWN'; mw_min?: string; mw_max?: string; sort?: 'priority' | 'project' | 'mw' | 'start' | 'updated'; offset?: number; cohort_token?: string }
export type OpportunityBrowseFilters = {
  geography?: string
  industry?: string
  industryGroup?: 'industrial'
  activity?: string
  timing?: 'KNOWN' | 'UNKNOWN' | ''
  mwStatus?: 'KNOWN' | 'UNKNOWN' | ''
  mwMin?: string
  mwMax?: string
  prioritySegment?: string
}
export type OpportunityPage = {
  items: Opportunity[]
  totalCount: number
  /** False when the response lacked a numeric X-Total-Count; totalCount is then a placeholder 0, not a count. */
  totalCountKnown: boolean
  groupTotalCount: number
  pageRecordCount: number
  pageGroupCount: number
  limit: number
  offset: number
  nextOffset: number | null
  cohortToken: string
  decisionCounts: Record<'SHOW' | 'REVIEW' | 'HOLD', number>
}
export type OpportunityMapWindow = {
  items: Opportunity[]
  totalCount: number
  loadedCount: number
  isSubset: boolean
  windowLimit: number
  groupTotalCount: number
  cohortToken: string
  decisionCounts: Record<'SHOW' | 'REVIEW' | 'HOLD', number>
}
export type OpportunityNeedScope = {
  tier: string
  search: string
  decision: string
  cohortToken?: string
  filters?: OpportunityBrowseFilters
}
export type OpportunityGroupPage = components['schemas']['OpportunityGroupPageOut']
export type SourceHealth = components['schemas']['HealthSourceOut']
export type Evidence = components['schemas']['EvidenceOut']
export type IngestionItem = components['schemas']['IngestionItemOut']
export type IngestionPage = components['schemas']['IngestionPageOut']
export type AutonomousResearch = components['schemas']['AutonomousResearchOut']
export type ResearchOverview = components['schemas']['ResearchOverviewOut']
export type ResearchRoute = components['schemas']['ResearchRouteOut']
export type ResearchQuestion = components['schemas']['ResearchQuestionOut']

export type CompanyGraph = components['schemas']['CompanyGraphOut']
export type CompanyGraphEvidence = components['schemas']['GraphEvidence']

/** Bind every protected fetch to its starting session; discard late responses and expire only a matching 401. */
async function sessionFetch(path: string, init?: RequestInit, onUnauthorized: (generation: number) => unknown = expireSession) {
  const generation = currentSessionGeneration()
  const response = await fetch(path, init)
  if (generation !== currentSessionGeneration()) throw new DOMException('Request belongs to an earlier session.', 'AbortError')
  if (response.status === 401) onUnauthorized(generation)
  return response
}

/** Decode a protected API response while preventing a late body from repopulating a newer session. */
async function api<T>(path: string, init?: RequestInit, includeSafeDetail = false): Promise<T> {
  const requestGeneration = currentSessionGeneration()
  const response = await sessionFetch(path, { ...init, credentials: 'same-origin', headers: { 'content-type': 'application/json', ...init?.headers } })
  if (response.status === 401) throw new Error('Your session ended. Sign in again.')
  if (!response.ok) {
    if (includeSafeDetail) {
      try {
        const payload = await response.clone().json() as { detail?: unknown }
        if (typeof payload.detail === 'string' && payload.detail.length <= 300) throw new Error(`GridLens could not complete this request (${response.status}): ${payload.detail}`)
      } catch (cause) {
        if (cause instanceof Error && cause.message.startsWith('GridLens could not complete this request')) throw cause
      }
    }
    throw new Error(`GridLens could not complete this request (${response.status}).`)
  }
  const value = await response.json() as T
  if (currentSessionGeneration() !== requestGeneration) throw new DOMException('Request belongs to an earlier session.', 'AbortError')
  return value
}

/** Add only populated optional filters to an opportunity browse request. */
function addBrowseFilters(params: URLSearchParams, filters: OpportunityBrowseFilters = {}) {
  const entries: [string, string | undefined][] = [
    ['geography', filters.geography], ['industry', filters.industry], ['industry_group', filters.industryGroup], ['activity', filters.activity],
    ['timing', filters.timing], ['mw_status', filters.mwStatus], ['mw_min', filters.mwMin],
    ['mw_max', filters.mwMax], ['priority_segment', filters.prioritySegment],
  ]
  for (const [key, value] of entries) if (value) params.set(key, value)
}

async function opportunityPage(tier: string, search: string, decision: string, limit: number, offset: number, cohortToken?: string, filters: OpportunityBrowseFilters = {}, signal?: AbortSignal, sort?: 'rank'): Promise<OpportunityPage> {
  const params = new URLSearchParams({ tier, search, decision, limit: String(limit), offset: String(offset) })
  if (cohortToken) params.set('cohort_token', cohortToken)
  if (sort) params.set('sort', sort)
  addBrowseFilters(params, filters)
  const response = await sessionFetch(`/api/opportunities?${params}`, { credentials: 'same-origin', signal })
  if (response.status === 401) throw new Error('Your session ended. Sign in again.')
  if (response.status === 409) throw new OpportunityCohortChangedError()
  if (!response.ok) throw new Error(`GridLens could not complete this request (${response.status}).`)
  const items = await response.json() as Opportunity[]
  const header = (name: string) => Number(response.headers.get(name) ?? '0')
  const totalHeader = response.headers.get('X-Total-Count')
  let decisionCounts: OpportunityPage['decisionCounts'] = { SHOW: 0, REVIEW: 0, HOLD: 0 }
  try {
    decisionCounts = { ...decisionCounts, ...JSON.parse(response.headers.get('X-Decision-Counts') ?? '{}') as OpportunityPage['decisionCounts'] }
  } catch { /* Counts stay explicitly empty when an older backend is in front. */ }
  const nextOffset = response.headers.get('X-Next-Offset')
  return {
    items,
    totalCount: header('X-Total-Count'),
    totalCountKnown: totalHeader !== null && totalHeader.trim() !== '' && Number.isFinite(Number(totalHeader)),
    groupTotalCount: header('X-Group-Total-Count'),
    pageRecordCount: header('X-Page-Record-Count'),
    pageGroupCount: header('X-Page-Group-Count'),
    limit: header('X-Limit'),
    offset: header('X-Offset'),
    nextOffset: nextOffset === null ? null : Number(nextOffset),
    cohortToken: response.headers.get('X-Cohort-Token') ?? '',
    decisionCounts,
  }
}

async function opportunityMapWindow(tier: string, search: string, filters: OpportunityBrowseFilters = {}, signal?: AbortSignal): Promise<OpportunityMapWindow> {
  const params = new URLSearchParams({ tier, search, decision: 'ALL' })
  addBrowseFilters(params, filters)
  const response = await sessionFetch(`/api/opportunities/map-window?${params}`, { credentials: 'same-origin', signal })
  if (response.status === 401) throw new Error('Your session ended. Sign in again.')
  if (response.status === 409) throw new OpportunityCohortChangedError()
  if (!response.ok) throw new Error(`GridLens could not complete this request (${response.status}).`)
  const result = await response.json() as components['schemas']['OpportunityMapWindowOut']
  return {
    items: result.items,
    totalCount: result.total_count,
    loadedCount: result.loaded_count,
    isSubset: result.is_subset,
    windowLimit: result.window_limit,
    groupTotalCount: result.group_total_count,
    cohortToken: result.cohort_token,
    decisionCounts: {
      SHOW: result.decision_counts.SHOW ?? 0,
      REVIEW: result.decision_counts.REVIEW ?? 0,
      HOLD: result.decision_counts.HOLD ?? 0,
    },
  }
}

export class OpportunityCohortChangedError extends Error {
  constructor() {
    super('Opportunity cohort changed; restart pagination from the first page.')
    this.name = 'OpportunityCohortChangedError'
  }
}

const PENDING_RETRY_FALLBACK_MS = 1_000
const PENDING_RETRY_MAX_MS = 30_000

export class OpportunityBrowsePendingError extends Error {
  constructor(readonly retryAfterMs: number) {
    super('Operator/customer results are still being prepared.')
    this.name = 'OpportunityBrowsePendingError'
  }
}

/** Parse and clamp the server retry delay, using a safe fallback when invalid. */
function parsePendingRetryAfter(value: string | null): number {
  if (!value) return PENDING_RETRY_FALLBACK_MS
  let milliseconds: number
  if (/^\d+$/.test(value.trim())) {
    milliseconds = Number(value.trim()) * 1_000
  } else {
    const retryAt = Date.parse(value)
    if (!Number.isFinite(retryAt)) return PENDING_RETRY_FALLBACK_MS
    milliseconds = retryAt - Date.now()
  }
  if (!Number.isFinite(milliseconds)) return PENDING_RETRY_FALLBACK_MS
  return Math.max(PENDING_RETRY_FALLBACK_MS, Math.min(PENDING_RETRY_MAX_MS, milliseconds))
}

/** Convert a pending browse response into the client's retry-aware error. */
function throwIfBrowsePending(response: Response): void {
  if (response.status !== 503 || response.headers.get('X-Qualification-State')?.trim().toLowerCase() !== 'pending') return
  throw new OpportunityBrowsePendingError(parsePendingRetryAfter(response.headers.get('Retry-After')))
}

export class OpportunityNeedUnavailableError extends Error {
  constructor() {
    super('The selected opportunity is not available in this filtered cohort.')
    this.name = 'OpportunityNeedUnavailableError'
  }
}

async function opportunityNeed(needId: string, scope?: OpportunityNeedScope, signal?: AbortSignal): Promise<Opportunity> {
  // Omit scope for identity resolution. The server still enforces authentication and
  // opportunity eligibility; a map cohort is deliberately not an identity boundary.
  const params = new URLSearchParams(scope ? {
    tier: scope.tier, search: scope.search, decision: scope.decision,
    ...(scope.cohortToken ? { cohort_token: scope.cohortToken } : {}),
  } : {})
  addBrowseFilters(params, scope?.filters)
  const response = await sessionFetch(`/api/opportunities/needs/${encodeURIComponent(needId)}?${params}`, {
    credentials: 'same-origin',
    signal,
  })
  if (response.status === 401) throw new Error('Your session ended. Sign in again.')
  if (response.status === 409) throw new OpportunityCohortChangedError()
  if (response.status === 404) throw new OpportunityNeedUnavailableError()
  if (!response.ok) throw new Error(`GridLens could not complete this request (${response.status}).`)
  return response.json() as Promise<Opportunity>
}

export const client = {
  demandSummary: async (sector: 'all' | 'oil_gas' | 'data_centers', signal?: AbortSignal): Promise<DemandSummary> => {
    const response = await sessionFetch(`/api/opportunities/demand-summary?${new URLSearchParams({ sector })}`, { credentials: 'same-origin', signal })
    if (response.status === 401) throw new Error('Your session ended. Sign in again.')
    if (!response.ok) throw new Error(`Could not load identified power demand (${response.status}).`)
    return parseDemandSummary(await response.json() as unknown, sector)
  },
  opportunityGroups: async (query: { search?: string; sector?: 'all' | 'oil_gas' | 'data_centers'; limit?: number; offset?: number; cohort_token?: string; sort?: CustomerRollupSort; region?: string; stage?: string; priority?: CustomerRollupFilters['priority']; shortlist?: boolean }, signal?: AbortSignal): Promise<OpportunityGroupsPage> => {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(query)) if (value !== undefined && value !== '') params.set(key, String(value))
    const response = await sessionFetch(`/api/opportunities/groups?${params}`, { credentials: 'same-origin', signal })
    if (response.status === 401) throw new Error('Your session ended. Sign in again.')
    if (response.status === 409) throw new OpportunityCohortChangedError()
    throwIfBrowsePending(response)
    if (!response.ok) throw new Error(`Could not load operator/customer groups (${response.status}).`)
    const value = await response.json() as OpportunityGroupsPage
    requireCurrentBrowseGeneration(value)
  return value
  },
  groupProjects: async (groupId: string, query: { search?: string; sector?: 'all' | 'oil_gas' | 'data_centers'; limit?: number; offset?: number; cohort_token?: string; parent_cohort_token?: string; sort?: CustomerRollupSort; region?: string; stage?: string; priority?: CustomerRollupFilters['priority']; shortlist?: boolean }, signal?: AbortSignal): Promise<ProjectResultsPage & { group?: Pick<OpportunityGroup, 'id' | 'name' | 'role'> }> => {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(query)) if (value !== undefined && value !== '') params.set(key, String(value))
    const response = await sessionFetch(`/api/opportunities/groups/${encodeURIComponent(groupId)}/projects?${params}`, { credentials: 'same-origin', signal })
    if (response.status === 401) throw new Error('Your session ended. Sign in again.')
    if (response.status === 404) throw new OpportunityGroupUnavailableError()
    if (response.status === 409) throw new OpportunityCohortChangedError()
    throwIfBrowsePending(response)
    if (!response.ok) throw new Error(`Could not load projects (${response.status}).`)
    const value = await response.json() as ProjectResultsPage & { group?: Pick<OpportunityGroup, 'id' | 'name' | 'role'> }
    requireCurrentBrowseGeneration(value)
    return value
  },
  openOpportunityGroup: async (groupId: string, query: { search?: string; sector?: 'all' | 'oil_gas' | 'data_centers'; limit?: number; sort?: CustomerRollupSort; region?: string; stage?: string; priority?: CustomerRollupFilters['priority']; shortlist?: boolean }, signal?: AbortSignal): Promise<OpportunityGroupOpen> => {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(query)) if (value !== undefined && value !== '') params.set(key, String(value))
    const response = await sessionFetch(`/api/opportunities/groups/${encodeURIComponent(groupId)}/open?${params}`, { credentials: 'same-origin', signal })
    if (response.status === 401) throw new Error('Your session ended. Sign in again.')
    if (response.status === 404) throw new OpportunityGroupUnavailableError()
    throwIfBrowsePending(response)
    if (!response.ok) throw new Error(`Could not open current operator/customer results (${response.status}).`)
    const value = await response.json() as OpportunityGroupOpen
    requireCurrentBrowseGeneration(value)
    requireCurrentBrowseGeneration(value.projects)
    return value
  },
  /** Fetch a bounded project page with optional filters and source shortlist mode. */
  projectResults: async (query: { search?: string; sector?: 'all' | 'oil_gas' | 'data_centers'; limit?: number; offset?: number; cohort_token?: string; sort?: ProjectResultsSort; need_id?: string; include_signals?: boolean; shortlist?: boolean }, signal?: AbortSignal): Promise<ProjectResultsPage> => {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(query)) if (value !== undefined && value !== '') params.set(key, String(value))
    const response = await sessionFetch(`/api/opportunities/projects?${params}`, { credentials: 'same-origin', signal })
    if (response.status === 401) throw new Error('Your session ended. Sign in again.')
    if (response.status === 409) throw new OpportunityCohortChangedError()
    if (!response.ok) throw new Error(`Could not load projects (${response.status}).`)
    const value: unknown = await response.json()
    const record = (input: unknown): input is Record<string, unknown> => typeof input === 'object' && input !== null && !Array.isArray(input)
    const nonEmpty = (input: unknown): input is string => typeof input === 'string' && input.trim().length > 0
    const rowsAreValid = record(value) && Array.isArray(value.items) && value.items.every(project =>
      record(project) && nonEmpty(project.id) && nonEmpty(project.project_id) && nonEmpty(project.name)
      && Array.isArray(project.needs) && project.needs.every(need => record(need) && nonEmpty(need.id)),
    )
    const pageIsValid = record(value)
      && rowsAreValid
      && Number.isSafeInteger(value.total) && (value.total as number) >= 0
      && value.count_unit === 'projects'
      && Number.isSafeInteger(value.limit) && (value.limit as number) > 0
      && Number.isSafeInteger(value.offset) && (value.offset as number) >= 0
      && nonEmpty(value.cohort_token)
      && nonEmpty(value.generation)
    if (!pageIsValid) throw new Error('Current project results could not be confirmed. Refresh to retry.')
    return value as ProjectResultsPage
  },
  search: (query: string, signal?: AbortSignal) => api<GlobalSearchResult>(`/api/search?${new URLSearchParams({ q: query, limit: '20' })}`, { signal }),
  workspace: async (filters: WorkspaceFilters = {}, signal?: AbortSignal): Promise<WorkspacePage> => {
    const params = new URLSearchParams({ limit: '25' })
    params.set('group_by', 'account')
    for (const [key, value] of Object.entries(filters)) if (value !== undefined && value !== '') params.set(key, String(value))
    const response = await sessionFetch(`/api/opportunities/workspace?${params}`, { credentials: 'same-origin', signal })
    if (response.status === 401) throw new Error('Your session ended. Sign in again.')
    if (response.status === 409) throw new OpportunityCohortChangedError()
    if (!response.ok) throw new Error(response.status === 503 ? 'The workspace cohort is unavailable. Retry to reload current opportunities.' : `GridLens could not complete this request (${response.status}).`)
    return response.json() as Promise<WorkspacePage>
  },
  resolveProjectAccount: async (projectId: string, signal?: AbortSignal): Promise<Pick<OpportunityGroup, 'id' | 'name' | 'group_kind'> & { project_id?: string }> => {
    const response = await sessionFetch(`/api/projects/${encodeURIComponent(projectId)}/account`, { credentials: 'same-origin', signal })
    if (response.status === 401) throw new Error('Your session ended. Sign in again.')
    if (response.status === 404) throw new OpportunityGroupUnavailableError()
    throwIfBrowsePending(response)
    if (!response.ok) throw new Error(`Could not verify the current account (${response.status}).`)
    const account = await response.json() as Pick<OpportunityGroup, 'id' | 'name' | 'group_kind'> & { project_id?: string }
    if (!account || typeof account.id !== 'string' || !account.id.startsWith('cg_') || typeof account.name !== 'string') throw new Error('The current account response is unavailable.')
    return account
  },
  resolveCompanyAccount: async (companyId: string, signal?: AbortSignal): Promise<Pick<OpportunityGroup, 'id' | 'name' | 'group_kind'>> => {
    const response = await sessionFetch(`/api/companies/${encodeURIComponent(companyId)}/account`, { credentials: 'same-origin', signal })
    if (response.status === 401) throw new Error('Your session ended. Sign in again.')
    if (response.status === 404) throw new OpportunityGroupUnavailableError()
    throwIfBrowsePending(response)
    if (!response.ok) throw new Error(`Could not resolve the current account (${response.status}).`)
    const account = await response.json() as Pick<OpportunityGroup, 'id' | 'name' | 'group_kind'>
    if (!account || typeof account.id !== 'string' || !account.id.startsWith('cg_') || typeof account.name !== 'string') throw new Error('The current account response is unavailable.')
    return account
  },
  companyContacts: async (companyIdentityId: string, signal?: AbortSignal): Promise<components['schemas']['CompanyContacts']> => {
    const response = await sessionFetch(`/api/customer-accounts/${encodeURIComponent(companyIdentityId)}/contacts`, { credentials: 'same-origin', signal })
    if (response.status === 401) throw new Error('Your session ended. Sign in again.')
    if (!response.ok) throw new Error(`Could not load contacts (${response.status}).`)
    return response.json()
  },
  companyGraph: async (companyIdentityId: string, signal?: AbortSignal): Promise<CompanyGraph> => {
    const response = await sessionFetch(`/api/companies/${encodeURIComponent(companyIdentityId)}/graph`, { credentials: 'same-origin', signal })
    if (response.status === 401) throw new Error('Your session ended. Sign in again.')
    if (!response.ok) throw new Error(`Could not load company intelligence (${response.status}).`)
    return response.json() as Promise<CompanyGraph>
  },
  customerAccountProjects: async (companyIdentityId: string, offset = 0, needOffset = 0, signal?: AbortSignal): Promise<CustomerProjectsPage> => {
    const params = new URLSearchParams({ limit: '25', offset: String(offset), need_limit: '25', need_offset: String(needOffset) })
    const response = await sessionFetch(`/api/customer-accounts/${encodeURIComponent(companyIdentityId)}/projects?${params}`, { credentials: 'same-origin', signal })
    if (response.status === 401) throw new Error('Your session ended. Sign in again.')
    if (!response.ok) throw new Error(`GridLens could not load this account's projects (${response.status}).`)
    return response.json() as Promise<CustomerProjectsPage>
  },
  unresolvedCustomerProjects: async (search = '', offset = 0, signal?: AbortSignal): Promise<UnresolvedCustomerProjectsPage> => {
    const params = new URLSearchParams({ limit: '25', offset: String(offset) })
    if (search) params.set('search', search)
    const response = await sessionFetch(`/api/customer-accounts/unresolved?${params}`, { credentials: 'same-origin', signal })
    if (response.status === 401) throw new Error('Your session ended. Sign in again.')
    if (!response.ok) throw new Error(`GridLens could not load unresolved customer projects (${response.status}).`)
    return response.json() as Promise<UnresolvedCustomerProjectsPage>
  },
  workspaceChanges: (limit = 50, offset = 0, signal?: AbortSignal) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    return api<WorkspaceChanges>(`/api/opportunities/workspace/changes?${params}`, { signal })
  },
  workspaceHistoricalNeed: (needId: string, signal?: AbortSignal) => api<WorkspaceHistoricalNeed>(
    `/api/opportunities/needs/${encodeURIComponent(needId)}/history`, { signal },
  ),
  buyingChain: (projectId: string, signal?: AbortSignal) => api<BuyingChainResult>(`/api/projects/${encodeURIComponent(projectId)}/buying-chain`, { signal }),
  autonomousResearch: (needId: string, signal?: AbortSignal) => api<AutonomousResearch>(`/api/commercial/triage/${encodeURIComponent(needId)}/autonomous-research`, { signal }, true),
  intelligenceOperations: (signal?: AbortSignal) => api<IntelligenceOperations>('/api/intelligence/operations', { signal }),
  evidenceContent: (evidenceId: string, offset = 0, limit = 4096, signal?: AbortSignal) => {
    const params = new URLSearchParams({ offset: String(offset), limit: String(limit) })
    return api<EvidenceContent>(`/api/evidence/${encodeURIComponent(evidenceId)}/content?${params}`, { signal }, true)
  },
  session: () => api<{ authenticated: boolean }>('/api/auth/session').then((session) => {
    if (!session.authenticated) clearContinuity()
    return session
  }),
  /** Background reads also expire the shell on a current-session 401; old responses are ignored by generation. */
  commercialPursuits: (filters: { needsAttention?: boolean; activeOnly?: boolean; needId?: string; background?: boolean; limit?: number; offset?: number } = {}, signal?: AbortSignal) => {
    const params = new URLSearchParams()
    if (filters.needsAttention) params.set('needs_attention', 'true')
    if (filters.activeOnly) params.set('active_only', 'true')
    if (filters.needId) params.set('need_id', filters.needId)
    if (filters.limit) params.set('limit', String(filters.limit))
    if (filters.offset) params.set('offset', String(filters.offset))
    const path = `/api/commercial-pursuits?${params}`
    const read = filters.background
      ? sessionFetch(path, { credentials: 'same-origin', signal }, endPursuitsSession).then(response => {
        if (!response.ok) throw new Error(response.status === 401 ? 'Your session ended. Sign in again.' : `GridLens could not complete this request (${response.status}).`)
        return response.json() as Promise<CommercialPursuitList>
      })
      : api<CommercialPursuitList>(path, { signal })
    return read.then(list => {
      if (!list || !Array.isArray(list.items) || typeof list.counts?.active !== 'number') throw new Error('Pursuits response was not recognised.')
      return list
    })
  },
  commercialPursuit: (id: string, signal?: AbortSignal) => api<CommercialPursuit>(`/api/commercial-pursuits/${encodeURIComponent(id)}`, { signal }),
  createCommercialPursuit: (needId: string) => api<CommercialPursuit>('/api/commercial-pursuits', { method: 'POST', body: JSON.stringify({ need_id: needId }) }, true),
  setPursuitStage: (id: string, stage: PursuitStage) => api<CommercialPursuit>(`/api/commercial-pursuits/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify({ stage }) }, true),
  addPursuitTask: (id: string, task: { description: string; due_date?: string | null; client_id?: string }) => api<CommercialPursuit>(`/api/commercial-pursuits/${encodeURIComponent(id)}/tasks`, { method: 'POST', body: JSON.stringify(task) }, true),
  updatePursuitTask: (id: string, taskId: string, patch: { description?: string; due_date?: string | null; clear_due_date?: boolean; completed?: boolean }) => api<CommercialPursuit>(`/api/commercial-pursuits/${encodeURIComponent(id)}/tasks/${encodeURIComponent(taskId)}`, { method: 'PATCH', body: JSON.stringify(patch) }, true),
  logPursuitActivity: (id: string, entry: { kind: 'call' | 'email' | 'meeting' | 'note'; summary: string; detail?: string | null; client_id: string }) => api<CommercialPursuit>(`/api/commercial-pursuits/${encodeURIComponent(id)}/activity`, { method: 'POST', body: JSON.stringify({ ...entry, confirmed: true }) }, true),
  login: (password: string) => api<{ authenticated: boolean }>('/api/auth/login', { method: 'POST', body: JSON.stringify({ password }) }).then(session => { if (session.authenticated) authenticatedSessionStarted(); return session }),
  logout: () => api('/api/auth/logout', { method: 'POST' }).finally(clearContinuity),
  opportunityPage,
  opportunityMapWindow,
  opportunityGroupPage: (groupId: string, tier: string, search: string, decision: string, cohortToken: string, limit: number, offset: number, filters: OpportunityBrowseFilters = {}, signal?: AbortSignal) => {
    const params = new URLSearchParams({ tier, search, decision, cohort_token: cohortToken, limit: String(limit), offset: String(offset) })
    addBrowseFilters(params, filters)
    return api<OpportunityGroupPage>(`/api/opportunity-groups/${encodeURIComponent(groupId)}?${params}`, { signal })
  },
  opportunityNeed,
  opportunityExportUrl: (tier: string, search: string, decision: string, cohortToken?: string, filters: OpportunityBrowseFilters = {}) => {
    const params = new URLSearchParams({ tier, search, decision })
    if (cohortToken) params.set('cohort_token', cohortToken)
    addBrowseFilters(params, filters)
    return `/api/opportunities/export.csv?${params.toString()}`
  },
  changes: () => api<{ kind: string; title: string; url: string; published_at: string | null }[]>('/api/changes'),
  health: () => api<components['schemas']['HealthOut']>('/api/health'),
  ingestion: (sourceId: string, vertical: string, limit: number, offset: number) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    if (sourceId) params.set('source_id', sourceId)
    if (vertical) params.set('vertical', vertical)
    return api<IngestionPage>(`/api/ingestion?${params.toString()}`)
  },
}
