import { expect, test } from '@playwright/test'

const pageFixture = {
  items: [
    { id: 'p1', project_id: 'p1', name: 'Northstar Energy · Mesa Compressor', company: 'Northstar Energy', location: 'Midland, TX', sector: 'oil_gas', asset_type: 'Compressor station', priority_score: 42, representative_need_id: 'n1', need_count: 2, needs: [{ id: 'n1', tier: 'Signal', activity: 'compression' }, { id: 'n2', tier: 'Prospect', activity: 'construction power' }], event: { kind: 'permit_issued', label: 'Permit issued', date: '2026-10-10' }, contact: [], power_summary: null, power_summary_kind: 'unknown', next_action: null, updated_at: '2026-10-28T00:00:00Z' },
    { id: 'p2', project_id: 'p2', name: 'Copperline Data · Mesa Campus', company: 'Copperline Data', location: 'Phoenix, AZ', sector: 'data_centers', asset_type: 'Campus', priority_score: null, representative_need_id: 'n3', need_count: 1, needs: [{ id: 'n3', tier: 'Lead' }], event: null, contact: [], power_summary: '420 MW supported residual gap', power_summary_kind: 'supported_gap', next_action: null, updated_at: '2026-10-28T00:00:00Z' },
  ], total: 2, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'synthetic-flat', generation: 'synthetic', results_scope: 'discovery',
}

test('synthetic flat results render company/project rows, honest KPIs, filters, selection and full-cohort server search', async ({ page }) => {
  const requests: URL[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/projects?*', route => { requests.push(new URL(route.request().url())); return route.fulfill({ json: pageFixture }) })
  await page.goto('/?view=workspace')

  await expect(page.getByRole('heading', { name: 'Opportunities' })).toBeVisible()
  await expect.poll(() => requests[0]?.searchParams.get('include_signals')).toBe('true')
  await expect(page.locator('.cfr-table tbody tr')).toHaveCount(2)
  await expect(page.locator('.cfr-kpis')).toContainText('2')
  await expect(page.locator('.cfr-kpis')).toContainText('Signals included')
  await expect(page.locator('.cfr-kpis')).toContainText('Priority classification unavailable')
  await expect(page.locator('.cfr-kpis')).toContainText('Creation date unavailable')
  await expect(page.locator('.cfr-table')).toContainText('Northstar Energy')
  await expect(page.locator('.cfr-table')).toContainText('Mesa Compressor')
  await expect(page.locator('.cfr-table')).toContainText('Permit issued')
  await expect(page.locator('.cfr-table')).toContainText('Qualification: Signal')
  await expect(page.getByText('2 related power needs')).toBeVisible()

  await page.getByRole('combobox', { name: 'Region' }).selectOption({ label: 'Midland, TX' })
  await expect(page.locator('.cfr-table tbody tr')).toHaveCount(1)
  await page.getByRole('combobox', { name: 'Region' }).selectOption('')
  await page.getByRole('checkbox', { name: 'Select all visible projects' }).check()
  await expect(page.getByRole('checkbox', { name: 'Select Mesa Compressor' })).toBeChecked()

  await page.getByRole('textbox', { name: 'Search opportunities' }).fill('alternate source alias')
  await expect.poll(() => requests.some(url => url.searchParams.get('search') === 'alternate source alias')).toBeTruthy()
})

test('synthetic repeated cohort conflict stops after one reset and presents a retry', async ({ page }) => {
  let reads = 0
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/projects?*', route => { reads += 1; return route.fulfill({ status: 409, json: { detail: 'cohort changed' } }) })
  await page.goto('/?view=workspace')
  await expect(page.getByRole('alert')).toContainText('Results changed again')
  expect(reads).toBeLessThanOrEqual(3)
})

test('synthetic logout while a request is pending cannot repopulate rows or cache', async ({ page }) => {
  let release: (() => void) | undefined
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/projects?*', async route => {
    await new Promise<void>(resolve => { release = resolve })
    return route.fulfill({ json: pageFixture })
  })
  await page.goto('/?view=workspace')
  await page.evaluate(() => window.dispatchEvent(new Event('gl3-clear-continuity')))
  await expect(page.getByRole('alert')).toContainText('session ended')
  release?.()
  await page.waitForTimeout(150)
  await expect(page.locator('.cfr-table tbody tr')).toHaveCount(0)
})

test('synthetic logout while results are unmounted clears module cache before returning', async ({ page }) => {
  let projectReads = 0
  let holdNext = false
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/projects?*', async route => {
    projectReads += 1
    if (holdNext) return new Promise<void>(() => {})
    return route.fulfill({ json: pageFixture })
  })
  await page.goto('/?view=workspace')
  await expect(page.locator('.cfr-table tbody tr')).toHaveCount(2)
  await page.getByRole('button', { name: 'Intelligence' }).click()
  await page.evaluate(() => window.dispatchEvent(new Event('gl3-clear-continuity')))
  holdNext = true
  await page.getByRole('button', { name: 'Opportunities' }).click()
  await expect(page.getByRole('status')).toContainText('Loading current opportunities')
  await expect(page.locator('.cfr-table tbody tr')).toHaveCount(0)
  expect(projectReads).toBeGreaterThanOrEqual(2)
})

test('synthetic empty and error states do not produce repeated React update errors', async ({ page }) => {
  const consoleErrors: string[] = []
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ status: 503, json: { detail: 'unavailable' } }))
  await page.goto('/?view=workspace')
  await expect(page.getByRole('alert')).toContainText('Could not load projects')
  await expect.poll(() => consoleErrors.filter(error => /maximum update depth|too many re-renders/i.test(error)).length).toBe(0)
})

test('synthetic related need navigation restores focus to its exact need control', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: pageFixture }))
  await page.route('**/api/opportunities/needs/**', route => route.fulfill({ json: { id: 'n2', project_id: 'p1', name: 'Synthetic related need', browse_title: 'Synthetic related need', location: 'Midland, TX', tier: 'Prospect', activity: 'construction power', priority_score: 42, required_mw: null, start_window: null, duration: null, supply: 'Unknown', rationale: 'Synthetic fixture', workflow_status: 'New' } }))
  await page.goto('/?view=workspace')
  await expect(page.locator('.cfr-table tbody tr')).toHaveCount(2)
  await page.getByText('2 related power needs').click()
  const relatedNeed = page.locator('[data-need-row="n2"]')
  await expect(relatedNeed).toBeEnabled()
  await relatedNeed.click()
  await expect(page).toHaveURL(/need=n2/)
  await page.locator('.cod-back').click()
  await expect(page.locator('[data-need-row="n2"]')).toBeFocused()
})

test('synthetic unavailable browse response stays visible for explicit retry', async ({ page }) => {
  let reads = 0
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/projects?*', route => { reads += 1; return route.fulfill({ status: 503, headers: { 'X-Qualification-State': 'pending', 'retry-after': '0' }, json: { detail: 'browse pending' } }) })
  await page.goto('/?view=workspace')
  await expect(page.getByRole('alert')).toContainText('Could not load projects (503)')
  expect(reads).toBeLessThanOrEqual(2)
})

test('malformed browse payload fails safely while an exact selected need remains available', async ({ page }) => {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: [] }))
  await page.route('**/api/opportunities/needs/n2*', route => route.fulfill({ json: {
    id: 'n2', project_id: 'p1', name: 'Exact selected need', browse_title: 'Exact selected need',
    location: 'Midland, TX', tier: 'Prospect', activity: 'construction power', priority_score: 42,
    required_mw: null, start_window: null, duration: null, supply: 'Unknown', rationale: 'Synthetic fixture', workflow_status: 'New',
  } }))

  await page.goto('/?view=workspace&need=n2')
  await expect(page.getByRole('heading', { name: 'Exact selected need' })).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('Current project results could not be confirmed')
})
