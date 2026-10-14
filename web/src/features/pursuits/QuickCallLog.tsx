import { useState, type FormEvent } from 'react'
import { client, type CallFact, type Opportunity } from '../../api/client'

// One call, one form: a shared call header and only the facts that were actually said.
// Each filled section becomes an attributed draft through the normal fact API; nothing is
// accepted until the operator presses the explicit accept button.
type Section = 'demand' | 'timing' | 'buyer' | 'supply'

const nowLocal = () => {
  const now = new Date()
  now.setSeconds(0, 0)
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}

export function QuickCallLog({ item, onReadback }: { item: Opportunity; onReadback: () => void }) {
  const [contact, setContact] = useState({ name: '', organization: '', role: '', channel: 'phone', at: nowLocal() })
  const [values, setValues] = useState<Record<string, string>>({})
  const [drafts, setDrafts] = useState<CallFact[]>([])
  const [accepted, setAccepted] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const set = (key: string) => (event: { target: { value: string } }) => setValues((current) => ({ ...current, [key]: event.target.value }))
  const has = (...keys: string[]) => keys.some((key) => (values[key] ?? '').trim() !== '')

  function factsToDraft(): { section: Section; value: Record<string, unknown> }[] {
    const note = (values.quote ?? '').trim()
    const extra = note ? { source_quote: note } : {}
    const facts: { section: Section; value: Record<string, unknown> }[] = []
    if (has('mw')) facts.push({ section: 'demand', value: { mw: values.mw.trim(), ...extra } })
    if (has('start', 'end', 'duration')) {
      facts.push({ section: 'timing', value: {
        ...(has('start') ? { start_date: values.start } : {}),
        ...(has('end') ? { end_date: values.end } : {}),
        ...(has('duration') ? { duration_days: Number(values.duration) } : {}),
        ...extra,
      } })
    }
    if (has('buyer')) facts.push({ section: 'buyer', value: { organization: values.buyer.trim(), role: values.buyerRole ?? '', ...extra } })
    if (has('supply')) facts.push({ section: 'supply', value: { mw: values.supply.trim(), quality: values.supplyQuality || 'unknown', ...extra } })
    return facts
  }

  async function saveDrafts(event: FormEvent) {
    event.preventDefault()
    if (!item.project_id) return setError('No project identity is linked yet.')
    if (contact.name.trim().length < 2) return setError('Enter who you spoke with.')
    if (!item.location) return setError('This record has no facility location, so call facts cannot be attached to it.')
    const facts = factsToDraft()
    if (!facts.length) return setError('Fill in at least one thing they told you.')
    // Check what the fact API requires up front so a call is never half-saved by a predictable error.
    if (facts.some((fact) => fact.section === 'timing') && !(has('start') && has('end') && has('duration'))) {
      return setError('Timing needs the earliest start, latest start and duration together.')
    }
    if (has('start') && has('end') && values.start > values.end) return setError('Earliest start must be on or before latest start.')
    if (has('buyer') && !values.buyerRole) return setError('Choose the buyer role they reported.')
    setBusy(true); setError('')
    const saved: CallFact[] = []
    try {
      let version = (await client.callFacts(item.id)).current_fact_version
      for (const fact of facts) {
        const created = await client.createCallFact(item.id, {
          client_id: crypto.randomUUID(),
          project_id: item.project_id,
          pursuit_id: null,
          expected_version: version,
          predecessor_id: null,
          activity_key: item.activity,
          facility_scope: item.location,
          fact_type: fact.section === 'supply' ? 'suitable_supply' : fact.section,
          value: fact.value,
          reporter_name: contact.name.trim(),
          reporter_organization: contact.organization.trim() || null,
          reporter_role: contact.role.trim() || null,
          confirmation_channel: contact.channel.trim() || 'phone',
          source_reference: null,
          source_date: contact.at.slice(0, 10),
          confirmed_at: new Date(contact.at).toISOString(),
          effective_from: new Date(contact.at).toISOString(),
          effective_until: null,
        })
        saved.push(created)
        version = created.decision_version ?? version + 1
      }
    } catch (failure) {
      setError(`${saved.length} of ${facts.length} drafts saved before an error: ${failure instanceof Error ? failure.message : 'request failed'}. Saved drafts stay unaccepted in the history below.`)
    } finally {
      setDrafts(saved)
      setBusy(false)
      onReadback()
    }
  }

  async function acceptAll() {
    setBusy(true); setError('')
    let done = 0
    try {
      let version = (await client.callFacts(item.id)).current_fact_version
      for (const fact of drafts) {
        const decision = await client.decideCallFact(item.id, fact.id, {
          client_id: crypto.randomUUID(),
          expected_version: version,
          decision: 'accepted',
          reason: `Confirmed on a ${contact.channel || 'phone'} call with ${contact.name.trim()}.`,
        })
        version = decision.version
        done += 1
      }
      setAccepted(true)
    } catch (failure) {
      setError(`${done} of ${drafts.length} facts accepted before an error: ${failure instanceof Error ? failure.message : 'request failed'}. Review the rest in the history below.`)
    } finally {
      setBusy(false)
      onReadback()
    }
  }

  const describe = (fact: CallFact) => `${fact.fact_type.replaceAll('_', ' ')}: ${Object.entries(fact.value).filter(([key]) => key !== 'source_quote').map(([key, value]) => `${key.replaceAll('_', ' ')} ${String(value)}`).join(', ')}`

  return <section className="detail-section quick-call" aria-label="Log this call">
    <h3>Log this call</h3>
    {error && <p className="error" role="alert">{error}</p>}
    {drafts.length > 0 ? <>
      <p role="status">{accepted ? `${drafts.length} facts accepted. Tier re-evaluated from the accepted facts.` : `${drafts.length} drafts saved, not yet accepted. Review them, then accept.`}</p>
      <ul>{drafts.map((fact) => <li key={fact.id}>{describe(fact)}</li>)}</ul>
      {!accepted && <button type="button" disabled={busy} onClick={() => void acceptAll()}>Accept all {drafts.length} as confirmed by {contact.name.trim()}</button>}
    </> : <form onSubmit={(event) => void saveDrafts(event)}>
      <fieldset disabled={busy}>
        <legend>Who you spoke with</legend>
        <label>Name<input aria-label="Contact name" value={contact.name} onChange={(event) => setContact({ ...contact, name: event.target.value })}/></label>
        <label>Organization<input aria-label="Contact organization" value={contact.organization} onChange={(event) => setContact({ ...contact, organization: event.target.value })}/></label>
        <label>Role<input aria-label="Contact role" value={contact.role} onChange={(event) => setContact({ ...contact, role: event.target.value })}/></label>
        <label>Channel<input aria-label="Channel" value={contact.channel} onChange={(event) => setContact({ ...contact, channel: event.target.value })}/></label>
        <label>When<input aria-label="Call time" type="datetime-local" value={contact.at} onChange={(event) => setContact({ ...contact, at: event.target.value })}/></label>
      </fieldset>
      <fieldset disabled={busy}>
        <legend>What they told you · leave blank what wasn't said</legend>
        <label>Power needed (MW or range, e.g. 10 or 8-12)<input aria-label="Power needed" value={values.mw ?? ''} onChange={set('mw')}/></label>
        <label>Earliest start<input aria-label="Earliest start" type="date" value={values.start ?? ''} onChange={set('start')}/></label>
        <label>Latest start<input aria-label="Latest start" type="date" value={values.end ?? ''} onChange={set('end')}/></label>
        <label>Duration (days)<input aria-label="Duration days" type="number" min="1" value={values.duration ?? ''} onChange={set('duration')}/></label>
        <label>Buyer organization<input aria-label="Buyer organization" value={values.buyer ?? ''} onChange={set('buyer')}/></label>
        <label>Buyer role<select aria-label="Buyer role" value={values.buyerRole ?? ''} onChange={set('buyerRole')}><option value="">Choose a reported role</option><option value="project owner">Project owner</option><option value="electrical contractor">Electrical contractor</option><option value="general contractor">General contractor</option><option value="energy manager">Energy manager</option></select></label>
        <label>Supply they have (MW)<input aria-label="Supply MW" value={values.supply ?? ''} onChange={set('supply')}/></label>
        <label>Supply quality<select aria-label="Supply quality" value={values.supplyQuality ?? 'unknown'} onChange={set('supplyQuality')}><option value="unknown">Unknown</option><option value="suitable">Suitable</option><option value="unsuitable">Unsuitable</option></select></label>
        <label>What they said (quote or note)<textarea aria-label="Call note" value={values.quote ?? ''} onChange={set('quote')}/></label>
      </fieldset>
      <button type="submit" disabled={busy}>Save as drafts</button>
    </form>}
  </section>
}
