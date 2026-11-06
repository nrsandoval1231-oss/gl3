import type { ReactNode } from 'react'
import { useEffect, useRef, useState } from 'react'
import { client } from '../../api/client'
import { applyPursuit, usePursuitStore } from '../../state/pursuitStore'
import { inApp, openPursuit, pursuitHref } from './pursuitNav'

/** Add-to-Pursuit control for one opportunity. Mount with `key={needId}` so state never leaks between needs. */
export function AddToPursuit({ needId, children }: { needId: string; children?: ReactNode }) {
  const store = usePursuitStore()
  const fromStore = store.items.find(item => item.need_id === needId)
  const storeUsable = store.loaded && !store.error
  const [lookup, setLookup] = useState<{ state: 'idle' | 'loading' | 'done'; id: string | null }>({ state: 'idle', id: null })
  const [created, setCreated] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const inflight = useRef(false)

  useEffect(() => {
    if (storeUsable || fromStore) return
    const controller = new AbortController()
    setLookup({ state: 'loading', id: null })
    client.commercialPursuits({ needId, background: true }, controller.signal)
      .then(list => { if (!controller.signal.aborted) setLookup({ state: 'done', id: list.items.find(item => item.need_id === needId)?.id ?? null }) })
      .catch(() => { if (!controller.signal.aborted) setLookup({ state: 'done', id: null }) })
    return () => controller.abort()
  }, [needId, storeUsable, fromStore?.id])

  const existingId = created ?? fromStore?.id ?? lookup.id
  const checking = !existingId && !storeUsable && lookup.state !== 'done'

  async function add() {
    if (inflight.current || existingId) return
    inflight.current = true; setBusy(true); setError('')
    try {
      const pursuit = await client.createCommercialPursuit(needId)
      setCreated(pursuit.id)
      applyPursuit(pursuit)
    } catch (cause) {
      setError(cause instanceof Error && cause.message ? `Could not add to Pursuits: ${cause.message}` : 'Could not add to Pursuits. Try again.')
    } finally { inflight.current = false; setBusy(false) }
  }

  return <div className="cod-actions" role="group" aria-label="Opportunity actions">
    {existingId
      ? <a className="cod-action-primary is-added" href={pursuitHref(existingId)} onClick={event => inApp(event, () => openPursuit(existingId))}>In Pursuits</a>
      : <button type="button" className="cod-action-primary" disabled={busy || checking} aria-busy={busy || checking} onClick={() => void add()}>{busy ? 'Adding…' : 'Add to Pursuit'}</button>}
    {children}
    {error && <p className="cod-action-error" role="alert">{error}</p>}
  </div>
}
