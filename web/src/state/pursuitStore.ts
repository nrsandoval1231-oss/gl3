import { useSyncExternalStore } from 'react'
import { client, type CommercialPursuit, type CommercialPursuitList } from '../api/client'

type State = { items: CommercialPursuit[]; counts: CommercialPursuitList['counts']; loaded: boolean; error: string }
let state: State = { items: [], counts: { total: 0, active: 0, needs_attention: 0 }, loaded: false, error: '' }
const listeners = new Set<() => void>()
let inflight: Promise<void> | null = null
const emit = () => listeners.forEach(listener => listener())
const set = (next: Partial<State>) => { state = { ...state, ...next }; emit() }

export function refreshPursuits(): Promise<void> {
  inflight ??= client.commercialPursuits().then(list => set({ items: list.items, counts: list.counts, loaded: true, error: '' }))
    .catch(cause => set({ loaded: true, error: cause instanceof Error ? cause.message : 'Pursuits are unavailable.' }))
    .finally(() => { inflight = null })
  return inflight
}
/** Replace one pursuit from a write response without waiting for a full refresh. */
export function applyPursuit(updated: CommercialPursuit) {
  const exists = state.items.some(item => item.id === updated.id)
  set({ items: exists ? state.items.map(item => item.id === updated.id ? { ...item, ...updated } : item) : [updated, ...state.items] })
  void refreshPursuits()
}
export function clearPursuits() { state = { items: [], counts: { total: 0, active: 0, needs_attention: 0 }, loaded: false, error: '' }; emit() }
if (typeof window !== 'undefined') window.addEventListener('gl3-clear-continuity', clearPursuits)

export function usePursuitStore(): State {
  return useSyncExternalStore(listener => { listeners.add(listener); return () => { listeners.delete(listener) } }, () => state)
}
