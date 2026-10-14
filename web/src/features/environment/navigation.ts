import { useEffect, useLayoutEffect, useReducer, useRef } from 'react'
import { readSession, writeSession } from '../../state/sessionState'
import type { Scene } from './Environment'

type Surface = { menuOpen: boolean; y: number; scroll: Record<string, number>; focus: string | null; disclosures: Record<string, boolean> }
type Entry = { scene: Scene; surface?: Surface }
function identity(element: Element): string {
  const explicit = element.getAttribute('data-context-key') || element.id || element.getAttribute('aria-label')
    || (element.tagName === 'SUMMARY' ? element.parentElement?.getAttribute('data-context-key') : null)
  if (explicit) return `${element.tagName}:${explicit}`
  const owner = element.closest('[data-context-owner]')?.getAttribute('data-context-owner') ?? ''
  return `${owner}:${element.tagName}:${element instanceof HTMLDetailsElement ? element.querySelector('summary')?.textContent : element.textContent}`
}
const controls = () => [...document.querySelectorAll<HTMLElement>('.env button, .env a, .env input, .env textarea, .env select, .env summary, .env h1')]
function capture(): Surface {
  return {
    menuOpen: document.querySelector('.env-menu > button')?.getAttribute('aria-expanded') === 'true',
    y: scrollY,
    focus: document.activeElement?.closest('.env') ? identity(document.activeElement) : null,
    scroll: Object.fromEntries([...document.querySelectorAll<HTMLElement>('[data-context-scroll]')].map((el) => [el.dataset.contextScroll!, el.scrollTop])),
    disclosures: Object.fromEntries([...document.querySelectorAll<HTMLDetailsElement>('.env details')].map((el) => [identity(el), el.open])),
  }
}
// Browser history is the context stack. Domain responses and call drafts never enter it.
export function useEnvironmentNavigation(parse: () => Scene, urlFor: (scene: Scene) => string) {
  const [entry, dispatch] = useReducer((_old: Entry, next: Entry) => next, undefined, () => {
    const scene = parse()
    const stored = readSession<Entry>(`nav:${urlFor(scene)}`)
    return (history.state?.gl3env as Entry | undefined)?.scene
      ? history.state.gl3env as Entry
      : { scene, surface: stored?.surface }
  })
  const current = useRef(entry)
  current.current = entry
  const restoring = useRef(true)
  const save = () => {
    if (restoring.current) return
    const saved = { scene: current.current.scene, surface: capture() }
    history.replaceState({ ...history.state, gl3env: saved }, '')
    writeSession(`nav:${urlFor(saved.scene)}`, saved)
  }
  useEffect(() => {
    history.scrollRestoration = 'manual'
    history.replaceState({ ...history.state, gl3env: entry }, '', urlFor(entry.scene))
    const pop = () => {
      restoring.current = true
      dispatch(history.state?.gl3env?.scene ? history.state.gl3env : { scene: parse() })
    }
    const saveEvent = () => save()
    window.addEventListener('popstate', pop)
    window.addEventListener('pagehide', saveEvent)
    document.addEventListener('scroll', saveEvent, true)
    document.addEventListener('focusin', saveEvent)
    document.addEventListener('toggle', saveEvent, true)
    return () => {
      window.removeEventListener('popstate', pop)
      window.removeEventListener('pagehide', saveEvent)
      document.removeEventListener('scroll', saveEvent, true)
      document.removeEventListener('focusin', saveEvent)
      document.removeEventListener('toggle', saveEvent, true)
      history.scrollRestoration = 'auto'
    }
    // Listeners use the current entry ref, never a captured scene.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  useLayoutEffect(() => {
    let finished = false
    const restore = () => {
      if (finished) return
      const surface = entry.surface
      for (const el of document.querySelectorAll<HTMLDetailsElement>('.env details')) {
        const open = surface?.disclosures[identity(el)]
        if (open !== undefined && el.open !== open) el.open = open
      }
      if (surface?.menuOpen && !document.querySelector('.env-menu nav')) return
      const target = (surface?.focus ? controls().find((el) => identity(el) === surface.focus) : null) ?? document.querySelector<HTMLElement>('.env h1')
      if (!target || document.querySelector('.env [data-context-loading="true"]')) return
      target.focus({ preventScroll: true })
      for (const el of document.querySelectorAll<HTMLElement>('[data-context-scroll]')) el.scrollTop = surface?.scroll[el.dataset.contextScroll!] ?? 0
      window.scrollTo({ top: surface?.y ?? 0, behavior: 'instant' })
      finished = true
      restoring.current = false
    }
    const observer = new MutationObserver(restore)
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['data-context-loading'] })
    restore()
    const cancel = () => { finished = true; restoring.current = false }
    window.addEventListener('pointerdown', cancel, { once: true })
    window.addEventListener('keydown', cancel, { once: true })
    return () => { observer.disconnect(); window.removeEventListener('pointerdown', cancel); window.removeEventListener('keydown', cancel) }
  }, [entry])
  function go(patch: Partial<Scene>) {
    save()
    const scene = { ...current.current.scene, ...patch, depth: current.current.scene.depth + 1 }
    const next = { scene }
    restoring.current = true
    history.pushState({ gl3env: next }, '', urlFor(scene))
    dispatch(next)
  }
  return { scene: entry.scene, surface: entry.surface, go, save }
}

export function environmentReturnUrl() {
  const candidate = new URLSearchParams(location.search).get('returnTo')
  if (!candidate) return null
  try {
    const url = new URL(candidate, location.origin)
    return url.origin === location.origin && url.pathname === '/' && url.searchParams.get('view') === 'environment' ? url.pathname + url.search : null
  } catch { return null }
}
export function withEnvironmentReturn(destination: string) {
  const url = new URL(destination, location.origin)
  url.searchParams.set('returnTo', location.pathname + location.search)
  return url.pathname + url.search + url.hash
}
