import { expect, test, type Page, type Route } from '@playwright/test'
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import type { PursuitsResult } from '../src/api/client'

const credentialPath = resolve(process.cwd(), '../.artifacts/local-auth.txt')
const password = process.env.GRIDLENS_TEST_PASSWORD ?? (existsSync(credentialPath) ? readFileSync(credentialPath, 'utf8').split(/\r?\n/)[1] : undefined)

async function signIn(page: import('@playwright/test').Page) {
  if (!password) throw new Error('Real database browser verification requires the existing private workspace password')
  await page.goto('/?view=pursuits')
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByRole('heading', { name: 'What should we work today?' })).toBeVisible()
}

async function openSavedResearch(page: import('@playwright/test').Page) {
  await page.getByText('Saved research workspace and call history').click()
  await expect(page.getByRole('heading', { name: "Today's Power Pursuits" })).toBeVisible()
}

test('real pursuits retain evidence gates and a saved owner call outcome across reload', async ({ page }) => {
  await expect((await page.request.get('/api/pursuits')).status()).toBe(401)
  await signIn(page)
  await openSavedResearch(page)
  const data = await page.evaluate(async () => (await fetch('/api/pursuits')).json() as Promise<PursuitsResult>)
  expect(data.items.length).toBeGreaterThan(0)
  expect(data.items.length).toBeLessThanOrEqual(10)
  const kramer = data.items.find(item => item.trigger.includes('800A') && item.site.includes('KRAMER'))
  expect(kramer, 'generic real ingestion must discover explicit Kramer scope').toBeTruthy()
  if (!kramer) throw new Error('Kramer challenge was not discovered by the app')
  expect(kramer.action_status).toBe('Call now')
  expect(kramer.tier).toBe('Signal')
  expect(kramer.people.every(person => person.purchasing_authority === 'Unknown')).toBe(true)
  expect(kramer.contacts.every(contact => contact.label.includes('routing'))).toBe(true)
  const card = page.locator(`[data-pursuit-id="${kramer.id}"]`)
  await card.locator('.pursuit-heading').click()
  await expect(card.getByText('Purchasing authority', { exact: true }).first()).toBeVisible()
  await expect(card.getByRole('link', { name: /Relationship evidence/ }).first()).toHaveAttribute('href', /^https:\/\//)
  const note = `Workflow validation only — no call placed. ${Date.now()}`
  await card.getByLabel('Call note', { exact: true }).fill(note)
  await card.getByRole('combobox', { name: 'Outcome', exact: true }).selectOption('Not reached')
  await card.getByLabel('Next action', { exact: true }).fill('Validation only: verify package owner before outreach')
  await card.getByLabel('Follow-up date', { exact: true }).fill('2026-10-02')
  await card.getByRole('button', { name: 'Save call outcome' }).click()
  await expect(card.getByText('Call outcome saved. Evidence tier unchanged.')).toBeVisible()
  await page.reload()
  await openSavedResearch(page)
  const restored = page.locator(`[data-pursuit-id="${kramer.id}"]`)
  await restored.locator('.pursuit-heading').click()
  await expect(restored.getByText(note, { exact: true })).toBeVisible()
  await expect(restored.getByText(/Follow-up 2026-10-02/).first()).toBeVisible()
  await expect(restored.locator('.pursuit-badges')).toContainText('Signal')
  await page.screenshot({ path: test.info().outputPath('real-pursuits-desktop.png'), fullPage: true })
})

test('real conflicts, bounded refresh and mobile pursuit history work in the app', async ({ page }) => {
  test.setTimeout(420_000) // Existing worker bounds one real-source batch to 350 seconds.
  await page.setViewportSize({ width: 390, height: 844 })
  await signIn(page)
  await openSavedResearch(page)
  const data = await page.evaluate(async () => (await fetch('/api/pursuits')).json() as Promise<PursuitsResult>)
  const clayton = data.items.find(item => item.site.includes('CLAYTON'))
  const stassney = data.items.find(item => item.site.includes('STASSNEY'))
  expect(clayton, 'live city/state conflict must be in saved pursuits').toBeTruthy()
  expect(stassney, 'live city/state manufacturing/office scope must be researched').toBeTruthy()
  if (!clayton || !stassney) throw new Error('Real conflict cases absent')
  expect(clayton.action_status).toBe('Verify first')
  expect(stassney.action_status).toBe('Verify first')
  expect(clayton.conflicts.some(value => value.includes('EV charging'))).toBe(true)
  expect(clayton.timing.every(value => !value.includes('12/31/2026'))).toBe(true)
  const card = page.locator(`[data-pursuit-id="${clayton.id}"]`)
  await card.locator('.pursuit-heading').click()
  await expect(card.getByRole('heading', { name: 'Conflicting evidence — verify first' })).toBeVisible()
  await expect(card.getByRole('heading', { name: 'Address-matched registrations · separate work context' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await card.screenshot({ path: test.info().outputPath('real-pursuits-mobile-conflict.png') })
  await page.getByRole('button', { name: 'Refresh pursuits', exact: true }).click()
  await expect(page.getByText(/Bounded source research is queued or running/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Refresh pursuits', exact: true })).toBeEnabled({ timeout: 360_000 })
  const after = await page.evaluate(async () => (await fetch('/api/pursuits')).json() as Promise<PursuitsResult>)
  expect(after.items.find(item => item.id === clayton.id)?.conflicts.length).toBeGreaterThan(0)
  await page.getByLabel('Include dropped pursuits and saved call history').check()
  await expect(page.getByRole('heading', { name: /saved records · page 1/ })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Next history page' })).toBeEnabled()
  const secondPageResponse = page.waitForResponse(response => response.url().includes('/api/pursuits?include_dropped=true&offset=10') && response.status() === 200)
  await page.getByRole('button', { name: 'Next history page' }).click()
  const secondPage = await (await secondPageResponse).json() as PursuitsResult
  await expect(page.getByRole('heading', { name: /saved records · page 2/ })).toBeVisible()
  await expect(page.getByText('Loading saved pursuits…')).not.toBeVisible()
  expect(secondPage.items.length).toBeGreaterThan(0)
  expect(secondPage.items[0].id).not.toBe(data.items[0].id)
  await expect(page.locator('.pursuit-card').first()).toHaveAttribute('data-pursuit-id', secondPage.items[0].id)
  await page.screenshot({ path: test.info().outputPath('real-pursuits-mobile.png'), fullPage: true })
})

const fixedTime = '2026-10-04T22:30:00Z'
const mockJob = (id: string, status: string, error: string | null = null) => ({ id, status, attempts: 0, error, created_at: fixedTime, checkpoint: null })
const savedPursuit = {
  id: 'saved-pursuit-1', project: 'Retained project', site: 'Austin, TX', organization: 'Unknown',
  organization_involvement: 'Unknown', action_status: 'Verify first', tier: 'Signal', trigger: 'Public project trigger',
  trigger_date: '2026-10-01', next_action: 'Verify source evidence', last_researched_at: null, last_attempt_at: null,
  research_status: 'UNKNOWN', research_errors: [], ranking_reasons: [], timing: [], load_facts: [], fuel_facts: [],
  utility_facts: [], people: [], contacts: [], registration_context: [], unknowns: ['Demand unknown'], conflicts: [],
  evidence: [], notes: [],
}
const pursuitsPayload = (jobs: ReturnType<typeof mockJob>[] = []) => ({
  items: [savedPursuit], total: 1, offset: 0, excluded_count: 0, jobs,
  usage: { fetch_requests_today: 0, daily_fetch_limit: 10, model_requests_today: 0, daily_model_limit: 10 },
  ranking_policy: 'Evidence-first', scheduler: 'A worker processes queued research.',
}) as unknown as PursuitsResult

async function installPursuitMocks(page: Page, handlers: {
  pursuits: (route: Route, requestIndex: number) => Promise<void>
  refresh: (route: Route) => Promise<void>
}) {
  let getIndex = 0
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/health', route => route.fulfill({ json: { sources: [], backlog: 0, pending_interpretations: 0 } }))
  await page.route('**/api/commercial/triage/history', route => route.fulfill({ json: { items: [] } }))
  await page.route('**/api/commercial/triage?limit=50', route => route.fulfill({ json: {
    evaluated_at: fixedTime, policy_version: 'test', total: 0, items: [],
    cohort_counts: { action_now: 0, research: 0, watch: 0, reject: 0 },
    daily: { evaluated: 0, surfaced: 0, contacted: 0 },
  } }))
  await page.route('**/api/pursuits/refresh*', route => handlers.refresh(route))
  await page.route(/\/api\/pursuits(?:\?.*)?$/, route => handlers.pursuits(route, ++getIndex))
  await page.goto('/?view=pursuits')
  await expect(page.getByRole('heading', { name: 'What should we work today?' })).toBeVisible()
  await page.getByText('Saved research workspace and call history').click()
  await expect(page.getByRole('heading', { name: "Today's Power Pursuits" })).toBeVisible()
  await expect(page.getByText('Retained project')).toBeVisible()
}

test('accepted refresh survives a GET longer than the polling interval and reconciles serially', async ({ page }) => {
  test.setTimeout(30_000)
  const jobId = 'accepted-job-1'
  let postCount = 0
  let acceptedGets = 0
  let accepted = false
  let releaseFirst!: () => void
  const firstGetBlocked = new Promise<void>(resolve => { releaseFirst = resolve })
  let firstGetStarted!: () => void
  const firstGetStartedSignal = new Promise<void>(resolve => { firstGetStarted = resolve })
  let releaseTerminal!: () => void
  const terminalGetBlocked = new Promise<void>(resolve => { releaseTerminal = resolve })
  let terminalGetStarted!: () => void
  const terminalGetStartedSignal = new Promise<void>(resolve => { terminalGetStarted = resolve })
  await installPursuitMocks(page, {
    refresh: async route => {
      postCount += 1
      accepted = true
      await route.fulfill({ json: mockJob(jobId, 'queued') })
    },
    pursuits: async (route) => {
      if (!accepted) return route.fulfill({ json: pursuitsPayload() })
      const index = ++acceptedGets
      if (index === 1) {
        firstGetStarted()
        await firstGetBlocked
        return route.fulfill({ json: pursuitsPayload([mockJob(jobId, 'running')]) })
      }
      if (index === 2) {
        terminalGetStarted()
        await terminalGetBlocked
        return route.fulfill({ json: pursuitsPayload([mockJob(jobId, 'succeeded')]) })
      }
      return route.fulfill({ json: pursuitsPayload([mockJob(jobId, 'running')]) })
    },
  })

  const refreshButton = page.locator('button.pursuit-refresh')
  await refreshButton.click()
  await expect(page.getByText(/Refresh was accepted; status confirmation is pending/)).toBeVisible()
  await expect(refreshButton).toBeDisabled()
  await firstGetStartedSignal
  await page.waitForTimeout(3_500)
  expect(acceptedGets).toBe(1)
  expect(postCount).toBe(1)
  await expect(page.getByText('Retained project')).toBeVisible()

  releaseFirst()
  await expect(page.getByText(/research is still running/)).toBeVisible()
  await terminalGetStartedSignal
  await page.waitForTimeout(3_500)
  expect(acceptedGets).toBe(2)
  expect(postCount).toBe(1)
  releaseTerminal()
  await expect(refreshButton).toBeEnabled({ timeout: 5_000 })
  expect(postCount).toBe(1)
})

test('accepted refresh remains UNKNOWN after failed or missing GET and clears only on matching terminal job', async ({ page }) => {
  test.setTimeout(30_000)
  const jobId = 'accepted-job-2'
  let postCount = 0
  let accepted = false
  let acceptedGets = 0
  let releaseMissingGet!: () => void
  const missingGetFinished = new Promise<void>(resolve => { releaseMissingGet = resolve })
  let releaseTerminalGet!: () => void
  const terminalGetFinished = new Promise<void>(resolve => { releaseTerminalGet = resolve })
  let releaseTerminalResponse!: () => void
  const terminalResponseBlocked = new Promise<void>(resolve => { releaseTerminalResponse = resolve })
  let signalTerminalStarted!: () => void
  const terminalGetStarted = new Promise<void>(resolve => { signalTerminalStarted = resolve })
  await installPursuitMocks(page, {
    refresh: async route => {
      postCount += 1
      accepted = true
      await route.fulfill({ json: mockJob(jobId, 'queued') })
    },
    pursuits: async (route) => {
      if (!accepted) return route.fulfill({ json: pursuitsPayload() })
      const index = ++acceptedGets
      if (index === 1) return route.fulfill({ status: 503, json: { detail: 'temporary status failure' } })
      if (index === 2) {
        await route.fulfill({ json: pursuitsPayload() })
        releaseMissingGet()
        return
      }
      signalTerminalStarted()
      await terminalResponseBlocked
      await route.fulfill({ json: pursuitsPayload([mockJob(jobId, 'failed', 'source unavailable')]) })
      releaseTerminalGet()
    },
  })

  const refreshButton = page.locator('button.pursuit-refresh')
  await refreshButton.click()
  await missingGetFinished
  await expect(page.getByText(/status is UNKNOWN or temporarily unavailable/)).toBeVisible()
  await expect(refreshButton).toBeDisabled()
  await expect.poll(() => postCount).toBe(1)
  await terminalGetStarted
  await expect(page.getByText(/status is UNKNOWN or temporarily unavailable/)).toBeVisible()
  await expect(refreshButton).toBeDisabled()
  releaseTerminalResponse()
  await terminalGetFinished
  await expect(page.getByRole('alert').filter({ hasText: /Research job failed: source unavailable/ })).toBeVisible()
  await expect(refreshButton).toBeEnabled()
  expect(postCount).toBe(1)
})

test('failed refresh POST does not create an accepted pending receipt', async ({ page }) => {
  let postCount = 0
  await installPursuitMocks(page, {
    refresh: async route => {
      postCount += 1
      await route.fulfill({ status: 503, json: { detail: 'queue unavailable' } })
    },
    pursuits: async route => route.fulfill({ json: pursuitsPayload() }),
  })
  const refreshButton = page.locator('button.pursuit-refresh')
  await refreshButton.click()
  await expect(page.getByRole('alert').filter({ hasText: /GridLens could not complete this request \(503\)/ })).toBeVisible()
  await expect(page.getByText(/Refresh was accepted/)).toHaveCount(0)
  await expect(refreshButton).toBeEnabled()
  await expect(page.getByText('Retained project')).toBeVisible()
  expect(postCount).toBe(1)
})
