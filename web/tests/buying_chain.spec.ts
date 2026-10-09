import { expect, test } from '@playwright/test'
import type { BuyingChainResult, Opportunity } from '../src/api/client'

const apiRoute = `http://127.0.0.1:${process.env.GRIDLENS_WEB_PORT ?? '5173'}/api/**`
const stamp = '2026-09-30T12:00:00Z'
const project = (id: string): Opportunity => ({
  id, project_id: id, name: `Test facility ${id}`, location: 'Chicago, IL', tier: 'Signal',
  workflow_status: 'UNKNOWN',
  activity: 'construction', rationale: 'A test-only sourced construction event.',
  brief_status: 'unavailable', brief_stale: false,
  required_mw: null, start_window: null, duration: null, supply: 'Unknown',
  next_action: 'Confirm temporary power procurement.', conflict_state: 'Not assessed',
  signal_display_decision: 'SHOW', signal_display_decision_state: 'adjudicated', signal_evidence_state: 'active_evidence', evidence: [],
})
const chain = (id: string): BuyingChainResult => ({
  project_id: id, status: 'complete', policy_version: 'buying-chain-v1',
  unresolved: ['Temporary power purchasing authority remains UNKNOWN.'], runs: [],
  candidates: [{
    id: `candidate-${id}`, organization: `Test Electrical ${id}`, person_name: 'Test Person',
    title: 'Director of Construction', category: 'electrical_contractor',
    organization_relationship: 'DIRECT', person_organization_relationship: 'CURRENT',
    person_project_relationship: 'ROLE_SUPPORTED', evidence_strength: 'Medium',
    reason: 'Test fixture: employer involved, current relevant role, no personal assignment evidence.',
    observed_at: stamp, verified_at: stamp, stale: false, history_count: 1,
    public_contacts: [], evidence: [{
      id: 'evidence-1', url: 'https://example.com/project', quote: 'Test Electrical is the electrical contractor.',
      supports: 'project_organization', extraction_location: 'contractor field',
      published_at: null, observed_at: stamp, content_hash: 'fixture-hash',
    }],
  }],
})

function emptyExactNeedAuxiliary(path: string) {
  const facts = path.match(/^\/api\/needs\/([^/]+)\/facts$/)
  if (facts) {
    return {
      items: [], total: 0, limit: 50, offset: 0, next_offset: null, current_fact_version: 0,
      current_reported_timing_correction_target: {
        available: false, unavailable_reason: 'no_current_admitted_lead', need_id: facts[1],
        project_id: null, project_identity_key: null, activity_key: null, facility_identity: null,
        source_semantic_hash: null, source_evidence_hash: null, retained_evidence_id: null,
        source_id: null, earliest_possible_start: null, latest_possible_start: null,
        minimum_duration_days: null, maximum_duration_days: null, current_fact_version: 0,
      },
    }
  }
  if (/^\/api\/needs\/[^/]+\/workflow-status$/.test(path)) {
    return { status: 'UNKNOWN', version: 0, events: [] }
  }
  return undefined
}

async function shell(page: import('@playwright/test').Page, buying: (route: import('@playwright/test').Route) => Promise<void>) {
  await page.route(apiRoute, async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.includes('/buying-chain')) { await buying(route); return }
    const body = path === '/api/auth/session' ? { authenticated: true }
      : path === '/api/opportunities' ? [project('one'), project('two')]
      : path === '/api/health' ? { sources: [], backlog: 0, pending_interpretations: 0 }
        : emptyExactNeedAuxiliary(path) ?? []
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/?tier=Signals')
  await page.getByRole('button', { name: /Test facility one/ }).click()
}

test('buying chain exposes three separate relationships and retains evidence after enrichment failure', async ({ page }) => {
  let posts = 0
  await shell(page, async (route) => {
    if (route.request().method() === 'POST') {
      posts += 1
      await route.fulfill({ status: 503, body: 'unavailable' })
    } else await route.fulfill({ contentType: 'application/json', body: JSON.stringify(chain('one')) })
  })
  const section = page.getByRole('region', { name: 'Buying chain' })
  await expect(section.getByRole('heading', { name: 'Test Electrical one' })).toBeVisible()
  await expect(section.getByText('Project → organization')).toBeVisible()
  await expect(section.getByText('Organization → person')).toBeVisible()
  await expect(section.getByText('Person → project')).toBeVisible()
  await expect(section.getByText('Role-supported · project assignment unknown', { exact: true })).toBeVisible()
  await expect(section.getByText('Public business contact details unknown')).toBeVisible()
  await section.getByText('Inspect relationship evidence (1)').click()
  await expect(section.getByText('Test Electrical is the electrical contractor.')).toBeVisible()
  await section.getByRole('button', { name: 'Enrich buying chain' }).click()
  await expect(section.getByRole('alert')).toContainText('Previously retained findings remain below')
  await expect(section.getByRole('heading', { name: 'Test Electrical one' })).toBeVisible()
  expect(posts).toBe(1)
})

test('navigation ignores a late enrichment result and limits repeated requests', async ({ page }) => {
  let finish: (() => void) | undefined
  let posts = 0
  const release = new Promise<void>((resolve) => { finish = resolve })
  await shell(page, async (route) => {
    const id = route.request().url().includes('/one/') ? 'one' : 'two'
    if (route.request().method() === 'POST') { posts += 1; await release }
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(chain(id)) })
  })
  const button = page.getByRole('button', { name: 'Enrich buying chain' })
  await expect(button).toBeEnabled()
  await button.click()
  await expect(page.getByRole('button', { name: 'Checking evidence…' })).toBeDisabled()
  await page.getByRole('button', { name: 'Next →' }).click()
  await expect(page.getByRole('heading', { name: 'Test Electrical two' })).toBeVisible()
  const finished = page.waitForResponse((response) => response.request().method() === 'POST' && response.url().includes('/buying-chain/enrich'))
  finish!()
  await finished
  await expect(page.getByRole('heading', { name: 'Test Electrical one' })).toHaveCount(0)
  expect(posts).toBe(1)
  await page.getByRole('button', { name: /Back to Signals/ }).click()
  await expect(page.getByRole('button', { name: /Test facility one/ })).toBeVisible()
  await page.goForward()
  await expect(page.getByRole('heading', { name: 'Test Electrical two' })).toBeVisible()
})

test('mobile buying chain keeps unknown and empty results readable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await shell(page, async (route) => {
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ...chain('one'), candidates: [], status: 'unresolved' }) })
  })
  await expect(page.getByText('No supported buying-chain candidates retained yet. Buyer and project contacts remain unknown.')).toBeVisible()
  await expect(page.getByText('Temporary power purchasing authority remains UNKNOWN.')).toBeVisible()
  await page.getByText('Add supporting source links').click()
  await page.getByRole('textbox', { name: 'Public project or organization sources (up to four)' }).fill('http://127.0.0.1/private')
  await page.getByRole('button', { name: 'Enrich buying chain' }).click()
  await expect(page.getByRole('alert')).toHaveText('Use up to four public HTTPS source links, one per line.')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
})

test('retained permit fields are useful before enrichment and preserve source roles', async ({ page }) => {
  const result = chain('one')
  result.permit_summaries = [{
    evidence_id: 'permit-1', source_id: 'chicago-building-permits',
    url: 'https://data.cityofchicago.org/resource/ydr8-5enu.json',
    title: 'Synthetic data-center permit', observed_at: stamp,
    extraction_location: 'Official Chicago permit fields',
    facts: [
      { label: 'Permit scope', value: 'Data center conversion with MEP upgrades', quote: 'description: Data center conversion with MEP upgrades' },
      { label: 'Permit-listed party · ARCHITECT', value: 'DOE, JANE', quote: 'contact_2_name: DOE, JANE', role_quote: 'contact_2_type: ARCHITECT' },
      { label: 'Application start date', value: '2026-06-17', quote: 'application_start: 2026-06-17' },
    ],
  }]
  await shell(page, async (route) => {
    expect(route.request().method()).toBe('GET')
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(result) })
  })
  await expect(page.getByRole('heading', { name: 'Retained permit facts' })).toBeVisible()
  await expect(page.getByText('Data center conversion with MEP upgrades', { exact: true })).toBeVisible()
  await expect(page.getByText('DOE, JANE', { exact: true })).toBeVisible()
  await page.getByText('Field evidence', { exact: true }).nth(1).click()
  await expect(page.getByText('contact_2_type: ARCHITECT', { exact: true })).toBeVisible()
  await expect(page.getByText(/Permit dates describe permitting/)).toBeVisible()
})
