import { openProjectFilters } from '../../tests/ui-helpers'
import { expect, test, type Page } from '@playwright/test'
import { mkdir, readFile, writeFile } from 'node:fs/promises'

type Manifest = {
  synthetic_fixture: true
  migration_revision: '0051_canonical_need_aliases'
  target_need_id: string
  target_project_id: string
  target_name: string
  second_page_need_id: string
  second_page_project_id: string
  contact_project_id: string
  contact_company: string
  contact_phone_href: string
  account_name: string
}
type ApiResponse = { path: string; method: string; status: number }
type TaskBody = { description: string; due_date: string | null; client_id: string }

const manifestPath = process.env.PURSUITS_RELEASE_REAL_MANIFEST
const password = process.env.PURSUITS_RELEASE_REAL_PASSWORD
if (!manifestPath) throw new Error('Set PURSUITS_RELEASE_REAL_MANIFEST to the sanitized local seed manifest.')
if (!password) throw new Error('Set PURSUITS_RELEASE_REAL_PASSWORD for the disposable API only.')
const manifestPromise = readFile(manifestPath, 'utf8').then(raw => JSON.parse(raw) as Manifest)

const viewports = [
  { label: '1648x928', width: 1648, height: 928 },
  { label: '1440x900', width: 1440, height: 900 },
  { label: '1280x800', width: 1280, height: 800 },
  { label: '768x1024', width: 768, height: 1024 },
  { label: '390x844', width: 390, height: 844 },
]

function isLoopback(url: URL) {
  return ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)
}

async function signIn(page: Page): Promise<number> {
  await page.goto('/')
  const signInHeading = page.getByRole('heading', { name: 'Sign in', exact: true })
  const opportunitiesButton = page.getByRole('button', { name: 'Opportunities' })
  await expect(signInHeading).toBeVisible()
  await page.getByLabel('Password', { exact: true }).fill(password!)
  const login = page.waitForResponse(response => new URL(response.url()).pathname === '/api/auth/login')
  const loginStarted = Date.now()
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  const loginResponse = await login
  expect(loginResponse.status(), 'Disposable account login must succeed').toBe(200)
  const sessionCookie = (await page.context().cookies()).find(cookie => cookie.name === 'gridlens_session')
  expect(sessionCookie, 'Login must store the persisted session cookie in the browser context').toBeTruthy()
  expect(sessionCookie?.secure, 'The disposable loopback session cookie must be usable on HTTP').toBe(false)
  expect(sessionCookie?.expires).toBeGreaterThan(Date.now() / 1000)
  const auth = await page.evaluate(async () => {
    const response = await fetch('/api/auth/session', { credentials: 'same-origin' })
    if (!response.ok) return false
    return (await response.json() as { authenticated: boolean }).authenticated
  })
  expect(auth, 'Same-origin session endpoint must validate the login cookie').toBe(true)
  await expect(opportunitiesButton).toBeVisible()
  return loginStarted
}

async function capture(page: Page, testInfo: import('@playwright/test').TestInfo, state: string) {
  for (const viewport of viewports) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), { message: `${state} must fit ${viewport.label}` }).toBe(true)
    const file = testInfo.outputPath('screenshots', `${state}-${viewport.label}.png`)
    await mkdir(testInfo.outputPath('screenshots'), { recursive: true })
    await page.screenshot({ path: file, fullPage: false, animations: 'disabled' })
  }
}

test('real account-first pursuit journey persists through navigation, reload, and lost-response retry', async ({ page }, testInfo) => {
  const manifest = await manifestPromise
  expect(manifest.synthetic_fixture).toBe(true)
  expect(manifest.migration_revision).toBe('0051_canonical_need_aliases')

  const external = new Set<string>()
  const responses: ApiResponse[] = []
  const durations: Array<{ path: string; method: string; status: number; ms: number }> = []
  const interactionTimes: Record<string, number> = {}
  const interactionSamples: Record<string, number[]> = {}
  const recordInteraction = (name: string, elapsedMs: number, warm = false) => {
    if (warm) (interactionSamples[name] ??= []).push(elapsedMs)
  }
  const writes: string[] = []
  const starts = new Map<import('@playwright/test').Request, number>()
  const taskBodies: TaskBody[] = []
  let firstTaskReplyDropped = false
  await page.context().route('**/*', async route => {
    const url = new URL(route.request().url())
    if (!['http:', 'https:'].includes(url.protocol) || !isLoopback(url)) {
      external.add(`${route.request().method()} ${url.origin}${url.pathname}`)
      return route.abort()
    }
    return route.continue()
  })
  page.on('request', request => {
    starts.set(request, Date.now())
    if (request.method() !== 'GET' && !new URL(request.url()).pathname.startsWith('/api/auth/')) writes.push(`${request.method()} ${new URL(request.url()).pathname}`)
  })
  page.on('requestfinished', async request => {
    const url = new URL(request.url()), started = starts.get(request)
    if (url.pathname.startsWith('/api/')) {
      const status = (await request.response())?.status() ?? 0
      responses.push({ path: url.pathname, method: request.method(), status })
      if (started !== undefined) durations.push({ path: `${url.pathname}${url.search}`, method: request.method(), status, ms: Date.now() - started })
    }
  })
  await page.route('**/api/commercial-pursuits/*/tasks', async route => {
    if (route.request().method() !== 'POST') return route.continue()
    const body = route.request().postDataJSON() as TaskBody
    taskBodies.push(body)
    const stored = await route.fetch()
    expect([200, 201]).toContain(stored.status())
    if (!firstTaskReplyDropped) {
      firstTaskReplyDropped = true
      // The real backend commits the task; only this browser reply is lost.
      return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'simulated lost response' }) })
    }
    return route.fulfill({ response: stored })
  })

  const start = await signIn(page)
  await expect(page.getByRole('heading', { name: 'Commercial intelligence for constrained power.' })).toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Opportunity scope' }).getByRole('button', { name: 'Shortlist' })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('.project-results[aria-busy="true"]')).toHaveCount(0)
  await expect(page.locator('.project-results-count')).toContainText(/\d+ accounts?/)
  interactionTimes.loginToFirstShortlistReadyMs = Date.now() - start
  recordInteraction('loginToFirstShortlistReadyMs', interactionTimes.loginToFirstShortlistReadyMs)
  await capture(page, testInfo, 'default-shortlist')

  const searchStarted = Date.now()
  await openProjectFilters(page)
  const search = page.getByRole('textbox', { name: 'Search accounts and projects' })
  const matchingGroups = page.waitForResponse(async response => {
    const url = new URL(response.url())
    if (url.pathname !== '/api/opportunities/groups' || url.searchParams.get('search') !== manifest.account_name) return false
    if (!response.ok()) return true
    const body = await response.json() as { items: Array<{ name: string }> }
    return body.items.some(item => item.name === manifest.account_name)
  })
  await search.fill(manifest.account_name)
  const response = await matchingGroups
  expect(response.status(), await response.text()).toBe(200)
  const accountCard = page.locator('.customer-group').filter({ hasText: manifest.account_name })
  await expect(accountCard).toHaveCount(1)
  interactionTimes.searchUntilAccountResultMs = Date.now() - searchStarted
  recordInteraction('searchUntilAccountResultMs', interactionTimes.searchUntilAccountResultMs)
  const accountStarted = Date.now()
  await accountCard.getByRole('button', { name: new RegExp(manifest.account_name) }).click()
  await expect(page).toHaveURL(/account=cg_/)
  await expect(page.getByRole('heading', { name: manifest.account_name, exact: true })).toBeVisible()
  const account = page.getByRole('region', { name: new RegExp(`(?:Company|Group) ${manifest.account_name}`) })
  await expect(account.getByRole('region', { name: 'Account overview' })).toContainText(/synthetic/i)
  await expect(account.getByRole('region', { name: 'Account projects' })).toBeVisible()
  interactionTimes.accountOpenReadyMs = Date.now() - accountStarted
  recordInteraction('accountOpenReadyMs', interactionTimes.accountOpenReadyMs)
  const accountOverview = account.getByRole('region', { name: 'Account overview' })
  await expect(accountOverview.getByRole('link', { name: 'Call company' })).toHaveAttribute('href', manifest.contact_phone_href)
  expect(writes).toEqual([]) // Inspecting contact routes must not log outreach or mutate a pursuit.
  await capture(page, testInfo, 'account-detail')

  // The selected opportunity intentionally belongs to the account's second
  // independently paged project page.
  const paginationStarted = Date.now()
  await expect(account.getByRole('button', { name: 'Load more projects' })).toBeVisible()
  await account.getByRole('button', { name: 'Load more projects' }).click()
  const secondProject = account.locator(`[data-project-id="${manifest.second_page_project_id}"]`)
  await expect(secondProject).toBeVisible()
  interactionTimes.nestedPaginationReadyMs = Date.now() - paginationStarted
  recordInteraction('nestedPaginationReadyMs', interactionTimes.nestedPaginationReadyMs)
  const projectName = (await secondProject.locator('strong').innerText()).trim()
  const detailStarted = Date.now()
  await secondProject.getByRole('button', { name: /Open project detail/ }).click()
  await expect(page).toHaveURL(new RegExp(`account=cg_.*need=${manifest.second_page_need_id}`))
  const detail = page.getByRole('complementary', { name: 'Opportunity detail' })
  await expect(detail).toBeVisible()
  await expect(detail).toContainText(projectName)
  await expect(detail.getByText('Loading current project details…')).toHaveCount(0)
  await expect(detail.getByRole('alert')).toHaveCount(0)
  await expect(detail.getByRole('button', { name: 'Add to Pursuit' }).or(detail.getByRole('link', { name: 'In Pursuits' }))).toBeVisible()
  interactionTimes.projectDetailReadyMs = Date.now() - detailStarted
  recordInteraction('projectDetailReadyMs', interactionTimes.projectDetailReadyMs)
  await capture(page, testInfo, 'project-detail')
  await page.goBack()
  await expect(page.getByRole('heading', { name: manifest.account_name, exact: true })).toBeVisible()
  await expect(page).toHaveURL(/account=cg_/)
  await expect(account.locator(`[data-project-id="${manifest.second_page_project_id}"]`)).toBeVisible()

  const companiesStarted = Date.now()
  await page.getByRole('button', { name: 'Companies' }).click()
  await expect(page.getByRole('heading', { name: 'Companies', exact: true })).toBeVisible()
  const companySearch = page.getByRole('searchbox', { name: 'Search companies', exact: true })
  const companyResult = page.waitForResponse(async item => {
    const url = new URL(item.url())
    if (url.pathname !== '/api/opportunities/groups' || url.searchParams.get('search') !== manifest.account_name) return false
    if (!item.ok()) return true
    const body = await item.json() as { items: Array<{ name: string }> }
    return body.items.some(group => group.name === manifest.account_name)
  })
  await companySearch.fill(manifest.account_name)
  const companyGroupsResponse = await companyResult
  expect(companyGroupsResponse.status()).toBe(200)
  const companyGroupsBody = await companyGroupsResponse.json() as { items: Array<{ id: string; name: string; account_contact_project?: { project_id: string; name: string; contact: Array<{ href?: string | null; name?: string | null }> } | null }> }
  const companyGroup = companyGroupsBody.items.find(group => group.name === manifest.account_name)
  expect(companyGroup, 'Companies search must return the synthetic account').toBeTruthy()
  const companyContactProject = companyGroup?.account_contact_project
  expect(companyContactProject, 'Companies account contact selection must be available from the real API').toMatchObject({ project_id: manifest.contact_project_id })
  expect(companyContactProject?.contact.map(contact => contact.href)).toEqual(expect.arrayContaining([manifest.contact_phone_href]))
  await page.getByRole('button', { name: new RegExp(`Open ${manifest.account_name}`) }).click()
  const companyDetail = page.getByRole('region', { name: new RegExp(`(?:Company|Group) ${manifest.account_name}`) })
  await expect(companyDetail.getByRole('heading', { name: 'Projects' })).toBeVisible()
  const companyOverview = companyDetail.getByRole('region', { name: 'Account overview' })
  await expect(companyOverview.getByText(`Contact associated with ${companyContactProject!.name}`, { exact: true })).toBeVisible()
  await expect(companyOverview.getByRole('link', { name: 'Call company' })).toHaveAttribute('href', manifest.contact_phone_href)
  expect(writes).toEqual([]) // Viewing an account contact must not create activity or send outreach.
  const chosenProject = companyDetail.locator(`[data-project-id="${manifest.second_page_project_id}"]`)
  if (await chosenProject.count() === 0) await companyDetail.getByRole('button', { name: 'Load more projects' }).click()
  await expect(chosenProject).toBeVisible()
  interactionTimes.companiesSameAccountReadyMs = Date.now() - companiesStarted
  recordInteraction('companiesSameAccountReadyMs', interactionTimes.companiesSameAccountReadyMs)
  await capture(page, testInfo, 'companies-account-detail')
  await expect(chosenProject.getByRole('button', { name: /Add to Pursuit/ })).toBeEnabled()

  const createResponse = page.waitForResponse(item => item.request().method() === 'POST' && new URL(item.url()).pathname === '/api/commercial-pursuits')
  await chosenProject.getByRole('button', { name: /Add to Pursuit/ }).click()
  const created = await createResponse
  expect(created.status()).toBe(201)
  const pursuit = await created.json() as { id: string; need_id: string; account_id?: string }
  expect(pursuit.need_id).toBe(manifest.second_page_need_id)
  const persisted = await page.request.get(`/api/commercial-pursuits?need_id=${encodeURIComponent(manifest.second_page_need_id)}`)
  expect(persisted.status()).toBe(200)
  const persistedBody = await persisted.json() as { items: Array<{ id: string; need_id: string }> }
  expect(persistedBody.items).toHaveLength(1)
  expect(persistedBody.items[0]).toMatchObject({ id: pursuit.id, need_id: manifest.second_page_need_id })

  const pursuitsStarted = Date.now()
  await page.getByRole('button', { name: 'Pursuits' }).click()
  await expect(page.getByRole('heading', { name: 'Pursuits', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: manifest.account_name, exact: true })).toBeVisible()
  await expect(page.getByText(projectName, { exact: false })).toBeVisible()
  interactionTimes.pursuitNavigationReadyMs = Date.now() - pursuitsStarted
  recordInteraction('pursuitNavigationReadyMs', interactionTimes.pursuitNavigationReadyMs)
  await capture(page, testInfo, 'grouped-pursuits')
  await page.reload()
  await expect(page.getByRole('heading', { name: manifest.account_name, exact: true })).toBeVisible()
  await expect(page.getByText(projectName, { exact: false })).toBeVisible()
  const storedPursuit = await page.request.get(`/api/commercial-pursuits/${pursuit.id}`)
  const pursuitDetail = await storedPursuit.json() as { id: string; tasks: Array<{ id: string }> }
  expect(storedPursuit.status()).toBe(200)
  expect(pursuitDetail.id).toBe(pursuit.id)

  const savedPursuitUrl = page.url()
  await page.getByRole('button', { name: 'Reports' }).click()
  await expect(page.getByRole('heading', { name: 'Reports', exact: true })).toBeVisible()
  await page.goBack()
  await expect(page).toHaveURL(savedPursuitUrl)
  await expect(page.getByRole('button', { name: new RegExp(projectName) })).toBeVisible()
  await expect(page.getByRole('heading', { name: manifest.account_name, exact: true })).toBeVisible()

  // Idempotency, a dropped task reply, and retry with the same client key.
  const duplicate = await page.evaluate(async needId => {
    const result = await fetch('/api/commercial-pursuits', { method: 'POST', credentials: 'same-origin', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ need_id: needId }) })
    return { status: result.status, body: await result.json() as { id: string } }
  }, manifest.second_page_need_id)
  expect(duplicate.status).toBe(200)
  expect(duplicate.body.id).toBe(pursuit.id)
  await page.goto(`/?view=pursuits&pursuit=${pursuit.id}`)
  await expect(page.getByRole('heading', { name: projectName })).toBeVisible()
  const taskInput = page.getByRole('textbox', { name: 'Follow-up description' })
  await taskInput.fill('Confirm synthetic project follow-up')
  const taskButton = page.getByRole('button', { name: 'Add follow-up' })
  await taskButton.click()
  await expect(page.getByRole('alert')).toContainText(/503|simulated lost response/i)
  await expect(taskInput).toHaveValue('Confirm synthetic project follow-up')
  await taskButton.click()
  await expect(page.getByText('Confirm synthetic project follow-up', { exact: true })).toBeVisible()
  expect(taskBodies).toHaveLength(2)
  expect(taskBodies[0].client_id).toMatch(/^[0-9a-f-]{36}$/i)
  expect(taskBodies[1].client_id).toBe(taskBodies[0].client_id)
  const retryDetail = await page.request.get(`/api/commercial-pursuits/${pursuit.id}`)
  const retryBody = await retryDetail.json() as { tasks: Array<{ id: string; description: string }> }
  expect(retryBody.tasks.filter(task => task.description === 'Confirm synthetic project follow-up')).toHaveLength(1)
  expect(retryBody.tasks.find(task => task.description === 'Confirm synthetic project follow-up')?.id).toBe(taskBodies[0].client_id)
  const persistedJourneyElapsedMs = Date.now() - start

  // Ten read-only warm iterations provide per-interaction samples on the
  // persisted 2,098-row corpus. These do not create further pursuits/tasks.
  await page.goto('/?view=workspace')
  await expect(page.getByRole('heading', { name: 'Commercial intelligence for constrained power.' })).toBeVisible()
  const accountNamePattern = new RegExp(manifest.account_name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  for (let iteration = 0; iteration < 10; iteration++) {
    await openProjectFilters(page)
    const listSearch = page.getByRole('textbox', { name: 'Search accounts and projects' })
    const resultStarted = Date.now()
    const resultWait = page.waitForResponse(async response => {
      const url = new URL(response.url())
      if (url.pathname !== '/api/opportunities/groups' || url.searchParams.get('search') !== manifest.account_name) return false
      if (!response.ok()) return true
      const body = await response.json() as { items: Array<{ name: string }> }
      return body.items.some(item => item.name === manifest.account_name)
    })
    await listSearch.fill(manifest.account_name)
    expect((await resultWait).status()).toBe(200)
    const warmCard = page.locator('.customer-group').filter({ hasText: manifest.account_name })
    await expect(warmCard).toHaveCount(1)
    recordInteraction('searchUntilAccountResultMs', Date.now() - resultStarted, true)

    const openStarted = Date.now()
    await warmCard.getByRole('button', { name: accountNamePattern }).click()
    await expect(page).toHaveURL(/account=cg_/)
    const warmAccount = page.getByRole('region', { name: new RegExp(`(?:Company|Group) ${manifest.account_name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`) })
    await expect(warmAccount.getByRole('region', { name: 'Account projects' })).toBeVisible()
    recordInteraction('accountOpenReadyMs', Date.now() - openStarted, true)

    const pageStarted = Date.now()
    const more = warmAccount.getByRole('button', { name: 'Load more projects' })
    await expect(more).toBeVisible()
    await more.click()
    await expect(warmAccount.locator(`[data-project-id="${manifest.second_page_project_id}"]`)).toBeVisible()
    recordInteraction('nestedPaginationReadyMs', Date.now() - pageStarted, true)

    const detailStartedWarm = Date.now()
    const warmProject = warmAccount.locator(`[data-project-id="${manifest.second_page_project_id}"]`)
    await warmProject.getByRole('button', { name: /Open project detail/ }).click()
    const warmDetail = page.getByRole('complementary', { name: 'Opportunity detail' })
    await expect(warmDetail).toBeVisible()
    await expect(warmDetail).toContainText(projectName)
    await expect(warmDetail.getByText('Loading current project details…')).toHaveCount(0)
    await expect(warmDetail.getByRole('alert')).toHaveCount(0)
    await expect(warmDetail.getByRole('button', { name: 'Add to Pursuit' }).or(warmDetail.getByRole('link', { name: 'In Pursuits' }))).toBeVisible()
    recordInteraction('projectDetailReadyMs', Date.now() - detailStartedWarm, true)
    await warmDetail.getByRole('button', { name: /Back to account/ }).click()
    await expect(warmAccount.getByRole('heading', { name: 'Projects' })).toBeVisible()
    await warmAccount.getByRole('button', { name: 'Back to accounts' }).click()
    await expect(page.getByRole('heading', { name: 'Commercial intelligence for constrained power.' })).toBeVisible()
    await openProjectFilters(page)
    await listSearch.fill('')
    await expect(page.locator('.project-results[aria-busy="true"]')).toHaveCount(0)
  }

  const companiesNavStarted = Date.now()
  await page.getByRole('button', { name: 'Companies' }).click()
  await expect(page.getByRole('heading', { name: 'Companies', exact: true })).toBeVisible()
  recordInteraction('companiesNavigationReadyMs', Date.now() - companiesNavStarted, true)
  const warmCompanySearch = page.getByRole('searchbox', { name: 'Search companies', exact: true })
  for (let iteration = 0; iteration < 10; iteration++) {
    const companySearchStarted = Date.now()
    const companyResults = page.waitForResponse(async response => {
      const url = new URL(response.url())
      if (url.pathname !== '/api/opportunities/groups' || url.searchParams.get('search') !== manifest.account_name) return false
      if (!response.ok()) return true
      const body = await response.json() as { items: Array<{ name: string }> }
      return body.items.some(item => item.name === manifest.account_name)
    })
    await warmCompanySearch.fill(manifest.account_name)
    expect((await companyResults).status()).toBe(200)
    const openCompany = page.getByRole('button', { name: new RegExp(`Open ${manifest.account_name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`) })
    await expect(openCompany).toBeVisible()
    recordInteraction('companiesSearchReadyMs', Date.now() - companySearchStarted, true)

    const companyOpenStarted = Date.now()
    await openCompany.click()
    const warmCompany = page.getByRole('region', { name: new RegExp(`(?:Company|Group) ${manifest.account_name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`) })
    await expect(warmCompany.getByRole('region', { name: 'Account projects' })).toBeVisible()
    recordInteraction('companiesAccountOpenReadyMs', Date.now() - companyOpenStarted, true)
    await warmCompany.getByRole('button', { name: /Back to companies/ }).click()
    await expect(page.getByRole('heading', { name: 'Companies', exact: true })).toBeVisible()
    const clearWait = page.waitForResponse(response => {
      const url = new URL(response.url())
      return url.pathname === '/api/opportunities/groups' && !url.searchParams.has('search')
    })
    await warmCompanySearch.fill('')
    await clearWait
  }

  const elapsed = Date.now() - start
  const sorted = durations.map(item => item.ms).sort((a, b) => a - b)
  const percentile = (p: number) => sorted.length ? sorted[Math.min(sorted.length - 1, Math.ceil(sorted.length * p) - 1)] : null
  const interactions = Object.fromEntries(Object.entries({ ...interactionTimes, ...interactionSamples }).map(([name]) => {
    const warm = (interactionSamples[name] ?? []).slice().sort((a, b) => a - b)
    const pick = (p: number) => warm.length ? warm[Math.min(warm.length - 1, Math.ceil(warm.length * p) - 1)] : null
    return [name, { initial_journey_ms: interactionTimes[name] ?? null, warm_n: warm.length, warm_p50_ms: pick(0.5), warm_p95_ms: pick(0.95), warm_samples_ms: warm }]
  }))
  const performance = {
    synthetic_fixture: true,
    corpus_rows: 2098,
    run_count: 1,
    repeated_read_only_iterations: 10,
    persistedJourneyElapsedMs,
    journeyPlusBenchmarkElapsedMs: elapsed,
    coldScope: 'first full shortlist render after authenticated session in a fresh browser context; server/PostgreSQL cache state unknown',
    warmScope: '10 read-only account and Companies interaction repeats in the same browser context and backend process',
    interaction_samples: interactions,
    initial_interaction_ms: interactionTimes,
    api_sample_count: durations.length,
    api_p50_ms: percentile(0.5),
    api_p95_ms: percentile(0.95),
    api_status_failures: responses.filter(item => item.status >= 500 && !(item.method === 'POST' && item.path.endsWith('/tasks') && item.status === 503)),
    api_samples: durations,
  }
  const output = process.env.PURSUITS_RELEASE_REAL_OUTPUT_DIR
  if (output) { await mkdir(output, { recursive: true }); await writeFile(`${output}/performance.json`, JSON.stringify(performance, null, 2) + '\n') }
  expect(performance.api_status_failures).toEqual([])
  expect([...external]).toEqual([])
})
