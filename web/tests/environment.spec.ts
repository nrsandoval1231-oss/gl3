import { expect, test, type Page, type Route } from '@playwright/test'
import type { Opportunity } from '../src/api/client'

// Test-only fixtures. They exercise layout and navigation, never production data.
const stamp = '2026-10-01T12:00:00Z'
const evidence = (n: number): Opportunity['evidence'][number] => ({
  source_id: 'test-source', document_number: `DOC-${n}`, content_hash: `fixturehash${n}0000`,
  url: `https://example.com/${n}`, title: `Test evidence ${n}`, published_at: null,
  event_date: '2026-09-30', event_date_label: 'Permit issue date', retrieved_at: stamp,
  abstract: 'Test-only abstract.', extraction_location: 'row', assessment_current: true,
} as Opportunity['evidence'][number])
const opportunity = (id: string, location: string | null): Opportunity => ({
  id, project_id: id, name: `Test project ${id}`, location, tier: 'Signal', workflow_status: 'UNKNOWN',
  activity: 'construction-power', rationale: 'Test rationale.', assessment_reason: 'Test assessment.',
  brief_status: 'unavailable', brief_stale: false, required_mw: null, start_window: null, duration: null,
  supply: 'Unknown', next_action: `Test next action ${id}.`, conflict_state: 'None recorded',
  title_company: `Test project ${id}`,
  signal_display_decision: 'SHOW', signal_display_decision_state: 'adjudicated', signal_evidence_state: 'active_evidence',
  missing_facts: ['Activity-specific load (MW)'], asset_type: 'data_center', evidence: [evidence(1), evidence(2)],
} as Opportunity)

async function mock(page: Page, items: Opportunity[], opportunities?: (route: Route) => Promise<void>, mapWindow?: (route: Route) => Promise<void>) {
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (!path.startsWith('/api/')) return route.continue()
    if (path === '/api/opportunities' && opportunities) return opportunities(route)
    if (path === '/api/opportunities/map-window' && mapWindow) return mapWindow(route)
    const json = (body: unknown, headers: Record<string, string> = {}) =>
      route.fulfill({ contentType: 'application/json', headers, body: JSON.stringify(body) })
    if (path === '/api/auth/session') return json({ authenticated: true })
    if (path === '/api/opportunities/workspace') {
      const params = new URL(route.request().url()).searchParams
      const offset = Number(params.get('offset') ?? 0), limit = 25
      const filtered = items.filter(item => (!params.get('tier') || item.tier === params.get('tier')) && (!params.get('geography') || item.location === params.get('geography')) && (!params.get('industry') || item.asset_type === params.get('industry')) && (!params.get('search') || `${item.name} ${item.location}`.toLowerCase().includes(params.get('search')!.toLowerCase())))
      return json({ items: filtered.slice(offset, offset + limit), total: filtered.length, counts: { action_now: 0, research: 0, watch: 0, reject: 0 }, offset, limit, next_offset: offset + limit < filtered.length ? offset + limit : null, cohort_token: 'workspace-fixture', count_unit: 'power needs', changes_available: false })
    }
    if (path === '/api/opportunities/workspace/changes') return json({ items: [], counts: { discovered: 0, changed: 0, promoted: 0, closed: 0, review_exception: 0 }, total_unreviewed: 0, offset: 0, limit: 50, next_offset: null, evaluated_at: stamp, baseline_identity: '00000000-0000-4000-8000-000000000001', baseline_reviewed_at: null, first_use: true, token: 'a'.repeat(64), source_health_exceptions: [] })
    if (path === '/api/opportunities') {
      const url = new URL(route.request().url())
      const limit = Number(url.searchParams.get('limit'))
      if (limit > 50) return route.fulfill({ status: 422, body: 'limit above API maximum' })
      const offset = Number(url.searchParams.get('offset') ?? 0)
      const pageItems = items.slice(offset, offset + limit)
      const next: Record<string, string> = offset + limit < items.length ? { 'X-Next-Offset': String(offset + limit) } : {}
      return json(pageItems, { 'X-Total-Count': String(items.length), 'X-Cohort-Token': 'c1', ...next })
    }
    if (path === '/api/opportunities/map-window') {
      const loaded = items.slice(0, 200)
      return json({ items: loaded, total_count: items.length, loaded_count: loaded.length,
        is_subset: loaded.length < items.length, window_limit: 200, group_total_count: items.length,
        cohort_token: 'map-cohort', decision_counts: { SHOW: 0, REVIEW: 0, HOLD: 0 } })
    }
    if (path.startsWith('/api/opportunities/needs/')) {
      const item = items.find((item) => item.id === path.split('/').at(-1))
      const tier = new URL(route.request().url()).searchParams.get('tier')
      return item && (!tier || item.tier === tier) ? json(item) : route.fulfill({ status: 404 })
    }
    if (path === '/api/ingestion') return json({ items: [], total: 0, limit: 25, offset: 0, next_offset: null })
    if (path === '/api/health') return json({ sources: [{ id: 's', enabled: true, status: 'Updated' }], backlog: 0, pending_interpretations: 0 })
    if (route.request().method() === 'GET' && path === '/api/intelligence/tasks') return json({ items: [] })
    if (route.request().method() === 'GET' && /^\/api\/intelligence\/needs\/[^/]+\/history$/.test(path)) return json({ items: [] })
    if (path.endsWith('/buying-chain')) return json({ project_id: 'a', status: 'complete', policy_version: 'v1', unresolved: [], runs: [], candidates: [] })
    if (path.endsWith('/facts')) {
      return json({
        items: [], total: 0, limit: 50, offset: 0, next_offset: null, current_fact_version: 0,
        current_reported_timing_correction_target: {
          available: false, unavailable_reason: 'no_current_admitted_lead', need_id: 'a',
          project_id: null, project_identity_key: null, activity_key: null, facility_identity: null,
          source_semantic_hash: null, source_evidence_hash: null, retained_evidence_id: null,
          source_id: null, earliest_possible_start: null, latest_possible_start: null,
          minimum_duration_days: null, maximum_duration_days: null, current_fact_version: 0,
        },
      })
    }
    if (path.endsWith('/workflow-status')) return json({ status: 'UNKNOWN', version: 0, events: [] })
    return json([])
  })
}

async function commercialEnvironment(page: Page, pursuitId: string | null = 'pursuit-a') {
  await mock(page, [opportunity('a', 'Austin, TX')])
  const item = { id: 'a', project_id: 'a', pursuit_id: pursuitId, name: 'Commercial fixture A', location: 'Austin, TX', tier: 'Signal', activity: 'construction-power', industry: 'data_center', disposition: 'ACTION NOW', reason: 'Fixture reason', supply: 'Unknown', next_question: 'What is the activity-specific construction load?', next_action: 'Confirm the package buyer.', stage: { stage: 'construction', date: null }, facts: [], contacts: [], sources: [], notes: [], unknowns: [], blockers: [] }
  await page.route('**/api/commercial/triage?*', (route) => route.fulfill({ json: {
    evaluated_at: '2026-10-01T12:00:00Z', policy_version: 'fixture', total: 1, grouped_total: 1, offset: 0, limit: 50, next_offset: null,
    cohort_counts: { action_now: 1, research: 0, watch: 0, reject: 0 }, daily: { evaluated: 1, surfaced: 1, contacted: 0 }, items: [item],
  } }))
  return item
}


test('canonical queue keeps geographically unknown records reachable and restores selected need', async ({ page }) => {
  await mock(page, [opportunity('a', 'Austin, TX'), opportunity('d', null)])
  await page.goto('/environment')
  await expect(page.getByRole('heading', { name: 'Opportunity Intelligence' })).toBeVisible()
  await expect(page.getByRole('button', { name: /Test project d/ })).toBeVisible()
  await page.getByRole('button', { name: /Test project a/ }).click()
  await expect(page.locator('.wh-record-identity h2')).toHaveText('Test project a')
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  await expect(page.getByRole('link', { name: 'Test evidence 2' })).toBeVisible()
  await page.getByRole('button', { name: /Back to power needs/ }).click()
  await expect(page.getByRole('button', { name: /Test project d/ })).toBeVisible()
  await page.goForward()
  await expect(page.locator('.wh-record-identity h2')).toHaveText('Test project a')
})

test('legacy action deep link restores selected need and an unsent call preparation', async ({ page }) => {
  await mock(page, [opportunity('a', 'Austin, TX')])
  const writes: string[] = []
  page.on('request', request => { if (request.method() === 'POST') writes.push(request.url()) })
  await page.goto('/environment?view=environment&mode=action&state=Texas&need=a')
  await expect(page.locator('.wh-record-identity h2')).toHaveText('Test project a')
  await expect(page.getByRole('heading', { name: 'Prepare the call' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Call preparation' }).getByText('Test next action a.')).toBeVisible()
  expect(writes).toEqual([])
})

test('legacy environment URL reaches the canonical queue without map requests', async ({ page }) => {
  const requests: string[] = []
  await mock(page, [opportunity('a', 'Austin, TX'), opportunity('dc', 'Washington, DC')])
  page.on('request', request => requests.push(new URL(request.url()).pathname))
  await page.goto('/environment')
  await expect(page.getByRole('heading', { name: 'Opportunity Intelligence' })).toBeVisible()
  await expect(page.getByRole('button', { name: /Test project dc/ })).toBeVisible()
  expect(requests).toContain('/api/opportunities/workspace')
  expect(requests).not.toContain('/api/opportunities/map-window')
})

test('canonical queue uses bounded server pagination instead of map-window data', async ({ page }) => {
  const requests: URL[] = []
  await mock(page, Array.from({ length: 60 }, (_, i) => opportunity(`n${i}`, 'Austin, TX')))
  page.on('request', request => requests.push(new URL(request.url())))
  await page.goto('/environment')
  await expect(page.getByText('Showing 1–25 of 60')).toBeVisible()
  await page.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(page.getByText('Showing 26–50 of 60')).toBeVisible()
  expect(requests.some(url => url.pathname === '/api/opportunities/workspace' && url.searchParams.get('offset') === '25')).toBe(true)
  expect(requests.some(url => url.pathname === '/api/opportunities/map-window')).toBe(false)
})

test('commercial pursuit investigation returns to its note and selected need without writes', async ({ page }) => {
  await commercialEnvironment(page)
  const writes: string[] = []
  page.on('request', (request) => { if (request.method() === 'POST') writes.push(request.url()) })
  await page.goto('/?view=pursuits')
  await page.getByLabel('Search commercial pursuits on this page').fill('fixture')
  await page.getByRole('button', { name: /Commercial fixture A/ }).click()
  await page.getByLabel('Note', { exact: true }).fill('Unsaved commercial note')
  await page.getByRole('button', { name: 'Investigate this need' }).click()
  await expect(page.getByRole('heading', { name: 'Test project a', exact: true })).toBeVisible()
  await page.goBack()
  await expect(page.getByLabel('Search commercial pursuits on this page')).toHaveValue('fixture')
  await expect(page.getByLabel('Note', { exact: true })).toHaveValue('Unsaved commercial note')
  await expect(page.getByRole('button', { name: 'Investigate this need' })).toBeFocused()
  await page.reload()
  await expect(page.getByLabel('Search commercial pursuits on this page')).toHaveValue('fixture')
  await expect(page.getByLabel('Note', { exact: true })).toHaveValue('Unsaved commercial note')
  expect(writes).toEqual([])
})

test('commercial pending note save survives investigation without duplicate submission', async ({ page }) => {
  await commercialEnvironment(page)
  let release!: () => void
  const gate = new Promise<void>((resolve) => { release = resolve })
  let posts = 0
  await page.route('**/api/pursuits/pursuit-a/notes', async (route) => {
    posts += 1
    await gate
    await route.fulfill({ json: {} })
  })
  await page.goto('/environment?view=environment&mode=pursuits&pursuitNeed=a')
  await page.getByLabel('Note', { exact: true }).fill('Save exactly once')
  await page.getByRole('button', { name: 'Save note', exact: true }).click()
  await expect.poll(() => posts).toBe(1)
  await page.getByRole('button', { name: 'Investigate this need' }).click()
  await page.goBack()
  await expect(page.getByRole('button', { name: 'Saving…', exact: true })).toBeDisabled()
  await expect(page.getByLabel('Note', { exact: true })).toHaveValue('Save exactly once')
  release()
  await expect(page.getByText('Note saved to this pursuit. Evidence tier unchanged.')).toBeVisible()
  await expect(page.getByLabel('Note', { exact: true })).toHaveValue('')
  expect(posts).toBe(1)
})

test('pending targeted research stays disabled across investigation and returns its result', async ({ page }) => {
  await commercialEnvironment(page)
  let release!: () => void
  const gate = new Promise<void>((resolve) => { release = resolve })
  let posts = 0
  await page.route('**/api/commercial/triage/a/research', async (route) => {
    posts += 1
    await gate
    await route.fulfill({ json: { status: 'ready', job_id: null, stale: false, citations: [], result: { next_step: 'Fixture research result' } } })
  })
  await page.goto('/environment?view=environment&mode=pursuits&pursuitNeed=a')
  await page.getByRole('button', { name: 'Research this question' }).click()
  await expect.poll(() => posts).toBe(1)
  await page.getByRole('button', { name: 'Investigate this need' }).click()
  await page.goBack()
  await expect(page.getByRole('button', { name: 'Queueing…' })).toBeDisabled()
  await expect(page.getByLabel('Exact missing-fact question')).toBeDisabled()
  release()
  await expect(page.getByText('Next step: Fixture research result', { exact: true })).toBeVisible()
  expect(posts).toBe(1)
})

test('authentication expiry clears private call drafts before another session', async ({ page }) => {
  await mock(page, [opportunity('a', 'Austin, TX')])
  await page.goto('/environment?view=environment&mode=action&need=a')
  await page.getByLabel('Call note').fill('Private previous session note')
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: false } }))
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  expect(await page.evaluate(() => Object.keys(sessionStorage).filter(key => key.startsWith('gl3-continuity:')))).toEqual([])
  await page.unroute('**/api/auth/session')
  await page.goto('/environment?view=environment&mode=action&need=a')
  await expect(page.getByLabel('Call note')).toHaveValue('')
})

test('failed draft persistence invalidates the older snapshot instead of restoring stale input', async ({ page }) => {
  await mock(page, [opportunity('a', 'Austin, TX')])
  await page.goto('/environment?view=environment&mode=action&need=a')
  await page.getByLabel('Call note').fill('Old snapshot must not return')
  await page.evaluate(() => {
    for (let i = 0; i < 39; i += 1) sessionStorage.setItem(`gl3-continuity:call:filler-${i}`, JSON.stringify({ at: Date.now(), data: 'x'.repeat(51_250) }))
  })
  await page.getByLabel('Call note').fill('New note '.repeat(400))
  await page.reload()
  await expect(page.getByLabel('Call note')).not.toHaveValue('Old snapshot must not return')
})

test('first pursuit link preserves the unlinked note and question without transferring to another pursuit', async ({ page }) => {
  const item = await commercialEnvironment(page, null)
  let release!: () => void
  const gate = new Promise<void>((resolve) => { release = resolve })
  await page.route('**/api/commercial/triage/a/research', async (route) => {
    await gate
    await route.fulfill({ json: { status: 'ready', job_id: null, stale: false, citations: [], result: { next_step: 'Linked research result' } } })
  })
  const result = (id: string) => ({ evaluated_at: stamp, policy_version: 'fixture', total: 1, grouped_total: 1, offset: 0, limit: 50, next_offset: null, cohort_counts: { action_now: 1, research: 0, watch: 0, reject: 0 }, daily: { evaluated: 1, surfaced: 1, contacted: 0 }, items: [{ ...item, pursuit_id: id }] })
  await page.route('**/api/commercial/triage/evaluate*', (route) => route.fulfill({ json: result('first-pursuit') }))
  await page.goto('/environment?view=environment&mode=pursuits&pursuitNeed=a')
  await page.getByLabel('Note', { exact: true }).fill('Unlinked note stays with first pursuit')
  await page.getByLabel('Exact missing-fact question').fill('Which contractor owns this package?')
  await page.getByRole('button', { name: 'Research this question' }).click()
  await expect(page.getByRole('button', { name: 'Queueing…' })).toBeDisabled()
  await page.getByText('Queue details and research updates', { exact: true }).click()
  await page.getByRole('button', { name: 'Evaluate Signals' }).click()
  await expect(page.getByRole('button', { name: 'Save note', exact: true })).toBeEnabled()
  await expect(page.getByLabel('Note', { exact: true })).toHaveValue('Unlinked note stays with first pursuit')
  await expect(page.getByLabel('Exact missing-fact question')).toHaveValue('Which contractor owns this package?')
  release()
  await expect(page.getByText('Next step: Linked research result', { exact: true })).toBeVisible()
  await page.route('**/api/commercial/triage?*', (route) => route.fulfill({ json: result('first-pursuit') }))
  await page.reload()
  await expect(page.getByLabel('Note', { exact: true })).toHaveValue('Unlinked note stays with first pursuit')
  await page.route('**/api/commercial/triage?*', (route) => route.fulfill({ json: result('different-pursuit') }))
  await page.reload()
  await expect(page.getByLabel('Note', { exact: true })).toHaveValue('')
})

test('authentication rejection clears the currently mounted commercial note', async ({ page }) => {
  await commercialEnvironment(page)
  await page.route('**/api/commercial/triage/evaluate*', (route) => route.fulfill({ status: 401 }))
  await page.goto('/environment?view=environment&mode=pursuits&pursuitNeed=a')
  await page.getByLabel('Note', { exact: true }).fill('Private mounted note')
  await page.getByText('Queue details and research updates', { exact: true }).click()
  await page.getByRole('button', { name: 'Evaluate Signals' }).click()
  await expect(page.getByText(/Your session ended/).first()).toBeVisible()
  await expect(page.getByLabel('Note', { exact: true })).toHaveValue('')
})

test('Back and Forward wait for the matching page before restoring each queue position', async ({ page }) => {
  const items = Array.from({ length: 60 }, (_, i) => opportunity(`history-${i}`, 'Austin, TX'))
  await mock(page, items)
  let delayFirstPage = false, delayed = false
  let release: (() => void) | undefined
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/opportunities/workspace?*', async route => {
    const params = new URL(route.request().url()).searchParams
    const offset = Number(params.get('offset') ?? 0)
    if (delayFirstPage && offset === 0 && !delayed) { delayed = true; await gate }
    await route.fulfill({ json: { items: items.slice(offset, offset + 25), total: 60, counts: { action_now: 0, research: 0, watch: 0, reject: 0 }, offset, limit: 25, next_offset: offset < 50 ? offset + 25 : null, cohort_token: 'workspace-fixture', count_unit: 'power needs', changes_available: false } })
  })
  try {
    await page.goto('/?view=workspace')
    await expect(page.getByText('Showing 1–25 of 60')).toBeVisible()
    const first = page.locator('[data-need-row="history-7"]')
    await first.focus()
    await page.locator('.wh-list').evaluate(el => { el.scrollTop = 200 })
    const firstScroll = await page.locator('.wh-list').evaluate(el => el.scrollTop)
    await page.getByRole('button', { name: 'Next', exact: true }).evaluate(button => (button as HTMLButtonElement).click())
    await expect(page.getByText('Showing 26–50 of 60')).toBeVisible()
    const second = page.locator('[data-need-row="history-32"]')
    await second.focus()
    await page.locator('.wh-list').evaluate(el => { el.scrollTop = 300 })
    const secondScroll = await page.locator('.wh-list').evaluate(el => el.scrollTop)
    await page.getByRole('button', { name: 'Next', exact: true }).evaluate(button => (button as HTMLButtonElement).click())
    await expect(page.getByText('Showing 51–60 of 60')).toBeVisible()
    await page.goBack()
    await expect(page.getByText('Showing 26–50 of 60')).toBeVisible()
    await expect.poll(() => page.locator('.wh-list').evaluate(el => el.scrollTop)).toBe(secondScroll)
    await expect(second).toBeFocused()
    delayFirstPage = true
    await page.goBack()
    await expect.poll(() => delayed).toBe(true)
    await expect(page.getByText('Showing 1–25 of 60')).toHaveCount(0)
    release?.()
    await expect(page.getByText('Showing 1–25 of 60')).toBeVisible()
    await expect.poll(() => page.locator('.wh-list').evaluate(el => el.scrollTop)).toBe(firstScroll)
    await expect(first).toBeFocused()
    await page.goForward()
    await expect(page.getByText('Showing 26–50 of 60')).toBeVisible()
    await expect.poll(() => page.locator('.wh-list').evaluate(el => el.scrollTop)).toBe(secondScroll)
  } finally { release?.() }
})

test('section navigation keeps Opportunities and Signals searches independent through reload and history', async ({ page }) => {
  const requests: URL[] = []
  await mock(page, [opportunity('alpha', 'Austin, TX')])
  page.on('request', request => { const url = new URL(request.url()); if (url.pathname === '/api/opportunities/workspace') requests.push(url) })
  await page.goto('/?view=workspace&q=alpha')
  await expect(page.getByRole('textbox', { name: 'Search workspace' })).toHaveValue('alpha')
  await page.getByRole('button', { name: 'Signals', exact: true }).click()
  await page.getByRole('textbox', { name: 'Search projects' }).fill('beta')
  await expect.poll(() => new URL(page.url()).searchParams.get('q')).toBe('beta')
  await page.getByRole('button', { name: 'Opportunities', exact: true }).click()
  await expect(page.getByRole('textbox', { name: 'Search workspace' })).toHaveValue('alpha')
  expect(new URL(page.url()).searchParams.get('q')).toBe('alpha')
  expect(new URL(page.url()).searchParams.has('decision')).toBe(false)
  await expect.poll(() => requests.at(-1)?.searchParams.get('search')).toBe('alpha')
  await page.reload()
  await expect(page.getByRole('textbox', { name: 'Search workspace' })).toHaveValue('alpha')
  await page.goBack()
  await expect(page.getByRole('textbox', { name: 'Search projects' })).toHaveValue('beta')
  await page.goForward()
  await expect(page.getByRole('textbox', { name: 'Search workspace' })).toHaveValue('alpha')
  expect(new URL(page.url()).searchParams.get('q')).toBe('alpha')
})

test('Research disposition does not leak into Opportunities through navigation and reload', async ({ page }) => {
  await commercialEnvironment(page)
  await page.goto('/?view=workspace&q=a')
  await page.getByRole('button', { name: 'Research', exact: true }).click()
  await page.getByRole('button', { name: /WATCH 0/ }).click()
  await expect.poll(() => new URL(page.url()).searchParams.get('disposition')).toBe('WATCH')
  await page.getByRole('button', { name: 'Opportunities', exact: true }).click()
  await expect(page.getByRole('textbox', { name: 'Search workspace' })).toHaveValue('a')
  expect(new URL(page.url()).searchParams.has('disposition')).toBe(false)
  expect(new URL(page.url()).searchParams.has('pursuitNeed')).toBe(false)
  await page.reload()
  await expect(page.getByRole('navigation', { name: 'Filter opportunities by category' }).getByRole('button', { name: 'All', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await page.goBack()
  await expect(page.getByRole('button', { name: /WATCH 0/ })).toHaveAttribute('aria-pressed', 'true')
  await page.goForward()
  await expect(page.getByRole('textbox', { name: 'Search workspace' })).toHaveValue('a')
  expect(new URL(page.url()).searchParams.has('disposition')).toBe(false)
})
