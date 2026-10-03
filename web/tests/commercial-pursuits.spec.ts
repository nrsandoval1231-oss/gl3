import { expect, test } from '@playwright/test'
import type { CommercialTriage, CommercialTriageCard } from '../src/api/client'

const base: CommercialTriage = {
  evaluated_at: '2026-10-03T14:00:00Z', policy_version: 'v1', total: 2,
  cohort_counts: { action_now: 1, research: 1, watch: 0, reject: 0 },
  daily: { evaluated: 2, surfaced: 1, contacted: 0, reached_buyer: null, qualified: null, promoted_prospects: 0, promoted_leads: 0, supported_mw: null, metric_scope: ['Counts reflect current UTC day.'], unavailable_metrics: ['Buyer authority remains unverified.'] },
  items: [
    { id: 'need-a', project_id: 'project-a', related_project_ids: ['project-a', 'project-a-related'], lifecycle_timeline: [{ state: 'Under construction', event_type: 'construction_start', date: '2026-09-28', value_kind: 'project_milestone', evidence_url: 'https://example.test/timeline', current: true, published_at: '2026-09-29', event_date_label: null }, { state: 'Planned', event_type: 'prior_plan', date: null, value_kind: 'project_milestone', evidence_url: 'https://example.test/timeline-old', current: false, published_at: null, event_date_label: null }], related_need_ids: ['need-a'], pursuit_id: 'pursuit-a', name: 'Northstar Campus', location: 'Ohio · location approximate', tier: 'Signal', activity: 'electrical-construction', industry: 'data_center', disposition: 'ACTION NOW', reason: 'A retained filing describes active campus construction.', required_mw: null, start_window: null, duration: null, supply: 'Unknown', stage: { stage: 'project_construction', date: '2026-09-28', source_url: 'https://example.test/stage', evidence_id: 'ev-stage' }, organization: 'Northstar', organization_role: 'Unknown', contacts: [], facts: [{ text: 'Construction filing accepted.', evidence_id: 'ev-1', url: 'https://example.test/fact', hash: 'abcdef1234567890', date: '2026-09-28' }], hypothesis: 'Temporary power may be needed during construction.', unknowns: ['Activity-specific load', 'Utility service timing'], blockers: ['No activity-specific MW'], next_question: 'What is the electrical load and energization window for this construction phase?', next_action: 'Verify scope and electrical package owner.', watch: null, sources: [{ text: 'Filing status: accepted.', evidence_id: 'ev-1', url: 'https://example.test/fact', hash: 'abcdef1234567890', date: '2026-09-28' }], conflict_state: 'clear', input_hash: 'hash-a', notes: [] },
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
    const body = route.request().postDataJSON() as { question: string }
    receivedQuestion = body.question
    await route.fulfill(researchStatus === 200
      ? { json: { status: 'ready', stale: false, generated_at: '2026-10-03T14:05:00Z', result: { event_summary: [{ text: 'Source review confirms the filing stage.', evidence_id: 'ev-1' }], commercial_hypothesis: { text: 'Timing needs confirmation.', evidence_id: 'ev-1' }, unknowns: ['Need-specific MW remains unknown.'], next_step: 'Confirm the activity load schedule.' }, citations: [{ evidence_id: 'ev-1', url: 'https://example.test/fact', title: 'Retained filing' }], error: null, input_tokens: 0, output_tokens: 0, job_id: 'job-a' } }
      : { status: researchStatus, json: { detail: 'Research worker unavailable.' } })
  })
  await page.goto('/?view=pursuits')
  return { get savedNote() { return savedNote }, get receivedQuestion() { return receivedQuestion }, get evaluationCalls() { return evaluationCalls }, noteIds }
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

test('commercial targeted research reports unavailable response', async ({ page }) => {
  const captured = await useCommercialFixture(page, 503)
  await page.locator('.commercial-card-heading').click()
  await page.getByRole('button', { name: 'Research this question' }).click()
  await expect(page.getByRole('alert').filter({ hasText: '503' })).toBeVisible()
  expect(captured.receivedQuestion).toContain('energization window')
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

test('malformed default triage response shows unavailable state and Signals remains usable', async ({ page }) => {
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  await page.route('**/api/auth/session', (route) => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/health', (route) => route.fulfill({ json: { sources: [], backlog: 0, pending_interpretations: 0 } }))
  await page.route('**/api/changes', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/opportunities*', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/commercial/triage?limit=50', (route) => route.fulfill({ json: {} }))
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'What should we work today?' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Commercial pursuits are unavailable' })).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('returned incomplete data')
  await expect(page.locator('.commercial-summary')).toHaveCount(0)
  await expect(page.locator('.commercial-filters')).toHaveCount(0)
  await expect(page.locator('.commercial-list .empty')).toHaveCount(0)
  await expect(page.getByRole('heading', { name: /No action now pursuits/ })).toHaveCount(0)
  await page.getByRole('button', { name: 'Signals', exact: true }).click()
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
  await page.goto('/')
  await expect(page.getByLabel('Password')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'What should we work today?' })).toHaveCount(0)
  await page.getByLabel('Password').fill('test-session')
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByRole('heading', { name: 'What should we work today?' })).toBeVisible()
})

test('saved evaluation history keeps as-of card and notes searchable after cohort departure', async ({ page }) => {
  await useCommercialFixture(page)
  const current = structuredClone(base)
  current.items = [current.items[1]]
  current.total = 1
  current.cohort_counts = { action_now: 0, research: 1, watch: 0, reject: 0 }
  current.daily.evaluated = 1
  await page.route('**/api/commercial/triage?limit=50', (route) => route.fulfill({ json: current }))
  await page.route('**/api/commercial/triage/history', (route) => route.fulfill({ json: { items: [
    { pursuit_id: 'pursuit-a', need_id: 'need-a', project_id: 'project-a', related_project_ids: ['project-a-related'], disposition: 'ACTION NOW', evaluated_at: '2026-10-02T14:00:00Z', evaluated_on: '2026-10-02', input_hash: 'persisted-hash-a', snapshot_status: 'saved_as_of', live_status: 'not_rechecked', saved_card: base.items[0], notes: [{ id: 'saved-note-a', client_id: 'client-a', owner: 'Operator', created_at: '2026-10-02T14:10:00Z', note: 'Persisted operator note after displacement.', outcome: 'Reached buying organization', next_action: 'Confirm the project load.', follow_up: null }] },
    { pursuit_id: 'pursuit-old', need_id: 'need-old', project_id: 'project-old', disposition: 'REJECT', evaluated_at: null, evaluated_on: null, input_hash: null, snapshot_status: 'metadata_only', live_status: 'not_rechecked', saved_card: null, notes: [] },
  ] } }))
  await page.goto('/?view=pursuits')
  await page.locator('.commercial-filters button').nth(1).click()
  await expect(page.locator('.commercial-card-heading')).toContainText('South Ridge Works')
  await expect(page.locator('.commercial-card-heading')).not.toContainText('Northstar Campus')
  const history = page.locator('.commercial-history')
  await history.locator('summary').click()
  await expect(history.getByRole('button', { name: /Northstar Campus/ })).toBeVisible()
  await history.getByLabel('Search saved evaluations').fill('Persisted operator note')
  await expect(history.getByRole('button', { name: /Northstar Campus/ })).toBeVisible()
  await history.getByRole('button', { name: /Northstar Campus/ }).click()
  await expect(history.locator('.commercial-history-asof')).toContainText('Saved evaluation: ACTION NOW')
  await expect(history.locator('.commercial-history-asof')).toContainText('current status not rechecked')
  await expect(history.locator('.commercial-history-detail')).toContainText('Construction filing accepted.')
  await expect(history.locator('.commercial-history-detail')).toContainText('Required power: Unknown')
  await expect(history.locator('.commercial-history-detail .commercial-note')).toContainText('Persisted operator note after displacement.')
  await history.getByLabel('Search saved evaluations').fill('need-old')
  await expect(history.getByRole('button', { name: /Saved work · need-old/ })).toBeVisible()
  await history.getByRole('button', { name: /Saved work · need-old/ }).click()
  await expect(history.locator('.commercial-history-detail')).toContainText('Only its saved disposition and operator notes are available; facts are not reconstructed.')
  await expect(history.locator('.commercial-history-detail')).toContainText('Saved evaluation: REJECT')
  await expect(history.locator('.commercial-history-detail')).not.toContainText('Construction filing accepted.')
})
