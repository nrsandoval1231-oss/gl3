import { useEffect, useRef, useState } from 'react'
import { client, type BuyingChainCorrectionBody, type BuyingChainResult } from '../../api/client'

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

function CorrectionControls({ projectId, candidate, onSaved, onReadback }: {
  projectId: string
  candidate: NonNullable<BuyingChainResult['candidates']>[number]
  onSaved: (result: BuyingChainResult) => void
  onReadback: () => void
}) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [reported, setReported] = useState(false)
  const [kind, setKind] = useState('phone')
  const [value, setValue] = useState('')
  const [reason, setReason] = useState('')
  const [sourceId, setSourceId] = useState('')
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [pending, setPending] = useState<BuyingChainCorrectionBody | null>(null)
  const currentVersion = candidate.correction_version ?? candidate.fingerprint
  const publicSources = (candidate.evidence ?? []).filter((evidence) => evidence.supports === 'public_contact')

  async function save(action: 'correct' | 'retract') {
    if (busy || !currentVersion) return
    setBusy(true); setError(''); setNotice('')
    try {
      let body = pending
      if (!body) {
        if (!reason.trim()) throw new Error('Enter a reason for this contact decision.')
        const selected = publicSources.find((source) => source.id === sourceId)
        if (action === 'correct' && !reported && !selected) throw new Error('Choose current public-contact evidence, or mark this as an operator-reported contact.')
        if (action === 'correct' && !value.trim()) throw new Error('Enter the contact value to record.')
        body = {
          expected_version: currentVersion,
          idempotency_key: crypto.randomUUID(),
          action,
          values: action === 'correct' ? { public_contact_kind: kind, public_contact_value: value.trim() } : {},
          ...(action === 'correct' && !reported && selected ? { source_evidence_id: selected.id, source_hash: selected.content_hash } : {}),
          reason: reason.trim(),
          reported_contact: action === 'correct' && reported,
        }
        setPending(body)
      }
      const saved = await client.correctBuyingChain(projectId, candidate.id, body)
      const readback = checkedResult(await client.buyingChain(projectId, undefined, true), projectId)
      const current = readback.candidates?.find((item) => item.id === candidate.id)
      const confirmed = current?.correction_history?.some((entry) => entry.id === saved.id)
      if (!current || !confirmed || current.correction_version !== saved.version || (action === 'retract' && !current.retracted)) {
        throw new Error('The saved correction could not be confirmed in this project’s claim history. Its request is preserved; reload history before retrying.')
      }
      onSaved(readback)
      onReadback?.()
      setPending(null); setValue(''); setReason(''); setNotice(action === 'retract' ? 'Claim retraction confirmed in project history.' : reported ? 'Operator-reported contact saved separately; it has no public call or email action.' : 'Contact correction confirmed against current public evidence.')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Contact correction failed. Reload project history before retrying.')
    } finally { setBusy(false) }
  }

  return <section className="buying-chain-correction" aria-label={`Contact correction for ${candidate.organization}`}>
    {candidate.correction_stale && <p className="integrity">The cited source version changed. Review current evidence before correcting or retracting.</p>}
    <button type="button" disabled={busy || candidate.stale || candidate.correction_stale || !currentVersion} onClick={() => setOpen((value) => !value)}>{open ? 'Close contact review' : 'Correct or retract contact'}</button>
    {open && <div>
      <label>Contact type<select value={kind} disabled={busy || Boolean(pending)} onChange={(event) => setKind(event.target.value)}><option value="phone">Phone</option><option value="email">Email</option><option value="profile">Profile</option><option value="website">Website</option><option value="general">General contact</option></select></label>
      <label>Corrected contact value<input value={value} disabled={busy || Boolean(pending)} onChange={(event) => setValue(event.target.value)}/></label>
      {!reported && <label>Current public-contact evidence<select value={sourceId} disabled={busy || Boolean(pending)} onChange={(event) => setSourceId(event.target.value)}><option value="">Choose cited evidence</option>{publicSources.map((source) => <option key={source.id} value={source.id}>{source.url} · {source.extraction_location}</option>)}</select></label>}
      <label><input type="checkbox" checked={reported} disabled={busy || Boolean(pending)} onChange={(event) => setReported(event.target.checked)}/> Operator-reported contact; not a verified public method</label>
      <label>Reason<textarea value={reason} disabled={busy || Boolean(pending)} onChange={(event) => setReason(event.target.value)}/></label>
      {pending && <p role="status">This correction request is unconfirmed. Retry sends the same idempotency key and values.</p>}
      {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
      <button type="button" disabled={busy} onClick={() => void save('correct')}>{busy ? 'Saving…' : pending ? 'Retry same correction' : 'Save contact correction'}</button>
      {pending && <button type="button" disabled={busy} onClick={() => setPending(null)}>Discard unconfirmed request</button>}
      <button type="button" disabled={busy || Boolean(pending) || !reason.trim()} onClick={() => void save('retract')}>Retract this project relationship</button>
      {(candidate.correction_history ?? []).length > 0 && <details><summary>Correction history ({candidate.correction_history?.length})</summary><ol>{candidate.correction_history?.map((entry, index) => <li key={String(entry.id ?? index)}>{String(entry.action ?? 'decision')} · {String(entry.reason ?? 'Reason not recorded')} · {String(entry.created_at ?? 'Date unknown')}</li>)}</ol></details>}
    </div>}
  </section>
}

export function BuyingChain({ projectId, onReadback = () => {} }: { projectId: string; onReadback?: () => void }) {
  const [result, setResult] = useState<BuyingChainResult | null>(null)
  const [showHistory, setShowHistory] = useState(false)
  const [loading, setLoading] = useState(true)
  const [enriching, setEnriching] = useState(false)
  const [error, setError] = useState('')
  const [sourceUrls, setSourceUrls] = useState('')
  const active = useRef(true)
  const pending = useRef(false)
  const activeProjectId = useRef(projectId)
  const requestSequence = useRef(0)

  useEffect(() => {
    const sequence = ++requestSequence.current
    activeProjectId.current = projectId
    active.current = true
    const controller = new AbortController()
    client.buyingChain(projectId, controller.signal, showHistory)
      .then((data) => { if (active.current && requestSequence.current === sequence && activeProjectId.current === projectId && !controller.signal.aborted) setResult(checkedResult(data, projectId)) })
      .catch((cause: unknown) => {
        if (active.current && requestSequence.current === sequence && activeProjectId.current === projectId && !controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Buying chain could not be loaded.')
      })
      .finally(() => { if (active.current && requestSequence.current === sequence && activeProjectId.current === projectId && !controller.signal.aborted) setLoading(false) })
    return () => { if (requestSequence.current === sequence) requestSequence.current += 1; controller.abort() }
  }, [projectId, showHistory])

  useEffect(() => {
    const status = result?.research_job?.status
    if (status !== 'queued' && status !== 'running') return
    const controller = new AbortController()
    const timer = setInterval(() => {
      const sequence = requestSequence.current
      client.buyingChain(projectId, controller.signal, showHistory)
        .then((data) => { if (active.current && requestSequence.current === sequence && activeProjectId.current === projectId && !controller.signal.aborted) setResult(checkedResult(data, projectId)) })
        .catch(() => undefined)
    }, 1500)
    return () => { clearInterval(timer); controller.abort() }
  }, [projectId, showHistory, result?.research_job?.id, result?.research_job?.status])

  function acceptCorrection(data: BuyingChainResult) {
    if (activeProjectId.current !== projectId || data.project_id !== projectId) return
    setResult(data)
    setShowHistory(true)
  }

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
    const controller = new AbortController()
    try {
      const data = await client.enrichBuyingChain(projectId, urls, controller.signal)
      if (active.current) setResult(checkedResult(data, projectId))
    } catch (cause: unknown) {
      if (active.current) setError(cause instanceof Error ? cause.message : 'Buying chain could not be enriched. Retained evidence is unchanged.')
    } finally {
      pending.current = false
      if (active.current) setEnriching(false)
    }
  }

  return <section className="detail-section buying-chain" aria-labelledby="buying-chain-heading" data-context-loading={loading}>
    <div className="evidence-heading"><div><p className="eyebrow">Project-specific relationships</p><h3 id="buying-chain-heading">Buying chain</h3></div><button disabled={loading || enriching} onClick={enrich}>{enriching ? 'Checking evidence…' : 'Enrich buying chain'}</button></div>
    <button type="button" disabled={loading} onClick={() => { setLoading(true); setShowHistory((value) => !value) }}>{showHistory ? 'Hide claim history' : 'Review claim and correction history'}</button>
    <p className="buying-chain-note">Organization involvement, current job role, and a person’s assignment to this project are separate claims. A relevant role does not establish purchasing authority or an open temporary-power package.</p>
    <details className="buying-chain-sources"><summary>Add supporting source links</summary><label>Public project or organization sources (up to four)<textarea value={sourceUrls} onChange={(event) => setSourceUrls(event.target.value)} rows={3} placeholder="https://…" disabled={enriching}/></label><p>Existing project evidence is checked first. Links should support this project’s contractors or their current team.</p></details>
    {loading && <p role="status">Loading buying chain…</p>}
    {(enriching || result?.research_job?.status === 'queued' || result?.research_job?.status === 'running') && <p role="status">Buying-chain research {result?.research_job?.status ?? 'queued'}. You can leave this view and return later.</p>}
    {result?.research_job?.detail_status === 'disabled' && <p className="buying-chain-note">Public research is disabled. Retained project evidence remains available.</p>}
    {result?.research_job?.detail_status === 'blocked_source_policy' && <p className="buying-chain-note">Public research was blocked because this project’s source policy is disabled. Retained project evidence remains available.</p>}
    {result?.research_job?.detail_status === 'stale' && <p className="buying-chain-note">Project evidence changed while research was running, so this result was discarded. Enrich again to check the current project.</p>}
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
        <p className="evidence-meta">Observed {time(candidate.observed_at)} · Verified {time(candidate.verified_at)} · {candidate.history_count ?? 1} retained claim version(s)</p>
        {(candidate.public_contacts ?? []).length === 0 && <p className="buying-chain-note">Public business contact details unknown</p>}
        {(candidate.public_contacts ?? []).map((contact, index) => <p key={index}>{contact.kind}: {contact.value} <a href={safeUrl(contact.source_url)} target="_blank" rel="noreferrer">Contact source</a></p>)}
        {(candidate.reported_contacts ?? []).map((contact, index) => <p key={`reported-${index}`} className="integrity">Operator-reported contact: {String(contact.value ?? 'Value not recorded')} · not a verified public call or email method.</p>)}
        {!candidate.retracted && <CorrectionControls projectId={projectId} candidate={candidate} onSaved={acceptCorrection} onReadback={onReadback}/>}
        <details><summary>Inspect relationship evidence ({(candidate.evidence ?? []).length})</summary>{(candidate.evidence ?? []).map((evidence, index) => <div className="evidence" key={index}><a href={safeUrl(evidence.url)} target="_blank" rel="noreferrer">{evidence.supports.replaceAll("_", " ")} · {evidence.extraction_location}</a><blockquote>{evidence.quote}</blockquote><p className="evidence-meta">Published {evidence.published_at ?? 'Unknown'} · Observed {time(evidence.observed_at)}</p></div>)}</details>
      </li>)}</ol>
      {(result.unresolved ?? []).length > 0 && <details open={(result.candidates ?? []).length === 0}><summary>Unresolved questions ({(result.unresolved ?? []).length})</summary><ul>{(result.unresolved ?? []).map((question, index) => <li key={index}>{question}</li>)}</ul></details>}
      {(result.runs ?? []).length > 0 && <details><summary>Research history ({(result.runs ?? []).length})</summary><ul>{(result.runs ?? []).map((run) => <li key={run.id}>{time(run.created_at)} · {run.status.replaceAll("_", " ")} · {run.documents_checked} documents checked · {run.candidates_added} new claim versions{run.unresolved.length > 0 && <ul>{run.unresolved.map((question, questionIndex) => <li key={questionIndex}>{question}</li>)}</ul>}</li>)}</ul></details>}
      <p className="buying-chain-note"><a href={`/api/projects/${encodeURIComponent(projectId)}/buying-chain?history=true`} target="_blank" rel="noreferrer">Inspect retained claim history</a></p>
    </>}
  </section>
}
