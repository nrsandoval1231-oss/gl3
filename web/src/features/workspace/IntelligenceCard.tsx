import type { Opportunity } from '../../api/client'
import './intelligence-card.css'

type Card = NonNullable<Opportunity['intelligence_card']>
type CardContact = Card['contacts'][number]
type ContactMethod = NonNullable<CardContact['methods']>[number]

function latestVerifiedMethod(methods: ContactMethod[]) {
  return methods
    .map(method => method.verified_at)
    .filter((value): value is string => Boolean(value) && !Number.isNaN(new Date(value as string).getTime()))
    .sort((left, right) => new Date(right).getTime() - new Date(left).getTime())[0] ?? null
}

function latestSourceCheck(contact: CardContact) {
  return (contact.sources ?? [])
    .map(source => source.assessed_at)
    .filter((value): value is string => Boolean(value) && !Number.isNaN(new Date(value as string).getTime()))
    .sort((left, right) => new Date(right).getTime() - new Date(left).getTime())[0] ?? null
}

function contactMethodLabel(contact: CardContact, method: ContactMethod) {
  const action = method.kind === 'email' ? 'Email' : 'Call'
  if (contact.name) return `${action} ${method.value}`
  const route = /owner/i.test(contact.role) ? 'owner company route' : 'company contact route'
  return `${action} ${contact.company} ${route} · ${method.value}`
}

export function IntelligenceCard({ card, opportunityName, customer, location, activity, tier, why, nextAction, onResearch }: {
  card: Card; opportunityName: string; customer: string | null | undefined; location: string | null | undefined; activity: string; tier: string; why: string; nextAction: string; onResearch: () => void
}) {
  const known = card.fields.filter(field => field.value !== null)
  const projectFields = known.filter(field => field.section === 'identity' || field.section === 'power')
  const commercialFields = known.filter(field => field.section === 'commercial')
  return <section className="intelligence-card" aria-label="Commercial intelligence card">
    <div className="ic-dashboard">
      <section className="ic-project" aria-label="Project and customer details">
        <h3>Project &amp; customer details</h3>
        <dl className="ic-detail-list"><div><dt>Project</dt><dd>{opportunityName}</dd></div>{customer && <div><dt>Customer / organization</dt><dd>{customer}</dd></div>}<div><dt>Location</dt><dd>{location ?? 'Location not established'}</dd></div><div><dt>Power activity</dt><dd>{activity}</dd></div><div><dt>Qualification tier</dt><dd>{tier}</dd></div></dl>
        {projectFields.length > 0 && <details className="ic-supported-fields"><summary>Supported power details ({projectFields.length})</summary><dl className="ic-detail-list">{projectFields.map(field => <div key={field.key}><dt>{field.label}</dt><dd>{field.value}<small>{field.status}</small><details><summary>Basis &amp; sources</summary><p>{field.basis}</p>{(field.sources ?? []).map((source, index) => <div key={`${source.reference}-${index}`}><p>{source.url ? <a href={source.url} target="_blank" rel="noreferrer">{source.title}</a> : source.title}{source.source_date ? ` · ${source.source_date}` : ''}</p>{source.passage && <blockquote>{source.passage}</blockquote>}<small>{source.verification_status} · {source.reference}</small></div>)}</details></dd></div>)}</dl></details>}
        {commercialFields.length > 0 && <details className="ic-commercial-facts"><summary>Commercial assessment details</summary><dl className="ic-detail-list">{commercialFields.map(field => <div key={field.key}><dt>{field.label}</dt><dd>{field.value}<small>{field.status}</small><details><summary>Basis &amp; sources</summary><p>{field.basis}</p>{(field.sources ?? []).map((source, index) => <p key={`${source.reference}-${index}`}><a href={source.url ?? undefined} target="_blank" rel="noreferrer">{source.title}</a> · {source.reference}</p>)}</details></dd></div>)}</dl></details>}
      </section>
      <section className="ic-contacts" aria-label="Key contacts and buying chain">
        <h3>Key contacts &amp; buying chain</h3>
        {card.contacts.length ? card.contacts.map(person => <article className="ic-contact" key={person.claim_id}><span className="ic-avatar" aria-hidden="true">{(person.name || person.company).split(/\s+/).filter(Boolean).slice(0, 2).map(word => word[0]).join('').toUpperCase()}</span><div className="ic-contact-identity"><span className="ic-role-badge">{person.role}</span><strong>{person.name || person.company}</strong><p>{person.name ? `${person.title || person.role} · ${person.company}` : person.role}</p></div><div className="ic-contact-actions">{(person.methods ?? []).map(method => <a key={`${method.kind}:${method.value}`} href={method.href}>{contactMethodLabel(person, method)}</a>)}</div><details><summary>Responsibility, authority &amp; evidence</summary><p>{person.responsibility}. {person.purchasing_authority}.</p>{(person.methods ?? []).length > 0 && latestVerifiedMethod(person.methods ?? []) && <p>Published method source checked {new Date(latestVerifiedMethod(person.methods ?? []) as string).toLocaleDateString()}</p>}{!(person.methods ?? []).length && latestSourceCheck(person) && <p>Role/source checked {new Date(latestSourceCheck(person) as string).toLocaleDateString()}</p>}{(person.sources ?? []).map((source, index) => <p key={`${source.reference}-${index}`}><a href={source.url ?? undefined} target="_blank" rel="noreferrer">{source.passage || source.title}</a>{source.source_date ? ` · ${source.source_date}` : ''}</p>)}</details></article>) : <p>No verified contacts are available in the current retained evidence.</p>}
        <p className="ic-contact-path">{card.next_contact_path || 'Contact path not established.'}</p>
      </section>
      <div className="ic-recommendations">
      <section className="ic-why" aria-label="Why this opportunity matters">
        <h3>Why this opportunity matters</h3>
        <p>{why}</p>
        {card.research_gaps.length > 0 && <p className="ic-gap-summary">{card.research_gaps.length} research {card.research_gaps.length === 1 ? 'gap' : 'gaps'} remain.</p>}
        {commercialFields.length > 0 && <ul className="ic-commercial-list">{commercialFields.slice(0, 3).map(field => <li key={field.key}>{field.label}: {field.value}</li>)}</ul>}
      </section>
      <section className="ic-next" aria-label="Recommended next action"><h3>Recommended next action</h3><p>{nextAction}</p><button onClick={onResearch}>View automated research</button></section>
      </div>
    </div>
  </section>
}
