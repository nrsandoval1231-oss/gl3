import { clearContinuity } from '../state/sessionState'
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

export type IntelligenceHistoryItem = {
  job_id: string; task_type: string | null; need_id: string; status: string
  result: Record<string, unknown> | null; result_status?: string | null; validation_outcome?: string; validation_reason?: string | null; error: string | null; evidence_ids: string[]
  commercial_assessment_support?: {
    status: 'current' | 'saved' | 'unavailable' | 'stale'
    reason?: string | null
    document_coverage?: string | null
    source_collection_status?: string | null
    selected_facts: { fact_id: string; field?: string | null; value?: string | null; label?: string | null; support_status: 'current' | 'saved' | 'unavailable' | 'stale'; unavailable_reason?: string | null; citation?: { evidence_id: string; evidence_hash: string; source_url: string; excerpt: string; field: string; start: number; end: number } | null }[]
  } | null
  logical_call_id: string | null; usage: { input_tokens?: number | null; output_tokens?: number | null; cost_usd?: string | number | null; estimated_cost_usd?: string | number | null; cost_basis?: string | null } | null
  reserved: boolean; uncertain: boolean; created_at: string | null; completed_at: string | null
}
export type IntelligenceTasks = {
  items: { task_type: string; question_id: string | null; eligible: boolean; reason: string | null; provider: string | null; pinned_model: string | null }[]
  mode: string; enabled: boolean; provider_configuration: { openai_key_present: boolean; typesafe_key_present: boolean }; note: string
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
export type Opportunity = components['schemas']['OpportunityOut']
export type WorkspaceNeed = components['schemas']['PursuitWorkspaceItemOut']
export type WorkspacePage = components['schemas']['PursuitWorkspacePageOut']
export type ProjectResultNeed = { id: string; project_id?: string; name?: string | null; browse_title?: string | null; location?: string | null; activity?: string | null; tier?: 'Signal' | 'Prospect' | 'Lead' | null; commercial_preview?: { disposition?: string | null; reason?: string | null; next_question?: string | null; next_action?: string | null; organization?: string | null } }
export type ProjectResultContactPerson = { record_type?: 'contact_person'; company_identity_id?: string | null; person_identity_id?: string | null; company?: string | null; name?: string | null; title?: string | null; role?: string | null; responsibility?: string | null; purchasing_authority?: string | null; source_url?: string | null }
export type ProjectResult = { id: string; project_id: string; project_ids?: string[]; name: string; company: string | null; location: string | null; sector: 'oil_gas' | 'data_centers' | null; asset_type: string | null; priority_score: number | null; representative_need_id: string | null; needs: ProjectResultNeed[]; need_count: number; event: { kind: string; label: string; date: string | null; source?: string | null; evidence_refs?: unknown[] } | null; contact: { kind: string; label: string; href?: string | null; name?: string | null; title?: string | null; company?: string | null; route_kind?: string | null; responsibility?: string | null; support?: string | null }[]; contact_people?: ProjectResultContactPerson[]; power_summary: string | null; power_summary_kind?: 'supported_gap' | 'activity_requirement' | 'facility_demand' | 'source_context' | 'unknown'; next_action: string | null; updated_at: string | null }
export type ProjectResultsPage = { items: ProjectResult[]; total: number; count_unit: 'projects'; limit: number; offset: number; cohort_token: string; generation: string; results_scope?: 'qualified' | 'discovery' }
export type OpportunityGroup = { id: string; name: string; role: 'operator' | 'customer' | 'unresolved'; operator_number?: string | null; project_count: number; need_count: number; priority_score?: number | null; sectors: string[] }
export type OpportunityGroupsPage = { items: OpportunityGroup[]; total: number; count_unit: 'operators and customers'; limit: number; offset: number; cohort_token: string; generation: string }
export type OpportunityGroupOpen = { group: OpportunityGroup; projects: ProjectResultsPage; parent_cohort_token: string; generation: string }
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

async function api<T>(path: string, init?: RequestInit, includeSafeDetail = false): Promise<T> {
  const response = await fetch(path, { ...init, credentials: 'same-origin', headers: { 'content-type': 'application/json', ...init?.headers } })
  if (response.status === 401) { clearContinuity(); throw new Error('Your session ended. Sign in again.') }
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
  return response.json() as Promise<T>
}

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
  const response = await fetch(`/api/opportunities?${params}`, { credentials: 'same-origin', signal })
  if (response.status === 401) { clearContinuity(); throw new Error('Your session ended. Sign in again.') }
  if (response.status === 409) throw new OpportunityCohortChangedError()
  if (!response.ok) throw new Error(`GridLens could not complete this request (${response.status}).`)
  const items = await response.json() as Opportunity[]
  const header = (name: string) => Number(response.headers.get(name) ?? '0')
  let decisionCounts: OpportunityPage['decisionCounts'] = { SHOW: 0, REVIEW: 0, HOLD: 0 }
  try {
    decisionCounts = { ...decisionCounts, ...JSON.parse(response.headers.get('X-Decision-Counts') ?? '{}') as OpportunityPage['decisionCounts'] }
  } catch { /* Counts stay explicitly empty when an older backend is in front. */ }
  const nextOffset = response.headers.get('X-Next-Offset')
  return {
    items,
    totalCount: header('X-Total-Count'),
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
  const response = await fetch(`/api/opportunities/map-window?${params}`, { credentials: 'same-origin', signal })
  if (response.status === 401) { clearContinuity(); throw new Error('Your session ended. Sign in again.') }
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
  const response = await fetch(`/api/opportunities/needs/${encodeURIComponent(needId)}?${params}`, {
    credentials: 'same-origin',
    signal,
  })
  if (response.status === 401) { clearContinuity(); throw new Error('Your session ended. Sign in again.') }
  if (response.status === 409) throw new OpportunityCohortChangedError()
  if (response.status === 404) throw new OpportunityNeedUnavailableError()
  if (!response.ok) throw new Error(`GridLens could not complete this request (${response.status}).`)
  return response.json() as Promise<Opportunity>
}

export const client = {
  opportunityGroups: async (query: { search?: string; sector?: 'all' | 'oil_gas' | 'data_centers'; limit?: number; offset?: number; cohort_token?: string; sort?: string }, signal?: AbortSignal): Promise<OpportunityGroupsPage> => {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(query)) if (value !== undefined && value !== '') params.set(key, String(value))
    const response = await fetch(`/api/opportunities/groups?${params}`, { credentials: 'same-origin', signal })
    if (response.status === 401) { clearContinuity(); throw new Error('Your session ended. Sign in again.') }
    if (response.status === 409) throw new OpportunityCohortChangedError()
    throwIfBrowsePending(response)
    if (!response.ok) throw new Error(`Could not load operator/customer groups (${response.status}).`)
    return response.json() as Promise<OpportunityGroupsPage>
  },
  groupProjects: async (groupId: string, query: { search?: string; sector?: 'all' | 'oil_gas' | 'data_centers'; limit?: number; offset?: number; cohort_token?: string; parent_cohort_token?: string; sort?: string }, signal?: AbortSignal): Promise<ProjectResultsPage & { group?: Pick<OpportunityGroup, 'id' | 'name' | 'role'> }> => {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(query)) if (value !== undefined && value !== '') params.set(key, String(value))
    const response = await fetch(`/api/opportunities/groups/${encodeURIComponent(groupId)}/projects?${params}`, { credentials: 'same-origin', signal })
    if (response.status === 401) { clearContinuity(); throw new Error('Your session ended. Sign in again.') }
    if (response.status === 409) throw new OpportunityCohortChangedError()
    throwIfBrowsePending(response)
    if (!response.ok) throw new Error(`Could not load projects (${response.status}).`)
    return response.json() as Promise<ProjectResultsPage & { group?: Pick<OpportunityGroup, 'id' | 'name' | 'role'> }>
  },
  openOpportunityGroup: async (groupId: string, query: { search?: string; sector?: 'all' | 'oil_gas' | 'data_centers'; limit?: number; sort?: string }, signal?: AbortSignal): Promise<OpportunityGroupOpen> => {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(query)) if (value !== undefined && value !== '') params.set(key, String(value))
    const response = await fetch(`/api/opportunities/groups/${encodeURIComponent(groupId)}/open?${params}`, { credentials: 'same-origin', signal })
    if (response.status === 401) { clearContinuity(); throw new Error('Your session ended. Sign in again.') }
    if (response.status === 404) throw new OpportunityGroupUnavailableError()
    throwIfBrowsePending(response)
    if (!response.ok) throw new Error(`Could not open current operator/customer results (${response.status}).`)
    return response.json() as Promise<OpportunityGroupOpen>
  },
  projectResults: async (query: { search?: string; sector?: 'all' | 'oil_gas' | 'data_centers'; limit?: number; offset?: number; cohort_token?: string; sort?: string; need_id?: string }, signal?: AbortSignal): Promise<ProjectResultsPage> => {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(query)) if (value !== undefined && value !== '') params.set(key, String(value))
    const response = await fetch(`/api/opportunities/projects?${params}`, { credentials: 'same-origin', signal })
    if (response.status === 401) { clearContinuity(); throw new Error('Your session ended. Sign in again.') }
    if (response.status === 409) throw new OpportunityCohortChangedError()
    if (!response.ok) throw new Error(`Could not load projects (${response.status}).`)
    return response.json() as Promise<ProjectResultsPage>
  },
  search: (query: string, signal?: AbortSignal) => api<GlobalSearchResult>(`/api/search?${new URLSearchParams({ q: query, limit: '20' })}`, { signal }),
  workspace: async (filters: WorkspaceFilters = {}, signal?: AbortSignal): Promise<WorkspacePage> => {
    const params = new URLSearchParams({ limit: '25' })
    params.set('group_by', 'account')
    for (const [key, value] of Object.entries(filters)) if (value !== undefined && value !== '') params.set(key, String(value))
    const response = await fetch(`/api/opportunities/workspace?${params}`, { credentials: 'same-origin', signal })
    if (response.status === 401) { clearContinuity(); throw new Error('Your session ended. Sign in again.') }
    if (response.status === 409) throw new OpportunityCohortChangedError()
    if (!response.ok) throw new Error(response.status === 503 ? 'The workspace cohort is unavailable. Retry to reload current opportunities.' : `GridLens could not complete this request (${response.status}).`)
    return response.json() as Promise<WorkspacePage>
  },
  companyContacts: async (companyIdentityId: string, signal?: AbortSignal): Promise<components['schemas']['CompanyContacts']> => {
    const response = await fetch(`/api/customer-accounts/${encodeURIComponent(companyIdentityId)}/contacts`, { credentials: 'same-origin', signal })
    if (response.status === 401) { clearContinuity(); throw new Error('Your session ended. Sign in again.') }
    if (!response.ok) throw new Error(`Could not load contacts (${response.status}).`)
    return response.json()
  },
  companyGraph: async (companyIdentityId: string, signal?: AbortSignal): Promise<CompanyGraph> => {
    const response = await fetch(`/api/companies/${encodeURIComponent(companyIdentityId)}/graph`, { credentials: 'same-origin', signal })
    if (response.status === 401) { clearContinuity(); throw new Error('Your session ended. Sign in again.') }
    if (!response.ok) throw new Error(`Could not load company intelligence (${response.status}).`)
    return response.json() as Promise<CompanyGraph>
  },
  customerAccountProjects: async (companyIdentityId: string, offset = 0, needOffset = 0, signal?: AbortSignal): Promise<CustomerProjectsPage> => {
    const params = new URLSearchParams({ limit: '25', offset: String(offset), need_limit: '25', need_offset: String(needOffset) })
    const response = await fetch(`/api/customer-accounts/${encodeURIComponent(companyIdentityId)}/projects?${params}`, { credentials: 'same-origin', signal })
    if (response.status === 401) { clearContinuity(); throw new Error('Your session ended. Sign in again.') }
    if (!response.ok) throw new Error(`GridLens could not load this account's projects (${response.status}).`)
    return response.json() as Promise<CustomerProjectsPage>
  },
  unresolvedCustomerProjects: async (search = '', offset = 0, signal?: AbortSignal): Promise<UnresolvedCustomerProjectsPage> => {
    const params = new URLSearchParams({ limit: '25', offset: String(offset) })
    if (search) params.set('search', search)
    const response = await fetch(`/api/customer-accounts/unresolved?${params}`, { credentials: 'same-origin', signal })
    if (response.status === 401) { clearContinuity(); throw new Error('Your session ended. Sign in again.') }
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
  intelligenceTasks: (signal?: AbortSignal) => api<IntelligenceTasks>('/api/intelligence/tasks', { signal }),
  intelligenceOperations: (signal?: AbortSignal) => api<IntelligenceOperations>('/api/intelligence/operations', { signal }),
  intelligenceHistory: (needId: string, signal?: AbortSignal, taskType?: string) => {
    const params = new URLSearchParams({ limit: '20' })
    if (taskType) params.set('task_type', taskType)
    return api<{ items: IntelligenceHistoryItem[] }>(`/api/intelligence/needs/${encodeURIComponent(needId)}/history?${params}`, { signal })
  },
  evidenceContent: (evidenceId: string, offset = 0, limit = 4096, signal?: AbortSignal) => {
    const params = new URLSearchParams({ offset: String(offset), limit: String(limit) })
    return api<EvidenceContent>(`/api/evidence/${encodeURIComponent(evidenceId)}/content?${params}`, { signal }, true)
  },
  session: () => api<{ authenticated: boolean }>('/api/auth/session').then((session) => {
    if (!session.authenticated) clearContinuity()
    return session
  }),
  login: (password: string) => api<{ authenticated: boolean }>('/api/auth/login', { method: 'POST', body: JSON.stringify({ password }) }),
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
