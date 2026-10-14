// Tab-local continuity only: eight-hour expiry, bounded count and total bytes.
// Storage denial falls back to memory; no server facts are changed by this module.
const PREFIX = 'gl3-continuity:'
const TTL = 8 * 60 * 60 * 1000
const MAX_BYTES = 2_000_000
export function readSession<T>(key: string): T | undefined {
  try {
    const value = JSON.parse(sessionStorage.getItem(PREFIX + key) ?? 'null')
    if (value && Date.now() - value.at < TTL) return value.data as T
    sessionStorage.removeItem(PREFIX + key)
  } catch { /* Storage is optional. */ }
}
export function writeSession(key: string, data: unknown) {
  try {
    // A rejected replacement must not make an older draft look current on refresh.
    sessionStorage.removeItem(PREFIX + key)
    const value = JSON.stringify({ at: Date.now(), data })
    if (value.length > MAX_BYTES) return false
    // Expire old entries first. Navigation may evict navigation snapshots, never
    // call input. If drafts fill the budget, reject the new write visibly.
    const entries = Object.keys(sessionStorage).filter((name) => name.startsWith(PREFIX))
      .map((name) => ({ name, value: sessionStorage.getItem(name) ?? '' }))
      .filter((entry) => {
        if (Date.now() - JSON.parse(entry.value).at < TTL) return true
        sessionStorage.removeItem(entry.name)
        return false
      })
      .filter((entry) => entry.name !== PREFIX + key)
      .sort((a, b) => JSON.parse(a.value).at - JSON.parse(b.value).at)
    let bytes = value.length + entries.reduce((sum, entry) => sum + entry.value.length, 0)
    while (entries.length >= 40 || bytes > MAX_BYTES) {
      const index = entries.findIndex((entry) => entry.name.startsWith(PREFIX + 'nav:'))
      if (index < 0) return false
      const [entry] = entries.splice(index, 1)
      sessionStorage.removeItem(entry.name)
      bytes -= entry.value.length
    }
    sessionStorage.setItem(PREFIX + key, value)
    return true
  } catch { return false }
}
export function clearContinuity() {
  try {
    for (const key of Object.keys(sessionStorage)) if (key.startsWith(PREFIX)) sessionStorage.removeItem(key)
  } catch { /* Storage may be disabled. */ }
  window.dispatchEvent(new Event('gl3-clear-continuity'))
}

export function removeSession(key: string) {
  try { sessionStorage.removeItem(PREFIX + key) } catch { /* Storage is optional. */ }
}
