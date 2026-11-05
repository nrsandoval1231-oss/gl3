import { mockDemandSummary } from './mock-demand-summary'
import { expect, test, type Page } from '@playwright/test'

// Synthetic UI fixtures only. The server order intentionally crosses a page boundary.
const projects = Array.from({ length: 26 }, (_, index) => ({
  id: `sort-project-${index}`, project_id: `sort-project-${index}`,
  name: index === 25 ? 'Alpha site' : `Zulu site ${String(index).padStart(2, '0')}`,
  company: index === 25 ? 'Aardvark Company' : 'Zebra Company',
  location: index === 25 ? 'Dallas, TX' : 'Midland, TX', sector: 'oil_gas', asset_type: 'Compressor station',
  priority_score: 100 - index, representative_need_id: `sort-need-${index}`, need_count: 1,
  needs: [{ id: `sort-need-${index}`, tier: 'Signal', activity: 'compression' }],
  event: null, contact: [], power_summary: null, power_summary_kind: 'unknown', updated_at: '2026-10-30T00:00:00Z',
}))

async function setup(page: Page) {
  const requests: URL[] = []
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (url.pathname === '/api/opportunities/projects') {
      requests.push(url)
      const sort = url.searchParams.get('sort') ?? 'priority'
      const need = url.searchParams.get('need_id')
      const offset = Number(url.searchParams.get('offset') ?? 0)
      const ordered = sort === 'company' || sort === 'project' || sort === 'priority_asc'
        ? [projects[25], ...projects.slice(0, 25)] : projects
      const items = need ? projects.filter(project => project.needs[0].id === need) : ordered.slice(offset, offset + 25)
      return route.fulfill({ json: { items, total: need ? items.length : 26, count_unit: 'projects', offset, limit: need ? 1 : 25, cohort_token: `synthetic-sort-${sort}`, generation: 'synthetic-sort', results_scope: 'discovery' } })
    }
    if (url.pathname.startsWith('/api/opportunities/needs/')) {
      const project = projects.find(value => value.needs[0].id === url.pathname.split('/').at(-1))!
      return route.fulfill({ json: { id: project.needs[0].id, project_id: project.id, name: project.name, browse_title: project.name, location: project.location, tier: 'Signal', activity: 'compression', priority_score: project.priority_score, required_mw: null, start_window: null, duration: null, supply: 'Unknown', rationale: 'Synthetic source-backed fixture.', workflow_status: 'New', evidence: [] } })
    }
    return route.fulfill({ json: [] })
  })
  return requests
}

for (const sort of ['company', 'project'] as const) {
  test(`${sort} sort requests the complete cohort and resets pagination`, async ({ page }) => {
    const requests = await setup(page)
    await mockDemandSummary(page)
  await page.goto('/?view=workspace&projectBrowse=1')
    await expect(page.locator('.cfr-table tbody tr')).toHaveCount(25)
    await page.getByRole('button', { name: 'Next', exact: true }).click()
    await expect(page.locator('.cfr-table tbody tr')).toHaveCount(1)
    await page.getByRole('combobox', { name: 'Sort opportunities' }).selectOption(sort)
    await expect(page.locator('.cfr-table tbody tr').first()).toContainText('Alpha site')
    await expect(page.locator('.cfr-table tbody tr')).toHaveCount(25)
    expect(requests.at(-1)?.searchParams.get('sort')).toBe(sort)
    expect(requests.at(-1)?.searchParams.get('offset')).toBe('0')
    expect(requests.at(-1)?.searchParams.has('cohort_token')).toBe(false)
    await expect(page).toHaveURL(new RegExp(`sort=${sort}`))
    await page.getByRole('button', { name: 'Next', exact: true }).click()
    await expect(page.locator('.cfr-table tbody tr')).toHaveCount(1)
    expect(requests.at(-1)?.searchParams.get('sort')).toBe(sort)
    expect(requests.at(-1)?.searchParams.get('cohort_token')).toBe(`synthetic-sort-${sort}`)
  })
}

test('priority ascending belongs to the server cohort and survives detail/back and reload', async ({ page }) => {
  const requests = await setup(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await mockDemandSummary(page)
  await page.goto('/?view=workspace&projectBrowse=1')
  await expect(page.locator('.cfr-table tbody tr')).toHaveCount(25)
  await page.getByRole('button', { name: 'Priority ↓', exact: true }).click()
  await expect(page.locator('.cfr-table tbody tr').first()).toContainText('Alpha site')
  expect(requests.at(-1)?.searchParams.get('sort')).toBe('priority_asc')
  await expect(page).toHaveURL(/sort=priority_asc/)
  await page.getByRole('button', { name: 'Alpha site', exact: true }).click()
  await expect(page.locator('.cod-panel h2')).toContainText('Alpha site')
  await expect(page).toHaveURL(/sort=priority_asc/)
  await page.locator('.cod-back').click()
  await expect(page.locator('.cfr-table tbody tr').first()).toContainText('Alpha site')
  await expect(page.locator('th[aria-sort="ascending"]')).toBeVisible()
  await page.reload()
  await expect(page.locator('.cfr-table tbody tr').first()).toContainText('Alpha site')
  expect(requests.at(-1)?.searchParams.get('sort')).toBe('priority_asc')
})

test('browser Back restores sort and its cached cohort without mixing rows', async ({ page }) => {
  const requests = await setup(page)
  await mockDemandSummary(page)
  await page.goto('/?view=workspace&projectBrowse=1&sort=project')
  await expect(page.locator('.cfr-table tbody tr').first()).toContainText('Alpha site')
  await expect(page.getByRole('combobox', { name: 'Sort opportunities' })).toHaveValue('project')
  await page.getByRole('combobox', { name: 'Sort opportunities' }).selectOption('priority')
  await expect(page.locator('.cfr-table tbody tr').first()).toContainText('Zulu site 00')
  await page.goBack()
  await expect(page.getByRole('combobox', { name: 'Sort opportunities' })).toHaveValue('project')
  await expect(page.locator('.cfr-table tbody tr').first()).toContainText('Alpha site')
  expect(requests.at(-1)?.searchParams.get('sort')).toBe('project')
})

test('sorting beside an open desktop detail clears the need without undoing the new sort', async ({ page }) => {
  await setup(page)
  await mockDemandSummary(page)
  await page.goto('/?view=workspace&projectBrowse=1')
  await page.getByRole('button', { name: 'Zulu site 00', exact: true }).click()
  await expect(page.locator('.cod-panel h2')).toContainText('Zulu site 00')
  await page.getByRole('combobox', { name: 'Sort opportunities' }).selectOption('company')
  await expect(page.getByRole('combobox', { name: 'Sort opportunities' })).toHaveValue('company')
  await expect(page.locator('.cfr-table tbody tr').first()).toContainText('Alpha site')
  await expect(page).toHaveURL(/sort=company/)
  await expect(page).not.toHaveURL(/need=/)
  await expect(page.locator('.cod-panel h2')).toHaveCount(0)
  await page.reload()
  await expect(page.locator('.cfr-table tbody tr').first()).toContainText('Alpha site')
})

test('an empty filtered page reports visible matches separately from the cohort range', async ({ page }) => {
  await setup(page)
  await mockDemandSummary(page)
  await page.goto('/?view=workspace&projectBrowse=1')
  await expect(page.locator('.cfr-table tbody tr')).toHaveCount(25)
  await page.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(page.locator('.cfr-table tbody tr')).toHaveCount(1)
  await page.getByRole('combobox', { name: 'Region', exact: true }).selectOption('Dallas, TX')
  await page.getByRole('button', { name: 'Previous', exact: true }).click()
  await expect(page.getByText('No projects match these page filters.')).toBeVisible()
  await expect(page.locator('.cfr-paging')).toContainText('0 of 25 projects on this page match filters')
  await expect(page.locator('.cfr-paging')).toContainText('1–25 of 26 projects')
  await expect(page.locator('.cfr-paging')).not.toContainText('1–0')
})

test('an empty server page beyond a smaller cohort reports no inverted range', async ({ page }) => {
  await setup(page)
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: {
    items: [], total: 10, count_unit: 'projects', offset: 25, limit: 25,
    cohort_token: 'synthetic-smaller-cohort', generation: 'synthetic-sort', results_scope: 'discovery',
  } }))
  await mockDemandSummary(page)
  await page.goto('/?view=workspace&projectBrowse=1&offset=25&cohort_token=synthetic-smaller-cohort')
  await expect(page.locator('.cfr-paging')).toContainText('0 projects on this page · 10 projects total')
  await expect(page.locator('.cfr-paging')).not.toContainText('26–25')
  await expect(page.getByRole('button', { name: 'Previous', exact: true })).toBeEnabled()
  await expect(page.getByRole('button', { name: 'Next', exact: true })).toBeDisabled()
})
