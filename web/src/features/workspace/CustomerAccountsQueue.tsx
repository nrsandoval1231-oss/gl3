import { useEffect, useRef, useState } from 'react'
import { client, type WorkspaceNeed, type WorkspacePage, type WorkspaceFilters, type CustomerProjectsPage, type CustomerAccount, type UnresolvedCustomerProjectsPage } from '../../api/client'

type AccountRow = WorkspaceNeed & { company_identity_id: string }
const displayAliases = (name: string | null | undefined, aliases: string[] | undefined) => (aliases ?? []).filter(alias => alias.trim() && alias.trim().toLocaleLowerCase() !== (name ?? '').trim().toLocaleLowerCase())
const formatEvidenceDate = (value: string | null | undefined) => {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString()
}

export function CustomerAccountsQueue({ page, filters, onNeed, onPage, pagingAvailable }: { page: WorkspacePage | null; filters: WorkspaceFilters; onNeed: (needId: string) => void; onPage: (offset: number, cohortToken: string | undefined) => void; pagingAvailable: boolean }) {
  const rows = page?.items ?? []
  const accounts = rows.filter((row): row is AccountRow => Boolean(row.company_identity_id))
  const [accountId, setAccountId] = useState(() => new URLSearchParams(location.search).get('account') ?? '')
  const [projectId, setProjectId] = useState(() => new URLSearchParams(location.search).get('project') ?? '')
  const [projectOffset, setProjectOffset] = useState(0)
  const [needOffset, setNeedOffset] = useState(() => Number(new URLSearchParams(location.search).get('need_offset') ?? 0) || 0)
  const [projects, setProjects] = useState<CustomerProjectsPage | null>(null)
  const [unresolved, setUnresolved] = useState<UnresolvedCustomerProjectsPage | null>(null)
  const [unresolvedOffset, setUnresolvedOffset] = useState(0)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [unresolvedOpen, setUnresolvedOpen] = useState(false)
  const projectRequest = useRef(0)
  const unresolvedRequest = useRef(0)
  const accountParam = new URLSearchParams(location.search).get('account') ?? ''

  useEffect(() => {
    const sync = () => { const params = new URLSearchParams(location.search); setAccountId(params.get('account') ?? ''); setProjectId(params.get('project') ?? ''); setProjectOffset(0); setNeedOffset(Number(params.get('need_offset') ?? 0) || 0) }
    addEventListener('popstate', sync)
    return () => removeEventListener('popstate', sync)
  }, [])
  useEffect(() => {
    if (accountId !== accountParam) { const params = new URLSearchParams(location.search); setAccountId(accountParam); setProjectOffset(0); setProjectId(params.get('project') ?? ''); setNeedOffset(Number(params.get('need_offset') ?? 0) || 0) }
  }, [accountParam, accountId])
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
  }, [filters.search, unresolvedOffset, retry])

  const openAccount = (id: string) => {
    const params = new URLSearchParams(location.search); params.set('account', id); params.delete('project')
    history.pushState(history.state, '', `${location.pathname}?${params}`)
    setProjectOffset(0); setNeedOffset(0); setAccountId(id); setProjectId('')
  }
  const closeAccount = () => {
    const params = new URLSearchParams(location.search); params.delete('account'); params.delete('project')
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
      {projects?.items.map(project => <article className={`ci-project ${projectId === project.id ? 'selected' : ''}`} key={project.id}>
        <h3><button type="button" aria-pressed={projectId === project.id} onClick={() => openProject(project.id)}>{project.name}</button></h3><p>{project.location ?? 'Location not established'} · {project.customer_role}</p>
        {project.id === projectId && <>
          {project.needs.map(need => <button className="ci-need" type="button" key={need.id} onClick={() => onNeed(need.id)}>
            {need.activity_key} · {need.required_mw ? `${need.required_mw} MW` : 'MW not established'} · {need.start_window ?? 'timing not established'}
          </button>)}
          {(needOffset > 0 || project.need_next_offset != null) && <nav className="ci-paging" aria-label={`${project.name} power need pages`}><span>Needs {pageNeeds(needOffset, project.needs.length)} of {project.need_count}</span><button type="button" disabled={needOffset === 0} onClick={() => updateNeedOffset(Math.max(0, needOffset - 25))}>Previous</button><button type="button" disabled={project.need_next_offset == null} onClick={() => updateNeedOffset(project.need_next_offset!)}>Next</button></nav>}
        </>}
      </article>)}
      {projects && <nav className="ci-paging" aria-label="Account project pages"><span>{projects.items.length} of {projects.total} projects</span><button type="button" disabled={!projects.offset} onClick={() => setProjectOffset(Math.max(0, projects.offset - projects.limit))}>Previous</button><button type="button" disabled={projects.next_offset == null} onClick={() => setProjectOffset(projects.next_offset!)}>Next</button></nav>}
    </> : <>
      <h2>Customer accounts</h2>
      <p>Companies are grouped across their matching projects and power needs.</p>
      <div className="ci-account-list"><table className="brand-account-table"><caption className="sr-only">Customer opportunities</caption><thead><tr><th scope="col">Customer / evidence</th><th scope="col">Projects</th><th scope="col">Power needs</th></tr></thead><tbody>{accounts.map(account => <tr key={account.company_identity_id}><td><button type="button" onClick={() => openAccount(account.company_identity_id!)}>
        <strong>{account.account_name ?? account.commercial_organization ?? account.browse_title ?? 'Customer name not established'}</strong>
        <span>{account.location ?? 'Location not established'} · {account.project_count ?? '—'} projects · {account.need_count ?? '—'} power needs · {account.supporting_evidence_count ?? 0} supporting evidence items</span>
        {displayAliases(account.account_name, account.account_aliases).length ? <span>Also known as: {displayAliases(account.account_name, account.account_aliases).join(', ')}</span> : null}
        {account.last_evidence_update ? <span>Evidence updated {formatEvidenceDate(account.last_evidence_update)}</span> : null}
        <span>{account.asset_type?.replaceAll('_', ' ') ?? 'Industry not established'} · {account.tier} · {[account.required_mw ? `${account.required_mw} MW` : '', account.start_window, account.commercial_disposition].filter(Boolean).join(' · ') || 'Needs confirmation'}</span>
        <span>{account.commercial_next_action ?? 'Research needed'}</span>
      </button></td><td>{account.project_count ?? "—"}</td><td>{account.need_count ?? "—"}</td></tr>)}</tbody></table></div>
      {accountPaging}
      <details className="ci-unresolved" open={unresolvedOpen} onToggle={event => setUnresolvedOpen(event.currentTarget.open)}>
        <summary>Projects needing customer research{unresolved ? ` (${unresolved.total})` : ''}</summary>
        {unresolvedItems.map(project => <article key={project.project_id}><strong>{project.project_name}</strong><span>{project.location ?? 'Location not established'} · {project.role}</span><span className="ci-customer-review">Customer needs confirmation</span><p>{project.reason}</p>{project.need_id && !project.no_eligible_need ? <button type="button" onClick={() => onNeed(project.need_id!)}>Review this power need</button> : <a href={`/?view=pursuits&pursuitQuery=${encodeURIComponent(project.organization)}`}>Research {project.organization}</a>}</article>)}
        {unresolved && <nav className="ci-paging" aria-label="Unresolved customer project pages"><span>{pageNeeds(unresolved.offset, unresolved.items.length)} of {unresolved.total}</span><button type="button" disabled={!unresolved.offset} onClick={() => setUnresolvedOffset(Math.max(0, unresolved.offset - unresolved.limit))}>Previous</button><button type="button" disabled={unresolved.offset + unresolved.items.length >= unresolved.total} onClick={() => setUnresolvedOffset(unresolved.offset + unresolved.limit)}>Next</button></nav>}
        {!unresolved && <p>Unresolved customer projects could not be loaded. <button type="button" onClick={() => setRetry(value => value + 1)}>Retry</button></p>}
      </details>
    </>}
  </section>
}
