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
  const groups = projects.map(project => ({ id: `group-${project.id}`, name: project.company, role: 'customer', operator_number: null, project_count: 1, need_count: 1, priority_score: null, sectors: ['data_centers'] }))
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (url.pathname === '/api/opportunities/groups') {
      requests.push(url)
      const search = (url.searchParams.get('search') ?? '').toLowerCase()
      const matching = groups.filter(group => `${group.name} ${projects.find(project => `group-${project.id}` === group.id)?.name}`.toLowerCase().includes(search))
      const offset = Number(url.searchParams.get('offset') || 0)
      return route.fulfill({ json: { items: matching.slice(offset, offset + 25), total: matching.length, offset, limit: 25, cohort_token: 'dashboard-group-cohort', generation: 1, count_unit: 'operators and customers' } })
    }
    if (url.pathname.startsWith('/api/opportunities/groups/')) {
      const groupId = url.pathname.split('/')[4]
      const project = projects.find(item => `group-${item.id}` === groupId)
      const parentToken = url.searchParams.get('parent_cohort_token')
      expect(parentToken).toBe('dashboard-group-cohort')
      return route.fulfill({ json: { items: project ? [project] : [], total: project ? 1 : 0, offset: 0, limit: 25, cohort_token: 'dashboard-project-cohort', generation: 1, count_unit: 'projects' } })
    }
    if (url.pathname === '/api/opportunities/projects') {
      requests.push(url)
      const offset = Number(url.searchParams.get('offset') || 0)
      const needId = url.searchParams.get('need_id')
      if (needId) {
        const project = projects.find(item => item.needs.some(need => need.id === needId))
        return route.fulfill({ json: { items: project ? [project] : [], total: project ? 1 : 0, offset: 0, limit: 1, cohort_token: 'dashboard-project-detail-fixture', generation: 'synthetic', count_unit: 'projects', results_scope: 'discovery' } })
      }
      return route.fulfill({ json: { items: projects.slice(offset, offset + 25), total: projects.length, offset, limit: 25, cohort_token: 'dashboard-project-fixture', generation: 1, count_unit: 'projects' } })
    }
    if (url.pathname.startsWith('/api/opportunities/needs/')) {
      const id = url.pathname.split('/').at(-1)!
      return route.fulfill({ json: { ...needB, id, tier: 'Lead', commercial_next_action: 'Confirm the power package and expected timing.', name: projects.find(project => project.representative_need_id === id)?.name ?? 'Synthetic project', project_id: id.replace('need-', 'project-') } })
    }
    return route.fulfill({ status: 503, json: { detail: 'Not supplied by this project results fixture' } })
  })
  await page.goto('/?view=workspace')
  await expect(page.getByRole('heading', { name: 'Search opportunities' })).toBeVisible()
  await expect(page.locator('.project-results-count')).toHaveText('26 operator/customer groups')
  await expect(page.locator('.customer-group-toggle').first()).toBeVisible()
  await page.locator('.customer-group-toggle').first().click()
  await expect(page.locator('.project-card')).toHaveCount(1)
  await expect(page.locator('.project-card').first()).toContainText('Construction notice')
  await expect(page.locator('.project-card').first()).toContainText('Contact not yet verified')
  await expect(page.locator('.brand-kpi')).toHaveCount(0)
  await expect(page.getByRole('navigation', { name: 'Project type' }).getByRole('button')).toHaveText(['All', 'Oil & Gas', 'Data Centers'])

  await page.locator('.project-card').first().getByRole('button', { name: 'View project details' }).click()
  await expect(page).toHaveURL(/need=need-0/)
  await expect(page.locator('.wh-detail h2')).toBeVisible()
  await expect(page.locator('.wh-detail h2')).toHaveText('Site development 1')
  await expect(page.locator('.wh-detail')).toContainText('Fixture Customer 1')
  await expect(page.locator('.wh-detail')).toContainText('Construction notice · 2026-10-20')
  await expect(page.locator('.wh-detail')).not.toContainText('Not yet verified')
  await expect(page.locator('.wh-customer-metrics')).toHaveCount(0)
  await expect(page.locator('.wh-detail')).toContainText('Review the source-backed project details.')
  await expect(page.locator('.wh-detail')).not.toContainText('Canonical rank score')
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  await page.locator('.wh-tabs .wh-more-tabs summary').click()
  await page.locator('.wh-tabs').getByRole('button', { name: 'Research', exact: true }).click()
  await page.goBack()
  await expect(page.getByRole('button', { name: 'Evidence', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await page.goForward()
  await expect(page.locator('.wh-tabs .wh-more-tabs button[aria-pressed="true"]')).toHaveText('Research')
  await page.reload()
  await expect(page.locator('.wh-detail h2')).toBeVisible()
  await expect(page.locator('.wh-customer-metrics')).toHaveCount(0)
  await page.getByRole('button', { name: 'Overview', exact: true }).click()

  for (const [width, height] of [[1280,800],[768,1024],[390,844]]) {
    await page.setViewportSize({ width, height })
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
    await page.screenshot({ path: testInfo.outputPath(`project-results-${width}x${height}.png`) })
  }
  await page.getByRole('button', { name: /Back to power needs/ }).click()
  await expect(page.locator('.customer-group')).toHaveCount(25)

  await page.setViewportSize({ width: 1280, height: 800 })
  await page.locator('.customer-group-toggle').first().click()
  await page.locator('.project-card').first().getByRole('button', { name: 'View project details' }).click()
  await expect(page).toHaveURL(/need=need-0/)
  await page.getByRole('textbox', { name: 'Search opportunities' }).fill('customer')
  await expect(page).not.toHaveURL(/need=/)
  await expect(page.locator('.wh-detail')).toHaveCount(0)

  await page.getByRole('textbox', { name: 'Search opportunities' }).fill('customer')
  await expect.poll(() => requests.at(-1)?.searchParams.get('search')).toBe('customer')
  await page.getByRole('button', { name: 'Oil & Gas', exact: true }).click()
  await expect.poll(() => requests.at(-1)?.searchParams.get('sector')).toBe('oil_gas')
  await page.getByRole('button', { name: 'Next' }).click()
  await expect.poll(() => requests.at(-1)?.searchParams.get('cohort_token')).toBe('dashboard-group-cohort')
  await expect(page.locator('.customer-group')).toHaveCount(1)
  await page.getByRole('button', { name: 'Previous' }).click()
  await expect(page.locator('.customer-group')).toHaveCount(25)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/?view=workspace&need=need-1')
  await expect(page.locator('.wh-detail h2')).toHaveText('Site development 2')
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
})
