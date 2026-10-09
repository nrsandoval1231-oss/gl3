import { expect, test, type Page, type Route } from '@playwright/test'
import type { CallFact, CallFactPage, NeedWorkflowStatus, Opportunity, TimingCorrectionTarget } from '../src/api/client'

const workflow = ['New', 'Investigating', 'Contacted', 'Qualified', 'Won', 'Lost', 'Closed'] as const

function opportunity(id: string): Opportunity {
  return {
    id, project_id: 'project-a', name: `Synthetic Facility ${id}`, location: 'Test City', tier: 'Lead',
    workflow_status: 'UNKNOWN', activity: 'construction', rationale: 'Synthetic current retained evidence.',
    signal_evidence_state: 'active_evidence', required_mw: '20 to 25 MW', commercial_size_status: 'known',
    start_window: '2027-01-01 to 2027-02-01', duration: '31 to 62 days', supply: 'Insufficient',
    next_action: 'Confirm source facts with the exact facility.', conflict_state: 'No conflict',
    missing_facts: [], reported_power_facts: [], signal_display_decision_state: 'adjudicated',
    brief_status: 'unavailable', brief_stale: false, evidence: [{
      id: 'evidence-a', title: 'Synthetic source filing', abstract: 'Test City construction filing.',
      url: 'https://example.test/source', published_at: '2026-10-01', retrieved_at: '2026-10-08T00:00:00Z',
      extraction_location: 'description', content_hash: 'a'.repeat(64), event_date: null, event_date_label: 'Unknown',
      source_id: 'synthetic-source', document_number: 'synthetic-a', source_origin: 'Synthetic fixture',
      assessment_current: true, permit_status: null,
    }], asset_type: 'construction', lifecycle_timeline: [], lifecycle_open_questions: [],
  } as Opportunity
}

const target: TimingCorrectionTarget = {
  available: true, unavailable_reason: null, need_id: 'need-a', project_id: 'project-a',
  project_identity_key: 'facility-a', activity_key: 'construction', facility_identity: 'facility-a',
  source_semantic_hash: 'b'.repeat(64), source_evidence_hash: 'c'.repeat(64),
  retained_evidence_id: 'evidence-a', source_id: 'synthetic-source', earliest_possible_start: '2027-01-01',
  latest_possible_start: '2027-02-01', minimum_duration_days: 31, maximum_duration_days: 62,
  current_fact_version: 0,
}

function emptyFacts(needId = 'need-a'): CallFactPage {
  const currentTarget = needId === 'need-a' ? target : { ...target, available: false, unavailable_reason: 'no_current_admitted_lead', need_id: needId }
  return { items: [], total: 0, limit: 50, offset: 0, next_offset: null, current_fact_version: 0, current_reported_timing_correction_target: currentTarget }
}

function factRecord(
  id: string,
  needId = 'need-a',
  body: Record<string, unknown> | null = null,
  decision: CallFact['decision'] = 'draft',
  version: number | null = null,
): CallFact {
  const timestamp = '2026-10-08T12:00:00Z'
  return {
    id, need_id: needId, project_id: String(body?.project_id ?? 'project-a'), pursuit_id: null,
    predecessor_id: typeof body?.predecessor_id === 'string' ? body.predecessor_id : null,
    activity_key: String(body?.activity_key ?? 'construction'),
    facility_scope: String(body?.facility_scope ?? 'Synthetic Facility Campus'),
    fact_type: String(body?.fact_type ?? 'demand') as CallFact['fact_type'],
    value: body?.value && typeof body.value === 'object' ? body.value as Record<string, unknown> : {},
    reporter_name: String(body?.reporter_name ?? 'Avery Chen'),
    reporter_organization: typeof body?.reporter_organization === 'string' ? body.reporter_organization : null,
    reporter_role: typeof body?.reporter_role === 'string' ? body.reporter_role : 'Project Engineer',
    confirmation_channel: String(body?.confirmation_channel ?? 'phone') as CallFact['confirmation_channel'],
    source_reference: typeof body?.source_reference === 'string' ? body.source_reference : null,
    source_date: typeof body?.source_date === 'string' ? body.source_date : null,
    confirmed_at: String(body?.confirmed_at ?? timestamp), effective_from: String(body?.effective_from ?? timestamp),
    effective_until: typeof body?.effective_until === 'string' ? body.effective_until : null,
    content_hash: 'd'.repeat(64), decision, decision_version: version,
    decision_reason: decision === 'draft' ? 'Fact captured as an unaccepted operator report.' : null,
    decision_actor: decision === 'draft' ? 'Operator' : null, decided_at: null,
    authority_label: decision === 'accepted' || decision === 'corrected' ? 'User-confirmed' : 'Reported / not accepted',
    recorded_by: 'Operator', created_at: timestamp,
  }
}

async function installFactsFixture(
  page: Page,
  initialCreateFailure: 'none' | 'ambiguous' | 'stale' = 'none',
  delayNeedA = false,
  changeTargetAfterTimingDraft = false,
  changeTargetBoundsAfterTimingDraft = false,
  changeSavedPayloadAfterTimingDraft = false,
  workflowScenario: {
    lostReplies?: number
    failedReadsAfterPost?: number
    foreignReply?: boolean
    conflictBeforeCommit?: boolean
    competingStatusAfterCommit?: boolean
    eventEvictedFromReadback?: boolean
    seedHistory?: number
  } = {},
) {
  let facts = emptyFacts()
  let selectedTarget = target
  let status: NeedWorkflowStatus = { status: 'UNKNOWN', version: 0, events: [] }
  let createFailure = initialCreateFailure
  let lostWorkflowReplies = workflowScenario.lostReplies ?? 0
  let failedWorkflowReads = workflowScenario.failedReadsAfterPost ?? 0
  let workflowPostCount = 0
  let conflictPending = workflowScenario.conflictBeforeCommit ?? false
  const seededHistory = workflowScenario.seedHistory ?? 0
  if (seededHistory > 0) {
    const events: NeedWorkflowStatus['events'] = Array.from({ length: seededHistory }, (_, index) => {
      const version = index + 1
      const eventStatus = version === seededHistory ? 'Qualified' : 'Investigating'
      return {
        id: `seeded-status-${version}`, need_id: 'need-a', project_id: 'project-a', pursuit_id: null,
        version, status: eventStatus, previous_status: version === 1 ? null : 'Investigating',
        expected_version: version - 1, reason: `History reason ${version}`, content_hash: `${version}`.padStart(64, '0'),
        actor: 'Operator', created_at: `2026-10-08T12:${String(version % 60).padStart(2, '0')}:00Z`,
      }
    })
    status = { status: 'Qualified', version: seededHistory, events }
  }
  let alterSavedTimingOnReadback = false
  let nextFactNumber = 1
  const factsByClientId = new Map<string, CallFact>()
  const workflowEventsByClientId = new Map<string, NeedWorkflowStatus['events'][number]>()
  const requests: { path: string; url: string; method: string; body: Record<string, unknown> | null }[] = []
  const records = [opportunity('need-a'), opportunity('need-b')]
  await page.route('**/api/**', async (route: Route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    if (!path.startsWith('/api/')) return route.continue()
    const method = request.method()
    const body = method === 'POST' ? request.postDataJSON() as Record<string, unknown> : null
    requests.push({ path, url: url.href, method, body })
    if (path === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (path === '/api/health') return route.fulfill({ json: { sources: [], backlog: 0, pending_interpretations: 0 } })
    if (path === '/api/changes') return route.fulfill({ json: [] })
    if (path === '/api/opportunities') {
      const selected = url.searchParams.get('status')
      const matches = selected
        ? records.filter((record) => (record.id === 'need-a' ? status.status : 'UNKNOWN') === selected)
        : records
      return route.fulfill({
        json: matches,
        headers: { 'X-Total-Count': String(matches.length), 'X-Group-Total-Count': String(matches.length),
          'X-Page-Record-Count': String(matches.length), 'X-Page-Group-Count': String(matches.length),
          'X-Limit': '25', 'X-Offset': url.searchParams.get('offset') ?? '0', 'X-Cohort-Token': `status-${status.version}`,
          'X-Decision-Counts': '{"SHOW":0,"REVIEW":0,"HOLD":0}' },
      })
    }
    if (path.startsWith('/api/opportunities/needs/')) return route.fulfill({ json: records.find((row) => row.id === path.split('/').at(-1)) ?? records[0] })
    if (path.endsWith('/brief')) return route.fulfill({ json: { status: 'unavailable', stale: false, generated_at: null, result: null, citations: [], error: null, input_tokens: 0, output_tokens: 0, job_id: null } })
    if (path.endsWith('/buying-chain')) return route.fulfill({ json: { project_id: 'project-a', status: 'unavailable', policy_version: 'buying-chain-v2', unresolved: [], runs: [], permit_summaries: [], candidates: [] } })
    if (/^\/api\/needs\/[^/]+\/facts$/.test(path) && method === 'GET') {
      if (path === '/api/needs/need-a/facts' && delayNeedA) {
        delayNeedA = false
        await new Promise((resolve) => setTimeout(resolve, 900))
      }
      if (path === '/api/needs/need-a/facts' && alterSavedTimingOnReadback) {
        alterSavedTimingOnReadback = false
        facts = { ...facts, items: facts.items.map((fact) => fact.fact_type === 'timing' && fact.decision === 'draft'
          ? { ...fact, value: { ...fact.value, start_date: '2026-11-02' } }
          : fact) }
      }
      return route.fulfill({ json: path === '/api/needs/need-a/facts' ? facts : emptyFacts(path.split('/').at(-2)) })
    }
    if (path === '/api/needs/need-a/facts' && method === 'POST') {
      if (createFailure === 'stale') {
        createFailure = 'none'
        const concurrent = { ...factRecord('concurrent-fact', 'need-a', null, 'accepted', facts.current_fact_version + 1), decision_reason: 'Concurrent exact-Need acceptance.', decision_actor: 'Operator', authority_label: 'User-confirmed' }
        facts = { ...facts, items: [concurrent, ...facts.items], total: facts.total + 1, current_fact_version: facts.current_fact_version + 1, current_reported_timing_correction_target: { ...selectedTarget, current_fact_version: facts.current_fact_version + 1 } }
        return route.fulfill({ status: 409, json: { detail: 'The expected fact version is stale.' } })
      }
      const clientId = String(body?.client_id ?? '')
      let row = factsByClientId.get(clientId)
      if (!row) {
        const version = facts.current_fact_version + 1
        row = factRecord(`fact-${nextFactNumber++}`, 'need-a', body, 'draft', version)
        factsByClientId.set(clientId, row)
        selectedTarget = { ...selectedTarget, current_fact_version: version }
        facts = { ...facts, current_fact_version: version, current_reported_timing_correction_target: selectedTarget }
        if (changeTargetAfterTimingDraft && body?.fact_type === 'timing') {
          changeTargetAfterTimingDraft = false
          selectedTarget = { ...selectedTarget, source_semantic_hash: 'e'.repeat(64), earliest_possible_start: '2027-01-02' }
          facts = { ...facts, current_reported_timing_correction_target: selectedTarget }
        }
        if (changeTargetBoundsAfterTimingDraft && body?.fact_type === 'timing') {
          changeTargetBoundsAfterTimingDraft = false
          selectedTarget = { ...selectedTarget, latest_possible_start: '2027-02-02' }
          facts = { ...facts, current_reported_timing_correction_target: selectedTarget }
        }
        if (changeSavedPayloadAfterTimingDraft && body?.fact_type === 'timing') alterSavedTimingOnReadback = true
      }
      const items = [row, ...facts.items.filter((item) => item.id !== row?.id)]
      facts = { ...facts, items, total: items.length }
      if (createFailure === 'ambiguous') {
        createFailure = 'none'
        return route.fulfill({ status: 503, json: { detail: 'The response was lost after persistence.' } })
      }
      return route.fulfill({ json: row })
    }
    if (/^\/api\/needs\/need-a\/facts\/[^/]+\/decision$/.test(path) && method === 'POST') {
      const decision = String(body?.decision ?? 'accepted')
      const factId = path.split('/').at(-2) ?? ''
      const prior = facts.items.find((item) => item.id === factId)
      if (!prior) return route.fulfill({ status: 404, json: { detail: 'Fact not found.' } })
      let version = facts.current_fact_version + 1
      let items = facts.items
      if (decision === 'corrected' && prior.predecessor_id) {
        const predecessorVersion = version
        items = items.map((item) => item.id === prior.predecessor_id
          ? { ...item, decision: 'superseded', decision_version: predecessorVersion, decision_reason: String(body?.reason ?? ''), decision_actor: 'Operator', authority_label: 'Reported / not accepted' }
          : item)
        version += 1
      }
      const saved = { ...prior, decision, decision_version: version, decision_reason: String(body?.reason ?? ''), decision_actor: 'Operator', authority_label: decision === 'accepted' || decision === 'corrected' ? 'User-confirmed' : 'Reported / not accepted' }
      selectedTarget = { ...selectedTarget, current_fact_version: version }
      facts = { ...facts, items: items.map((item) => item.id === factId ? saved : item), current_fact_version: version, current_reported_timing_correction_target: selectedTarget }
      return route.fulfill({ json: { id: `decision-${version}`, version, decision, reason: body?.reason, actor: 'Operator', created_at: '2026-10-08T12:00:01Z', fact_version_id: factId, content_hash: saved.content_hash, tier: 'Lead', active: true } })
    }
    if (/^\/api\/needs\/[^/]+\/workflow-status$/.test(path) && method === 'GET') {
      if (workflowPostCount > 0 && failedWorkflowReads > 0) {
        failedWorkflowReads -= 1
        return route.fulfill({ status: 503, json: { detail: 'Workflow read-back unavailable.' } })
      }
      return route.fulfill({ json: path === '/api/needs/need-a/workflow-status'
        ? { ...status, events: status.events.slice(-100) }
        : { status: 'UNKNOWN', version: 0, events: [] } })
    }
    if (path === '/api/needs/need-a/workflow-status' && method === 'POST') {
      workflowPostCount += 1
      if (conflictPending) {
        conflictPending = false
        const competing = {
          id: `status-${status.version + 1}`, need_id: 'need-a', project_id: 'project-a', pursuit_id: null,
          version: status.version + 1, status: 'Contacted', previous_status: status.status === 'UNKNOWN' ? null : status.status,
          expected_version: status.version, reason: 'A separate operator updated this Need.', content_hash: 'f'.repeat(64),
          actor: 'Other operator', created_at: '2026-10-08T12:00:03Z',
        }
        status = { status: 'Contacted', version: competing.version, events: [...status.events, competing].sort((left, right) => left.version - right.version) }
        records[0].workflow_status = 'Contacted'
        return route.fulfill({ status: 409, json: { detail: 'The expected workflow version is stale.' } })
      }
      const clientId = String(body?.client_id ?? '')
      const priorEvent = workflowEventsByClientId.get(clientId)
      if (priorEvent) {
        if (lostWorkflowReplies > 0) {
          lostWorkflowReplies -= 1
          return route.fulfill({ status: 503, json: { detail: 'The idempotent replay response was lost.' } })
        }
        return route.fulfill({ json: priorEvent })
      }
      if (Number(body?.expected_version) !== status.version) {
        return route.fulfill({ status: 409, json: { detail: 'The expected workflow version is stale.' } })
      }
      const nextStatus = String(body?.status ?? 'New')
      const event = { id: `status-${status.version + 1}`, need_id: 'need-a', project_id: 'project-a', pursuit_id: null,
        version: status.version + 1, status: nextStatus, previous_status: status.status === 'UNKNOWN' ? null : status.status,
        expected_version: Number(body?.expected_version ?? status.version), reason: String(body?.reason ?? ''), content_hash: 'e'.repeat(64), actor: 'Operator', created_at: '2026-10-08T12:00:02Z' }
      workflowEventsByClientId.set(clientId, event)
      status = { status: nextStatus, version: event.version, events: [...status.events, event].sort((left, right) => left.version - right.version) }
      records[0].workflow_status = nextStatus
      if (workflowScenario.competingStatusAfterCommit) {
        const competing = {
          id: `status-${status.version + 1}`, need_id: 'need-a', project_id: 'project-a', pursuit_id: null,
          version: status.version + 1, status: 'Contacted', previous_status: nextStatus,
          expected_version: status.version, reason: 'A later operator update.', content_hash: 'f'.repeat(64),
          actor: 'Other operator', created_at: '2026-10-08T12:00:03Z',
        }
        status = { status: 'Contacted', version: competing.version, events: [...status.events, competing] }
        records[0].workflow_status = 'Contacted'
      }
      if (workflowScenario.eventEvictedFromReadback) {
        for (let index = 0; index < 100; index += 1) {
          const version = status.version + 1
          const later = {
            id: `later-status-${version}`, need_id: 'need-a', project_id: 'project-a', pursuit_id: null,
            version, status: 'Investigating', previous_status: status.status, expected_version: status.version,
            reason: `Later status ${version}`, content_hash: 'a'.repeat(64), actor: 'Other operator',
            created_at: '2026-10-08T12:00:04Z',
          }
          status = { status: later.status, version, events: [...status.events, later] }
        }
      }
      if (workflowScenario.foreignReply) {
        return route.fulfill({ json: { ...event, need_id: 'need-foreign', project_id: 'project-foreign', pursuit_id: 'pursuit-foreign' } })
      }
      if (lostWorkflowReplies > 0) {
        lostWorkflowReplies -= 1
        return route.fulfill({ status: 503, json: { detail: 'The response was lost after persistence.' } })
      }
      return route.fulfill({ json: event })
    }
    return route.fulfill({ json: [] })
  })
  return { get facts() { return facts }, get status() { return status }, requests }
}

test('exact-Need timing correction uses the server target and status is separately attributed', async ({ page }) => {
  const fixture = await installFactsFixture(page)
  await page.goto('/?tier=Leads')
  await page.locator('[data-opportunity-id="need-a"]').first().click()
  await expect(page.getByRole('heading', { name: 'Attributed facts and live workflow' })).toBeVisible()
  await expect(page.getByText(/earliest possible start 2027-01-01/)).toBeVisible()
  await page.getByLabel('Fact type').selectOption('timing')
  await page.getByLabel('Reporter name').fill('Avery Chen')
  await page.getByLabel('Facility').fill('Synthetic Facility Campus')
  await page.getByLabel('Earliest possible start').fill('2026-11-01')
  await page.getByLabel('Latest possible start').fill('2026-11-01')
  await page.getByLabel('Activity duration (days)').fill('31')
  await page.getByLabel('Deliberately correct the selected reported timing').check()
  await page.getByLabel('Reason for correction').fill('The project owner confirmed the revised possible start date.')
  await page.getByRole('button', { name: 'Save fact draft' }).click()
  await expect(page.getByText(/Draft persisted and confirmed in this exact Need history/)).toBeVisible()
  const draftRequest = fixture.requests.find((request) => request.path === '/api/needs/need-a/facts' && request.method === 'POST')
  expect(draftRequest?.body?.fact_type).toBe('timing')
  const value = draftRequest?.body?.value as Record<string, unknown>
  expect(value.corrects_source_semantic_hash).toBe('b'.repeat(64))
  expect(value.corrects_source_evidence_hash).toBe('c'.repeat(64))
  expect(value.basis).toContain('project owner confirmed')
  await expect(page.getByRole('textbox', { name: /source.*hash/i })).toHaveCount(0)
  expect(fixture.facts.current_fact_version).toBe(1)
  expect(fixture.facts.current_reported_timing_correction_target.current_fact_version).toBe(1)
  expect(fixture.facts.items[0].value).toMatchObject(value)
  await page.getByRole('textbox', { name: 'Reason for decision' }).fill('The attributed report was verified with the owner.')
  await page.getByRole('button', { name: 'Accept fact' }).click()
  await expect(page.getByText(/Server read-back confirmed accepted version 2/)).toBeVisible()
  expect(fixture.facts.current_fact_version).toBe(2)
  expect(fixture.facts.items[0].decision_actor).toBe('Operator')
  await page.getByLabel('Set operator status').selectOption('Investigating')
  await page.getByLabel('Status reason').fill('Operator is confirming the activity schedule.')
  await page.getByRole('button', { name: 'Save live status' }).click()
  await expect(page.getByText(/Live operator status Investigating was read back at version 1/)).toBeVisible()
  expect(fixture.status.status).toBe('Investigating')
  await expect(page.getByText(/Status and reason do not qualify the Need/)).toBeVisible()
})

test('lost workflow-status reply retries the frozen key and confirms the original event', async ({ page }) => {
  const fixture = await installFactsFixture(page, 'none', false, false, false, false, { lostReplies: 1 })
  await page.goto('/?tier=Leads')
  await page.locator('[data-opportunity-id="need-a"]').first().click()
  await page.getByLabel('Set operator status').selectOption('Investigating')
  await page.getByLabel('Status reason').fill('Confirm this status exactly once.')
  await page.getByRole('button', { name: 'Save live status' }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByLabel('Status reason')).toHaveValue('Confirm this status exactly once.')
  const firstPost = fixture.requests.find((request) => request.path === '/api/needs/need-a/workflow-status' && request.method === 'POST')
  expect(firstPost?.body?.expected_version).toBe(0)
  await page.getByRole('button', { name: 'Retry same status request' }).click()
  await expect(page.getByText(/Live operator status Investigating was read back at version 1/)).toBeVisible()
  const statusPosts = fixture.requests.filter((request) => request.path === '/api/needs/need-a/workflow-status' && request.method === 'POST')
  expect(statusPosts).toHaveLength(2)
  expect(statusPosts[1].body?.client_id).toBe(firstPost?.body?.client_id)
  expect(statusPosts[1].body?.expected_version).toBe(firstPost?.body?.expected_version)
  expect(fixture.status.version).toBe(1)
  expect(fixture.status.events).toHaveLength(1)
})

test('status retry succeeds when first exact-Need read-back is unavailable', async ({ page }) => {
  const fixture = await installFactsFixture(page, 'none', false, false, false, false, { lostReplies: 1, failedReadsAfterPost: 1 })
  await page.goto('/?tier=Leads')
  await page.locator('[data-opportunity-id="need-a"]').first().click()
  await page.getByLabel('Set operator status').selectOption('Contacted')
  await page.getByLabel('Status reason').fill('The operator made contact.')
  await page.getByRole('button', { name: 'Save live status' }).click()
  await expect(page.getByRole('alert')).toContainText('unconfirmed')
  await page.getByRole('button', { name: 'Retry same status request' }).click()
  await expect(page.getByText(/Live operator status Contacted was read back at version 1/)).toBeVisible()
  const posts = fixture.requests.filter((request) => request.path === '/api/needs/need-a/workflow-status' && request.method === 'POST')
  expect(posts).toHaveLength(2)
  expect(posts[0].body?.client_id).toBe(posts[1].body?.client_id)
  expect(fixture.status.events).toHaveLength(1)
})

test('failed read-back does not leave a possibly stale current status visible', async ({ page }) => {
  await installFactsFixture(page, 'none', false, false, false, false, { lostReplies: 1, failedReadsAfterPost: 1, seedHistory: 3 })
  await page.goto('/?tier=Leads')
  await page.locator('[data-opportunity-id="need-a"]').first().click()
  await expect(page.getByText('Current status: Qualified · version 3')).toBeVisible()
  await page.getByLabel('Set operator status').selectOption('Contacted')
  await page.getByLabel('Status reason').fill('Confirm status after current read-back recovers.')
  await page.getByRole('button', { name: 'Save live status' }).click()
  await expect(page.getByRole('alert')).toContainText('unconfirmed')
  await expect(page.getByText('Current status: UNKNOWN · version 0')).toBeVisible()
  await expect(page.getByLabel('Status reason')).toHaveValue('Confirm status after current read-back recovers.')
})

test('repeated lost status replies keep the exact draft and idempotency key unresolved', async ({ page }) => {
  const fixture = await installFactsFixture(page, 'none', false, false, false, false, { lostReplies: 2, failedReadsAfterPost: 2 })
  await page.goto('/?tier=Leads')
  await page.locator('[data-opportunity-id="need-a"]').first().click()
  await page.getByLabel('Set operator status').selectOption('Won')
  await page.getByLabel('Status reason').fill('The purchase is complete.')
  await page.getByRole('button', { name: 'Save live status' }).click()
  await expect(page.getByRole('alert')).toContainText('unconfirmed')
  await page.getByRole('button', { name: 'Retry same status request' }).click()
  await expect(page.getByRole('alert')).toContainText('unconfirmed')
  await expect(page.getByLabel('Status reason')).toHaveValue('The purchase is complete.')
  await expect(page.getByLabel('Set operator status')).toBeDisabled()
  const posts = fixture.requests.filter((request) => request.path === '/api/needs/need-a/workflow-status' && request.method === 'POST')
  expect(posts).toHaveLength(2)
  expect(posts[0].body?.client_id).toBe(posts[1].body?.client_id)
  expect(posts[0].body).toEqual(posts[1].body)
  expect(fixture.status.events).toHaveLength(1)
})

test('foreign status event with matching text cannot confirm the selected Need request', async ({ page }) => {
  const fixture = await installFactsFixture(page, 'none', false, false, false, false, { foreignReply: true })
  await page.goto('/?tier=Leads')
  await page.locator('[data-opportunity-id="need-a"]').first().click()
  await page.getByLabel('Set operator status').selectOption('Qualified')
  await page.getByLabel('Status reason').fill('Reviewed for qualification.')
  await page.getByRole('button', { name: 'Save live status' }).click()
  await expect(page.getByRole('alert')).toContainText('did not match this exact-Need request')
  await expect(page.getByLabel('Status reason')).toHaveValue('Reviewed for qualification.')
  expect(fixture.status.version).toBe(1)
  expect(fixture.status.events).toHaveLength(1)
})

test('a concurrent version conflict keeps the original status request for review', async ({ page }) => {
  const fixture = await installFactsFixture(page, 'none', false, false, false, false, { conflictBeforeCommit: true })
  await page.goto('/?tier=Leads')
  await page.locator('[data-opportunity-id="need-a"]').first().click()
  await page.getByLabel('Set operator status').selectOption('Investigating')
  await page.getByLabel('Status reason').fill('The operator is investigating.')
  await page.getByRole('button', { name: 'Save live status' }).click()
  await expect(page.getByRole('alert')).toContainText('409')
  await expect(page.getByText('Current status: Contacted · version 1')).toBeVisible()
  await expect(page.getByLabel('Status reason')).toHaveValue('The operator is investigating.')
  await expect(page.getByRole('button', { name: 'Retry same status request' })).toBeEnabled()
  const posts = fixture.requests.filter((request) => request.path === '/api/needs/need-a/workflow-status' && request.method === 'POST')
  expect(posts).toHaveLength(1)
  expect(fixture.status.events).toHaveLength(1)
})

test('status event committed before a newer update confirms historically without replacing current status', async ({ page }) => {
  const fixture = await installFactsFixture(page, 'none', false, false, false, false, { competingStatusAfterCommit: true })
  await page.goto('/?tier=Leads')
  await page.locator('[data-opportunity-id="need-a"]').first().click()
  await page.getByLabel('Set operator status').selectOption('Investigating')
  await page.getByLabel('Status reason').fill('The first operator update.')
  await page.getByRole('button', { name: 'Save live status' }).click()
  await expect(page.getByText(/confirmed at version 1; the newer current status remains Contacted at version 2/)).toBeVisible()
  await expect(page.getByText('Current status: Contacted · version 2')).toBeVisible()
  expect(fixture.status.events.map((row) => row.version)).toEqual([1, 2])
})

test('an idempotent event outside the latest hundred remains unresolved', async ({ page }) => {
  const fixture = await installFactsFixture(page, 'none', false, false, false, false, { eventEvictedFromReadback: true })
  await page.goto('/?tier=Leads')
  await page.locator('[data-opportunity-id="need-a"]').first().click()
  await page.getByLabel('Set operator status').selectOption('Closed')
  await page.getByLabel('Status reason').fill('The event is outside the available history window.')
  await page.getByRole('button', { name: 'Save live status' }).click()
  await expect(page.getByRole('alert')).toContainText('could not be confirmed in exact-Need history')
  await expect(page.getByLabel('Status reason')).toHaveValue('The event is outside the available history window.')
  await expect(page.getByText('Current status: Investigating · version 101')).toBeVisible()
  expect(fixture.status.version).toBe(101)
})

test('workflow history shows the newest ten events from the returned ascending page', async ({ page }) => {
  await installFactsFixture(page, 'none', false, false, false, false, { seedHistory: 12 })
  await page.goto('/?tier=Leads')
  await page.locator('[data-opportunity-id="need-a"]').first().click()
  await expect(page.getByText('Qualified · History reason 12 · Operator')).toBeVisible()
  await expect(page.getByText('Investigating · History reason 3 · Operator')).toBeVisible()
  await expect(page.getByText('Investigating · History reason 2 · Operator')).toHaveCount(0)
})

test('a concurrent source-target change after draft read-back cannot rebind a timing correction', async ({ page }) => {
  const fixture = await installFactsFixture(page, 'none', false, true)
  await page.goto('/?tier=Leads')
  await page.locator('[data-opportunity-id="need-a"]').first().click()
  await page.getByLabel('Fact type').selectOption('timing')
  await page.getByLabel('Reporter name').fill('Avery Chen')
  await page.getByLabel('Earliest possible start').fill('2026-11-01')
  await page.getByLabel('Latest possible start').fill('2026-11-01')
  await page.getByLabel('Activity duration (days)').fill('31')
  await page.getByLabel('Deliberately correct the selected reported timing').check()
  await page.getByLabel('Reason for correction').fill('The owner supplied this proposed correction.')
  await page.getByRole('button', { name: 'Save fact draft' }).click()
  await expect(page.getByRole('alert')).toContainText('source timing or saved correction changed while the draft was being saved')
  await expect(page.getByLabel('Earliest possible start')).toHaveValue('2026-11-01')
  await expect(page.getByText(/Currently reported timing: earliest possible start 2027-01-02/)).toBeVisible()
  const draftRequest = fixture.requests.find((request) => request.method === 'POST' && request.path === '/api/needs/need-a/facts')
  expect((draftRequest?.body?.value as Record<string, unknown>).corrects_source_semantic_hash).toBe('b'.repeat(64))
  await page.getByLabel('Reason for decision').fill('Do not apply a correction to the changed source target.')
  await page.getByRole('button', { name: 'Accept fact' }).click()
  await expect(page.getByRole('alert')).toContainText('selected source timing changed')
  expect(fixture.requests.filter((request) => request.method === 'POST' && request.path.endsWith('/decision'))).toHaveLength(0)
})

test('a same-hash reported-bounds change after draft read-back requires timing re-review', async ({ page }) => {
  const fixture = await installFactsFixture(page, 'none', false, false, true)
  await page.goto('/?tier=Leads')
  await page.locator('[data-opportunity-id="need-a"]').first().click()
  await page.getByLabel('Fact type').selectOption('timing')
  await page.getByLabel('Reporter name').fill('Avery Chen')
  await page.getByLabel('Earliest possible start').fill('2026-11-01')
  await page.getByLabel('Latest possible start').fill('2026-11-01')
  await page.getByLabel('Activity duration (days)').fill('31')
  await page.getByLabel('Deliberately correct the selected reported timing').check()
  await page.getByLabel('Reason for correction').fill('The owner supplied this proposed correction.')
  await page.getByRole('button', { name: 'Save fact draft' }).click()
  await expect(page.getByRole('alert')).toContainText('source timing or saved correction changed while the draft was being saved')
  await expect(page.getByText(/Currently reported timing: earliest possible start 2027-01-01; latest possible start 2027-02-02/)).toBeVisible()
  expect(fixture.facts.current_reported_timing_correction_target.source_semantic_hash).toBe('b'.repeat(64))
  await page.getByLabel('Reason for decision').fill('Do not apply a correction to changed reported bounds.')
  await page.getByRole('button', { name: 'Accept fact' }).click()
  await expect(page.getByRole('alert')).toContainText('selected source timing changed')
  expect(fixture.requests.filter((request) => request.method === 'POST' && request.path.endsWith('/decision'))).toHaveLength(0)
})

test('a saved timing draft payload mismatch cannot advance the reviewed source binding', async ({ page }) => {
  const fixture = await installFactsFixture(page, 'none', false, false, false, true)
  await page.goto('/?tier=Leads')
  await page.locator('[data-opportunity-id="need-a"]').first().click()
  await page.getByLabel('Fact type').selectOption('timing')
  await page.getByLabel('Reporter name').fill('Avery Chen')
  await page.getByLabel('Earliest possible start').fill('2026-11-01')
  await page.getByLabel('Latest possible start').fill('2026-11-01')
  await page.getByLabel('Activity duration (days)').fill('31')
  await page.getByLabel('Deliberately correct the selected reported timing').check()
  await page.getByLabel('Reason for correction').fill('The owner supplied this proposed correction.')
  await page.getByRole('button', { name: 'Save fact draft' }).click()
  await expect(page.getByRole('alert')).toContainText('source timing or saved correction changed while the draft was being saved')
  await expect(page.getByText(/Possible start: 2026-11-02 to 2026-11-01/)).toBeVisible()
  expect(fixture.facts.items[0].value.start_date).toBe('2026-11-02')
  await page.getByLabel('Reason for decision').fill('Do not accept a changed saved correction payload.')
  await page.getByRole('button', { name: 'Accept fact' }).click()
  await expect(page.getByRole('alert')).toContainText('selected source timing changed')
  expect(fixture.requests.filter((request) => request.method === 'POST' && request.path.endsWith('/decision'))).toHaveLength(0)
})

test('fact acceptance, correction, retraction and rejection are separate attributed read-backs', async ({ page }) => {
  const fixture = await installFactsFixture(page)
  await page.goto('/?tier=Leads')
  await page.locator('[data-opportunity-id="need-a"]').first().click()
  await page.getByLabel('Reporter name').fill('Avery Chen')
  await page.getByLabel('Reported demand (MW or bounded range)').fill('22')
  await page.getByRole('button', { name: 'Save fact draft' }).click()
  await page.getByLabel('Reason for decision').fill('The project owner confirmed this demand.')
  await page.getByRole('button', { name: 'Accept fact' }).click()
  await expect(page.getByText(/Server read-back confirmed accepted version 2/)).toBeVisible()

  await page.getByLabel('Reporter name').fill('Avery Chen')
  await page.getByLabel('Reported demand (MW or bounded range)').fill('24')
  await page.getByLabel('Predecessor fact version (for correction)').selectOption('fact-1')
  await page.getByRole('button', { name: 'Save fact draft' }).click()
  await expect(page.getByRole('button', { name: 'Record correction' })).toBeVisible()
  await page.getByLabel('Reason for decision').fill('The owner corrected the reported amount.')
  await page.getByRole('button', { name: 'Record correction' }).click()
  await expect(page.getByText(/Server read-back confirmed corrected version 5/)).toBeVisible()
  await page.getByLabel('Reason for retraction').fill('The corrected report was withdrawn by its reporter.')
  await page.getByRole('button', { name: 'Retract this accepted version' }).first().click()
  await expect(page.getByText(/Server read-back confirmed retracted version 6/)).toBeVisible()

  await page.getByLabel('Reporter name').fill('Avery Chen')
  await page.getByLabel('Reported demand (MW or bounded range)').fill('18')
  await page.getByRole('button', { name: 'Save fact draft' }).click()
  await page.getByLabel('Reason for decision').fill('The second source could not confirm this amount.')
  await page.getByRole('button', { name: 'Reject fact' }).click()
  await expect(page.getByText(/Server read-back confirmed rejected version 8/)).toBeVisible()
  expect(fixture.facts.items.some((fact) => fact.decision === 'retracted')).toBe(true)
  expect(fixture.facts.items.some((fact) => fact.decision === 'rejected')).toBe(true)
  const created = fixture.requests.filter((request) => request.method === 'POST' && request.path === '/api/needs/need-a/facts')
  expect((created[1]?.body?.predecessor_id)).toBe('fact-1')
})

test('buyer role and closure state remain unknown until explicitly selected', async ({ page }) => {
  const fixture = await installFactsFixture(page)
  await page.goto('/?tier=Leads')
  await page.locator('[data-opportunity-id="need-a"]').first().click()
  await page.getByLabel('Fact type').selectOption('buyer')
  await page.getByLabel('Reporter name').fill('Avery Chen')
  await expect(page.getByLabel('Buyer role')).toHaveValue('')
  await page.getByRole('button', { name: 'Save fact draft' }).click()
  await expect(page.getByRole('alert')).toContainText('Choose the buyer organization role')
  expect(fixture.requests.filter((request) => request.method === 'POST' && request.path === '/api/needs/need-a/facts')).toHaveLength(0)
  await page.getByLabel('Buyer organization').fill('Northstar Electric')
  await page.getByLabel('Buyer role').selectOption('electrical contractor')
  await page.getByRole('button', { name: 'Save fact draft' }).click()
  await expect(page.getByText(/Draft persisted and confirmed in this exact Need history/)).toBeVisible()
  const buyerDraft = fixture.requests.find((request) => request.method === 'POST' && request.path === '/api/needs/need-a/facts')
  expect(buyerDraft?.body?.value).toEqual({ organization: 'Northstar Electric', role: 'electrical contractor' })
  await page.getByLabel('Reason for decision').fill('The organization identified its role.')
  await page.getByRole('button', { name: 'Accept fact' }).click()

  await page.getByLabel('Fact type').selectOption('closure')
  await page.getByLabel('Reporter name').fill('Avery Chen')
  await expect(page.getByLabel('Reported closure state')).toHaveValue('')
  await page.getByRole('button', { name: 'Save fact draft' }).click()
  await expect(page.getByRole('alert')).toContainText('Choose the reported closure state')
  expect(fixture.requests.filter((request) => request.method === 'POST' && request.path === '/api/needs/need-a/facts')).toHaveLength(1)
  await page.getByLabel('Reported closure state').selectOption('cancelled')
  await page.getByRole('button', { name: 'Save fact draft' }).click()
  await expect(page.getByText(/Draft persisted and confirmed in this exact Need history/)).toBeVisible()
  const closureDraft = fixture.requests.filter((request) => request.method === 'POST' && request.path === '/api/needs/need-a/facts').at(-1)
  expect(closureDraft?.body?.value).toEqual({ state: 'cancelled' })
})

test('ambiguous draft response retries with the same idempotency key and stale 409 refreshes before retry', async ({ page }) => {
  const ambiguous = await installFactsFixture(page, 'ambiguous')
  await page.goto('/?tier=Leads')
  await page.locator('[data-opportunity-id="need-a"]').first().click()
  await page.getByLabel('Reporter name').fill('Avery Chen')
  await page.getByLabel('Reported demand (MW or bounded range)').fill('22')
  await page.getByRole('button', { name: 'Save fact draft' }).click()
  await expect(page.getByRole('alert')).toContainText('503')
  await expect(page.getByLabel('Reporter name')).toHaveValue('Avery Chen')
  await page.getByRole('button', { name: 'Save fact draft' }).click()
  await expect(page.getByText(/Draft persisted and confirmed in this exact Need history/)).toBeVisible()
  const ambiguousPosts = ambiguous.requests.filter((request) => request.method === 'POST' && request.path === '/api/needs/need-a/facts')
  expect(ambiguousPosts).toHaveLength(2)
  expect(ambiguousPosts.map((request) => request.body?.client_id)).toEqual([ambiguousPosts[0].body?.client_id, ambiguousPosts[0].body?.client_id])
  expect(ambiguous.facts.total).toBe(1)

  const stalePage = await page.context().newPage()
  const stale = await installFactsFixture(stalePage, 'stale')
  await stalePage.goto('/?tier=Leads')
  await stalePage.locator('[data-opportunity-id="need-a"]').first().click()
  await stalePage.getByLabel('Reporter name').fill('Avery Chen')
  await stalePage.getByLabel('Reported demand (MW or bounded range)').fill('22')
  await stalePage.getByRole('button', { name: 'Save fact draft' }).click()
  await expect(stalePage.getByRole('alert')).toContainText('409')
  await expect(stalePage.getByLabel('Reporter name')).toHaveValue('Avery Chen')
  await stalePage.getByRole('button', { name: 'Save fact draft' }).click()
  await expect(stalePage.getByText(/Draft persisted and confirmed in this exact Need history/)).toBeVisible()
  const stalePosts = stale.requests.filter((request) => request.method === 'POST' && request.path === '/api/needs/need-a/facts')
  expect(stalePosts.map((request) => request.body?.expected_version)).toEqual([0, 1])
  expect(stalePosts[0].body?.client_id).toBe(stalePosts[1].body?.client_id)
  await stalePage.close()
})

test('all seven workflow filters and UNKNOWN round-trip through the browse URL', async ({ page }) => {
  const fixture = await installFactsFixture(page)
  await page.goto('/?tier=Leads&status=UNKNOWN')
  await expect(page.getByLabel('Filter by workflow status')).toHaveValue('UNKNOWN')
  for (const status of workflow) {
    const value = status.toUpperCase()
    await page.getByLabel('Filter by workflow status').selectOption(value)
    await expect.poll(() => fixture.requests.some((request) => request.path === '/api/opportunities'
      && new URL(request.url).searchParams.get('status') === value)).toBe(true)
    await expect.poll(() => new URL(page.url()).searchParams.get('status')).toBe(value)
  }
  await page.goBack()
  await expect.poll(() => page.getByLabel('Filter by workflow status').inputValue()).toBe('LOST')
  await expect.poll(() => new URL(page.url()).searchParams.get('status')).toBe('LOST')
})

test('fact drafts stay isolated by exact Need while navigating away and back', async ({ page }) => {
  await installFactsFixture(page)
  await page.goto('/?tier=Leads')
  await page.locator('[data-opportunity-id="need-a"]').first().click()
  await page.getByLabel('Reporter name').fill('Avery for Need A')
  await page.getByRole('button', { name: /Back to Leads/ }).click()
  await page.locator('[data-opportunity-id="need-b"]').first().click()
  await expect(page.getByLabel('Reporter name')).not.toHaveValue('Avery for Need A')
  await page.getByRole('button', { name: /Back to Leads/ }).click()
  await page.locator('[data-opportunity-id="need-a"]').first().click()
  await expect(page.getByLabel('Reporter name')).toHaveValue('Avery for Need A')
})

test('late fact-history response from a prior Need cannot overwrite the selected sibling', async ({ page }) => {
  const fixture = await installFactsFixture(page, 'none', true)
  await page.goto('/?tier=Leads')
  await page.locator('[data-opportunity-id="need-a"]').first().click()
  await expect.poll(() => fixture.requests.some((request) => request.path === '/api/needs/need-a/facts' && request.method === 'GET')).toBe(true)
  await page.getByRole('button', { name: /Back to Leads/ }).click()
  await page.locator('[data-opportunity-id="need-b"]').first().click()
  await expect(page.getByText(/Need need-b · project project-a/)).toBeVisible()
  await expect(page.getByText(/Correction unavailable: A current, replayable source-supported Lead is unavailable/)).toBeVisible()
  await page.waitForTimeout(1000)
  await expect(page.getByText(/Need need-b · project project-a/)).toBeVisible()
  await expect(page.getByText(/earliest possible start 2027-01-01/)).toHaveCount(0)
})

test('synthetic authenticated browser writes persist through the isolated local API', async ({ page }) => {
  const needId = process.env.A6_UI_PERSISTED_NEED_ID
  const projectId = process.env.A6_UI_PERSISTED_PROJECT_ID
  const facility = process.env.A6_UI_PERSISTED_NAME
  const password = process.env.A6_UI_PERSISTED_PASSWORD
  test.skip(!needId || !projectId || !facility || !password, 'requires the explicitly seeded disposable UI application database')
  const item = { ...opportunity(needId!), project_id: projectId!, name: facility!, tier: 'Signal' }
  const readCurrentNeed = async () => page.evaluate(async (selectedNeedId) => {
    const response = await fetch(`/api/opportunities/needs/${encodeURIComponent(selectedNeedId)}?tier=Signal&search=&decision=ALL`, { credentials: 'include' })
    if (!response.ok) throw new Error(`Selected Need read-back failed with ${response.status}`)
    return response.json() as Promise<Opportunity>
  }, needId!)
  await page.route('**/api/opportunities*', async (route) => {
    if (new URL(route.request().url()).pathname !== '/api/opportunities') return route.continue()
    return route.fulfill({ json: [item], headers: {
      'X-Total-Count': '1', 'X-Group-Total-Count': '1', 'X-Page-Record-Count': '1', 'X-Page-Group-Count': '1',
      'X-Limit': '50', 'X-Offset': '0', 'X-Cohort-Token': 'synthetic-browser-only-cohort',
      'X-Decision-Counts': '{"SHOW":0,"REVIEW":0,"HOLD":0}',
    } })
  })
  await page.route('**/api/health', (route) => route.fulfill({ json: { sources: [], backlog: 0, pending_interpretations: 0 } }))
  await page.route('**/api/changes', (route) => route.fulfill({ json: [] }))
  let statusPostCount = 0
  let lostStatusEventId = ''
  const statusPostBodies: Record<string, unknown>[] = []
  await page.route('**/api/needs/*/workflow-status', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    statusPostCount += 1
    statusPostBodies.push(route.request().postDataJSON() as Record<string, unknown>)
    if (statusPostCount !== 2) return route.continue()
    const response = await route.fetch()
    const saved = await response.json() as { id: string }
    lostStatusEventId = saved.id
    await route.abort('failed')
  })
  await page.goto('/?tier=Signals')
  await page.getByLabel('Password').fill(password!)
  await page.getByRole('button', { name: 'Continue' }).click()
  await page.locator(`[data-opportunity-id="${needId}"]`).click()
  await expect(page.getByText(new RegExp(`Need ${needId} · project ${projectId}`))).toBeVisible()
  const selectedNeedBefore = await readCurrentNeed()
  expect(selectedNeedBefore.tier).toBe('Signal')
  const beforeDecision = selectedNeedBefore
  expect(beforeDecision.tier).toBe('Signal')
  await expect(page.getByText('Fact history version: 0')).toBeVisible()
  await page.getByLabel('Reporter name').fill('Synthetic browser operator')
  await page.getByLabel('Reported demand (MW or bounded range)').fill('22')
  await page.getByRole('button', { name: 'Save fact draft' }).click()
  await expect(page.getByText(/Draft persisted and confirmed in this exact Need history/)).toBeVisible()
  await page.getByLabel('Reason for decision').fill('Synthetic isolated API persistence verification.')
  await page.getByRole('button', { name: 'Accept fact' }).click()
  await expect(page.getByText(/Server read-back confirmed accepted version 2/)).toBeVisible()
  const afterFact = await readCurrentNeed()
  expect(afterFact.tier).toBe(beforeDecision.tier)
  await expect(page.getByText('Fact history version: 2')).toBeVisible()
  await page.getByLabel('Set operator status').selectOption('Investigating')
  await page.getByLabel('Status reason').fill('Synthetic live status persistence verification.')
  await page.getByRole('button', { name: 'Save live status' }).click()
  await expect(page.getByText(/Live operator status Investigating was read back at version 1/)).toBeVisible()
  await page.getByLabel('Set operator status').selectOption('Contacted')
  await page.getByLabel('Status reason').fill('Synthetic lost-response idempotency verification.')
  await page.getByRole('button', { name: 'Save live status' }).click()
  await expect(page.getByRole('alert')).toContainText('unconfirmed')
  await expect(page.getByText('Current status: Contacted · version 2')).toBeVisible()
  await page.getByRole('button', { name: 'Retry same status request' }).click()
  await expect(page.getByText(/Live operator status Contacted was read back at version 2/)).toBeVisible()
  const statusReadback = await page.evaluate(async (selectedNeedId) => {
    const response = await fetch(`/api/needs/${encodeURIComponent(selectedNeedId)}/workflow-status`, { credentials: 'include' })
    if (!response.ok) throw new Error(`Workflow status read-back failed with ${response.status}`)
    return response.json() as Promise<NeedWorkflowStatus>
  }, needId!)
  expect(statusReadback.events.filter((event) => event.id === lostStatusEventId)).toHaveLength(1)
  expect(statusReadback.version).toBe(2)
  expect(statusPostBodies).toHaveLength(3)
  expect(statusPostBodies[2]).toEqual(statusPostBodies[1])
  const afterStatus = await readCurrentNeed()
  expect(afterStatus.tier).toBe(beforeDecision.tier)
  await expect(page.getByText(/Status and reason do not qualify the Need/)).toBeVisible()
})
