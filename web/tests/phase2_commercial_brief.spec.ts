import { expect, test, type Page } from '@playwright/test'
import { readFileSync, mkdirSync } from 'node:fs'
import { resolve } from 'node:path'

type Manifest = {
  schema_version: 'phase2-browser-v1'
  synthetic_fixture: true
  db_name: string
  fixture_input_sha256: string
  source_commit: string
  account: { company_identity_id: string; name: string; group_id: string; project_ids: string[]; project_names: string[]; need_ids: string[] }
  lookalike_account: { company_identity_id: string; name: string }
  expected: {
    why_now: string
    contact_label: string
    contact_href: string
    next_action: string
    power_amount_class: string
    power_scope: string
  }
}

const manifestPath = process.env.GRIDLENS_PHASE2_MANIFEST
const password = process.env.GRIDLENS_TEST_PASSWORD

function loadManifest(): Manifest {
  if (!manifestPath) throw new Error('Set GRIDLENS_PHASE2_MANIFEST to the private output manifest for the disposable phase 2 fixture.')
  const manifest = JSON.parse(readFileSync(resolve(manifestPath), 'utf8')) as Manifest
  expect(manifest.schema_version).toBe('phase2-browser-v1')
  expect(manifest.synthetic_fixture).toBe(true)
  expect(manifest.db_name).toMatch(/^gl3_phase2_browser_fixture_test$/)
  expect(manifest.fixture_input_sha256).toMatch(/^[a-f0-9]{64}$/i)
  expect(manifest.account.project_ids.length).toBeGreaterThanOrEqual(3)
  expect(manifest.account.project_names.length).toBe(manifest.account.project_ids.length)
  expect(manifest.account.need_ids.length).toBeGreaterThanOrEqual(4)
  return manifest
}

async function signIn(page: Page) {
  if (!password) throw new Error('Set GRIDLENS_TEST_PASSWORD to the private password for the disposable test API.')
  await page.goto('/?view=workspace&groupBrowse=1&shortlist=0')
  await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Customer accounts', exact: true })).toBeVisible()
}

test('source-backed disposable account brief survives responsive navigation and remains read-only', async ({ page }, testInfo) => {
  const manifest = loadManifest()
  const browserWrites: string[] = []
  page.on('request', request => {
    const method = request.method().toUpperCase()
    const url = new URL(request.url())
    if (url.pathname.startsWith('/api/') && !['GET', 'HEAD', 'OPTIONS'].includes(method) && url.pathname !== '/api/auth/login' && url.pathname !== '/api/auth/logout') {
      browserWrites.push(`${method} ${url.pathname}`)
    }
  })

  await signIn(page)
  const search = page.getByRole('textbox', { name: 'Search accounts and projects' })
  await search.fill(manifest.account.name)
  const account = page.getByRole('region', { name: new RegExp(`${escapeRegExp(manifest.account.name)} customer group`, 'i') })
  await expect(account).toBeVisible()
  await expect(account).toContainText(manifest.expected.why_now)
  await expect(account).toContainText(manifest.expected.contact_label)
  await expect(account).toContainText(manifest.expected.next_action)
  const brief = account.locator('.customer-commercial-brief')
  await expect(brief.getByRole('link', { name: new RegExp(escapeRegExp(manifest.expected.contact_label), 'i') })).toHaveAttribute('href', manifest.expected.contact_href)
  await expect(brief.getByRole('heading', { name: 'Best contact' })).toHaveCount(0)
  await expect(brief.locator('details.customer-brief-sources')).not.toHaveAttribute('open', '')
  const sourceDisclosure = brief.locator('details.customer-brief-sources')
  await expect(sourceDisclosure).toContainText(/Sources \(\d+\)/)
  await sourceDisclosure.locator('summary').click()
  const sourceLinks = sourceDisclosure.getByRole('link')
  await expect(sourceLinks.first()).toBeVisible()
  for (const href of await sourceLinks.evaluateAll(links => links.map(link => (link as HTMLAnchorElement).href))) {
    expect(new URL(href).protocol).toMatch(/^https?:$/)
  }
  await sourceDisclosure.locator('summary').click()
  await expect(sourceDisclosure).not.toHaveAttribute('open', '')
  expect(manifest.expected.power_amount_class).toBeTruthy()
  expect(manifest.expected.power_scope).toBeTruthy()
  await expect(brief).toContainText(manifest.expected.power_scope)
  await expect(brief).toContainText(/documented|calculated|estimated|inferred|unknown/i)

  // Capture the same real API-backed customer card at the five agreed viewports.
  const viewports = [
    { width: 1648, height: 928 }, { width: 1440, height: 900 }, { width: 1280, height: 800 },
    { width: 768, height: 1024 }, { width: 390, height: 844 },
  ]
  const screenshotDir = resolve(testInfo.outputDir, 'phase2-viewports')
  mkdirSync(screenshotDir, { recursive: true })
  for (const viewport of viewports) {
    await page.setViewportSize(viewport)
    await expect(account).toBeVisible()
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
    expect(overflow, `horizontal overflow at ${viewport.width}px`).toBe(false)
    await page.screenshot({ path: resolve(screenshotDir, `${viewport.width}x${viewport.height}.png`), fullPage: true })
  }

  // Open account detail, verify separate projects, and exercise browser history.
  await account.getByRole('button', { name: /Choose opportunity|View account details/ }).click()
  await expect(page).toHaveURL(new RegExp(`[?&]account=${escapeRegExp(manifest.account.group_id)}(?:&|$)`))
  const detail = page.getByRole('region', { name: 'Account projects' })
  for (const projectName of manifest.account.project_names) await expect(detail).toContainText(projectName)
  await page.goBack()
  await expect(page).toHaveURL(/groupBrowse=1/)
  await expect(page.getByRole('textbox', { name: 'Search accounts and projects' })).toHaveValue(manifest.account.name)
  await page.goForward()
  await expect(page).toHaveURL(new RegExp(`[?&]account=${escapeRegExp(manifest.account.group_id)}(?:&|$)`))

  const opened = await page.request.get(`/api/opportunities/groups/${encodeURIComponent(manifest.account.group_id)}/open`)
  expect(opened.ok()).toBeTruthy()
  const openedBody = await opened.json() as { projects?: { items?: Array<{ id?: string; project_id?: string; name?: string }> } }
  const returnedProjects = openedBody.projects?.items ?? []
  const returnedIds = new Set(returnedProjects.map(project => project.project_id ?? project.id))
  for (const projectId of manifest.account.project_ids) expect(returnedIds.has(projectId), `distinct project ${projectId} remains in account detail`).toBe(true)
  const returnedNames = new Set(returnedProjects.map(project => project.name))
  for (const projectName of manifest.account.project_names) expect(returnedNames.has(projectName), `distinct project ${projectName} is present`).toBe(true)

  const readSamples: { status: number; elapsed_ms: number }[] = []
  for (let i = 0; i < 5; i += 1) {
    const start = performance.now()
    const response = await page.request.get('/api/opportunities/groups?sector=all&search=' + encodeURIComponent(manifest.account.name) + '&limit=25&offset=0')
    readSamples.push({ status: response.status(), elapsed_ms: Math.round((performance.now() - start) * 100) / 100 })
    expect(response.ok()).toBeTruthy()
    const body = await response.json() as { items: Array<{ id: string; name: string; featured_project?: { commercial_brief?: { why_now?: { text?: string | null } } | null } }> }
    const found = body.items.find(item => item.id === manifest.account.group_id)
    expect(found, 'account group is present in live API response').toBeTruthy()
    expect(found?.featured_project?.commercial_brief?.why_now?.text).toBe(manifest.expected.why_now)
  }
  await testInfo.attach('phase2-read-latency.json', { body: JSON.stringify({ read_count: readSamples.length, reads: readSamples }, null, 2), contentType: 'application/json' })
  await page.getByRole('navigation', { name: 'Primary navigation' }).getByRole('button', { name: 'Pursuits' }).click()
  await expect(page.getByRole('heading', { name: 'Pursuits', exact: true })).toBeVisible()
  expect(browserWrites).toEqual([])
})

function escapeRegExp(value: string): string { return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') }
