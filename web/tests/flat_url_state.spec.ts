import { expect, test, type Page } from '@playwright/test'
import { mockDemandSummary } from './mock-demand-summary'

// SYNTHETIC UI TEST FIXTURE ONLY. Flat default browse: page-local filters, legacy sort and paging stay consistent with the URL.

const mk = (index: number, location: string, kind: string, score: number | null) => ({
  id: `p${index}`, project_id: `p${index}`, name: `Acme ${index} · Site ${index}`, company: `Acme ${index}`, location, sector: 'oil_gas', asset_type: 'compressor_station',
  priority_score: score, representative_need_id: `n${index}`, need_count: 1, needs: [{ id: `n${index}`, project_id: `p${index}`, tier: 'Lead', activity: 'drilling' }],
  event: { kind, label: kind, date: null }, contact: [], contact_people: [], power_summary: null, power_summary_kind: 'unknown', updated_at: '2026-10-21T00:00:00Z',
})
const first = [mk(1, 'Permian Basin, TX', 'Permit issued', 10), mk(2, 'Permian Basin, TX', 'Permit issued', null), mk(3, 'Dallas, TX', 'Construction', 5)]
const second = [mk(4, 'Dallas, TX', 'Construction', 7)]
const detail = (id: string) => ({
  id, project_id: id.replace('n', 'p'), name: `Site ${id}`, browse_title: `Site ${id}`, location: 'Permian Basin, TX', tier: 'Lead', workflow_status: 'New', activity: 'drilling', rationale: 'Synthetic.',
  signal_evidence_state: 'active_evidence', required_mw: null, start_window: null, duration: null, supply: 'Unknown', next_action: 'Confirm.', conflict_state: 'Not assessed',
  title_company: 'Acme', commercial_organization: 'Acme', evidence: [], missing_facts: [],
})

async function mock(page: Page) {
  const requests: URL[] = []
  await mockDemandSummary(page)
  await page.route(url => url.pathname.startsWith('/api/') && !url.pathname.includes('demand-summary'), route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (url.pathname === '/api/opportunities/projects') {
      requests.push(url)
      const offset = Number(url.searchParams.get('offset') ?? 0)
      return route.fulfill({ json: { items: offset ? second : first, total: 4, count_unit: 'projects', limit: 3, offset, cohort_token: 'flat-url', generation: 'g', results_scope: 'discovery', valid_until: '2099-01-01T00:00:00Z' } })
    }
    const match = /\/api\/opportunities\/needs\/(n\d)$/.exec(url.pathname)
    if (match) return route.fulfill({ json: detail(match[1]) })
    if (url.pathname === '/api/commercial-pursuits') return route.fulfill({ json: { items: [], counts: { total: 0, active: 0, needs_attention: 0 }, total_matching: 0, has_more: false, next_offset: null } })
    return route.fulfill({ json: [] })
  })
  return requests
}
const params = (page: Page) => new URL(page.url()).searchParams
const rows = (page: Page) => page.locator('.cfr-table tbody tr')
const bookmark = '/?view=workspace&projectBrowse=1&shortlist=0&region=Permian+Basin%2C+TX&stage=Permit+issued&priority=ranked&sort=updated'

test('an old bookmark seeds region, stage and priority, filters the page, and drops the unsupported sort', async ({ page }) => {
  await mock(page)
  await page.goto(bookmark)
  await expect(rows(page)).toHaveCount(1)
  await expect(rows(page).first()).toContainText('Acme 1')
  await expect(page.getByRole('combobox', { name: 'Region', exact: true })).toHaveValue('Permian Basin, TX')
  await expect(page.getByRole('combobox', { name: 'Stage', exact: true })).toHaveValue('Permit issued')
  await expect(page.getByRole('combobox', { name: 'Priority', exact: true })).toHaveValue('ranked')
  await expect(page.getByRole('combobox', { name: 'Sort opportunities' })).toHaveValue('priority')
  expect(params(page).has('sort')).toBe(false)
  expect(params(page).get('region')).toBe('Permian Basin, TX')
  await page.reload()
  await expect(rows(page)).toHaveCount(1)
  await expect(page.getByRole('combobox', { name: 'Priority', exact: true })).toHaveValue('ranked')
  // Selecting keeps the filters and never reintroduces sort=updated.
  await page.locator('[data-need-row="n1"]').click()
  await expect(page).toHaveURL(/need=n1/)
  expect(params(page).get('region')).toBe('Permian Basin, TX')
  expect(params(page).get('stage')).toBe('Permit issued')
  expect(params(page).get('priority')).toBe('ranked')
  expect(params(page).get('sort')).not.toBe('updated')
  await page.goBack()
  await expect(page.getByRole('combobox', { name: 'Region', exact: true })).toHaveValue('Permian Basin, TX')
  await expect(rows(page)).toHaveCount(1)
})

test('changing and clearing page filters writes and removes their URL params', async ({ page }) => {
  await mock(page)
  await page.goto(bookmark)
  await expect(rows(page)).toHaveCount(1)
  await page.getByRole('combobox', { name: 'Priority', exact: true }).selectOption('')
  await expect.poll(() => params(page).has('priority')).toBe(false)
  await expect(rows(page)).toHaveCount(2)
  await page.getByRole('button', { name: 'Clear', exact: true }).click()
  await expect(rows(page)).toHaveCount(3)
  await expect.poll(() => ['region', 'stage', 'priority', 'sort'].some(key => params(page).has(key))).toBe(false)
  await page.getByRole('combobox', { name: 'Region', exact: true }).selectOption('Dallas, TX')
  await expect(rows(page)).toHaveCount(1)
  await expect.poll(() => params(page).get('region')).toBe('Dallas, TX')
  await page.reload()
  await expect(page.getByRole('combobox', { name: 'Region', exact: true })).toHaveValue('Dallas, TX')
  await expect(rows(page)).toHaveCount(1)
})

test('a bookmarked filter value absent from the page shows the empty page-filter state and Clear recovers', async ({ page }) => {
  await mock(page)
  await page.goto('/?view=workspace&projectBrowse=1&shortlist=0&region=Nowhere%2C+ZZ&priority=bogus')
  await expect(page.getByText('No projects match these page filters.')).toBeVisible()
  await expect(page.getByRole('combobox', { name: 'Region', exact: true })).toHaveValue('Nowhere, ZZ')
  await expect(page.getByRole('combobox', { name: 'Priority', exact: true })).toHaveValue('')
  await page.getByRole('button', { name: 'Clear', exact: true }).click()
  await expect(rows(page)).toHaveCount(3)
  expect(params(page).has('region')).toBe(false)
})

test('a stale Priority bookmark is ignored and removed in Shortlist view', async ({ page }) => {
  await mock(page)
  await page.goto('/?view=workspace&projectBrowse=1&shortlist=1&priority=unranked')
  await expect(rows(page)).toHaveCount(3)
  await expect(page.getByRole('combobox', { name: 'Priority', exact: true })).toHaveCount(0)
  await expect.poll(() => params(page).has('priority')).toBe(false)
  await expect(rows(page)).toHaveCount(3)
})

test('paging with a selected need clears the selection and URL consistently, and reload does not resurrect it', async ({ page }) => {
  const requests = await mock(page)
  await page.goto('/?view=workspace&projectBrowse=1')
  await expect(rows(page)).toHaveCount(3)
  await page.locator('[data-need-row="n1"]').click()
  await expect(page).toHaveURL(/need=n1/)
  await expect(page.locator('.cod-panel')).toBeVisible()
  await page.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(rows(page)).toHaveCount(1)
  await expect(rows(page).first()).toContainText('Acme 4')
  await expect(page.locator('.cod-panel h2')).toHaveCount(0)
  expect(params(page).has('need')).toBe(false)
  expect(params(page).get('offset')).toBe('3')
  expect(requests.at(-1)?.searchParams.get('offset')).toBe('3')
  await page.reload()
  await expect(rows(page)).toHaveCount(1)
  await expect(rows(page).first()).toContainText('Acme 4')
  await expect(page.locator('.cod-panel h2')).toHaveCount(0)
  expect(params(page).get('offset')).toBe('3')
})
