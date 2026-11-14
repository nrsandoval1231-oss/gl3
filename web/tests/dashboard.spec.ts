import { expect, test } from '@playwright/test'
import { needB } from './fixtures/dashboard'

const makeProjects = () => Array.from({ length: 26 }, (_, i) => ({
  id: `project-${i}`, project_id: `project-${i}`, name: `Site development ${i + 1}`, company: `Fixture Customer ${i + 1}`,
  location: 'Austin, TX', sector: 'data_centers', asset_type: 'data_center_campus', priority_score: null,
  representative_need_id: `need-${i}`, need_count: 1,
  needs: [{ id: `need-${i}`, project_id: `project-${i}`, activity: 'construction', browse_title: `Site development ${i + 1}`, location: 'Austin, TX' }],
  event: { kind: 'construction_notice', label: 'Construction notice', date: '2026-10-20', source: 'Synthetic fixture', evidence_refs: [] },
  contact: [], power_summary: 'Power relevance requires project-specific confirmation.', next_action: 'Review the source-backed project details.', updated_at: '2026-10-20T10:00:00Z',
}))

test('project results preserve detail history, truthful gaps, and responsive navigation', async ({ page }, testInfo) => {
  page.on('pageerror', error => { throw error })
  const requests: URL[] = []
  const projects = makeProjects()
  const groups = projects.map(project => ({ id: `cg_${project.id}`, name: project.company, role: 'customer', group_kind: 'resolved_identity' as const, operator_number: null, project_count: 1, total_known_project_count: 1, need_count: 1, priority_score: null, sectors: ['data_centers'] }))
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (/^\/api\/projects\/project-\d+\/account$/.test(url.pathname)) {
      const projectId = url.pathname.split('/')[3]
      const project = projects.find(item => item.project_id === projectId)
      return route.fulfill({ json: { id: `cg_${projectId}`, name: project?.company ?? 'Unknown account', group_kind: 'resolved_identity', project_id: projectId } })
    }
    if (url.pathname === '/api/opportunities/groups') {
      requests.push(url)
      const search = (url.searchParams.get('search') ?? '').toLowerCase()
      const matching = groups.filter(group => `${group.name} ${projects.find(project => `group-${project.id}` === group.id)?.name}`.toLowerCase().includes(search))
      const offset = Number(url.searchParams.get('offset') || 0)
      return route.fulfill({ json: { items: matching.slice(offset, offset + 25), total: matching.length, offset, limit: 25, cohort_token: 'dashboard-group-cohort', generation: 'dashboard-synthetic', count_unit: 'groups', valid_until: '2099-01-01T00:00:00Z' } })
    }
    if (/^\/api\/opportunities\/groups\/[^/]+\/open$/.test(url.pathname)) {
      const groupId = url.pathname.split('/')[4]
      const project = projects.find(item => `cg_${item.id}` === groupId)
      const item = groups.find(group => group.id === groupId)
      return route.fulfill({ json: { group: item, parent_cohort_token: 'dashboard-group-cohort', generation: 'dashboard-synthetic', valid_until: '2099-01-01T00:00:00Z', projects: { items: project ? [project] : [], total: project ? 1 : 0, offset: 0, limit: 25, cohort_token: 'dashboard-project-cohort', generation: 'dashboard-synthetic', count_unit: 'projects', valid_until: '2099-01-01T00:00:00Z' } } })
    }
    if (/^\/api\/opportunities\/groups\/[^/]+\/projects$/.test(url.pathname)) {
      const parentToken = url.searchParams.get('parent_cohort_token')
      expect(parentToken).toBe('dashboard-group-cohort')
      const groupId = url.pathname.split('/')[4]
      const project = projects.find(item => `cg_${item.id}` === groupId)
      return route.fulfill({ json: { items: project ? [project] : [], total: project ? 1 : 0, offset: 0, limit: 25, cohort_token: 'dashboard-project-cohort', parent_cohort_token: parentToken, generation: 'dashboard-synthetic', count_unit: 'projects', valid_until: '2099-01-01T00:00:00Z' } })
    }
    if (url.pathname === '/api/opportunities/projects') {
      requests.push(url)
      const offset = Number(url.searchParams.get('offset') || 0)
      const needId = url.searchParams.get('need_id')
      if (needId) {
        const project = projects.find(item => item.needs.some(need => need.id === needId))
        return route.fulfill({ json: { items: project ? [project] : [], total: project ? 1 : 0, offset: 0, limit: 1, cohort_token: 'dashboard-project-detail-fixture', generation: 'synthetic', count_unit: 'projects', results_scope: 'discovery', valid_until: '2099-01-01T00:00:00Z' } })
      }
      return route.fulfill({ json: { items: projects.slice(offset, offset + 25), total: projects.length, offset, limit: 25, cohort_token: 'dashboard-project-fixture', generation: 'dashboard-synthetic', count_unit: 'projects', valid_until: '2099-01-01T00:00:00Z' } })
    }
    if (url.pathname.startsWith('/api/opportunities/needs/')) {
      const id = url.pathname.split('/').at(-1)!
      return route.fulfill({ json: { ...needB, id, tier: 'Lead', commercial_next_action: 'Confirm the power package and expected timing.', name: projects.find(project => project.representative_need_id === id)?.name ?? 'Synthetic project', project_id: id.replace('need-', 'project-') } })
    }
    return route.fulfill({ status: 503, json: { detail: 'Not supplied by this project results fixture' } })
  })
  await page.goto('/?view=workspace&groupBrowse=1&shortlist=0')
  await expect(page.getByRole('heading', { name: 'Customers' })).toBeVisible()
  await expect(page.locator('.project-results-count')).toHaveText('26 accounts')
  await expect(page.locator('.customer-group-toggle').first()).toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Project type' }).getByRole('button')).toHaveText(['All', 'Oil & Gas', 'Data Centers'])
  await page.locator('.customer-group-toggle').first().click()
  const account = page.getByRole('region', { name: 'Company Fixture Customer 1' })
  await expect(account.getByRole('region', { name: 'Account projects' }).locator('.cmp-projects li')).toHaveCount(1)
  await expect(account.locator('.cmp-projects li')).toContainText('Construction notice')
  await expect(account.getByRole('region', { name: 'Account overview' })).toContainText('No verified business contact is currently available. Contact research is needed.')
  await expect(page.locator('.brand-kpi')).toHaveCount(0)

  await account.locator('.cmp-projects li').getByRole('button', { name: /Open project detail Site development 1/ }).click()
  await expect(page).toHaveURL(/need=need-0/)
  await expect(page).toHaveURL(/account=cg_project-0/)
  const detail = page.locator('.cod-panel')
  await expect(detail.getByRole('heading', { name: 'Site development 1' })).toBeVisible()
  await expect(detail).toContainText('Construction notice')
  await expect(detail).not.toContainText('0 MW')
  await expect(detail).toContainText('Confirm the power package and expected timing.')
  await expect(detail).not.toContainText('Canonical rank score')
  await page.goBack()
  await expect(page.getByRole('region', { name: 'Company Fixture Customer 1' })).toBeVisible()
  await page.goForward()
  await expect(detail.getByRole('heading', { name: 'Site development 1' })).toBeVisible()
  await page.reload()
  await expect(page.locator('.cod-panel h2')).toBeVisible()

  for (const [width, height] of [[1280,800],[768,1024],[390,844]]) {
    await page.setViewportSize({ width, height })
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
    await page.screenshot({ path: testInfo.outputPath(`project-results-${width}x${height}.png`) })
  }
  await page.getByRole('button', { name: /Back to account/ }).click()
  await expect(page.getByRole('region', { name: 'Company Fixture Customer 1' })).toBeVisible()
  await page.getByRole('button', { name: /Back to accounts/ }).click()
  await expect(page.locator('.customer-group')).toHaveCount(25)

  await page.setViewportSize({ width: 1280, height: 800 })
  await page.getByRole('textbox', { name: 'Search accounts and projects' }).fill('customer')
  await expect(page).not.toHaveURL(/need=/)
  await expect(page.locator('.cod-panel')).toHaveCount(0)

  await page.getByRole('textbox', { name: 'Search accounts and projects' }).fill('customer')
  await expect.poll(() => requests.at(-1)?.searchParams.get('search')).toBe('customer')
  await page.getByRole('button', { name: 'Data Centers', exact: true }).click()
  await expect.poll(() => requests.at(-1)?.searchParams.get('sector')).toBe('data_centers')
  await page.getByRole('button', { name: 'Next' }).click()
  await expect.poll(() => requests.at(-1)?.searchParams.get('cohort_token')).toBe('dashboard-group-cohort')
  await expect(page.locator('.customer-group')).toHaveCount(1)
  await page.getByRole('button', { name: 'Previous' }).click()
  await expect(page.locator('.customer-group')).toHaveCount(25)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/?view=workspace&need=need-1&groupBrowse=1&shortlist=0')
  await expect(page.locator('.cod-panel h2')).toContainText('Site development 2')
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
})
