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
    observed_at: stamp, verified_at: stamp, stale: false, correction_stale: false, retracted: false, history_count: 1,
    correction_version: 'v1',
    public_contacts: [], evidence: [{
      id: 'evidence-1', url: 'https://example.com/project', quote: 'Test Electrical is the electrical contractor.',
      supports: 'project_organization', extraction_location: 'contractor field',
      published_at: null, observed_at: stamp, content_hash: 'fixture-hash',
    }, {
      id: 'contact-evidence', url: 'https://example.com/contact', quote: 'Business contact: +1 312 555 0100',
      supports: 'public_contact', extraction_location: 'current contact page',
      published_at: null, observed_at: stamp, content_hash: 'b'.repeat(64),
    }],
  }],
})

async function shell(page: import('@playwright/test').Page, buying: (route: import('@playwright/test').Route) => Promise<void>) {
  await page.route(apiRoute, async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.includes('/buying-chain')) { await buying(route); return }
    const body = path === '/api/auth/session' ? { authenticated: true }
      : path === '/api/opportunities/needs/one' ? project('one')
        : path === '/api/opportunities/needs/two' ? project('two')
      : path === '/api/opportunities' ? [project('one'), project('two')]
      : path === '/api/health' ? { sources: [], backlog: 0, pending_interpretations: 0 }
        : []
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/?tier=Signals')
  await page.getByRole('button', { name: /Test facility one/ }).click()
  await page.getByRole('button', { name: 'Buying Chain', exact: true }).click()
}













test('mobile buying chain keeps unknown and empty results readable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await shell(page, async (route) => {
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ...chain('one'), candidates: [], status: 'unresolved' }) })
  })
  await expect(page.getByText('No supported buying-chain candidates retained yet. Buyer and project contacts remain unknown.')).toBeVisible()
  await expect(page.getByRole('button', { name: /enrich buying chain|correct or retract contact/i })).toHaveCount(0)
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
  await expect(page.getByText('Evidence assessed 9/30/2026')).toBeVisible()
  await expect(page.getByText('Data center conversion with MEP upgrades', { exact: true })).toBeVisible()
  await expect(page.getByText('DOE, JANE', { exact: true })).toBeVisible()
  await page.getByText('Field evidence', { exact: true }).nth(1).click()
  await expect(page.getByText('contact_2_type: ARCHITECT', { exact: true })).toBeVisible()
  await expect(page.getByText(/Permit dates describe permitting/)).toBeVisible()
})
