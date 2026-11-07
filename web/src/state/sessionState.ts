// Clear legacy tab-local state on logout and expired sessions.
import { clearProjectBrowseCache } from './projectBrowseCache'

const PREFIX = 'gl3-continuity:'
let sessionGeneration = 0
export const currentSessionGeneration = () => sessionGeneration
export function authenticatedSessionStarted() { sessionGeneration += 1 }
export function clearContinuity() {
  sessionGeneration += 1
  clearProjectBrowseCache()
  try {
    for (const key of Object.keys(sessionStorage)) if (key.startsWith(PREFIX)) sessionStorage.removeItem(key)
  } catch { /* Storage may be disabled. */ }
  window.dispatchEvent(new Event('gl3-clear-continuity'))
}

/** Clear private continuity data and tell the authenticated shell to return to sign-in. */
export const AUTH_SESSION_ENDED = 'gl3-auth-session-ended'
export function expireSession(expectedGeneration?: number) {
  if (expectedGeneration !== undefined && expectedGeneration !== sessionGeneration) return false
  clearContinuity()
  window.dispatchEvent(new Event(AUTH_SESSION_ENDED))
  return true
}

/** A background pursuit read found the session ended; clear every private view and return the shell to sign-in. */
export const PURSUITS_SESSION_ENDED = 'gl3-pursuits-session-ended'
export function endPursuitsSession(expectedGeneration?: number) {
  if (expectedGeneration !== undefined && expectedGeneration !== sessionGeneration) return false
  window.dispatchEvent(new Event(PURSUITS_SESSION_ENDED))
  return expireSession(expectedGeneration)
}
/** Subscribe one handler to every event that must remove pursuit-derived data from the screen. Returns the unsubscribe. */
export function onPursuitDataEnded(handler: () => void): () => void {
  addEventListener('gl3-clear-continuity', handler); addEventListener(PURSUITS_SESSION_ENDED, handler)
  return () => { removeEventListener('gl3-clear-continuity', handler); removeEventListener(PURSUITS_SESSION_ENDED, handler) }
}
