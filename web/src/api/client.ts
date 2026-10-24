import { clearContinuity } from '../state/sessionState'
import type { components } from './generated'

export type PursuitsResult = components['schemas']['PursuitsOut']
export type Pursuit = components['schemas']['PursuitOut']
export type CallNoteBody = components['schemas']['CallNoteBody']
export const workflowStatuses = ['New', 'Investigating', 'Contacted', 'Qualified', 'Won', 'Lost', 'Closed'] as const
export type WorkflowStatus = typeof workflowStatuses[number]
export type WorkflowStatusFilter = Uppercase<WorkflowStatus> | 'UNKNOWN' | ''
export type CallFact = components['schemas']['CallFactOut']
export type CallFactPage = components['schemas']['CallFactPageOut']
export type EvidenceContent = {
  evidence_id: string
  content_hash: string
  source_url: string
  offset: number
  total_chars: number
  content: string
  next_offset: number | null
}
export type TimingCorrectionTarget = components['schemas']['TimingCorrectionTargetOut']
export type CallFactDraftBody = components['schemas']['CallFactDraftBody']
export type CallFactDecisionBody = components['schemas']['CallFactDecisionBody']
export type NeedWorkflowStatus = components['schemas']['NeedWorkflowStatusOut']
export type NeedWorkflowStatusBody = components['schemas']['NeedWorkflowStatusBody']

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
export type OwnerFeedbackBody = { client_id: string; job_id: string; logical_call_id: string; decision: 'SUPPORTED' | 'CONFLICT' | 'UNRESOLVED' | 'OTHER'; note: string; next_action?: string; follow_up?: string | null; candidate: { field: string; value: string; unit?: string | null; original_value?: string | null; original_unit?: string | null; precision?: number | null; date_precision?: string | null; speaker?: string | null; speaker_organization?: string | null; speaker_role?: string | null; evidence_id: string; evidence_hash: string; quote: string; section: string; page?: number | null; span_start: number; span_end: number; publisher: string; published_date?: string | null; support: string; status: string; source_url: string; source_id?: string | null }; evidence_refs: { evidence_id: string; content_hash: string; source_url: string }[] }

export type BuyingChainResult = components['schemas']['BuyingChainOut']
export type BuyingChainCorrectionBody = components['schemas']['BuyingChainCorrectionBody']
export type BuyingChainCorrection = components['schemas']['BuyingChainCorrectionOut']
export type Opportunity = components['schemas']['OpportunityOut']
export type WorkspaceNeed = components['schemas']['PursuitWorkspaceItemOut']
export type WorkspacePage = components['schemas']['PursuitWorkspacePageOut']
export type CustomerAccount = components['schemas']['CustomerAccountOut']
export type CustomerProjectsPage = components['schemas']['CustomerProjectsPageOut']
export type UnresolvedCustomerProjectsPage = components['schemas']['UnresolvedCustomerProjectsPageOut']
export type WorkspaceChanges = components['schemas']['WorkspaceChangesOut']
export type WorkspaceChangeNeed = components['schemas']['WorkspaceChangeNeedOut']
export type WorkspaceChangesReviewBody = components['schemas']['WorkspaceChangesReviewBody']
export type WorkspaceChangesReviewReceipt = components['schemas']['WorkspaceChangesReviewReceiptOut']
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
  status?: WorkflowStatusFilter
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
export type Brief = components['schemas']['BriefOut']
export type BriefRequest = components['schemas']['BriefRequestOut']
export type PowerNeedTitle = { status: 'disabled' | 'unavailable' | 'pending' | 'ready' | 'stale' | 'failed'; result: { title: string; organization: string | null; role: string | null; activity: string | null } | null; citations: { evidence_id: string; title: string; url: string; publisher: string; quote: string; role?: string | null }[]; generated_at: string | null; model: string | null; error?: string | null; job_id?: string | null }
export type CommercialTriage = components['schemas']['CommercialTriagePageOut']
export type CommercialTriageCard = components['schemas']['CommercialTriageCard']
export type CommercialTriageHistory = components['schemas']['CommercialTriageHistoryPageOut']
export type CommercialTriageHistoryItem = components['schemas']['CommercialTriageHistoryItem']
export type CommercialResearchBody = components['schemas']['CommercialResearchBody']
export type AutonomousResearch = components['schemas']['AutonomousResearchOut']
export type ResearchOverview = components['schemas']['ResearchOverviewOut']
export type ResearchRoute = components['schemas']['ResearchRouteOut']
export type ResearchQuestion = components['schemas']['ResearchQuestionOut']
export type CommercialResearchStatus = components['schemas']['CommercialResearchStatusOut']

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
    ['mw_max', filters.mwMax], ['priority_segment', filters.prioritySegment], ['status', filters.status],
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
  reviewWorkspaceChanges: (body: WorkspaceChangesReviewBody) => api<WorkspaceChangesReviewReceipt>(
    '/api/opportunities/workspace/changes/review', { method: 'POST', body: JSON.stringify(body) }, true,
  ),
  workspaceHistoricalNeed: (needId: string, signal?: AbortSignal) => api<WorkspaceHistoricalNeed>(
    `/api/opportunities/needs/${encodeURIComponent(needId)}/history`, { signal },
  ),
  pursuits: (signal?: AbortSignal, includeDropped = false, offset = 0) => api<PursuitsResult>(`/api/pursuits${includeDropped ? `?include_dropped=true&offset=${offset}` : ''}`, { signal }),
  refreshPursuits: (force = false) => api<components['schemas']['PursuitJobOut']>(`/api/pursuits/refresh${force ? '?force=true' : ''}`, { method: 'POST' }),
  savePursuitNote: (pursuitId: string, body: CallNoteBody) => api<components['schemas']['CallNoteOut']>(`/api/pursuits/${encodeURIComponent(pursuitId)}/notes`, { method: 'POST', body: JSON.stringify(body) }),
  buyingChain: (projectId: string, signal?: AbortSignal, history = false) => api<BuyingChainResult>(`/api/projects/${encodeURIComponent(projectId)}/buying-chain${history ? '?history=true' : ''}`, { signal }),
  correctBuyingChain: (projectId: string, claimId: string, body: BuyingChainCorrectionBody) => api<BuyingChainCorrection>(`/api/projects/${encodeURIComponent(projectId)}/buying-chain/${encodeURIComponent(claimId)}/corrections`, { method: 'POST', body: JSON.stringify(body) }, true),
  enrichBuyingChain: (projectId: string, sourceUrls: string[], signal?: AbortSignal) => api<BuyingChainResult>(`/api/projects/${encodeURIComponent(projectId)}/buying-chain/enrich`, { method: 'POST', body: JSON.stringify({ source_urls: sourceUrls }), signal }),
  brief: (needId: string) => api<Brief>(`/api/power-needs/${encodeURIComponent(needId)}/brief`),
  requestBrief: (needId: string) => api<BriefRequest>(`/api/power-needs/${encodeURIComponent(needId)}/brief`, { method: 'POST', body: '{}' }),
  powerNeedTitle: (needId: string, signal?: AbortSignal) => api<PowerNeedTitle>(`/api/power-needs/${encodeURIComponent(needId)}/title`, { signal }),
  requestPowerNeedTitle: (needId: string, signal?: AbortSignal) => api<PowerNeedTitle>(`/api/power-needs/${encodeURIComponent(needId)}/title`, { method: 'POST', body: '{}', signal }),
  commercialTriage: (limit = 50, signal?: AbortSignal, offset = 0) => api<CommercialTriage>(`/api/commercial/triage?limit=${limit}${offset ? `&offset=${offset}` : ''}`, { signal }),
  commercialTriageHistory: (signal?: AbortSignal, offset = 0, limit = 50) => api<CommercialTriageHistory>(`/api/commercial/triage/history${offset || limit !== 50 ? `?limit=${limit}&offset=${offset}` : ''}`, { signal }),
  commercialTriageHistoryDetail: (pursuitId: string, signal?: AbortSignal) => api<CommercialTriageHistoryItem>(`/api/commercial/triage/history/${encodeURIComponent(pursuitId)}`, { signal }),
  evaluateCommercialTriage: (limit = 50, offset = 0) => api<CommercialTriage>(`/api/commercial/triage/evaluate${limit === 50 && offset === 0 ? '' : `?limit=${limit}&offset=${offset}`}`, { method: 'POST', body: '{}' }),
  researchCommercialNeed: (needId: string, body: CommercialResearchBody) => api<BriefRequest>(`/api/commercial/triage/${encodeURIComponent(needId)}/research`, { method: 'POST', body: JSON.stringify(body) }, true),
  commercialResearchStatus: (needId: string, question: string, signal?: AbortSignal) => api<CommercialResearchStatus>(`/api/commercial/triage/${encodeURIComponent(needId)}/research?${new URLSearchParams({ question }).toString()}`, { signal }, true),
  autonomousResearch: (needId: string, signal?: AbortSignal) => api<AutonomousResearch>(`/api/commercial/triage/${encodeURIComponent(needId)}/autonomous-research`, { signal }, true),
  intelligenceTasks: (signal?: AbortSignal) => api<IntelligenceTasks>('/api/intelligence/tasks', { signal }),
  intelligenceOperations: (signal?: AbortSignal) => api<IntelligenceOperations>('/api/intelligence/operations', { signal }),
  intelligenceHistory: (needId: string, signal?: AbortSignal, taskType?: string) => {
    const params = new URLSearchParams({ limit: '20' })
    if (taskType) params.set('task_type', taskType)
    return api<{ items: IntelligenceHistoryItem[] }>(`/api/intelligence/needs/${encodeURIComponent(needId)}/history?${params}`, { signal })
  },
  requestIntelligence: (needId: string, taskType: string, questionId?: string) => api<IntelligenceHistoryItem>(`/api/intelligence/needs/${encodeURIComponent(needId)}/jobs`, { method: 'POST', body: JSON.stringify({ task_type: taskType, ...(questionId ? { question_id: questionId } : {}) }) }),
  saveIntelligenceFeedback: (needId: string, body: OwnerFeedbackBody) => api<{ id: string; metadata: Record<string, unknown>; note: string }>(`/api/intelligence/needs/${encodeURIComponent(needId)}/feedback`, { method: 'POST', body: JSON.stringify(body) }),
  evidenceContent: (evidenceId: string, offset = 0, limit = 4096, signal?: AbortSignal) => {
    const params = new URLSearchParams({ offset: String(offset), limit: String(limit) })
    return api<EvidenceContent>(`/api/evidence/${encodeURIComponent(evidenceId)}/content?${params}`, { signal }, true)
  },
  refreshAutonomousResearch: (needId: string, force: boolean, signal?: AbortSignal, completeIntelligence = false) => api<AutonomousResearch>(`/api/commercial/triage/${encodeURIComponent(needId)}/autonomous-research`, { method: 'POST', body: JSON.stringify({ force, ...(completeIntelligence ? { complete_intelligence: true } : {}) }), signal }, true),
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
  callFacts: (needId: string, limit = 50, offset = 0, signal?: AbortSignal) => api<CallFactPage>(
    `/api/needs/${encodeURIComponent(needId)}/facts?limit=${limit}&offset=${offset}`, { signal }, true,
  ),
  createCallFact: (needId: string, body: CallFactDraftBody) => api<CallFact>(
    `/api/needs/${encodeURIComponent(needId)}/facts`, { method: 'POST', body: JSON.stringify(body) }, true,
  ),
  decideCallFact: (needId: string, factVersionId: string, body: CallFactDecisionBody) => api<components['schemas']['CallFactDecisionOut']>(
    `/api/needs/${encodeURIComponent(needId)}/facts/${encodeURIComponent(factVersionId)}/decision`,
    { method: 'POST', body: JSON.stringify(body) }, true,
  ),
  workflowStatus: (needId: string, signal?: AbortSignal) => api<NeedWorkflowStatus>(
    `/api/needs/${encodeURIComponent(needId)}/workflow-status`, { signal }, true,
  ),
  setWorkflowStatus: (needId: string, body: NeedWorkflowStatusBody) => api<components['schemas']['NeedWorkflowEventOut']>(
    `/api/needs/${encodeURIComponent(needId)}/workflow-status`, { method: 'POST', body: JSON.stringify(body) }, true,
  ),
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
