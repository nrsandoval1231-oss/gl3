import { type FormEvent } from 'react'
import { freshCallDraft, useCallDraft } from './callDrafts'
import { client, type CallFact, type Opportunity } from '../../api/client'

// One call, one form: a shared call header and only the facts that were actually said.
// Each filled section becomes an attributed draft through the normal fact API; nothing is
// accepted until the operator presses the explicit accept button.
type Section = 'demand' | 'timing' | 'buyer' | 'suitable_supply' | 'unsuitable_supply'

export function QuickCallLog({ item, onReadback }: { item: Opportunity; onReadback: () => void }) {
  const [draft, update] = useCallDraft(item.id)
  const { contact, values, drafts, accepted, busy, error } = draft
  const setContact = (contact: typeof draft.contact) => update({ contact })
  const setValues = (fn: (current: typeof values) => typeof values) => update({ values: fn(values) })
  const setDrafts = (drafts: CallFact[]) => update({ drafts })
  const setAccepted = (accepted: boolean) => update({ accepted })
  const setBusy = (busy: boolean) => update({ busy })
  const setError = (error: string) => update({ error })
  // Keys belong to the need draft, including after navigation or a lost response.
  const keyFor = (payload: unknown) => {
    const signature = JSON.stringify(payload)
    const known = draft.keys[signature]
    if (known) return known
    const fresh = crypto.randomUUID()
    draft.keys[signature] = fresh
    update({ keys: { ...draft.keys } })
    return fresh
  }
  const set = (key: string) => (event: { target: { value: string } }) => setValues((current) => ({ ...current, [key]: event.target.value }))
  const has = (...keys: string[]) => keys.some((key) => (values[key] ?? '').trim() !== '')
  const validMw = (value: string, allowZero: boolean) => {
    const match = /^\s*(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(kW|MW)?(?:\s*(?:-|–|to)\s*(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(kW|MW)?)?\s*$/i.exec(value)
    if (!match || value.trim().length > 128) return false
    const lowUnit = match[2] ?? match[4]
    const highUnit = match[4] ?? match[2]
    const low = Number(match[1].replaceAll(',', '')) * (lowUnit?.toLowerCase() === 'kw' ? 0.001 : 1)
    const high = Number((match[3] ?? match[1]).replaceAll(',', '')) * (highUnit?.toLowerCase() === 'kw' ? 0.001 : 1)
    return Number.isFinite(low) && Number.isFinite(high) && low >= (allowZero ? 0 : Number.MIN_VALUE) && high >= low && high <= 1_000_000
  }

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
    // Only an unsuitable_supply fact is shortage evidence for the qualification gate.
    if (has('supply')) {
      facts.push(values.supplyQuality === 'unsuitable'
        ? { section: 'unsuitable_supply', value: { mw: values.supply.trim(), ...extra } }
        : { section: 'suitable_supply', value: { mw: values.supply.trim(), quality: values.supplyQuality || 'unknown', ...extra } })
    }
    return facts
  }

  async function saveDrafts(event: FormEvent) {
    event.preventDefault()
    if (busy) return
    if (!item.project_id) return setError('No project identity is linked yet.')
    if (contact.name.trim().length < 2) return setError('Enter who you spoke with.')
    if (contact.name.trim().length > 160 || contact.organization.trim().length > 200 || contact.role.trim().length > 160 || contact.channel.trim().length < 2 || contact.channel.trim().length > 40) {
      return setError('Contact details exceed the supported field length.')
    }
    if (!item.location) return setError('This record has no facility location, so call facts cannot be attached to it.')
    if (item.location.trim().length < 2 || item.location.length > 500) return setError('Facility location must be 2 to 500 characters.')
    const facts = factsToDraft()
    if (!facts.length) return setError('Fill in at least one thing they told you.')
    if ((values.quote ?? '').trim().length > 2000) return setError('Call note must be 2000 characters or fewer.')
    if (!Number.isFinite(new Date(contact.at).getTime())) return setError('Call time must be a valid date and time.')
    // Check what the fact API requires up front so a call is never half-saved by a predictable error.
    if (facts.some((fact) => fact.section === 'timing') && !(has('start') && has('end') && has('duration'))) {
      return setError('Timing needs the earliest start, latest start and duration together.')
    }
    if (facts.some((fact) => fact.section === 'timing') && (![values.start, values.end].every((date) => /^\d{4}-\d{2}-\d{2}$/.test(date) && Number.isFinite(new Date(date).getTime()) && new Date(date).toISOString().slice(0, 10) === date))) {
      return setError('Timing needs valid calendar dates.')
    }
    if (has('duration') && (!/^\d+$/.test(values.duration.trim()) || !Number.isSafeInteger(Number(values.duration)) || Number(values.duration) < 1 || Number(values.duration) > 36500)) {
      return setError('Duration must be a whole number from 1 to 36500 days.')
    }
    if (has('start') && has('end') && values.start > values.end) return setError('Earliest start must be on or before latest start.')
    if (has('buyer') && values.buyer.trim().length < 2) return setError('Buyer organization needs at least 2 characters.')
    if (has('buyer') && !values.buyerRole) return setError('Choose the buyer role they reported.')
    if (has('mw') && !validMw(values.mw.trim(), false)) return setError('Power needed must be a positive MW value or supported range, up to 1000000 MW.')
    if (has('supply') && values.supplyQuality === 'unsuitable' && (!/^\s*\d+(\.\d+)?\s*$/.test(values.supply) || !validMw(values.supply.trim(), false))) {
      return setError('Unsuitable supply needs one positive MW number within the supported range.')
    }
    if (has('supply') && values.supplyQuality !== 'unsuitable' && !validMw(values.supply.trim(), true)) return setError('Suitable supply must be an MW value or supported range from 0 to 1000000 MW.')
    setBusy(true); setError('')
    const saved: CallFact[] = []
    try {
      for (const fact of facts) {
        const payload = {
          project_id: item.project_id,
          pursuit_id: null,
          predecessor_id: null,
          activity_key: item.activity,
          facility_scope: item.location,
          fact_type: fact.section,
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
        }
        // Read the current version per write; a replayed draft keeps its original version.
        const version = (await client.callFacts(item.id)).current_fact_version
        saved.push(await client.createCallFact(item.id, { ...payload, client_id: keyFor(payload), expected_version: version }))
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
    if (busy) return
    setBusy(true); setError('')
    let done = 0
    try {
      for (const fact of drafts) {
        const decision = { decision: 'accepted', reason: `Confirmed on a ${contact.channel || 'phone'} call with ${contact.name.trim()}.` }
        const version = (await client.callFacts(item.id)).current_fact_version
        await client.decideCallFact(item.id, fact.id, { ...decision, client_id: keyFor({ fact: fact.id, ...decision }), expected_version: version })
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
    <p role="status">{busy ? 'Saving…' : error ? 'Failed — review the message below.' : accepted ? 'Accepted facts' : drafts.length ? 'Saved draft — not accepted' : 'Unsaved — no facts accepted'}</p>
    <p>{draft.refreshSafe ? 'Input survives navigation and refresh in this tab for up to eight hours, within the session storage limit. Sign out clears it.' : 'Session storage is unavailable or full. Input survives this page’s navigation, but may be lost on refresh.'}</p>
    {error && <p className="error" role="alert">{error}</p>}
    {drafts.length > 0 ? <>
      <p role="status">{accepted ? `${drafts.length} facts accepted. Tier re-evaluated from the accepted facts.` : `${drafts.length} drafts saved, not yet accepted. Review them, then accept.`}</p>
      <ul>{drafts.map((fact) => <li key={fact.id}>{describe(fact)}</li>)}</ul>
      {!error && <><p>Saved facts stay in full fact history. Starting another call does not accept unaccepted drafts.</p><button type="button" disabled={busy} onClick={() => update(freshCallDraft())}>Start another call</button></>}
      {!accepted && <button type="button" disabled={busy} onClick={() => void acceptAll()}>Accept all {drafts.length} as confirmed by {contact.name.trim()}</button>}
      {error && !accepted && <button type="button" disabled={busy} onClick={(event) => void saveDrafts(event)}>Retry saving drafts</button>}
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
