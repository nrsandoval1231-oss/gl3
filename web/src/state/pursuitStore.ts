import { useSyncExternalStore } from 'react'
import { client, type CommercialPursuit, type CommercialPursuitList } from '../api/client'

type State = { items: CommercialPursuit[]; counts: CommercialPursuitList['counts']; loaded: boolean; error: string; truncated: boolean }
let state: State = { items: [], counts: { total: 0, active: 0, needs_attention: 0 }, loaded: false, error: '', truncated: false }
const listeners = new Set<() => void>()
let inflight: Promise<void> | null = null
let generation = 0
const EMPTY_COUNTS = { total: 0, active: 0, needs_attention: 0 }
const emit = () => listeners.forEach(listener => listener())
const set = (next: Partial<State>) => { state = { ...state, ...next }; emit() }

const PAGE_SIZE = 200
export const MAX_PURSUIT_PAGES = 10 // hard cap: 2000 items
/** Follow `next_offset` until the list is complete or the cap is hit; a capped list is flagged `truncated`, never presented as complete. */
const fetchList = () => {
  const started = generation
  const load = async () => {
    const items: CommercialPursuit[] = []
    let counts = EMPTY_COUNTS, offset = 0, truncated = false
    for (let page = 1; ; page += 1) {
      const list = await client.commercialPursuits({ background: true, limit: PAGE_SIZE, offset })
      if (started !== generation) return
      items.push(...list.items); counts = list.counts
      const next = list.has_more ? list.next_offset ?? null : null
      if (next === null || next <= offset) break
      if (page >= MAX_PURSUIT_PAGES) { truncated = true; break }
      offset = next
    }
    set({ items, counts, loaded: true, error: '', truncated })
  }
  return load()
    .catch(cause => {
      if (started !== generation) return
      const message = cause instanceof Error ? cause.message : 'Pursuits are unavailable.'
      // An ended session must not leave stale items or counts on screen.
      if (message.startsWith('Your session ended')) set({ items: [], counts: EMPTY_COUNTS, loaded: true, error: message, truncated: false })
      else set({ loaded: true, error: message })
    })
    .finally(() => { if (started === generation) inflight = null })
}
/** Load the list. `force` queues a second read when one is already in flight so a write is never masked by a stale response. */
export function refreshPursuits(force = false): Promise<void> {
  if (inflight && force) return inflight.then(() => refreshPursuits())
  inflight ??= fetchList()
  return inflight
}
/** Replace one pursuit from a write response without waiting for a full refresh. */
export function applyPursuit(updated: CommercialPursuit) {
  const exists = state.items.some(item => item.id === updated.id)
  // Only adjust counts against a loaded list; otherwise the follow-up refresh supplies them.
  const usable = state.loaded && !state.error
  const counts = exists || !usable ? state.counts : { ...state.counts, total: state.counts.total + 1, active: state.counts.active + (updated.stage === 'Won' || updated.stage === 'Lost' ? 0 : 1) }
  set({ items: exists ? state.items.map(item => item.id === updated.id ? { ...item, ...updated } : item) : usable ? [updated, ...state.items] : state.items, counts })
  void refreshPursuits(true)
}
export function clearPursuits() { generation += 1; inflight = null; state = { items: [], counts: EMPTY_COUNTS, loaded: false, error: '', truncated: false }; emit() }
if (typeof window !== 'undefined') window.addEventListener('gl3-clear-continuity', clearPursuits)

export function usePursuitStore(): State {
  return useSyncExternalStore(listener => { listeners.add(listener); return () => { listeners.delete(listener) } }, () => state)
}
