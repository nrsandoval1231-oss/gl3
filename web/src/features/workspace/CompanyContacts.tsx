import { useEffect, useState } from 'react'
import { client } from '../../api/client'
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
    {error ? <p role="alert">{error} <button onClick={() => setRetry(value => value + 1)}>Retry contacts</button></p> : !current ? <p role="status">Checking retained contacts…</p> : <>
      {current.research_required && <p><strong>Research Required</strong> · {current.contacts?.length ? 'Review the verified people and company routes below; decision-maker status and purchasing authority are unconfirmed.' : 'No current verified company contact method is available.'}</p>}
      {orderedContacts(current.contacts ?? []).map(contact => <div key={contact.claim_id}>
        <strong>{contact.name ?? contact.company}</strong>{contact.title && <> · {contact.title}</>}
        {contact.name && <p>Affiliation: {contact.company}</p>}
        <p>{contact.role} · {contact.responsibility}.</p>
        <p>{contact.methods?.length ? contact.purchasing_authority : 'No usable email or phone is verified.'} Purchasing authority remains unconfirmed.</p>
        {(contact.methods ?? []).length > 0 && orderedMethods(contact.methods ?? []).map(method => <p key={`${method.kind}-${method.href}`}><a href={method.href}>{method.value}</a>{method.source_url && <> · <a href={method.source_url} target="_blank" rel="noreferrer">Verify source</a>{isContactPage(method.source_url) && <> · <a href={method.source_url} target="_blank" rel="noreferrer">Open contact page</a></>}</>}{displayDate(method.verified_at) && <> · Verified {displayDate(method.verified_at)}</>}</p>)}
        {(contact.sources ?? []).map((source, index) => <p key={JSON.stringify([source.reference, source.url, source.passage, index])}>{source.url && <a href={source.url} target="_blank" rel="noreferrer">Contact evidence</a>}{source.source_date && <> · Source date {displayDate(source.source_date) ?? source.source_date}</>}</p>)}
        {displayDate(contact.verified_at) && <p>Last verified {displayDate(contact.verified_at)}</p>}
        {!contact.verified_at && displayDate(latestSourceCheck(contact.sources ?? [])) && <p>Role/source checked {displayDate(latestSourceCheck(contact.sources ?? []))}</p>}
        <small>{contact.verification_status}</small>
      </div>)}
    </>}
  </section>
}
