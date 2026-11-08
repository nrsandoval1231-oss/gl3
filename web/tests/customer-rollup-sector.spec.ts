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

  await page.goto('/?view=workspace&region=Permian+Basin%2C+TX&stage=Permit+issued&priority=ranked&groupBrowse=1&shortlist=0')
  await expect(page.locator('.customer-group')).toHaveCount(1)
  await page.getByText('More filters and sorting', { exact: true }).click()
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

  await page.goto('/?view=workspace&region=Nonfacet+Region&stage=Nonfacet+Stage&groupBrowse=1&shortlist=0')
  await expect(page.locator('.customer-group')).toHaveCount(1)
  await page.getByText('More filters and sorting', { exact: true }).click()
  await expect(page.getByRole('combobox', { name: 'Region' })).toHaveValue('Nonfacet Region')
  await expect(page.getByRole('combobox', { name: 'Region' }).locator('option', { hasText: 'Nonfacet Region' })).toHaveCount(1)
  await expect(page.getByRole('combobox', { name: 'Stage' })).toHaveValue('Nonfacet Stage')
  await expect(page.getByRole('combobox', { name: 'Stage' }).locator('option', { hasText: 'Nonfacet Stage' })).toHaveCount(1)
  expect(requests.at(-1)?.searchParams.get('region')).toBe('Nonfacet Region')
  expect(requests.at(-1)?.searchParams.get('stage')).toBe('Nonfacet Stage')
})
test('sector switch immediately announces loading and hides the previous cohort until the requested groups arrive', async ({ page }) => {
  let releaseDataCenters!: () => void
  const dataCentersPending = new Promise<void>(resolve => { releaseDataCenters = resolve })
  const requests: string[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', async route => {
    const url = new URL(route.request().url())
    const sector = url.searchParams.get('sector') ?? 'all'
    requests.push(sector)
    if (sector === 'data_centers') await dataCentersPending
    const result = sector === 'data_centers'
      ? { id: 'dc-group', name: 'Data Center Group', role: 'customer', project_count: 1, need_count: 1, sectors: ['data_centers'] }
      : sector === 'oil_gas'
        ? { id: 'oil-group', name: 'Oil and Gas Group', role: 'operator', project_count: 1, need_count: 1, sectors: ['oil_gas'] }
        : { id: 'all-group', name: 'All Sector Group', role: 'customer', project_count: 2, need_count: 2, sectors: ['oil_gas', 'data_centers'] }
    await route.fulfill({ json: { items: [result], total: 1, count_unit: 'groups', limit: 25, offset: 0, cohort_token: `${sector}-cohort`, facets: { regions: [], stages: [] } } })
  })

  await page.goto('/?view=workspace&groupBrowse=1&shortlist=0')
  await expect(page.locator('.customer-group')).toContainText('All Sector Group')

  await page.getByRole('button', { name: 'Data Centers', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Data Centers', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('.project-results')).toHaveAttribute('aria-busy', 'true')
  await expect(page.getByRole('status')).toContainText('Refreshing accounts; previous results are hidden')
  await expect(page.locator('.customer-group')).toHaveCount(0)
  expect(requests).toContain('data_centers')

  releaseDataCenters()
  await expect(page.locator('.project-results')).toHaveAttribute('aria-busy', 'false')
  await expect(page.locator('.customer-group')).toContainText('Data Center Group')
  await expect(page.locator('.customer-group')).toContainText('Data Center Group')
  await expect(page.locator('.customer-group')).not.toContainText('All Sector Group')
})

test('a rapid sector change ignores a late response from the previously requested cohort', async ({ page }) => {
  let releaseDataCenters!: () => void
  const dataCentersPending = new Promise<void>(resolve => { releaseDataCenters = resolve })
  const requests: string[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', async route => {
    const url = new URL(route.request().url())
    const sector = url.searchParams.get('sector') ?? 'all'
    requests.push(sector)
    if (sector === 'data_centers') await dataCentersPending
    const result = sector === 'data_centers'
      ? { id: 'dc-group', name: 'Data Center Group', role: 'customer', project_count: 1, need_count: 1, sectors: ['data_centers'] }
      : sector === 'oil_gas'
        ? { id: 'oil-group', name: 'Oil and Gas Group', role: 'operator', project_count: 1, need_count: 1, sectors: ['oil_gas'] }
        : { id: 'all-group', name: 'All Sector Group', role: 'customer', project_count: 2, need_count: 2, sectors: ['oil_gas', 'data_centers'] }
    await route.fulfill({ json: { items: [result], total: 1, count_unit: 'groups', limit: 25, offset: 0, cohort_token: `${sector}-cohort`, facets: { regions: [], stages: [] } } })
  })

  await page.goto('/?view=workspace&groupBrowse=1&shortlist=0')
  await expect(page.locator('.customer-group')).toContainText('All Sector Group')

  await page.getByRole('button', { name: 'Data Centers', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('Refreshing accounts; previous results are hidden')
  await page.getByRole('button', { name: 'Oil & Gas', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Oil & Gas', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('.customer-group')).toContainText('Oil and Gas Group')
  releaseDataCenters()
  await expect(page.locator('.customer-group')).toContainText('Oil and Gas Group')
  await expect(page.locator('.customer-group')).not.toContainText('Data Center Group')
  expect(requests.slice(-2)).toEqual(['data_centers', 'oil_gas'])
})

test('failed sector results keep retry through no-op filter clicks and reverted search drafts', async ({ page }) => {
  let releaseFailure!: () => void
  const failurePending = new Promise<void>(resolve => { releaseFailure = resolve })
  let dataCenterReads = 0
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', async route => {
    const sector = new URL(route.request().url()).searchParams.get('sector') ?? 'all'
    if (sector === 'data_centers') {
      dataCenterReads += 1
      if (dataCenterReads === 1) {
        await failurePending
        await route.fulfill({ status: 503, json: { detail: 'Data Centers groups temporarily unavailable' } })
        return
      }
    }
    const result = sector === 'data_centers'
      ? { id: 'dc-retry-group', name: 'Recovered Data Center Group', role: 'customer', project_count: 1, need_count: 1, sectors: ['data_centers'] }
      : { id: 'all-before-error', name: 'All Sector Before Error', role: 'customer', project_count: 1, need_count: 1, sectors: ['oil_gas', 'data_centers'] }
    await route.fulfill({ json: { items: [result], total: 1, count_unit: 'groups', limit: 25, offset: 0, cohort_token: `${sector}-retry-cohort`, facets: { regions: [], stages: [] } } })
  })

  await page.goto('/?view=workspace&groupBrowse=1&shortlist=0')
  await expect(page.locator('.customer-group')).toContainText('All Sector Before Error')
  await page.getByRole('button', { name: 'Data Centers', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('Refreshing accounts; previous results are hidden')
  await expect(page.locator('.customer-group')).toHaveCount(0)
  releaseFailure()

  const alert = page.getByRole('alert')
  await expect(alert).toContainText('Could not load accounts')
  await expect(alert.getByRole('button', { name: 'Retry' })).toBeVisible()
  await expect(page.locator('.project-results')).toHaveAttribute('aria-busy', 'false')
  await expect(page.locator('.customer-group-list')).toHaveCount(0)

  // Selecting the already-active sector does not start a new cohort request,
  // so it must leave the actionable error state in place.
  await page.getByRole('button', { name: 'Data Centers', exact: true }).click()
  await expect(alert).toContainText('Could not load accounts')
  await expect(alert.getByRole('button', { name: 'Retry' })).toBeVisible()
  expect(dataCenterReads).toBe(1)

  // A draft that is reverted before debounce is not a request either; the
  // failed cohort's retry remains available until a real read starts.
  const search = page.getByRole('textbox', { name: 'Search accounts and projects' })
  await search.fill('temporary draft')
  await search.fill('')
  await page.waitForTimeout(400)
  await expect(alert).toContainText('Could not load accounts')
  await expect(alert.getByRole('button', { name: 'Retry' })).toBeVisible()
  await expect(page.locator('.project-results-count')).not.toHaveText('No accounts')
  expect(dataCenterReads).toBe(1)

  await alert.getByRole('button', { name: 'Retry' }).click()
  await expect(page.locator('.customer-group')).toContainText('Recovered Data Center Group')
  await expect(page.locator('.project-results')).toHaveAttribute('aria-busy', 'false')
  await expect(page.locator('.customer-group')).not.toContainText('All Sector Before Error')
  expect(dataCenterReads).toBe(2)
})

test('responsive sector loading and settled states render at desktop, tablet, and phone widths', async ({ page }) => {
  let pendingSector: string | undefined
  let releasePending!: () => void
  let pending = Promise.resolve()
  const fixture = (sector: string) => ({ id: `${sector}-visual-group`, name: `${sector === 'oil_gas' ? 'Oil and Gas' : 'Data Center'} Visual Group`, role: 'customer', project_count: 1, need_count: 1, sectors: [sector] })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', async route => {
    const sector = new URL(route.request().url()).searchParams.get('sector') ?? 'all'
    if (sector === pendingSector) await pending
    const item = sector === 'all' ? { ...fixture('oil_gas'), id: 'visual-all', name: 'All Sector Visual Group' } : fixture(sector)
    await route.fulfill({ json: { items: [item], total: 1, count_unit: 'groups', limit: 25, offset: 0, cohort_token: `${sector}-visual`, facets: { regions: [], stages: [] } } })
  })
  await page.goto('/?view=workspace&groupBrowse=1&shortlist=0')
  await expect(page.locator('.customer-group')).toContainText('All Sector Visual Group')
  const sizes = [
    { name: 'desktop1440', width: 1440, height: 1000, sector: 'data_centers', label: 'Data Centers' },
    { name: 'header1281', width: 1281, height: 900, sector: 'oil_gas', label: 'Oil & Gas' },
    { name: 'tablet768', width: 768, height: 1024, sector: 'data_centers', label: 'Data Centers' },
    { name: 'mobile390', width: 390, height: 844, sector: 'oil_gas', label: 'Oil & Gas' },
  ] as const
  for (const size of sizes) {
    await page.setViewportSize({ width: size.width, height: size.height })
    pendingSector = size.sector
    pending = new Promise<void>(resolvePending => { releasePending = resolvePending })
    await page.getByRole('button', { name: size.label, exact: true }).click()
    await expect(page.locator('.project-results')).toHaveAttribute('aria-busy', 'true')
    await expect(page.getByRole('status')).toBeVisible()
    await page.screenshot({ path: test.info().outputPath(`${size.name}-loading.png`), fullPage: true })
    releasePending()
    await expect(page.locator('.customer-group')).toContainText('Visual Group')
    await expect(page.locator('.project-results')).toHaveAttribute('aria-busy', 'false')
    await page.screenshot({ path: test.info().outputPath(`${size.name}-settled.png`), fullPage: true })
    pendingSector = undefined
  }
})
