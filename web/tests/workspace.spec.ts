import { mockDemandSummary } from './mock-demand-summary'
import { expect, test } from '@playwright/test'

const need = {
  id: 'need-a', project_id: 'project-a', name: 'Test data center', location: 'Austin, TX', tier: 'Signal', workflow_status: 'New', activity: 'construction',
  rationale: 'A retained project filing supports investigation.', signal_evidence_state: 'active', conflict_state: 'Not assessed', required_mw: null, supply: 'Unknown', start_window: null, duration: null,
  evidence: [{ source_id: 'city-permit', document_number: 'P-1', title: 'Permit filing', url: 'https://example.test/permit', published_at: null, retrieved_at: '2026-10-18T10:00:00Z', event_date: null, event_date_label: 'Event date', source_origin: 'City permits', extraction_location: 'Page 1', abstract: 'Construction filing.' }],
  missing_facts: ['Activity-specific load', 'Suitable utility supply'], project_identity_key: 'test', commercial_disposition: 'RESEARCH', commercial_reason: 'Load and supply remain unknown.', commercial_next_question: 'Who owns the electrical scope?', commercial_next_action: 'Research the project contractor.', commercial_organization: null,
} as any
const projectResults = (items = [need], total = items.length, offset = 0) => ({
  items: items.map((item: any) => {
    const projectId = items.filter((candidate: any) => candidate.project_id === item.project_id).length > 1 ? `${item.project_id}-${item.id}` : item.project_id
    const company = item.commercial_organization ?? item.title_company ?? 'Example operator'
    return {
      id: projectId || `project-${item.id}`, project_id: projectId || `project-${item.id}`, name: item.browse_title ? `${company} · ${item.browse_title}` : item.name, company,
      location: item.location, sector: item.sector ?? 'data_centers', asset_type: item.asset_type ?? 'data_center', priority_score: item.rank_score ?? null,
      representative_need_id: item.id, need_count: 1,
      needs: [{ id: item.id, project_id: projectId || `project-${item.id}`, tier: item.tier, activity: item.activity, browse_title: item.browse_title ?? item.name, location: item.location, commercial_preview: { disposition: item.commercial_disposition } }],
      event: null, contact: [], contact_people: [], power_summary: null, power_summary_kind: 'unknown', next_action: item.commercial_next_action ?? null, updated_at: null,
      shortlist_assessment: item.rank_reasons?.length ? { why_now: item.commercial_reason ?? item.rationale ?? item.rank_reasons.join('; '), next_step: item.commercial_next_action ?? null } : undefined,
    }
  }), total, count_unit: 'projects', limit: 25, offset, cohort_token: 'project-fixture', generation: 'fixture', valid_until: '2099-01-01T00:00:00Z', results_scope: 'discovery', qualification_state: 'current', refresh_state: 'current',
})
const response = (items = [need]) => projectResults(items)
const emptyChanges = { items: [], counts: { discovered: 0, changed: 0, promoted: 0, closed: 0, review_exception: 0 }, total_unreviewed: 0, offset: 0, limit: 50, next_offset: null, evaluated_at: '2026-10-20T12:00:00Z', baseline_identity: '00000000-0000-4000-8000-000000000001', baseline_reviewed_at: null, first_use: true, token: 'a'.repeat(64), source_health_exceptions: [] }

test.beforeEach(async ({ page }) => {
  await page.route('**/api/opportunities/workspace/changes*', route => route.fulfill({ json: emptyChanges }))
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: { items: [], total: 0, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'empty-groups', generation: 'synthetic', valid_until: '2099-01-01T00:00:00Z' } }))
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: { items: [], total: 0, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'empty-projects', generation: 'synthetic', valid_until: '2099-01-01T00:00:00Z' } }))
  await page.route('**/api/opportunities/needs/*', route => route.fulfill({ json: need }))
})



test('default workspace shows customer accounts and opens an existing project need without the legacy list API', async ({ page }) => {
  const workspaceRequests: URL[] = []
  const project = { id: 'project-a', project_id: 'project-a', name: 'Test data center', company: 'Example operator', location: 'Austin, TX', sector: 'data_centers', asset_type: 'data_center', priority_score: null, representative_need_id: 'need-a', needs: [{ id: 'need-a', project_id: 'project-a', activity: 'construction', browse_title: 'Test data center', location: 'Austin, TX' }], need_count: 1, event: { kind: 'permit_issued', label: 'Permit issued', date: '2026-10-18', source: 'Synthetic fixture', evidence_refs: [] }, contact: [], power_summary: 'Power need remains unconfirmed.', next_action: 'Review the source-backed project evidence.', updated_at: '2026-10-20T00:00:00Z' }
  const group = { id: 'cg_example_operator', name: 'Example operator', role: 'operator', group_kind: 'resolved_identity', project_count: 1, total_known_project_count: 1, relevant_project_count: 1, eligible_need_count: 1, pursued_eligible_need_count: 0, need_count: 1, sectors: ['data_centers'], featured_project: project }
  const accountNeed = { ...need, project_identity_key: group.id, commercial_organization: group.name, associated_account: { company_identity_id: group.id, name: group.name, role: 'asset_operator', support_status: 'current', basis: 'current supported identity' } }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: { items: [group], total: 1, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'group-cohort', generation: 'synthetic', valid_until: '2099-01-01T00:00:00Z' } }))
  await page.route(`**/api/opportunities/groups/${group.id}/open?*`, route => route.fulfill({ json: { group, projects: { items: [project], total: 1, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'project-cohort', generation: 'synthetic', valid_until: '2099-01-01T00:00:00Z' }, parent_cohort_token: 'group-cohort', generation: 'synthetic', valid_until: '2099-01-01T00:00:00Z' } }))
  await page.route(`**/api/opportunities/groups/${group.id}/projects?*`, route => route.fulfill({ json: { items: [project], total: 1, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'project-cohort', generation: 'synthetic', valid_until: '2099-01-01T00:00:00Z' } }))
  await page.route('**/api/projects/project-a/account', route => route.fulfill({ json: { id: group.id, name: group.name, group_kind: group.group_kind, project_id: 'project-a' } }))
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: { items: [project], total: 1, count_unit: 'projects', limit: 1, offset: 0, cohort_token: 'exact-project-cohort', generation: 'synthetic', valid_until: '2099-01-01T00:00:00Z' } }))
  await page.route('**/api/opportunities/workspace?*', route => { workspaceRequests.push(new URL(route.request().url())); return route.fulfill({ json: response() }) })
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: accountNeed }))
  await page.goto('/?view=workspace')
  await expect(page.getByRole('heading', { name: 'Customers' })).toBeVisible()
  await expect(page.getByText('1 account')).toBeVisible()
  await page.getByRole('button', { name: 'View account details' }).click()
  await expect(page.getByRole('region', { name: 'Company Example operator' })).toBeVisible()
  await page.getByRole('button', { name: /Open project detail .*Test data center/ }).click()
  await expect(page).toHaveURL(/need=need-a/)
  await expect(page.locator('.cod-panel h2')).toContainText('Test data center')
  await page.locator('.cod-account-sources summary').click()
  await expect(page.locator('.cod-account-sources').getByRole('link', { name: 'Permit filing' })).toBeVisible()
  await page.getByRole('button', { name: '← Back to account', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Company Example operator' })).toBeVisible()
  expect(workspaceRequests).toEqual([])
})

test('flat results hide a contractor artifact and settled detail renders current evidence', async ({ page }) => {
  const row = { ...need, name: 'Austin permit 2026-127192 EP', browse_title: 'JLC Electrical Contractor corp · contractor' }
  const detail = {
    ...row,
    browse_title: undefined,
    title_company: undefined,
    title_company_role: undefined,
    evidence: [{ ...need.evidence[0], assessment_current: true, abstract: 'contractor_company_name: Current project electrician' }],
  }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => {
    const selectedNeed = new URL(route.request().url()).searchParams.has('need_id')
    return route.fulfill({ json: response(selectedNeed ? [detail] : [row]) })
  })
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: detail }))
  await page.route('**/api/projects/project-a/buying-chain', route => route.fulfill({ json: { project_id: 'project-a', status: 'unavailable', candidates: [], unresolved: [], runs: [], permit_summaries: [], policy_version: 'buying-chain-v2-permits' } }))
  await page.goto('/?view=workspace&projectBrowse=1&shortlist=0')
  const rowButton = page.locator('[data-need-row="need-a"]')
  await expect(rowButton).toHaveText('Project name not established')
  await rowButton.click()
  const detailHeading = page.locator('.cod-panel h2')
  await expect(detailHeading).toContainText('Austin permit 2026-127192 EP')
  await expect(detailHeading).not.toContainText('JLC Electrical Contractor corp · contractor')
  const relatedTab = page.getByRole('button', { name: 'Related', exact: true })
  await relatedTab.click()
  await expect(relatedTab).toHaveAttribute('aria-pressed', 'true')
  const related = page.locator('.cod-tab-content')
  await expect(related.getByRole('heading', { name: 'Related records' })).toBeVisible()
  await expect(related).toContainText('Current project electrician')
  await expect(related).not.toContainText('JLC Electrical Contractor corp · contractor')
})

test('Signal, Prospect and Lead details keep qualification clear without exposing disposition labels', async ({ page }) => {
  const rows = [
    { ...need, id: 'signal-action-now', name: 'Signal discovery project', tier: 'Signal', commercial_disposition: 'ACTION NOW' },
    { ...need, id: 'prospect-action-now', name: 'Prospect action project', tier: 'Prospect', commercial_disposition: 'ACTION NOW' },
    { ...need, id: 'lead-action-now', name: 'Lead action project', tier: 'Lead', commercial_disposition: 'ACTION NOW' },
    { ...need, id: 'signal-research', name: 'Signal research project', tier: 'Signal', commercial_disposition: 'RESEARCH' },
  ]
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: {
    ...response(rows), counts: { action_now: 3, research: 1, watch: 0, reject: 0 },
  } }))
  await page.route('**/api/opportunities/needs/*', route => route.fulfill({ json: rows.find(row => route.request().url().includes(row.id)) ?? need }))
  await page.goto('/?view=workspace&projectBrowse=1&shortlist=0')

  const rowFor = (id: string) => page.locator(`[data-need-row="${id}"]`)
  for (const [id, tier] of [['signal-action-now', 'Signal'], ['prospect-action-now', 'Prospect'], ['lead-action-now', 'Lead'], ['signal-research', 'Signal']]) {
    await expect(rowFor(id)).toBeVisible()
    await rowFor(id).click()
    await expect(page.locator('.cod-panel')).toContainText(tier)
    await expect(page.locator('.cod-panel')).not.toContainText('ACTION NOW')
  }

  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.locator('.cod-panel')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
})

test('off-page detail reload ignores historical company evidence and keeps the source name visible', async ({ page }) => {
  const detail = {
    ...need,
    name: 'Austin permit 2026-127192 EP',
    browse_title: undefined,
    title_company: undefined,
    title_company_role: undefined,
    activity: 'temporary-power',
    supported_action: 'New',
    evidence: [{ ...need.evidence[0], source_id: 'austin-building-permits', assessment_current: false, abstract: 'owner_company_name: Historical Owner LLC' }],
  }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => {
    const selectedNeed = new URL(route.request().url()).searchParams.has('need_id')
    return route.fulfill({ json: response(selectedNeed ? [detail] : []) })
  })
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: detail }))
  await page.route('**/api/projects/project-a/buying-chain', route => route.fulfill({ json: { project_id: 'project-a', status: 'unavailable', candidates: [], unresolved: [], runs: [], permit_summaries: [], policy_version: 'buying-chain-v2-permits' } }))
  await page.goto('/?view=workspace&projectBrowse=1&shortlist=0&need=need-a')
  await expect(page.locator('.cod-panel h2')).toContainText('Austin permit 2026-127192 EP')
  await page.getByRole('button', { name: 'Related', exact: true }).click()
  await expect(page.locator('.cod-tab-content')).toContainText('Related records')
  await expect(page.locator('.cod-tab-content')).toContainText('Historical support')
  await expect(page.locator('.cod-tab-content')).toContainText('owner_company_name: Historical Owner LLC')
  await page.getByRole('button', { name: 'Overview', exact: true }).click()
  await expect(page.locator('.cod-panel h2')).not.toContainText('Historical Owner LLC')
  await expect(page.locator('.cod-panel')).not.toContainText('Historical Owner LLC')
  await page.reload()
  await expect(page.locator('.cod-panel h2')).toContainText('Austin permit 2026-127192 EP')
  await expect(page.locator('.cod-panel')).not.toContainText('Historical Owner LLC')
})

test('workspace gives an honest retry state when the current cohort is unavailable', async ({ page }) => {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ status: 503, json: { detail: 'stale cohort' } }))
  await page.goto('/?groupBrowse=1&shortlist=0')
  await expect(page.getByRole('alert')).toContainText('Could not load accounts')
  await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible()
})

test('workspace selection switches to a full detail view on mobile and has a clear return', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: response() }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: need }))
  await page.goto('/?view=workspace&projectBrowse=1&shortlist=0')
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await page.getByRole('button', { name: /Test data center/ }).click()
  await expect(page.getByRole('button', { name: '← Opportunities' })).toBeVisible()
  await page.getByRole('button', { name: '← Opportunities' }).click()
  await expect(page.getByRole('heading', { name: 'Opportunities', exact: true })).toBeVisible()
})

test('legacy selected detail and lifecycle copy do not expose confidence labels', async ({ page }) => {
  const lifecycleNeed = { ...need, estimate_version: 'lifecycle-v1', estimate_basis: { confidence: 'high' }, lifecycle_state: 'operational' }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: response([lifecycleNeed]) }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: lifecycleNeed }))
  await page.goto('/?view=workspace&projectBrowse=1&shortlist=0&need=need-a')
  await expect(page.getByRole('heading', { name: 'Test data center' })).toBeVisible()
  await expect(page.locator('.cod-panel')).not.toContainText(/confidence/i)
  await expect(page.locator('body')).not.toContainText(/confidence/i)
})

test('groupBrowse selected detail omits confidence even when source data contains it', async ({ page }) => {
  const lifecycleNeed = { ...need, estimate_version: 'lifecycle-v1', estimate_basis: { confidence: 'high' }, lifecycle_state: 'operational' }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: { items: [], total: 0, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'group-empty', generation: 'fixture', valid_until: '2099-01-01T00:00:00Z' } }))
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: { items: [{ id: 'project-a', project_id: 'project-a', name: 'Example operator · Test data center', company: 'Example operator', location: 'Austin, TX', sector: 'data_centers', asset_type: 'data_center', priority_score: null, representative_need_id: 'need-a', need_count: 1, needs: [{ ...lifecycleNeed, tier: 'Signal' }], event: null, contact: [], contact_people: [], power_summary: null, power_summary_kind: 'unknown', next_action: null, updated_at: null }], total: 1, count_unit: 'projects', limit: 1, offset: 0, cohort_token: 'selected-project', generation: 'fixture', valid_until: '2099-01-01T00:00:00Z' } }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: lifecycleNeed }))
  await page.goto('/?view=workspace&projectBrowse=1&shortlist=0&need=need-a')
  await expect(page.getByRole('heading', { name: 'Test data center' })).toBeVisible()
  await expect(page.locator('.cod-panel')).not.toContainText(/confidence/i)
})



test('mobile history Back keeps the selected shell through delayed readback and focuses Back', async ({ page }) => {
  const needA = { ...need, id: 'need-a', project_id: 'project-a', name: 'ACS project' }
  const needB = { ...need, id: 'need-b', project_id: 'project-b', name: 'JLC project' }
  let bReads = 0
  let releaseSecondB!: () => void
  let signalSecondB!: () => void
  const secondBStarted = new Promise<void>(resolve => { signalSecondB = resolve })
  const secondBResponse = new Promise<void>(resolve => { releaseSecondB = resolve })
  await page.setViewportSize({ width: 1280, height: 844 })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: response([needA, needB]) }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: needA }))
  await page.route('**/api/opportunities/needs/need-b*', async route => {
    bReads += 1
    if (bReads === 2) { signalSecondB(); await secondBResponse }
    await route.fulfill({ json: needB })
  })
  await page.goto('/?view=workspace&projectBrowse=1&shortlist=0')
  await page.locator('[data-need-row="need-b"]').click()
  await expect(page.getByRole('heading', { name: 'JLC project' })).toBeVisible()
  await page.locator('[data-need-row="need-a"]').click()
  await expect(page.getByRole('heading', { name: 'ACS project' })).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: '← Opportunities' }).click()
  await secondBStarted
  await expect(page).toHaveURL(/need=need-b/)
  await expect(page.locator('.cod-panel')).toContainText('Loading verified opportunity detail')
  await expect(page.locator('.canonical-flat-results')).toBeHidden()
  const pendingBack = page.locator('.cod-back')
  await expect(pendingBack).toBeVisible()
  await expect(pendingBack).toBeEnabled()
  releaseSecondB()
  await expect(page.getByRole('heading', { name: 'JLC project' })).toBeVisible()
  await expect(page.getByRole('button', { name: '← Opportunities' })).toBeFocused()
})

test('desktop history readback does not steal Search focus after resizing to phone', async ({ page }) => {
  const needA = { ...need, id: 'need-a', name: 'ACS project' }
  const needB = { ...need, id: 'need-b', project_id: 'project-b', name: 'JLC project' }
  await page.setViewportSize({ width: 1280, height: 844 })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: response([needA, needB]) }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: needA }))
  await page.route('**/api/opportunities/needs/need-b*', route => route.fulfill({ json: needB }))
  await page.goto('/?view=workspace&projectBrowse=1&shortlist=0')
  await page.locator('[data-need-row="need-b"]').click()
  await expect(page.getByRole('heading', { name: 'JLC project' })).toBeVisible()
  await page.locator('[data-need-row="need-a"]').click()
  await expect(page.getByRole('heading', { name: 'ACS project' })).toBeVisible()
  await page.goBack()
  await expect(page.getByRole('heading', { name: 'JLC project' })).toBeVisible()
  const more = page.locator('.wh-account summary')
  await more.focus()
  await expect(more).toBeFocused()
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(more).toBeFocused()
  await expect(page.locator('.canonical-flat-results')).toBeHidden()
})

test('mobile Back can leave a held history readback and late response cannot restore it', async ({ page }) => {
  const needA = { ...need, id: 'need-a', project_id: 'project-a', name: 'ACS project' }
  const needB = { ...need, id: 'need-b', project_id: 'project-b', name: 'JLC project' }
  let bReads = 0
  let releaseSecondB!: () => void
  let signalSecondB!: () => void
  let finishSecondB!: () => void
  const secondBStarted = new Promise<void>(resolve => { signalSecondB = resolve })
  const secondBResponse = new Promise<void>(resolve => { releaseSecondB = resolve })
  const secondBFinished = new Promise<void>(resolve => { finishSecondB = resolve })
  await page.setViewportSize({ width: 1280, height: 844 })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: response([needA, needB]) }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: needA }))
  await page.route('**/api/opportunities/needs/need-b*', async route => {
    bReads += 1
    if (bReads === 2) {
      signalSecondB()
      await secondBResponse
      try { await route.fulfill({ json: needB }) } catch { /* The selected-detail request is expected to be aborted by Back. */ }
      finishSecondB()
      return
    }
    await route.fulfill({ json: needB })
  })
  await page.goto('/?view=workspace&projectBrowse=1&shortlist=0')
  await page.locator('[data-need-row="need-b"]').click()
  await expect(page.getByRole('heading', { name: 'JLC project' })).toBeVisible()
  await page.locator('[data-need-row="need-a"]').click()
  await expect(page.getByRole('heading', { name: 'ACS project' })).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: '← Opportunities' }).click()
  await secondBStarted
  const pendingBack = page.locator('.cod-back')
  await expect(pendingBack).toBeVisible()
  await expect(pendingBack).toBeEnabled()
  await pendingBack.click()
  await expect(page).toHaveURL(/view=workspace/)
  await expect(page).not.toHaveURL(/need=need-b/)
  await expect(page.locator('.canonical-flat-results')).toBeVisible()
  releaseSecondB()
  await secondBFinished
  await expect(page).not.toHaveURL(/need=need-b/)
  await expect(page.getByRole('heading', { name: 'JLC project' })).toHaveCount(0)
  await expect(page.locator('.canonical-flat-results')).toBeVisible()
})

test('mobile failed history readback keeps Retry and Back available', async ({ page }) => {
  const needA = { ...need, id: 'need-a', project_id: 'project-a', name: 'ACS project' }
  const needB = { ...need, id: 'need-b', project_id: 'project-b', name: 'JLC project' }
  let bReads = 0
  await page.setViewportSize({ width: 1280, height: 844 })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: response([needA, needB]) }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: needA }))
  await page.route('**/api/opportunities/needs/need-b*', route => {
    bReads += 1
    return bReads === 2
      ? route.fulfill({ status: 503, json: { detail: 'selected detail temporarily unavailable' } })
      : route.fulfill({ json: needB })
  })
  await page.goto('/?view=workspace&projectBrowse=1&shortlist=0')
  await page.locator('[data-need-row="need-b"]').click()
  await expect(page.getByRole('heading', { name: 'JLC project' })).toBeVisible()
  await page.locator('[data-need-row="need-a"]').click()
  await expect(page.getByRole('heading', { name: 'ACS project' })).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: '← Opportunities' }).click()
  await expect(page.getByRole('alert')).toContainText('could not complete this request (503)')
  await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible()
  const errorBack = page.locator('.cod-back')
  await expect(errorBack).toBeVisible()
  await expect(errorBack).toBeEnabled()
  await errorBack.click()
  await expect(page).not.toHaveURL(/need=need-b/)
  await expect(page.locator('.canonical-flat-results')).toBeVisible()
})

test('mobile selected detail keeps the compact header and clear return', async ({ page }) => {
  const realistic = {
    ...need,
    name: 'North Austin Advanced Manufacturing and Logistics Campus Phase Two',
    location: 'North Austin, Texas · approximate site location',
    required_mw: 'Unknown',
    commercial_next_action: 'Confirm the electrical package owner and expected utility service date.',
    commercial_reason: 'A retained source supports construction activity, but does not establish the facility-specific load or available supply.',
    missing_facts: ['Activity-specific load', 'Utility service timing', 'Suitable supply availability'],
  }
  await page.setViewportSize({ width: 390, height: 844 })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: response([realistic]) }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: realistic }))
  await page.goto('/?view=workspace&projectBrowse=1&shortlist=0')
  await page.locator('[data-need-row="need-a"]').click()
  const action = page.locator('.cod-panel')
  await expect(action).toBeInViewport()
  await expect(action.getByRole('button', { name: 'Add to Pursuit' })).toBeVisible()
  await expect(page.locator('.canonical-header .global-search label > span')).toBeHidden()
  const brand = page.locator('.canonical-header__brand')
  await expect(brand).toBeVisible()
  expect(await brand.evaluate(node => node.getBoundingClientRect().width)).toBeLessThanOrEqual(await brand.evaluate(node => node.parentElement!.getBoundingClientRect().width))
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  await expect(page.getByRole('button', { name: '← Opportunities' })).toBeVisible()
})





test('switching selected needs does not invoke title enrichment', async ({ page }) => {
  const second = { ...need, id: 'need-b', project_id: 'project-b', name: 'Second project' }
  const titleRequests: string[] = []
  page.on('request', request => { if (request.url().includes('/title')) titleRequests.push(request.url()) })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: response([need, second]) }))
  await page.route('**/api/opportunities/needs/*', route => route.fulfill({ json: route.request().url().includes('need-b') ? second : need }))
  await page.goto('/?view=workspace&projectBrowse=1&shortlist=0')
  await page.locator('[data-need-row="need-a"]').click()
  await page.locator('[data-need-row="need-b"]').click()
  await expect(page.getByRole('heading', { name: 'Second project' })).toBeVisible()
  await page.getByRole('button', { name: 'Related', exact: true }).click()
  await expect(page.getByRole('button', { name: /enrich title/i })).toHaveCount(0)
  expect(titleRequests).toEqual([])
})

test('selected opportunity uses its returned project title without enrichment requests', async ({ page }) => {
  const first = { ...need, id: 'need-a', name: 'Permit filing A', browse_title: 'Cedar Ridge campus', commercial_organization: null }
  const second = { ...need, id: 'need-b', project_id: 'project-b', name: 'Permit filing B', browse_title: 'West Texas buildout', commercial_organization: null }
  const titleRequests: string[] = []
  page.on('request', request => { if (request.url().includes('/title')) titleRequests.push(request.url()) })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: response([first, second]) }))
  await page.route('**/api/opportunities/needs/*', route => route.fulfill({ json: route.request().url().includes('need-b') ? second : first }))
  await page.goto('/?view=workspace&projectBrowse=1&shortlist=0')
  await page.locator('[data-need-row="need-a"]').click()
  await expect(page.getByRole('heading', { name: 'Cedar Ridge campus' })).toBeVisible()
  await page.locator('[data-need-row="need-b"]').click()
  await expect(page.getByRole('heading', { name: 'West Texas buildout' })).toBeVisible()
  expect(titleRequests).toEqual([])
})

test('project-sector deep links stay on Opportunities and a changed cohort resets pagination', async ({ page }) => {
  const requested: URL[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', async route => {
    const url = new URL(route.request().url()); requested.push(url)
    if (url.searchParams.get('cohort_token') === 'old') return route.fulfill({ status: 409, json: { detail: 'cohort changed' } })
    return route.fulfill({ json: response() })
  })
  await page.goto('/?view=workspace&projectBrowse=1&shortlist=0&sector=oil_gas&offset=25&cohort_token=old')
  await expect(page.getByRole('heading', { name: 'Opportunities', exact: true })).toBeVisible()
  await expect.poll(() => requested.length).toBeGreaterThan(1)
  expect(requested[0].searchParams.get('sector')).toBe('oil_gas')
  expect(requested[0].searchParams.get('cohort_token')).toBe('old')
  await expect.poll(() => requested.some(url => Number(url.searchParams.get('offset') ?? 0) === 0 && !url.searchParams.has('cohort_token'))).toBe(true)
})

test('stale list responses cannot replace a newer filter result', async ({ page }) => {
  let resolveOld!: () => void
  const oldResponse = new Promise<void>(resolve => { resolveOld = resolve })
  const requested: URL[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', async route => {
    const url = new URL(route.request().url()); requested.push(url)
    const search = url.searchParams.get('search')
    if (search === 'Old') { await oldResponse; return route.fulfill({ json: response([{ ...need, id: 'old', name: 'Stale result' }]) }) }
    if (search === 'New') return route.fulfill({ json: response([{ ...need, id: 'new', name: 'Current result' }]) })
    return route.fulfill({ json: response() })
  })
  await page.goto('/?view=workspace&projectBrowse=1&shortlist=0')
  const search = page.getByRole('textbox', { name: 'Search opportunities' })
  await search.fill('Old')
  await expect.poll(() => requested.some(url => url.searchParams.get('search') === 'Old')).toBe(true)
  await search.fill('New')
  await expect(page.getByRole('button', { name: /Current result/ })).toBeVisible()
  resolveOld()
  await expect(page.getByRole('button', { name: /Stale result/ })).toHaveCount(0)
})

test('a failed project search hides rows, counts, and pagination from the prior cohort', async ({ page }) => {
  const oldCohortAction = 'Austin cohort only action'
  const selectedRow = { ...need, name: 'Austin retained row', commercial_next_action: oldCohortAction }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => {
    const search = new URL(route.request().url()).searchParams.get('search')
    if (search === 'Houston') return route.fulfill({ status: 503, json: { detail: 'project results unavailable' } })
    if (new URL(route.request().url()).searchParams.has('need_id')) return route.fulfill({ json: response([{ ...selectedRow, name: 'Fresh canonical detail' }]) })
    return route.fulfill({ json: response([selectedRow]) })
  })
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: { ...need, name: 'Fresh canonical detail' } }))
  await page.goto('/?view=workspace&projectBrowse=1&shortlist=0')
  await expect(page.getByRole('button', { name: /Austin retained row/ })).toBeVisible()
  await expect(page.getByText(oldCohortAction)).toBeVisible()
  await page.locator('[data-need-row="need-a"]').click()
  await expect(page.getByRole('heading', { name: 'Fresh canonical detail' })).toBeVisible()
  await page.getByRole('textbox', { name: 'Search opportunities' }).fill('Houston')
  await expect(page.getByRole('alert')).toContainText('Could not load projects (503)')
  await expect(page.getByText(oldCohortAction)).toHaveCount(0)
  await expect(page.getByRole('button', { name: /Austin retained row/ })).toHaveCount(0)
  await expect(page.locator('.cfr-table-wrap')).toHaveCount(0)
  await expect(page.locator('.cfr-paging')).toHaveCount(0)
})

test('ordinary project results hide score values while keeping source-backed reasons and ordering', async ({ page }) => {
  const ranked = { ...need, rank_score: 8, rank_reasons: ['Near-term start', 'Supported project scale'], rank_version: 'rank-v1', commercial_reason: 'A retained construction filing supports near-term review.' }
  const unranked = { ...need, id: 'need-b', project_id: 'project-b', name: 'Unranked second project', commercial_reason: 'A separate retained filing supports review.' }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: response([ranked, unranked]) }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: ranked }))
  await page.goto('/?view=workspace&projectBrowse=1&shortlist=0&section=evidence')
  const rows = page.locator('.cfr-table tbody tr')
  await expect(rows).toHaveCount(2)
  await expect(rows.nth(0)).toContainText('A retained construction filing supports near-term review.')
  await expect(rows.nth(0).locator('[data-need-row]')).toHaveAttribute('data-need-row', 'need-a')
  await expect(rows.nth(1).locator('[data-need-row]')).toHaveAttribute('data-need-row', 'need-b')
  await expect(page.locator('body')).not.toContainText('Canonical rank score')
  await expect(page.locator('body')).not.toContainText('rank-v1')
})









test('tablet workspace has no horizontal overflow and retains readable layout', async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 900 })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: response() }))
  await page.goto('/?view=workspace&projectBrowse=1&shortlist=0&section=evidence')
  await expect(page.getByRole('heading', { name: 'Opportunities', exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(900)
})

test('tablet direct selection keeps detail and header reachable and restores the queue', async ({ page }) => {
  await page.setViewportSize({ width: 768, height: 1024 })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: response() }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: need }))
  await page.goto('/?view=workspace&projectBrowse=1&shortlist=0&need=need-a')
  const identity = page.getByRole('heading', { name: 'Test data center' })
  await expect(identity).toBeVisible()
  const bounds = await identity.boundingBox()
  expect(bounds!.y).toBeGreaterThanOrEqual(0)
  expect(bounds!.y + bounds!.height).toBeLessThan(1024)
  for (const control of [page.locator('.canonical-header__brand'), page.getByRole('navigation', { name: 'Primary navigation' }), page.locator('.wh-account > summary')]) {
    const box = await control.boundingBox()
    expect(box).not.toBeNull()
    expect(box!.x).toBeGreaterThanOrEqual(0)
    expect(box!.x + box!.width).toBeLessThanOrEqual(768)
  }
  await page.getByRole('button', { name: '← Opportunities' }).click()
  const row = page.locator('[data-need-row="need-a"]')
  await expect(row).toBeVisible()
  await row.click()
  await expect(identity).toBeVisible()
})

test('legacy flat project results remain available explicitly and keep routine research queues out of the workspace', async ({ page }) => {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: { items: [], total: 0, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'default-flat', generation: 'synthetic', valid_until: '2099-01-01T00:00:00Z' } }))
  await page.goto('/?view=workspace&projectBrowse=1&shortlist=0')
  await expect(page.getByRole('heading', { name: 'Opportunities', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Notifications' })).toHaveCount(0)
  await expect(page.locator('.wh-tools')).toHaveCount(0)
  await expect(page.locator('.brand-kpi')).toHaveCount(0)
  await expect(page.getByRole('navigation', { name: 'Primary navigation' }).getByRole('button')).toHaveText(['Opportunities', 'Companies', 'Pursuits', 'Reports'])
  for (const width of [768, 390]) {
    await page.setViewportSize({ width, height: 900 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
  }
})

test('project type filters canonical oil-and-gas assets, carries cohorts, and resets pagination', async ({ page }) => {
  const assets = [
    ...Array.from({ length: 10 }, (_, index) => ({ ...need, id: `gas-${index}`, name: `Gas plant ${index}`, asset_type: 'gas_processing_plant', sector: 'oil_gas' })),
    ...Array.from({ length: 10 }, (_, index) => ({ ...need, id: `compressor-${index}`, name: `Compressor ${index}`, asset_type: 'compressor_station', sector: 'oil_gas' })),
    ...Array.from({ length: 10 }, (_, index) => ({ ...need, id: `well-${index}`, name: `Upstream well ${index}`, asset_type: 'upstream_well', sector: 'oil_gas' })),
    { ...need, id: 'data-center', name: 'Data center', asset_type: 'data_center', sector: 'data_centers' },
    { ...need, id: 'unknown-asset', name: 'Unclassified asset', asset_type: 'unknown', sector: 'unknown' },
  ]
  const requests: URL[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', async route => {
    const url = new URL(route.request().url())
    requests.push(url)
    const sector = url.searchParams.get('sector')
    const selected = sector === 'oil_gas'
      ? assets.filter(item => item.sector === 'oil_gas')
      : sector === 'data_centers' ? assets.filter(item => item.sector === 'data_centers') : assets
    const offset = Number(url.searchParams.get('offset') ?? 0)
    const items = selected.slice(offset, offset + 25)
    const cohort = sector === 'oil_gas' ? 'oil-gas-cohort' : sector === 'data_centers' ? 'data-center-cohort' : 'all-cohort'
    await route.fulfill({ json: { ...response(items), total: selected.length, offset, next_offset: offset + items.length < selected.length ? offset + items.length : null, cohort_token: cohort } })
  })
  await page.goto('/?view=workspace&projectBrowse=1&shortlist=0&sector=oil_gas')
  await expect(page.getByLabel('Project type')).toHaveValue('oil_gas')
  await expect.poll(() => requests.at(-1)?.searchParams.get('sector')).toBe('oil_gas')
  await expect(page.locator('.canonical-flat-results [data-need-row]')).toHaveCount(25)
  await expect(page.locator('[data-need-row="data-center"]')).toHaveCount(0)
  await expect(page.locator('[data-need-row="unknown-asset"]')).toHaveCount(0)
  await expect(page.locator('.cfr-paging')).toContainText('of 30')
  await page.locator('.cfr-paging').getByRole('button', { name: 'Next' }).click()
  await expect.poll(() => requests.at(-1)?.searchParams.get('offset')).toBe('25')
  await expect.poll(() => requests.at(-1)?.searchParams.get('cohort_token')).toBe('oil-gas-cohort')
  await page.getByLabel('Project type').selectOption('data_centers')
  await expect.poll(() => requests.at(-1)?.searchParams.get('sector')).toBe('data_centers')
  await expect.poll(() => requests.at(-1)?.searchParams.get('offset')).toBe('0')
  await expect(requests.at(-1)?.searchParams.has('cohort_token')).toBe(false)
  await expect(page.getByLabel('Project type')).toHaveValue('data_centers')
  await expect(page.locator('[data-need-row="data-center"]')).toBeVisible()
  await page.reload()
  await expect.poll(() => requests.at(-1)?.searchParams.get('sector')).toBe('data_centers')
  await expect.poll(() => requests.at(-1)?.searchParams.get('offset')).toBe('0')
  await expect(requests.at(-1)?.searchParams.has('cohort_token')).toBe(false)
})

test('Power gap shows only backend-qualified ranges and keeps null or conflicted gaps unknown', async ({ page }) => {
  const qualified = { ...need, id: 'need-qualified', name: 'Qualified power need', tier: 'Lead', required_mw: '4–6 MW', supply: '2–3 MW', qualified_remaining_gap: { required_mw_min: '4', required_mw_max: '6', available_mw_min: '2', available_mw_max: '3', remaining_mw_min: '1', remaining_mw_max: '4', start_window: 'Q2 2027', duration: '90–120 days', basis_quote: 'Service letter states 2–3 MW available.', value_kind: 'Derived', calculation: 'range intersection from supported demand and supply', version: 'qual-v1' }, qualification_version: 'qual-v1' }
  const unknown = { ...need, id: 'need-unknown', name: 'Unknown power need', qualified_remaining_gap: null, qualification_version: null }
  const conflict = { ...need, id: 'need-conflict', name: 'Conflicted power need', conflict_state: 'CONFLICT', qualified_remaining_gap: null, qualification_version: null }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: response([qualified, unknown, conflict]) }))
  await page.route('**/api/opportunities/needs/*', route => {
    const id = new URL(route.request().url()).pathname.split('/').pop()
    return route.fulfill({ json: [qualified, unknown, conflict].find(value => value.id === id) ?? need })
  })
  await page.goto('/?view=workspace&projectBrowse=1&shortlist=0&section=power-gap&need=need-qualified')
  await expect(page.getByText(/Qualified remaining gap: 1–4 MW/)).toBeVisible()
  await page.goto('/?view=workspace&projectBrowse=1&shortlist=0&section=power-gap&need=need-unknown')
  await expect(page.getByText('Supply unknown or no supported remaining gap is available for this need.')).toBeVisible()
  await page.goto('/?view=workspace&projectBrowse=1&shortlist=0&section=power-gap&need=need-conflict')
  await expect(page.getByText('Supply unknown or no supported remaining gap is available for this need.')).toBeVisible()
  await expect(page.locator('.wh-detail')).toContainText('CONFLICT')
})

test('utility service status stays distinct from an energization date and facility demand stays separate from activity size', async ({ page }) => {
  const card = {
    policy_version: 'opportunity-intelligence-v1', need_id: need.id, project_id: need.project_id,
    input_fingerprint: 'a'.repeat(64), qualification: 'Signal', disposition: 'RESEARCH', fields: [
      { key: 'facility_demand', label: 'Facility Demand', section: 'power', value: null, status: 'Not publicly available', basis: 'No facility-wide demand evidence.' },
      { key: 'energization', label: 'Utility service status', section: 'power', value: 'Utility service application filed', status: 'Verified', basis: 'Public utility filing; no date stated.' },
    ], contacts: [], next_contact_path: 'Unknown', next_action: 'Verify utility timing.', research_gaps: [],
    completeness: { supported: 1, total: 2, percent: 50 }, last_intelligence_update: null, power_gap: null, evidence: [], research_enabled: false,
  }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: response([{ ...need, required_mw: '18 MW' }]) }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: { ...need, required_mw: '18 MW', intelligence_card: card } }))
  await page.goto('/?view=workspace&projectBrowse=1&shortlist=0&section=power-gap&need=need-a')
  const metrics = page.getByRole('region', { name: 'Power need metrics' })
  await expect(metrics).toContainText('Facility DemandNot established')
  await expect(metrics).not.toContainText('18 MW')
  await expect(metrics).toContainText('Utility EnergizationUtility service application filed')
  await expect(metrics).toContainText('Public utility filing; no date stated.')
  await expect(metrics).not.toContainText('date not established')
})

for (const width of [1280, 390]) {
  test(`canonical detail preserves verified contact evidence and source context at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    const source = { reference: 'evidence:test', title: 'Official project notice', url: 'https://example.test/project', source_date: '2026-10-20', assessed_at: '2026-10-22T10:00:00Z', retained_evidence_id: 'test', content_hash: 'a'.repeat(64), passage: 'Example Owner is developing the site.', extraction_method: 'Official notice', verification_status: 'Current retained support' }
    const card = {
      policy_version: 'opportunity-intelligence-v1', need_id: need.id, project_id: need.project_id,
      input_fingerprint: 'a'.repeat(64), qualification: 'Signal', disposition: 'RESEARCH',
      fields: [{ key: 'customer', label: 'Customer / end user', section: 'identity', value: 'Example Owner', status: 'Evidence-supported', basis: 'Current owner relationship.', sources: [source] }],
      contacts: [
        { claim_id: 'party', company: 'Example Owner', name: null, title: null, role: 'owner developer', responsibility: 'General company contact path', purchasing_authority: 'Requires confirmation for this power package', methods: [{ kind: 'phone', value: '+1 512 555 0100', href: 'tel:+15125550100', source_url: source.url, verified_at: '2026-10-20T10:00:00Z' }, { kind: 'phone', value: '+1 512 555 0101', href: 'tel:+15125550101', source_url: source.url, verified_at: '2026-10-25T10:00:00Z' }], sources: [source] },
        { claim_id: 'party-source-only', company: 'Example Owner', name: null, title: null, role: 'procurement', responsibility: 'Inferred likely role', purchasing_authority: 'Requires confirmation for this power package', methods: [], sources: [source] },
        { claim_id: 'unknown-date', company: 'Example Owner', name: 'Taylor Unknown', title: 'Operations Director', role: 'operations', responsibility: 'Organizational role', purchasing_authority: 'Requires confirmation for this power package', methods: [{ kind: 'email', value: 'unknown@example.test', href: 'mailto:unknown@example.test', verified_at: 'invalid-date' }], sources: [] },
      ],
      next_contact_path: 'Confirm power procurement with the company office.', next_action: 'Verify the activity-specific power window.',
      research_gaps: [{ key: 'start', label: 'Power needed', section: 'power', value: null, status: 'Research in progress', basis: 'No supported date yet.', research_category: 'timing', research_status: 'NOT_SCHEDULED', sources: [] }],
      completeness: { supported: 1, total: 2, percent: 50, basis: 'Independent of qualification' },
      last_intelligence_update: '2026-10-20T10:00:00Z', power_gap: null, evidence: [source], research_enabled: true,
      power_schedule: {
        status: 'UNRESOLVED', basis: 'Operator-reported phased work plan',
        fact_refs: [{ fact_version_id: 'schedule-v1', content_hash: 'b'.repeat(64), authority: 'User-confirmed', source_reference: 'utility-letter-1', confirmed_at: '2026-10-20T10:00:00Z', reporter_name: 'A. Operator', reporter_organization: 'Example Owner', reporter_role: 'Project Engineer', source_quote: 'January commissioning schedule.' }],
        supplies: [
          { supply_id: 'utility-service', start_date: '2027-01-15', end_date: '2027-02-01', mw_min: '4', mw_max: '5', state: 'committed', suitability: 'suitable', source_kind: 'utility_grid', service_ready_date: '2027-01-15', date_basis: 'Utility service letter', basis: 'Committed service', source_reference: 'utility-letter-1' },
          { supply_id: 'future-grid-option', start_date: '2027-03-01', end_date: '2027-04-01', mw_min: '4', mw_max: '5', state: 'proposed', suitability: 'suitable', source_kind: 'utility_grid', service_ready_date: '2027-03-15', date_basis: 'Draft utility schedule', basis: 'Proposed service', source_reference: null },
        ],
        segments: [
          { phase_id: 'commissioning', start_date: '2027-01-01', end_date: '2027-02-01', demand_min_mw: '10', demand_max_mw: '12', demand_basis: 'Owner-described package', supply_min_mw: null, supply_max_mw: null, residual_min_mw: null, residual_max_mw: null, supply_ids: [], unresolved_supply_ids: [], supply_basis: [], unresolved_reason: 'Other supply is unknown', scenario: 'base' },
          { phase_id: 'future phase', start_date: '2027-03-01', end_date: '2027-03-15', demand_min_mw: '10', demand_max_mw: '12', demand_basis: 'Owner-described package', supply_min_mw: '0', supply_max_mw: '0', residual_min_mw: '10', residual_max_mw: '12', supply_ids: [], unresolved_supply_ids: [], supply_basis: [], unresolved_reason: null, scenario: 'base' },
          { phase_id: 'future phase', start_date: '2027-03-15', end_date: '2027-04-01', demand_min_mw: '10', demand_max_mw: '12', demand_basis: 'Owner-described package', supply_min_mw: '0', supply_max_mw: '0', residual_min_mw: '10', residual_max_mw: '12', supply_ids: [], unresolved_supply_ids: [], supply_basis: [], unresolved_reason: null, scenario: 'base' },
          { phase_id: 'future phase', start_date: '2027-03-15', end_date: '2027-04-01', demand_min_mw: '10', demand_max_mw: '12', demand_basis: 'Owner-described package', supply_min_mw: '4', supply_max_mw: '5', residual_min_mw: '5', residual_max_mw: '8', supply_ids: ['future-grid-option'], unresolved_supply_ids: [], supply_basis: ['future-grid-option: Proposed service (Draft utility schedule)'], unresolved_reason: null, scenario: 'alternative' },
        ],
      },
    }
    await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
    await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: response() }))
    await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: {
      ...need, asset_type: 'gas_processing_plant', lifecycle_state: 'operation',
      expected_next_milestone: 'Integrity inspection', expected_power_event: 'Compression upgrade',
      time_to_power_window: 'Within 90 days', estimate_version: 'lifecycle-v2',
      estimate_basis: { confidence: 'medium' },
      lifecycle_timeline: [{ event_type: 'permit', date: '2026-10-20', state: 'permit', evidence_url: source.url, value_kind: 'reported', current: true, published_at: '2026-10-20' }],
      monitoring_requirements: ['Monitor compressor replacement schedule'], lifecycle_open_questions: ['Confirm the power package owner'],
      rank_score: 8, rank_version: 'rank-v1', rank_reasons: ['Near-term power event', 'Known industrial asset'],
      intelligence_card: card,
    } }))
    const researchWrites: string[] = []
    page.on('request', request => { if (request.url().includes('/autonomous-research') && request.method() !== 'GET') researchWrites.push(request.method()) })
    await page.route('**/api/commercial/triage/need-a/autonomous-research', route => route.fulfill({ json: { items: [] } }))
    await page.goto('/?view=workspace&projectBrowse=1&shortlist=0&need=need-a')
    const detail = page.locator('.cod-panel')
    await expect(detail.getByRole('heading', { name: 'Example operator — Test data center' })).toBeVisible()
    await expect(detail.getByRole('region', { name: 'Why this matters' })).toContainText('Load and supply remain unknown.')
    await expect(detail.getByRole('region', { name: 'Decision maker or contact' })).toContainText('Example Owner')
    await expect(detail.getByRole('link', { name: 'Call +1 512 555 0100' })).toHaveAttribute('href', 'tel:+15125550100')
    await expect(detail.getByRole('region', { name: 'Decision maker or contact' })).toContainText('Source checked')
    await expect(detail).not.toContainText('unknown@example.test')
    await expect(detail).not.toContainText('Invalid Date')
    await expect(detail).not.toContainText('RESEARCH')
    await expect(detail).not.toContainText('Canonical rank score')
    await expect(detail).not.toContainText('rank-v1')
    const recentEvidence = detail.getByRole('region', { name: 'Recent evidence' })
    await expect(recentEvidence).toContainText('Official project notice')
    await expect(recentEvidence).toContainText('2026-10-20')
    await expect(recentEvidence).toContainText('Current retained support')
    expect(researchWrites).toEqual([])
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    await page.screenshot({ path: testInfo.outputPath(`intelligence-card-${width}.png`), fullPage: true })
  })
}
