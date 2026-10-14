import { useSyncExternalStore } from 'react'
import type { BriefRequest, CallNoteBody, CommercialTriageCard } from '../../api/client'
import { readSession, removeSession, writeSession } from '../../state/sessionState'

type ResearchProgress = { question: string; brief: BriefRequest; message: string; failed: boolean }
export type CommercialDraft = { question: string; note: string; outcome: CallNoteBody['outcome']; nextAction: string; clientId?: string; research?: ResearchProgress; savingNote?: boolean; researchSubmitting?: boolean; researchInterrupted?: boolean; noteMessage?: string; refreshSafe?: boolean }
type Entry = { key: string; draft: CommercialDraft }
const records = new Map<string, Entry>()
const listeners = new Set<() => void>()
let epoch = 0
window.addEventListener('gl3-clear-continuity', () => { epoch += 1; records.clear(); listeners.forEach((fn) => fn()) })
function restore(key: string): Entry | undefined {
  const saved = readSession<CommercialDraft>(`commercial:${key}`)
  return saved ? { key, draft: { ...saved, savingNote: false, researchSubmitting: false, researchInterrupted: saved.researchSubmitting || saved.researchInterrupted, noteMessage: saved.savingNote ? 'Save interrupted by refresh. Retry with the same key to confirm the original note.' : saved.noteMessage } } : undefined
}
function entryFor(item: CommercialTriageCard): Entry {
  const key = `${item.id}:${item.pursuit_id ?? 'unlinked'}`
  let entry = records.get(key) ?? restore(key)
  if (!entry && item.pursuit_id) {
    const unlinked = `${item.id}:unlinked`
    entry = records.get(unlinked) ?? restore(unlinked)
    if (entry) {
      // Only the first link consumes an unlinked draft. Linked pursuits never
      // borrow one another's drafts. Keep the entry object so a pending research
      // response updates the new key rather than resurrecting the unlinked key.
      records.delete(unlinked)
      removeSession(`commercial:${unlinked}`)
      entry.key = key
      entry.draft = { ...entry.draft, refreshSafe: writeSession(`commercial:${key}`, entry.draft) }
    }
  }
  entry ??= { key, draft: { question: item.next_question, note: '', outcome: 'Not reached', nextAction: '', refreshSafe: true } }
  records.set(key, entry)
  return entry
}
export function useCommercialDraft(item: CommercialTriageCard) {
  const entry = entryFor(item)
  const draft = useSyncExternalStore((fn) => { listeners.add(fn); return () => listeners.delete(fn) }, () => records.get(entry.key)?.draft ?? entryFor(item).draft)
  const generation = epoch
  const update = (patch: Partial<CommercialDraft>) => {
    if (generation !== epoch) return
    const next = { ...entry.draft, ...patch }
    next.refreshSafe = writeSession(`commercial:${entry.key}`, next)
    entry.draft = next
    listeners.forEach((fn) => fn())
  }
  return [draft, update] as const
}
