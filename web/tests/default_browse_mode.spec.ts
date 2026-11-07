import { expect, test, type Page } from '@playwright/test'
import { mockDemandSummary } from './mock-demand-summary'

// SYNTHETIC UI TEST FIXTURE ONLY. Owner decision 2026-11-06: flat project cards are the default
// Opportunities browse; the released operator/customer group browse stays at ?groupBrowse=1 and
// ?projectBrowse=1 remains an alias for the flat browse.

const project = {
  id: 'project-1', project_id: 'project-1', name: 'Example Energy · Example Compressor Station', company: 'Example Energy', customer_identity_id: 'company-1',
  location: 'Permian Basin, TX', sector: 'oil_gas', asset_type: 'compressor_station', priority_score: null, representative_need_id: 'need-1', need_count: 1,
  needs: [{ id: 'need-1', project_id: 'project-1', tier: 'Lead', activity: 'drilling' }],
  event: null, contact: [], contact_people: [], power_summary: null, power_summary_kind: 'unknown', next_action: 'Confirm fixture details.', updated_at: '2026-10-21T00:00:00Z',
}
const group = { id: 'group-1', name: 'Example Energy', role: 'operator', project_count: 1, need_count: 1, priority_score: null, sectors: ['oil_gas'] }
const need = {
  id: 'need-1', project_id: 'project-1', name: 'Example Compressor Station', browse_title: 'Example Compressor Station', location: 'Permian Basin, TX', tier: 'Lead', workflow_status: 'New',
  activity: 'drilling', rationale: 'Synthetic fixture.', signal_evidence_state: 'active_evidence', required_mw: null, start_window: null, duration: null, supply: 'Unknown',
  next_action: 'Confirm the fixture package.', conflict_state: 'Not assessed', title_company: 'Example Energy', commercial_organization: 'Example Energy', evidence: [], missing_facts: [],
}

async function mock(page: Page) {
  await mockDemandSummary(page)
  await page.route(url => url.pathname.startsWith('/api/') && !url.pathname.includes('demand-summary'), route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (path === '/api/opportunities/groups') return route.fulfill({ json: { items: [group], total: 1, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'g1', generation: 'g' } })
    if (path.startsWith('/api/opportunities/groups/') && path.endsWith('/projects')) return route.fulfill({ json: { items: [project], total: 1, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'p1', parent_cohort_token: 'g1', generation: 'g' } })
    if (path === '/api/opportunities/projects') return route.fulfill({ json: { items: [project], total: 1, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'p1', generation: 'g' } })
    if (path === '/api/opportunities/needs/need-1') return route.fulfill({ json: need })
    if (path === '/api/commercial-pursuits') return route.fulfill({ json: { items: [], counts: { total: 0, active: 0, needs_attention: 0 }, total_matching: 0, has_more: false, next_offset: null } })
    return route.fulfill({ json: [] })
  })
}

const params = (page: Page) => new URL(page.url()).searchParams

test('the bare default renders flat project cards, one KPI card and the restyled detail with Add to Pursuit', async ({ page }) => {
  await mock(page)
  await page.goto('/?view=workspace')
  await expect(page.locator('.cfr-table tbody tr')).toHaveCount(1)
  await expect(page.locator('.cfr-kpis article')).toHaveCount(1)
  await expect(page.locator('.customer-group')).toHaveCount(0)
  await page.locator('[data-need-row="need-1"]').click()
  await expect(page.locator('.cod-panel')).toBeVisible()
  await expect(page.locator('.wh-detail')).toHaveCount(0)
  await expect(page.locator('.cod-panel').getByRole('button', { name: 'Add to Pursuit' })).toBeVisible()
  expect(params(page).get('groupBrowse')).toBeNull()
})

test('the bare root path also opens the flat browse', async ({ page }) => {
  await mock(page)
  await page.goto('/')
  await expect(page.locator('.cfr-table tbody tr')).toHaveCount(1)
  await expect(page.locator('.customer-group')).toHaveCount(0)
})

test('?groupBrowse=1 renders the operator/customer groups, keeps its mode through filters and selection', async ({ page }) => {
  await mock(page)
  await page.goto('/?view=workspace&groupBrowse=1')
  await expect(page.locator('.customer-group')).toHaveCount(1)
  await expect(page.locator('.cfr-table')).toHaveCount(0)
  await page.getByRole('navigation', { name: 'Project type' }).getByRole('button', { name: 'Oil & Gas' }).click()
  await expect.poll(() => params(page).get('sector')).toBe('oil_gas')
  expect(params(page).get('groupBrowse')).toBe('1')
  await page.locator('.customer-group-toggle').first().click()
  await page.getByRole('button', { name: 'View project details' }).click()
  await expect(page).toHaveURL(/need=need-1/)
  expect(params(page).get('groupBrowse')).toBe('1')
  await expect(page.locator('.wh-detail')).toBeVisible()
})

test('?projectBrowse=1 remains an alias for the flat browse (old bookmarks)', async ({ page }) => {
  await mock(page)
  await page.goto('/?view=workspace&projectBrowse=1')
  await expect(page.locator('.cfr-table tbody tr')).toHaveCount(1)
  await expect(page.locator('.customer-group')).toHaveCount(0)
})

for (const [label, url, rows, groups] of [['default', '/?view=workspace', 1, 0], ['group browse', '/?view=workspace&groupBrowse=1', 0, 1]] as const) {
  test(`Back after selecting an opportunity keeps the same mode (${label})`, async ({ page }) => {
    await mock(page)
    await page.goto(url)
    if (rows) await page.locator('[data-need-row="need-1"]').click()
    else { await page.locator('.customer-group-toggle').first().click(); await page.getByRole('button', { name: 'View project details' }).click() }
    await expect(page).toHaveURL(/need=need-1/)
    await page.goBack()
    await expect(page).not.toHaveURL(/need=/)
    await expect(page.locator('.cfr-table tbody tr')).toHaveCount(rows)
    await expect(page.locator('.customer-group')).toHaveCount(groups)
    await page.goForward()
    await expect(page).toHaveURL(/need=need-1/)
    await expect(page.locator(rows ? '.cod-panel' : '.wh-detail')).toBeVisible()
  })
}

test('the Companies panel group-browse link opens the group browse', async ({ page }) => {
  await mock(page)
  await page.goto('/?view=workspace&panel=companies')
  const link = page.getByRole('link', { name: 'Browse operator and customer groups' })
  await expect(link).toHaveAttribute('href', '/?view=workspace&groupBrowse=1')
  await link.click()
  await expect(page.locator('.customer-group')).toHaveCount(1)
  await expect(page.locator('.cfr-table')).toHaveCount(0)
})
