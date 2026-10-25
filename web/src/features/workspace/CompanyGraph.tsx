import { useEffect, useState } from 'react'
import { client, type CompanyGraph as CompanyGraphData } from '../../api/client'

function safeSource(value?: string | null) {
  if (!value) return null
  try {
    const url = new URL(value)
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null
  } catch { return null }
}

function evidenceLabel(item: CompanyGraphData['evidence'][number]) { return item.title ?? `Evidence ${item.id}` }

export function CompanyGraph({ companyId }: { companyId: string }) {
  const [graph, setGraph] = useState<CompanyGraphData | null>(null)
  const [error, setError] = useState(false)
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setGraph(null); setError(false)
    client.companyGraph(companyId, controller.signal).then(value => {
      if (!controller.signal.aborted) setGraph(value)
    }).catch(() => { if (!controller.signal.aborted) setError(true) })
    return () => controller.abort()
  }, [companyId, retry])

  const current = graph?.company?.id === companyId ? graph : null
  const evidenceLink = (item?: CompanyGraphData['evidence'][number] | null) => {
    const href = safeSource(item?.url)
    const evidenceId = item?.id
    return <small>{evidenceId ? `Evidence ${evidenceId}` : 'Evidence not established'}{item?.source_id ? ` · Source ${item.source_id}` : ''}{href && <> · <a href={href} target="_blank" rel="noreferrer">Open source</a></>}</small>
  }

  return <section aria-label="Company graph" className="company-graph">
    <h4>Company &amp; project context</h4>
    {error ? <p role="alert">Company context is unavailable. <button type="button" onClick={() => setRetry(value => value + 1)}>Retry context</button></p>
      : !current ? <p role="status">Loading company context…</p> : <>
        <p><strong>{current.company.display_name ?? 'Company name not established'}</strong></p>
        {current.company.identifiers.length > 0
          ? <ul aria-label="Company identifiers">{current.company.identifiers.map((identifier, index) => <li key={`${identifier.identifier_type}-${index}`}>{identifier.identifier_type}: {identifier.value} · {evidenceLink(identifier.evidence)}</li>)}</ul>
          : <p>Identifiers not established.</p>}
        {current.company.aliases.some(alias => alias.value && alias.evidence) ? <ul aria-label="Evidence-backed aliases">{current.company.aliases.map((alias, index) => {
          if (!alias.value || !alias.evidence) return null
          return <li key={`${alias.value}-${index}`}>{alias.value} · {evidenceLink(alias.evidence)}</li>
        })}</ul> : <p>Aliases not established by retained evidence.</p>}

        <h5>Projects</h5>
        {current.projects.length ? current.projects.map(project => <article key={project.id}>
          <strong>{project.name}</strong>
          {project.location && <p>{project.location}</p>}
          {project.roles.length ? <ul>{project.roles.map((role, index) => <li key={`${role.role}-${index}`}>{role.role}{role.organization_name ? ` · ${role.organization_name}` : ''} · {role.state} · {evidenceLink(role.evidence)}</li>)}</ul> : <p>Project role not established.</p>}
        </article>) : <p>No linked projects are established.</p>}

        <h5>Company relationships</h5>
        {current.relationships.length ? current.relationships.map(relationship => <article key={relationship.id}>
          <p>{relationship.relationship_type} · {relationship.status} · version {relationship.version}</p>
          <p>{relationship.source_company_id} → {relationship.target_company_id}</p>
          {relationship.reason && <p>{relationship.reason}</p>}
          {evidenceLink(relationship.evidence)}
        </article>) : <p>No evidence-backed company relationships are available.</p>}

        {current.evidence.length > 0 && <details><summary>Retained evidence ({current.evidence.length})</summary>
          <ul>{current.evidence.map((item, index) => {
            const href = safeSource(item.url)
            return <li key={item.id ?? index}>{evidenceLabel(item)}{href && <> · <a href={href} target="_blank" rel="noreferrer">Open source</a></>}</li>
          })}</ul>
        </details>}
      </>}
  </section>
}
