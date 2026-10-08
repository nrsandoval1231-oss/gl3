import { expect, test } from '@playwright/test'
import type { CommercialTriage, CommercialTriageCard } from '../src/api/client'

const base: CommercialTriage = {
  evaluated_at: '2026-10-03T14:00:00Z', policy_version: 'v1', total: 2,
  cohort_counts: { action_now: 1, research: 1, watch: 0, reject: 0 },
  daily: { evaluated: 2, surfaced: 1, contacted: 0, reached_buyer: null, qualified: null, promoted_prospects: 0, promoted_leads: 0, supported_mw: null, metric_scope: ['Counts reflect current UTC day.'], unavailable_metrics: ['Buyer authority remains unverified.'] },
  items: [
    { id: 'need-a', project_id: 'project-a', related_project_ids: ['project-a', 'project-a-related'], lifecycle_timeline: [{ state: 'Under construction', event_type: 'construction_start', date: '2026-09-28', value_kind: 'project_milestone', evidence_url: 'https://example.test/timeline', current: true, published_at: '2026-09-29', event_date_label: null }, { state: 'Planned', event_type: 'prior_plan', date: null, value_kind: 'project_milestone', evidence_url: 'https://example.test/timeline-old', current: false, published_at: null, event_date_label: null }], related_need_ids: ['need-a', 'need-a-sibling', 'need-a-closed'], related_need_states: [{ need_id: 'need-a', project_id: 'project-a', disposition: 'ACTION NOW', reason: 'Active campus construction is retained.', held: false, conflict_state: 'clear', closed: false }, { need_id: 'need-a-sibling', project_id: 'project-a', disposition: 'RESEARCH', reason: 'Sibling evidence conflicts on project stage.', held: true, conflict_state: 'conflict', closed: false }, { need_id: 'need-a-closed', project_id: 'project-a', disposition: 'WATCH', reason: 'Earlier need was closed.', held: false, conflict_state: 'clear', closed: true }], pursuit_id: 'pursuit-a', name: 'Northstar Campus', location: 'Ohio · location approximate', tier: 'Signal', activity: 'electrical-construction', industry: 'data_center', disposition: 'ACTION NOW', reason: 'A retained filing describes active campus construction.', required_mw: null, start_window: null, duration: null, supply: 'Unknown', stage: { stage: 'project_construction', date: '2026-09-28', source_url: 'https://example.test/stage', evidence_id: 'ev-stage' }, organization: 'Northstar', organization_role: 'Unknown', contacts: [], facts: [{ text: 'Construction filing accepted.', evidence_id: 'ev-1', url: 'https://example.test/fact', hash: 'abcdef1234567890', date: '2026-09-28' }], hypothesis: 'Temporary power may be needed during construction.', unknowns: ['Activity-specific load', 'Utility service timing'], blockers: ['No activity-specific MW'], next_question: 'What is the electrical load and energization window for this construction phase?', next_action: 'Verify scope and electrical package owner.', watch: null, sources: [{ text: 'Filing status: accepted.', evidence_id: 'ev-1', url: 'https://example.test/fact', hash: 'abcdef1234567890', date: '2026-09-28' }], conflict_state: 'clear', input_hash: 'hash-a', notes: [] },
    { id: 'need-b', project_id: 'project-b', related_need_ids: ['need-b'], pursuit_id: null, name: 'South Ridge Works', location: null, tier: 'Signal', activity: 'industrial expansion', industry: 'Industrial', disposition: 'RESEARCH', reason: 'An expansion announcement lacks a confirmed construction date.', required_mw: null, start_window: null, duration: null, supply: 'Unknown', stage: { stage: 'Announced', date: null, source_url: null, evidence_id: null }, organization: null, organization_role: null, contacts: [], facts: [], hypothesis: null, unknowns: ['Site address', 'Project stage'], blockers: [], next_question: 'What is the project site address and current construction stage?', next_action: 'Verify the site address and project stage.', watch: null, sources: [], conflict_state: 'clear', input_hash: 'hash-b', notes: [] },
  ],
}

async function contrastRatio(locator: import('@playwright/test').Locator) {
  return locator.evaluate((node) => {
    const channels = (value: string) => value.match(/[\d.]+/g)?.map(Number) ?? []
    const luminance = (value: string) => {
      const [red, green, blue] = channels(value).slice(0, 3).map((channel) => {
        const linear = channel / 255
        return linear <= 0.04045 ? linear / 12.92 : ((linear + 0.055) / 1.055) ** 2.4
      })
      return 0.2126 * red + 0.7152 * green + 0.0722 * blue
    }
    const foreground = getComputedStyle(node).color
    let backgroundNode: Element | null = node
    let background = 'rgb(255, 255, 255)'
    while (backgroundNode) {
      const value = getComputedStyle(backgroundNode).backgroundColor
      const components = channels(value)
      if (components.length === 3 || components[3] === 1) { background = value; break }
      backgroundNode = backgroundNode.parentElement
    }
    const [light, dark] = [luminance(foreground), luminance(background)].sort((a, b) => b - a)
    return (light + 0.05) / (dark + 0.05)
  })
}

async function useCommercialFixture(page: import('@playwright/test').Page, researchStatus = 200, failFirstNote = false) {
  let savedNote: NonNullable<CommercialTriageCard['notes']>[number] | null = null
  let receivedQuestion = ''
  let statusQuestion = ''
  let researchCalls = 0
  let statusCalls = 0
  let evaluationCalls = 0
  const noteIds: string[] = []
  await page.route('**/api/auth/session', (route) => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/health', (route) => route.fulfill({ json: {} }))
  await page.route(/\/api\/opportunities\?/, (route) => route.fulfill({ json: [] }))
  await page.route('**/api/changes', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/projects/*/buying-chain', (route) => {
    const projectId = new URL(route.request().url()).pathname.split('/')[3]
    return route.fulfill({ json: {
      project_id: projectId, status: 'available', policy_version: 'buying-chain-v2-permits', unresolved: [], runs: [], permit_summaries: [],
      candidates: projectId === 'project-a' ? [{ id: 'buyer-a', organization: 'Northstar Electric', person_name: 'Avery Chen', title: 'Project Engineer', category: 'ELECTRICAL_CONTRACTOR', organization_relationship: 'DIRECT', person_organization_relationship: 'CURRENT', person_project_relationship: 'UNKNOWN', evidence_strength: 'SUPPORTED', reason: 'A project filing names the electrical contractor.', observed_at: '2026-10-03T14:00:00Z', verified_at: null, history_count: 1, stale: false, public_contacts: [], evidence: [{ id: 'claim-a', url: 'https://example.test/buyer', quote: 'Northstar Electric is listed.', supports: 'CONTRACTOR_ROLE', extraction_location: 'Applicant section', published_at: null, observed_at: '2026-10-03T14:00:00Z', content_hash: 'hash-buyer' }] }] : [],
    } })
  })
  await page.route(/\/api\/commercial\/triage\?limit=50$/, (route) => {
    const current = structuredClone(base)
    if (savedNote) current.items[0].notes = [savedNote]
    return route.fulfill({ json: current })
  })
  await page.route('**/api/commercial/triage/evaluate', async (route) => {
    evaluationCalls += 1
    await route.fulfill({ json: base })
  })
  await page.route('**/api/pursuits/pursuit-a/notes', async (route) => {
    const body = route.request().postDataJSON() as { client_id: string; note: string; outcome: string; next_action: string }
    noteIds.push(body.client_id)
    if (failFirstNote && noteIds.length === 1) return route.fulfill({ status: 503, json: { detail: 'Temporary note response failure.' } })
    savedNote = { ...body, id: 'note-a', owner: 'Operator', created_at: '2026-10-03T14:06:00Z', follow_up: null } as NonNullable<CommercialTriageCard['notes']>[number]
    await route.fulfill({ status: 200, json: savedNote })
  })
  await page.route('**/api/commercial/triage/need-a/research', async (route) => {
    researchCalls += 1
    const body = route.request().postDataJSON() as { question: string }
    receivedQuestion = body.question
    await route.fulfill(researchStatus === 200
      ? { json: { status: 'pending', stale: false, generated_at: null, result: null, citations: [], error: null, input_tokens: 0, output_tokens: 0, job_id: 'job-a' } }
      : { status: researchStatus, json: { detail: 'Research worker unavailable.' } })
  })
  await page.route('**/api/commercial/triage/need-a/research?*', async (route) => {
    statusCalls += 1
    statusQuestion = new URL(route.request().url()).searchParams.get('question') ?? ''
    await route.fulfill({ json: statusCalls === 1
      ? { status: 'pending', job_id: 'job-a', input_hash: 'fingerprint-a', generated_at: null, result: null, citations: [], error: null }
      : { status: 'ready', job_id: 'job-a', input_hash: 'fingerprint-a', generated_at: '2026-10-03T14:05:00Z', result: { event_summary: [{ text: 'Source review confirms the filing stage.', evidence_id: 'ev-1' }], commercial_hypothesis: { text: 'Timing needs confirmation.', evidence_id: 'ev-1' }, unknowns: ['Need-specific MW remains unknown.'], next_step: 'Confirm the activity load schedule.' }, citations: [{ evidence_id: 'ev-1', url: 'https://example.test/fact', title: 'Retained filing' }], error: null } })
  })
  await page.goto('/?view=pursuits')
  return { get savedNote() { return savedNote }, get receivedQuestion() { return receivedQuestion }, get statusQuestion() { return statusQuestion }, get researchCalls() { return researchCalls }, get statusCalls() { return statusCalls }, get evaluationCalls() { return evaluationCalls }, noteIds }
}

test('commercial queue filters backend states, exposes UNKNOWN, and saves targeted research and linked notes', async ({ page }) => {
  const captured = await useCommercialFixture(page, 200, true)
  await expect(page.getByRole('heading', { name: 'What should we work today?' })).toBeVisible()
  await expect(page.getByRole('button', { name: /ACTION NOW 1/ })).toBeVisible()
  await page.getByRole('button', { name: 'Evaluate Signals' }).click()
  await expect(page.getByRole('button', { name: 'Evaluate Signals' })).toBeEnabled()
  expect(captured.evaluationCalls).toBe(1)
  await expect(page.locator('.commercial-card')).toHaveCount(1)
  await page.locator('.commercial-card-heading').click()
  await expect(page.locator('.commercial-card-facts')).toContainText('Power Unknown')
  await expect(page.locator('.commercial-card-heading')).toContainText('Data center · Electrical construction')
  await expect(page.locator('.commercial-card-facts')).toContainText('Stage Project construction')
  await expect(page.locator('.commercial-detail')).toContainText('Activity-specific load')
  await expect(page.locator('.commercial-detail')).toContainText('Construction filing accepted.')
  await expect(page.locator('.commercial-detail')).toContainText('Related need states')
  await expect(page.locator('.commercial-related-needs')).toContainText('RESEARCH · need-a-sibling · held · conflict: Conflict')
  await expect(page.locator('.commercial-related-needs')).toContainText('WATCH · need-a-closed · closed')
  await expect(page.locator('.commercial-detail')).toContainText('Group review question: What is the electrical load and energization window for this construction phase?')
  expect(await contrastRatio(page.locator('.commercial-toolbar h2'))).toBeGreaterThanOrEqual(4.5)
  expect(await contrastRatio(page.locator('.buying-chain h3').first())).toBeGreaterThanOrEqual(4.5)
  expect(await contrastRatio(page.locator('.buying-chain-note').first())).toBeGreaterThanOrEqual(4.5)
  expect(await contrastRatio(page.locator('.buying-chain a').last())).toBeGreaterThanOrEqual(4.5)
  await expect(page.getByRole('heading', { name: 'Buying chain' }).first()).toBeVisible()
  await expect(page.locator('.buying-chain')).toContainText('Avery Chen')
  await expect(page.locator('.buying-chain')).toContainText('Person → project')
  await expect(page.locator('.buying-chain')).toContainText('Project relationship unknown')
  await expect(page.locator('.commercial-project-chain')).toHaveCount(1)
  await page.getByRole('button', { name: 'Project 2 · related record' }).click()
  await expect(page.locator('.commercial-project-chain-label')).toContainText('related project record')
  await page.getByRole('button', { name: 'Project 1 · primary record' }).click()
  await expect(page.locator('.commercial-timeline')).toContainText('Under construction')
  await expect(page.locator('.commercial-timeline')).toContainText('2026-09-28')
  await expect(page.locator('.commercial-timeline')).toContainText('superseded source state')
  await expect(page.locator('.commercial-history-note')).toContainText('do not establish a verified power start window')
  await expect(page.locator('.commercial-timeline a').first()).toHaveAttribute('href', 'https://example.test/timeline')
  const question = 'What is the electrical load and energization window for this construction phase?'
  await page.getByLabel('Exact missing-fact question').fill(question)
  await page.locator('.commercial-card-heading').click()
  await page.locator('.commercial-card-heading').click()
  await expect(page.getByLabel('Exact missing-fact question')).toHaveValue(question)
  await page.locator('.commercial-filters button').nth(1).click()
  await expect(page.locator('.commercial-card-heading')).toContainText('South Ridge Works')
  await page.locator('.commercial-filters button').first().click()
  await page.getByRole('button', { name: 'Signals', exact: true }).click()
  await page.goBack()
  await expect(page.getByLabel('Exact missing-fact question')).toHaveValue(question)
  await page.getByRole('button', { name: 'Research this question' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Research result' })).toBeVisible()
  await expect(page.locator('.commercial-research-result')).toContainText('Source review confirms the filing stage.')
  await expect(page.locator('.commercial-research-result a').first()).toHaveAttribute('href', 'https://example.test/fact')
  expect(captured.receivedQuestion).toBe(question)
  expect(captured.statusQuestion).toBe(question)
  expect(captured.statusCalls).toBeGreaterThanOrEqual(2)
  expect(captured.researchCalls).toBe(1)
  const noteText = 'Operator reported a follow-up is needed.'
  await page.locator('.commercial-action textarea').nth(1).fill(noteText)
  await page.getByLabel('Reported outcome').selectOption('Reached buying organization')
  await page.locator('.commercial-card-heading').click()
  await page.locator('.commercial-card-heading').click()
  await expect(page.locator('.commercial-action textarea').nth(1)).toHaveValue(noteText)
  await page.getByLabel('Reported outcome').selectOption('Reached buying organization')
  await page.getByRole('button', { name: 'Save note' }).click()
  await expect(page.getByRole('status').filter({ hasText: '503' })).toBeVisible()
  await page.getByRole('button', { name: 'Save note' }).click()
  await expect(page.getByText('Note saved to this pursuit. Evidence tier unchanged.')).toBeVisible()
  expect(captured.savedNote?.note).toBe(noteText)
  expect(captured.noteIds).toHaveLength(2)
  expect(captured.noteIds[0]).toBe(captured.noteIds[1])
  await expect(page.locator('.commercial-note')).toContainText(noteText)
  await page.reload()
  await page.locator('.commercial-card-heading').click()
  await expect(page.locator('.commercial-note')).toContainText(noteText)
  await page.locator('.commercial-filters button').nth(1).click()
  await expect(page.locator('.commercial-card')).toHaveCount(1)
  await expect(page.locator('.commercial-card-heading')).toContainText('South Ridge Works')
  await page.getByRole('button', { name: 'Signals', exact: true }).click()
  await page.goBack()
  await expect(page.locator('.commercial-filters button').nth(1)).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('.commercial-card-heading')).toContainText('South Ridge Works')
  await page.locator('.commercial-filters button').first().click()
  await expect(page.locator('.commercial-card-heading')).toContainText('Northstar Campus')
})

test('commercial pages report all-group totals and preserve note drafts while traversing', async ({ page }) => {
  await useCommercialFixture(page)
  const firstPage: CommercialTriage = {
    ...base,
    total: 1,
    limit: 50,
    offset: 0,
    grouped_total: 51,
    next_offset: 50,
    cohort_counts: { action_now: 1, research: 0, watch: 0, reject: 0 },
    items: [base.items[0]],
  }
  const secondPage: CommercialTriage = {
    ...base,
    total: 1,
    limit: 50,
    offset: 50,
    grouped_total: 51,
    next_offset: null,
    cohort_counts: { action_now: 0, research: 1, watch: 0, reject: 0 },
    items: [base.items[1]],
  }
  await page.route(/\/api\/commercial\/triage\?/, (route) => {
    const offset = Number(new URL(route.request().url()).searchParams.get('offset') ?? 0)
    return route.fulfill({ json: offset ? secondPage : firstPage })
  })
  await page.goto('/?view=pursuits')
  await expect(page.getByText('All eligible groups').locator('..')).toContainText('51')
  await expect(page.getByText(/eligible groups overall/).first()).toContainText('51')
  await page.locator('.commercial-card-heading').first().click()
  const noteDraft = 'Keep this unsaved operator note across pages.'
  await page.locator('.commercial-action textarea').nth(1).fill(noteDraft)
  const pager = page.getByRole('navigation', { name: 'Commercial pursuit pages' })
  await pager.getByRole('button', { name: 'Next page' }).click()
  await expect(page.locator('.pursuit-position')).toHaveText('51')
  await pager.getByRole('button', { name: 'Previous page' }).click()
  await page.locator('.commercial-card-heading').first().click()
  await expect(page.locator('.commercial-action textarea').nth(1)).toHaveValue(noteDraft)
})

test('commercial targeted research reports unavailable response', async ({ page }) => {
  const captured = await useCommercialFixture(page, 503)
  await page.locator('.commercial-card-heading').click()
  await page.getByRole('button', { name: 'Research this question' }).click()
  await expect(page.getByRole('alert').filter({ hasText: '503' })).toBeVisible()
  expect(captured.receivedQuestion).toContain('energization window')
})

test('targeted research polling resumes after detail collapse without posting the question again', async ({ page }) => {
  const captured = await useCommercialFixture(page)
  await page.locator('.commercial-card-heading').click()
  await page.getByRole('button', { name: 'Research this question' }).click()
  await expect.poll(() => captured.statusCalls).toBeGreaterThan(0)
  await page.locator('.commercial-card-heading').click()
  const callsAtCollapse = captured.statusCalls
  await page.waitForTimeout(1750)
  expect(captured.statusCalls).toBe(callsAtCollapse)
  await page.locator('.commercial-card-heading').click()
  await expect(page.locator('.commercial-research-result')).toContainText('Source review confirms the filing stage.')
  expect(captured.researchCalls).toBe(1)
  expect(captured.statusQuestion).toContain('energization window')
})

test('explicit Signals entry does not request or mount hidden commercial triage', async ({ page }) => {
  let triageRequests = 0
  await page.route('**/api/auth/session', (route) => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/health', (route) => route.fulfill({ json: { sources: [], backlog: 0, pending_interpretations: 0 } }))
  await page.route('**/api/changes', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/opportunities*', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/commercial/triage*', async (route) => {
    triageRequests += 1
    await route.fulfill({ json: [] })
  })
  await page.goto('/?tier=Signals')
  await expect(page.getByRole('heading', { name: 'Signals', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'All 0' })).toBeVisible()
  await page.waitForLoadState('networkidle')
  expect(triageRequests).toBe(0)
})

test('default root previews commercial work with an explicit full queue path', async ({ page }) => {
  await page.route('**/api/auth/session', (route) => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/health', (route) => route.fulfill({ json: { sources: [], backlog: 0, pending_interpretations: 0 } }))
  await page.route('**/api/changes', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/opportunities*', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/commercial/triage?limit=50', (route) => route.fulfill({ json: base }))
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'What should we work today?' })).toBeVisible()
  await expect(page.locator('.commercial-today-entry')).toContainText('Northstar Campus')
  await expect(page.locator('.commercial-today-entry')).toContainText('Required power Unknown')
  await expect(page.getByRole('heading', { name: 'Signals', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Open full pursuit queue' }).click()
  await expect(page).toHaveURL(/view=pursuits/)
  await expect(page.getByRole('heading', { name: 'What should we work today?' })).toBeVisible()
})

test('watch-only commercial cohort is not described as empty or actionable', async ({ page }) => {
  const watchOnly = structuredClone(base)
  watchOnly.items = [{ ...watchOnly.items[0], disposition: 'WATCH', watch: { event: 'Utility service plan filing', date: '2026-11-01', source_url: 'https://example.test/watch' } }]
  watchOnly.total = 1
  watchOnly.cohort_counts = { action_now: 0, research: 0, watch: 1, reject: 0 }
  await page.route('**/api/auth/session', (route) => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/health', (route) => route.fulfill({ json: { sources: [], backlog: 0, pending_interpretations: 0 } }))
  await page.route('**/api/changes', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/opportunities*', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/commercial/triage?limit=50', (route) => route.fulfill({ json: watchOnly }))
  await page.goto('/')
  const preview = page.locator('.commercial-today-entry')
  await expect(preview).toContainText('No ACTION NOW or RESEARCH action is currently available.')
  await expect(preview).toContainText('WATCH trigger: Utility service plan filing')
  await expect(preview).not.toContainText('No candidates are currently retained')
})

test('malformed default commercial preview fails visibly without a false empty cohort', async ({ page }) => {
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  await page.route('**/api/auth/session', (route) => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/health', (route) => route.fulfill({ json: { sources: [], backlog: 0, pending_interpretations: 0 } }))
  await page.route('**/api/changes', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/opportunities*', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/commercial/triage?limit=50', (route) => route.fulfill({ json: {} }))
  await page.goto('/')
  await expect(page.locator('.commercial-today-entry').getByRole('heading', { name: 'What should we work today?' })).toBeVisible()
  await expect(page.locator('.commercial-today-entry').getByRole('alert')).toContainText('incomplete data')
  await expect(page.locator('.commercial-today-entry')).not.toContainText('No candidates are currently retained')
  await expect(page.locator('.commercial-summary')).toHaveCount(0)
  await expect(page.locator('.commercial-filters')).toHaveCount(0)
  await expect(page.locator('.commercial-list .empty')).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Signals', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'All 0' })).toBeVisible()
  expect(pageErrors).toEqual([])
})

test('commercial queue stays behind sign-in until the authenticated session is established', async ({ page }) => {
  await page.route('**/api/auth/session', (route) => route.fulfill({ status: 401, json: { detail: 'Not authenticated' } }))
  await page.route('**/api/auth/login', (route) => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/health', (route) => route.fulfill({ json: {} }))
  await page.route(/\/api\/opportunities\?/, (route) => route.fulfill({ json: [] }))
  await page.route('**/api/changes', (route) => route.fulfill({ json: [] }))
  await page.route(/\/api\/commercial\/triage\?limit=50$/, (route) => route.fulfill({ json: base }))
  await page.goto('/?view=pursuits')
  await expect(page.getByLabel('Password')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'What should we work today?' })).toHaveCount(0)
  await page.getByLabel('Password').fill('test-session')
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByRole('heading', { name: 'What should we work today?' })).toBeVisible()
})

test('saved evaluation history keeps as-of card and notes searchable after cohort departure', async ({ page }) => {
  const captured = await useCommercialFixture(page)
  const current = structuredClone(base)
  current.items = [current.items[1]]
  current.total = 1
  current.cohort_counts = { action_now: 0, research: 1, watch: 0, reject: 0 }
  current.daily.evaluated = 1
  await page.route('**/api/commercial/triage?limit=50', (route) => route.fulfill({ json: current }))
  const historyItems = [
    { pursuit_id: 'pursuit-a', need_id: 'need-a', project_id: 'project-a', related_project_ids: ['project-a-related'], disposition: 'ACTION NOW', evaluated_at: '2026-10-02T14:00:00Z', evaluated_on: '2026-10-02', input_hash: 'persisted-hash-a', snapshot_status: 'saved_as_of', live_status: 'not_rechecked', saved_card: base.items[0], notes: [{ id: 'saved-note-a', client_id: 'client-a', owner: 'Operator', created_at: '2026-10-02T14:10:00Z', note: 'Persisted operator note after displacement.', outcome: 'Reached buying organization', next_action: 'Confirm the project load.', follow_up: null }] },
    { pursuit_id: 'pursuit-old', need_id: 'need-old', project_id: 'project-old', disposition: 'REJECT', evaluated_at: null, evaluated_on: null, input_hash: null, snapshot_status: 'metadata_only', live_status: 'not_rechecked', saved_card: null, notes: [] },
  ]
  await page.route('**/api/commercial/triage/history', (route) => route.fulfill({ json: { items: historyItems, total: 2, limit: 50, offset: 0, next_offset: null } }))
  await page.route('**/api/commercial/triage/history/*', (route) => {
    const pursuitId = new URL(route.request().url()).pathname.split('/').at(-1)
    const item = historyItems.find((candidate) => candidate.pursuit_id === pursuitId)
    return route.fulfill(item ? { json: item } : { status: 404, json: { detail: 'Not found' } })
  })
  const researchReads: string[] = []
  await page.route(/\/api\/commercial\/triage\/[^/]+\/autonomous-research/, (route) => {
    const needId = new URL(route.request().url()).pathname.split('/').at(-2) ?? ''
    researchReads.push(needId)
    if (needId === 'need-old' && researchReads.filter((value) => value === needId).length === 1) {
      return route.fulfill({ status: 503, json: { detail: 'Retained research history is temporarily unavailable.' } })
    }
    return route.fulfill({ json: { items: [] } })
  })
  await page.goto('/?view=pursuits')
  await page.locator('.commercial-filters button').nth(1).click()
  await expect(page.locator('.commercial-card-heading')).toContainText('South Ridge Works')
  await expect(page.locator('.commercial-card-heading')).not.toContainText('Northstar Campus')
  const history = page.locator('details.commercial-history')
  await history.locator('summary').click()
  await expect(history.getByRole('button', { name: /Northstar Campus/ })).toBeVisible()
  await history.getByLabel('Search saved evaluations').fill('Persisted operator note')
  await expect(history.getByRole('button', { name: /Northstar Campus/ })).toBeVisible()
  await history.getByRole('button', { name: /Northstar Campus/ }).click()
  await expect(history.locator('.commercial-history-asof')).toContainText('Saved version 1: ACTION NOW')
  await expect(history.locator('.commercial-history-asof')).toContainText('current status not rechecked')
  await expect(history.locator('.commercial-history-detail')).toContainText('Construction filing accepted.')
  await expect(history.locator('.commercial-history-detail')).toContainText('Required power: Unknown')
  await expect(history.locator('.commercial-history-detail .commercial-note')).toContainText('Persisted operator note after displacement.')
  expect(researchReads).toEqual([])
  expect(captured.evaluationCalls).toBe(0)
  await history.getByRole('button', { name: 'Inspect later research attempts' }).click()
  await expect(history.getByText(/Research attempt history loaded now/)).toBeVisible()
  expect(researchReads).toEqual(['need-a'])
  await history.getByLabel('Search saved evaluations').fill('need-old')
  await expect(history.getByRole('button', { name: /Saved work · need-old/ })).toBeVisible()
  await history.getByRole('button', { name: /Saved work · need-old/ }).click()
  await expect(history.locator('.commercial-history-detail')).toContainText('Only its saved disposition and operator notes are available; facts are not reconstructed.')
  await expect(history.locator('.commercial-history-detail')).toContainText('Saved version 1: REJECT')
  await expect(history.locator('.commercial-history-detail')).not.toContainText('Construction filing accepted.')
  await expect(history.getByRole('region', { name: 'Autonomous pursuit research' })).toHaveCount(0)
  await history.getByRole('button', { name: 'Inspect later research attempts' }).click()
  await expect(history.locator('.commercial-history-detail')).toContainText('Later research attempt history is unavailable; status is UNKNOWN.')
  expect(researchReads).toEqual(['need-a', 'need-old'])
  await history.getByRole('button', { name: /Saved work · need-old/ }).click()
  await history.getByRole('button', { name: /Saved work · need-old/ }).click()
  await history.getByRole('button', { name: 'Inspect later research attempts' }).click()
  await expect(history.locator('.commercial-history-detail')).toContainText('No autonomous research questions recorded.')
  expect(researchReads).toEqual(['need-a', 'need-old', 'need-old'])
})

test('saved evaluation history traverses more than one bounded page', async ({ page }) => {
  await useCommercialFixture(page)
  const historyItem = (pursuitId: string, needId: string) => ({
    pursuit_id: pursuitId,
    need_id: needId,
    project_id: `project-${needId}`,
    disposition: 'REJECT',
    evaluated_at: null,
    evaluated_on: null,
    input_hash: null,
    snapshot_status: 'metadata_only' as const,
    live_status: 'not_rechecked' as const,
    saved_card: null,
    notes: [],
  })
  await page.route((url) => url.pathname === '/api/commercial/triage/history', (route) => {
    const offset = Number(new URL(route.request().url()).searchParams.get('offset') ?? 0)
    return route.fulfill({ json: {
      items: [offset ? historyItem('pursuit-last', 'historic-last') : historyItem('pursuit-first', 'historic-first')],
      total: 51,
      limit: 50,
      offset,
      next_offset: offset ? null : 50,
    } })
  })
  await page.goto('/?view=pursuits')
  const history = page.locator('details.commercial-history')
  await history.locator('summary').click()
  await expect(history).toContainText('Showing 1–1 of 51 saved workspaces')
  await expect(history.getByRole('button', { name: /Saved work · historic/ })).toBeVisible()
  await history.getByRole('navigation', { name: 'Saved evaluation history pages' }).getByRole('button', { name: 'Next page' }).click()
  await expect(history).toContainText('Showing 51–51 of 51 saved workspaces')
  await expect(history.getByRole('button', { name: /Saved work · historic/ })).toBeVisible()
})

test('prior saved versions remain visible when the need is still in the current cohort', async ({ page }) => {
  await useCommercialFixture(page)
  const card = structuredClone(base.items[0])
  const olderCard = { ...card, reason: 'Earlier evidence cited an announced project stage.' }
  const historyItem = {
    pursuit_id: 'pursuit-a', need_id: 'need-a', project_id: 'project-a', disposition: 'ACTION NOW', evaluated_at: '2026-10-03T14:00:00Z', evaluated_on: '2026-10-03', input_hash: 'hash-new', snapshot_status: 'saved_as_of', live_status: 'not_rechecked', saved_card: card, notes: [], versions: [
      { version: 1, disposition: 'RESEARCH', evaluated_at: '2026-10-02T14:00:00Z', evaluated_on: '2026-10-02', input_hash: 'hash-older', snapshot_status: 'saved_as_of', live_status: 'not_rechecked', saved_card: olderCard },
      { version: 2, disposition: 'ACTION NOW', evaluated_at: '2026-10-03T14:00:00Z', evaluated_on: '2026-10-03', input_hash: 'hash-new', snapshot_status: 'saved_as_of', live_status: 'not_rechecked', saved_card: card },
    ],
  }
  await page.route('**/api/commercial/triage/history', (route) => route.fulfill({ json: { items: [historyItem], total: 1, limit: 50, offset: 0, next_offset: null } }))
  await page.route('**/api/commercial/triage/history/*', (route) => route.fulfill({ json: historyItem }))
  await page.locator('.commercial-card-heading').waitFor()
  const history = page.locator('details.commercial-history')
  await history.locator('summary').click()
  await history.getByLabel('Search saved evaluations').fill('hash-older')
  const previous = history.getByRole('button', { name: /Version 1 · RESEARCH/ })
  await expect(previous).toBeVisible()
  await expect(history.getByRole('button', { name: /Version 2 · ACTION NOW/ })).toHaveCount(0)
  await previous.click()
  await expect(history.locator('.commercial-history-asof')).toContainText('Saved version 1: RESEARCH')
  await expect(history.locator('.commercial-history-detail')).toContainText('Earlier evidence cited an announced project stage.')
})
