import { useEffect, useState } from 'react'
import { client, OpportunityCohortChangedError, type ProjectResult, type ProjectResultsPage } from '../../api/client'

type Props = { selectedNeedId?: string; onNeed: (need: { id: string }) => void; onBrowseChange?: () => void }
export function ProjectResults({ selectedNeedId, onNeed, onBrowseChange }: Props) {
  const readRoute = () => { const route = new URLSearchParams(location.search); return { search: route.get('q') ?? '', sector: (route.get('sector') === 'oil_gas' || route.get('sector') === 'data_centers' ? route.get('sector') : 'all') as 'all' | 'oil_gas' | 'data_centers', offset: Number(route.get('offset') ?? 0) } }
  const [initialRoute] = useState(readRoute)
  const [search, setSearch] = useState(initialRoute.search)
  const [sector, setSector] = useState(initialRoute.sector)
  const [page, setPage] = useState<ProjectResultsPage | null>(null)
  const [offset, setOffset] = useState(initialRoute.offset)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [loading, setLoading] = useState(false)
  const [retryKey, setRetryKey] = useState(0)
  useEffect(() => {
    const onPop = () => { const route = readRoute(); setSearch(route.search); setSector(route.sector); setOffset(route.offset) }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError(''); setPage(null)
    const cohort = new URLSearchParams(location.search).get('cohort_token') ?? undefined
    client.projectResults({ search, sector, limit: 25, offset, cohort_token: cohort, sort: 'priority' }, controller.signal).then(value => { setPage(value); setLoading(false) }).catch((e: Error) => {
      if (controller.signal.aborted) return
      if (e instanceof OpportunityCohortChangedError) {
        setPage(null)
        setError('')
        setNotice('Project results changed. Reloaded from the first page.')
        updateUrl(search, sector)
        setOffset(0)
        if (offset === 0) setRetryKey(value => value + 1)
      } else {
        setError(e.message)
        setLoading(false)
      }
    })
    return () => controller.abort()
  }, [search, sector, offset, retryKey])
  const updateUrl = (nextSearch: string, nextSector: string, nextOffset = 0, cohort?: string) => {
    const next = new URLSearchParams({ view: 'workspace' }); if (nextSearch) next.set('q', nextSearch); if (nextSector !== 'all') next.set('sector', nextSector); if (nextOffset) next.set('offset', String(nextOffset)); if (cohort) next.set('cohort_token', cohort)
    history.replaceState(history.state, '', `/?${next}`)
  }
  const setFilter = (q: string, s: 'all' | 'oil_gas' | 'data_centers') => { if (selectedNeedId) onBrowseChange?.(); setNotice(''); setSearch(q); setSector(s); setOffset(0); updateUrl(q, s) }
  const cards = page?.items ?? []
  return <section className="project-results" aria-label="Project opportunities">
    <header className="project-results-header"><div><h1>Search opportunities</h1></div>
      <label><span className="project-search-label">Search opportunities</span><input aria-label="Search opportunities" placeholder="Project, operator, well or location" value={search} onChange={e => setFilter(e.target.value, sector)}/></label>
    </header>
    <nav className="project-sector-tabs" aria-label="Project type">{([['all','All'],['oil_gas','Oil & Gas'],['data_centers','Data Centers']] as const).map(([value,label]) => <button key={value} type="button" aria-pressed={sector === value} onClick={() => setFilter(search, value)}>{label}</button>)}</nav>
    <div className="project-results-count" aria-live="polite">{page ? `${page.total} ${page.total === 1 ? 'project' : 'projects'}` : loading ? 'Loading projects…' : 'Projects unavailable'}</div>
    {notice && <p role="status" className="project-results-notice">{notice}</p>}
    {error && <p role="alert">{error} <button onClick={() => setRetryKey(value => value + 1)}>Retry</button></p>}
    {loading && <p role="status">Loading projects…</p>}
    {!loading && !error && !cards.length && <p className="project-empty">{page?.results_scope === 'qualified' ? 'No qualified power opportunities yet. Choose Oil & Gas or Data Centers, or search, to explore early project signals.' : 'No projects match this search.'}</p>}
    {!loading && !error && <div className="project-card-list">{cards.map(project => <ProjectCard key={project.id} project={project} selectedNeedId={selectedNeedId} onNeed={onNeed}/>)}</div>}
    {page && page.total > page.limit && <footer className="project-paging"><span>{page && !loading && !error ? `${page.offset + (cards.length ? 1 : 0)}–${page.offset + cards.length} of ${page.total}` : ''}</span><button disabled={!page || loading || Boolean(error) || page.offset === 0} onClick={() => { const n = Math.max(0, (page?.offset ?? 0) - 25); setOffset(n); updateUrl(search, sector, n, page?.cohort_token) }}>Previous</button><button disabled={!page || loading || Boolean(error) || page.offset + cards.length >= page.total} onClick={() => { const n = (page?.offset ?? 0) + 25; setOffset(n); updateUrl(search, sector, n, page?.cohort_token) }}>Next</button></footer>}
  </section>
}
function ProjectCard({ project, selectedNeedId, onNeed }: { project: ProjectResult; selectedNeedId?: string; onNeed: Props['onNeed'] }) {
  const primary = project.representative_need_id ?? project.needs[0]?.id
  const representative = project.needs.find(need => need.id === primary) ?? project.needs[0]
  const disposition = representative?.commercial_preview?.disposition
  const contacts = project.contact.filter(contact => /^(tel:|mailto:|https?:\/\/)/i.test(contact.href ?? ''))
  const people = project.contact_people ?? []
  const eventLabel = project.event?.label && project.event.date ? `${project.event.label} · ${project.event.date}` : project.event?.label
  const displayName = project.company && project.name.startsWith(`${project.company} · `) ? project.name.slice(project.company.length + 3) : project.name
  const call = contacts.find(contact => contact.kind === 'call' || contact.kind === 'phone' || contact.kind === 'tel')
  const nextAction = representative?.tier === 'Signal' && disposition === 'WATCH'
    ? 'Monitoring for verified power demand.'
    : representative?.tier === 'Signal' && disposition === 'ACTION NOW'
      ? call && (call.company || project.company) ? `Discuss project power plans with ${call.company || project.company}.` : 'Discovery call · Power need unconfirmed'
      : project.next_action
  const showPowerSummary = Boolean(project.power_summary && project.power_summary_kind !== 'unknown')
  return <article className="project-card" aria-current={selectedNeedId && project.needs.some(need => need.id === selectedNeedId) ? 'true' : undefined}>
    <div className="project-card-top"><span>{project.asset_type?.replaceAll('_', ' ') ?? (project.sector === 'oil_gas' ? 'Oil & Gas project' : project.sector === 'data_centers' ? 'Data center project' : 'Project')}</span>{project.sector && <span>{project.sector === 'oil_gas' ? 'Oil & Gas' : 'Data Centers'}</span>}</div>
    {representative?.tier && <div className="project-qualification"><span className="project-tier">{representative.tier}</span>{representative.tier === 'Signal' && disposition === 'ACTION NOW' && <span>Discovery call · Power need unconfirmed</span>}</div>}
    <h2>{displayName}</h2>{(project.company || project.location) && <p className="project-company">{[project.company, project.location].filter(Boolean).join(' · ')}</p>}
    {eventLabel && <p className="project-event">{eventLabel}</p>}
    {showPowerSummary && <p>{project.power_summary}</p>}
    {nextAction && <p className="project-next">{nextAction}</p>}
    {people.length > 0 && <div className="project-contact-people" aria-label="Source-supported project contacts">{people.map((person, index) => { const sourceUrl = /^https?:\/\//i.test(person.source_url ?? '') ? person.source_url : null; const role = (person.role ?? '').toLowerCase().replaceAll('_', ' '); const label = person.title?.trim() || (role === 'owner developer' || role === 'owner/developer' ? 'Listed owner contact' : 'Source-listed project contact'); return <div key={`${person.person_identity_id ?? person.name}-${index}`}><p><strong>{person.name}</strong>{` · ${label}`}{person.company ? ` · ${person.company}` : ''}</p>{person.responsibility && <p>{person.responsibility}</p>}<span>No verified direct method</span>{sourceUrl && <a href={sourceUrl} target="_blank" rel="noreferrer">Source</a>}</div> })}</div>}
    <div className="project-card-actions">{contacts.map((contact, index) => <a key={`${contact.kind}-${contact.href}-${index}`} href={contact.href!}>{contact.label}</a>)}{contacts.length === 0 && people.length === 0 && <span>Contact not yet verified</span>}{primary && <button type="button" onClick={() => onNeed({ id: primary })}>View project details</button>}</div>
    {project.need_count > 1 && <details className="project-needs"><summary>{project.need_count} related power needs</summary><ul>{project.needs.map(need => <li key={need.id}><button type="button" onClick={() => onNeed({ id: need.id })}>{String(need.activity ?? need.browse_title ?? 'Related project detail')}{need.location ? ` · ${String(need.location)}` : ''}</button></li>)}</ul></details>}
  </article>
}
