import { useSyncExternalStore } from 'react'
import type { CallFact } from '../../api/client'
import { readSession, writeSession } from '../../state/sessionState'

type Contact = { name: string; organization: string; role: string; channel: string; at: string }
type CallDraft = {
  contact: Contact; values: Record<string, string>; drafts: CallFact[]
  accepted: boolean; busy: boolean; error: string; keys: Record<string, string>; refreshSafe: boolean
}
const drafts = new Map<string, CallDraft>()
let generation = 0
const listeners = new Set<() => void>()
window.addEventListener('gl3-clear-continuity', () => { generation += 1; drafts.clear(); listeners.forEach((fn) => fn()) })
export function freshCallDraft(): CallDraft {
  const now = new Date()
  now.setSeconds(0, 0)
  return {
    contact: { name: '', organization: '', role: '', channel: 'phone', at: new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16) },
    values: {}, drafts: [], accepted: false, busy: false, error: '', keys: {}, refreshSafe: true,
  }
}
function getDraft(id: string): CallDraft {
  let draft = drafts.get(id)
  if (!draft) {
    const stored = readSession<CallDraft>(`call:${id}`)
    draft = stored ? { ...stored, busy: false, error: stored.busy ? 'The request was interrupted by refresh. Retry with the same request keys; review fact history before accepting.' : stored.error } : freshCallDraft()
    drafts.set(id, draft)
  }
  return draft
}
export function useCallDraft(id: string) {
  const draft = useSyncExternalStore((fn) => { listeners.add(fn); return () => listeners.delete(fn) }, () => getDraft(id))
  const epoch = generation
  const update = (patch: Partial<CallDraft>) => {
    // Do not resurrect private state when a late request completes after logout.
    if (epoch !== generation || !drafts.has(id)) return
    const next = { ...getDraft(id), ...patch }
    next.refreshSafe = writeSession(`call:${id}`, next)
    drafts.set(id, next)
    listeners.forEach((fn) => fn())
  }
  return [draft, update] as const
}
