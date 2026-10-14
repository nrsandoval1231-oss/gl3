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

async function mock(page: Page, items: Opportunity[], opportunities?: (route: Route) => Promise<void>) {
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (!path.startsWith('/api/')) return route.continue()
    if (path === '/api/opportunities' && opportunities) return opportunities(route)
    const json = (body: unknown, headers: Record<string, string> = {}) =>
      route.fulfill({ contentType: 'application/json', headers, body: JSON.stringify(body) })
    if (path === '/api/auth/session') return json({ authenticated: true })
    if (path === '/api/opportunities') return json(items, { 'X-Total-Count': String(items.length) })
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

test('lens and tier changes query the server and reset to the nation', async ({ page }) => {
  const queries: URLSearchParams[] = []
  await mock(page, [opportunity('a', 'Austin, TX')])
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (url.pathname === '/api/opportunities') queries.push(url.searchParams)
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
