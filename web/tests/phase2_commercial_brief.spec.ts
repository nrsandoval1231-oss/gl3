import { expect, test, type Page } from '@playwright/test'
import { readFileSync, mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
import type { OpportunityGroup } from '../src/api/client'

type Manifest = {
  schema_version: 'phase2-browser-v1'
  synthetic_fixture: true
  db_name: string
  fixture_input_sha256: string
  source_commit: string
  account: { company_identity_id: string; name: string; group_id: string; projects: Array<{ id: string; name: string }>; need_ids: string[] }
  lookalike_account: { company_identity_id: string; name: string }
  featured: { project_id: string; need_id: string }
  contact_source_need_id?: string | null
  source: { title: string; url: string; evidence_id: string; content_hash: string; event_date: string | null }
  brief: {
    why_now_text: string
    why_now_source_date: string | null
    why_now_scope: string | null
    power_amount_class: string
    power_value: string | null
    power_unit: string | null
    power_scope: string | null
    power_limitations?: string[]
    best_contact_label: string
    best_contact_href: string
    best_contact_kind: string
    best_contact_route_kind: string
    best_contact_authority: string
    best_contact_deliverability: string
    next_action: string
    freshness_status: string
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
  expect(manifest.account.projects.length).toBeGreaterThanOrEqual(3)
  expect(manifest.account.need_ids.length).toBeGreaterThanOrEqual(4)
  expect(manifest.brief.why_now_text).toBeTruthy()
  expect(manifest.brief.best_contact_href).toBeTruthy()
  expect(manifest.brief.next_action).toBeTruthy()
  if (manifest.contact_source_need_id != null) {
    expect(manifest.contact_source_need_id).toBe(manifest.featured.need_id)
    expect(manifest.account.need_ids).toContain(manifest.contact_source_need_id)
  }
  return manifest
}

async function signIn(page: Page) {
  if (!password) throw new Error('Set GRIDLENS_TEST_PASSWORD to the private password for the disposable test API.')
  await page.goto('/?view=workspace&groupBrowse=1&shortlist=1')
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
  await expect(account).toContainText(manifest.brief.why_now_text)
  await expect(account).toContainText(manifest.brief.best_contact_label)
  await expect(account).toContainText(manifest.brief.next_action)
  const brief = account.locator('.customer-commercial-brief')
  await expect(brief.getByRole('link', { name: new RegExp(escapeRegExp(manifest.brief.best_contact_label), 'i') })).toHaveAttribute('href', manifest.brief.best_contact_href)
  await expect(brief.getByRole('heading', { name: 'Best contact' })).toHaveCount(0)
  await expect(brief.locator('details.customer-brief-sources')).not.toHaveAttribute('open', '')
  const sourceDisclosure = brief.locator('details.customer-brief-sources')
  await expect(sourceDisclosure).toContainText(manifest.source.title)
  await sourceDisclosure.locator('summary').click()
  const sourceLinks = sourceDisclosure.getByRole('link')
  const retainedSource = sourceLinks.getByText(manifest.source.title, { exact: true })
  await expect(retainedSource).toHaveAttribute('href', manifest.source.url)
  for (const href of await sourceLinks.evaluateAll(links => links.map(link => (link as HTMLAnchorElement).href))) {
    expect(new URL(href).protocol).toMatch(/^https?:$/)
  }
  await sourceDisclosure.locator('summary').click()
  await expect(sourceDisclosure).not.toHaveAttribute('open', '')
  const powerClaim = brief.locator('.customer-brief-claim').filter({ hasText: 'Power need' })
  const informativePowerLimitations = (manifest.brief.power_limitations ?? []).filter(value => !/unknown is not zero|unknown does not mean zero|power need is unknown|power amount is unknown/i.test(value))
  if (manifest.brief.power_amount_class === 'unknown' || !manifest.brief.power_value) {
    if (manifest.brief.power_scope && informativePowerLimitations.length) {
      await expect(powerClaim).toContainText(manifest.brief.power_scope)
      for (const limitation of informativePowerLimitations) await expect(powerClaim).toContainText(limitation)
      const visiblePowerText = await powerClaim.innerText()
      if (/\b40\s*MW\b/i.test(visiblePowerText)) {
        expect(visiblePowerText).toMatch(/40\s*MW.{0,100}campus nameplate/i)
        expect(visiblePowerText).toMatch(/(?:not|does not|doesn't).{0,40}rental load/i)
      }
    } else {
      await expect(powerClaim).toHaveCount(0)
    }
  } else {
    expect(manifest.brief.power_scope, 'quantified power retains a scoped basis').toBeTruthy()
    await expect(powerClaim).toContainText(manifest.brief.power_scope!)
    const amount = manifest.brief.power_unit ? `${manifest.brief.power_value} ${manifest.brief.power_unit}` : manifest.brief.power_value
    await expect(powerClaim).toContainText(amount)
    const classLabel = manifest.brief.power_amount_class.replaceAll('_', ' ').replace(/\b[a-z]/g, character => character.toUpperCase())
    await expect(powerClaim).toContainText(classLabel)
  }

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
  for (const project of manifest.account.projects) await expect(detail).toContainText(project.name)
  await page.goBack()
  await expect(page).toHaveURL(/groupBrowse=1/)
  await expect(page.getByRole('textbox', { name: 'Search accounts and projects' })).toHaveValue(manifest.account.name)
  await page.goForward()
  await expect(page).toHaveURL(new RegExp(`[?&]account=${escapeRegExp(manifest.account.group_id)}(?:&|$)`))

  const opened = await page.request.get(`/api/opportunities/groups/${encodeURIComponent(manifest.account.group_id)}/open`)
  expect(opened.ok()).toBeTruthy()
  const openedBody = await opened.json() as { projects?: { items?: Array<{ id?: string; project_id?: string }> } }
  const returnedProjects = openedBody.projects?.items ?? []
  const returnedIds = new Set(returnedProjects.map(project => project.project_id ?? project.id))
  for (const project of manifest.account.projects) expect(returnedIds.has(project.id), `distinct project ${project.id} remains in account detail`).toBe(true)
  for (const project of manifest.account.projects) {
    await expect(detail).toContainText(project.name)
  }

  const readSamples: { status: number; elapsed_ms: number }[] = []
  for (let i = 0; i < 5; i += 1) {
    const start = performance.now()
    const response = await page.request.get('/api/opportunities/groups?sector=all&search=' + encodeURIComponent(manifest.account.name) + '&limit=25&offset=0')
    readSamples.push({ status: response.status(), elapsed_ms: Math.round((performance.now() - start) * 100) / 100 })
    expect(response.ok()).toBeTruthy()
    const body = await response.json() as { items: OpportunityGroup[] }
    const found = body.items.find(item => item.id === manifest.account.group_id)
    expect(found, 'account group is present in live API response').toBeTruthy()
    expect(found?.featured_project?.commercial_brief?.why_now?.text).toBe(manifest.brief.why_now_text)
    expect(found?.featured_project?.commercial_brief?.power_need?.scope ?? null).toBe(manifest.brief.power_scope)
    expect(found?.featured_project?.commercial_brief?.power_need?.value ?? null).toBe(manifest.brief.power_value)
    if (manifest.contact_source_need_id) {
      const selectedNeed = found?.featured_project?.needs?.find(need => need.id === manifest.contact_source_need_id)
      expect(selectedNeed?.commercial_brief?.best_contact?.href).toBe(manifest.brief.best_contact_href)
    } else {
      expect(found?.featured_project?.commercial_brief?.best_contact?.href).toBe(manifest.brief.best_contact_href)
    }
  }
  await testInfo.attach('phase2-read-latency.json', { body: JSON.stringify({ read_count: readSamples.length, reads: readSamples }, null, 2), contentType: 'application/json' })
  await page.getByRole('navigation', { name: 'Primary navigation' }).getByRole('button', { name: 'Pursuits' }).click()
  await expect(page.getByRole('heading', { name: 'Pursuits', exact: true })).toBeVisible()
  await page.getByRole('navigation', { name: 'Primary navigation' }).getByRole('button', { name: 'Opportunities' }).click()
  await expect(page.getByRole('heading', { name: 'Customer accounts', exact: true })).toBeVisible()
  await page.locator('.wh-account > summary').click()
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
  expect(await (await page.request.get('/api/auth/session')).json()).toEqual({ authenticated: false })
  await expect(page.getByText(manifest.brief.why_now_text, { exact: true })).toHaveCount(0)
  expect(browserWrites).toEqual([])
})

function escapeRegExp(value: string): string { return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') }
