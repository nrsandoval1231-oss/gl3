import { expect, test, type Page } from '@playwright/test'

// Distinct per-sector values so a swapped or merged vertical cannot pass.
const SECTOR = { all: { mw: 40.5, doc: 3, calc: 2 }, oil_gas: { mw: 11.5, doc: 1, calc: 4 }, data_centers: { mw: 29, doc: 2, calc: 7 } } as const
const summary = (sector: string, available = true, complete = true) => ({
  availability: available ? 'available' : 'unavailable', counts_complete: complete, sector, as_of: '2026-11-01T00:00:00Z',
  totals: available ? { identified_records: 5, known_mw_records: 3, unknown_records: 2, conflicted_records: 0 } : { identified_records: 6, known_mw_records: 0, unknown_records: 5, conflicted_records: 1 },
  classes: { documented: { mw: available ? SECTOR[sector as keyof typeof SECTOR].mw : null, record_count: available ? SECTOR[sector as keyof typeof SECTOR].doc : 0 }, calculated: { mw: null, record_count: available ? SECTOR[sector as keyof typeof SECTOR].calc : 0 }, estimated: { mw: null, record_count: 0 } },
  provenance: { contract: 'equipment-demand-v1', source_count: 2, latest_evidence_at: null }, limitations: ['Synthetic limitation text.'],
})
async function mock(page: Page, opts: { demand?: 'ok' | 'unavailable' | 'incomplete' | 'error'; projects?: 'ok' | 'error'; tiers?: 'ok' | 'error' | 'no-header' } = {}) {
  await page.route(url => url.pathname.startsWith('/api/'), route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (url.pathname === '/api/opportunities/demand-summary') {
      if (opts.demand === 'error') return route.fulfill({ status: 500, json: {} })
      return route.fulfill({ json: summary(url.searchParams.get('sector') ?? 'all', opts.demand !== 'unavailable' && opts.demand !== 'incomplete', opts.demand !== 'incomplete') })
    }
    if (url.pathname === '/api/opportunities/projects') return opts.projects === 'error' ? route.fulfill({ status: 500, json: {} }) : route.fulfill({ json: { items: [], total: 42, count_unit: 'projects', limit: 1, offset: 0, cohort_token: 'p', generation: 'g', results_scope: 'qualified' } })
    if (url.pathname === '/api/opportunities/groups') return route.fulfill({ json: { items: [], total: 9, count_unit: 'groups', limit: 1, offset: 0, cohort_token: 'c', generation: 'g' } })
    if (url.pathname === '/api/opportunities') {
      if (opts.tiers === 'error') return route.fulfill({ status: 500, json: {} })
      if (opts.tiers === 'no-header') return route.fulfill({ json: [] })
      const tier = url.searchParams.get('tier')
      return route.fulfill({ json: [], headers: { 'X-Total-Count': String(tier === 'Signal' ? 30 : tier === 'Prospect' ? 10 : 5), 'X-Group-Total-Count': '1', 'X-Cohort-Token': 't', 'X-Limit': '1', 'X-Offset': '0' } })
    }
    if (url.pathname === '/api/commercial-pursuits') return route.fulfill({ json: { items: [], counts: { total: 4, active: 3, needs_attention: 0 } } })
    if (url.pathname === '/api/opportunities/workspace/changes') return route.fulfill({ json: { items: [], counts: { discovered: 0, changed: 0, promoted: 0, closed: 0, review_exception: 0 }, total_unreviewed: 0, offset: 0, limit: 50, next_offset: null, baseline_identity: 't', token: 't', source_health_exceptions: [] } })
    return route.fulfill({ json: [] })
  })
}

test('reports show real supported metrics with definitions and keep existing content', async ({ page }) => {
  await mock(page)
  await page.goto('/?view=workspace&panel=reports')
  const reports = page.getByRole('region', { name: 'Reports' })
  await expect(reports.getByRole('heading', { name: 'Reports', level: 1 })).toBeVisible()
  await expect(reports.getByRole('article', { name: 'Total Projects' })).toContainText('42')
  await expect(reports.getByRole('article', { name: 'Total Projects' })).toContainText('qualified scope')
  await expect(reports.getByRole('article', { name: 'Operator/customer groups' })).toContainText('9')
  await expect(reports.getByRole('article', { name: 'Operator/customer groups' })).toContainText('not a count of confirmed companies')
  await expect(reports.getByRole('article', { name: 'Companies' })).toHaveCount(0)
  await expect(reports.getByRole('article', { name: 'Active Pursuits' })).toContainText('3')
  const demand = reports.getByRole('article', { name: 'Identified Demand' })
  await expect(demand).toContainText('5 identified records')
  await expect(demand).toContainText('Documented40.5 MW')
  await expect(demand).toContainText('Calculated')
  await expect(demand).toContainText('Unknown · 2 records')
  await expect(demand).toContainText('not total portfolio demand')
  await expect(demand).not.toContainText(/\bGW\b/)
  const bars = reports.getByRole('region', { name: 'Activity and pipeline' })
  await expect(bars).toContainText('Signal')
  await expect(bars.getByRole('listitem').nth(0)).toContainText('30')
  await expect(bars.getByRole('listitem').nth(1)).toContainText('10')
  await expect(bars.getByRole('listitem').nth(2)).toContainText('5')
  await expect(bars).toContainText('not Pursuit stages')
  const oil = reports.locator('.rpt-vertical', { has: page.getByRole('heading', { name: 'Oil & Gas' }) })
  const dc = reports.locator('.rpt-vertical', { has: page.getByRole('heading', { name: 'Data Centers' }) })
  await expect(oil).toContainText('Documented 11.5 MW')
  await expect(oil).not.toContainText('29 MW')
  await expect(dc).toContainText('Documented 29 MW')
  await expect(dc).not.toContainText('11.5 MW')
  await expect(reports.getByRole('region', { name: 'Not yet available' })).toContainText('Demand by Vertical chart')
  await expect(reports.getByRole('region', { name: 'Not yet available' })).not.toContainText('no existing endpoint')
  await expect(reports.locator('svg circle')).toHaveCount(0)
  await expect(reports).toContainText("Export the current results with the table's Export action")
  await expect(reports.getByRole('region', { name: 'Material changes' })).toBeVisible()
})

test('unavailable demand and failed requests render honest states, not numbers', async ({ page }) => {
  await mock(page, { demand: 'unavailable', projects: 'error', tiers: 'error' })
  await page.goto('/?view=workspace&panel=reports')
  const reports = page.getByRole('region', { name: 'Reports' })
  const demand = reports.getByRole('article', { name: 'Identified Demand' })
  await expect(demand).toContainText('Unavailable')
  await expect(demand).toContainText('Unknown is not zero')
  await expect(demand).toContainText('6 identified records · 0 with MW · 5 unknown · 1 conflicted')
  await expect(demand).toContainText('Synthetic limitation text.')
  await expect(demand).not.toContainText('No supported equipment demand records')
  await expect(demand).not.toContainText(/\d+ MW/)
  const oilUnavailable = reports.locator('.rpt-vertical', { has: page.getByRole('heading', { name: 'Oil & Gas' }) })
  await expect(oilUnavailable).toContainText('6 identified records')
  await expect(oilUnavailable).toContainText('Synthetic limitation text.')
  await expect(oilUnavailable).not.toContainText('no supported equipment demand records')
  const projects = reports.getByRole('article', { name: 'Total Projects' })
  await expect(projects).toContainText('Unavailable')
  await expect(projects.getByRole('button', { name: 'Retry' })).toBeVisible()
  await expect(projects).not.toContainText('42')
  const bars = reports.getByRole('region', { name: 'Activity and pipeline' })
  await expect(bars.getByRole('alert')).toContainText('Qualification counts are unavailable')
  await expect(bars.getByRole('listitem')).toHaveCount(0)
})

test('demand summary error shows retry and reports fit 390px', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mock(page, { demand: 'error' })
  await page.goto('/?view=workspace&panel=reports')
  const demand = page.getByRole('article', { name: 'Identified Demand' })
  await expect(demand).toContainText('Unavailable')
  await expect(demand.getByRole('button', { name: 'Retry' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
})

test('unavailable demand with incomplete counts says counts are unavailable, never none', async ({ page }) => {
  await mock(page, { demand: 'incomplete' })
  await page.goto('/?view=workspace&panel=reports')
  const reports = page.getByRole('region', { name: 'Reports' })
  await expect(reports.getByRole('article', { name: 'Identified Demand' })).toContainText('Record counts are unavailable.')
  await expect(reports.locator('.rpt-vertical').first()).toContainText('Record counts are unavailable.')
  await expect(reports).not.toContainText('No supported equipment demand records')
})

test('a response without X-Total-Count shows the retryable error, not 0', async ({ page }) => {
  await mock(page, { tiers: 'no-header' })
  await page.goto('/?view=workspace&panel=reports')
  const bars = page.getByRole('region', { name: 'Reports' }).getByRole('region', { name: 'Activity and pipeline' })
  await expect(bars.getByRole('alert')).toContainText('Qualification counts are unavailable')
  await expect(bars.getByRole('button', { name: 'Retry' })).toBeVisible()
  await expect(bars.getByRole('listitem')).toHaveCount(0)
})

test('session end clears every report figure and change item', async ({ page }) => {
  await mock(page)
  await page.goto('/?view=workspace&panel=reports')
  const reports = page.getByRole('region', { name: 'Reports' })
  await expect(reports.getByRole('article', { name: 'Total Projects' })).toContainText('42')
  await page.evaluate(() => window.dispatchEvent(new Event('gl3-clear-continuity')))
  await expect(reports.getByRole('alert')).toContainText('Your session ended. Sign in again.')
  await expect(reports.getByRole('article')).toHaveCount(0)
  await expect(reports.getByText('42')).toHaveCount(0)
  await expect(reports.getByText('40.5')).toHaveCount(0)
})
