import { expect, test } from '@playwright/test'
import { mockDemandSummary } from './mock-demand-summary'

test('far-future legacy browse leases do not expire early when the timer reaches its browser limit', async ({ page }) => {
  const requests: URL[] = []
  await page.clock.install({ time: new Date('2026-11-13T12:00:00Z') })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => {
    requests.push(new URL(route.request().url()))
    return route.fulfill({ json: {
      items: [], total: 0, count_unit: 'projects', limit: 25, offset: 0,
      cohort_token: 'far-future-lease', generation: 'fixture', results_scope: 'discovery',
      valid_until: '2099-01-01T00:00:00Z',
    } })
  })

  await page.goto('/?view=workspace&projectBrowse=1&shortlist=0')
  await expect(page.getByRole('heading', { name: 'Opportunities' })).toBeVisible()
  await expect(page.locator('.canonical-flat-results')).toHaveAttribute('aria-busy', 'false')
  const settledRequestCount = requests.length
  expect(settledRequestCount).toBeGreaterThan(0)

  await page.clock.fastForward(2_147_483_647)
  await expect(page.locator('.canonical-flat-results')).toHaveAttribute('aria-busy', 'false')
  expect(requests).toHaveLength(settledRequestCount)
})
