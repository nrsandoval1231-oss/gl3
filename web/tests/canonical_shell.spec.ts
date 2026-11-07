import { mockDemandSummary } from './mock-demand-summary'
import { expect, test } from '@playwright/test'

const need = {
  id: 'need-shell', project_id: 'project-shell', name: 'Mesa compressor project', browse_title: 'Mesa compressor project',
  location: 'Midland, TX', tier: 'Signal', workflow_status: 'New', activity: 'compressor station construction',
  rationale: 'Synthetic browser fixture.', signal_evidence_state: 'active', conflict_state: 'Not assessed',
  required_mw: null, supply: 'Unknown', start_window: null, duration: null,
  evidence: [], missing_facts: [], commercial_organization: 'Northstar Energy',
}
const projectResults = {
  items: [{ id: 'project-shell', project_id: 'project-shell', name: 'Northstar Energy · Mesa compressor project', company: 'Northstar Energy', location: 'Midland, TX', sector: 'oil_gas', asset_type: 'Compressor station', priority_score: null, representative_need_id: 'need-shell', need_count: 1, needs: [{ id: 'need-shell', project_id: 'project-shell', name: 'Mesa compressor project', browse_title: 'Mesa compressor project', activity: 'compressor station construction', tier: 'Signal' }], event: null, contact: [], power_summary: null, power_summary_kind: 'unknown', next_action: null, updated_at: null }],
  total: 1, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'shell-cohort', generation: 'shell', results_scope: 'discovery',
}

test('canonical shell searches opportunities, navigates, and remains usable at narrow widths', async ({ page }) => {
  const searchQueries: string[] = []
  const projectQueries: URL[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/search?**', route => {
    const url = new URL(route.request().url())
    searchQueries.push(url.searchParams.get('q') ?? '')
    return route.fulfill({ json: { query: url.searchParams.get('q'), companies: [], projects: [], contacts: [], opportunities: [{ id: 'need-shell', name: 'Mesa compressor project', organization: 'Northstar Energy', location: 'Midland, TX', tier: 'Signal', confidence: 'High' }] } })
  })
  await page.route('**/api/opportunities/projects?**', route => {
    projectQueries.push(new URL(route.request().url()))
    return route.fulfill({ json: projectResults })
  })
  await page.route('**/api/opportunities/needs/need-shell?**', route => route.fulfill({ json: need }))
  // Panel endpoints; an unmocked call would surface as a genuine session-ended event.
  await page.route('**/api/opportunities/groups?**', route => route.fulfill({ json: { items: [], total: 0, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'g', generation: 'g' } }))
  await page.route(url => url.pathname === '/api/opportunities', route => route.fulfill({ json: [], headers: { 'X-Total-Count': '0', 'X-Group-Total-Count': '0', 'X-Cohort-Token': 't', 'X-Limit': '1', 'X-Offset': '0' } }))
  await page.route('**/api/commercial-pursuits**', route => route.fulfill({ json: { items: [], counts: { total: 0, active: 0, needs_attention: 0 } } }))
  await page.route('**/api/opportunities/workspace/changes**', route => route.fulfill({ json: { items: [], counts: { discovered: 0, changed: 0, promoted: 0, closed: 0, review_exception: 0 }, total_unreviewed: 0, offset: 0, limit: 50, next_offset: null, baseline_identity: 't', token: 't', source_health_exceptions: [] } }))

  await page.goto('/?view=workspace&projectBrowse=1')
  const search = page.getByRole('searchbox', { name: 'Search companies, projects, contacts and opportunities' })
  await search.fill('Mesa')
  await expect.poll(() => searchQueries).toContain('Mesa')
  await expect(page.getByRole('region', { name: 'Search results' }).getByRole('button', { name: /Mesa compressor project/ })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Search results' })).not.toContainText(/confidence/i)
  await page.getByRole('region', { name: 'Search results' }).getByRole('button', { name: /Mesa compressor project/ }).click()
  await expect(page).toHaveURL(/need=need-shell/)
  await expect(page.getByRole('heading', { name: /Mesa compressor project/ })).toBeVisible()
  expect(searchQueries).toContain('Mesa')

  await page.getByRole('button', { name: 'Companies' }).click()
  await expect(page.getByRole('region', { name: 'Companies' })).toBeVisible()
  await expect(page).toHaveURL(/panel=companies/)
  await expect(page.getByRole('link', { name: 'Browse customer accounts' })).toBeVisible()
  await page.getByRole('button', { name: 'Reports' }).click()
  await expect(page.getByRole('region', { name: 'Reports' })).toBeVisible()
  await page.goBack()
  await expect(page.getByRole('region', { name: 'Companies' })).toBeVisible()
  await page.goBack()
  await expect(page.getByRole('region', { name: 'Companies' })).toHaveCount(0)

  await page.setViewportSize({ width: 390, height: 844 })
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  await expect(page.getByRole('navigation', { name: 'Primary navigation' })).toBeVisible()
  await expect(page.getByRole('searchbox', { name: 'Search companies, projects, contacts and opportunities' })).toBeVisible()
  expect(projectQueries.length).toBeGreaterThan(0)
})

test('companies and reports open as their own page and closing restores the exact Opportunities state', async ({ page }) => {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/search?**', route => route.fulfill({ json: { query: '', companies: [], projects: [], contacts: [], opportunities: [] } }))
  await page.route('**/api/opportunities/projects?**', route => route.fulfill({ json: projectResults }))
  await page.route('**/api/opportunities/needs/need-shell?**', route => route.fulfill({ json: need }))
  await page.route('**/api/opportunities/groups?**', route => route.fulfill({ json: { items: [], total: 0, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'g', generation: 'g' } }))
  // Reports panel endpoints; an unmocked call would surface as a genuine session-ended event.
  await page.route(url => url.pathname === '/api/opportunities', route => route.fulfill({ json: [], headers: { 'X-Total-Count': '0', 'X-Group-Total-Count': '0', 'X-Cohort-Token': 't', 'X-Limit': '1', 'X-Offset': '0' } }))
  await page.route('**/api/commercial-pursuits**', route => route.fulfill({ json: { items: [], counts: { total: 0, active: 0, needs_attention: 0 } } }))
  await page.route('**/api/opportunities/workspace/changes**', route => route.fulfill({ json: { items: [], counts: { discovered: 0, changed: 0, promoted: 0, closed: 0, review_exception: 0 }, total_unreviewed: 0, offset: 0, limit: 50, next_offset: null, baseline_identity: 't', token: 't', source_health_exceptions: [] } }))
  let projectRequests = 0
  page.on('request', request => { const url = new URL(request.url()); if (url.pathname === '/api/opportunities/projects' && url.searchParams.get('limit') !== '1') projectRequests++ }) // limit=1 is the Companies panel's own count probe

  await page.goto('/?view=workspace&projectBrowse=1')
  const search = page.getByRole('textbox', { name: 'Search opportunities' })
  await search.fill('Mesa')
  await page.getByRole('button', { name: /Mesa compressor project/ }).first().click()
  await expect(page).toHaveURL(/need=need-shell/)
  const seen = projectRequests
  await page.evaluate(() => { (window as unknown as { __kept: boolean }).__kept = true })

  await page.getByRole('button', { name: 'Companies' }).click()
  const panel = page.getByRole('region', { name: 'Companies' })
  await expect(panel).toBeVisible()
  await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Companies')
  await expect(search).toBeHidden()
  await expect(page.getByRole('textbox', { name: 'Search opportunities' })).toHaveCount(0)

  await page.getByRole('button', { name: 'Close navigation panel' }).click()
  await expect(panel).toHaveCount(0)
  await expect(search).toBeVisible()
  await expect(search).toHaveValue('Mesa')
  await expect(page).toHaveURL(/need=need-shell/)
  await expect(page.getByRole('heading', { name: /Mesa compressor project/ }).first()).toBeVisible()
  expect(await page.evaluate(() => (window as unknown as { __kept?: boolean }).__kept)).toBe(true)
  expect(projectRequests).toBe(seen)

  // Browser back reopens the panel, forward returns to Opportunities with state intact.
  await page.goBack()
  await expect(panel).toBeVisible()
  await expect(search).toBeHidden()
  await page.goForward()
  await expect(panel).toHaveCount(0)
  await expect(search).toHaveValue('Mesa')

  await page.getByRole('button', { name: 'Reports' }).click()
  await expect(page.getByRole('region', { name: 'Reports' })).toBeVisible()
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Reports')
  await page.setViewportSize({ width: 390, height: 844 })
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
})

test('panel navigation: no duplicate history, one-press Back, and focus lands on the new page', async ({ page }) => {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/search?**', route => route.fulfill({ json: { query: '', companies: [], projects: [], contacts: [], opportunities: [] } }))
  await page.route('**/api/opportunities/projects?**', route => route.fulfill({ json: projectResults }))
  await page.route('**/api/opportunities/groups?**', route => route.fulfill({ json: { items: [], total: 0, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'g', generation: 'g' } }))
  await page.route(url => url.pathname === '/api/opportunities', route => route.fulfill({ json: [], headers: { 'X-Total-Count': '0', 'X-Group-Total-Count': '0', 'X-Cohort-Token': 't', 'X-Limit': '1', 'X-Offset': '0' } }))
  await page.route('**/api/commercial-pursuits**', route => route.fulfill({ json: { items: [], counts: { total: 0, active: 0, needs_attention: 0 } } }))
  await page.route('**/api/opportunities/workspace/changes**', route => route.fulfill({ json: { items: [], counts: { discovered: 0, changed: 0, promoted: 0, closed: 0, review_exception: 0 }, total_unreviewed: 0, offset: 0, limit: 50, next_offset: null, baseline_identity: 't', token: 't', source_health_exceptions: [] } }))

  await page.goto('/?view=workspace&projectBrowse=1')
  await expect(page.getByRole('textbox', { name: 'Search opportunities' })).toBeVisible()
  const base = await page.evaluate(() => history.length)

  await page.getByRole('button', { name: 'Companies' }).click()
  await expect(page.getByRole('region', { name: 'Companies' })).toBeVisible()
  await expect(page.getByRole('heading', { level: 1, name: 'Companies' })).toBeFocused()
  // Clicking the already-open panel adds nothing to history.
  await page.getByRole('button', { name: 'Companies' }).click()
  await page.getByRole('button', { name: 'Companies' }).click()
  expect(await page.evaluate(() => history.length)).toBe(base + 1)

  // The in-page Back control keeps the existing push semantics (browser Back reopens the panel); focus does not fall to <body>.
  await page.getByRole('button', { name: 'Close navigation panel' }).click()
  await expect(page.getByRole('region', { name: 'Companies' })).toHaveCount(0)
  await expect(page).not.toHaveURL(/panel=/)
  expect(await page.evaluate(() => history.length)).toBe(base + 2)
  await expect(page.locator('main.wh-main h1')).toBeFocused()

  await page.getByRole('button', { name: 'Reports' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Reports' })).toBeFocused()
  await page.goBack()
  await expect(page.getByRole('region', { name: 'Reports' })).toHaveCount(0)
  await expect(page).not.toHaveURL(/panel=/)
})
