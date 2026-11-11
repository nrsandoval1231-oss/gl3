import { openProjectFilters, selectProjectType } from '../../tests/ui-helpers'
import { expect, test, type Page } from '@playwright/test'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'

type Target = { id: string; name: string; project_count: number; identity_count?: number }
type Manifest = {
  synthetic_fixture: true
  generation_id: string
  total_rows: number
  group_count: number
  groups: {
    de_central: Target & { project_ids: string[]; need_ids: string[]; operator_number: string; search: string }
    diamondback: Target & { project_ids: string[]; need_ids: string[]; operator_number: string }
    amazon: Target & { project_ids: string[]; need_ids: string[]; identity_count: number; identity_ids: string[] }
  }
}
type Measurement = { viewport: string; label: string; path: string; elapsedUntilBodyCompleteMs: number; status: number }

const httpBudgetMs = 15_000
const uiBudgetMs = Number(process.env.CUSTOMER_ROLLUP_UI_READY_MS ?? 15_000)
const measurements: Measurement[] = []
const viewportReports: Array<Record<string, unknown>> = []
const viewports = [{ label: '1440x900', width: 1440, height: 900 }, { label: '768x1024', width: 768, height: 1024 }, { label: '390x844', width: 390, height: 844 }]
const manifestPath = process.env.CUSTOMER_ROLLUP_REAL_MANIFEST
const outputDir = process.env.CUSTOMER_ROLLUP_REAL_OUTPUT_DIR
if (!manifestPath) throw new Error('Set CUSTOMER_ROLLUP_REAL_MANIFEST to the disposable fixture manifest. No mock routes or local test payloads are accepted.')
if (!outputDir) throw new Error('Set CUSTOMER_ROLLUP_REAL_OUTPUT_DIR outside web for real-browser evidence.')
const manifestPromise = readFile(manifestPath, 'utf8').then(value => JSON.parse(value) as Manifest)
const password = process.env.CUSTOMER_ROLLUP_REAL_PASSWORD
if (!password) throw new Error('Set CUSTOMER_ROLLUP_REAL_PASSWORD to the disposable stack password. The fixture manifest contains no credentials.')

function loopback(url: URL) {
  return ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)
}

async function observeRealHttp(page: Page, viewport: string) {
  const starts = new Map<import('@playwright/test').Request, number>()
  const statuses = new Map<import('@playwright/test').Request, number>()
  const nonLoopback: string[] = []
  await page.context().route('**/*', route => {
    const url = new URL(route.request().url())
    if (!['http:', 'https:'].includes(url.protocol) || !loopback(url)) {
      nonLoopback.push(`${route.request().method()} ${url.origin}${url.pathname}`)
      return route.abort()
    }
    return route.continue()
  })
  page.on('request', request => starts.set(request, Date.now()))
  page.on('response', response => {
    statuses.set(response.request(), response.status())
  })
  page.on('requestfinished', request => {
    const url = new URL(request.url())
    const started = starts.get(request)
    if (url.pathname.startsWith('/api/') && started !== undefined) {
      const elapsedUntilBodyCompleteMs = Date.now() - started
      measurements.push({ viewport, label: request.method(), path: `${url.pathname}${url.search} [body complete]`, elapsedUntilBodyCompleteMs, status: statuses.get(request) ?? 0 })
    }
  })
  return nonLoopback
}

async function openDeCentralEndpoint(page: Page, target: Target) {
  // The searchable STORMCHASER fixture is New Mexico / well_permitted; keep
  // the combined filters aligned with that exact source-backed synthetic row.
  const endpoint = `/api/opportunities/groups/${encodeURIComponent(target.id)}/open?${new URLSearchParams({ search: 'STORMCHASER', sector: 'oil_gas', sort: 'priority', limit: '25', region: 'New Mexico', stage: 'well_permitted', priority: 'ranked' })}`
  const result = await page.evaluate(async url => {
    const response = await fetch(url, { credentials: 'same-origin' })
    return { status: response.status, body: await response.json() as { group: { id: string }; projects: { total: number; items: unknown[] } } }
  }, endpoint)
  expect(result.status, `DE48 ${endpoint} must return HTTP 200`).toBe(200)
  expect(result.body.group.id).toBe(target.id)
  expect(result.body.projects.total).toBe(target.project_count)
  expect(result.body.projects.items.length).toBeGreaterThan(0)
}

async function openDeCentralConflictingFilterEndpoint(page: Page, target: Target) {
  const endpoint = `/api/opportunities/groups/${encodeURIComponent(target.id)}/open?${new URLSearchParams({ search: 'STORMCHASER', sector: 'oil_gas', sort: 'priority', limit: '25', region: 'Texas', stage: 'permit_issued', priority: 'ranked' })}`
  const result = await page.evaluate(async url => {
    const response = await fetch(url, { credentials: 'same-origin' })
    return { status: response.status, body: await response.json() as { projects?: { total: number } } }
  }, endpoint)
  expect([200, 404], `Contradictory filters should return no eligible DE CENTRAL project: ${endpoint}`).toContain(result.status)
  if (result.status === 200) expect(result.body.projects?.total).toBe(0)
}

async function openDeCentralFailedQueryEndpoint(page: Page, target: Target) {
  const endpoint = `/api/opportunities/groups/${encodeURIComponent(target.id)}/open?${new URLSearchParams({ search: 'DE CENTRAL', sector: 'oil_gas', sort: 'priority', limit: '25' })}`
  const result = await page.evaluate(async url => {
    const response = await fetch(url, { credentials: 'same-origin' })
    return { status: response.status, body: await response.json() as { group: { id: string }; projects: { total: number; limit: number; items: unknown[] } } }
  }, endpoint)
  expect(result.status, `Exact DE CENTRAL open ${endpoint} must return HTTP 200`).toBe(200)
  expect(result.body.group.id).toBe(target.id)
  expect(result.body.projects.total).toBe(target.project_count)
  expect(result.body.projects.limit).toBe(25)
  expect(result.body.projects.items.length).toBeGreaterThan(0)
}

async function assertCompanySortedFirstPage(page: Page, manifest: Manifest, target: Target) {
  const endpoint = '/api/opportunities/groups?' + new URLSearchParams({ sector: 'all', sort: 'company', limit: '50' })
  const result = await page.evaluate(async url => {
    const response = await fetch(url, { credentials: 'same-origin' })
    return { status: response.status, body: await response.json() as { total: number; limit: number; items: Array<{ id: string }> } }
  }, endpoint)
  expect(result.status, 'All/company/50 first page must return HTTP 200').toBe(200)
  expect(result.body.total).toBe(manifest.group_count)
  expect(result.body.limit).toBe(50)
  expect(result.body.items.some(group => group.id === target.id), 'DE CENTRAL must sort outside this first page').toBe(false)
}

async function waitForGroups(page: Page) {
  await expect(page.locator('.project-results')).toBeVisible({ timeout: uiBudgetMs })
  await expect(page.locator('.project-results-count')).toContainText(/\d+ accounts?/, { timeout: uiBudgetMs })
  await expect(page.locator('.project-results[aria-busy="true"]')).toHaveCount(0, { timeout: uiBudgetMs })
}

async function openTarget(page: Page, target: Target) {
  const backToAccounts = page.getByRole('button', { name: 'Back to accounts' })
  if (await backToAccounts.count()) {
    await backToAccounts.click()
    await waitForGroups(page)
  }
  // Search is server-side. The returned persisted group id must be visible
  // before clicking it; the test never synthesizes a response.
  await openProjectFilters(page)
  const search = page.getByRole('textbox', { name: 'Search accounts and projects' })
  const result = page.waitForResponse(async response => {
    const url = new URL(response.url())
    if (url.pathname !== '/api/opportunities/groups' || url.searchParams.get('search') !== target.name) return false
    if (!response.ok()) return true
    const body = await response.json() as { items: Array<{ id: string; name: string; identity_count?: number }> }
    return body.items.some(group => group.id === target.id && group.name === target.name)
  }, { timeout: uiBudgetMs })
  await search.fill(target.name)
  const groupSearchResponse = await result
  if (target.identity_count !== undefined) {
    const groupSearchBody = await groupSearchResponse.json() as { items: Array<{ id: string; identity_count?: number }> }
    const matched = groupSearchBody.items.find(group => group.id === target.id)
    expect(matched?.identity_count, `${target.name} must retain all ${target.identity_count} resolved company identities`).toBe(target.identity_count)
  }
  await expect(page.locator('.customer-group').filter({ has: page.getByRole('button', { name: new RegExp(target.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) }) })).toHaveCount(1, { timeout: uiBudgetMs })
  const group = page.locator('.customer-group').filter({ has: page.getByRole('button', { name: new RegExp(target.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) }) })
  await group.getByRole('button', { name: new RegExp(target.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) }).click()
  await expect(page).toHaveURL(new RegExp(`[?&]account=${encodeURIComponent(target.id)}(?:&|$)`), { timeout: uiBudgetMs })
  const account = page.getByRole('region', { name: new RegExp(`(?:Company|Group) ${target.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`) })
  await expect(account.getByRole('region', { name: 'Account projects' })).toBeVisible({ timeout: uiBudgetMs })
  return account
}

async function readAllVisibleChildPages(page: Page, group: ReturnType<Page['locator']>, expected: number) {
  let observed = 0
  for (;;) {
    await expect(group.locator('[data-project-id]').first()).toBeVisible({ timeout: uiBudgetMs })
    observed = await group.locator('[data-project-id]').count()
    const next = group.getByRole('button', { name: 'Load more projects' })
    if (await next.count() === 0) break
    await next.click()
    await expect(group.locator('[data-project-id]')).toHaveCount(Math.min(expected, observed + 25), { timeout: uiBudgetMs })
  }
  expect(observed, 'Every child page should expose every project in the target group').toBe(expected)
  return observed
}

for (const viewport of viewports) {
  test(`real customer rollup journeys at ${viewport.label}`, async ({ page }, testInfo) => {
    const manifest = await manifestPromise
    expect(manifest.synthetic_fixture, 'Fixture must identify synthetic-only data').toBe(true)
    expect(manifest.total_rows, 'Fixture must declare its synthetic BrowseRow count').toBeGreaterThanOrEqual(2_000)
    expect(manifest.group_count, 'Fixture must provide more than fifty real customer groups').toBeGreaterThan(50)
    const { de_central: de48, diamondback: diamond159, amazon } = manifest.groups
    expect(de48.project_count).toBe(48)
    expect(diamond159.project_count).toBe(159)
    expect(amazon.project_count).toBe(3)
    expect(amazon.identity_count).toBe(3)
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    const forbiddenRequests = await observeRealHttp(page, viewport.label)
    // This lane validates the full legacy rollup cohort. Keep the curated
    // account shortlist exercised by the separate account-first journeys.
    await page.goto('/?view=opportunities&groupBrowse=1&shortlist=0')
    await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible({ timeout: uiBudgetMs })
    await page.getByLabel('Password', { exact: true }).fill(password)
    const coldResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/opportunities/groups', { timeout: httpBudgetMs })
    const coldStarted = Date.now()
    await page.getByRole('button', { name: 'Continue' }).click()
    await expect(page.getByRole('heading', { name: 'Sign in' })).toHaveCount(0, { timeout: uiBudgetMs })
    await waitForGroups(page)
    const coldUiMs = Date.now() - coldStarted
    expect(coldUiMs, `Cold UI readiness must meet the explicit ${uiBudgetMs} ms budget`).toBeLessThanOrEqual(uiBudgetMs)
    const firstGroupResponse = await coldResponse
    const firstGroups = await firstGroupResponse.json() as { total: number; items: Array<{ id: string }> }
    expect(firstGroups.total, 'Actual backend group total must match the generated full cohort').toBe(manifest.group_count)
    expect(firstGroups.items.length).toBeGreaterThan(0)
    expect(new Set(firstGroups.items.map(item => item.id)).size).toBe(firstGroups.items.length)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `${viewport.label} viewport must not have horizontal page overflow`).toBe(true)
    await assertCompanySortedFirstPage(page, manifest, de48)
    await openDeCentralEndpoint(page, de48)
    await openDeCentralConflictingFilterEndpoint(page, de48)
    await openDeCentralFailedQueryEndpoint(page, de48)

    const warmResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/opportunities/groups', { timeout: httpBudgetMs })
    const warmStarted = Date.now()
    await page.reload()
    await waitForGroups(page)
    const warmUiMs = Date.now() - warmStarted
    await warmResponse
    expect(warmUiMs, `Warm UI readiness must meet the explicit ${uiBudgetMs} ms budget`).toBeLessThanOrEqual(uiBudgetMs)
    await openDeCentralEndpoint(page, de48)
    await openDeCentralConflictingFilterEndpoint(page, de48)
    await openDeCentralFailedQueryEndpoint(page, de48)

    // Exact full-cohort search implicated by the SQL profile; record and assert
    // the actual browser request parameters without an HTTP mock.
    const failingSearch = page.waitForResponse(response => {
      const url = new URL(response.url())
      return url.pathname === '/api/opportunities/groups' && url.searchParams.get('sector') === 'oil_gas' && url.searchParams.get('search') === 'DE CENTRAL' && url.searchParams.get('sort') === 'priority' && url.searchParams.get('limit') === '25'
    }, { timeout: httpBudgetMs })
    await selectProjectType(page, 'oil_gas')
    await openProjectFilters(page)
    await page.getByRole('textbox', { name: 'Search accounts and projects' }).fill('DE CENTRAL')
    const failingSearchResponse = await failingSearch
    expect(failingSearchResponse.status()).toBe(200)
    const failingSearchBody = await failingSearchResponse.json() as { items: Array<{ id: string }>; total: number; limit: number }
    expect(failingSearchBody.items.some(group => group.id === de48.id)).toBe(true)
    expect(failingSearchBody.limit).toBe(25)
    expect(failingSearchBody.total).toBeGreaterThan(0)
    await expect(page.locator('.project-results[aria-busy="true"]')).toHaveCount(0, { timeout: uiBudgetMs })

    // Exercise global filters and sort through the actual UI, then inspect the
    // resulting browser request. Global paging must expose a second page.
    await openProjectFilters(page)
    const requests: URL[] = []
    page.on('request', request => {
      const url = new URL(request.url())
      if (url.pathname === '/api/opportunities/groups') requests.push(url)
    })
    await selectProjectType(page, 'all')
    await page.getByRole('textbox', { name: 'Search accounts and projects' }).fill('')
    await expect.poll(() => requests.at(-1)?.searchParams.get('search') ?? '', { timeout: uiBudgetMs }).toBe('')
    await waitForGroups(page)
    await page.getByRole('combobox', { name: 'Priority' }).selectOption('ranked')
    await expect.poll(() => requests.at(-1)?.searchParams.get('priority'), { timeout: uiBudgetMs }).toBe('ranked')
    await expect(page.locator('.project-results[aria-busy="true"]')).toHaveCount(0, { timeout: uiBudgetMs })
    await page.getByRole('combobox', { name: 'Sort opportunities' }).selectOption('company')
    await expect.poll(() => requests.at(-1)?.searchParams.get('sort'), { timeout: uiBudgetMs }).toBe('company')
    const regionOptions = await page.getByRole('combobox', { name: 'Region' }).locator('option').evaluateAll(options => options.map(option => (option as HTMLOptionElement).value).filter(Boolean))
    expect(regionOptions.length, 'Synthetic fixture should expose at least one real region filter').toBeGreaterThan(0)
    const regionValue = regionOptions[0]
    const regionResponseWait = page.waitForResponse(response => {
      const url = new URL(response.url())
      return url.pathname === '/api/opportunities/groups' && url.searchParams.get('region') === regionValue
    }, { timeout: httpBudgetMs })
    await page.getByRole('combobox', { name: 'Region' }).selectOption(regionValue)
    const regionResponse = await regionResponseWait
    expect(regionResponse.status(), 'Region filter must reach the real API successfully').toBe(200)
    const regionBody = await regionResponse.json() as { total: number; limit: number; items: unknown[] }
    expect(regionBody.total, 'Region filter must return a coherent observed cohort').toBeGreaterThan(0)
    expect(regionBody.items.length).toBe(Math.min(regionBody.total, regionBody.limit))
    await waitForGroups(page)

    const stageOptions = await page.getByRole('combobox', { name: 'Stage' }).locator('option').evaluateAll(options => options.map(option => (option as HTMLOptionElement).value).filter(Boolean))
    expect(stageOptions.length, 'Synthetic fixture should expose at least one real stage filter').toBeGreaterThan(0)
    const stageValue = stageOptions[0]
    const stageResponseWait = page.waitForResponse(response => {
      const url = new URL(response.url())
      return url.pathname === '/api/opportunities/groups' && url.searchParams.get('region') === regionValue && url.searchParams.get('stage') === stageValue
    }, { timeout: httpBudgetMs })
    await page.getByRole('combobox', { name: 'Stage' }).selectOption(stageValue)
    const stageResponse = await stageResponseWait
    expect(stageResponse.status(), 'Combined region and stage filter must reach the real API successfully').toBe(200)
    const stageBody = await stageResponse.json() as { total: number; limit: number; items: unknown[] }
    expect(stageBody.total, 'Filtered cohort total cannot be negative').toBeGreaterThanOrEqual(0)
    expect(stageBody.items.length).toBe(Math.min(stageBody.total, stageBody.limit))
    await expect.poll(() => requests.at(-1)?.searchParams.get('stage'), { timeout: uiBudgetMs }).toBe(stageValue)
    await waitForGroups(page)
    if (stageBody.total === 0) {
      await expect(page.locator('.project-empty')).toContainText('No accounts match this search.', { timeout: uiBudgetMs })
      await expect(page.locator('.customer-group')).toHaveCount(0)
    } else {
      await expect(page.locator('.customer-group')).toHaveCount(stageBody.items.length, { timeout: uiBudgetMs })
    }

    // Clear the narrowing filters before asserting global pagination. A real
    // region/stage intersection may legitimately contain fewer than 25 accounts.
    const clearRegionWait = page.waitForResponse(response => {
      const url = new URL(response.url())
      return url.pathname === '/api/opportunities/groups' && !url.searchParams.has('region') && url.searchParams.get('stage') === stageValue
    }, { timeout: httpBudgetMs })
    await page.getByRole('combobox', { name: 'Region' }).selectOption('')
    expect((await clearRegionWait).status(), 'Clearing region must reload actual API results').toBe(200)
    await waitForGroups(page)
    const clearStageWait = page.waitForResponse(response => {
      const url = new URL(response.url())
      return url.pathname === '/api/opportunities/groups' && !url.searchParams.has('region') && !url.searchParams.has('stage') && url.searchParams.get('priority') === 'ranked'
    }, { timeout: httpBudgetMs })
    await page.getByRole('combobox', { name: 'Stage' }).selectOption('')
    expect((await clearStageWait).status(), 'Clearing stage must reload actual API results').toBe(200)
    await waitForGroups(page)
    const broadPageWait = page.waitForResponse(response => {
      const url = new URL(response.url())
      return url.pathname === '/api/opportunities/groups' && !url.searchParams.has('region') && !url.searchParams.has('stage') && !url.searchParams.has('priority') && url.searchParams.get('sort') === 'company' && (url.searchParams.get('offset') ?? '0') === '0'
    }, { timeout: httpBudgetMs })
    await page.getByRole('combobox', { name: 'Priority' }).selectOption('')
    const broadPageResponse = await broadPageWait
    expect(broadPageResponse.status(), 'Broad unfiltered cohort must reach the real API successfully').toBe(200)
    const broadPage = await broadPageResponse.json() as { total: number; limit: number; offset: number; items: Array<{ id: string }> }
    expect(broadPage.total, 'Global pagination must use the actual full synthetic group total').toBe(manifest.group_count)
    expect(broadPage.total).toBeGreaterThan(broadPage.limit)
    expect(broadPage.items.length).toBe(broadPage.limit)
    await waitForGroups(page)
    const globalNext = page.locator('.project-results > footer.project-paging').getByRole('button', { name: 'Next' })
    await expect(globalNext).toBeEnabled({ timeout: uiBudgetMs })
    const nextPageWait = page.waitForResponse(response => {
      const url = new URL(response.url())
      return url.pathname === '/api/opportunities/groups' && url.searchParams.get('offset') === '25' && !url.searchParams.has('region') && !url.searchParams.has('stage') && !url.searchParams.has('priority')
    }, { timeout: httpBudgetMs })
    await globalNext.click()
    const nextPageResponse = await nextPageWait
    expect(nextPageResponse.status(), 'Global next page must use the real API successfully').toBe(200)
    const nextPageBody = await nextPageResponse.json() as { total: number; offset: number; items: Array<{ id: string }> }
    expect(nextPageBody.total).toBe(manifest.group_count)
    expect(nextPageBody.offset).toBe(25)
    expect(nextPageBody.items).toHaveLength(broadPage.limit)
    await waitForGroups(page)
    const deGroup = await openTarget(page, de48)
    await readAllVisibleChildPages(page, deGroup, de48.project_count)
    const deNeedIds = new Set(de48.need_ids)
    const detailResponseWait = page.waitForResponse(response => {
      const url = new URL(response.url())
      const needId = url.pathname.split('/').at(-1) ?? ''
      return url.pathname.startsWith('/api/opportunities/needs/') && deNeedIds.has(needId)
    }, { timeout: httpBudgetMs })
    const preparedProjectWait = page.waitForResponse(response => {
      const url = new URL(response.url())
      return url.pathname === '/api/opportunities/projects' && deNeedIds.has(url.searchParams.get('need_id') ?? '')
    }, { timeout: httpBudgetMs })
    const detail = deGroup.getByRole('region', { name: 'Account projects' }).locator('[data-project-id]').first().getByRole('button', { name: /Open (?:project detail|matching opportunity)/ })
    await detail.click()
    const detailResponse = await detailResponseWait
    expect(detailResponse.status(), 'Project detail identity request must return HTTP 200 from the real API').toBe(200)
    const detailBody = await detailResponse.json() as { id: string }
    expect(deNeedIds.has(detailBody.id), 'Detail response must identify a member of the opened synthetic group').toBe(true)
    const preparedProjectResponse = await preparedProjectWait
    expect(preparedProjectResponse.status(), 'Project overview readback must return HTTP 200 from the real API').toBe(200)
    const preparedProjectBody = await preparedProjectResponse.json() as { items: Array<{ needs: Array<{ id: string }> }> }
    expect(preparedProjectBody.items.some(project => project.needs.some(need => need.id === detailBody.id)), 'Project overview must resolve the selected canonical need').toBe(true)
    const detailPanel = page.getByRole('complementary', { name: 'Opportunity detail' })
    await expect(detailPanel.locator('h2').first()).toBeVisible({ timeout: uiBudgetMs })
    await expect(detailPanel.getByText('Loading current project details…')).toHaveCount(0, { timeout: uiBudgetMs })
    await expect(detailPanel.getByRole('alert')).toHaveCount(0)
    await expect(detailPanel.getByText('The available source support is historical; confirm it before acting.')).toBeVisible({ timeout: uiBudgetMs })
    const backButton = detailPanel.getByRole('button', { name: /Back to account/ })
    await expect(backButton).toBeVisible({ timeout: uiBudgetMs })
    await expect(backButton).toBeEnabled({ timeout: uiBudgetMs })
    await backButton.click()
    await expect(deGroup.getByRole('region', { name: 'Account projects' }).locator('[data-project-id]')).toHaveCount(48, { timeout: uiBudgetMs })

    const diamond = await openTarget(page, diamond159)
    await readAllVisibleChildPages(page, diamond, diamond159.project_count)

    const amazonGroup = await openTarget(page, amazon)
    await expect(amazonGroup).toContainText('3 separate company identities', { timeout: uiBudgetMs })
    await expect(amazonGroup).toContainText('3 known projects', { timeout: uiBudgetMs })
    await readAllVisibleChildPages(page, amazonGroup, amazon.project_count)

    expect(forbiddenRequests, 'Browser attempted an external/non-loopback request').toEqual([])
    const httpEvidence = measurements.filter(item => item.viewport === viewport.label)
    for (const measurement of httpEvidence) {
      const query = new URL(`http://127.0.0.1${measurement.path.replace(' [body complete]', '')}`)
      const expectedNoMatch = query.pathname.endsWith(`/groups/${de48.id}/open`)
        && query.searchParams.get('search') === 'STORMCHASER'
        && query.searchParams.get('region') === 'Texas'
        && query.searchParams.get('stage') === 'permit_issued'
        && measurement.status === 404
      expect(expectedNoMatch || (measurement.status >= 200 && measurement.status < 400), `${measurement.label} ${measurement.path} returned unexpected HTTP ${measurement.status}`).toBe(true)
      expect(measurement.elapsedUntilBodyCompleteMs, `${measurement.label} ${measurement.path} exceeded the retained ${httpBudgetMs} ms HTTP acceptance budget`).toBeLessThanOrEqual(httpBudgetMs)
    }
    expect(httpEvidence.some(item => item.path.startsWith('/api/opportunities/groups'))).toBe(true)
    const deOpenEvidence = httpEvidence.filter(item => item.path.includes(`/api/opportunities/groups/${de48.id}/open?`))
    const directOpenQuery = (item: Measurement) => new URL(`http://127.0.0.1${item.path.replace(' [body complete]', '')}`).searchParams
    expect(deOpenEvidence.filter(item => directOpenQuery(item).get('search') === 'STORMCHASER' && directOpenQuery(item).get('region') === 'New Mexico')).toHaveLength(2)
    expect(deOpenEvidence.filter(item => directOpenQuery(item).get('search') === 'STORMCHASER' && directOpenQuery(item).get('region') === 'Texas')).toHaveLength(2)
    expect(deOpenEvidence.filter(item => directOpenQuery(item).get('search') === 'DE CENTRAL')).toHaveLength(2)
    expect(httpEvidence.some(item => {
      if (!item.path.includes(`/api/opportunities/groups/${de48.id}/projects?`)) return false
      return directOpenQuery(item).get('search') === de48.name
    }), 'Real DE CENTRAL UI expansion must issue its child-project request').toBe(true)
    const resourceTimings = await page.evaluate(() => performance.getEntriesByType('resource')
      .map(entry => entry as PerformanceResourceTiming)
      .filter(entry => new URL(entry.name).pathname.startsWith('/api/'))
      .map(entry => ({
        path: `${new URL(entry.name).pathname}${new URL(entry.name).search}`,
        startTime: entry.startTime,
        duration: entry.duration,
        requestStart: entry.requestStart,
        responseStart: entry.responseStart,
        responseEnd: entry.responseEnd,
        transferSize: entry.transferSize,
      })))
    await testInfo.attach('customer-rollup-real-http-timings.json', {
      body: JSON.stringify({ viewport: viewport.label, coldUiMs, warmUiMs, coldScope: 'first browser read from fresh Playwright context; server/PostgreSQL cache state unknown', warmScope: 'reload in same browser context and backend process', uiReadyBudgetMs: uiBudgetMs, httpAcceptanceBudgetMs: httpBudgetMs, elapsedSemantics: 'request event through Playwright requestfinished (response body complete), keyed by Request identity', responseMeasurements: httpEvidence, resourceTimings }, null, 2),
      contentType: 'application/json',
    })
    const routeGroups = new Map<string, Measurement[]>()
    for (const sample of httpEvidence) {
      const pathname = new URL(`http://127.0.0.1${sample.path.replace(' [body complete]', '')}`).pathname
      const key = `${sample.label} ${pathname}`
      routeGroups.set(key, [...(routeGroups.get(key) ?? []), sample])
    }
    const percentile = (values: number[], p: number) => {
      const sorted = [...values].sort((left, right) => left - right)
      return sorted[Math.min(sorted.length - 1, Math.ceil(sorted.length * p) - 1)]
    }
    const routeTimings = Object.fromEntries([...routeGroups].map(([route, samples]) => [route, {
      n: samples.length,
      p50_body_complete_ms: percentile(samples.map(sample => sample.elapsedUntilBodyCompleteMs), 0.5),
      p95_body_complete_ms: percentile(samples.map(sample => sample.elapsedUntilBodyCompleteMs), 0.95),
      statuses: [...new Set(samples.map(sample => sample.status))].sort((left, right) => left - right),
    }]))
    viewportReports.push({
      viewport: viewport.label,
      width: viewport.width,
      height: viewport.height,
      cold_ui_ready_ms: coldUiMs,
      warm_reload_ready_ms: warmUiMs,
      ui_ready_budget_ms: uiBudgetMs,
      request_count: httpEvidence.length,
      expected_negative_no_match_404_count: httpEvidence.filter(sample => {
        const query = new URL(`http://127.0.0.1${sample.path.replace(' [body complete]', '')}`)
        return query.pathname.endsWith(`/groups/${de48.id}/open`) && query.searchParams.get('region') === 'Texas' && query.searchParams.get('stage') === 'permit_issued' && sample.status === 404
      }).length,
      route_timings: routeTimings,
      browser_resource_timings: resourceTimings,
    })
    if (viewportReports.length === viewports.length) {
      await mkdir(outputDir, { recursive: true })
      await writeFile(join(outputDir, 'customer-rollup-report.json'), JSON.stringify({
        synthetic_fixture: true,
        manifest: {
          generation_id: manifest.generation_id,
          row_count: manifest.total_rows,
          account_group_count: manifest.group_count,
          de_central_projects: de48.project_count,
          diamondback_projects: diamond159.project_count,
          amazon_projects: amazon.project_count,
          amazon_company_identities: amazon.identity_count,
        },
        semantics: {
          http_elapsed: 'Per route, request start through Playwright requestfinished (response body complete).',
          cold_ui_ready: 'First list render in a fresh browser context; server/PostgreSQL cache state is unknown. n=1 per viewport.',
          warm_reload_ready: 'Same-page reload in the same browser context/process. n=1 per viewport.',
          route_groups: 'Aggregated separately by HTTP method and URL pathname, omitting query values.',
        },
        viewport_runs: viewportReports,
      }, null, 2) + '\n')
    }
  })
}
