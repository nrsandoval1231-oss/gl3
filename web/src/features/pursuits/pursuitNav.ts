/** In-app navigation requests handled by WorkspaceHome (no full page reload). */
export const pursuitHref = (id: string) => `/?view=pursuits&pursuit=${encodeURIComponent(id)}`
export const needHref = (needId: string) => `/?view=workspace&need=${encodeURIComponent(needId)}`
export const openPursuit = (id: string) => window.dispatchEvent(new CustomEvent('gl3-open-pursuit', { detail: id }))
export const openNeed = (needId: string) => window.dispatchEvent(new CustomEvent('gl3-open-need', { detail: needId }))
/** Let modified clicks (new tab) fall through to the real href; otherwise navigate in-app. */
export function inApp(event: { preventDefault: () => void; metaKey: boolean; ctrlKey: boolean; shiftKey: boolean; button: number }, go: () => void) {
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return
  event.preventDefault(); go()
}
