import { type FormEvent, useCallback, useEffect, useRef, useState } from 'react'
import {
  client,
  workflowStatuses,
  type CallFact,
  type CallFactPage,
  type NeedWorkflowStatus,
  type Opportunity,
  type TimingCorrectionTarget,
  type WorkflowStatus,
} from '../../api/client'

type FactType = 'demand' | 'unsuitable_supply' | 'suitable_supply' | 'timing' | 'buyer' | 'closure'
type FrozenWorkflowRequest = {
  needId: string
  projectId: string
  pursuitId: null
  clientId: string
  expectedVersion: number
  status: WorkflowStatus
  reason: string
}
type CorrectionBinding = Pick<TimingCorrectionTarget, 'need_id' | 'project_id' | 'project_identity_key' | 'activity_key' | 'facility_identity' | 'source_id' | 'source_semantic_hash' | 'source_evidence_hash' | 'retained_evidence_id' | 'earliest_possible_start' | 'latest_possible_start' | 'minimum_duration_days' | 'maximum_duration_days' | 'current_fact_version'>
type EditorDraft = {
  factType: FactType
  facilityScope: string
  reporterName: string
  reporterOrganization: string
  reporterRole: string
  channel: string
  sourceReference: string
  sourceDate: string
  confirmedAt: string
  effectiveFrom: string
  effectiveUntil: string
  fields: Record<string, string>
  correctsReportedTiming: boolean
  timingBasis: string
  predecessorId: string
  decisionReason: string
  factClientId: string
  decisionClientId: string
  pendingFactId: string
  workflowSelection: WorkflowStatus | ''
  workflowReason: string
  workflowClientId: string
  workflowRequest: FrozenWorkflowRequest | null
  timingBinding: CorrectionBinding | null
}

const draftByNeed = new Map<string, EditorDraft>()

function localDateTime(value = new Date()) {
  const local = new Date(value.getTime() - value.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}

function newDraft(facilityScope: string): EditorDraft {
  const now = localDateTime()
  return {
    factType: 'demand', facilityScope, reporterName: '', reporterOrganization: '', reporterRole: '',
    channel: 'phone', sourceReference: '', sourceDate: '', confirmedAt: now, effectiveFrom: now,
    effectiveUntil: '', fields: { mw: '', mw_min: '', mw_max: '', quality: 'unknown', start_date: '', end_date: '',
      duration_days: '', organization: '', role: '', state: '' },
    correctsReportedTiming: false, timingBasis: '', predecessorId: '', decisionReason: '',
    factClientId: crypto.randomUUID(), decisionClientId: crypto.randomUUID(), pendingFactId: '',
    workflowSelection: '', workflowReason: '', workflowClientId: crypto.randomUUID(), workflowRequest: null, timingBinding: null,
  }
}

function workflowEventMatchesRequest(
  event: NeedWorkflowStatus['events'][number],
  request: FrozenWorkflowRequest,
) {
  return event.need_id === request.needId
    && event.project_id === request.projectId
    && event.pursuit_id === request.pursuitId
    && event.status === request.status
    && event.reason === request.reason
    && event.expected_version === request.expectedVersion
}

function targetBinding(target: TimingCorrectionTarget, version: number): CorrectionBinding | null {
  if (!target.available || !target.source_semantic_hash || !target.source_evidence_hash || !target.retained_evidence_id) return null
  return {
    need_id: target.need_id,
    project_id: target.project_id,
    project_identity_key: target.project_identity_key,
    activity_key: target.activity_key,
    facility_identity: target.facility_identity,
    source_id: target.source_id,
    source_semantic_hash: target.source_semantic_hash,
    source_evidence_hash: target.source_evidence_hash,
    retained_evidence_id: target.retained_evidence_id,
    earliest_possible_start: target.earliest_possible_start,
    latest_possible_start: target.latest_possible_start,
    minimum_duration_days: target.minimum_duration_days,
    maximum_duration_days: target.maximum_duration_days,
    current_fact_version: version,
  }
}

function sameTargetSource(left: CorrectionBinding | null, right: CorrectionBinding | null) {
  return Boolean(left && right
    && left.need_id === right.need_id
    && left.project_id === right.project_id
    && left.project_identity_key === right.project_identity_key
    && left.activity_key === right.activity_key
    && left.facility_identity === right.facility_identity
    && left.source_id === right.source_id
    && left.source_semantic_hash === right.source_semantic_hash
    && left.source_evidence_hash === right.source_evidence_hash
    && left.retained_evidence_id === right.retained_evidence_id
    && left.earliest_possible_start === right.earliest_possible_start
    && left.latest_possible_start === right.latest_possible_start
    && left.minimum_duration_days === right.minimum_duration_days
    && left.maximum_duration_days === right.maximum_duration_days)
}

function sameTarget(left: CorrectionBinding | null, page: CallFactPage) {
  const right = targetBinding(page.current_reported_timing_correction_target, page.current_fact_version)
  return Boolean(sameTargetSource(left, right) && left?.current_fact_version === right?.current_fact_version)
}

function sameTimingCorrectionPayload(expected: Record<string, unknown>, actual: Record<string, unknown>) {
  const required = ['start_date', 'end_date', 'duration_days', 'corrects_source_semantic_hash', 'corrects_source_evidence_hash', 'basis']
  return required.every((key) => Object.hasOwn(expected, key) && actual[key] === expected[key])
}

function isoDateTime(value: string) {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) throw new Error('Enter a valid date and time.')
  return parsed.toISOString()
}

function statusError(cause: unknown) {
  return cause instanceof Error ? cause.message : 'The exact-Need request could not be confirmed.'
}

function factSummary(fact: CallFact) {
  const value = fact.value
  const range = value.mw_min != null && value.mw_max != null
    ? `${value.mw_min}–${value.mw_max} MW`
    : value.mw != null ? `${value.mw} MW` : 'amount not recorded'
  if (fact.fact_type === 'demand') return `Reported activity demand: ${range}.`
  if (fact.fact_type === 'suitable_supply') return `Suitable supply reported: ${range}; quality ${String(value.quality ?? 'unknown')}.`
  if (fact.fact_type === 'unsuitable_supply') return `Unsuitable supply reported: ${range}.`
  if (fact.fact_type === 'timing') return `Possible start: ${String(value.start_date ?? 'unknown')} to ${String(value.end_date ?? 'unknown')}; activity duration ${String(value.duration_days ?? 'unknown')} days.${value.basis ? ` Reason: ${String(value.basis)}` : ''}`
  if (fact.fact_type === 'buyer') return `Buyer: ${String(value.organization ?? 'not recorded')}; role ${String(value.role ?? 'not recorded')}.`
  if (fact.fact_type === 'closure') return `Reported closure state: ${String(value.state ?? 'unknown')}.${value.basis ? ` Reason: ${String(value.basis)}` : ''}`
  return 'Fact details are unavailable.'
}

function timingUnavailableReason(reason: string | null | undefined) {
  if (reason === 'no_current_admitted_lead') return 'A current, replayable source-supported Lead is unavailable.'
  if (reason === 'conflicting_source_facts') return 'Current source facts conflict; resolve the conflict before correcting timing.'
  return reason ? 'A current reported timing target is unavailable.' : 'The current source target is still loading.'
}

export function FactWorkflowPanel({ item, onReadback }: { item: Opportunity; onReadback: () => void }) {
  const needId = item.id
  const [draft, setDraft] = useState<EditorDraft>(() => draftByNeed.get(needId) ?? newDraft(item.location ?? item.name))
  const [page, setPage] = useState<CallFactPage | null>(null)
  const [workflow, setWorkflow] = useState<NeedWorkflowStatus | null>(null)
  const [historyOffset, setHistoryOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const activeNeedId = useRef(needId)
  const loadSequence = useRef(0)

  const storeDraft = useCallback((next: EditorDraft) => {
    draftByNeed.set(needId, next)
    setDraft(next)
  }, [needId])

  const reload = useCallback(async (offset = 0) => {
    const sequence = ++loadSequence.current
    const controller = new AbortController()
    setLoading(true)
    try {
      const [facts, currentWorkflow] = await Promise.all([
        client.callFacts(needId, 50, offset, controller.signal),
        client.workflowStatus(needId, controller.signal),
      ])
      if (sequence !== loadSequence.current || activeNeedId.current !== needId) return null
      setPage(facts)
      setWorkflow(currentWorkflow)
      setHistoryOffset(offset)
      return { facts, workflow: currentWorkflow }
    } catch (cause) {
      if (sequence === loadSequence.current && activeNeedId.current === needId) setError(statusError(cause))
      return null
    } finally {
      if (sequence === loadSequence.current && activeNeedId.current === needId) setLoading(false)
    }
  }, [needId])

  useEffect(() => {
    activeNeedId.current = needId
    setDraft(draftByNeed.get(needId) ?? newDraft(item.location ?? item.name))
    setPage(null)
    setWorkflow(null)
    setHistoryOffset(0)
    setError('')
    void reload(0)
    return () => { loadSequence.current += 1 }
  }, [needId, item.location, item.name, reload])

  function updateDraft(patch: Partial<EditorDraft>, factContentChanged = false, statusContentChanged = false) {
    const next = {
      ...draft,
      ...patch,
      ...(factContentChanged && !draft.pendingFactId ? { factClientId: crypto.randomUUID(), decisionClientId: crypto.randomUUID() } : {}),
      ...(statusContentChanged ? { workflowClientId: crypto.randomUUID() } : {}),
    }
    storeDraft(next)
  }

  function updateField(name: string, value: string) {
    updateDraft({ fields: { ...draft.fields, [name]: value } }, true)
  }

  function currentPageForSubmit(): CallFactPage | null {
    if (!page || page.current_fact_version < 0) return null
    return page
  }

  async function readFreshPage(): Promise<CallFactPage | null> {
    try {
      const fresh = await client.callFacts(needId)
      if (activeNeedId.current === needId) setPage(fresh)
      return fresh
    } catch (cause) {
      setError(statusError(cause))
      return null
    }
  }

  function valueForDraft(target: TimingCorrectionTarget): Record<string, unknown> {
    const value: Record<string, unknown> = {}
    const add = (key: string) => {
      const clean = draft.fields[key]?.trim()
      if (clean) value[key] = clean
    }
    if (draft.factType === 'demand' || draft.factType === 'unsuitable_supply') {
      add('mw')
    } else if (draft.factType === 'suitable_supply') {
      add('mw'); add('mw_min'); add('mw_max'); add('quality')
    } else if (draft.factType === 'timing') {
      add('start_date'); add('end_date')
      if (draft.fields.duration_days.trim()) value.duration_days = Number(draft.fields.duration_days)
      if (draft.correctsReportedTiming) {
        if (!sameTarget(draft.timingBinding, page as CallFactPage)) throw new Error('The selected source timing changed. Review the current source target and explicitly reselect it before saving.')
        if (!draft.timingBasis.trim()) throw new Error('Enter a nonempty reason for correcting reported timing.')
        value.corrects_source_semantic_hash = target.source_semantic_hash
        value.corrects_source_evidence_hash = target.source_evidence_hash
        value.basis = draft.timingBasis.trim()
      }
    } else if (draft.factType === 'buyer') {
      if (!draft.fields.role.trim()) throw new Error('Choose the buyer organization role before saving this reported fact.')
      add('organization'); add('role')
    } else if (draft.factType === 'closure') {
      if (!draft.fields.state.trim()) throw new Error('Choose the reported closure state before saving this fact.')
      add('state')
    }
    if (draft.fields.basis?.trim() && !(draft.factType === 'timing' && draft.correctsReportedTiming)) value.basis = draft.fields.basis.trim()
    if (draft.fields.source_quote?.trim()) value.source_quote = draft.fields.source_quote.trim()
    return value
  }

  async function createDraft(event: FormEvent) {
    event.preventDefault()
    const before = currentPageForSubmit()
    if (!before || draft.pendingFactId) return
    setBusy(true); setError(''); setNotice('')
    try {
      const fresh = await readFreshPage()
      if (!fresh) return
      if (fresh.current_fact_version !== before.current_fact_version) {
        setError('The current exact-Need fact version changed. Review the refreshed history before submitting this preserved draft.')
        return
      }
      const target = fresh.current_reported_timing_correction_target
      if (draft.correctsReportedTiming && !sameTarget(draft.timingBinding, fresh)) {
        setError('The selected source timing changed. Review the current source target and explicitly reselect it before saving.')
        return
      }
      if (!draft.facilityScope.trim() || !draft.reporterName.trim()) {
        setError('Facility scope and reporter name are required.')
        return
      }
      const body = {
        client_id: draft.factClientId,
        project_id: item.project_id,
        pursuit_id: null,
        expected_version: fresh.current_fact_version,
        predecessor_id: draft.predecessorId || null,
        activity_key: item.activity,
        facility_scope: draft.facilityScope.trim(),
        fact_type: draft.factType,
        value: valueForDraft(target),
        reporter_name: draft.reporterName.trim(),
        reporter_organization: draft.reporterOrganization.trim() || null,
        reporter_role: draft.reporterRole.trim() || null,
        confirmation_channel: draft.channel.trim(),
        source_reference: draft.sourceReference.trim() || null,
        source_date: draft.sourceDate || null,
        confirmed_at: isoDateTime(draft.confirmedAt),
        effective_from: isoDateTime(draft.effectiveFrom),
        effective_until: draft.effectiveUntil ? isoDateTime(draft.effectiveUntil) : null,
      }
      const created = await client.createCallFact(needId, body)
      const currentDraft = { ...draft, pendingFactId: created.id }
      storeDraft(currentDraft)
      const readback = await client.callFacts(needId)
      const savedDraft = readback.items.find((fact) => fact.id === created.id && fact.need_id === needId)
      if (!savedDraft) {
        setPage(readback)
        setError('The server created this draft but exact-Need read-back did not include it. The draft is preserved; reload history before deciding it.')
        return
      }
      if (draft.correctsReportedTiming) {
        const readbackTarget = targetBinding(readback.current_reported_timing_correction_target, readback.current_fact_version)
        const expectedVersion = before.current_fact_version + 1
        const ownAdvance = created.decision_version === expectedVersion
          && readback.current_fact_version === expectedVersion
        const alreadyReadBackDraft = before.current_fact_version === created.decision_version
          && readback.current_fact_version === before.current_fact_version
          && before.items.some((fact) => fact.id === created.id && fact.need_id === needId
            && fact.decision === 'draft' && fact.decision_version === created.decision_version)
        const payloadMatches = savedDraft.fact_type === 'timing' && savedDraft.decision === 'draft'
          && savedDraft.project_id === item.project_id
          && savedDraft.decision_version === created.decision_version
          && sameTimingCorrectionPayload(body.value, savedDraft.value)
        if (!sameTargetSource(draft.timingBinding, readbackTarget)
          || (!ownAdvance && !alreadyReadBackDraft)
          || !payloadMatches) {
          setPage(readback); setHistoryOffset(0)
          setError('The source timing or saved correction changed while the draft was being saved. The draft is preserved; review the current target and create a new correction before accepting it.')
          return
        }
        const confirmedDraft = { ...currentDraft, timingBinding: readbackTarget }
        storeDraft(confirmedDraft)
      }
      setPage(readback); setHistoryOffset(0)
      setNotice('Draft persisted and confirmed in this exact Need history. It is not qualification evidence unless explicitly accepted.')
    } catch (cause) {
      await readFreshPage()
      setError(statusError(cause))
    } finally { setBusy(false) }
  }

  async function decideFact(fact: CallFact, decision: 'accepted' | 'rejected' | 'corrected' | 'retracted') {
    const before = currentPageForSubmit()
    if (!before || !draft.decisionReason.trim()) {
      setError('Enter a reason before recording a fact decision.')
      return
    }
    if (decision === 'corrected' && !draft.predecessorId) {
      setError('Choose the exact predecessor fact version before recording a correction.')
      return
    }
    setBusy(true); setError(''); setNotice('')
    try {
      const fresh = await readFreshPage()
      if (!fresh) return
      if (fresh.current_fact_version !== before.current_fact_version) {
        setError('The current exact-Need fact version changed. Review the refreshed history; the draft and reason are preserved.')
        return
      }
      if (draft.correctsReportedTiming && !sameTarget(draft.timingBinding, fresh)) {
        setError('The selected source timing changed. Review the target and explicitly reselect it before deciding this correction.')
        return
      }
      const result = await client.decideCallFact(needId, fact.id, {
        client_id: draft.decisionClientId,
        expected_version: fresh.current_fact_version,
        decision,
        reason: draft.decisionReason.trim(),
      })
      const readback = await client.callFacts(needId)
      const saved = readback.items.find((row) => row.id === fact.id)
      if (!saved || saved.decision !== decision || saved.decision_version !== result.version) {
        setPage(readback)
        setError('The decision response could not be confirmed in exact-Need history. Your reason is preserved; reload before retrying.')
        return
      }
      setPage(readback); setHistoryOffset(0)
      if (fact.id === draft.pendingFactId) {
        const clean = newDraft(item.location ?? item.name)
        draftByNeed.delete(needId); setDraft(clean)
      } else {
        updateDraft({ decisionReason: '', decisionClientId: crypto.randomUUID() })
      }
      setNotice(`Server read-back confirmed ${saved.decision} version ${saved.decision_version}; current qualification is shown by the refreshed browse/detail response.`)
      onReadback()
    } catch (cause) {
      await readFreshPage()
      setError(statusError(cause))
    } finally { setBusy(false) }
  }

  async function saveStatus(event: FormEvent) {
    event.preventDefault()
    const before = workflow
    if (!draft.workflowRequest && (!before || !draft.workflowSelection || !draft.workflowReason.trim())) {
      setError('Choose an operator status and enter its reason.')
      return
    }
    setBusy(true); setError(''); setNotice('')
    try {
      let request = draft.workflowRequest
      if (!request) {
        let fresh: NeedWorkflowStatus
        try { fresh = await client.workflowStatus(needId) }
        catch (cause) {
          if (activeNeedId.current === needId) setError(statusError(cause))
          return
        }
        if (activeNeedId.current !== needId) return
        if (!before || fresh.version !== before.version) {
          setWorkflow(fresh)
          setError('The exact-Need workflow status changed. Review its latest event before submitting this preserved status draft.')
          return
        }
        request = {
          needId,
          projectId: item.project_id,
          pursuitId: null,
          clientId: draft.workflowClientId,
          expectedVersion: fresh.version,
          status: draft.workflowSelection as WorkflowStatus,
          reason: draft.workflowReason.trim(),
        }
        storeDraft({ ...draft, workflowRequest: request })
      }
      if (!request) return

      let savedEvent: NeedWorkflowStatus['events'][number]
      try {
        savedEvent = await client.setWorkflowStatus(request.needId, {
          client_id: request.clientId,
          project_id: request.projectId,
          pursuit_id: request.pursuitId,
          expected_version: request.expectedVersion,
          status: request.status,
          reason: request.reason,
        })
      } catch (cause) {
        if (activeNeedId.current !== request.needId) return
        try {
          const current = await client.workflowStatus(request.needId)
          if (activeNeedId.current === request.needId) setWorkflow(current)
        } catch {
          if (activeNeedId.current === request.needId) setWorkflow(null)
        }
        if (activeNeedId.current !== request.needId) return
        setError(`${statusError(cause)} The save is unconfirmed. Retrying will reuse the same request.`)
        return
      }
      if (activeNeedId.current !== request.needId) return
      if (!workflowEventMatchesRequest(savedEvent, request)) {
        try {
          const current = await client.workflowStatus(request.needId)
          if (activeNeedId.current === request.needId) setWorkflow(current)
        } catch {
          if (activeNeedId.current === request.needId) setWorkflow(null)
        }
        if (activeNeedId.current !== request.needId) return
        setError('The returned status event did not match this exact-Need request. Its draft is preserved for review.')
        return
      }

      let readback: NeedWorkflowStatus
      try { readback = await client.workflowStatus(request.needId) }
      catch (cause) {
        if (activeNeedId.current !== request.needId) return
        setWorkflow(null)
        setError(`${statusError(cause)} The returned event is not confirmed in exact-Need history; retrying will reuse the same request.`)
        return
      }
      if (activeNeedId.current !== request.needId) return
      const confirmed = readback.events.find((row) => row.id === savedEvent.id)
      if (!confirmed || !workflowEventMatchesRequest(confirmed, request)
        || confirmed.version !== savedEvent.version
        || confirmed.content_hash !== savedEvent.content_hash) {
        setWorkflow(readback)
        setError('The status response could not be confirmed in exact-Need history. Its draft is preserved; retry will reuse the same request.')
        return
      }

      setWorkflow(readback)
      storeDraft({ ...draft, workflowClientId: crypto.randomUUID(), workflowSelection: '', workflowReason: '', workflowRequest: null })
      setNotice(readback.version > confirmed.version
        ? `Status event ${confirmed.status} was confirmed at version ${confirmed.version}; the newer current status remains ${readback.status} at version ${readback.version}. Status and reason do not qualify the Need.`
        : `Live operator status ${confirmed.status} was read back at version ${confirmed.version}. Status and reason do not qualify the Need.`)
      onReadback()
    } finally {
      setBusy(false)
    }
  }

  const target = page?.current_reported_timing_correction_target
  const pendingFact = draft.pendingFactId ? page?.items.find((fact) => fact.id === draft.pendingFactId) : undefined
  const editable = !draft.pendingFactId && !busy
  const field = (key: string, label: string, type = 'text') => <label key={key}>{label}<input type={type} value={draft.fields[key] ?? ''} disabled={!editable} onChange={(event) => updateField(key, event.target.value)}/></label>

  return <section className="detail-section" aria-label="Exact-Need facts and operator status">
    <p className="eyebrow">Current exact-Need record · separate from saved evaluation history</p>
    <h3>Attributed facts and live workflow</h3>
    <p>Need {needId} · project {item.project_id} · {item.activity}. Facts and operator status are separate from public evidence; neither a note nor a status is a qualification input.</p>
    {error && <p className="error" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {loading && !page && <p role="status">Loading exact-Need history…</p>}
    {page && <>
      <section aria-label="Reported timing correction target">
        <h4>Correct reported timing</h4>
        {target?.available
          ? <p>Currently reported timing: earliest possible start {target.earliest_possible_start}; latest possible start {target.latest_possible_start}; activity duration {target.minimum_duration_days}–{target.maximum_duration_days} days. Source: {target.source_id ?? 'retained project evidence'}. A correction applies to these dates; review the target again if the source changes.</p>
          : <p>Correction unavailable: {timingUnavailableReason(target?.unavailable_reason)} Ordinary timing facts remain separate from any source correction.</p>}
        <p>Fact history version: {page.current_fact_version}. A timing correction needs a reason and review of the current reported dates.</p>
      </section>
      <form onSubmit={(event) => void createDraft(event)}>
        <h4>Record an attributed fact draft</h4>
        <label>Fact type<select aria-label="Fact type" value={draft.factType} disabled={!editable} onChange={(event) => updateDraft({ factType: event.target.value as FactType }, true)}>
          <option value="demand">Activity demand</option><option value="suitable_supply">Suitable supply</option><option value="unsuitable_supply">Unsuitable supply</option><option value="timing">Activity timing</option><option value="buyer">Buyer organization and role</option><option value="closure">Reported closure state</option>
        </select></label>
        <label>Facility<input aria-label="Facility" value={draft.facilityScope} disabled={!editable} onChange={(event) => updateDraft({ facilityScope: event.target.value }, true)}/></label>
        <label>Reporter name<input aria-label="Reporter name" value={draft.reporterName} disabled={!editable} onChange={(event) => updateDraft({ reporterName: event.target.value }, true)}/></label>
        <label>Reporter organization<input value={draft.reporterOrganization} disabled={!editable} onChange={(event) => updateDraft({ reporterOrganization: event.target.value }, true)}/></label>
        <label>Reporter role<input value={draft.reporterRole} disabled={!editable} onChange={(event) => updateDraft({ reporterRole: event.target.value }, true)}/></label>
        <label>Confirmation channel<input value={draft.channel} disabled={!editable} onChange={(event) => updateDraft({ channel: event.target.value }, true)}/></label>
        {draft.factType === 'demand' && field('mw', 'Reported demand (MW or bounded range)')}
        {draft.factType === 'unsuitable_supply' && field('mw', 'Unsuitable supply (MW)')}
        {draft.factType === 'suitable_supply' && <>{field('mw', 'Supply amount (MW, optional when using a range)')}{field('mw_min', 'Supply range minimum (MW)')}{field('mw_max', 'Supply range maximum (MW)')}<label>Supply quality<select value={draft.fields.quality} disabled={!editable} onChange={(event) => updateField('quality', event.target.value)}><option value="suitable">Suitable</option><option value="unsuitable">Unsuitable</option><option value="unknown">Unknown</option></select></label></>}
        {draft.factType === 'timing' && <>
          {field('start_date', 'Earliest possible start', 'date')}{field('end_date', 'Latest possible start', 'date')}{field('duration_days', 'Activity duration (days)', 'number')}
          <label><input type="checkbox" checked={draft.correctsReportedTiming} disabled={!editable || !target?.available} onChange={(event) => {
            const enabled = event.target.checked
            const binding = enabled && page ? targetBinding(page.current_reported_timing_correction_target, page.current_fact_version) : null
            updateDraft({ correctsReportedTiming: enabled, timingBinding: binding }, true)
          }}/> Deliberately correct the selected reported timing</label>
          {draft.correctsReportedTiming && <label>Reason for correction<textarea value={draft.timingBasis} disabled={!editable} onChange={(event) => updateDraft({ timingBasis: event.target.value }, true)}/></label>}
        </>}
        {draft.factType === 'buyer' && <>{field('organization', 'Buyer organization')}<label>Buyer role<select value={draft.fields.role} disabled={!editable} onChange={(event) => updateField('role', event.target.value)}><option value="">Choose a reported role</option><option value="project owner">Project owner</option><option value="electrical contractor">Electrical contractor</option><option value="general contractor">General contractor</option><option value="energy manager">Energy manager</option></select></label></>}
        {draft.factType === 'closure' && <label>Reported closure state<select value={draft.fields.state} disabled={!editable} onChange={(event) => updateField('state', event.target.value)}><option value="">Choose a reported state</option><option value="adequate_supply">Adequate supply</option><option value="cancelled">Cancelled</option><option value="completed">Completed</option></select></label>}
        {draft.factType !== 'timing' && <label>Basis<textarea value={draft.fields.basis ?? ''} disabled={!editable} onChange={(event) => updateField('basis', event.target.value)}/></label>}
        <label>Source quote<textarea value={draft.fields.source_quote ?? ''} disabled={!editable} onChange={(event) => updateField('source_quote', event.target.value)}/></label>
        <label>Source reference<input value={draft.sourceReference} disabled={!editable} onChange={(event) => updateDraft({ sourceReference: event.target.value }, true)}/></label>
        <label>Source date<input type="date" value={draft.sourceDate} disabled={!editable} onChange={(event) => updateDraft({ sourceDate: event.target.value }, true)}/></label>
        <label>Confirmed at<input type="datetime-local" value={draft.confirmedAt} disabled={!editable} onChange={(event) => updateDraft({ confirmedAt: event.target.value }, true)}/></label>
        <label>Effective from<input type="datetime-local" value={draft.effectiveFrom} disabled={!editable} onChange={(event) => updateDraft({ effectiveFrom: event.target.value }, true)}/></label>
        <label>Effective until (optional)<input type="datetime-local" value={draft.effectiveUntil} disabled={!editable} onChange={(event) => updateDraft({ effectiveUntil: event.target.value }, true)}/></label>
        <label>Predecessor fact version (for correction)<select value={draft.predecessorId} disabled={!editable} onChange={(event) => updateDraft({ predecessorId: event.target.value }, true)}><option value="">No predecessor</option>{page.items.map((fact) => <option value={fact.id} key={fact.id}>v{fact.decision_version ?? 0} · {fact.fact_type} · {fact.decision}</option>)}</select></label>
        {draft.predecessorId && <label>Decision reason<textarea value={draft.decisionReason} disabled={busy} onChange={(event) => updateDraft({ decisionReason: event.target.value, decisionClientId: crypto.randomUUID() })}/></label>}
        <button type="submit" disabled={!editable}>Save fact draft</button>
      </form>
      {pendingFact && <section aria-label="Explicit fact decision">
        <h4>Explicit decision · {pendingFact.fact_type} draft</h4>
        <p>This draft is not authoritative until a decision is recorded. Current qualification and gap are determined by the server after read-back.</p>
        <label>Reason for decision<textarea value={draft.decisionReason} disabled={busy} onChange={(event) => updateDraft({ decisionReason: event.target.value, decisionClientId: crypto.randomUUID() })}/></label>
        <button type="button" disabled={busy || !draft.decisionReason.trim()} onClick={() => void decideFact(pendingFact, draft.predecessorId ? 'corrected' : 'accepted')}>{draft.predecessorId ? 'Record correction' : 'Accept fact'}</button>
        <button type="button" disabled={busy || !draft.decisionReason.trim()} onClick={() => void decideFact(pendingFact, 'rejected')}>Reject fact</button>
      </section>}
      <section aria-label="Attributed fact history">
        <h4>Fact history · {page.total} total · showing {page.items.length} · version {page.current_fact_version}</h4>
        {page.items.some((fact) => fact.decision === 'accepted' || fact.decision === 'corrected') && <label>Reason for retraction<textarea value={draft.decisionReason} disabled={busy} onChange={(event) => updateDraft({ decisionReason: event.target.value, decisionClientId: crypto.randomUUID() })}/></label>}
        {page.items.map((fact) => <article key={fact.id}>
          <strong>{fact.fact_type} · {fact.decision} · {fact.authority_label}</strong>
          <p>{factSummary(fact)} · {fact.facility_scope} · confirmed by {fact.reporter_name} ({fact.reporter_role ?? 'role unrecorded'})</p>
          <p>Recorded by {fact.recorded_by} · {new Date(fact.created_at).toLocaleString()} · decision {fact.decision_version ?? 'unknown'} by {fact.decision_actor ?? 'unrecorded'}{fact.decision_reason ? `: ${fact.decision_reason}` : ''}</p>
          {(fact.decision === 'accepted' || fact.decision === 'corrected') && <button type="button" disabled={busy || !draft.decisionReason.trim()} onClick={() => void decideFact(fact, 'retracted')}>Retract this accepted version</button>}
        </article>)}
        <button type="button" disabled={busy || historyOffset <= 0} onClick={() => void reload(Math.max(0, historyOffset - 50))}>Newer fact versions</button>
        <button type="button" disabled={busy || page.next_offset == null} onClick={() => page.next_offset != null && void reload(page.next_offset)}>Older fact versions</button>
        <button type="button" disabled={busy} onClick={() => void reload(0)}>Reload exact-Need history</button>
      </section>
    </>}
    <section aria-label="Live operator workflow status">
      <h4>Live workflow status</h4>
      <p>Current status: {workflow?.status ?? 'UNKNOWN'} · version {workflow?.version ?? 0}. No event is UNKNOWN, not New. Status and reason do not establish or close an evidence need.</p>
      {draft.workflowRequest && <p role="status">This save is unconfirmed. Its status and reason are held; retrying sends the same request and cannot create a second event.</p>}
      <form onSubmit={(event) => void saveStatus(event)}>
        <label>Set operator status<select aria-label="Set operator status" value={draft.workflowSelection} disabled={busy || Boolean(draft.workflowRequest)} onChange={(event) => updateDraft({ workflowSelection: event.target.value as WorkflowStatus | '', workflowClientId: crypto.randomUUID() }, false, true)}><option value="">Choose status</option>{workflowStatuses.map((status) => <option key={status} value={status}>{status}</option>)}</select></label>
        <label>Status reason<textarea aria-label="Status reason" value={draft.workflowReason} disabled={busy || Boolean(draft.workflowRequest)} onChange={(event) => updateDraft({ workflowReason: event.target.value }, false, true)}/></label>
        <button type="submit" disabled={busy || !draft.workflowSelection || !draft.workflowReason.trim()}>{draft.workflowRequest ? 'Retry same status request' : 'Save live status'}</button>
      </form>
      <ol>{workflow?.events.slice(-10).reverse().map((event) => <li key={event.id}>{event.status} · {event.reason} · {event.actor} · {new Date(event.created_at).toLocaleString()}</li>)}</ol>
    </section>
  </section>
}
