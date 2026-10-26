import { useEffect, useState } from 'react'
import { client, type BuyingChainResult } from '../../api/client'

const relationshipLabels: Record<string, string> = {
  DIRECT: 'Direct project evidence',
  ROLE_SUPPORTED: 'Role-supported · project assignment unknown',
  UNKNOWN: 'Project relationship unknown',
}

function safeUrl(value: string) {
  try {
    const url = new URL(value)
    return ['https:', 'http:'].includes(url.protocol) ? url.href : undefined
  } catch { return undefined }
}

function time(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString() : 'Unknown'
}

function checkedResult(data: BuyingChainResult, projectId: string) {
  if (!data || data.project_id !== projectId || !Array.isArray(data.candidates)
    || !Array.isArray(data.unresolved) || !Array.isArray(data.runs)) {
    throw new Error('Buying-chain response did not match this project. Please retry.')
  }
  return data
}

export function BuyingChain({ projectId }: { projectId: string }) {
  const [result, setResult] = useState<BuyingChainResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    setResult(null); setLoading(true); setError('')
    void client.buyingChain(projectId, controller.signal)
      .then((data) => { if (!controller.signal.aborted) setResult(checkedResult(data, projectId)) })
      .catch((cause: unknown) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Buying chain could not be loaded.') })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [projectId])

  return <section className="detail-section buying-chain" aria-labelledby="buying-chain-heading" data-context-loading={loading}>
    <div className="evidence-heading"><div><p className="eyebrow">Project-specific relationships</p><h3 id="buying-chain-heading">Buying chain</h3></div></div>
    <p className="buying-chain-note">Organization involvement, current job role, and a person’s assignment to this project are separate claims. A relevant role does not establish purchasing authority or an open temporary-power package.</p>
    {loading && <p role="status">Loading buying chain…</p>}
    {(result?.research_job?.status === 'queued' || result?.research_job?.status === 'running') && <p role="status">Automated buying-chain research {result.research_job.status}. Findings update when the worker completes.</p>}
    {result?.research_job?.detail_status === 'disabled' && <p className="buying-chain-note">Public research is disabled. Retained project evidence remains available.</p>}
    {result?.research_job?.detail_status === 'blocked_source_policy' && <p className="buying-chain-note">Public research was blocked because this project’s source policy is disabled. Retained project evidence remains available.</p>}
    {result?.research_job?.detail_status === 'stale' && <p className="buying-chain-note">Project evidence changed while research was running, so this result was discarded. The latest project evidence has not yet been evaluated.</p>}
    {result?.research_job?.detail_status === 'partial' && <p className="buying-chain-note">Research completed with unresolved sources. Existing findings and citations remain inspectable.</p>}
    {error && <p role="alert" className="integrity">{error}{result?.candidates?.length ? ' Previously retained findings remain below.' : ''}</p>}
    {result && <>
      <div className="permit-summary">
        <h4>Retained permit facts</h4>
        <p className="buying-chain-note">Permit dates describe permitting, not the power start date. Listed parties are source roles; employment, purchasing authority and an open power package require separate evidence.</p>
        {(result.permit_summaries ?? []).length === 0 && <p>No supported permit fields retained for this project yet.</p>}
        {(result.permit_summaries ?? []).map((permit) => <details key={permit.evidence_id} data-context-owner={permit.evidence_id} open>
          <summary>{permit.title}</summary>
          <dl>{(permit.facts ?? []).map((fact, index) => <div key={index}><dt>{fact.label}</dt><dd><span>{safeUrl(fact.value) ? <a href={safeUrl(fact.value)} target="_blank" rel="noreferrer">{fact.value}</a> : fact.value}</span><details data-context-key={`${permit.evidence_id}:${fact.label}:${index}`}><summary>Field evidence</summary><blockquote>{fact.quote}</blockquote>{fact.role_quote && <blockquote>{fact.role_quote}</blockquote>}</details></dd></div>)}</dl>
          <p className="evidence-meta"><a href={safeUrl(permit.url)} target="_blank" rel="noreferrer">Official permit source</a> · {permit.extraction_location} · Observed {time(permit.observed_at)}</p>
        </details>)}
        <p className="buying-chain-note">Unlisted applicant, operator, GC, electrical contractor, EPC, engineer, named person and business contact fields remain unknown. Permit scope alone does not establish temporary load, fuel suitability, commissioning dates or an unmet supply gap.</p>
      </div>
      <p className="buying-chain-status">Research status: {result.status.replaceAll('_', ' ')}</p>
      {(result.candidates ?? []).length === 0 && <p>No supported buying-chain candidates retained yet. Buyer and project contacts remain unknown.</p>}
      <ol className="buying-chain-list">{(result.candidates ?? []).map((candidate) => <li key={candidate.id} data-context-owner={candidate.id}>
        <div className="buying-chain-title"><h4>{candidate.organization}</h4><span>{candidate.category.replaceAll('_', ' ')}</span></div>
        {candidate.retracted && <p className="integrity">This project relationship is retracted and retained here as history.</p>}
        <p><strong>{candidate.person_name ?? 'Named person unknown'}</strong>{candidate.title ? ` · ${candidate.title}` : ' · Current title unknown'}</p>
        <p className="integrity">{candidate.person_name ? (relationshipLabels[candidate.person_project_relationship] ?? relationshipLabels.UNKNOWN) : candidate.organization_relationship === 'DIRECT' ? 'Organization involvement supported · named person unknown' : 'Organization involvement unknown'} · {candidate.evidence_strength} evidence</p>
        <p>{candidate.reason}</p>{candidate.stale && <p className="integrity">Historical title evidence · current role needs verification</p>}
        <dl className="buying-chain-relations"><div><dt>Project → organization</dt><dd>{candidate.organization_relationship === 'DIRECT' ? 'Direct involvement evidence' : 'Unknown'}</dd></div><div><dt>Organization → person</dt><dd>{candidate.person_organization_relationship === 'CURRENT' ? 'Current role supported' : 'Current role unknown'}</dd></div><div><dt>Person → project</dt><dd>{relationshipLabels[candidate.person_project_relationship] ?? relationshipLabels.UNKNOWN}</dd></div></dl>
        <p className="evidence-meta">Observed {time(candidate.observed_at)} · Evidence assessed {time(candidate.verified_at)} · {candidate.history_count ?? 1} retained claim version(s)</p>
        {(candidate.public_contacts ?? []).length === 0 && <p className="buying-chain-note">Public business contact details unknown</p>}
        {(candidate.public_contacts ?? []).map((contact, index) => <p key={index}>{contact.kind}: {contact.value} <a href={safeUrl(contact.source_url)} target="_blank" rel="noreferrer">Contact source</a></p>)}

        <details><summary>Inspect relationship evidence ({(candidate.evidence ?? []).length})</summary>{(candidate.evidence ?? []).map((evidence, index) => <div className="evidence" key={index}><a href={safeUrl(evidence.url)} target="_blank" rel="noreferrer">{evidence.supports.replaceAll("_", " ")} · {evidence.extraction_location}</a><blockquote>{evidence.quote}</blockquote><p className="evidence-meta">Published {evidence.published_at ?? 'Unknown'} · Observed {time(evidence.observed_at)}</p></div>)}</details>
      </li>)}</ol>
      {(result.unresolved ?? []).length > 0 && <details open={(result.candidates ?? []).length === 0}><summary>Unresolved questions ({(result.unresolved ?? []).length})</summary><ul>{(result.unresolved ?? []).map((question, index) => <li key={index}>{question}</li>)}</ul></details>}
      {(result.runs ?? []).length > 0 && <details><summary>Research history ({(result.runs ?? []).length})</summary><ul>{(result.runs ?? []).map((run) => <li key={run.id}>{time(run.created_at)} · {run.status.replaceAll("_", " ")} · {run.documents_checked} documents checked · {run.candidates_added} new claim versions{run.unresolved.length > 0 && <ul>{run.unresolved.map((question, questionIndex) => <li key={questionIndex}>{question}</li>)}</ul>}</li>)}</ul></details>}
      <p className="buying-chain-note"><a href={`/api/projects/${encodeURIComponent(projectId)}/buying-chain?history=true`} target="_blank" rel="noreferrer">Inspect retained claim history</a></p>
    </>}
  </section>
}
