import type { components } from './generated'

export type PursuitsResult = components['schemas']['PursuitsOut']
export type Pursuit = components['schemas']['PursuitOut']
export type CallNoteBody = components['schemas']['CallNoteBody']

export type BuyingChainResult = components['schemas']['BuyingChainOut']
export type Opportunity = components['schemas']['OpportunityOut']
export type SourceHealth = components['schemas']['HealthSourceOut']
export type Evidence = components['schemas']['EvidenceOut']
export type IngestionItem = components['schemas']['IngestionItemOut']
export type IngestionPage = components['schemas']['IngestionPageOut']
export type Brief = components['schemas']['BriefOut']
export type BriefRequest = components['schemas']['BriefRequestOut']
export type CommercialTriage = components['schemas']['CommercialTriageOut']
export type CommercialTriageCard = components['schemas']['CommercialTriageCard']
export type CommercialTriageHistory = components['schemas']['CommercialTriageHistoryOut']
export type CommercialTriageHistoryItem = components['schemas']['CommercialTriageHistoryItem']
export type CommercialResearchBody = components['schemas']['CommercialResearchBody']

async function api<T>(path: string, init?: RequestInit, includeSafeDetail = false): Promise<T> {
  const response = await fetch(path, { ...init, credentials: 'same-origin', headers: { 'content-type': 'application/json', ...init?.headers } })
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
  return response.json() as Promise<T>
}

export const client = {
  pursuits: (signal?: AbortSignal, includeDropped = false, offset = 0) => api<PursuitsResult>(`/api/pursuits${includeDropped ? `?include_dropped=true&offset=${offset}` : ''}`, { signal }),
  refreshPursuits: (force = false) => api<components['schemas']['PursuitJobOut']>(`/api/pursuits/refresh${force ? '?force=true' : ''}`, { method: 'POST' }),
  savePursuitNote: (pursuitId: string, body: CallNoteBody) => api<components['schemas']['CallNoteOut']>(`/api/pursuits/${encodeURIComponent(pursuitId)}/notes`, { method: 'POST', body: JSON.stringify(body) }),
  buyingChain: (projectId: string, signal?: AbortSignal) => api<BuyingChainResult>(`/api/projects/${encodeURIComponent(projectId)}/buying-chain`, { signal }),
  enrichBuyingChain: (projectId: string, sourceUrls: string[]) => api<BuyingChainResult>(`/api/projects/${encodeURIComponent(projectId)}/buying-chain/enrich`, { method: 'POST', body: JSON.stringify({ source_urls: sourceUrls }) }),
  brief: (needId: string) => api<Brief>(`/api/power-needs/${encodeURIComponent(needId)}/brief`),
  requestBrief: (needId: string) => api<BriefRequest>(`/api/power-needs/${encodeURIComponent(needId)}/brief`, { method: 'POST', body: '{}' }),
  commercialTriage: (limit = 50, signal?: AbortSignal) => api<CommercialTriage>(`/api/commercial/triage?limit=${limit}`, { signal }),
  commercialTriageHistory: (signal?: AbortSignal) => api<CommercialTriageHistory>('/api/commercial/triage/history', { signal }),
  evaluateCommercialTriage: () => api<CommercialTriage>('/api/commercial/triage/evaluate', { method: 'POST', body: '{}' }),
  researchCommercialNeed: (needId: string, body: CommercialResearchBody) => api<BriefRequest>(`/api/commercial/triage/${encodeURIComponent(needId)}/research`, { method: 'POST', body: JSON.stringify(body) }, true),
  session: () => api<{ authenticated: boolean }>('/api/auth/session'),
  login: (password: string) => api<{ authenticated: boolean }>('/api/auth/login', { method: 'POST', body: JSON.stringify({ password }) }),
  logout: () => api('/api/auth/logout', { method: 'POST' }),
  opportunities: (tier: string, search: string) => api<Opportunity[]>(`/api/opportunities?tier=${encodeURIComponent(tier)}&search=${encodeURIComponent(search)}`),
  changes: () => api<{ kind: string; title: string; url: string; published_at: string | null }[]>('/api/changes'),
  health: () => api<components['schemas']['HealthOut']>('/api/health'),
  ingestion: (sourceId: string, vertical: string, limit: number, offset: number) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    if (sourceId) params.set('source_id', sourceId)
    if (vertical) params.set('vertical', vertical)
    return api<IngestionPage>(`/api/ingestion?${params.toString()}`)
  },
}
