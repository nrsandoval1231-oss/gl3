import type { ReactNode } from 'react'
import { useEffect, useRef, useState } from 'react'
import { client } from '../../api/client'
import { applyPursuit, usePursuitStore } from '../../state/pursuitStore'
import { onPursuitDataEnded } from '../../state/sessionState'
import { inApp, openPursuit, pursuitHref } from './pursuitNav'

/** Add-to-Pursuit control for one opportunity. Mount with `key={needId}` so state never leaks between needs. */
export function AddToPursuit({ needId, children, disabled = false, deferLookup = false }: { needId: string; children?: ReactNode; disabled?: boolean; deferLookup?: boolean }) {
  const store = usePursuitStore()
  const fromStore = store.items.find(item => item.need_id === needId)
  // A truncated list is incomplete, so a missing need still gets the targeted lookup.
  const storeUsable = store.loaded && !store.error && !store.truncated
  const [lookup, setLookup] = useState<{ state: 'idle' | 'loading' | 'done'; id: string | null }>({ state: 'idle', id: null })
  const [created, setCreated] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const inflight = useRef(false)
  // Set synchronously by the ended event so a response resolving before the next commit cannot restore pursuit state; each new request clears it.
  const endedRef = useRef(false)

  // Drop local pursuit state when the session ends; 'done' keeps the button usable (a later add or lookup runs after sign-in).
  useEffect(() => onPursuitDataEnded(() => { endedRef.current = true; setCreated(null); setLookup({ state: 'done', id: null }); setError('') }), [])

  useEffect(() => {
    if (deferLookup || storeUsable || fromStore) return
    endedRef.current = false
    const controller = new AbortController()
    setLookup({ state: 'loading', id: null })
    client.commercialPursuits({ needId, background: true }, controller.signal)
      .then(list => { if (!controller.signal.aborted && !endedRef.current) setLookup({ state: 'done', id: list.items.find(item => item.need_id === needId)?.id ?? null }) })
      .catch(() => { if (!controller.signal.aborted && !endedRef.current) setLookup({ state: 'done', id: null }) })
    return () => controller.abort()
  }, [needId, storeUsable, fromStore?.id, deferLookup])

  const existingId = created ?? fromStore?.id ?? lookup.id
  const checking = !existingId && !storeUsable && lookup.state !== 'done'

  async function add() {
    if (inflight.current || existingId) return
    if (deferLookup && !storeUsable && !fromStore && lookup.state === 'idle') {
      inflight.current = true; endedRef.current = false; setBusy(true); setError('')
      try {
        const list = await client.commercialPursuits({ needId, background: true })
        const existing = list.items.find(item => item.need_id === needId)?.id ?? null
        if (endedRef.current) return
        if (existing) { setLookup({ state: 'done', id: existing }); return }
        setLookup({ state: 'done', id: null })
      } catch (cause) {
        if (endedRef.current) return
        setError(cause instanceof Error && cause.message ? `Could not check Pursuits: ${cause.message}` : 'Could not check Pursuits. Try again.')
        return
      } finally { inflight.current = false; setBusy(false) }
    }
    inflight.current = true; endedRef.current = false; setBusy(true); setError('')
    try {
      const pursuit = await client.createCommercialPursuit(needId)
      if (endedRef.current) return
      setCreated(pursuit.id)
      applyPursuit(pursuit)
    } catch (cause) {
      if (endedRef.current) return
      setError(cause instanceof Error && cause.message ? `Could not add to Pursuits: ${cause.message}` : 'Could not add to Pursuits. Try again.')
    } finally { inflight.current = false; setBusy(false) }
  }

  return <div className="cod-actions" role="group" aria-label="Opportunity actions">
    {existingId
      ? <a className="cod-action-primary is-added" href={pursuitHref(existingId)} onClick={event => inApp(event, () => openPursuit(existingId))}>In Pursuits</a>
      : <button type="button" className="cod-action-primary" disabled={disabled || busy || (checking && !deferLookup)} aria-busy={busy || (checking && !deferLookup)} onClick={() => void add()}>{busy ? 'Adding…' : 'Add to Pursuit'}</button>}
    {children}
    {error && <p className="cod-action-error" role="alert">{error}</p>}
  </div>
}
