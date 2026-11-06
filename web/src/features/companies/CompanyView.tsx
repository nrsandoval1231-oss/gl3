import { useEffect, useMemo, useState } from 'react'
import { client, OpportunityGroupUnavailableError, type OpportunityGroup, type ProjectResult } from '../../api/client'
import { usePursuitStore } from '../../state/pursuitStore'
import { CompanyContacts } from '../workspace/CompanyContacts'

const sectorLabel = (value: string) => value === 'oil_gas' ? 'Oil & Gas' : value === 'data_centers' ? 'Data Centers' : value.replaceAll('_', ' ')
const needHref = (id: string) => `/?${new URLSearchParams({ view: 'workspace', need: id })}`

export function CompanyView({ groupId, summary, onBack, onNeed }: { groupId: string; summary?: OpportunityGroup; onBack: () => void; onNeed: (needId: string) => void }) {
  const [group, setGroup] = useState<OpportunityGroup | null>(summary ?? null)
  const [projects, setProjects] = useState<ProjectResult[]>([])
  const [total, setTotal] = useState<number | null>(null)
  const [tokens, setTokens] = useState<{ cohort: string; parent: string } | null>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'error' | 'gone'>('loading')
  const [message, setMessage] = useState('')
  const [more, setMore] = useState<'idle' | 'loading' | 'error'>('idle')
  const [retry, setRetry] = useState(0)
  const pursuits = usePursuitStore()
  useEffect(() => {
    const controller = new AbortController()
    setState('loading'); setProjects([]); setTotal(null); setTokens(null); setMore('idle'); setGroup(summary ?? null)
    client.openOpportunityGroup(groupId, { limit: 25 }, controller.signal).then(value => {
      if (controller.signal.aborted) return
      setGroup(value.group); setProjects(value.projects.items); setTotal(value.projects.total)
      setTokens({ cohort: value.projects.cohort_token, parent: value.parent_cohort_token }); setState('ready')
    }).catch((cause: unknown) => {
      if (controller.signal.aborted) return
      if (cause instanceof OpportunityGroupUnavailableError) setState('gone')
      else { setMessage(cause instanceof Error ? cause.message : 'Company projects are unavailable.'); setState('error') }
    })
    return () => controller.abort()
  }, [groupId, retry])
  async function loadMore() {
    if (!tokens) return
    setMore('loading')
    try {
      const value = await client.groupProjects(groupId, { limit: 25, offset: projects.length, cohort_token: tokens.cohort, parent_cohort_token: tokens.parent })
      setProjects(current => { const seen = new Set(current.map(item => item.id)); return [...current, ...value.items.filter(item => !seen.has(item.id))] })
      setTotal(value.total); setMore('idle')
    } catch { setMore('error') }
  }
  const complete = total !== null && projects.length >= total
  const linked = useMemo(() => {
    const projectIds = new Set<string>(), needIds = new Set<string>()
    for (const project of projects) { projectIds.add(project.project_id); project.project_ids?.forEach(id => projectIds.add(id)); project.needs.forEach(need => needIds.add(need.id)) }
    return pursuits.items.filter(item => projectIds.has(item.project_id) || needIds.has(item.need_id))
  }, [projects, pursuits.items])
  const pursuitByProject = (project: ProjectResult) => linked.filter(item => item.project_id === project.project_id || project.project_ids?.includes(item.project_id) || project.needs.some(need => need.id === item.need_id))
  const identities = useMemo(() => {
    const map = new Map<string, string>()
    for (const project of projects) if (project.customer_identity_id && !map.has(project.customer_identity_id)) map.set(project.customer_identity_id, project.company ?? group?.name ?? 'Company')
    return [...map]
  }, [projects, group?.name])
  const name = group?.name ?? 'Company'

  return <section className="cmp-company" aria-label={`Company ${name}`}>
    <button type="button" className="cmp-back" onClick={onBack}>← Back to companies</button>
    <h2>{name}</h2>
    {group && <p className="cmp-meta">{group.role === 'operator' ? 'Operator' : group.role === 'customer' ? 'Customer' : 'Unresolved'} · {group.project_count.toLocaleString()} {group.project_count === 1 ? 'project' : 'projects'} · {group.need_count.toLocaleString()} {group.need_count === 1 ? 'power need' : 'power needs'} · Priority score {group.priority_score == null ? 'unranked' : group.priority_score}{group.sectors.length ? ` · ${group.sectors.map(sectorLabel).join(', ')}` : ''}</p>}
    {state === 'loading' && <p role="status">Loading company projects…</p>}
    {state === 'gone' && <p role="alert" className="cmp-error">This company is no longer available in the current results.</p>}
    {state === 'error' && <p role="alert" className="cmp-error">{message} <button type="button" onClick={() => setRetry(value => value + 1)}>Retry</button></p>}
    {state === 'ready' && <>
      <section aria-label="Linked pursuits" className="cmp-block">
        <h3>Linked pursuits</h3>
        {!pursuits.loaded ? <p role="status">Checking your pursuits…</p> : pursuits.error ? <p>Pursuits are unavailable: {pursuits.error}</p> : <>
          <p>{linked.length} {linked.length === 1 ? 'pursuit' : 'pursuits'}{complete ? '' : ` among the ${projects.length} loaded projects`}. Matched by project and power-need ids.</p>
          {!complete && <p className="cmp-note">Load the remaining projects for a complete count.</p>}
          <ul>{linked.map(item => <li key={item.id}><button type="button" onClick={() => dispatchEvent(new CustomEvent('gl3-open-pursuit', { detail: item.id }))}>{item.title}</button> · {item.stage}</li>)}</ul>
        </>}
      </section>
      <section aria-label="Company projects" className="cmp-block">
        <h3>Projects</h3>
        <p className="cmp-note">Showing {projects.length} of {total ?? '—'} projects. Power is shown only as reported by sources.</p>
        <ul className="cmp-projects">{projects.map(project => {
          const needId = project.representative_need_id ?? project.needs[0]?.id ?? null
          const own = pursuitByProject(project)
          return <li key={project.id}>
            <strong>{project.name}</strong>
            <span>{project.location ?? 'Location unknown'}{project.asset_type ? ` · ${project.asset_type}` : ''}{project.sector ? ` · ${sectorLabel(project.sector)}` : ''}</span>
            <span>Power: {project.power_summary ?? 'Unknown'} · Priority score {project.priority_score == null ? 'unranked' : project.priority_score}{project.event?.label ? ` · ${project.event.label}${project.event.date ? ` ${project.event.date}` : ''}` : ''}</span>
            {own.length > 0 && <span className="cmp-badge">Pursuit: {own.map(item => item.stage).join(', ')}</span>}
            {needId ? <a href={needHref(needId)} onClick={event => { if (event.metaKey || event.ctrlKey || event.shiftKey || event.button) return; event.preventDefault(); onNeed(needId) }}>Open opportunity<span className="cmp-sr"> {project.name}</span></a> : <span>No opportunity record is linked.</span>}
          </li>
        })}</ul>
        {projects.length === 0 && <p>No projects are listed for this company.</p>}
        {!complete && <p><button type="button" disabled={more === 'loading'} onClick={() => void loadMore()}>{more === 'loading' ? 'Loading…' : 'Load more projects'}</button>{more === 'error' && <span role="alert"> Could not load more projects. Try again.</span>}</p>}
      </section>
      <section aria-label="Key contacts" className="cmp-block">
        <h3>Key contacts</h3>
        {identities.length === 0 ? <p>No resolved company identity is available for these projects, so contacts cannot be looked up.</p>
          : identities.map(([id, label], index) => identities.length === 1 ? <CompanyContacts key={id} companyId={id}/> : <details key={id} open={index === 0}><summary>{label}</summary><CompanyContacts companyId={id}/></details>)}
      </section>
    </>}
  </section>
}
