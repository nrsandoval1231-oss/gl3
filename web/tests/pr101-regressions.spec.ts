import { expect, test } from '@playwright/test'

const need = {
  id: 'need-a', project_id: 'project-a', name: 'Austin data center', location: 'Austin, TX', tier: 'Signal',
  workflow_status: 'UNKNOWN', activity: 'construction', rationale: 'A retained construction filing supports investigation.',
  signal_display_decision: 'SHOW', signal_display_decision_state: 'adjudicated', signal_evidence_state: 'active_evidence',
  required_mw: null, supply: 'Unknown', start_window: null, duration: null, conflict_state: 'clear',
  project_identity_key: 'project-a', group_id: 'project-a', commercial_disposition: 'RESEARCH',
  commercial_reason: 'A retained construction filing supports investigation.', commercial_next_question: 'Who owns the electrical scope?',
  commercial_next_action: 'Confirm the package owner.', evidence: [{ id: 'evidence-a', title: 'Construction filing', url: 'https://example.test/filing',
    published_at: '2026-10-01', retrieved_at: '2026-10-02T00:00:00Z', extraction_location: 'Description', content_hash: 'a'.repeat(64),
    event_date: null, event_date_label: 'Unknown', source_id: 'city-permits', document_number: 'permit-1', source_origin: 'City', abstract: 'A construction filing.', assessment_current: true }],
} as const

const secondNeed = { ...need, id: 'need-b', name: 'Dallas data center', project_id: 'project-b', group_id: 'project-b', location: 'Dallas, TX' }
const workspaceResponse = (items: readonly unknown[] = [need]) => ({ items, total: items.length, counts: { action_now: 0, research: items.length, watch: 0, reject: 0 }, offset: 0, limit: 25, next_offset: null, cohort_token: 'workspace-token', count_unit: 'power needs', changes_available: false })
const emptyChanges = { items: [], counts: { discovered: 0, changed: 0, promoted: 0, closed: 0, review_exception: 0 }, total_unreviewed: 0, offset: 0, limit: 50, next_offset: null, evaluated_at: '2026-10-20T12:00:00Z', baseline_identity: '00000000-0000-4000-8000-000000000001', baseline_reviewed_at: null, first_use: true, token: 'a'.repeat(64), source_health_exceptions: [] }

async function authenticated(page: import('@playwright/test').Page) {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
}

function opportunityHeaders(token: string, offset: number, nextOffset: number | null) {
  return {
    'X-Total-Count': '1', 'X-Group-Total-Count': '1', 'X-Page-Record-Count': '1', 'X-Page-Group-Count': '1',
    'X-Limit': '25', 'X-Offset': String(offset), 'X-Cohort-Token': token,
    'X-Decision-Counts': JSON.stringify({ SHOW: 1, REVIEW: 0, HOLD: 0 }),
    ...(nextOffset == null ? {} : { 'X-Next-Offset': String(nextOffset) }),
  }
}

test('legacy environment links preserve supported tab, lens, tier, and grouped browse offset', async ({ page }) => {
  await authenticated(page)
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: workspaceResponse() }))
  let detailReads = 0
  await page.route('**/api/opportunities/needs/need-a*', route => { detailReads += 1; return route.fulfill({ json: need }) })
  const browseRequests: URL[] = []
  await page.route('**/api/opportunities?*', route => {
    const url = new URL(route.request().url())
    browseRequests.push(url)
    const offset = Number(url.searchParams.get('offset') ?? 0)
    return route.fulfill({ status: 200, contentType: 'application/json', headers: opportunityHeaders('legacy-page', offset, null), body: JSON.stringify([need]) })
  })

  await page.goto('/environment?view=environment&mode=evidence&need=need-a&lens=data_center')
  await expect.poll(() => {
    const params = new URL(page.url()).searchParams
    return [params.get('view'), params.get('industry'), params.get('section'), params.get('need')]
  }).toEqual(['workspace', 'data_center', 'evidence', 'need-a'])
  await expect.poll(() => detailReads).toBeGreaterThan(0)
  await expect(page.locator('.wh-detail').getByRole('button', { name: 'Evidence', exact: true })).toHaveClass(/active/)
  await expect(page.locator('.wh-evidence-table').getByRole('link', { name: 'Construction filing' })).toBeVisible()
  await page.goto('/environment?view=environment&mode=browse&level=Leads&lens=data_center&records=50')
  await expect(page.getByRole('heading', { name: 'Leads' })).toBeVisible()
  await expect.poll(() => new URL(page.url()).searchParams.get('offset')).toBe('50')
  await expect.poll(() => new URL(page.url()).searchParams.get('industry')).toBe('data_center')
  const browseQueries = browseRequests.map(url => Object.fromEntries(url.searchParams.entries()))
  await expect.poll(() => browseRequests.some(url => url.searchParams.get('offset') === '50' && url.searchParams.get('tier') === 'Lead' && url.searchParams.get('industry') === 'data_center'), { message: JSON.stringify(browseQueries) }).toBe(true)
})

test('active Operations navigation keeps the filtered inbox URL and readback aligned', async ({ page }) => {
  await authenticated(page)
  await page.route('**/api/health', route => route.fulfill({ json: { sources: [{ id: 'city-permits' }], backlog: 0, pending_interpretations: 0 } }))
  const requests: URL[] = []
  await page.route('**/api/ingestion?*', route => {
    requests.push(new URL(route.request().url()))
    return route.fulfill({ json: { items: [], total: 30, limit: 25, offset: Number(new URL(route.request().url()).searchParams.get('offset')) } })
  })
  await page.goto('/?view=ingestion&source=city-permits&vertical=data-centers&offset=25')
  await expect(page.getByLabel('Filter by source', { exact: true })).toHaveValue('city-permits')
  await expect(page.getByLabel('Filter by source sector', { exact: true })).toHaveValue('data-centers')
  const before = new URL(page.url()).search
  await page.getByRole('button', { name: 'Operations', exact: true }).click()
  expect(new URL(page.url()).search).toBe(before)
  await page.reload()
  await expect(page.getByLabel('Filter by source', { exact: true })).toHaveValue('city-permits')
  await expect(page.getByLabel('Filter by source sector', { exact: true })).toHaveValue('data-centers')
  await expect.poll(() => requests.at(-1)?.searchParams.get('offset')).toBe('25')
})

test('queue keeps commercial disposition separate from qualification and scopes briefing counts', async ({ page }) => {
  await authenticated(page)
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: workspaceResponse() }))
  await page.route('**/api/opportunities/workspace/changes?*', route => route.fulfill({ json: emptyChanges }))
  await page.goto('/')
  await expect(page.locator('.wh-queue-meta')).toContainText('Signal')
  await expect(page.locator('.wh-queue-meta')).toContainText('RESEARCH')
  await expect(page.locator('.wh-briefing-scope')).toContainText('ignore the selected disposition')
})

test('brief busy state follows the selected need when an earlier request is pending', async ({ page }) => {
  await authenticated(page)
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: workspaceResponse([need, secondNeed]) }))
  await page.route('**/api/opportunities/needs/*', route => route.fulfill({ json: route.request().url().includes('need-b') ? secondNeed : need }))
  let releaseFirst!: () => void
  const firstPostHeld = new Promise<void>(resolve => { releaseFirst = resolve })
  await page.route('**/api/power-needs/*/brief', async route => {
    const isFirst = route.request().url().includes('need-a')
    if (route.request().method() === 'GET') return route.fulfill({ json: { status: 'unavailable', stale: false, result: null, citations: [] } })
    if (isFirst) await firstPostHeld
    return route.fulfill({ json: { status: 'pending', stale: false, result: null, citations: [], job_id: isFirst ? 'job-a' : 'job-b' } })
  })
  await page.goto('/')
  await page.locator('[data-need-row="need-a"]').click()
  await page.locator('.wh-record-actions').getByRole('button', { name: 'Update workflow' }).click()
  await page.getByRole('button', { name: 'Generate or retry brief' }).click()
  await page.locator('[data-need-row="need-b"]').click()
  await expect(page.locator('.wh-detail').getByRole('heading', { name: 'Dallas data center' })).toBeVisible()
  await page.locator('.wh-record-actions').getByRole('button', { name: 'Update workflow' }).click()
  await expect(page.getByRole('button', { name: 'Generate or retry brief' })).toBeEnabled()
  releaseFirst()
})

test('a superseded brief POST cannot clear a later request for the same Need', async ({ page }) => {
  await authenticated(page)
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: workspaceResponse([need, secondNeed]) }))
  await page.route('**/api/opportunities/needs/*', route => route.fulfill({ json: route.request().url().includes('need-b') ? secondNeed : need }))
  const releases: Array<() => void> = []
  let postCount = 0
  await page.route('**/api/power-needs/need-a/brief', async route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: { status: 'unavailable', stale: false, result: null, citations: [] } })
    postCount += 1
    await new Promise<void>(resolve => releases.push(resolve))
    return route.fulfill({ json: { status: 'pending', stale: false, result: null, citations: [], job_id: `job-a-${postCount}` } })
  })
  await page.goto('/')
  await page.locator('[data-need-row="need-a"]').click()
  await page.locator('.wh-record-actions').getByRole('button', { name: 'Update workflow' }).click()
  await page.getByRole('button', { name: 'Generate or retry brief' }).click()
  await expect.poll(() => postCount).toBe(1)
  await page.locator('[data-need-row="need-b"]').click()
  await page.locator('[data-need-row="need-a"]').click()
  await page.locator('.wh-record-actions').getByRole('button', { name: 'Update workflow' }).click()
  await page.getByRole('button', { name: 'Generate or retry brief' }).click()
  await expect.poll(() => postCount).toBe(2)

  const firstResponse = page.waitForResponse(response => response.request().method() === 'POST' && response.url().includes('/api/power-needs/need-a/brief'))
  releases[0]()
  await firstResponse
  await page.waitForTimeout(0)
  const requestButton = page.getByRole('button', { name: 'Requesting\u2026' })
  await expect(requestButton).toBeDisabled()
  releases[1]()
  await expect(page.getByRole('status').filter({ hasText: 'Generating from retained public evidence\u2026' })).toBeVisible()
})

test('pending brief status can be retried after a transient status read failure', async ({ page }) => {
  await authenticated(page)
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: workspaceResponse() }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: need }))
  let requested = false
  let postSeen = false
  let postCount = 0
  let failedPendingPoll = false
  const ready = { status: 'ready', stale: false, generated_at: '2026-10-21T00:00:00Z', result: { event_summary: [{ text: 'The permit supports construction.', evidence_id: 'ev-a' }], unknowns: [], next_step: 'Confirm timing.' }, citations: [], error: null }
  await page.route('**/api/power-needs/need-a/brief', async route => {
    if (route.request().method() === 'POST') { postSeen = true; postCount += 1; return route.fulfill({ json: { status: 'pending', stale: false, result: null, citations: [], job_id: 'brief-a' } }) }
    if (!postSeen) return route.fulfill({ json: { status: 'unavailable', stale: false, result: null, citations: [] } })
    if (!failedPendingPoll) { failedPendingPoll = true; return route.fulfill({ status: 503, json: { detail: 'Temporary status failure' } }) }
    requested = true
    return route.fulfill({ json: ready })
  })
  await page.goto('/')
  await page.locator('[data-need-row="need-a"]').click()
  await page.locator('.wh-record-actions').getByRole('button', { name: 'Update workflow' }).click()
  await page.getByRole('button', { name: 'Generate or retry brief' }).click()
  await expect(page.getByRole('button', { name: 'Retry brief status' })).toBeVisible({ timeout: 5000 })
  await page.getByRole('button', { name: 'Retry brief status' }).click()
  await expect.poll(() => requested).toBeTruthy()
  expect(postCount).toBe(1)
  await expect(page.getByText('The permit supports construction.')).toBeVisible()
})

test('Signals fact workflow readback refreshes the cohort before exact-Need retry', async ({ page }) => {
  await authenticated(page)
  let browseCount = 0
  let workflowSaved = false
  const detailScopeTokens: string[] = []
  const postSaveDetailScopeTokens: string[] = []
  await page.route('**/api/opportunities?*', route => {
    browseCount += 1
    const token = workflowSaved ? 'cohort-new' : 'cohort-old'
    return route.fulfill({ status: 200, contentType: 'application/json', headers: opportunityHeaders(token, 0, null), body: JSON.stringify([need]) })
  })
  await page.route('**/api/opportunities/needs/need-a*', route => {
    const token = new URL(route.request().url()).searchParams.get('cohort_token') ?? ''
    detailScopeTokens.push(token)
    if (workflowSaved) postSaveDetailScopeTokens.push(token)
    if (workflowSaved && token === 'cohort-old') return route.fulfill({ status: 409, json: { detail: 'Signal cohort changed; refresh and reopen this need.' } })
    return route.fulfill({ status: 200, json: need })
  })
  let workflowStatus = { status: 'UNKNOWN', version: 0, events: [] as Record<string, unknown>[] }
  await page.route('**/api/needs/need-a/facts?*', route => route.fulfill({ json: { items: [], total: 0, limit: 50, offset: 0, next_offset: null, current_fact_version: 0, current_reported_timing_correction_target: { available: false, unavailable_reason: 'no_current_admitted_lead', need_id: 'need-a', project_id: 'project-a', project_identity_key: null, activity_key: 'construction', facility_identity: null, source_semantic_hash: null, source_evidence_hash: null, retained_evidence_id: null, source_id: null, earliest_possible_start: null, latest_possible_start: null, minimum_duration_days: null, maximum_duration_days: null, current_fact_version: 0 } } }))
  await page.route('**/api/needs/need-a/workflow-status', async route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: workflowStatus })
    const body = route.request().postDataJSON() as Record<string, unknown>
    workflowSaved = true
    workflowStatus = { status: String(body.status), version: 1, events: [{ id: 'event-1', need_id: 'need-a', project_id: 'project-a', pursuit_id: null, version: 1, status: body.status, previous_status: null, expected_version: 0, reason: body.reason, content_hash: 'b'.repeat(64), actor: 'Operator', created_at: '2026-10-21T00:00:00Z' }] }
    return route.fulfill({ json: workflowStatus.events[0] })
  })
  await page.goto('/?view=signals')
  await page.getByRole('button', { name: /Austin data center/ }).click()
  await page.locator('.wh-record-actions').getByRole('button', { name: 'Update workflow' }).click()
  await page.getByLabel('Set operator status').selectOption('Investigating')
  await page.getByLabel('Status reason').fill('Confirm the site package with the operator.')
  const browseRequestsBeforeSave = browseCount
  await page.getByRole('button', { name: 'Save live status' }).click()
  await expect.poll(() => browseCount).toBeGreaterThan(browseRequestsBeforeSave)
  await expect.poll(() => detailScopeTokens.at(-1)).toBe('cohort-new')
  expect(postSaveDetailScopeTokens.every(token => token === 'cohort-new')).toBe(true)
  await expect(page.getByRole('link', { name: 'Download filtered CSV' })).toHaveAttribute('href', /cohort_token=cohort-new/)
  await expect(page.locator('.wh-detail').getByRole('heading', { name: 'Austin data center' })).toBeVisible()
})
