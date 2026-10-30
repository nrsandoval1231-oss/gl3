import { expect, test } from '@playwright/test'

const syntheticOpportunity = (index: number, tier: string, sector: string) => ({
  id: `synthetic-discovery-${index}`,
  project_id: `synthetic-project-${index}`,
  name: `Sourced project ${index}`,
  browse_title: `Sourced project ${index}`,
  company: `Sourced company ${index}`,
  location: index % 2 ? 'Midland, TX' : 'Dallas, TX',
  sector,
  asset_type: sector === 'data_centers' ? 'Data center' : 'Industrial facility',
  priority_score: 50 - index,
  representative_need_id: `synthetic-need-${index}`,
  need_count: 1,
  needs: [{ id: `synthetic-need-${index}`, project_id: `synthetic-project-${index}`, name: `Sourced project ${index}`, browse_title: `Sourced project ${index}`, tier }],
  event: null,
  contact: [],
  power_summary: null,
  power_summary_kind: 'unknown',
  next_action: null,
  updated_at: '2026-10-28T00:00:00Z',
})

const pageFor = (url: URL) => {
  const sector = url.searchParams.get('sector') ?? 'all'
  const offset = Number(url.searchParams.get('offset') ?? 0)
  const isDiscovery = url.searchParams.get('include_signals') === 'true'
  const tier = 'Signal'
  const total = isDiscovery ? 26 : 0
  const count = offset === 25 ? 1 : 25
  return {
    items: Array.from({ length: isDiscovery ? count : 0 }, (_, i) => syntheticOpportunity(offset + i + 1, tier, sector === 'all' ? (i % 2 ? 'oil_gas' : 'data_centers') : sector)),
    total,
    count_unit: 'projects',
    limit: 25,
    offset,
    cohort_token: `cohort-${sector}-${url.searchParams.get('search') ?? 'all'}`,
    generation: 'source-backed-generation',
    results_scope: isDiscovery ? 'discovery' : 'qualified',
  }
}

test('synthetic All view requests discovery so Signals render, and pagination and filters keep that scope', async ({ page }) => {
  const requests: URL[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/projects?**', route => {
    const url = new URL(route.request().url())
    requests.push(url)
    return route.fulfill({ json: pageFor(url) })
  })

  await page.goto('/?view=workspace')
  await expect(page.getByRole('heading', { name: 'Opportunities' })).toBeVisible()
  await expect.poll(() => requests[0]?.searchParams.get('include_signals')).toBe('true')
  await expect(page.locator('.cfr-table tbody tr')).toHaveCount(25)
  await expect(page.locator('.cfr-table tbody tr').first()).toContainText('Qualification: Signal')
  await expect(page.locator('.cfr-heading')).toContainText('Signals included')

  await page.getByRole('button', { name: 'Next', exact: true }).click()
  await expect.poll(() => requests.at(-1)?.searchParams.get('offset')).toBe('25')
  await expect.poll(() => requests.at(-1)?.searchParams.get('include_signals')).toBe('true')
  await expect(page.locator('.cfr-table tbody tr')).toHaveCount(1)
  await expect(page.locator('.cfr-table tbody tr').first()).toContainText('Qualification: Signal')

  await page.getByRole('combobox', { name: 'Project type' }).selectOption('data_centers')
  await expect.poll(() => requests.at(-1)?.searchParams.get('sector')).toBe('data_centers')
  await expect.poll(() => requests.at(-1)?.searchParams.get('include_signals')).toBe('true')
  await expect(page.locator('.cfr-table tbody tr').first()).toContainText('Qualification: Signal')

  await page.getByRole('textbox', { name: 'Search opportunities' }).fill('Mesa')
  await expect.poll(() => requests.some(url => url.searchParams.get('search') === 'Mesa' && url.searchParams.get('include_signals') === 'true')).toBeTruthy()
  expect(requests.every(url => url.searchParams.get('include_signals') === 'true')).toBe(true)
})
