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
    return route.fulfill({ json: { query: url.searchParams.get('q'), companies: [], projects: [], contacts: [], opportunities: [{ id: 'need-shell', name: 'Mesa compressor project', organization: 'Northstar Energy', location: 'Midland, TX', tier: 'Signal' }] } })
  })
  await page.route('**/api/opportunities/projects?**', route => {
    projectQueries.push(new URL(route.request().url()))
    return route.fulfill({ json: projectResults })
  })
  await page.route('**/api/opportunities/needs/need-shell?**', route => route.fulfill({ json: need }))

  await page.goto('/?view=workspace&projectBrowse=1')
  const search = page.getByRole('searchbox', { name: 'Search companies, projects, contacts and opportunities' })
  await search.fill('Mesa')
  await expect.poll(() => searchQueries).toContain('Mesa')
  await expect(page.getByRole('region', { name: 'Search results' }).getByRole('button', { name: /Mesa compressor project/ })).toBeVisible()
  await page.getByRole('region', { name: 'Search results' }).getByRole('button', { name: /Mesa compressor project/ }).click()
  await expect(page).toHaveURL(/need=need-shell/)
  await expect(page.getByRole('heading', { name: /Mesa compressor project/ })).toBeVisible()
  expect(searchQueries).toContain('Mesa')

  await page.getByRole('button', { name: 'Developers' }).click()
  await expect(page.getByRole('region', { name: 'Developers' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Browse customer accounts' })).toBeVisible()
  await page.getByRole('button', { name: 'Power Supply' }).click()
  await expect(page.getByRole('region', { name: 'Power Supply' })).toBeVisible()

  await page.setViewportSize({ width: 390, height: 844 })
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  await expect(page.getByRole('navigation', { name: 'Primary navigation' })).toBeVisible()
  await expect(page.getByRole('searchbox', { name: 'Search companies, projects, contacts and opportunities' })).toBeVisible()
  expect(projectQueries.length).toBeGreaterThan(0)
})
