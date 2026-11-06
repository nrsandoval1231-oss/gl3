// Clear legacy tab-local state on logout and expired sessions.
import { clearProjectBrowseCache } from './projectBrowseCache'

const PREFIX = 'gl3-continuity:'
export function clearContinuity() {
  clearProjectBrowseCache()
  try {
    for (const key of Object.keys(sessionStorage)) if (key.startsWith(PREFIX)) sessionStorage.removeItem(key)
  } catch { /* Storage may be disabled. */ }
  window.dispatchEvent(new Event('gl3-clear-continuity'))
}

/** A background pursuit read found the session ended. Narrower than `clearContinuity`: it never touches opportunity caches. */
export const PURSUITS_SESSION_ENDED = 'gl3-pursuits-session-ended'
export function endPursuitsSession() { window.dispatchEvent(new Event(PURSUITS_SESSION_ENDED)) }
/** Subscribe one handler to every event that must remove pursuit-derived data from the screen. Returns the unsubscribe. */
export function onPursuitDataEnded(handler: () => void): () => void {
  addEventListener('gl3-clear-continuity', handler); addEventListener(PURSUITS_SESSION_ENDED, handler)
  return () => { removeEventListener('gl3-clear-continuity', handler); removeEventListener(PURSUITS_SESSION_ENDED, handler) }
}
