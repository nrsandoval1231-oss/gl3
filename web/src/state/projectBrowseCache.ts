import type { OpportunityGroup, OpportunityGroupsPage, ProjectResultsPage } from '../api/client'

export type ProjectBrowseRoute = { search: string; sector: 'all' | 'oil_gas' | 'data_centers'; offset: number }
export type ProjectBrowseCacheEntry = { savedAt: number; page: OpportunityGroupsPage; expanded: Record<string, boolean>; children: Record<string, ProjectResultsPage | null>; childOffsets: Record<string, number>; groupParentTokens: Record<string, string>; openedGroups: Record<string, OpportunityGroup>; scrollY: number }

const CACHE_TTL_MS = 30_000
const browseCache = new Map<string, ProjectBrowseCacheEntry>()
let cacheVersion = 0
function generationIsCurrent(validUntil?: string) {
  if (validUntil === undefined) return true
  const until = Date.parse(validUntil)
  return Number.isFinite(until) && Date.now() < until
}

export const projectBrowseCacheKey = (route: ProjectBrowseRoute) => JSON.stringify([route.search, route.sector, route.offset])
export function projectBrowseCacheVersion() { return cacheVersion }

export function readProjectBrowseCache(route: ProjectBrowseRoute): ProjectBrowseCacheEntry | null {
  const key = projectBrowseCacheKey(route), entry = browseCache.get(key)
  if (!entry) return null
  if (Date.now() - entry.savedAt > CACHE_TTL_MS || !generationIsCurrent(entry.page.valid_until)) {
    browseCache.delete(key)
    return null
  }
  const expiredChildren = Object.entries(entry.children).filter(([, page]) => page && !generationIsCurrent(page.valid_until)).map(([groupId]) => groupId)
  if (!expiredChildren.length) return entry
  const children = { ...entry.children }, expanded = { ...entry.expanded }, childOffsets = { ...entry.childOffsets }, groupParentTokens = { ...entry.groupParentTokens }, openedGroups = { ...entry.openedGroups }
  for (const groupId of expiredChildren) {
    children[groupId] = null; expanded[groupId] = false
    delete childOffsets[groupId]; delete groupParentTokens[groupId]; delete openedGroups[groupId]
  }
  const freshEntry = { ...entry, children, expanded, childOffsets, groupParentTokens, openedGroups }
  browseCache.set(key, freshEntry)
  return freshEntry
}

export function writeProjectBrowseCache(key: string, entry: ProjectBrowseCacheEntry, expectedVersion: number) {
  if (expectedVersion !== cacheVersion) return
  browseCache.delete(key)
  browseCache.set(key, entry)
  while (browseCache.size > 8) browseCache.delete(browseCache.keys().next().value!)
}

export function clearProjectBrowseCache() {
  cacheVersion += 1
  browseCache.clear()
}

export function invalidateProjectBrowseCache(route: ProjectBrowseRoute) {
  browseCache.delete(projectBrowseCacheKey(route))
}
