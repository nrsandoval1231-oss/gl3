import { expect, test, type Page } from '@playwright/test'
import type { ResearchQuestion, ResearchOverview } from '../src/api/client'

const question = (status: string): ResearchQuestion => ({
  id: 'question-a', project_id: 'project-a', need_id: 'need-a', pursuit_id: 'pursuit-a', category: 'buyer', question: 'Who owns the electrical scope at this exact project?', status, attempt_count: 1,
  created_at: '2026-10-04T10:00:00Z', completed_at: status === 'QUEUED' ? null : '2026-10-04T10:01:00Z', retry_after: null,
  query_fingerprint: 'query-hash', evidence_fingerprint: 'evidence-hash', budget: {},
  context: { route_plan: [{kind: 'registered', family: 'utility-filings', status: 'PLANNED', source_id: 'utility-fixture'}], why: 'A reachable project path supports a discovery call.', known_facts: [{ text: 'Temporary construction power is required.', evidence_id: 'ev-before' }], unknowns: ['Electrical contractor'], before: { disposition: 'RESEARCH', tier: 'Signal' }, source_families: ['permit', 'contractor'], queries: ['"811 Test Lane" electrical contractor'] },
  receipt: status === 'QUEUED' ? { reevaluation_status: 'NOT_STARTED', searches: 0, retrieval_attempts: 0, model_calls: 0 } : { route_results: [{kind: 'registered', family: 'utility-filings', status: 'UNAVAILABLE', reason: 'No bounded utility adapter configured.'}], before: 'RESEARCH', after: status === 'RESOLVED' ? 'ACTION NOW' : 'RESEARCH', reason: status === 'RESOLVED' ? 'Current project contractor and public contact confirmed.' : 'No admissible contractor evidence.', reevaluation_status: 'COMPLETED', tier: 'Signal', remaining_blockers: ['Activity-specific load remains unknown.'], searches: 0, retrieval_attempts: 1, model_calls: 0, cost_usd: null, reserved_cost_usd: '0.05', runtime_seconds: 1.2,
    error: status === 'FAILED' ? 'Public source timed out.' : null,
    queries_attempted: ['\"811 Test Lane\" project contact'], queries_searched: [], acquisition_limitations: ['Broad web search was unavailable.'], queries_generated: ['"811 Test Lane" electrical contractor'],
    source_checks: [{ event_date: '2026-09-30', match_basis: 'Exact retained permit identifier', evidence_url: 'https://example.test/original-permit', claim_type: 'project_organization_relationship', publisher: 'Municipal permits', extraction_location: 'Electrical contractor field', checked_at: '2026-10-04T10:00:31Z', cache_reused: true, duplicate: true, url: 'https://example.test/permit', disposition: status === 'RESOLVED' ? 'accepted' : 'rejected', reason: 'Exact project identifier checked.', evidence_id: status === 'RESOLVED' ? 'ev-new' : null, label: 'Reported', excerpt: 'Project electrical contractor: Example Electric.', published_at: '2026-10-01', retrieved_at: '2026-10-04T10:00:30Z' }],
  },
})
async function fixture(page: Page, initial: ResearchQuestion[], progress = false, overview: ResearchOverview | null = null) {
  let posts = 0
  let gets = 0
  let readsAfterPost = 0
  let forced: unknown
  let items = initial
  await page.route('**/api/auth/session', (route) => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/health', (route) => route.fulfill({ json: {} }))
  await page.route('**/api/opportunities?*', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/changes', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/projects/*/buying-chain', (route) => route.fulfill({ json: { project_id: 'project-a', status: 'available', unresolved: [], runs: [], candidates: [] } }))
  await page.route('**/api/commercial/triage?*', (route) => route.fulfill({ json: {
    research_overview: overview, evaluated_at: '2026-10-04T10:00:00Z', policy_version: 'v1', total: 1, cohort_counts: { action_now: 0, research: 1, watch: 0, reject: 0 }, daily: { evaluated: 1, surfaced: 0, contacted: 0 },
    items: [{ id: 'need-a', project_id: 'project-a', pursuit_id: 'pursuit-a', name: 'Research fixture project', tier: 'Signal', activity: 'construction', industry: 'data_center', disposition: 'RESEARCH', reason: 'Buying path unknown.', supply: 'Unknown', next_question: 'Who owns electrical scope?', next_action: 'Find the public project contact.', stage: { stage: 'construction' }, blockers: ['Project contractor unknown'], facts: [], contacts: [], sources: [], unknowns: [], lifecycle_timeline: [], notes: [] }],
  } }))
  await page.route('**/api/commercial/triage/need-a/autonomous-research', async (route) => {
    if (route.request().method() === 'POST') {
      posts += 1
      forced = route.request().postDataJSON().force
      items = [question('QUEUED')]
    } else {
      gets += 1
      if (posts > 0) readsAfterPost += 1
      if (progress && readsAfterPost > 1) items = [question('RESOLVED')]
    }
    await route.fulfill({ json: { items } })
  })
  await page.goto('/?view=pursuits')
  await page.getByRole('button', { name: 'RESEARCH 1', exact: true }).click()
  await page.locator('.commercial-card-heading').filter({ hasText: 'Research fixture project' }).click()
  return { get posts() { return posts }, get gets() { return gets }, get forced() { return forced } }
}

test('explicit request polls GET through resolution, exposes evidence and preserves prior state', async ({ page }) => {
  const calls = await fixture(page, [], true)
  const panel = page.getByRole('region', { name: 'Autonomous pursuit research' })
  await panel.getByRole('button', { name: 'Research missing facts', exact: true }).click()
  await expect(panel.getByText(/1 active blocker/)).toBeVisible()
  await expect(panel.getByRole('button', { name: 'Research in progress…' })).toBeDisabled()
  await expect(panel.getByText(/RESEARCH → ACTION NOW/)).toBeVisible()
  await expect(panel.getByText('Resulting evidence tier: Signal')).toBeVisible()
  await panel.getByText('What GridLens knew before').click()
  await expect(panel.getByText(/Temporary construction power is required/)).toBeVisible()
  await panel.getByText('Research trail · sources and evidence decisions').click()
  await expect(panel.getByText(/Searches executed: 0/)).toBeVisible()
  await expect(panel.getByText(/Actual cost: Unavailable · Reserved cost: \$0.05/)).toBeVisible()
  await expect(panel.getByText('No successful searches recorded.')).toBeVisible()
  await expect(panel.getByRole('heading', {name: 'Planned source routes'})).toBeVisible()
  await expect(panel.getByText('No bounded utility adapter configured.')).toBeVisible()
  await expect(panel.getByText('Project match basis: Exact retained permit identifier')).toBeVisible()
  await expect(panel.getByText(/Event date: 2026-09-30/)).toBeVisible()
  await expect(panel.getByText(/Publisher: Municipal permits/)).toBeVisible()
  await expect(panel.getByText('Cached source result reused.')).toBeVisible()
  await expect(panel.getByText('Duplicate evidence avoided.')).toBeVisible()
  await expect(panel.getByText('Claim type: Project organization relationship')).toBeVisible()
  await expect(panel.getByRole('link', { name: 'https://example.test/original-permit', exact: true })).toHaveAttribute('href', 'https://example.test/original-permit')
  await expect(panel.getByText('Project electrical contractor: Example Electric.')).toBeVisible()
  await expect(panel.getByRole('link', { name: 'https://example.test/permit' })).toHaveAttribute('href', 'https://example.test/permit')
  expect(calls.posts).toBe(1)
  expect(calls.forced).toBe(false)
  const gets = calls.gets
  await page.waitForTimeout(1800)
  expect(calls.gets).toBe(gets)
})

test('unresolved and failure history are inspectable without POST; refresh is explicit', async ({ page }) => {
  const unresolved = question('UNRESOLVED')
  const failed = { ...question('FAILED'), id: 'question-b' }
  const calls = await fixture(page, [unresolved, failed])
  const panel = page.getByRole('region', { name: 'Autonomous pursuit research' })
  await expect(panel.getByText(/Insufficient evidence within this attempt/)).toBeVisible()
  await expect(panel.getByRole('alert')).toHaveText('Public source timed out.')
  expect(calls.posts).toBe(0)
  await panel.getByRole('button', { name: 'Refresh missing facts' }).click()
  await expect(panel.getByText(/1 active blocker/)).toBeVisible()
  expect(calls.posts).toBe(1)
  expect(calls.forced).toBe(true)
  const gets = calls.gets
  await page.getByRole('button', { name: /Research fixture project/ }).click()
  await page.waitForTimeout(1800)
  expect(calls.gets).toBe(gets)
  expect(calls.posts).toBe(1)
})

test('failed status request is visible and retry only reads status', async ({ page }) => {
  const calls = await fixture(page, [])
  await page.route('**/api/commercial/triage/need-a/autonomous-research', (route) => route.fulfill({ status: 503, json: { detail: 'Status temporarily unavailable.' } }))
  await page.getByRole('button', { name: /Research fixture project/ }).click()
  await page.getByRole('button', { name: /Research fixture project/ }).click()
  const panel = page.getByRole('region', { name: 'Autonomous pursuit research' })
  await expect(panel.getByRole('alert')).toContainText('Status temporarily unavailable')
  await panel.getByRole('button', { name: 'Retry research status' }).click()
  await expect(panel.getByRole('alert')).toContainText('Status temporarily unavailable')
  expect(calls.posts).toBe(0)
})

test('saved evaluation research history is read-only even for an active attempt', async ({ page }) => {
  await fixture(page, [])
  let reads = 0
  let writes = 0
  await page.route('**/api/commercial/triage/history', (route) => route.fulfill({ json: { items: [{ pursuit_id: 'pursuit-old', need_id: 'need-old', project_id: 'project-old', disposition: 'RESEARCH', snapshot_status: 'metadata_only', live_status: 'not_rechecked', saved_card: null, notes: [] }] } }))
  await page.route('**/api/commercial/triage/need-old/autonomous-research', (route) => {
    if (route.request().method() === 'POST') writes += 1
    else reads += 1
    return route.fulfill({ json: { items: [{ ...question('QUEUED'), need_id: 'need-old' }] } })
  })
  const history = page.locator('.commercial-history')
  await history.locator('summary').click()
  await history.getByRole('button', { name: /Saved work · need-old/ }).click()
  const panel = history.getByRole('region', { name: 'Autonomous pursuit research' })
  await expect(panel.getByText(/Read-only research history/)).toBeVisible()
  await expect(panel.getByText(/1 active blocker/)).toBeVisible()
  await expect(panel.getByRole('button')).toHaveCount(0)
  const initialReads = reads
  await page.waitForTimeout(1800)
  expect(reads).toBe(initialReads)
  expect(writes).toBe(0)
})


test('research-related summary preserves one evaluation for multiple questions and opens read-only history', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const overview: ResearchOverview = {
    since: '2026-10-04T00:00:00Z', summary: { blockers_attempted: 2, blocker_statuses: { RESOLVED: 1, UNRESOLVED: 1 }, commercial_transitions: { 'RESEARCH → ACTION NOW': 1 } },
    items: [{ id: 'pursuit-a:2', pursuit_id: 'pursuit-a', need_id: 'need-a', project_id: 'project-a', version: 2, evaluated_at: '2026-10-04T10:01:00Z', name: 'Research fixture project', before: 'RESEARCH', after: 'ACTION NOW', before_tier: 'Signal', after_tier: 'Signal', reason: 'Reachable project contractor confirmed.', next_action: 'Ask the contractor who owns the power package.', question_ids: ['question-a', 'question-b'], new_evidence: [{ text: 'Project electrical contractor confirmed.', evidence_id: 'ev-new', url: 'https://example.test/permit', hash: 'hash-new', date: '2026-10-01' }] }],
  }
  const calls = await fixture(page, [question('RESOLVED')], false, overview)
  const summary = page.getByRole('region', { name: 'Research-related changes' })
  await expect(summary.getByText(/2 blockers attempted · 1 resolved/)).toBeVisible()
  await expect(summary.getByText('RESEARCH → ACTION NOW', { exact: true })).toHaveCount(1)
  await expect(summary.getByText('Evidence tier: Signal → Signal')).toBeVisible()
  await expect(summary.getByText(/Ask the contractor who owns the power package/)).toBeVisible()
  await summary.getByRole('button', { name: 'Inspect research history · Research fixture project' }).click()
  const history = summary.getByRole('region', { name: 'Autonomous pursuit research' })
  await expect(history.getByText(/Read-only research history/)).toBeVisible()
  await expect(history.getByRole('button')).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  expect(calls.posts).toBe(0)
})

test('empty research overview does not claim actionable changes', async ({ page }) => {
  await fixture(page, [], false, { since: null, summary: { blockers_attempted: 0 }, items: [] })
  const summary = page.getByRole('region', { name: 'Research-related changes' })
  await expect(summary.getByText('No research-linked evaluation changes recorded in this time window.')).toBeVisible()
  await expect(summary.getByRole('button')).toHaveCount(0)
})
