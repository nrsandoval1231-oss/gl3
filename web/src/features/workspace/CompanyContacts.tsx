import { useEffect, useState } from 'react'
import { client } from '../../api/client'
import type { components } from '../../api/generated'

type Contacts = components['schemas']['CompanyContacts']

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
      {current.research_required && <p><strong>Research Required</strong> · {current.contacts?.length ? 'Company contact available; a relevant named buyer still needs confirmation.' : 'No current verified company contact method is available.'}</p>}
      {(current.contacts ?? []).map(contact => <div key={contact.claim_id}>
        <strong>{contact.name ?? contact.company}</strong>{contact.title && <> · {contact.title}</>}
        <p>{contact.role} · {contact.responsibility}. {contact.purchasing_authority}.</p>
        {(contact.methods ?? []).map(method => <p key={`${method.kind}-${method.href}`}><a href={method.href}>{method.value}</a> · <a href={method.source_url} target="_blank" rel="noreferrer">Verify source</a>{method.verified_at && <> · Observed {new Date(method.verified_at).toLocaleDateString()}</>}</p>)}
        <small>{contact.verification_status}</small>
      </div>)}
    </>}
  </section>
}
