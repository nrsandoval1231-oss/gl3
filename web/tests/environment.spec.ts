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

test('nation counts per state, keeps unmapped records reachable, and Back restores each scene', async ({ page }) => {
  await mock(page, [opportunity('a', 'Austin, TX'), opportunity('b', 'Dallas, Texas'), opportunity('c', 'Atlanta, GA'), opportunity('d', 'Site unknown')])
  await page.goto('/')
  await expect(page.getByRole('heading', { name: /A wider view/ })).toBeVisible()
  await expect(page.getByText('4 signals · 2 states · 1 unmapped.', { exact: false })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Texas 2' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'No mappable state 1' })).toBeVisible()

  await page.getByRole('button', { name: 'Texas 2' }).click()
  await expect(page.getByRole('heading', { name: 'Texas', level: 1 })).toBeVisible()
  await page.getByRole('button', { name: /Test project a/ }).click()
  await expect(page.getByRole('heading', { name: 'Test project a', level: 1 })).toBeVisible()
  await expect(page.getByText('Required power')).toBeVisible()
  await page.getByRole('button', { name: /Reveal the evidence/ }).click()
  await expect(page.getByRole('link', { name: 'Test evidence 2' })).toBeVisible()

  await page.goBack()
  await expect(page.getByRole('button', { name: /Follow the power need/ })).toBeVisible()
  await page.goBack()
  await expect(page.getByRole('heading', { name: 'Texas', level: 1 })).toBeVisible()
  await expect(page).toHaveURL(/mode=state&state=Texas/)
  await page.goBack()
  await expect(page.getByRole('heading', { name: /A wider view/ })).toBeVisible()

  await page.getByRole('button', { name: 'No mappable state 1' }).click()
  await expect(page.getByRole('button', { name: /Test project d/ })).toBeVisible()
})

test('deep link restores a project scene and the call brief stays unsent', async ({ page }) => {
  await mock(page, [opportunity('a', 'Austin, TX')])
  await page.goto('/?view=environment&mode=action&state=Texas&need=a')
  await expect(page.getByRole('heading', { name: 'Ask the question that moves this forward.' })).toBeVisible()
  await expect(page.getByText('Test next action a.')).toBeVisible()
  await expect(page.getByText(/call brief · nothing is sent/i)).toBeVisible()
})

test('empty and failed result sets are honest', async ({ page }) => {
  await mock(page, [])
  await page.goto('/?view=environment&level=Leads')
  await expect(page.getByText('No leads match this view. Nothing is invented to fill it.')).toBeVisible()

  await page.unroute('**/api/**')
  await mock(page, [], (route) => route.fulfill({ status: 503, body: 'down' }))
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Opportunities are unavailable.' })).toBeVisible()
})

test('lens and tier changes query the server', async ({ page }) => {
  const queries: URLSearchParams[] = []
  await mock(page, [opportunity('a', 'Austin, TX')])
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (url.pathname === '/api/opportunities/map-window') queries.push(url.searchParams)
  })
  await page.goto('/')
  await page.getByLabel('Industry lens').selectOption('data_center')
  await expect.poll(() => queries.at(-1)?.get('industry')).toBe('data_center')
  await page.getByLabel('Tier').selectOption('Prospects')
  await expect.poll(() => queries.at(-1)?.get('tier')).toBe('Prospect')
  await page.getByLabel('Search projects, companies or places').fill('austin')
  await page.getByRole('button', { name: 'Search' }).click()
  await expect.poll(() => queries.at(-1)?.get('search')).toBe('austin')
})

test('one bounded map-window request maps its subset and District of Columbia correctly', async ({ page }) => {
  const many = Array.from({ length: 60 }, (_, index) => opportunity(`p${index}`, 'Austin, TX'))
  many.push(opportunity('dc', 'Washington, DC'))
  let mapRequests = 0
  await mock(page, many, undefined, async (route) => {
    mapRequests += 1
    await route.fulfill({ json: { items: many, total_count: many.length, loaded_count: many.length,
      is_subset: false, window_limit: 200, group_total_count: many.length,
      cohort_token: 'map-cohort', decision_counts: { SHOW: 0, REVIEW: 0, HOLD: 0 } } })
  })
  await page.goto('/')
  await expect.poll(() => mapRequests).toBe(1)
  await expect(page.getByText('61 signals · 2 states.', { exact: false })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Texas 60' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'District of Columbia 1' })).toBeVisible()
  await expect(page.getByRole('button', { name: /^Washington/ })).toHaveCount(0)
})

test('Back restores the previous lens after a nation-level change', async ({ page }) => {
  await mock(page, [opportunity('a', 'Austin, TX')])
  await page.goto('/')
  const back = page.getByRole('button', { name: 'Back to previous view' })
  await expect(back).toBeDisabled()
  await page.getByLabel('Tier').selectOption('Prospects')
  await expect(back).toBeEnabled()
  await back.click()
  await expect(page.getByLabel('Tier')).toHaveValue('Signals')
})

test('a filing that left its source listing shows a status-review notice in the project view', async ({ page }) => {
  await mock(page, [{ ...opportunity('a', 'Austin, TX'), signal_evidence_state: 'source_listing_absent' } as Opportunity])
  await page.goto('/?view=environment&mode=project&state=Texas&need=a')
  await expect(page.getByText(/Status review needed: this filing is no longer in the source's current listing/)).toBeVisible()
})

test('featured pursuit is the highest rank and its reasons are shown', async ({ page }) => {
  await mock(page, [
    { ...opportunity('a', 'Austin, TX'), rank_score: 40, rank_reasons: ['Signal: dated official or published source'] } as Opportunity,
    { ...opportunity('b', 'Dallas, TX'), rank_score: 82, rank_reasons: ['Data-center construction phase', 'Priority geography: DFW'] } as Opportunity,
  ])
  await page.goto('/')
  await expect(page.getByText(/Highest rank · 82/i)).toBeVisible()
  await expect(page.getByText('Data-center construction phase · Priority geography: DFW')).toBeVisible()
  await page.getByRole('button', { name: /Explore this pursuit/ }).click()
  await expect(page.getByText(/Rank 82\/100/)).toBeVisible()
})

test('state lists default to rank order, highest first', async ({ page }) => {
  await mock(page, [
    { ...opportunity('a', 'Austin, TX'), rank_score: 30 } as Opportunity,
    { ...opportunity('b', 'Dallas, TX'), rank_score: 75 } as Opportunity,
    { ...opportunity('c', 'Houston, TX'), rank_score: 50 } as Opportunity,
  ])
  await page.goto('/?view=environment&mode=state&state=Texas')
  await expect(page.locator('.env-list li')).toHaveText([/Dallas/, /Houston/, /Austin/])
})

test('the map makes one ranked-window request and discloses its loaded subset', async ({ page }) => {
  const requests: URL[] = []
  const items = Array.from({ length: 60 }, (_, i) => ({ ...opportunity(`n${i}`, 'Austin, TX'), rank_score: 60 - i } as Opportunity))
  await mock(page, items, undefined, async (route) => {
    requests.push(new URL(route.request().url()))
    await route.fulfill({ json: { items, total_count: 260, loaded_count: items.length,
      is_subset: true, window_limit: 200, group_total_count: 260, cohort_token: 'map-cohort',
      decision_counts: { SHOW: 0, REVIEW: 0, HOLD: 0 } } })
  })
  await page.goto('/')
  await expect(page.getByText(/Highest rank/)).toBeVisible()
  await expect(page.getByText(/Showing the 60 highest-ranked of 260/)).toBeVisible()
  expect(requests).toHaveLength(1)
  expect(requests[0].pathname).toBe('/api/opportunities/map-window')
  expect(requests[0].searchParams.get('tier')).toBe('Signal')
  expect(requests[0].searchParams.has('offset')).toBe(false)
  expect(requests[0].searchParams.has('limit')).toBe(false)
})

test('collection scenes skip map ranking and Back reloads the current map window', async ({ page }) => {
  let mapRequests = 0
  await mock(page, [opportunity('a', 'Austin, TX')], undefined, async (route) => {
    mapRequests += 1
    await route.fulfill({ json: {
      items: [opportunity('a', 'Austin, TX')], total_count: 1, loaded_count: 1,
      is_subset: false, window_limit: 200, group_total_count: 1, cohort_token: 'map',
      decision_counts: { SHOW: 0, REVIEW: 0, HOLD: 0 },
    } })
  })
  await page.goto('/')
  await expect.poll(() => mapRequests).toBe(1)
  await page.getByRole('link', { name: 'Advanced record browser' }).click()
  await expect(page.getByRole('heading', { name: 'Browse signals' })).toBeVisible()
  expect(mapRequests).toBe(1)
  await page.goBack()
  await expect(page.getByRole('heading', { name: /A wider view/ })).toBeVisible()
  await expect.poll(() => mapRequests).toBe(2)
  await page.goto('/?view=environment&mode=pursuits')
  await expect(page.getByRole('heading', { name: 'What should we work today?' })).toBeVisible()
  expect(mapRequests).toBe(2)
})
test('one call logs several facts as drafts, then accepts them in one explicit step', async ({ page }) => {
  await mock(page, [opportunity('a', 'Midlothian, TX')])
  let version = 0
  let failNextCreate = true
  const created: { client_id: string, fact_type: string, value: Record<string, unknown>, expected_version: number, facility_scope: string, reporter_name: string }[] = []
  const decided: { expected_version: number, decision: string }[] = []
  await page.route('**/api/needs/a/facts**', async (route) => {
    const request = route.request()
    const json = (body: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
    if (request.method() === 'POST' && request.url().endsWith('/decision')) {
      const body = request.postDataJSON()
      decided.push(body)
      version += 1
      return json({ id: `d${version}`, version, decision: body.decision, reason: body.reason, actor: 'Nick Sandoval', created_at: '2026-10-14T12:00:00Z', fact_version_id: 'x', content_hash: 'h', tier: 'Signal', active: true })
    }
    if (request.method() === 'POST') {
      const body = request.postDataJSON()
      created.push(body)
      if (failNextCreate) { failNextCreate = false; return route.fulfill({ status: 503, body: 'lost' }) }
      version += 1
      return json({ ...body, id: `f${created.length}`, need_id: 'a', decision: 'draft', decision_version: version, content_hash: 'h', authority_label: 'Operator report', recorded_by: 'Nick Sandoval', created_at: '2026-10-14T12:00:00Z', decision_reason: null, decision_actor: null, decided_at: null })
    }
    return json({ items: [], total: 0, limit: 50, offset: 0, next_offset: null, current_fact_version: version,
      current_reported_timing_correction_target: { available: false, unavailable_reason: 'no_current_admitted_lead', need_id: 'a', current_fact_version: version } })
  })
  await page.goto('/?view=environment&mode=action&state=Texas&need=a')
  await page.getByLabel('Contact name').fill('Jordan Example')
  await page.getByLabel('Power needed').fill('8-12')
  await page.getByLabel('Buyer organization').fill('Example GC')
  await page.getByLabel('Supply MW').fill('3')
  await page.getByLabel('Supply quality').selectOption('unsuitable')
  await page.getByRole('button', { name: 'Save as drafts' }).click()
  await expect(page.getByRole('alert')).toHaveText(/Choose the buyer role/)
  expect(created).toHaveLength(0)
  await page.getByLabel('Buyer role').selectOption('general contractor')
  await page.getByRole('button', { name: 'Save as drafts' }).click()
  await expect(page.getByRole('alert')).toHaveText(/0 of 3 drafts saved before an error/)
  await page.reload()
  await expect(page.getByLabel('Contact name')).toHaveValue('Jordan Example')
  // The retry reuses the first request's key, including after refresh.
  await page.getByRole('button', { name: 'Save as drafts' }).click()
  await expect(page.getByText('3 drafts saved, not yet accepted.')).toBeVisible()
  expect(created[1].client_id).toBe(created[0].client_id)
  expect(created.slice(1).map((fact) => [fact.fact_type, fact.expected_version, fact.facility_scope, fact.reporter_name])).toEqual([
    ['demand', 0, 'Midlothian, TX', 'Jordan Example'],
    ['buyer', 1, 'Midlothian, TX', 'Jordan Example'],
    ['unsuitable_supply', 2, 'Midlothian, TX', 'Jordan Example'],
  ])
  expect(created[3].value).toEqual({ mw: '3' })
  expect(decided).toHaveLength(0)
  await page.getByRole('button', { name: /Accept all 3 as confirmed by Jordan Example/ }).click()
  await expect(page.getByText('3 facts accepted.', { exact: false })).toBeVisible()
  expect(decided.map((decision) => [decision.decision, decision.expected_version])).toEqual([['accepted', 3], ['accepted', 4], ['accepted', 5]])
  await page.getByRole('button', { name: 'Start another call' }).click()
  await expect(page.getByLabel('Contact name')).toHaveValue('')
  await expect(page.getByLabel('Power needed')).toHaveValue('')
})


test('selected need beyond 200 resolves independently from bounded map results', async ({ page }) => {
  await mock(page, Array.from({ length: 205 }, (_, i) => opportunity(`p${i}`, 'Austin, TX')))
  await page.goto('/?view=environment&mode=project&state=Texas&need=p204')
  await expect(page.getByRole('heading', { name: 'Test project p204', exact: true })).toBeVisible()
  await expect(page.getByText(/Showing the 200 highest-ranked of 205/)).toBeVisible()
})

test('filter exclusion retains action identity and geography', async ({ page }) => {
  await mock(page, [opportunity('a', 'Austin, TX')], async (route) => {
    const matches = new URL(route.request().url()).searchParams.get('tier') === 'Signal'
    await route.fulfill({ json: matches ? [opportunity('a', 'Austin, TX')] : [], headers: { 'X-Total-Count': matches ? '1' : '0' } })
  })
  await page.goto('/?view=environment&mode=action&state=Texas&need=a')
  await page.getByLabel('Contact name').fill('Alex')
  await page.getByLabel('Tier').selectOption('Leads')
  await expect(page.getByText('Outside current filters', { exact: true })).toBeVisible()
  await expect(page.getByLabel('Contact name')).toHaveValue('Alex')
  await expect(page).toHaveURL(/mode=action&state=Texas&need=a/)
  await expect(page.getByRole('button', { name: 'Texas 1', exact: true })).toHaveCount(0)
})

test('Back and Forward restore focus, scroll, disclosure and isolated call input', async ({ page }) => {
  await mock(page, [opportunity('a', 'Austin, TX'), opportunity('b', 'Austin, TX')])
  await page.goto('/')
  await page.getByRole('button', { name: 'Explore this pursuit' }).click()
  await page.getByRole('button', { name: 'Prepare the call' }).click()
  await page.getByLabel('Contact name').fill('Alex')
  await page.getByLabel('Call note').fill('Private unsaved note A')
  await page.getByText('Full fact history, single-fact entry and corrections', { exact: true }).click()
  await page.getByLabel('Call note').focus()
  const y = await page.evaluate(() => scrollY)
  await page.goBack()
  await expect(page.getByRole('button', { name: 'Prepare the call' })).toBeVisible()
  await page.goForward()
  await expect(page.getByLabel('Call note')).toHaveValue('Private unsaved note A')
  await expect(page.getByLabel('Call note')).toBeFocused()
  await expect.poll(() => page.evaluate(() => scrollY)).toBeCloseTo(y, 0)
  await expect(page.locator('.env-full-facts')).toHaveAttribute('open', '')
  await page.getByRole('link', { name: 'GridLens home' }).click()
  await page.getByRole('button', { name: 'Texas 2', exact: true }).click()
  await page.getByRole('button', { name: /Test project b/ }).click()
  await page.getByRole('button', { name: 'Prepare the call' }).click()
  await expect(page.getByLabel('Call note')).toHaveValue('')
  await page.getByLabel('Call note').fill('Separate note B')
  await page.goBack(); await page.goBack(); await page.goBack(); await page.goBack()
  await expect(page.getByLabel('Call note')).toHaveValue('Private unsaved note A')
})

test('failed map has an actual retry and source-health return path', async ({ page }) => {
  let fail = true
  await mock(page, [], undefined, async (route) => {
    await route.fulfill(fail ? { status: 503 } : { json: { items: [], total_count: 0, loaded_count: 0, is_subset: false, window_limit: 200, group_total_count: 0, cohort_token: 'empty', decision_counts: { SHOW: 0, REVIEW: 0, HOLD: 0 } } })
  })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Opportunities are unavailable.' })).toBeVisible()
  fail = false
  await page.getByRole('button', { name: 'Retry opportunities' }).click()
  await expect(page.getByRole('heading', { name: /A wider view/ })).toBeVisible()
  await page.getByRole('button', { name: 'Menu', exact: true }).click()
  await page.getByRole('link', { name: 'Source health', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Source health', exact: true })).toBeVisible()
  await page.getByRole('link', { name: 'Return to environment' }).click()
  await expect(page.getByRole('heading', { name: /A wider view/ })).toBeVisible()
})

test('draft refresh and legacy full-record round trip retain context without writes; logout clears drafts', async ({ page }) => {
  await mock(page, [opportunity('a', 'Austin, TX')])
  const writes: string[] = []
  page.on('request', (request) => { if (request.method() === 'POST') writes.push(new URL(request.url()).pathname) })
  await page.goto('/?view=environment&mode=action&state=Texas&need=a')
  await page.getByLabel('Contact name').fill('Alex')
  await page.getByLabel('Call note').fill('Keep across refresh')
  await page.reload()
  await expect(page.getByLabel('Call note')).toHaveValue('Keep across refresh')
  await page.getByRole('link', { name: 'Open the full record' }).click()
  await expect(page.getByRole('heading', { name: 'Test project a', exact: true }).first()).toBeVisible()
  await page.reload()
  await page.getByRole('link', { name: 'Return to environment' }).click()
  await expect(page.getByLabel('Call note')).toHaveValue('Keep across refresh')
  expect(writes).toEqual([])
  await page.getByRole('button', { name: 'Menu', exact: true }).click()
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
  expect(await page.evaluate(() => Object.keys(sessionStorage).filter((key) => key.startsWith('gl3-continuity:')))).toEqual([])
  await page.reload()
  await expect(page.getByLabel('Call note')).toHaveValue('')
})

test('state-list scroll and selected-record keyboard focus restore on Back', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await mock(page, Array.from({ length: 40 }, (_, i) => opportunity(`p${i}`, 'Austin, TX')))
  await page.goto('/?view=environment&mode=state&state=Texas&lens=data_center')
  const chosen = page.getByRole('button', { name: /Test project p30 / })
  await chosen.focus()
  await chosen.scrollIntoViewIfNeeded()
  const scroll = await page.locator('.env-list').evaluate((el) => el.scrollTop)
  await chosen.press('Enter')
  await expect(page.getByRole('heading', { name: 'Test project p30', exact: true })).toBeVisible()
  await page.goBack()
  await expect(chosen).toBeFocused()
  await expect.poll(() => page.locator('.env-list').evaluate((el) => el.scrollTop)).toBeCloseTo(scroll, 0)
  await expect(page.getByLabel('Industry lens')).toHaveValue('data_center')
})

test('late selected-record and map responses cannot replace newer navigation', async ({ page }) => {
  await mock(page, [opportunity('a', 'Austin, TX'), opportunity('b', 'Austin, TX')])
  let release: () => void = () => {}
  const gate = new Promise<void>((resolve) => { release = resolve })
  await page.route('**/api/opportunities/needs/a?**', async (route) => {
    await gate
    await route.fulfill({ json: opportunity('a', 'Austin, TX') }).catch(() => {})
  })
  await page.goto('/?view=environment&mode=state&state=Texas')
  await page.getByRole('button', { name: /Test project a/ }).click()
  await page.getByRole('link', { name: 'GridLens home' }).click()
  await page.getByRole('button', { name: 'Texas 2', exact: true }).click()
  await page.getByRole('button', { name: /Test project b/ }).click()
  await expect(page.getByRole('heading', { name: 'Test project b', exact: true })).toBeVisible()
  release()
  await expect(page.getByRole('heading', { name: 'Test project a', exact: true })).toHaveCount(0)
  await page.getByLabel('Tier').selectOption('Leads')
  await page.getByLabel('Tier').selectOption('Signals')
  await expect(page.getByRole('heading', { name: 'Test project b', exact: true })).toBeVisible()
  await expect(page.getByLabel('Tier')).toHaveValue('Signals')
})

for (const [status, message] of [[404, /unavailable, deleted/], [401, /session ended/], [503, /could not complete this request/]] as const) {
  test(`selected-record ${status} is distinguished from filter exclusion`, async ({ page }) => {
    await mock(page, [])
    await page.route('**/api/opportunities/needs/missing?**', (route) => route.fulfill({ status }))
    await page.goto('/?view=environment&mode=project&need=missing')
    await expect(page.getByRole('alert')).toContainText(message)
    await expect(page.getByText('Outside current filters', { exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Retry selected opportunity' })).toBeVisible()
  })
}


test('buying-chain async disclosures restore independently per field after Back', async ({ page }) => {
  await mock(page, [opportunity('a', 'Austin, TX')])
  await page.route('**/api/projects/a/buying-chain', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 300))
    await route.fulfill({ json: { project_id: 'a', status: 'complete', policy_version: 'v1', unresolved: [], runs: [], candidates: [], permit_summaries: [
      { evidence_id: 'permit-a', title: 'Fixture permit', url: 'https://example.test', facts: [
        { label: 'Owner', value: 'Fixture owner', quote: 'Fixture quote one' },
        { label: 'Applicant', value: 'Fixture applicant', quote: 'Fixture quote two' },
      ] },
    ] } })
  })
  await page.goto('/?view=environment&mode=buyers&need=a')
  await page.getByText('Field evidence', { exact: true }).first().click()
  await expect(page.getByText('Fixture quote one', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Prepare the call' }).click()
  await page.goBack()
  await expect(page.getByText('Fixture quote one', { exact: true })).toBeVisible()
  await expect(page.getByText('Fixture quote two', { exact: true })).not.toBeVisible()
})

test('legacy menu return restores scroll even when departure focus was inside the menu', async ({ page }) => {
  await mock(page, [opportunity('a', 'Austin, TX')])
  await page.goto('/?view=environment&mode=action&state=Texas&need=a')
  await page.getByLabel('Call note').fill('Keep menu return context')
  await page.getByRole('button', { name: 'Menu', exact: true }).click()
  const y = await page.evaluate(() => scrollY)
  await page.getByRole('link', { name: 'Advanced record browser', exact: true }).click()
  await page.getByRole('link', { name: 'Return to environment' }).click()
  await expect(page.getByLabel('Call note')).toHaveValue('Keep menu return context')
  await expect(page.getByRole('link', { name: 'Advanced record browser', exact: true })).toBeFocused()
  await expect.poll(() => page.evaluate(() => scrollY)).toBeCloseTo(y, 0)
})

test('late map responses do not restore stale filters or counts', async ({ page }) => {
  let release: () => void = () => {}
  const gate = new Promise<void>((resolve) => { release = resolve })
  await mock(page, [opportunity('a', 'Austin, TX')], undefined, async (route) => {
    const tier = new URL(route.request().url()).searchParams.get('tier')
    if (tier === 'Prospect') await gate
    const matching = tier === 'Signal' ? [opportunity('a', 'Austin, TX')] : []
    await route.fulfill({ json: { items: matching, total_count: matching.length, loaded_count: matching.length, is_subset: false, window_limit: 200, group_total_count: matching.length, cohort_token: 'map', decision_counts: { SHOW: 0, REVIEW: 0, HOLD: 0 } } }).catch(() => {})
  })
  await page.goto('/')
  await expect(page.getByRole('button', { name: 'Texas 1', exact: true })).toBeVisible()
  await page.getByLabel('Tier').selectOption('Prospects')
  await page.getByLabel('Tier').selectOption('Signals')
  await expect(page.getByRole('button', { name: 'Texas 1', exact: true })).toBeVisible()
  release()
  await expect(page.getByLabel('Tier')).toHaveValue('Signals')
  await expect(page.getByRole('button', { name: 'Texas 1', exact: true })).toBeVisible()
})

for (const width of [1280, 390]) {
  test(`rendered ${width}px keyboard journey with reduced motion`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 844 })
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await mock(page, [opportunity('a', 'Austin, TX')])
    await page.goto('/')
    await page.getByRole('button', { name: 'Explore this pursuit' }).focus()
    await page.keyboard.press('Enter')
    await page.getByRole('button', { name: 'Reveal the evidence' }).focus()
    await page.keyboard.press('Enter')
    await expect(page.getByRole('link', { name: 'Test evidence 1' })).toBeVisible()
    await page.getByRole('button', { name: 'Follow the buying path' }).click()
    await page.getByRole('button', { name: 'Prepare the call' }).click()
    await page.getByLabel('Contact name').fill('Test-only contact')
    await page.getByLabel('Call note').fill('Unsaved fixture input — no facts accepted.')
    await page.goBack(); await page.goForward()
    await expect(page.getByLabel('Call note')).toHaveValue('Unsaved fixture input — no facts accepted.')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    const screenshot = testInfo.outputPath(`environment-${width}-fixture.png`)
    await page.screenshot({ path: screenshot, fullPage: true })
    await testInfo.attach(`Rendered ${width}px fixture journey (not live data)`, { path: screenshot, contentType: 'image/png' })
  })
}

test('Back across filters waits for matching list before restoring its scroll', async ({ page }) => {
  const items = Array.from({ length: 40 }, (_, i) => opportunity(`p${i}`, 'Austin, TX'))
  await mock(page, items, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 200))
    const matches = new URL(route.request().url()).searchParams.get('tier') === 'Signal'
    await route.fulfill({ json: matches ? items : [], headers: { 'X-Total-Count': matches ? '40' : '0' } })
  })
  await page.goto('/?view=environment&mode=state&state=Texas')
  await expect(page.getByRole('button', { name: /Test project p39 / })).toBeAttached()
  await page.locator('.env-list').evaluate((el) => { el.scrollTop = 500 })
  const y = await page.locator('.env-list').evaluate((el) => el.scrollTop)
  await page.getByLabel('Tier').focus()
  await page.getByLabel('Tier').selectOption('Leads')
  await expect(page.getByText('No leads here in the current view.')).toBeVisible()
  await page.goBack()
  await expect(page.getByRole('button', { name: /Test project p39 / })).toBeAttached()
  await expect.poll(() => page.locator('.env-list').evaluate((el) => el.scrollTop)).toBeCloseTo(y, 0)
  await expect(page.getByLabel('Tier')).toBeFocused()
})

test('navigation snapshot bounds do not evict an unsaved call draft', async ({ page }) => {
  test.setTimeout(90_000)
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await mock(page, [opportunity('a', 'Austin, TX')])
  await page.goto('/?view=environment&mode=action&need=a')
  await page.getByLabel('Call note').fill('Must outlive navigation snapshots')
  await page.getByRole('link', { name: 'GridLens home' }).click()
  for (let i = 0; i < 42; i += 1) {
    await page.getByLabel('Search projects, companies or places').fill(`fixture search ${i}`)
    await page.getByRole('button', { name: 'Search', exact: true }).click()
  }
  await page.goto('/?view=environment&mode=action&need=a')
  await expect(page.getByLabel('Call note')).toHaveValue('Must outlive navigation snapshots')
})

test('all-record browsing stays in the environment and restores its page after investigation', async ({ page }) => {
  await mock(page, Array.from({ length: 205 }, (_, i) => opportunity(`p${i}`, 'Austin, TX')))
  await page.goto('/')
  await page.getByRole('button', { name: 'Menu', exact: true }).click()
  await page.getByRole('link', { name: 'All records', exact: true }).click()
  await expect(page.locator('.env')).toBeVisible()
  for (let i = 0; i < 4; i += 1) await page.getByRole('button', { name: 'Next records' }).click()
  await page.getByRole('button', { name: /Test project p204 / }).click()
  await expect(page.getByRole('heading', { name: 'Test project p204', exact: true })).toBeVisible()
  await page.goBack()
  await expect(page.getByRole('button', { name: /Test project p204 / })).toBeFocused()
  await expect(page.getByText('201–205 of 205 matching records', { exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByText('201–205 of 205 matching records', { exact: true })).toBeVisible()
})

async function commercialEnvironment(page: Page, pursuitId: string | null = 'pursuit-a') {
  await mock(page, [opportunity('a', 'Austin, TX')])
  const item = { id: 'a', project_id: 'a', pursuit_id: pursuitId, name: 'Commercial fixture A', location: 'Austin, TX', tier: 'Signal', activity: 'construction-power', industry: 'data_center', disposition: 'ACTION NOW', reason: 'Fixture reason', supply: 'Unknown', next_question: 'What is the activity-specific construction load?', next_action: 'Confirm the package buyer.', stage: { stage: 'construction', date: null }, facts: [], contacts: [], sources: [], notes: [], unknowns: [], blockers: [] }
  await page.route('**/api/commercial/triage?*', (route) => route.fulfill({ json: {
    evaluated_at: '2026-10-01T12:00:00Z', policy_version: 'fixture', total: 1, grouped_total: 1, offset: 0, limit: 50, next_offset: null,
    cohort_counts: { action_now: 1, research: 0, watch: 0, reject: 0 }, daily: { evaluated: 1, surfaced: 1, contacted: 0 }, items: [item],
  } }))
  return item
}

test('commercial pursuit investigation returns to its note and selected need without writes', async ({ page }) => {
  await commercialEnvironment(page)
  const writes: string[] = []
  page.on('request', (request) => { if (request.method() === 'POST') writes.push(request.url()) })
  await page.goto('/')
  await page.getByRole('button', { name: 'Menu', exact: true }).click()
  await page.getByRole('link', { name: 'Today’s pursuits', exact: true }).click()
  await expect(page.locator('.env')).toBeVisible()
  await page.getByRole('button', { name: /Commercial fixture A/ }).click()
  await page.getByLabel('Note', { exact: true }).fill('Unsaved commercial note')
  await page.getByRole('button', { name: 'Investigate this need' }).click()
  await expect(page.getByRole('heading', { name: 'Test project a', exact: true })).toBeVisible()
  await page.goBack()
  await expect(page.getByLabel('Note', { exact: true })).toHaveValue('Unsaved commercial note')
  await expect(page.getByRole('button', { name: 'Investigate this need' })).toBeFocused()
  await page.reload()
  await expect(page.getByLabel('Note', { exact: true })).toHaveValue('Unsaved commercial note')
  expect(writes).toEqual([])
})

test('commercial filters retain the selected pursuit separately and Back restores disposition and focus', async ({ page }) => {
  await commercialEnvironment(page)
  await page.goto('/?view=environment&mode=pursuits&pursuitNeed=a')
  await page.getByLabel('Note', { exact: true }).fill('Keep this note')
  await page.getByRole('button', { name: 'WATCH 0', exact: true }).click()
  await expect(page.getByText('Selected pursuit outside current page filters.', { exact: false })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'WATCH · 0 pursuits on this page' })).toBeVisible()
  await expect(page.getByLabel('Note', { exact: true })).toHaveValue('Keep this note')
  await page.goBack()
  await expect(page.getByRole('button', { name: 'WATCH 0', exact: true })).toBeFocused()
  await page.goForward()
  await expect(page.getByRole('heading', { name: 'WATCH · 0 pursuits on this page' })).toBeVisible()
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
  await page.goto('/?view=environment&mode=pursuits&pursuitNeed=a')
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

test('environment commercial retry stays in place on mobile with reduced motion', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await commercialEnvironment(page)
  let failed = true
  await page.route('**/api/commercial/triage?*', async (route) => {
    if (failed) return route.fulfill({ status: 503, body: 'Unavailable' })
    return route.fallback()
  })
  await page.goto('/?view=environment&mode=pursuits')
  const retry = page.getByRole('button', { name: 'Retry commercial pursuits' })
  await expect(retry).toBeVisible()
  failed = false
  await retry.focus()
  await page.keyboard.press('Enter')
  await page.getByRole('button', { name: /Commercial fixture A/ }).click()
  await expect(page.getByLabel('Note', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.getByRole('button', { name: 'Investigate this need' }).click()
  await page.goBack()
  await expect(page.getByRole('button', { name: 'Investigate this need' })).toBeFocused()
  expect(await page.locator('.env-subject').evaluate((el) => getComputedStyle(el).animationName)).toBe('none')
})

test('delayed commercial research restores each question disclosure and scroll independently', async ({ page }) => {
  await commercialEnvironment(page)
  let delay = false
  await page.route('**/api/commercial/triage/a/autonomous-research', async (route) => {
    if (delay) await new Promise((resolve) => setTimeout(resolve, 350))
    await route.fulfill({ json: { items: ['one', 'two'].map((id) => ({ id, question: `Fixture question ${id}`, status: 'UNRESOLVED', receipt: {}, context: { known_facts: [{ text: `Known fixture fact ${id}` }] } })) } })
  })
  await page.goto('/?view=environment&mode=pursuits&pursuitNeed=a')
  await page.getByText('What GridLens knew before', { exact: true }).first().click()
  await expect(page.getByText('Known fixture fact one')).toBeVisible()
  const investigate = page.getByRole('button', { name: 'Investigate this need' })
  await investigate.scrollIntoViewIfNeeded()
  const y = await page.evaluate(() => scrollY)
  await investigate.click()
  delay = true
  await page.goBack()
  await expect(page.getByText('Known fixture fact one')).toBeVisible()
  await expect(page.getByText('Known fixture fact two')).not.toBeVisible()
  await expect(investigate).toBeFocused()
  await expect.poll(() => page.evaluate(() => scrollY)).toBeCloseTo(y, 0)
})

for (const width of [1280, 390]) {
  test(`rendered commercial environment at ${width}px`, async ({ page }, testInfo) => {
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.setViewportSize({ width, height: 900 })
    await commercialEnvironment(page)
    await page.goto('/?view=environment&mode=pursuits')
    await expect(page.getByRole('button', { name: /Commercial fixture A/ })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    const screenshot = testInfo.outputPath(`commercial-${width}-fixture.png`)
    await page.screenshot({ path: screenshot, fullPage: true })
    await testInfo.attach('Synthetic fixture rendering, not live data', { path: screenshot, contentType: 'image/png' })
    const card = page.getByRole('button', { name: /Commercial fixture A/ })
    expect((await card.boundingBox())!.y + (await card.boundingBox())!.height).toBeLessThan(800)
    await page.goto('/')
    await expect(page.getByRole('heading', { name: /A wider view/ })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'What should we work today?' })).not.toBeVisible()
    await expect(page.getByRole('button', { name: /Explore this pursuit/ })).toBeVisible()
    const national = testInfo.outputPath(`national-${width}-fixture.png`)
    await page.screenshot({ path: national, fullPage: true })
    await testInfo.attach('National fixture rendering, not live data', { path: national, contentType: 'image/png' })
  })
}

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
  await page.goto('/?view=environment&mode=pursuits&pursuitNeed=a')
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

test('late browse page response cannot replace the restored first page', async ({ page }) => {
  const items = Array.from({ length: 55 }, (_, i) => opportunity(`p${i}`, 'Austin, TX'))
  let delay = false
  let release!: () => void
  const gate = new Promise<void>((resolve) => { release = resolve })
  let requested = false
  await mock(page, items, async (route) => {
    const offset = Number(new URL(route.request().url()).searchParams.get('offset') ?? 0)
    if (delay && offset === 50) { requested = true; await gate }
    await route.fulfill({ json: items.slice(offset, offset + 50), headers: { 'X-Total-Count': '55', 'X-Cohort-Token': 'c1', ...(offset === 0 ? { 'X-Next-Offset': '50' } : {}) } }).catch(() => {})
  })
  await page.goto('/?view=environment&mode=browse')
  await expect(page.getByText('1–50 of 55 matching records', { exact: true })).toBeVisible()
  delay = true
  await page.getByRole('button', { name: 'Next records' }).click()
  await expect.poll(() => requested).toBe(true)
  await page.goBack()
  await expect(page.getByText('1–50 of 55 matching records', { exact: true })).toBeVisible()
  release()
  await expect(page.getByRole('button', { name: /Test project p0 / })).toBeVisible()
  await expect(page.getByText('51–55 of 55 matching records', { exact: true })).not.toBeVisible()
})

test('expired authentication clears private drafts before another sign-in', async ({ page }) => {
  await mock(page, [opportunity('a', 'Austin, TX')])
  await page.goto('/?view=environment&mode=action&need=a')
  await page.getByLabel('Call note').fill('Private previous session note')
  await page.route('**/api/auth/session', (route) => route.fulfill({ json: { authenticated: false } }))
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  expect(await page.evaluate(() => Object.keys(sessionStorage).filter((key) => key.startsWith('gl3-continuity:')))).toEqual([])
  await page.unroute('**/api/auth/session')
  await page.goto('/?view=environment&mode=action&need=a')
  await expect(page.getByLabel('Call note')).toHaveValue('')
})

test('failed draft persistence invalidates the older snapshot instead of restoring stale input', async ({ page }) => {
  await mock(page, [opportunity('a', 'Austin, TX')])
  await page.goto('/?view=environment&mode=action&need=a')
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
  await page.goto('/?view=environment&mode=pursuits&pursuitNeed=a')
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

test('commercial disposition focus survives changed counts on Back', async ({ page }) => {
  const item = await commercialEnvironment(page)
  await page.goto('/?view=environment&mode=pursuits')
  await page.getByRole('button', { name: 'WATCH 0', exact: true }).click()
  await page.getByRole('link', { name: 'GridLens home' }).click()
  await page.route('**/api/commercial/triage?*', (route) => route.fulfill({ json: { evaluated_at: stamp, policy_version: 'fixture', total: 1, grouped_total: 1, offset: 0, limit: 50, next_offset: null, cohort_counts: { action_now: 0, research: 0, watch: 1, reject: 0 }, daily: { evaluated: 1, surfaced: 1, contacted: 0 }, items: [{ ...item, disposition: 'WATCH' }] } }))
  await page.goBack()
  await page.goBack()
  await expect(page.getByRole('button', { name: 'WATCH 1', exact: true })).toBeFocused()
})

test('authentication rejection clears the currently mounted commercial note', async ({ page }) => {
  await commercialEnvironment(page)
  await page.route('**/api/commercial/triage/evaluate*', (route) => route.fulfill({ status: 401 }))
  await page.goto('/?view=environment&mode=pursuits&pursuitNeed=a')
  await page.getByLabel('Note', { exact: true }).fill('Private mounted note')
  await page.getByText('Queue details and research updates', { exact: true }).click()
  await page.getByRole('button', { name: 'Evaluate Signals' }).click()
  await expect(page.getByText(/Your session ended/).first()).toBeVisible()
  await expect(page.getByLabel('Note', { exact: true })).toHaveValue('')
})

test('quiet queue keeps supporting context discoverable and restores its disclosure', async ({ page }) => {
  await commercialEnvironment(page)
  await page.goto('/?view=environment&mode=pursuits')
  await expect(page.getByRole('button', { name: /Commercial fixture A/ })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Current cohort summary' })).not.toBeVisible()
  await expect(page.getByText('Fixture reason', { exact: false })).not.toBeVisible()
  const summary = page.getByText('Queue details and research updates', { exact: true })
  await summary.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('region', { name: 'Current cohort summary' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Evaluate Signals', exact: true })).toBeVisible()
  await page.getByRole('button', { name: /Commercial fixture A/ }).click()
  const investigate = page.getByRole('button', { name: 'Investigate this need' })
  expect(await investigate.evaluate((el) => !!(el.compareDocumentPosition(document.querySelector('.commercial-detail')!) & Node.DOCUMENT_POSITION_FOLLOWING))).toBe(true)
  await investigate.click()
  await page.goBack()
  await expect(page.locator('[data-context-key="queue-context"]')).toHaveAttribute('open', '')
  await expect(investigate).toBeFocused()
})

test('Back waits for the expanded national preview before restoring scroll and focus', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  const item = await commercialEnvironment(page)
  let delayed = false
  await page.route('**/api/commercial/triage?*', async (route) => {
    if (delayed) await new Promise((resolve) => setTimeout(resolve, 900))
    await route.fulfill({ json: {
      evaluated_at: stamp, policy_version: 'fixture', total: 1, grouped_total: 1, offset: 0, limit: 50, next_offset: null,
      cohort_counts: { action_now: 1, research: 0, watch: 0, reject: 0 }, daily: { evaluated: 1, surfaced: 1, contacted: 0 },
      items: [{ ...item, reason: 'Retained fixture context. '.repeat(80) }],
    } })
  })
  await page.goto('/')
  await page.getByText('Today’s queue preview', { exact: true }).click()
  await expect(page.getByRole('heading', { name: /Commercial fixture A/ })).toBeVisible()
  const open = page.getByRole('button', { name: 'Open full pursuit queue' })
  await open.scrollIntoViewIfNeeded()
  await open.focus()
  const y = await page.evaluate(() => scrollY)
  expect(y).toBeGreaterThan(800)
  await open.click()
  await expect(page.getByRole('button', { name: /Commercial fixture A/ })).toBeVisible()
  delayed = true
  await page.goBack()
  await expect(page.locator('[data-context-key="today-preview"]')).toHaveAttribute('open', '')
  await expect(page.getByRole('heading', { name: /Commercial fixture A/ })).toBeVisible()
  await expect(open).toBeFocused()
  await expect.poll(() => page.evaluate(() => scrollY)).toBeCloseTo(y, 0)
})
