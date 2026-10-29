// Clear legacy tab-local state on logout and expired sessions.
const PREFIX = 'gl3-continuity:'
export function clearContinuity() {
  try {
    for (const key of Object.keys(sessionStorage)) if (key.startsWith(PREFIX)) sessionStorage.removeItem(key)
  } catch { /* Storage may be disabled. */ }
  window.dispatchEvent(new Event('gl3-clear-continuity'))
}
