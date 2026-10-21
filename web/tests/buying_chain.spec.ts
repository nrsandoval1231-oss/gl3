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
      : path === '/api/opportunities/needs/one' ? project('one')
        : path === '/api/opportunities/needs/two' ? project('two')
      : path === '/api/opportunities' ? [project('one'), project('two')]
      : path === '/api/health' ? { sources: [], backlog: 0, pending_interpretations: 0 }
        : emptyExactNeedAuxiliary(path) ?? []
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/?tier=Signals')
  await page.getByRole('button', { name: /Test facility one/ }).click()
  await page.getByRole('button', { name: 'Buying chain', exact: true }).click()
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
  await page.getByRole('button', { name: /Test facility two/ }).click()
  await page.getByRole('complementary', { name: 'Opportunity detail' }).getByRole('button', { name: 'Buying chain', exact: true }).click()
  const selectedChain = page.getByRole('region', { name: 'Buying chain' })
  await expect(selectedChain.getByRole('heading', { name: 'Test Electrical two' })).toBeVisible()
  const finished = page.waitForResponse((response) => response.request().method() === 'POST' && response.url().includes('/buying-chain/enrich'))
  finish!()
  await finished
  await expect(selectedChain.getByRole('heading', { name: 'Test Electrical two' })).toBeVisible()
  await expect(selectedChain.getByRole('heading', { name: 'Test Electrical one' })).toHaveCount(0)
  expect(posts).toBe(1)
  await page.goBack()
  await expect(page.getByRole('region', { name: 'Buying chain' }).getByRole('heading', { name: 'Test Electrical one' })).toBeVisible()
  await page.goForward()
  await expect(page.getByRole('region', { name: 'Buying chain' }).getByRole('heading', { name: 'Test Electrical two' })).toBeVisible()
})

test('contact correction surfaces 409, verifies history read-back and retracts the project claim', async ({ page }) => {
  let version = 'v1'
  let staleOnce = true
  let retracted = false
  const history: Array<{ id: string; action: string; reason: string; created_at: string }> = []
  await shell(page, async (route) => {
    const request = route.request()
    if (request.method() === 'POST') {
      const body = request.postDataJSON() as { expected_version: string; action: string; reported_contact: boolean }
      if (staleOnce) {
        staleOnce = false
        version = 'v2'
        await route.fulfill({ status: 409, body: 'Claim changed; review current history.' })
        return
      }
      expect(body.expected_version).toBe(version)
      version = body.action === 'retract' ? 'v4' : 'v3'
      retracted = body.action === 'retract'
      history.push({ id: `correction-${history.length + 1}`, action: body.action, reason: 'Confirmed with project team', created_at: stamp })
      await route.fulfill({ json: { id: history.at(-1)!.id, version, action: body.action, values: {}, reason: 'Confirmed with project team', actor: 'operator', created_at: stamp, reported_contact: body.reported_contact } })
      return
    }
    const value = chain('one')
    const candidate = value.candidates![0]
    candidate.correction_version = version
    candidate.retracted = retracted
    candidate.correction_history = history
    candidate.reported_contacts = retracted ? [] : [{ kind: 'phone', value: '+1 312 555 0199' }]
    candidate.public_contacts = []
    await route.fulfill({ json: value })
  })
  const section = page.getByRole('region', { name: 'Buying chain' })
  await section.getByRole('button', { name: 'Correct or retract contact' }).click()
  await section.getByLabel('Corrected contact value').fill('+1 312 555 0199')
  await section.getByLabel('Operator-reported contact; not a verified public method').check()
  await section.getByLabel('Reason', { exact: true }).fill('Confirmed with project team')
  await section.getByRole('button', { name: 'Save contact correction' }).click()
  await expect(section.getByRole('alert')).toContainText('409')
  await section.getByRole('button', { name: 'Review claim and correction history' }).click()
  await expect(section.getByRole('button', { name: 'Hide claim history' })).toBeVisible()
  await expect(section.getByRole('alert')).toContainText('409')
  expect(history).toHaveLength(0)
})

test('operator-reported contact is history-backed, has no call action and can be retracted', async ({ page }) => {
  let version = 'v1'
  let retracted = false
  let historyReads = 0
  const history: Array<{ id: string; action: string; reason: string; created_at: string }> = []
  await shell(page, async (route) => {
    const request = route.request()
    if (request.url().includes('history=true')) historyReads += 1
    if (request.method() === 'POST') {
      const body = request.postDataJSON() as { expected_version: string; action: string; reported_contact: boolean }
      expect(body.expected_version).toBe(version)
      version = body.action === 'retract' ? 'v3' : 'v2'
      retracted = body.action === 'retract'
      history.push({ id: `saved-${history.length + 1}`, action: body.action, reason: 'Confirmed with project team', created_at: stamp })
      await route.fulfill({ json: { id: history.at(-1)!.id, version, action: body.action, values: {}, reason: 'Confirmed with project team', actor: 'operator', created_at: stamp, reported_contact: body.reported_contact } })
      return
    }
    const value = chain('one')
    const candidate = value.candidates![0]
    candidate.correction_version = version
    candidate.retracted = retracted
    candidate.correction_history = history
    candidate.reported_contacts = history.some((entry) => entry.action === 'correct') && !retracted ? [{ kind: 'phone', value: '+1 312 555 0199' }] : []
    candidate.public_contacts = []
    await route.fulfill({ json: value })
  })
  const section = page.getByRole('region', { name: 'Buying chain' })
  await section.getByRole('button', { name: 'Correct or retract contact' }).click()
  await section.getByLabel('Corrected contact value').fill('+1 312 555 0199')
  await section.getByLabel('Operator-reported contact; not a verified public method').check()
  await section.getByLabel('Reason', { exact: true }).fill('Confirmed with project team')
  await section.getByRole('button', { name: 'Save contact correction' }).click()
  await expect.poll(() => history.length).toBe(1)
  await expect.poll(() => historyReads).toBeGreaterThan(0)
  if (await section.getByLabel('Corrected contact value').count() === 0) {
    await section.getByRole('button', { name: 'Correct or retract contact' }).click()
  }
  await expect(section.getByText(/not a verified public call or email method/)).toBeVisible()
  await expect(section.getByRole('link', { name: /Call|Email/ })).toHaveCount(0)
  await expect(section.getByRole('button', { name: 'Retract this project relationship' })).toBeVisible()
  await section.getByLabel('Reason', { exact: true }).fill('Confirmed with project team')
  await section.getByRole('button', { name: 'Retract this project relationship' }).click()
  await expect(section.getByText('This project relationship is retracted and retained here as history.')).toBeVisible()
  await expect(section.getByRole('button', { name: 'Correct or retract contact' })).toHaveCount(0)
  await expect(section.getByRole('link', { name: /Call|Email/ })).toHaveCount(0)
  expect(history.map((entry) => entry.action)).toEqual(['correct', 'retract'])
})

test('a historical stale correction can be repaired using fresh evidence', async ({ page }) => {
  let saved = false
  const staleHistory = [{
    id: 'stale-correction', action: 'correct', reason: 'Prior cited page was replaced', created_at: stamp,
  }]
  await shell(page, async (route) => {
    if (route.request().method() === 'POST') {
      const body = route.request().postDataJSON() as {
        expected_version: string; source_evidence_id: string; source_hash: string; values: Record<string, string>
      }
      expect(body.expected_version).toBe('stale-head')
      expect(body.source_evidence_id).toBe('current-contact')
      expect(body.source_hash).toBe('c'.repeat(64))
      expect(body.values.public_contact_value).toBe('+1 312 555 0199')
      saved = true
      await route.fulfill({ json: {
        id: 'fresh-correction', version: 'fresh-head', action: 'correct', values: body.values,
        reason: 'Verified from current contact page', actor: 'operator', created_at: stamp,
        reported_contact: false,
      } })
      return
    }
    const value = chain('one')
    const candidate = value.candidates![0]
    candidate.correction_stale = true
    candidate.correction_version = saved ? 'fresh-head' : 'stale-head'
    candidate.correction_history = saved
      ? [...staleHistory, { id: 'fresh-correction', action: 'correct', reason: 'Verified from current contact page', created_at: stamp }]
      : staleHistory
    candidate.public_contacts = saved
      ? [{ kind: 'phone', value: '+1 312 555 0199', source_url: 'https://example.com/current', quote: 'Current business contact: +1 312 555 0199', observed_at: stamp }]
      : [{ kind: 'phone', value: '+1 312 555 0100', source_url: 'https://example.com/old', quote: 'Old business contact: +1 312 555 0100', observed_at: stamp }]
    candidate.evidence = [
      ...candidate.evidence!.filter((item) => item.id !== 'contact-evidence'),
      {
        id: 'old-contact', url: 'https://example.com/old', quote: 'Old business contact: +1 312 555 0100',
        supports: 'public_contact', extraction_location: 'superseded contact page', published_at: null,
        observed_at: stamp, content_hash: 'b'.repeat(64),
      },
      {
        id: 'current-contact', url: 'https://example.com/current', quote: 'Current business contact: +1 312 555 0199',
        supports: 'public_contact', extraction_location: 'current contact page', published_at: null,
        observed_at: stamp, content_hash: 'c'.repeat(64),
      },
    ]
    await route.fulfill({ json: value })
  })
  const section = page.getByRole('region', { name: 'Buying chain' })
  await expect(section.getByText('phone: +1 312 555 0100', { exact: false })).toBeVisible()
  await section.getByRole('button', { name: 'Correct or retract contact' }).click()
  await section.getByLabel('Corrected contact value').fill('+1 312 555 0199')
  await section.getByLabel('Current public-contact evidence').selectOption('current-contact')
  await section.getByLabel('Reason', { exact: true }).fill('Verified from current contact page')
  await section.getByRole('button', { name: 'Save contact correction' }).click()
  await expect.poll(() => saved).toBe(true)
  await expect(section.getByText(/Contact correction confirmed against current public evidence/)).toBeVisible()
  await expect(section.getByText('phone: +1 312 555 0199', { exact: false })).toBeVisible()
  await expect(section.getByText('phone: +1 312 555 0100', { exact: false })).toHaveCount(0)
  await expect(section.getByRole('button', { name: 'Save contact correction' })).toBeEnabled()
})

test('contact correction readback reports an unverified replacement without restoring the old method', async ({ page }) => {
  let saved = false
  await shell(page, async (route) => {
    if (route.request().method() === 'POST') {
      const body = route.request().postDataJSON() as { values: Record<string, string> }
      saved = true
      await route.fulfill({ json: {
        id: 'accepted-correction', version: 'accepted-head', action: 'correct', values: body.values,
        reason: 'Recorded from submitted review', actor: 'operator', created_at: stamp, reported_contact: false,
      } })
      return
    }
    const value = chain('one')
    const candidate = value.candidates![0]
    candidate.correction_stale = true
    candidate.correction_version = saved ? 'accepted-head' : 'stale-head'
    candidate.correction_history = saved
      ? [{ id: 'accepted-correction', action: 'correct', reason: 'Recorded from submitted review', created_at: stamp }]
      : [{ id: 'stale-correction', action: 'correct', reason: 'Prior page was replaced', created_at: stamp }]
    candidate.public_contacts = saved
      ? []
      : [{ kind: 'phone', value: '+1 312 555 0100', source_url: 'https://example.com/old', quote: 'Old business contact: +1 312 555 0100', observed_at: stamp }]
    candidate.evidence = [{
      id: 'current-contact', url: 'https://example.com/current', quote: 'Current page lists a different contact.',
      supports: 'public_contact', extraction_location: 'current contact page', published_at: null,
      observed_at: stamp, content_hash: 'c'.repeat(64),
    }]
    await route.fulfill({ json: value })
  })
  const section = page.getByRole('region', { name: 'Buying chain' })
  await section.getByRole('button', { name: 'Correct or retract contact' }).click()
  await section.getByLabel('Corrected contact value').fill('+1 312 555 0199')
  await section.getByLabel('Current public-contact evidence').selectOption('current-contact')
  await section.getByLabel('Reason', { exact: true }).fill('Record reviewed value')
  await section.getByRole('button', { name: 'Save contact correction' }).click()
  await expect.poll(() => saved).toBe(true)
  await expect(section.getByRole('status')).toContainText('current public evidence did not confirm')
  await expect(section.getByText('phone: +1 312 555 0100', { exact: false })).toHaveCount(0)
  await expect(section.getByRole('link', { name: /Call|Email/ })).toHaveCount(0)
})

test('queued buying-chain job survives reload and polls to a truthful terminal state', async ({ page }) => {
  let reads = 0
  await shell(page, async (route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({
        ...chain('one'), research_job: { id: 'job-1', status: 'queued', detail_status: 'queued', created_at: stamp },
      }) })
      return
    }
    reads += 1
    const state = reads < 5 ? 'queued' : 'succeeded'
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({
      ...chain('one'), research_job: { id: 'job-1', status: state, detail_status: state, created_at: stamp },
    }) })
  })
  const section = page.getByRole('region', { name: 'Buying chain' })
  await section.getByRole('button', { name: 'Enrich buying chain' }).click()
  await expect(section.getByRole('status')).toContainText('queued')
  await page.reload()
  await expect(section.getByRole('status')).toContainText('queued')
  await expect.poll(() => reads).toBeGreaterThanOrEqual(5)
  await expect(section.getByRole('status')).toHaveCount(0)
  await expect(section.getByRole('heading', { name: 'Test Electrical one' })).toBeVisible()
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
