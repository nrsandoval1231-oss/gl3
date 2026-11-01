import { expect, test, type Page } from '@playwright/test'
import { readFile } from 'node:fs/promises'

type Target = { id: string; name: string; project_count: number }
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
const manifestPath = process.env.CUSTOMER_ROLLUP_REAL_MANIFEST
if (!manifestPath) throw new Error('Set CUSTOMER_ROLLUP_REAL_MANIFEST to the disposable fixture manifest. No mock routes or local test payloads are accepted.')
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
  const endpoint = `/api/opportunities/groups/${encodeURIComponent(target.id)}/open?${new URLSearchParams({ search: 'STORMCHASER', sector: 'oil_gas', sort: 'priority', limit: '25', region: 'Texas', stage: 'permit_issued', priority: 'ranked' })}`
  const result = await page.evaluate(async url => {
    const response = await fetch(url, { credentials: 'same-origin' })
    return { status: response.status, body: await response.json() as { group: { id: string }; projects: { total: number; items: unknown[] } } }
  }, endpoint)
  expect(result.status, `DE48 ${endpoint} must return HTTP 200`).toBe(200)
  expect(result.body.group.id).toBe(target.id)
  expect(result.body.projects.total).toBe(target.project_count)
  expect(result.body.projects.items.length).toBeGreaterThan(0)
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
  await expect(page.locator('.project-results-count')).toContainText(/\d+ groups?/, { timeout: uiBudgetMs })
  await expect(page.locator('.project-results[aria-busy="true"]')).toHaveCount(0, { timeout: uiBudgetMs })
}

async function openTarget(page: Page, target: Target) {
  // Search is server-side. The returned persisted group id must be visible
  // before clicking it; the test never synthesizes a response.
  const search = page.getByRole('textbox', { name: 'Search opportunities' })
  const result = page.waitForResponse(async response => {
    const url = new URL(response.url())
    if (url.pathname !== '/api/opportunities/groups' || url.searchParams.get('search') !== target.name) return false
    if (!response.ok()) return true
    const body = await response.json() as { items: Array<{ id: string; name: string }> }
    return body.items.some(group => group.id === target.id && group.name === target.name)
  }, { timeout: uiBudgetMs })
  await search.fill(target.name)
  await result
  await expect(page.locator('.customer-group').filter({ has: page.getByRole('button', { name: new RegExp(target.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) }) })).toHaveCount(1, { timeout: uiBudgetMs })
  const group = page.locator('.customer-group').filter({ has: page.getByRole('button', { name: new RegExp(target.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) }) })
  await group.getByRole('button', { name: new RegExp(target.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) }).click()
  await expect(group.getByRole('button', { name: new RegExp(target.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) })).toHaveAttribute('aria-expanded', 'true', { timeout: uiBudgetMs })
  return group
}

async function readAllVisibleChildPages(page: Page, group: ReturnType<Page['locator']>, expected: number) {
  let observed = 0
  for (;;) {
    await expect(group.locator('.project-card').first()).toBeVisible({ timeout: uiBudgetMs })
    observed += await group.locator('.project-card').count()
    const next = group.locator('.project-paging').getByRole('button', { name: 'Next' })
    if (await next.count() === 0 || await next.isDisabled()) break
    const previousPageLabel = await group.locator('.project-paging span').first().innerText()
    await next.click()
    await expect(group.locator('.project-paging span').first()).not.toHaveText(previousPageLabel, { timeout: uiBudgetMs })
    await expect(group.locator('.project-card').first()).toBeVisible({ timeout: uiBudgetMs })
  }
  expect(observed, 'Every child page should expose every project in the target group').toBe(expected)
  return observed
}

for (const viewport of [{ label: '1440x900', width: 1440, height: 900 }, { label: '768x1024', width: 768, height: 1024 }, { label: '390x844', width: 390, height: 844 }]) {
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
    await page.goto('/?view=opportunities')
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
    await openDeCentralFailedQueryEndpoint(page, de48)

    const warmResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/opportunities/groups', { timeout: httpBudgetMs })
    const warmStarted = Date.now()
    await page.reload()
    await waitForGroups(page)
    const warmUiMs = Date.now() - warmStarted
    await warmResponse
    expect(warmUiMs, `Warm UI readiness must meet the explicit ${uiBudgetMs} ms budget`).toBeLessThanOrEqual(uiBudgetMs)
    await openDeCentralEndpoint(page, de48)
    await openDeCentralFailedQueryEndpoint(page, de48)

    // Exact full-cohort search implicated by the SQL profile; record and assert
    // the actual browser request parameters without an HTTP mock.
    const failingSearch = page.waitForResponse(response => {
      const url = new URL(response.url())
      return url.pathname === '/api/opportunities/groups' && url.searchParams.get('sector') === 'oil_gas' && url.searchParams.get('search') === 'DE CENTRAL' && url.searchParams.get('sort') === 'priority' && url.searchParams.get('limit') === '25'
    }, { timeout: httpBudgetMs })
    await page.getByRole('button', { name: 'Oil & Gas', exact: true }).click()
    await page.getByRole('textbox', { name: 'Search opportunities' }).fill('DE CENTRAL')
    const failingSearchResponse = await failingSearch
    expect(failingSearchResponse.status()).toBe(200)
    const failingSearchBody = await failingSearchResponse.json() as { items: Array<{ id: string }>; total: number; limit: number }
    expect(failingSearchBody.items.some(group => group.id === de48.id)).toBe(true)
    expect(failingSearchBody.limit).toBe(25)
    expect(failingSearchBody.total).toBeGreaterThan(0)
    await expect(page.locator('.project-results[aria-busy="true"]')).toHaveCount(0, { timeout: uiBudgetMs })

    // Exercise global filters and sort through the actual UI, then inspect the
    // resulting browser request. Global paging must expose a second page.
    const requests: URL[] = []
    page.on('request', request => {
      const url = new URL(request.url())
      if (url.pathname === '/api/opportunities/groups') requests.push(url)
    })
    await page.getByRole('button', { name: 'All', exact: true }).click()
    await page.getByRole('textbox', { name: 'Search opportunities' }).fill('')
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
      await expect(page.locator('.project-empty')).toContainText('No groups match this search.', { timeout: uiBudgetMs })
      await expect(page.locator('.customer-group')).toHaveCount(0)
    } else {
      await expect(page.locator('.customer-group')).toHaveCount(stageBody.items.length, { timeout: uiBudgetMs })
    }

    // Clear the narrowing filters before asserting global pagination. A real
    // region/stage intersection may legitimately contain fewer than 25 groups.
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
    const childPageLabel = await deGroup.locator('.project-paging span').first().innerText()
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
    const detail = deGroup.getByRole('button', { name: 'View project details' }).first()
    await detail.click()
    const detailResponse = await detailResponseWait
    expect(detailResponse.status(), 'Project detail identity request must return HTTP 200 from the real API').toBe(200)
    const detailBody = await detailResponse.json() as { id: string }
    expect(deNeedIds.has(detailBody.id), 'Detail response must identify a member of the opened synthetic group').toBe(true)
    const preparedProjectResponse = await preparedProjectWait
    expect(preparedProjectResponse.status(), 'Project overview readback must return HTTP 200 from the real API').toBe(200)
    const preparedProjectBody = await preparedProjectResponse.json() as { items: Array<{ needs: Array<{ id: string }> }> }
    expect(preparedProjectBody.items.some(project => project.needs.some(need => need.id === detailBody.id)), 'Project overview must resolve the selected canonical need').toBe(true)
    await expect(page.locator('.project-first-detail h2')).toBeVisible({ timeout: uiBudgetMs })
    await expect(page.locator('.project-first-detail [role="status"]')).toHaveCount(0, { timeout: uiBudgetMs })
    await expect(page.locator('.project-first-detail [role="alert"]')).toHaveCount(0)
    const backButton = page.getByRole('button', { name: 'Back to power needs' })
    await expect(backButton).toBeVisible({ timeout: uiBudgetMs })
    await expect(backButton).toBeEnabled({ timeout: uiBudgetMs })
    await backButton.click()
    await expect(page.locator('.project-results')).toBeVisible({ timeout: uiBudgetMs })
    const restoredDeGroup = page.locator('.customer-group').filter({ has: page.getByRole('button', { name: new RegExp(de48.name) }) })
    await expect(restoredDeGroup).toHaveCount(1, { timeout: uiBudgetMs })
    await expect(restoredDeGroup.getByRole('button', { name: new RegExp(de48.name) })).toHaveAttribute('aria-expanded', 'true', { timeout: uiBudgetMs })
    await expect(restoredDeGroup.locator('.project-paging span').first()).toHaveText(childPageLabel, { timeout: uiBudgetMs })

    const diamond = await openTarget(page, diamond159)
    await readAllVisibleChildPages(page, diamond, diamond159.project_count)

    const amazonGroup = await openTarget(page, amazon)
    await expect(amazonGroup).toContainText('3 separate company identities', { timeout: uiBudgetMs })
    await readAllVisibleChildPages(page, amazonGroup, amazon.project_count)

    expect(forbiddenRequests, 'Browser attempted an external/non-loopback request').toEqual([])
    const httpEvidence = measurements.filter(item => item.viewport === viewport.label)
    for (const measurement of httpEvidence) {
      expect(measurement.status, `${measurement.label} ${measurement.path} returned a non-success status`).toBeGreaterThanOrEqual(200)
      expect(measurement.status, `${measurement.label} ${measurement.path} returned HTTP ${measurement.status}`).toBeLessThan(400)
      expect(measurement.elapsedUntilBodyCompleteMs, `${measurement.label} ${measurement.path} exceeded the retained ${httpBudgetMs} ms HTTP acceptance budget`).toBeLessThanOrEqual(httpBudgetMs)
    }
    expect(httpEvidence.some(item => item.path.startsWith('/api/opportunities/groups'))).toBe(true)
    const deOpenEvidence = httpEvidence.filter(item => item.path.includes(`/api/opportunities/groups/${de48.id}/open?`))
    const directOpenQuery = (item: Measurement) => new URL(`http://127.0.0.1${item.path.replace(' [body complete]', '')}`).searchParams
    expect(deOpenEvidence.filter(item => directOpenQuery(item).get('search') === 'STORMCHASER')).toHaveLength(2)
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
  })
}
