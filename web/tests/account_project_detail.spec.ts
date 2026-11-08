import { expect, test, type Page } from '@playwright/test'
import { mockDemandSummary } from './mock-demand-summary'

// Synthetic rendering and navigation coverage only; all identities, contacts,
// power values and source records below are fabricated test data.
const company = 'Synthetic Grid Operator'
const accountId = 'cg_synthetic-grid'
const sources = [
  {
    reference: 'fixture:current', title: 'Synthetic construction notice', url: 'https://sources.example.test/current',
    source_date: '2026-10-20', retained_evidence_id: 'fixture-e-current', content_hash: 'a'.repeat(64),
    verification_status: 'Current retained support', assessment_current: true,
    abstract: 'Synthetic test notice describing one construction phase.',
  },
  {
    reference: 'fixture:historical', title: 'Synthetic historical planning notice', url: 'https://sources.example.test/historical',
    source_date: '2026-09-01', retained_evidence_id: 'fixture-e-historical', content_hash: 'b'.repeat(64),
    verification_status: 'Historical support', assessment_current: false,
    abstract: 'Synthetic historical record for disclosure testing.',
  },
]
function fixtureProject(id: string, needId: string, name: string) {
  return {
    id,
    project_id: id,
    name: `${company} · ${name}`,
    company,
    customer_identity_id: accountId,
    location: 'Synthetic, TX',
    sector: 'oil_gas',
    asset_type: 'compressor_station',
    priority_score: null,
    representative_need_id: needId,
    eligible_need_ids: [needId],
    need_count: 1,
    needs: [{ id: needId, project_id: id, name, browse_title: name, activity: 'compressor expansion', tier: 'Lead' }],
    event: { kind: 'construction', label: 'Synthetic construction planned', date: '2026-10-18', source: 'https://sources.example.test/current', evidence_refs: [] },
    contact: [
      { kind: 'call', label: `Call ${company}`, href: 'tel:+15555550199', route_kind: 'company_route', responsibility: 'General company contact path' },
      { kind: 'email', label: `Email ${company}`, href: 'mailto:contact@synthetic.example.test', route_kind: 'company_route', responsibility: 'General company contact path' },
      { kind: 'email', label: 'Injected contact', href: 'mailto:x%0d%0abcc@evil.test', route_kind: 'company_route' },
      { kind: 'contact', label: 'Unsafe contact page', href: 'javascript:alert(1)', route_kind: 'company_route' },
    ],
    contact_people: [],
    power_summary: 'Source-reported facility demand of 840 MW',
    power_summary_kind: 'facility_demand',
    commercial_brief: {
      version: 'synthetic-v1',
      why_now: { text: `Synthetic ${name} construction activity is planned.`, source_date: '2026-10-18', scope: 'This project only', sources: [{ title: 'Synthetic construction notice', url: sources[0].url, evidence_id: 'fixture-e-current', date: '2026-10-18' }] },
      power_need: { amount_class: 'unknown', scope: 'Temporary rental requirement', value: null, unit: null, status: 'Not established', limitations: ['Facility demand is not a rental requirement.'] },
      best_contact: { contact: 'Unsafe route', kind: 'contact', route_kind: 'company_route', authority: 'Unknown', deliverability: 'Unknown', sources: [] },
      next_action: { text: `Confirm ${name} scope from sources.`, kind: 'review', source: null },
      freshness: { as_of: '2026-10-21T00:00:00Z', status: 'Current source support', source_date: '2026-10-18' },
      limitations: ['Synthetic fixture only.'],
      sources: [{ title: 'Synthetic construction notice', url: sources[0].url, evidence_id: 'fixture-e-current', date: '2026-10-18' }],
    },
    next_action: 'Confirm the equipment package and timing from current sources.',
    shortlist_assessment: { eligible: true, reasons: [], evidence_refs: [], why_now: 'Synthetic construction is planned at this site.', next_step: 'Confirm the temporary power scope.' },
    updated_at: null,
  }
}

const firstProject = fixtureProject('project-synthetic-one', 'need-synthetic-one', 'Synthetic Compressor Station')
const secondProject = fixtureProject('project-synthetic-two', 'need-synthetic-two', 'Synthetic Processing Site')

function fixtureNeed(project: typeof firstProject, person: string, phone: string, email: string) {
  return {
    id: project.representative_need_id,
    project_id: project.project_id,
    name: project.name,
    browse_title: project.name,
    location: project.location,
    tier: 'Signal',
    workflow_status: 'New',
    activity: 'compressor expansion',
    rationale: 'Synthetic fixture summary for the selected project.',
    signal_evidence_state: 'active_evidence',
    required_mw: null,
    start_window: null,
    duration: null,
    supply: 'Unknown',
    next_action: project.next_action,
    commercial_reason: project.shortlist_assessment.why_now,
    commercial_next_action: project.shortlist_assessment.next_step,
    conflict_state: 'CONFLICT',
    evidence: [
      { id: 'evidence-synthetic-current', title: sources[0].title, abstract: sources[0].abstract, url: sources[0].url, published_at: sources[0].source_date, retrieved_at: '2026-10-21T00:00:00Z', extraction_location: 'Synthetic fixture', content_hash: sources[0].content_hash, event_date: '2026-10-18', event_date_label: 'Construction notice', source_id: 'synthetic-source', document_number: 'FIXTURE-1', source_origin: 'Synthetic fixture', assessment_current: true },
      { id: 'evidence-synthetic-history', title: sources[1].title, abstract: sources[1].abstract, url: sources[1].url, published_at: sources[1].source_date, retrieved_at: '2026-09-02T00:00:00Z', extraction_location: 'Synthetic fixture', content_hash: sources[1].content_hash, event_date: null, event_date_label: 'Historical', source_id: 'synthetic-source', document_number: 'FIXTURE-2', source_origin: 'Synthetic fixture', assessment_current: false },
    ],
    missing_facts: ['Temporary rental demand', 'Buyer authority'],
    associated_account: { company_identity_id: accountId, name: company, role: 'asset_operator', basis: 'typed_rrc_operator_number_v1', support_status: 'current' },
    intelligence_card: {
      policy_version: 'synthetic-test',
      need_id: project.representative_need_id,
      project_id: project.project_id,
      qualification: 'Signal',
      disposition: 'RESEARCH',
      fields: [
        { key: 'facility_demand', label: 'Facility demand', section: 'power', value: '840 MW', status: 'Source-reported', basis: 'Synthetic fixture; not a rental estimate.', sources: [sources[0]] },
      ],
      contacts: [{ claim_id: `synthetic-${project.project_id}-contact`, company, name: person, title: 'Project procurement contact', role: 'procurement', responsibility: 'Verified project responsibility', purchasing_authority: 'Requires confirmation for this package', methods: [
        { kind: 'phone', value: phone, verified_at: '2026-10-20T12:00:00Z', source_url: sources[0].url },
        { kind: 'email', value: email, verified_at: '2026-10-20T12:00:00Z', source_url: sources[0].url },
        { kind: 'email', value: 'bad%0d%0a@example.test', verified_at: '2026-10-20T12:00:00Z', source_url: sources[0].url },
      ], sources: [sources[0]] }],
      evidence: [sources[0], sources[1]],
      research_gaps: [{ key: 'rental_gap', label: 'Temporary rental requirement not established' }],
      power_gap: { remaining_mw: 'Not established', status: 'unknown' },
      equipment_demand: { classification: 'UNKNOWN', status: 'PARTIAL', scope: 'equipment_schedule' },
    },
  }
}

const needs = {
  'need-synthetic-one': fixtureNeed(firstProject, 'Jordan Fixture', '+15555550111', 'jordan@synthetic.example.test'),
  'need-synthetic-two': fixtureNeed(secondProject, 'Riley Fixture', '+15555550222', 'riley@synthetic.example.test'),
}
const group = {
  id: accountId,
  name: company,
  role: 'operator',
  group_kind: 'resolved_identity',
  project_count: 2,
  relevant_project_count: 2,
  total_known_project_count: 2,
  need_count: 2,
  eligible_need_count: 2,
  pursued_eligible_need_count: 0,
  sectors: ['oil_gas'],
  featured_project: firstProject,
}
const projectPage = { items: [firstProject, secondProject], total: 2, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'synthetic-child-cohort', generation: 'synthetic', valid_until: '2099-01-01T00:00:00Z' }

async function install(page: Page, options: { delaySecondNeed?: () => Promise<void>; delayNeedRead?: (needId: string, count: number) => Promise<void>; projectValidUntil?: string[]; onProjectRead?: () => void; onNeedRead?: (needId: string, count: number) => void; suppressContacts?: () => boolean } = {}) {
  let mutations = 0
  let projectReadCount = 0
  const needReadCounts: Record<string, number> = {}
  await mockDemandSummary(page)
  await page.route(url => new URL(url).pathname.startsWith('/api/'), async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (url.pathname === '/api/opportunities/groups') return route.fulfill({ json: { items: [group], total: 1, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'synthetic-groups', generation: 'synthetic' } })
    if (url.pathname === `/api/opportunities/groups/${accountId}/open`) return route.fulfill({ json: { group, projects: projectPage, parent_cohort_token: 'synthetic-parent', generation: 'synthetic' } })
    if (url.pathname === `/api/opportunities/groups/${accountId}/projects`) return route.fulfill({ json: { ...projectPage, parent_cohort_token: 'synthetic-parent' } })
    if (url.pathname === `/api/projects/${firstProject.project_id}/account` || url.pathname === `/api/projects/${secondProject.project_id}/account`) return route.fulfill({ json: { id: accountId, name: company, group_kind: 'resolved_identity', project_id: url.pathname.includes('one') ? firstProject.project_id : secondProject.project_id } })
    if (url.pathname === '/api/opportunities/needs/need-synthetic-one') {
      const count = (needReadCounts['need-synthetic-one'] ?? 0) + 1
      needReadCounts['need-synthetic-one'] = count
      options.onNeedRead?.('need-synthetic-one', count)
      await options.delayNeedRead?.('need-synthetic-one', count)
      const value = structuredClone(needs['need-synthetic-one'])
      if (options.suppressContacts?.()) value.intelligence_card.contacts = []
      return route.fulfill({ json: value })
    }
    if (url.pathname === '/api/opportunities/needs/need-synthetic-two') {
      await options.delaySecondNeed?.()
      const count = (needReadCounts['need-synthetic-two'] ?? 0) + 1
      needReadCounts['need-synthetic-two'] = count
      options.onNeedRead?.('need-synthetic-two', count)
      await options.delayNeedRead?.('need-synthetic-two', count)
      return route.fulfill({ json: needs['need-synthetic-two'] })
    }
    if (url.pathname === '/api/opportunities/projects') {
      options.onProjectRead?.()
      const validUntil = options.projectValidUntil?.[Math.min(projectReadCount, (options.projectValidUntil?.length ?? 1) - 1)] ?? projectPage.valid_until
      projectReadCount += 1
      const items = options.suppressContacts?.() && projectReadCount > 1
        ? [firstProject, secondProject].map(project => ({ ...project, contact: [], contact_people: [] }))
        : [firstProject, secondProject]
      return route.fulfill({ json: { ...projectPage, valid_until: validUntil, items } })
    }
    if (url.pathname === '/api/commercial-pursuits') {
      if (route.request().method() !== 'GET') mutations += 1
      return route.fulfill({ json: { items: [], counts: { total: 0, active: 0, needs_attention: 0 }, total_matching: 0, has_more: false, next_offset: null } })
    }
    if (url.pathname === '/api/opportunities/workspace/changes') return route.fulfill({ json: { items: [], counts: {}, total_unreviewed: 0, offset: 0, limit: 50, next_offset: null, baseline_identity: 'synthetic', token: 'synthetic', source_health_exceptions: [] } })
    return route.fulfill({ status: 404, json: { detail: `No synthetic fixture for ${url.pathname}` } })
  })
  return () => mutations
}

test('account-first project detail is compact, source-on-demand, scoped and returns to its account', async ({ page }) => {
  const mutations = await install(page)
  await page.goto('/?view=workspace&groupBrowse=1')
  await page.getByRole('button', { name: /Synthetic Grid Operator/ }).click()
  const account = page.getByRole('region', { name: `Company ${company}` })
  const row = account.locator(`[data-project-id="${firstProject.project_id}"]`)
  await row.getByRole('button', { name: /Open project detail/ }).click()

  const detail = page.getByRole('complementary', { name: 'Opportunity detail' })
  await expect(detail.getByRole('heading', { name: 'Synthetic Compressor Station', exact: true })).toBeVisible()
  await expect(detail.getByRole('button', { name: '← Back to account' })).toBeVisible()
  await expect(detail.getByText(/Current evidence is conflicting/)).toBeVisible()
  await expect(detail.getByText('Power need unknown')).toBeVisible()
  await expect(detail.getByText(/Facility demand is not a rental requirement/)).toBeVisible()
  await expect(detail.getByText(/Synthetic Synthetic Compressor Station construction activity is planned/)).toBeVisible()
  await expect(detail.getByRole('link', { name: 'Unsafe route' })).toHaveCount(0)
  await expect(detail.getByRole('link', { name: 'Call +15555550111' })).toHaveAttribute('href', 'tel:+15555550111')
  await expect(detail.getByRole('link', { name: 'Email jordan@synthetic.example.test' })).toHaveAttribute('href', 'mailto:jordan@synthetic.example.test')
  await expect(detail.getByRole('link', { name: /bad%0d%0a|Injected contact|Unsafe contact page/ })).toHaveCount(0)
  await expect(detail.getByRole('button', { name: /Lead|Signal/ })).toHaveCount(0)
  await expect(detail.locator('.cod-tier, .cod-metrics, .cod-evidence')).toHaveCount(0)
  await expect(detail.getByText(/temporary rental demand|Buyer authority|Research gap/i)).toHaveCount(0)
  await expect(detail.getByRole('button', { name: /View research|Research/ })).toHaveCount(0)
  const sourcesDisclosure = detail.locator('details.cod-account-sources')
  await expect(sourcesDisclosure).toBeVisible()
  await expect(sourcesDisclosure).not.toHaveAttribute('open', '')
  await expect(sourcesDisclosure.getByText('Synthetic construction notice').first()).not.toBeVisible()
  await expect(detail.getByText(/Confirm Synthetic Compressor Station scope from sources/)).toBeVisible()
  await expect(detail.getByRole('button', { name: 'Add to Pursuit' })).toBeVisible()
  expect(mutations()).toBe(0)

  await sourcesDisclosure.locator('summary').click()
  await expect(sourcesDisclosure.getByRole('link', { name: 'Synthetic construction notice' })).toHaveAttribute('href', sources[0].url)
  await expect(sourcesDisclosure.getByRole('link', { name: 'Synthetic historical planning notice' })).toHaveAttribute('href', sources[1].url)
  await expect(sourcesDisclosure).toContainText('Current support')
  await expect(sourcesDisclosure).toContainText('Historical support')
  expect(mutations()).toBe(0)

  await detail.getByRole('button', { name: '← Back to account' }).click()
  await expect(page.getByRole('region', { name: `Company ${company}` })).toBeVisible()
  expect(mutations()).toBe(0)
})

test('switching a delayed project never leaves the previous project contact visible', async ({ page }) => {
  let releaseSecondNeed!: () => void
  const secondNeedWait = new Promise<void>(resolve => { releaseSecondNeed = resolve })
  await install(page, { delaySecondNeed: () => secondNeedWait })
  await page.goto(`/?view=workspace&groupBrowse=1&account=${accountId}`)
  const account = page.getByRole('region', { name: `Company ${company}` })
  await account.locator(`[data-project-id="${firstProject.project_id}"]`).getByRole('button', { name: /Open project detail/ }).click()
  const detail = page.getByRole('complementary', { name: 'Opportunity detail' })
  await expect(detail.getByRole('link', { name: 'Call +15555550111' })).toBeVisible()
  await detail.getByRole('button', { name: '← Back to account' }).click()
  await account.locator(`[data-project-id="${secondProject.project_id}"]`).getByRole('button', { name: /Open project detail/ }).click()
  const loadingDetail = page.getByRole('complementary', { name: 'Opportunity detail' })
  await expect(loadingDetail).toContainText('Loading verified opportunity detail')
  await expect(loadingDetail.getByText(/Synthetic Compressor Station construction activity is planned/)).toHaveCount(0)
  await expect(loadingDetail.getByText('Jordan Fixture')).toHaveCount(0)
  await expect(loadingDetail.getByRole('link', { name: 'Call +15555550111' })).toHaveCount(0)
  releaseSecondNeed()
  await expect(loadingDetail.getByRole('heading', { name: 'Synthetic Processing Site', exact: true })).toBeVisible()
  await expect(loadingDetail.getByText(/Synthetic Synthetic Processing Site construction activity is planned/)).toBeVisible()
  await expect(loadingDetail.getByRole('link', { name: 'Call +15555550222' })).toBeVisible()
  await expect(loadingDetail.getByText('Jordan Fixture')).toHaveCount(0)
})

test('expired project detail hides contacts and actions, then offers a bounded retry after an expired refresh', async ({ page }) => {
  await page.clock.install({ time: new Date('2026-11-07T00:00:00Z') })
  // Leave setup time for slower CI browsers; fastForward below triggers expiry deterministically.
  await install(page, { projectValidUntil: [
    '2026-11-07T00:01:00Z',
    '2026-11-07T00:00:00Z',
    '2026-11-07T00:02:00Z',
  ] })
  await page.goto('/?view=workspace&groupBrowse=1')
  await page.getByRole('button', { name: /Synthetic Grid Operator/ }).click()
  const account = page.getByRole('region', { name: `Company ${company}` })
  await account.locator(`[data-project-id="${firstProject.project_id}"]`).getByRole('button', { name: /Open project detail/ }).click()
  const detail = page.getByRole('complementary', { name: 'Opportunity detail' })
  await expect(detail.getByRole('link', { name: 'Call +15555550111' })).toBeVisible()
  await expect(detail.getByRole('button', { name: 'Add to Pursuit' })).toBeVisible()

  await page.clock.fastForward(61_000)
  await expect(detail.getByRole('alert')).toContainText('expired before it could be displayed')
  await expect(detail.getByText('Jordan Fixture')).toHaveCount(0)
  await expect(detail.getByRole('link', { name: 'Call +15555550111' })).toHaveCount(0)
  await expect(detail.getByRole('link', { name: /Synthetic Grid Operator/ })).toHaveCount(0)
  await expect(detail.getByRole('button', { name: 'Add to Pursuit' })).toHaveCount(0)
  await expect(detail.getByRole('region', { name: 'Recommended next action' })).toHaveCount(0)
  await expect(detail.getByRole('region', { name: 'Why this project matters' })).toHaveCount(0)
  await expect(detail.locator('details.cod-account-sources')).toBeVisible()

  await detail.getByRole('button', { name: 'Retry' }).click()
  await expect(detail.getByRole('link', { name: 'Call +15555550111' })).toBeVisible()
  await expect(detail.getByRole('button', { name: 'Add to Pursuit' })).toBeVisible()
})

test('expiry requires a fresh exact need and project projection before contacts can return', async ({ page }) => {
  await page.clock.install({ time: new Date('2026-11-07T00:00:00Z') })
  let suppressContacts = false
  let holdNeedRefresh = false
  let releaseNeedRefresh!: () => void
  const needRefreshWait = new Promise<void>(resolve => { releaseNeedRefresh = resolve })
  let needReads = 0
  let projectReads = 0
  await install(page, {
    // Keep initial support current until contacts are observed, then fastForward past this lease.
    projectValidUntil: ['2026-11-07T00:01:00Z', '2026-11-07T00:02:00Z'],
    onNeedRead: id => { if (id === 'need-synthetic-one') needReads += 1 },
    delayNeedRead: id => id === 'need-synthetic-one' && holdNeedRefresh ? needRefreshWait : Promise.resolve(),
    onProjectRead: () => { projectReads += 1 },
    suppressContacts: () => suppressContacts,
  })
  await page.goto('/?view=workspace&groupBrowse=1')
  await page.getByRole('button', { name: /Synthetic Grid Operator/ }).click()
  const account = page.getByRole('region', { name: `Company ${company}` })
  await account.locator(`[data-project-id="${firstProject.project_id}"]`).getByRole('button', { name: /Open project detail/ }).click()
  const detail = page.getByRole('complementary', { name: 'Opportunity detail' })
  await expect(detail.getByRole('link', { name: 'Call +15555550111' })).toBeVisible()
  const initialNeedReads = needReads
  suppressContacts = true
  holdNeedRefresh = true

  await page.clock.fastForward(61_000)
  await expect.poll(() => needReads).toBeGreaterThan(initialNeedReads)
  await expect(detail.getByRole('link', { name: 'Call +15555550111' })).toHaveCount(0)
  await expect(detail.getByText('Jordan Fixture')).toHaveCount(0)
  releaseNeedRefresh()
  await expect(detail.getByText('No appropriate business phone or email is available in retained contact evidence.')).toBeVisible()
  expect(needReads).toBeGreaterThan(initialNeedReads)
  expect(projectReads).toBeGreaterThanOrEqual(2)
  await expect(detail.getByText('Jordan Fixture')).toHaveCount(0)
  await expect(detail.getByRole('link', { name: 'Call +15555550111' })).toHaveCount(0)
  await expect(detail.getByRole('link', { name: 'Email jordan@synthetic.example.test' })).toHaveCount(0)
  await expect(detail.getByRole('link', { name: /Synthetic Grid Operator/ })).toHaveCount(0)
})

test('far-future project validity does not trigger an early expiry refresh', async ({ page }) => {
  await page.clock.install({ time: new Date('2026-11-07T00:00:00Z') })
  let projectReads = 0
  await install(page, { onProjectRead: () => { projectReads += 1 } })
  await page.goto('/?view=workspace&groupBrowse=1')
  await page.getByRole('button', { name: /Synthetic Grid Operator/ }).click()
  const account = page.getByRole('region', { name: `Company ${company}` })
  await account.locator(`[data-project-id="${firstProject.project_id}"]`).getByRole('button', { name: /Open project detail/ }).click()
  const detail = page.getByRole('complementary', { name: 'Opportunity detail' })
  await expect(detail.getByRole('link', { name: 'Call +15555550111' })).toBeVisible()
  expect(projectReads).toBe(1)
  await page.clock.fastForward(10_000)
  await expect(detail.getByRole('link', { name: 'Call +15555550111' })).toBeVisible()
  expect(projectReads).toBe(1)
})
