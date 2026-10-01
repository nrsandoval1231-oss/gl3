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

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, credentials: 'same-origin', headers: { 'content-type': 'application/json', ...init?.headers } })
  if (response.status === 401) throw new Error('Your session ended. Sign in again.')
  if (!response.ok) throw new Error(`GridLens could not complete this request (${response.status}).`)
  return response.json() as Promise<T>
}

export const client = {
  pursuits: (signal?: AbortSignal, includeDropped = false, offset = 0) => api<PursuitsResult>(`/api/pursuits${includeDropped ? `?include_dropped=true&offset=${offset}` : ''}`, { signal }),
  refreshPursuits: (force = false) => api<components['schemas']['PursuitJobOut']>(`/api/pursuits/refresh${force ? '?force=true' : ''}`, { method: 'POST' }),
  savePursuitNote: (pursuitId: string, body: CallNoteBody) => api<components['schemas']['CallNoteOut']>(`/api/pursuits/${encodeURIComponent(pursuitId)}/notes`, { method: 'POST', body: JSON.stringify(body) }),
  buyingChain: (projectId: string, signal?: AbortSignal) => api<BuyingChainResult>(`/api/projects/${encodeURIComponent(projectId)}/buying-chain`, { signal }),
  enrichBuyingChain: (projectId: string, sourceUrls: string[]) => api<BuyingChainResult>(`/api/projects/${encodeURIComponent(projectId)}/buying-chain/enrich`, { method: 'POST', body: JSON.stringify({ source_urls: sourceUrls }) }),
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
