import { mockDemandSummary } from './mock-demand-summary'
import { expect, test, type Page } from '@playwright/test'

const groups = [
  { id: 'g-north', name: 'Northstar Energy', role: 'operator', group_kind: 'resolved_identity', project_count: 2, need_count: 3, priority_score: 71, sectors: ['oil_gas'] },
  { id: 'g-cedar', name: 'Cedar Compute', role: 'customer', group_kind: 'resolved_identity', project_count: 1, need_count: 1, priority_score: null, sectors: ['data_centers'] },
]
const project = (id: string, name: string, extra: Record<string, unknown> = {}) => ({ id, project_id: id, name, company: 'Northstar Energy', customer_identity_id: 'company-north', location: 'Midland, TX', sector: 'oil_gas', asset_type: 'Compressor station', priority_score: 71, representative_need_id: `need-${id}`, need_count: 1, needs: [{ id: `need-${id}`, project_id: id, tier: 'Prospect' }], event: null, contact: [], power_summary: null, power_summary_kind: 'unknown', next_action: null, updated_at: null, ...extra })
const pursuit = { id: 'pursuit-1', need_id: 'need-p1', project_id: 'p1', stage: 'Engaged', title: 'Mesa pursuit', location: null, tier: 'Prospect', required_mw: null, start_window: null, contact: null, contact_status: 'unknown', attention: [], attention_labels: [], next_task: null, created_at: '2026-10-01T00:00:00Z', stage_changed_at: '2026-10-01T00:00:00Z' }

async function mock(page: Page, opts: { groupsStatus?: number; pursuits?: unknown[] } = {}) {
  const groupQueries: URL[] = []
  await mockDemandSummary(page)
  await page.route(url => url.pathname.startsWith('/api/') && !url.pathname.includes('demand-summary'), route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (url.pathname === '/api/opportunities/groups') {
      groupQueries.push(url)
      if (opts.groupsStatus) return route.fulfill({ status: opts.groupsStatus, json: {} })
      const q = (url.searchParams.get('search') ?? '').toLowerCase(), sector = url.searchParams.get('sector')
      const items = groups.filter(g => (!q || g.name.toLowerCase().includes(q)) && (!sector || sector === 'all' || g.sectors.includes(sector)))
      return route.fulfill({ json: { items, total: items.length, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'c1', generation: 'g' } })
    }
    if (url.pathname === '/api/opportunities/projects') return route.fulfill({ json: { items: [], total: 7, count_unit: 'projects', limit: 1, offset: 0, cohort_token: 'p', generation: 'g' } })
    if (url.pathname === '/api/opportunities/groups/g-north/open') return route.fulfill({ json: { group: groups[0], parent_cohort_token: 'c1', generation: 'g', projects: { items: [project('p1', 'Mesa compressor', { power_summary: '12 MW reported' }), project('p2', 'Basin plant')], total: 2, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'cp', generation: 'g' } } })
    if (url.pathname === '/api/opportunities/groups/g-gone/open') return route.fulfill({ status: 404, json: {} })
    if (url.pathname === '/api/commercial-pursuits') return route.fulfill({ json: { items: opts.pursuits ?? [], counts: { total: (opts.pursuits ?? []).length, active: (opts.pursuits ?? []).length, needs_attention: 0 } } })
    if (url.pathname === '/api/customer-accounts/company-north/contacts') return route.fulfill({ json: { company_id: 'company-north', research_required: true, contacts: [], imported_unverified: [] } })
    if (url.pathname.startsWith('/api/opportunities/needs/')) return route.fulfill({ json: { id: url.pathname.split('/').pop(), project_id: 'p1', name: 'Mesa compressor', browse_title: 'Mesa compressor', location: 'Midland, TX', tier: 'Prospect', workflow_status: 'New', activity: 'construction', rationale: 'Fixture', signal_evidence_state: 'active', conflict_state: 'Not assessed', required_mw: null, supply: 'Unknown', start_window: null, duration: null, evidence: [], missing_facts: [] } })
    if (url.pathname === '/api/opportunities/workspace/changes') return route.fulfill({ json: { items: [], counts: { discovered: 0, changed: 0, promoted: 0, closed: 0, review_exception: 0 }, total_unreviewed: 0, offset: 0, limit: 50, next_offset: null, baseline_identity: 't', token: 't', source_health_exceptions: [] } })
    return route.fulfill({ json: [] })
  })
  return groupQueries
}

test('directory shows only supplied fields, searches, and omits unsupported columns', async ({ page }) => {
  const queries = await mock(page)
  await page.goto('/?view=workspace&panel=companies')
  const panel = page.getByRole('region', { name: 'Companies' })
  await expect(panel.getByRole('status')).toContainText('2 companies · 7 projects')
  const table = panel.getByRole('table', { name: 'Companies' })
  await expect(table.getByRole('columnheader')).toHaveText(['Company', 'Projects', 'Priority score', 'Open'])
  await expect(table.getByRole('row').nth(1)).toContainText('Northstar Energy')
  await expect(table.getByRole('row').nth(1)).toContainText('71')
  await expect(table.getByRole('row').nth(2)).toContainText('Unranked')
  await expect(table).not.toContainText('Total MW')
  await expect(table).not.toContainText(/\b0 MW\b/)
  await expect(panel).toContainText('Total MW and linked pursuits are not part of the company list')
  await expect(page.getByRole('link', { name: 'Browse customer accounts' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Browse operator and customer groups' })).toBeVisible()
  await panel.getByRole('searchbox', { name: 'Search companies', exact: true }).fill('cedar')
  await expect(table.getByRole('row')).toHaveCount(2)
  await expect(panel.getByRole('status')).toContainText('1 company matching search')
  expect(queries.some(url => url.searchParams.get('search') === 'cedar')).toBeTruthy()
  await panel.getByRole('searchbox', { name: 'Search companies', exact: true }).fill('')
  await panel.getByRole('button', { name: 'Data Centers' }).click()
  await expect(table.getByRole('row')).toHaveCount(2)
  await expect(page).toHaveURL(/cs=data_centers/)
})

test('opening a company uses panel/company params, keeps context on back/forward, links pursuits and opportunities', async ({ page }) => {
  await mock(page, { pursuits: [pursuit] })
  await page.goto('/?view=workspace&panel=companies')
  const panel = page.getByRole('region', { name: 'Companies' })
  await panel.getByRole('searchbox', { name: 'Search companies', exact: true }).fill('north')
  await expect(panel.getByRole('table', { name: 'Companies' }).getByRole('row')).toHaveCount(2)
  await panel.getByRole('button', { name: 'Open Northstar Energy' }).click()
  await expect(page).toHaveURL(/panel=companies/)
  await expect(page).toHaveURL(/company=g-north/)
  const company = page.getByRole('region', { name: 'Company Northstar Energy' })
  await expect(company.getByRole('heading', { name: 'Northstar Energy', exact: true })).toBeVisible()
  await expect(company).toContainText('Power: 12 MW reported')
  await expect(company).toContainText('Power: Unknown')
  await expect(company.getByRole('region', { name: 'Linked pursuits' })).toContainText('1 pursuit')
  await expect(company.getByRole('region', { name: 'Linked pursuits' })).toContainText('Mesa pursuit · Engaged')
  await expect(company.getByRole('region', { name: 'Key contacts' })).toContainText('Research Required')
  await expect(company.getByRole('link', { name: /Open opportunity Mesa compressor/ })).toHaveAttribute('href', /need=need-p1/)
  await expect(page.getByRole('searchbox', { name: 'Search companies', exact: true })).toBeHidden()
  await page.goBack()
  await expect(page).not.toHaveURL(/company=/)
  await expect(page.getByRole('searchbox', { name: 'Search companies', exact: true })).toHaveValue('north')
  await page.goForward()
  await expect(page.getByRole('heading', { name: 'Northstar Energy', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '← Back to companies' }).click()
  await expect(page).not.toHaveURL(/company=/)
  await expect(page).toHaveURL(/panel=companies/)
  await page.getByRole('button', { name: 'Open Northstar Energy' }).click()
  await page.getByRole('link', { name: /Open opportunity Mesa compressor/ }).click()
  await expect(page).toHaveURL(/need=need-p1/)
  await expect(page.getByRole('region', { name: 'Companies' })).toHaveCount(0)
  await page.goBack()
  await expect(page.getByRole('region', { name: 'Company Northstar Energy' })).toBeVisible()
})

test('company deep link reloads, unavailable company and list errors are honest', async ({ page }) => {
  await mock(page, { pursuits: [] })
  await page.goto('/?view=workspace&panel=companies&company=g-north')
  await expect(page.getByRole('region', { name: 'Linked pursuits' })).toContainText('0 pursuits')
  await page.goto('/?view=workspace&panel=companies&company=g-gone')
  await expect(page.getByRole('alert')).toContainText('no longer available')
})

test('directory error offers retry and never shows counts', async ({ page }) => {
  await mock(page, { groupsStatus: 500 })
  await page.goto('/?view=workspace&panel=companies')
  const panel = page.getByRole('region', { name: 'Companies' })
  await expect(panel.getByRole('alert')).toContainText('Could not load operator/customer groups (500)')
  await expect(panel.getByRole('button', { name: 'Retry' })).toBeVisible()
  await expect(panel.getByRole('status')).toContainText('Company count unavailable')
})

test('directory and company view fit 390px without horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mock(page, { pursuits: [pursuit] })
  await page.goto('/?view=workspace&panel=companies')
  await expect(page.getByRole('button', { name: 'Open Northstar Energy' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  await page.getByRole('button', { name: 'Open Northstar Energy' }).click()
  await expect(page.getByRole('heading', { name: 'Northstar Energy', exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
})
