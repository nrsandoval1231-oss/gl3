import { expect, test, type Page } from '@playwright/test'
import { mockDemandSummary } from './mock-demand-summary'

// SYNTHETIC UI FIXTURE ONLY. Bare Opportunities is the server-ranked account
// shortlist; flat project browsing remains an explicit bookmarked compatibility route.

const project = {
  id: 'project-1', project_id: 'project-1', project_ids: ['project-1'], name: 'Example Compressor Station', company: 'Example Energy', customer_identity_id: 'company-1',
  location: 'Permian Basin, TX', sector: 'oil_gas', asset_type: 'compressor_station', priority_score: null, representative_need_id: 'need-1', need_count: 1,
  eligible_need_ids: ['need-1'], needs: [{ id: 'need-1', project_id: 'project-1', tier: 'Lead', activity: 'construction' }],
  event: null, contact: [], contact_people: [], power_summary: null, power_summary_kind: 'unknown', next_action: 'Confirm fixture details.',
  shortlist_assessment: { eligible: true, reasons: [], evidence_refs: ['synthetic-source-1'], why_now: 'Synthetic source reports current electrical construction.', next_step: 'Confirm construction timing.', source_subject: 'Example Compressor Station' },
  updated_at: '2026-10-21T00:00:00Z',
}
const group = {
  id: 'group-1', name: 'Example Energy', role: 'operator', project_count: 1, total_known_project_count: 1,
  relevant_project_count: 1, eligible_need_count: 1, need_count: 1, priority_score: null, sectors: ['oil_gas'],
  group_kind: 'resolved_identity', featured_project: project,
}
const need = {
  id: 'need-1', project_id: 'project-1', name: 'Example Compressor Station', browse_title: 'Example Compressor Station', location: 'Permian Basin, TX', tier: 'Lead', workflow_status: 'New',
  activity: 'construction', rationale: 'Synthetic fixture.', signal_evidence_state: 'active_evidence', required_mw: null, start_window: null, duration: null, supply: 'Unknown',
  next_action: 'Confirm the fixture package.', conflict_state: 'Not assessed', title_company: 'Example Energy', commercial_organization: 'Example Energy', evidence: [], missing_facts: [],
  associated_account: { company_identity_id: 'group-1', name: 'Example Energy', role: 'asset_operator', basis: 'Synthetic identity-backed fixture.', support_status: 'current', evidence_refs: [{ namespace: 'retained-evidence', id: 'synthetic-source-1', retained_evidence_id: 'synthetic-source-1' }] },
}
const groupPage = { items: [group], total: 1, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'g1', generation: 'g', valid_until: '2099-01-01T00:00:00Z', facets: { regions: [], stages: [] } }
const projectPage = { items: [project], total: 1, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'p1', parent_cohort_token: 'g1', generation: 'g', valid_until: '2099-01-01T00:00:00Z' }

async function mock(page: Page) {
  await mockDemandSummary(page)
  await page.route(url => url.pathname.startsWith('/api/') && !url.pathname.includes('demand-summary'), route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (path === '/api/opportunities/groups') return route.fulfill({ json: groupPage })
    if (path === '/api/opportunities/groups/group-1/open') return route.fulfill({ json: { group, projects: projectPage, parent_cohort_token: 'g1' } })
    if (path === '/api/opportunities/groups/group-1/projects') return route.fulfill({ json: projectPage })
    if (path === '/api/opportunities/projects') return route.fulfill({ json: { ...projectPage, items: [project] } })
    if (path === '/api/opportunities/needs/need-1') return route.fulfill({ json: need })
    if (path === '/api/opportunities/workspace/changes') return route.fulfill({ json: { items: [], counts: { discovered: 0, changed: 0, promoted: 0, closed: 0, review_exception: 0 }, total_unreviewed: 0, offset: 0, limit: 50, next_offset: null, evaluated_at: '2026-11-07T12:00:00Z', baseline_identity: '00000000-0000-4000-8000-000000000001', baseline_reviewed_at: null, first_use: true, token: 'fixture', source_health_exceptions: [] } })
    if (path === '/api/commercial-pursuits') return route.fulfill({ json: { items: [], counts: { total: 0, active: 0, needs_attention: 0 }, total_matching: 0, has_more: false, next_offset: null } })
    return route.fulfill({ json: [] })
  })
}

const params = (page: Page) => new URL(page.url()).searchParams

test('the bare Opportunities view is a compact server-ranked account shortlist', async ({ page }) => {
  const groupQueries: URL[] = []
  await mock(page)
  await page.route('**/api/opportunities/groups?*', route => { groupQueries.push(new URL(route.request().url())); return route.fallback() })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Customers' })).toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Opportunity scope' }).getByRole('button', { name: 'Shortlist' })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('.customer-group')).toHaveCount(1)
  await expect(page.locator('.cfr-kpis')).toHaveCount(0)
  await expect(page.locator('.cfr-table')).toHaveCount(0)
  await expect(page.locator('.customer-group-featured')).toContainText('Synthetic source reports current electrical construction.')
  await expect.poll(() => groupQueries.some(url => url.searchParams.get('shortlist') === 'true')).toBe(true)
  expect(params(page).get('groupBrowse')).toBeNull()
})

test('the bare root path also opens the account shortlist', async ({ page }) => {
  await mock(page)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Customers' })).toBeVisible()
  await expect(page.locator('.customer-group')).toHaveCount(1)
})

test('?projectBrowse=1 remains an explicit flat project compatibility route', async ({ page }) => {
  await mock(page)
  await page.goto('/?view=workspace&projectBrowse=1')
  await expect(page.locator('.cfr-table tbody tr')).toHaveCount(1)
  await expect(page.locator('.customer-group')).toHaveCount(0)
  expect(params(page).get('projectBrowse')).toBe('1')
})

test('the default account opens shared Companies detail and retains account context on a project deep link', async ({ page }) => {
  const pursuitPosts: Array<{ need_id: string }> = []
  await mock(page)
  await page.route('**/api/commercial-pursuits', async route => {
    if (route.request().method() === 'POST') {
      const body = route.request().postDataJSON() as { need_id: string }
      pursuitPosts.push(body)
      return route.fulfill({ status: 201, json: { id: 'p-new', need_id: body.need_id, project_id: 'project-1', title: 'Example Compressor Station', stage: 'Discovered' } })
    }
    return route.fulfill({ json: { items: [], counts: { total: 0, active: 0, needs_attention: 0 }, total_matching: 0, has_more: false, next_offset: null } })
  })
  await page.goto('/')
  await page.getByRole('button', { name: /Example Energy/ }).click()
  await expect(page).toHaveURL(/account=group-1/)
  await expect(page.getByRole('heading', { name: 'Example Energy', exact: true })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Account projects' })).toBeVisible()
  await page.getByRole('button', { name: /Open project detail Example Compressor Station/ }).click()
  await expect(page).toHaveURL(/account=group-1/)
  await expect(page).toHaveURL(/need=need-1/)
  await expect(page.getByRole('complementary', { name: 'Opportunity detail' })).toBeVisible()
  await page.goBack()
  await expect(page.getByRole('heading', { name: 'Example Energy', exact: true })).toBeVisible()

  await page.getByRole('button', { name: 'Companies' }).click()
  await expect(page.getByRole('heading', { name: 'Companies', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Open Example Energy' }).click()
  await expect(page.getByRole('heading', { name: 'Example Energy', exact: true })).toBeVisible()
  const project = page.locator('.cmp-projects li').filter({ hasText: 'Example Compressor Station' })
  await project.getByRole('button', { name: /Add to Pursuit/ }).click()
  await expect(project.getByRole('link', { name: 'In Pursuits' })).toBeVisible()
  expect(pursuitPosts).toEqual([{ need_id: 'need-1' }])
})

test('Companies and Reports replace the visible Opportunities page while a delayed account refresh completes', async ({ page }) => {
  await mock(page)
  let began!: () => void
  let release!: () => void
  const requestStarted = new Promise<void>(resolve => { began = resolve })
  const allowResponse = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/opportunities/groups?*', async route => {
    began()
    await allowResponse
    await route.fallback()
  })
  await page.goto('/')
  await requestStarted
  await page.getByRole('button', { name: 'Companies' }).click()
  release()
  await expect(page).toHaveURL(/panel=companies/)
  await expect(page.getByRole('heading', { name: 'Companies', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Customers', exact: true })).toHaveCount(0)
  await expect(page.locator('.customer-group')).toHaveCount(0)

  await page.evaluate(() => {
    window.dispatchEvent(new Event('gl3-demand-refresh'))
    document.dispatchEvent(new Event('visibilitychange'))
  })
  await page.getByRole('button', { name: 'Reports' }).click()
  await expect(page).toHaveURL(/panel=reports/)
  await expect(page.getByRole('heading', { name: 'Reports', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Customers', exact: true })).toHaveCount(0)
  await page.evaluate(() => window.dispatchEvent(new Event('gl3-demand-refresh')))
  await expect(page).toHaveURL(/panel=reports/)
  await expect(page.getByRole('heading', { name: 'Reports', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Close navigation panel' }).click()
  await expect(page).not.toHaveURL(/panel=/)
  await expect(page.getByRole('heading', { name: 'Customers' })).toBeVisible()
})
