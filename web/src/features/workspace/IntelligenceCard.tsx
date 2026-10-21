import { useState } from 'react'
import { client, type Opportunity } from '../../api/client'
import './intelligence-card.css'

type Card = NonNullable<Opportunity['intelligence_card']>

export function IntelligenceCard({ card, onReadback, onReview }: {
  card: Card; onReadback: () => void; onReview: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  async function research() {
    setBusy(true); setMessage('')
    try {
      const result = await client.refreshAutonomousResearch(card.need_id, false, undefined, true)
      setMessage(result.items.length ? 'Targeted research queued. Results appear after the worker completes.' : 'No new work queued. Existing work, freshness and budget limits still apply.')
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Research request failed.') }
    finally { setBusy(false) }
  }
  const known = card.fields.filter(field => field.value !== null)
  const groups = [...new Set(card.research_gaps.map(field => field.research_category ?? 'other'))]
  return <section className="intelligence-card" aria-label="Commercial intelligence card">
    <header className="ic-heading"><div><p className="wh-kicker">Commercial intelligence</p><small>{card.last_intelligence_update ? `Evidence updated ${new Date(card.last_intelligence_update).toLocaleDateString()}` : 'Awaiting a retained evidence update'}</small></div><span>{card.completeness.supported} / {card.completeness.total} fields supported</span></header>
    <p className="ic-completeness">Research completeness is separate from {card.qualification} qualification.</p>
    {(['identity', 'power', 'commercial'] as const).map(section => {
      const fields = known.filter(field => field.section === section)
      return fields.length > 0 && <section key={section} aria-label={section === 'identity' ? 'Customer and project' : section === 'power' ? 'Power opportunity' : 'Commercial assessment'}>
        <h3>{section === 'identity' ? 'Customer & project' : section === 'power' ? 'Power opportunity' : 'Commercial assessment'}</h3>
        <dl className="ic-facts">{fields.map(field => <div key={field.key}><dt>{field.label}</dt><dd>{field.value}</dd><small>{field.status}</small><details><summary>Basis & sources</summary><p>{field.basis}</p>{(field.sources ?? []).map((source, index) => <div key={`${source.reference}-${index}`}><p>{source.url ? <a href={source.url} target="_blank" rel="noreferrer">{source.title}</a> : source.title}{source.source_date ? ` · ${source.source_date}` : ''}</p>{source.passage && <blockquote>{source.passage}</blockquote>}<small>{source.verification_status} · {source.reference}</small></div>)}</details></div>)}</dl>
      </section>
    })}
    {card.power_gap && <details><summary>Power-gap calculation and interval</summary><pre>{JSON.stringify(card.power_gap, null, 2)}</pre></details>}
    <section aria-label="Customer and buying chain"><h3>Customer & buying chain</h3>
      {card.contacts.map(person => <article className="ic-contact" key={person.claim_id}><strong>{person.name || person.company}</strong><p>{person.name ? `${person.title || person.role} · ${person.company}` : person.role}</p><small>{person.responsibility}. {person.purchasing_authority}.</small><div className="ic-contact-actions">{(person.methods ?? []).map(method => <a key={`${method.kind}:${method.value}`} href={method.href}>{method.kind === 'email' ? 'Email' : 'Call'} {method.value}</a>)}</div>{person.verified_at && <small>Verified {new Date(person.verified_at).toLocaleDateString()}</small>}<details><summary>Relationship evidence</summary>{(person.sources ?? []).map((source, index) => <p key={`${source.reference}-${index}`}><a href={source.url ?? undefined} target="_blank" rel="noreferrer">{source.passage || source.title}</a></p>)}</details></article>)}
      <p className="ic-contact-path">{card.next_contact_path}</p>
    </section>
    <section className="ic-next" aria-label="Intelligence next action"><h3>Next action</h3><p>{card.next_action}</p><button onClick={onReview}>Review or correct evidence</button></section>
    <section aria-label="Research gaps"><div className="ic-heading"><h3>Research gaps</h3><button disabled={busy || !card.research_enabled} onClick={() => void research()}>{busy ? 'Queuing…' : 'Research missing information'}</button></div>
      {!card.research_enabled && <p>Research execution is disabled. Existing evidence remains available.</p>}
      {groups.map(group => { const fields = card.research_gaps.filter(field => (field.research_category ?? 'other') === group); return <details key={group} className="ic-gap"><summary>{fields.map(field => field.label).join(' · ')} <small>{fields.some(field => field.status === 'Conflicting evidence') ? 'Conflicting evidence' : fields.some(field => ['QUEUED', 'SEARCHING', 'REVIEWING_EVIDENCE'].includes(field.research_status ?? '')) ? 'Research running' : 'Needs research'}</small></summary>{fields.map(field => <p key={field.key}><strong>{field.label}:</strong> {field.basis}</p>)}</details> })}
      {message && <div><p role="status">{message}</p><button onClick={onReadback}>Refresh research status</button></div>}
    </section>
    <details className="ic-evidence"><summary>Retained evidence ({card.evidence.length})</summary>{card.evidence.map(source => <article key={source.reference}><a href={source.url ?? undefined} target="_blank" rel="noreferrer">{source.title}</a><p>{source.source_date || 'Source date not established'}</p>{source.passage && <blockquote>{source.passage}</blockquote>}<small>{source.reference} · {source.extraction_method}</small></article>)}</details>
  </section>
}
