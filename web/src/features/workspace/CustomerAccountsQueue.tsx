import { CompanyContacts } from "./CompanyContacts"
import { OpportunityTable } from './OpportunityTable'
import { useEffect, useRef, useState } from 'react'
import { client, type WorkspaceNeed, type WorkspacePage, type WorkspaceFilters, type CustomerProjectsPage, type CustomerAccount, type UnresolvedCustomerProjectsPage } from '../../api/client'

const expandedAccount = () => { const p = new URLSearchParams(location.search); return p.has('need') && !p.has('accountBrowse') ? '' : p.get('account') ?? '' }
const routeOffset = (key: string) => { const value = Number(new URLSearchParams(location.search).get(key) ?? 0); return Number.isSafeInteger(value) && value >= 0 ? value : 0 }

type AccountRow = WorkspaceNeed & { company_identity_id: string }
const displayAliases = (name: string | null | undefined, aliases: string[] | undefined) => (aliases ?? []).filter(alias => alias.trim() && alias.trim().toLocaleLowerCase() !== (name ?? '').trim().toLocaleLowerCase())
const formatEvidenceDate = (value: string | null | undefined) => {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString()
}

export function CustomerAccountsQueue({ page, filters, onNeed, onPage, pagingAvailable }: { page: WorkspacePage | null; filters: WorkspaceFilters; onNeed: (needId: string, context?: { accountId: string; projectId?: string }) => void; onPage: (offset: number, cohortToken: string | undefined) => void; pagingAvailable: boolean }) {
  const rows = page?.items ?? []
  const accounts = rows.filter((row): row is AccountRow => Boolean(row.company_identity_id))
  const [accountId, setAccountId] = useState(expandedAccount)
  const [projectId, setProjectId] = useState(() => new URLSearchParams(location.search).get('project') ?? '')
  const [projectOffset, setProjectOffset] = useState(() => routeOffset('project_offset'))
  const [needOffset, setNeedOffset] = useState(() => Number(new URLSearchParams(location.search).get('need_offset') ?? 0) || 0)
  const [projects, setProjects] = useState<CustomerProjectsPage | null>(null)
  const [unresolved, setUnresolved] = useState<UnresolvedCustomerProjectsPage | null>(null)
  const search = filters.search ?? ''
  const [unresolvedPage, setUnresolvedPage] = useState(() => ({ search, offset: 0 }))
  const unresolvedOffset = unresolvedPage.search === search ? unresolvedPage.offset : 0
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [unresolvedOpen, setUnresolvedOpen] = useState(false)
  const projectRequest = useRef(0)
  const unresolvedRequest = useRef(0)
  const accountParam = expandedAccount()

  useEffect(() => {
    const sync = () => { const params = new URLSearchParams(location.search); setAccountId(expandedAccount()); setProjectId(params.get('project') ?? ''); setProjectOffset(routeOffset('project_offset')); setNeedOffset(Number(params.get('need_offset') ?? 0) || 0) }
    addEventListener('popstate', sync)
    return () => removeEventListener('popstate', sync)
  }, [])
  useEffect(() => {
    if (accountId !== accountParam) { const params = new URLSearchParams(location.search); setAccountId(accountParam); setProjectOffset(routeOffset('project_offset')); setProjectId(params.get('project') ?? ''); setNeedOffset(Number(params.get('need_offset') ?? 0) || 0) }
  }, [accountParam, accountId])
  useEffect(() => {
    setUnresolvedPage(current => current.search === search ? current : { search, offset: 0 })
  }, [search])
  useEffect(() => {
    const controller = new AbortController()
    if (!accountId) { setProjects(null); return () => controller.abort() }
    setProjects(null); setError('')
    const sequence = ++projectRequest.current
    client.customerAccountProjects(accountId, projectOffset, needOffset, controller.signal).then(value => { if (!controller.signal.aborted && sequence === projectRequest.current) setProjects(value) }).catch(cause => { if (!controller.signal.aborted && sequence === projectRequest.current) setError(cause instanceof Error ? cause.message : 'Could not load account projects.') })
    return () => controller.abort()
  }, [accountId, projectOffset, needOffset, retry])
  useEffect(() => {
    const controller = new AbortController()
    const sequence = ++unresolvedRequest.current
    client.unresolvedCustomerProjects(filters.search ?? '', unresolvedOffset, controller.signal).then(value => { if (!controller.signal.aborted && sequence === unresolvedRequest.current) setUnresolved(value) }).catch(() => { if (!controller.signal.aborted && sequence === unresolvedRequest.current) setUnresolved(null) })
    return () => controller.abort()
  }, [search, unresolvedOffset, retry])

  const openAccount = (id: string) => {
    const params = new URLSearchParams(location.search); params.set('account', id); params.set('accountBrowse', '1'); params.delete('project'); params.delete('project_offset')
    history.pushState(history.state, '', `${location.pathname}?${params}`)
    setProjectOffset(0); setNeedOffset(0); setAccountId(id); setProjectId('')
  }
  const closeAccount = () => {
    const params = new URLSearchParams(location.search); params.delete('account'); params.delete('project'); params.delete('project_offset'); params.delete('accountBrowse')
    history.pushState(history.state, '', `${location.pathname}${params.size ? `?${params}` : ''}`)
    setAccountId(''); setProjectId(''); setNeedOffset(0)
  }
  const openProject = (id: string) => {
    const params = new URLSearchParams(location.search); params.set('project', id); params.delete('need_offset')
    history.pushState(history.state, '', `${location.pathname}?${params}`); setProjectId(id); setNeedOffset(0)
  }
  const selected = accounts.find(account => account.company_identity_id === accountId)
  const account: CustomerAccount | null = projects?.account ?? null
  const bestNeed = account?.highest_priority_need
  const unresolvedItems = unresolved?.items ?? []
  const pageNeeds = (offset: number, count: number) => `${count ? offset + 1 : 0}–${offset + count}`
  const updateNeedOffset = (offset: number) => {
    const params = new URLSearchParams(location.search); if (offset) params.set('need_offset', String(offset)); else params.delete('need_offset')
    history.pushState(history.state, '', `${location.pathname}?${params}`); setNeedOffset(offset)
  }
  const updateProjectOffset = (offset: number) => {
    const params = new URLSearchParams(location.search); if (offset) params.set('project_offset', String(offset)); else params.delete('project_offset')
    history.pushState(history.state, '', `${location.pathname}?${params}`); setProjectOffset(offset)
  }
  const updateUnresolvedOffset = (offset: number) => setUnresolvedPage({ search, offset })
  const accountPaging = <nav className="ci-paging" aria-label="Customer account pages"><span>Accounts {page ? pageNeeds(page.offset, accounts.length) : '—'} of {page?.total ?? '—'}</span><button type="button" disabled={!pagingAvailable || !page?.offset} onClick={() => { if (page) onPage(Math.max(0, page.offset - page.limit), page.cohort_token) }}>Previous</button><button type="button" disabled={!pagingAvailable || page?.next_offset == null} onClick={() => { if (page?.next_offset != null) onPage(page.next_offset, page.cohort_token) }}>Next</button></nav>

  return <section className="ci-accounts" aria-label="Customer accounts">
    {accountId ? <>
      <button type="button" className="ci-back" onClick={closeAccount}>← All accounts</button>
      <h2>{selected?.account_name ?? account?.name ?? selected?.commercial_organization ?? 'Customer account'}</h2>
      {accountPaging}
      <p className="ci-account-summary">{bestNeed?.industry ?? 'Industry not established'} · {bestNeed?.location ?? selected?.location ?? 'Location not established'}</p>
      <p className="ci-account-summary">{account?.project_count ?? selected?.project_count ?? '—'} projects · {account?.need_count ?? selected?.need_count ?? '—'} power needs · {account?.supporting_evidence_count ?? selected?.supporting_evidence_count ?? 0} supporting evidence items</p>
      {displayAliases(account?.name ?? selected?.account_name, account?.aliases ?? selected?.account_aliases).length > 0 && <p className="ci-account-summary">Also known as: {displayAliases(account?.name ?? selected?.account_name, account?.aliases ?? selected?.account_aliases).join(', ')}</p>}
      {(account?.last_evidence_update ?? selected?.last_evidence_update) && <p className="ci-account-summary">Evidence updated {formatEvidenceDate(account?.last_evidence_update ?? selected?.last_evidence_update)}</p>}
      <p className="ci-account-action">{bestNeed?.activity_key ?? 'Power need'}{bestNeed?.required_mw ? ` · ${bestNeed.required_mw} MW` : ''}{bestNeed?.start_window ? ` · ${bestNeed.start_window}` : ''}{bestNeed?.commercial_disposition ? ` · ${bestNeed.commercial_disposition}` : ''}</p>
      <p className="ci-account-action">{bestNeed?.commercial_next_action ?? 'Research needed'}</p>
      {error && <p role="alert">{error} <button type="button" onClick={() => setRetry(value => value + 1)}>Retry</button></p>}
      {!projects && !error && <p role="status">Loading account projects…</p>}
      {account && <CompanyContacts companyId={account.company_identity_id}/>}
      {projects?.items.map(project => <article className={`ci-project ${projectId === project.id ? 'selected' : ''}`} key={project.id}>
        <h3><button type="button" aria-pressed={projectId === project.id} onClick={() => openProject(project.id)}>{project.name}</button></h3><p>{project.location ?? 'Location not established'} · {project.customer_role}</p>
        {project.id === projectId && <>
          {project.needs.map(need => <button className="ci-need" type="button" key={need.id} onClick={() => onNeed(need.id)}>
            {need.activity_key} · {need.required_mw ? `${need.required_mw} MW` : 'MW not established'} · {need.start_window ?? 'timing not established'}
          </button>)}
          {(needOffset > 0 || project.need_next_offset != null) && <nav className="ci-paging" aria-label={`${project.name} power need pages`}><span>Needs {pageNeeds(needOffset, project.needs.length)} of {project.need_count}</span><button type="button" disabled={needOffset === 0} onClick={() => updateNeedOffset(Math.max(0, needOffset - 25))}>Previous</button><button type="button" disabled={project.need_next_offset == null} onClick={() => updateNeedOffset(project.need_next_offset!)}>Next</button></nav>}
        </>}
      </article>)}
      {projects && <nav className="ci-paging" aria-label="Account project pages"><span>{projects.items.length} of {projects.total} projects</span><button type="button" disabled={!projects.offset} onClick={() => updateProjectOffset(Math.max(0, projects.offset - projects.limit))}>Previous</button><button type="button" disabled={projects.next_offset == null} onClick={() => updateProjectOffset(projects.next_offset!)}>Next</button></nav>}
    </> : <>
      <OpportunityTable items={accounts} selectedId={new URLSearchParams(location.search).get('need') ?? undefined} onSelect={account => onNeed(account.id, { accountId: account.company_identity_id!, projectId: account.project_id })} onAccount={account => openAccount(account.company_identity_id!)}/>
      {accountPaging}
      <details className="ci-unresolved" open={unresolvedOpen} onToggle={event => setUnresolvedOpen(event.currentTarget.open)}>
        <summary>Projects needing customer research{unresolved ? ` (${unresolved.total})` : ''}</summary>
        {unresolvedItems.map(project => <article key={project.project_id}><strong>{project.project_name}</strong><span>{project.location ?? 'Location not established'} · {project.role}</span><span className="ci-customer-review">Customer needs confirmation</span><p>{project.reason}</p>{project.need_id && !project.no_eligible_need ? <button type="button" onClick={() => onNeed(project.need_id!)}>Review this power need</button> : <a href={`/?view=pursuits&q=${encodeURIComponent(project.organization)}`}>Research {project.organization}</a>}</article>)}
        {unresolved && <nav className="ci-paging" aria-label="Unresolved customer project pages"><span>{pageNeeds(unresolved.offset, unresolved.items.length)} of {unresolved.total}</span><button type="button" disabled={!unresolved.offset} onClick={() => updateUnresolvedOffset(Math.max(0, unresolved.offset - unresolved.limit))}>Previous</button><button type="button" disabled={unresolved.offset + unresolved.items.length >= unresolved.total} onClick={() => updateUnresolvedOffset(unresolved.offset + unresolved.limit)}>Next</button></nav>}
        {!unresolved && <p>Unresolved customer projects could not be loaded. <button type="button" onClick={() => setRetry(value => value + 1)}>Retry</button></p>}
      </details>
    </>}
  </section>
}
