import { useEffect, useState } from 'react'
import { client } from '../../api/client'
import { CompanyGraph } from './CompanyGraph'
import type { components } from '../../api/generated'

type Contacts = components['schemas']['CompanyContacts']
type Contact = NonNullable<Contacts['contacts']>[number]
type ContactMethod = NonNullable<Contact['methods']>[number]

function methodOrder(method: ContactMethod): number {
  const kind = method.kind?.toLowerCase()
  return kind === 'email' ? 0 : kind === 'phone' || kind === 'telephone' ? 1 : 2
}

function displayDate(value?: string | null) {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date.toLocaleDateString()
}

function latestSourceCheck(sources: NonNullable<Contact['sources']>) {
  const assessed = sources
    .map(source => source.assessed_at)
    .filter((value): value is string => Boolean(value) && !Number.isNaN(new Date(value as string).getTime()))
    .sort((left, right) => right.localeCompare(left))
  return assessed[0] ?? null
}

function latestMethodCheck(methods: ContactMethod[]) {
  return methods
    .map(method => method.verified_at)
    .filter((value): value is string => Boolean(value) && !Number.isNaN(new Date(value as string).getTime()))
    .sort((left, right) => new Date(right).getTime() - new Date(left).getTime())[0] ?? null
}

function orderedMethods(methods: ContactMethod[]) {
  return [...methods].sort((left, right) => {
    const sourceOrder = Number(!left.source_url) - Number(!right.source_url)
    if (sourceOrder) return sourceOrder
    const kindOrder = methodOrder(left) - methodOrder(right)
    if (kindOrder) return kindOrder
    return (right.verified_at ?? '').localeCompare(left.verified_at ?? '')
  })
}

function orderedContacts(contacts: Contact[]) {
  return contacts
    .map((contact, index) => ({ contact, index }))
    .sort((left, right) => {
      const leftHasMethod = (left.contact.methods ?? []).some(method =>
        ['email', 'phone', 'telephone'].includes(method.kind?.toLowerCase() ?? ''),
      )
      const rightHasMethod = (right.contact.methods ?? []).some(method =>
        ['email', 'phone', 'telephone'].includes(method.kind?.toLowerCase() ?? ''),
      )
      return Number(rightHasMethod) - Number(leftHasMethod) || left.index - right.index
    })
    .map(({ contact }) => contact)
}

function isContactPage(url?: string | null) {
  if (!url) return false
  try {
    return /(?:^|[\/_-])contacts?(?:[\/_-]|$)/i.test(new URL(url).pathname)
  } catch {
    return false
  }
}

export function CompanyContacts({ companyId }: { companyId: string }) {
  const [result, setResult] = useState<Contacts | null>(null)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setResult(null); setError('')
    client.companyContacts(companyId, controller.signal).then(value => {
      if (!controller.signal.aborted) setResult(value)
    }).catch(() => { if (!controller.signal.aborted) setError('Contact research is unavailable. Retry to verify current sources.') })
    return () => controller.abort()
  }, [companyId, retry])
  const current = result?.company_id === companyId ? result : null
  return <section aria-label="Contacts & Buying Chain">
    <h3>Contacts &amp; Buying Chain</h3>
    <CompanyGraph companyId={companyId}/>
    {error ? <p role="alert">{error} <button onClick={() => setRetry(value => value + 1)}>Retry contacts</button></p> : !current ? <p role="status">Checking retained contacts…</p> : <>
      {current.research_required && <p><strong>Research Required</strong> · {current.contacts?.length ? 'Review published company roles and company routes below; current employment, decision-maker status and purchasing authority are unconfirmed.' : 'No current verified company contact method is available.'}</p>}
      {orderedContacts(current.contacts ?? []).map(contact => <div key={contact.claim_id}>
        <strong>{contact.name ?? contact.company}</strong>{contact.title && <> · {contact.title}</>}
        {contact.name && <p>Affiliation: {contact.company}</p>}
        <p>{contact.role} · {contact.responsibility}.</p>
        <p>{contact.methods?.length ? contact.purchasing_authority : 'No usable email or phone is verified.'} Purchasing authority remains unconfirmed.</p>
        {(contact.methods ?? []).length > 0 && orderedMethods(contact.methods ?? []).map(method => <p key={`${method.kind}-${method.href}`}><a href={method.href}>{method.value}</a>{method.source_url && <> · <a href={method.source_url} target="_blank" rel="noreferrer">Open source</a>{isContactPage(method.source_url) && <> · <a href={method.source_url} target="_blank" rel="noreferrer">Open contact page</a></>}</>}{displayDate(method.verified_at) && <> · Source checked {displayDate(method.verified_at)}</>}</p>)}
        {(contact.sources ?? []).map((source, index) => <p key={JSON.stringify([source.reference, source.url, source.passage, index])}>{source.url && <a href={source.url} target="_blank" rel="noreferrer">Contact evidence</a>}{source.source_date && <> · Source date {displayDate(source.source_date) ?? source.source_date}</>}</p>)}
        {(contact.methods ?? []).length > 0 && displayDate(latestMethodCheck(contact.methods ?? [])) && <p>Last source check {displayDate(latestMethodCheck(contact.methods ?? []))}</p>}
        {!(contact.methods ?? []).length && displayDate(latestSourceCheck(contact.sources ?? [])) && <p>Role/source checked {displayDate(latestSourceCheck(contact.sources ?? []))}</p>}
        <small>{contact.assertion_status ?? contact.verification_status}{contact.mailbox_verified ? ' · Mailbox independently verified' : ' · Mailbox not independently verified'}{contact.verification_basis ? ` · ${contact.verification_basis}` : ''}</small>
      </div>)}
      {(current.imported_unverified ?? []).length > 0 && <section aria-label="Imported unverified contacts"><h4>Imported contacts · unverified</h4><p>Imported assertions have not been verified. Treat all details below as reference data, not outreach routes.</p>{current.imported_unverified?.map(contact => <article key={contact.import_row_id}>
        <strong>{contact.name ?? 'Name not provided'}</strong>{contact.title && <> · {contact.title}</>}
        {contact.company && <p>Company: {contact.company}</p>}
        {contact.email && <p>Email (unverified): <span>{contact.email}</span></p>}
        {contact.phone && <p>Phone (unverified): <span>{contact.phone}</span></p>}
        {contact.profile_url && <p>Profile URL (unverified): <span>{contact.profile_url}</span></p>}
        <small>{contact.assertion_status} · {contact.sheet}, row {contact.row_number} · Import {contact.batch_id}</small>
      </article>)}</section>}
    </>}
  </section>
}

export function PublishedCompanyRoles({ companyId }: { companyId: string }) {
  const [result, setResult] = useState<Contacts | null>(null)
  useEffect(() => {
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(companyId)) {
      setResult(null)
      return
    }
    const controller = new AbortController()
    setResult(null)
    client.companyContacts(companyId, controller.signal).then(value => {
      if (!controller.signal.aborted) setResult(value)
    }).catch(() => { if (!controller.signal.aborted) setResult(null) })
    return () => controller.abort()
  }, [companyId])

  useEffect(() => {
    const roles = result?.published_company_roles ?? []
    if (!roles.length) return
    let timer: ReturnType<typeof setTimeout>
    const checkExpiry = () => {
      const expiry = Math.min(...roles.map(role => Date.parse(role.valid_until)))
      const remaining = expiry - Date.now()
      if (!Number.isFinite(expiry) || remaining <= 0) {
        setResult(null)
        return
      }
      timer = setTimeout(checkExpiry, Math.min(remaining, 2_147_000_000))
    }
    checkExpiry()
    return () => clearTimeout(timer)
  }, [result?.published_company_roles])

  const roles = result?.company_id === companyId
    ? (result.published_company_roles ?? []).filter(role => Date.parse(role.valid_until) > Date.now())
    : []
  if (!roles.length) return null
  return <section aria-label="Published company roles">
    <h3>Published company roles</h3>
    <p>These roles appeared on a company roster. Current employment and project involvement are unverified.</p>
    {roles.map(contact => <article key={`${contact.name}:${contact.title}:${contact.source_hash}`}>
      <strong>{contact.name}</strong> · {contact.title}
      <p>{contact.role.replaceAll('_', ' ')} · Published company role; project involvement unverified.</p>
      <blockquote>{contact.source_quote}</blockquote>
      {(() => {
        let url: string | undefined
        try {
          const parsed = new URL(contact.source_url)
          if (parsed.protocol === 'https:' || parsed.protocol === 'http:') url = parsed.href
        } catch { /* Invalid source URLs are not linked. */ }
        return url ? <p><a href={url} target="_blank" rel="noreferrer">Open source roster</a> · Observed {displayDate(contact.observed_at) ?? contact.observed_at}</p> : null
      })()}
      <small>No personal email or phone is verified. Purchasing authority and project assignment are unconfirmed.</small>
    </article>)}
  </section>
}
