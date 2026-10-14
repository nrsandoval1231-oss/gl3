import { useSyncExternalStore } from 'react'
import type { BriefRequest, CallNoteBody, CommercialTriageCard } from '../../api/client'
import { readSession, writeSession } from '../../state/sessionState'

type ResearchProgress = { question: string; brief: BriefRequest; message: string; failed: boolean }
export type CommercialDraft = { question: string; note: string; outcome: CallNoteBody['outcome']; nextAction: string; clientId?: string; research?: ResearchProgress; savingNote?: boolean; researchSubmitting?: boolean; researchInterrupted?: boolean; noteMessage?: string; refreshSafe?: boolean }
const records = new Map<string, CommercialDraft>()
const listeners = new Set<() => void>()
let epoch = 0
window.addEventListener('gl3-clear-continuity', () => { epoch += 1; records.clear(); listeners.forEach((fn) => fn()) })
export function useCommercialDraft(item: CommercialTriageCard) {
  // A saved pursuit and a need are distinct identities. Never transfer a note
  // to a different pursuit merely because its representative need is the same.
  const id = `${item.id}:${item.pursuit_id ?? 'unlinked'}`
  const get = () => {
    if (!records.has(id)) {
      const saved = readSession<CommercialDraft>(`commercial:${id}`)
      records.set(id, saved ? { ...saved, savingNote: false, researchSubmitting: false, researchInterrupted: saved.researchSubmitting || saved.researchInterrupted, noteMessage: saved.savingNote ? 'Save interrupted by refresh. Retry with the same key to confirm the original note.' : saved.noteMessage } : { question: item.next_question, note: '', outcome: 'Not reached', nextAction: '', refreshSafe: true })
    }
    return records.get(id)!
  }
  const draft = useSyncExternalStore((fn) => { listeners.add(fn); return () => listeners.delete(fn) }, get)
  const generation = epoch
  const update = (patch: Partial<CommercialDraft>) => {
    if (generation !== epoch) return
    const next = { ...get(), ...patch }
    next.refreshSafe = writeSession(`commercial:${id}`, next)
    records.set(id, next)
    listeners.forEach((fn) => fn())
  }
  return [draft, update] as const
}
