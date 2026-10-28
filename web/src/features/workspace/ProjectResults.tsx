import { useEffect, useRef, useState } from 'react'
import { client, OpportunityBrowsePendingError, OpportunityCohortChangedError, OpportunityGroupUnavailableError, type OpportunityGroup, type OpportunityGroupsPage, type ProjectResult, type ProjectResultsPage } from '../../api/client'

type Props = { selectedNeedId?: string; onNeed: (need: { id: string }) => void; onBrowseChange?: () => void }
const MAX_PENDING_RETRIES = 3
const PENDING_EXHAUSTED_MESSAGE = 'Results are still being prepared. Please try again shortly.'

function waitForRetry(delayMs: number, signal: AbortSignal): Promise<boolean> {
  if (signal.aborted) return Promise.resolve(false)
  return new Promise(resolve => {
    let timer: ReturnType<typeof setTimeout>
    const finish = (completed: boolean) => {
      clearTimeout(timer)
      signal.removeEventListener('abort', onAbort)
      resolve(completed)
    }
    const onAbort = () => finish(false)
    signal.addEventListener('abort', onAbort, { once: true })
    timer = setTimeout(() => finish(true), delayMs)
  })
}

export function ProjectResults({ selectedNeedId, onNeed, onBrowseChange }: Props) {
  const readRoute = () => { const route = new URLSearchParams(location.search); return { search: route.get('q') ?? '', sector: (route.get('sector') === 'oil_gas' || route.get('sector') === 'data_centers' ? route.get('sector') : 'all') as 'all' | 'oil_gas' | 'data_centers', offset: Number(route.get('offset') ?? 0) } }
  const [initialRoute] = useState(readRoute)
  const [search, setSearch] = useState(initialRoute.search)
  const [sector, setSector] = useState(initialRoute.sector)
  const [page, setPage] = useState<OpportunityGroupsPage | null>(null)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [children, setChildren] = useState<Record<string, ProjectResultsPage | null>>({})
  const [childErrors, setChildErrors] = useState<Record<string, string>>({})
  const [childLoading, setChildLoading] = useState<Record<string, boolean>>({})
  const [childNotices, setChildNotices] = useState<Record<string, string>>({})
  const [childOffsets, setChildOffsets] = useState<Record<string, number>>({})
  const [groupParentTokens, setGroupParentTokens] = useState<Record<string, string>>({})
  const [openedGroups, setOpenedGroups] = useState<Record<string, OpportunityGroup>>({})
  const [offset, setOffset] = useState(initialRoute.offset)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [loading, setLoading] = useState(false)
  const [retryKey, setRetryKey] = useState(0)
  const childRequests = useRef(new Map<string, AbortController>())
  const childEpoch = useRef(0)
  const resetChildRequests = () => { childEpoch.current += 1; childRequests.current.forEach(request => request.abort()); childRequests.current.clear(); setExpanded({}); setChildren({}); setChildErrors({}); setChildLoading({}); setChildNotices({}); setChildOffsets({}); setGroupParentTokens({}); setOpenedGroups({}) }
  useEffect(() => () => {
    childEpoch.current += 1
    childRequests.current.forEach(request => request.abort())
    childRequests.current.clear()
  }, [])
  useEffect(() => {
    const onPop = () => { const route = readRoute(); setSearch(route.search); setSector(route.sector); setOffset(route.offset) }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])
  useEffect(() => {
    childEpoch.current += 1; childRequests.current.forEach(request => request.abort()); childRequests.current.clear()
    const controller = new AbortController(); setLoading(true); setError(''); setNotice(''); setPage(null); setExpanded({}); setChildren({}); setChildErrors({}); setChildLoading({}); setChildNotices({}); setChildOffsets({}); setGroupParentTokens({}); setOpenedGroups({})
    const cohort = new URLSearchParams(location.search).get('cohort_token') ?? undefined
    const loadGroups = async () => {
      for (let attempt = 0; attempt <= MAX_PENDING_RETRIES; attempt += 1) {
        try {
          const value = await client.opportunityGroups({ search, sector, limit: 25, offset, cohort_token: cohort, sort: 'priority' }, controller.signal)
          if (controller.signal.aborted) return
          setPage(value); setOpenedGroups({}); setLoading(false); setNotice('')
          return
        } catch (e) {
          if (controller.signal.aborted) return
          if (e instanceof OpportunityBrowsePendingError && attempt < MAX_PENDING_RETRIES) {
            setNotice('Results are still being prepared. Retrying automatically…')
            if (await waitForRetry(e.retryAfterMs, controller.signal)) continue
            return
          }
          if (e instanceof OpportunityCohortChangedError) {
            setPage(null)
            setNotice('Results changed. Reloaded from the first page.')
            updateUrl(search, sector)
            setOffset(0)
            if (offset === 0) setRetryKey(value => value + 1)
          } else {
            setNotice('')
            setError(e instanceof OpportunityBrowsePendingError ? PENDING_EXHAUSTED_MESSAGE : e instanceof Error ? e.message : 'Could not load operator/customer groups.')
          }
          setLoading(false)
          return
        }
      }
    }
    void loadGroups()
    return () => controller.abort()
  }, [search, sector, offset, retryKey])
  const updateUrl = (nextSearch: string, nextSector: string, nextOffset = 0, cohort?: string) => {
    const next = new URLSearchParams({ view: 'workspace' }); if (nextSearch) next.set('q', nextSearch); if (nextSector !== 'all') next.set('sector', nextSector); if (nextOffset) next.set('offset', String(nextOffset)); if (cohort) next.set('cohort_token', cohort)
    history.replaceState(history.state, '', `/?${next}`)
  }
  const setFilter = (q: string, s: 'all' | 'oil_gas' | 'data_centers') => { resetChildRequests(); if (selectedNeedId) onBrowseChange?.(); setNotice(''); setSearch(q); setSector(s); setOffset(0); updateUrl(q, s) }
  const groups = page?.items ?? []
  const toggleGroup = (group: OpportunityGroup) => {
    if (expanded[group.id]) {
      childRequests.current.get(group.id)?.abort(); childRequests.current.delete(group.id)
      setExpanded(current => ({ ...current, [group.id]: false }))
      setChildLoading(current => ({ ...current, [group.id]: false }))
      setChildNotices(current => { const next = { ...current }; delete next[group.id]; return next })
      setChildren(current => ({ ...current, [group.id]: null }))
      setChildOffsets(current => ({ ...current, [group.id]: 0 }))
      setGroupParentTokens(current => { const next = { ...current }; delete next[group.id]; return next })
      setOpenedGroups(current => { const next = { ...current }; delete next[group.id]; return next })
      return
    }
    setExpanded(current => ({ ...current, [group.id]: true }))
    if (children[group.id] || childLoading[group.id]) return
    loadGroupProjects(group, 0)
  }
  const loadGroupProjects = (group: OpportunityGroup, childOffset: number, cohortToken?: string) => {
    const requestSearch = search
    const requestSector = sector
    const requestPage = page
    const requestOffset = offset
    setChildLoading(current => ({ ...current, [group.id]: true })); setChildErrors(current => ({ ...current, [group.id]: '' })); setChildNotices(current => ({ ...current, [group.id]: '' }))
    childRequests.current.get(group.id)?.abort()
    const controller = new AbortController(); childRequests.current.set(group.id, controller)
    const epoch = childEpoch.current
    const requestIsCurrent = () => !controller.signal.aborted && epoch === childEpoch.current && requestSearch === search && requestSector === sector && requestOffset === offset
    const openFreshGroup = async (firstRetryDelayMs = 0) => {
      let retryDelayMs = firstRetryDelayMs
      for (let attempt = 0; attempt <= MAX_PENDING_RETRIES; attempt += 1) {
        if (retryDelayMs > 0 && !(await waitForRetry(retryDelayMs, controller.signal))) return
        if (!requestIsCurrent()) return
        try {
          const opened = await client.openOpportunityGroup(group.id, { search: requestSearch, sector: requestSector, limit: 25, sort: 'priority' }, controller.signal)
          if (!requestIsCurrent()) return
          if (opened.group.id !== group.id) throw new Error('The refreshed operator/customer group did not match the requested group.')
          setOpenedGroups(current => ({ ...current, [group.id]: opened.group }))
          setChildren(current => ({ ...current, [group.id]: opened.projects }))
          setChildOffsets(current => ({ ...current, [group.id]: 0 }))
          setGroupParentTokens(current => ({ ...current, [group.id]: opened.parent_cohort_token }))
          setChildLoading(current => ({ ...current, [group.id]: false }))
          setChildErrors(current => ({ ...current, [group.id]: '' }))
          setChildNotices(current => ({ ...current, [group.id]: '' }))
          return
        } catch (refreshError) {
          if (!requestIsCurrent()) return
          if (refreshError instanceof OpportunityBrowsePendingError && attempt < MAX_PENDING_RETRIES) {
            retryDelayMs = refreshError.retryAfterMs
            setChildNotices(current => ({ ...current, [group.id]: 'Project results are still being prepared. Retrying this group automatically…' }))
            continue
          }
          if (refreshError instanceof OpportunityGroupUnavailableError) {
            setExpanded(current => ({ ...current, [group.id]: false }))
            setChildren(current => ({ ...current, [group.id]: null }))
            setChildOffsets(current => ({ ...current, [group.id]: 0 }))
            setGroupParentTokens(current => { const next = { ...current }; delete next[group.id]; return next })
            setOpenedGroups(current => { const next = { ...current }; delete next[group.id]; return next })
            setNotice(refreshError.message)
          }
          setChildNotices(current => ({ ...current, [group.id]: '' }))
          setChildErrors(current => ({ ...current, [group.id]: refreshError instanceof OpportunityBrowsePendingError ? PENDING_EXHAUSTED_MESSAGE : refreshError instanceof Error ? refreshError.message : 'Could not load projects.' }))
          setChildLoading(current => ({ ...current, [group.id]: false }))
          return
        }
      }
    }
    const wasPagination = childOffset > 0 || Boolean(cohortToken)
    const recoverGroup = (retryDelayMs = 0) => {
      setChildren(current => ({ ...current, [group.id]: null }))
      setChildOffsets(current => ({ ...current, [group.id]: 0 }))
      if (retryDelayMs > 0) setChildNotices(current => ({ ...current, [group.id]: 'Project results are still being prepared. Retrying this group automatically…' }))
      else if (wasPagination) setNotice('Project results changed. Reloaded this operator/customer group.')
      void openFreshGroup(retryDelayMs)
    }
    client.groupProjects(group.id, { search: requestSearch, sector: requestSector, limit: 25, offset: childOffset, cohort_token: cohortToken, parent_cohort_token: groupParentTokens[group.id] ?? requestPage?.cohort_token, sort: 'priority' }, controller.signal).then(value => {
      if (!requestIsCurrent()) return
      setChildren(current => ({ ...current, [group.id]: value })); setChildOffsets(current => ({ ...current, [group.id]: childOffset })); setChildLoading(current => ({ ...current, [group.id]: false }))
    }).catch((e: Error) => {
      if (!requestIsCurrent()) return
      if (e instanceof OpportunityCohortChangedError) {
        recoverGroup()
      } else if (e instanceof OpportunityBrowsePendingError) {
        recoverGroup(e.retryAfterMs)
      } else {
        setChildNotices(current => ({ ...current, [group.id]: '' }))
        setChildErrors(current => ({ ...current, [group.id]: e.message }))
        setChildLoading(current => ({ ...current, [group.id]: false }))
      }
    })
  }
  return <section className="project-results" aria-label="Project opportunities">
    <header className="project-results-header"><div><h1>Search opportunities</h1></div>
      <label><span className="project-search-label">Search opportunities</span><input aria-label="Search opportunities" placeholder="Project, operator, well or location" value={search} onChange={e => setFilter(e.target.value, sector)}/></label>
    </header>
    <nav className="project-sector-tabs" aria-label="Project type">{([['all','All'],['oil_gas','Oil & Gas'],['data_centers','Data Centers']] as const).map(([value,label]) => <button key={value} type="button" aria-pressed={sector === value} onClick={() => setFilter(search, value)}>{label}</button>)}</nav>
    <div className="project-results-count" aria-live="polite">{page ? `${page.total} operator/customer ${page.total === 1 ? 'group' : 'groups'}` : loading ? 'Loading operator/customer groups…' : 'Operator/customer groups unavailable'}</div>
    {notice && <p role="status" className="project-results-notice">{notice}</p>}
    {error && <p role="alert">{error} <button onClick={() => setRetryKey(value => value + 1)}>Retry</button></p>}
    {loading && <p role="status">Loading operator/customer groups…</p>}
    {!loading && !error && !groups.length && <p className="project-empty">No operator/customer groups match this search.</p>}
    {!loading && !error && <div className="customer-group-list">{groups.map(group => { const displayedGroup = openedGroups[group.id] ?? group; return <section key={group.id} className="customer-group" aria-label={`${displayedGroup.name} customer group`}>
      <h2 className="customer-group-heading"><button className="customer-group-toggle" type="button" aria-expanded={Boolean(expanded[group.id])} onClick={() => toggleGroup(group)}>
        <span><strong className="customer-group-name">{displayedGroup.name}</strong><small>{displayedGroup.role === 'operator' ? 'Operator' : displayedGroup.role === 'customer' ? 'Customer' : 'Operator/customer unresolved'}{displayedGroup.operator_number ? ` · Operator ${displayedGroup.operator_number}` : ''}</small></span>
        <span className="customer-group-count">{displayedGroup.project_count} {displayedGroup.project_count === 1 ? 'project' : 'projects'}</span>
        <svg className="customer-group-chevron" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m9 18 6-6-6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
      </button></h2>
      {expanded[group.id] && <div className="customer-group-projects">
        {childNotices[group.id] && <p role="status" className="project-results-notice">{childNotices[group.id]}</p>}
        {childErrors[group.id] && <p role="alert">{childErrors[group.id]} <button type="button" onClick={() => loadGroupProjects(group, 0)}>Reload projects</button></p>}
        {childLoading[group.id] && <p role="status">Loading projects…</p>}
        {!childLoading[group.id] && !childErrors[group.id] && children[group.id] && <>
          <div className="project-card-list">{children[group.id]!.items.map(project => <ProjectCard key={project.id} project={project} selectedNeedId={selectedNeedId} onNeed={onNeed} nested/>)}</div>
          {children[group.id]!.total > children[group.id]!.limit && <footer className="project-paging"><span>{(childOffsets[group.id] ?? 0) + 1}–{(childOffsets[group.id] ?? 0) + children[group.id]!.items.length} of {children[group.id]!.total} projects</span><button disabled={childLoading[group.id] || (childOffsets[group.id] ?? 0) === 0} onClick={() => loadGroupProjects(group, Math.max(0, (childOffsets[group.id] ?? 0) - 25), children[group.id]?.cohort_token)}>Previous</button><button disabled={childLoading[group.id] || (childOffsets[group.id] ?? 0) + children[group.id]!.items.length >= children[group.id]!.total} onClick={() => loadGroupProjects(group, (childOffsets[group.id] ?? 0) + 25, children[group.id]?.cohort_token)}>Next</button></footer>}
        </>}
      </div>}
    </section>})}</div>}
    {page && page.total > page.limit && <footer className="project-paging"><span>{page && !loading && !error ? `${page.offset + (groups.length ? 1 : 0)}–${page.offset + groups.length} of ${page.total} operator/customer groups` : ''}</span><button disabled={!page || loading || Boolean(error) || page.offset === 0} onClick={() => { const n = Math.max(0, (page?.offset ?? 0) - 25); setOffset(n); updateUrl(search, sector, n, page?.cohort_token) }}>Previous</button><button disabled={!page || loading || Boolean(error) || page.offset + groups.length >= page.total} onClick={() => { const n = (page?.offset ?? 0) + 25; setOffset(n); updateUrl(search, sector, n, page?.cohort_token) }}>Next</button></footer>}
  </section>
}
function ProjectCard({ project, selectedNeedId, onNeed, nested = false }: { project: ProjectResult; selectedNeedId?: string; onNeed: Props['onNeed']; nested?: boolean }) {
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
    {nested ? <h3>{displayName}</h3> : <h2>{displayName}</h2>}{(project.company || project.location) && <p className="project-company">{[project.company, project.location].filter(Boolean).join(' · ')}</p>}
    {eventLabel && <p className="project-event">{eventLabel}</p>}
    {showPowerSummary && <p>{project.power_summary}</p>}
    {nextAction && <p className="project-next">{nextAction}</p>}
    {people.length > 0 && <div className="project-contact-people" aria-label="Source-supported project contacts">{people.map((person, index) => { const sourceUrl = /^https?:\/\//i.test(person.source_url ?? '') ? person.source_url : null; const role = (person.role ?? '').toLowerCase().replaceAll('_', ' '); const label = person.title?.trim() || (role === 'owner developer' || role === 'owner/developer' ? 'Listed owner contact' : 'Source-listed project contact'); return <div key={`${person.person_identity_id ?? person.name}-${index}`}><p><strong>{person.name}</strong>{` · ${label}`}{person.company ? ` · ${person.company}` : ''}</p>{person.responsibility && <p>{person.responsibility}</p>}<span>No verified direct method</span>{sourceUrl && <a href={sourceUrl} target="_blank" rel="noreferrer">Source</a>}</div> })}</div>}
    <div className="project-card-actions">{contacts.map((contact, index) => <a key={`${contact.kind}-${contact.href}-${index}`} href={contact.href!}>{contact.label}</a>)}{contacts.length === 0 && people.length === 0 && <span>Contact not yet verified</span>}{primary && <button type="button" onClick={() => onNeed({ id: primary })}>View project details</button>}</div>
    {project.need_count > 1 && <details className="project-needs"><summary>{project.need_count} related power needs</summary><ul>{project.needs.map(need => <li key={need.id}><button type="button" onClick={() => onNeed({ id: need.id })}>{String(need.activity ?? need.browse_title ?? 'Related project detail')}{need.location ? ` · ${String(need.location)}` : ''}</button></li>)}</ul></details>}
  </article>
}
