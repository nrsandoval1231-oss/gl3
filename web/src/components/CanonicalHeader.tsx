import type { ReactNode } from 'react'
import './canonical-header.css'

export type CanonicalHeaderDestination = 'opportunities' | 'companies' | 'pursuits' | 'reports'

export type CanonicalHeaderProps = {
  activeDestination?: CanonicalHeaderDestination
  onNavigate: (destination: CanonicalHeaderDestination) => void
  /** Existing search UI, preserving its API-backed behavior and callbacks. */
  search?: ReactNode
  /** Optional visual or functional fallback when the parent has no search UI. */
  searchFallback?: ReactNode
  /** Existing account/profile controls, including authentication actions. */
  profile?: ReactNode
  homeHref?: string
  /** Optional count pills per destination; hidden when absent or 0. */
  badges?: Partial<Record<CanonicalHeaderDestination, number>>
}

const destinations: { id: CanonicalHeaderDestination; label: string }[] = [
  { id: 'opportunities', label: 'Opportunities' },
  { id: 'companies', label: 'Companies' },
  { id: 'pursuits', label: 'Pursuits' },
  { id: 'reports', label: 'Reports' },
]

/** Reusable 54px corporate header; route behavior remains owned by the parent. */
export function CanonicalHeader({ activeDestination = 'opportunities', onNavigate, search, searchFallback, profile, homeHref = '/?view=workspace', badges }: CanonicalHeaderProps) {
  return (
    <header className="canonical-header">
      <a className="canonical-header__brand" href={homeHref}
        aria-label="GridLens — Commercial Intelligence for Constrained Power">
        <span className="canonical-header__brand-art" aria-hidden="true" />
      </a>
      <nav className="canonical-header__nav" aria-label="Primary navigation">
        {destinations.map(({ id, label }) => (
          <button key={id} type="button" aria-current={activeDestination === id ? 'page' : undefined}
            className={activeDestination === id ? 'is-active' : undefined} onClick={() => onNavigate(id)}>
            {label}
            {(badges?.[id] ?? 0) > 0 && <span className="canonical-header__badge" data-testid={`nav-badge-${id}`}>{badges![id]}</span>}
          </button>
        ))}
      </nav>
      <div className="canonical-header__tools">
        {(search ?? searchFallback) && <div className="canonical-header__search">{search ?? searchFallback}</div>}
        {profile && <div className="canonical-header__profile">{profile}</div>}
      </div>
    </header>
  )
}
