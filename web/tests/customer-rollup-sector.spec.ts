import { mockDemandSummary } from './mock-demand-summary'
import { expect, test } from '@playwright/test'

const group = { id: 'sector-group', name: 'Sector Customer', role: 'customer', project_count: 1, need_count: 1, sectors: ['oil_gas', 'data_centers'] }

test('changing sector clears region and stage filters and their URL state', async ({ page }) => {
  const requests: URL[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => {
    const url = new URL(route.request().url())
    requests.push(url)
    const dataCenters = url.searchParams.get('sector') === 'data_centers'
    return route.fulfill({ json: { items: [group], total: 1, count_unit: 'groups', limit: 25, offset: 0, cohort_token: `sector-${dataCenters ? 'dc' : 'oil'}`, facets: dataCenters ? { regions: ['Austin, TX'], stages: ['Construction notice'] } : { regions: ['Permian Basin, TX'], stages: ['Permit issued'] } } })
  })

  await page.goto('/?view=workspace&region=Permian+Basin%2C+TX&stage=Permit+issued&priority=ranked')
  await expect(page.locator('.customer-group')).toHaveCount(1)
  await expect(page.getByRole('combobox', { name: 'Region' })).toHaveValue('Permian Basin, TX')
  await expect(page.getByRole('combobox', { name: 'Stage' })).toHaveValue('Permit issued')

  await page.getByRole('button', { name: 'Data Centers', exact: true }).click()
  await expect.poll(() => requests.at(-1)?.searchParams.get('sector')).toBe('data_centers')
  await expect.poll(() => requests.at(-1)?.searchParams.has('region')).toBe(false)
  await expect.poll(() => requests.at(-1)?.searchParams.has('stage')).toBe(false)
  await expect(page.getByRole('combobox', { name: 'Region' })).toHaveValue('')
  await expect(page.getByRole('combobox', { name: 'Stage' })).toHaveValue('')
  const params = new URL(page.url()).searchParams
  expect(params.get('sector')).toBe('data_centers')
  expect(params.has('region')).toBe(false)
  expect(params.has('stage')).toBe(false)
  expect(params.get('priority')).toBe('ranked')
})

test('URL region and stage stay visibly selected when omitted from returned facets', async ({ page }) => {
  const requests: URL[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => {
    requests.push(new URL(route.request().url()))
    return route.fulfill({ json: { items: [group], total: 1, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'arbitrary-filter-cohort', facets: { regions: ['Austin, TX'], stages: ['Construction notice'] } } })
  })

  await page.goto('/?view=workspace&region=Nonfacet+Region&stage=Nonfacet+Stage')
  await expect(page.locator('.customer-group')).toHaveCount(1)
  await expect(page.getByRole('combobox', { name: 'Region' })).toHaveValue('Nonfacet Region')
  await expect(page.getByRole('combobox', { name: 'Region' }).locator('option', { hasText: 'Nonfacet Region' })).toHaveCount(1)
  await expect(page.getByRole('combobox', { name: 'Stage' })).toHaveValue('Nonfacet Stage')
  await expect(page.getByRole('combobox', { name: 'Stage' }).locator('option', { hasText: 'Nonfacet Stage' })).toHaveCount(1)
  expect(requests.at(-1)?.searchParams.get('region')).toBe('Nonfacet Region')
  expect(requests.at(-1)?.searchParams.get('stage')).toBe('Nonfacet Stage')
})
