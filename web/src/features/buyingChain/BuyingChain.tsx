import { useEffect, useRef, useState } from 'react'
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
  const [enriching, setEnriching] = useState(false)
  const [error, setError] = useState('')
  const [sourceUrls, setSourceUrls] = useState('')
  const active = useRef(true)
  const pending = useRef(false)

  useEffect(() => {
    active.current = true
    const controller = new AbortController()
    client.buyingChain(projectId, controller.signal)
      .then((data) => { if (active.current) setResult(checkedResult(data, projectId)) })
      .catch((cause: unknown) => {
        if (active.current && !controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Buying chain could not be loaded.')
      })
      .finally(() => { if (active.current) setLoading(false) })
    return () => { active.current = false; controller.abort() }
  }, [projectId])

  async function enrich() {
    if (pending.current) return
    const urls = sourceUrls.split(/\n/).map((url) => url.trim()).filter(Boolean)
    if (urls.length > 4 || urls.some((url) => !safeUrl(url) || !url.startsWith('https://'))) {
      setError('Use up to four public HTTPS source links, one per line.')
      return
    }
    pending.current = true
    setEnriching(true)
    setError('')
    try {
      const data = await client.enrichBuyingChain(projectId, urls)
      if (active.current) setResult(checkedResult(data, projectId))
    } catch (cause: unknown) {
      if (active.current) setError(cause instanceof Error ? cause.message : 'Buying chain could not be enriched. Retained evidence is unchanged.')
    } finally {
      pending.current = false
      if (active.current) setEnriching(false)
    }
  }

  return <section className="detail-section buying-chain" aria-labelledby="buying-chain-heading">
    <div className="evidence-heading"><div><p className="eyebrow">Project-specific relationships</p><h3 id="buying-chain-heading">Buying chain</h3></div><button disabled={loading || enriching} onClick={enrich}>{enriching ? 'Checking evidence…' : 'Enrich buying chain'}</button></div>
    <p className="buying-chain-note">Organization involvement, current job role, and a person’s assignment to this project are separate claims. A relevant role does not establish purchasing authority or an open temporary-power package.</p>
    <details className="buying-chain-sources"><summary>Add supporting source links</summary><label>Public project or organization sources (up to four)<textarea value={sourceUrls} onChange={(event) => setSourceUrls(event.target.value)} rows={3} placeholder="https://…" disabled={enriching}/></label><p>Existing project evidence is checked first. Links should support this project’s contractors or their current team.</p></details>
    {loading && <p role="status">Loading buying chain…</p>}
    {enriching && <p role="status">Checking this project’s bounded source evidence. You can leave this view and return later.</p>}
    {error && <p role="alert" className="integrity">{error}{result ? ' Previously retained findings remain below.' : ''}</p>}
    {result && <>
      <p className="buying-chain-status">Research status: {result.status.replaceAll('_', ' ')}</p>
      {(result.candidates ?? []).length === 0 && <p>No supported buying-chain candidates retained yet. Buyer and project contacts remain unknown.</p>}
      <ol className="buying-chain-list">{(result.candidates ?? []).map((candidate) => <li key={candidate.id}>
        <div className="buying-chain-title"><h4>{candidate.organization}</h4><span>{candidate.category.replaceAll('_', ' ')}</span></div>
        <p><strong>{candidate.person_name ?? 'Named person unknown'}</strong>{candidate.title ? ` · ${candidate.title}` : ' · Current title unknown'}</p>
        <p className="integrity">{candidate.person_name ? (relationshipLabels[candidate.person_project_relationship] ?? relationshipLabels.UNKNOWN) : candidate.organization_relationship === 'DIRECT' ? 'Organization involvement supported · named person unknown' : 'Organization involvement unknown'} · {candidate.evidence_strength} evidence</p>
        <p>{candidate.reason}</p>{candidate.stale && <p className="integrity">Historical title evidence · current role needs verification</p>}
        <dl className="buying-chain-relations"><div><dt>Project → organization</dt><dd>{candidate.organization_relationship === 'DIRECT' ? 'Direct involvement evidence' : 'Unknown'}</dd></div><div><dt>Organization → person</dt><dd>{candidate.person_organization_relationship === 'CURRENT' ? 'Current role supported' : 'Current role unknown'}</dd></div><div><dt>Person → project</dt><dd>{relationshipLabels[candidate.person_project_relationship] ?? relationshipLabels.UNKNOWN}</dd></div></dl>
        <p className="evidence-meta">Observed {time(candidate.observed_at)} · Verified {time(candidate.verified_at)} · {candidate.history_count ?? 1} retained claim version(s)</p>
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
