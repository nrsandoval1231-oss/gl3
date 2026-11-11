import { expect, test } from '@playwright/test'
import { mockDemandSummary } from './mock-demand-summary'

const validUntil = new Date(Date.now() + 60 * 60 * 1000).toISOString()

test('multi-opportunity account requires an explicit eligible choice and does not auto-create a Pursuit', async ({ page }) => {
  let mutations = 0
  const featured = {
    id: 'project-featured', project_id: 'project-featured', name: 'Synthetic Campus Phase 1', company: 'Synthetic Operator', customer_identity_id: 'company-synthetic',
    location: 'Austin, TX', sector: 'data_centers', asset_type: 'data_center', priority_score: null, representative_need_id: 'need-a', need_count: 2,
    eligible_need_ids: ['need-a', 'need-b'], needs: [{ id: 'need-a', name: 'Phase 1 construction' }, { id: 'need-b', name: 'Phase 2 expansion' }],
    event: { kind: 'construction', label: 'Synthetic construction planned', date: null, source: null, evidence_refs: [] }, contact: [],
    power_summary: null, power_summary_kind: 'unknown', next_action: null,
    shortlist_assessment: { eligible: true, reasons: [], evidence_refs: [], why_now: 'Synthetic construction is planned.', next_step: 'Confirm the commissioning window.' }, updated_at: null,
  }
  const group = { id: 'cg_synthetic', name: 'Synthetic Operator', role: 'operator', group_kind: 'resolved_identity', project_count: 1, relevant_project_count: 1, total_known_project_count: 1, need_count: 2, eligible_need_count: 2, pursued_eligible_need_count: 1, sectors: ['data_centers'], featured_project: featured }
  const projectPage = { items: [featured], total: 1, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'child-current', generation: 'synthetic', valid_until: validUntil }

  await mockDemandSummary(page)
  await page.route(url => new URL(url).pathname.startsWith('/api/'), async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (url.pathname === '/api/opportunities/groups') return route.fulfill({ json: { items: [group], total: 1, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'groups-current', generation: 'synthetic' } })
    if (url.pathname === '/api/opportunities/groups/cg_synthetic/open') return route.fulfill({ json: { group, projects: projectPage, parent_cohort_token: 'parent-current', generation: 'synthetic', valid_until: validUntil } })
    if (url.pathname === '/api/opportunities/groups/cg_synthetic/projects') return route.fulfill({ json: { ...projectPage, parent_cohort_token: 'parent-current' } })
    if (url.pathname === '/api/commercial-pursuits') {
      if (route.request().method() !== 'GET') mutations += 1
      return route.fulfill({ json: { items: [], counts: { total: 0, active: 0, needs_attention: 0 }, total_matching: 0, has_more: false, next_offset: null } })
    }
    return route.fulfill({ status: 404, json: { detail: 'Synthetic fixture has no matching route.' } })
  })

  await page.goto('/?view=workspace')
  await expect(page.getByText('1 of 2 opportunities in Pursuits')).toBeVisible()
  await page.getByRole('button', { name: 'Choose opportunity' }).click()
  const detail = page.getByRole('region', { name: 'Company Synthetic Operator' })
  const choice = detail.getByRole('combobox', { name: 'Choose an opportunity for Synthetic Campus Phase 1' })
  await expect(choice).toBeVisible()
  await expect(choice.locator('option')).toHaveText(['Phase 1 construction', 'Phase 2 expansion'])
  await choice.selectOption('need-b')
  await expect(detail.getByRole('button', { name: 'Add to Pursuit' })).toBeVisible()
  expect(mutations).toBe(0)
})

test('legacy UUID account URL translates to the canonical account without requesting the old workspace list', async ({ page }) => {
  const workspaceCalls: string[] = []
  const selectedNeed = { id: 'need-legacy', project_id: 'project-legacy', name: 'Synthetic legacy project', location: 'Austin, TX', tier: 'Signal', workflow_status: 'New', activity: 'construction', rationale: 'Synthetic evidence supports review.', signal_evidence_state: 'active', conflict_state: 'Not assessed', required_mw: null, supply: 'Unknown', start_window: null, duration: null, evidence: [], missing_facts: [], project_identity_key: 'synthetic', commercial_disposition: 'RESEARCH', commercial_reason: 'Demand remains unknown.', commercial_next_question: 'Who owns the scope?', commercial_next_action: 'Review retained evidence.', commercial_organization: null }
  const group = { id: 'cg_legacy', name: 'Synthetic Legacy Account', role: 'operator', group_kind: 'resolved_identity', project_count: 1, relevant_project_count: 1, total_known_project_count: 1, need_count: 1, eligible_need_count: 1, pursued_eligible_need_count: 0, sectors: ['data_centers'] }
  await mockDemandSummary(page)
  await page.route(url => new URL(url).pathname.startsWith('/api/'), async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (url.pathname === '/api/companies/company-legacy/account') return route.fulfill({ json: { id: 'cg_legacy', name: group.name, group_kind: 'resolved_identity' } })
    if (url.pathname === '/api/opportunities/workspace') { workspaceCalls.push(url.pathname); return route.fulfill({ status: 500, json: {} }) }
    if (url.pathname === '/api/opportunities/groups') return route.fulfill({ json: { items: [group], total: 1, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'legacy-groups', generation: 'synthetic' } })
    if (url.pathname === '/api/opportunities/groups/cg_legacy/open') return route.fulfill({ json: { group, projects: { items: [], total: 0, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'legacy-projects', generation: 'synthetic', valid_until: validUntil }, parent_cohort_token: 'legacy-parent', generation: 'synthetic', valid_until: validUntil } })
    if (url.pathname === '/api/opportunities/needs/need-legacy') return route.fulfill({ json: selectedNeed })
    if (url.pathname === '/api/projects/project-legacy/account') return route.fulfill({ json: group })
    if (url.pathname === '/api/opportunities/projects') return route.fulfill({ json: { items: [{ id: 'asset-legacy', project_id: 'project-legacy', project_ids: ['project-legacy'], name: selectedNeed.name, company: group.name, location: selectedNeed.location, sector: 'data_centers', asset_type: 'data_center', priority_score: null, representative_need_id: 'need-legacy', needs: [], need_count: 1, event: null, contact: [], power_summary: null, power_summary_kind: 'unknown', next_action: null, updated_at: null }], total: 1, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'legacy-projects-detail', generation: 'synthetic', valid_until: validUntil } })
    if (url.pathname === '/api/commercial-pursuits') return route.fulfill({ json: { items: [], counts: { total: 0, active: 0, needs_attention: 0 }, total_matching: 0, has_more: false, next_offset: null } })
    return route.fulfill({ status: 404, json: {} })
  })

  await page.goto('/?view=workspace&accountBrowse=1&account=company-legacy&project=project-legacy&need=need-legacy')
  await expect(page.getByRole('region', { name: 'Company Synthetic Legacy Account' })).toBeVisible()
  await expect.poll(() => new URL(page.url()).searchParams.get('account')).toBe('cg_legacy')
  const params = new URL(page.url()).searchParams
  expect(params.get('groupBrowse')).toBe('1')
  expect(params.get('accountBrowse')).toBeNull()
  expect(params.get('project')).toBe('project-legacy')
  expect(params.get('need')).toBe('need-legacy')
  expect(workspaceCalls).toEqual([])
})

test('searched account match preserves account and project context through explicit need selection', async ({ page }) => {
  const searchQueries: string[] = []
  const matchedProject = {
    id: 'project-match', project_id: 'project-match', name: 'Synthetic Phase North', company: 'Synthetic Operator', customer_identity_id: 'company-synthetic', location: 'Austin, TX', sector: 'data_centers', asset_type: 'data_center', priority_score: null,
    representative_need_id: 'need-match', need_count: 1, eligible_need_ids: ['need-match'], needs: [{ id: 'need-match', name: 'North campus construction' }], event: { kind: 'construction', label: 'Synthetic construction planned', date: null, source: null, evidence_refs: [] }, contact: [], power_summary: null, power_summary_kind: 'unknown', next_action: null,
    shortlist_assessment: { eligible: true, reasons: [], evidence_refs: [], why_now: 'Synthetic construction is planned.', next_step: 'Confirm the phase timing.' }, updated_at: null,
  }
  const group = { id: 'cg_match', name: 'Synthetic Operator', role: 'operator', group_kind: 'resolved_identity', project_count: 1, relevant_project_count: 1, total_known_project_count: 1, need_count: 1, eligible_need_count: 1, pursued_eligible_need_count: 0, matched_project_id: 'project-match', matched_need_id: 'need-match', sectors: ['data_centers'], featured_project: matchedProject }
  const selectedNeed = { id: 'need-match', project_id: 'project-match', name: 'Synthetic Phase North', location: 'Austin, TX', tier: 'Lead', workflow_status: 'New', activity: 'construction', rationale: 'Synthetic retained evidence supports the project.', signal_evidence_state: 'active', conflict_state: 'Not assessed', required_mw: null, supply: 'Unknown', start_window: null, duration: null, evidence: [], missing_facts: [], project_identity_key: 'synthetic', commercial_disposition: 'RESEARCH', commercial_reason: 'Demand remains unknown.', commercial_next_question: 'Who owns the scope?', commercial_next_action: 'Review retained evidence.', commercial_organization: null }
  await mockDemandSummary(page)
  await page.route(url => new URL(url).pathname.startsWith('/api/'), async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (url.pathname === '/api/opportunities/groups') { searchQueries.push(url.searchParams.get('search') ?? ''); return route.fulfill({ json: { items: [group], total: 1, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'match-groups', generation: 'synthetic' } }) }
    if (url.pathname === '/api/opportunities/groups/cg_match/open') { searchQueries.push(url.searchParams.get('search') ?? ''); return route.fulfill({ json: { group, projects: { items: [matchedProject], total: 1, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'match-projects', generation: 'synthetic', valid_until: validUntil }, parent_cohort_token: 'match-parent', generation: 'synthetic', valid_until: validUntil } }) }
    if (url.pathname === '/api/opportunities/needs/need-match') return route.fulfill({ json: selectedNeed })
    if (url.pathname === '/api/commercial-pursuits') return route.fulfill({ json: { items: [], counts: { total: 0, active: 0, needs_attention: 0 }, total_matching: 0, has_more: false, next_offset: null } })
    return route.fulfill({ status: 404, json: {} })
  })

  await page.goto('/?view=workspace&groupBrowse=1&shortlist=1&q=north')
  await page.locator('.customer-group-toggle').click()
  const account = page.getByRole('region', { name: 'Company Synthetic Operator' })
  await expect(account).toBeVisible()
  await expect.poll(() => new URL(page.url()).searchParams.get('project')).toBe('project-match')
  await expect.poll(() => new URL(page.url()).searchParams.get('matchedNeed')).toBe('need-match')
  await expect(account.locator('[data-project-id="project-match"]')).toBeFocused()
  await account.getByRole('button', { name: 'Open matching opportunity Synthetic Phase North' }).click()
  const params = new URL(page.url()).searchParams
  expect(params.get('account')).toBe('cg_match')
  expect(params.get('project')).toBe('project-match')
  expect(params.get('need')).toBe('need-match')
  expect(params.get('matchedNeed')).toBeNull()
  expect(searchQueries.every(value => value === 'north')).toBeTruthy()
})

test('unresolved legacy account route shows the unavailable state without rendering the old account queue', async ({ page }) => {
  let workspaceCalls = 0
  await mockDemandSummary(page)
  await page.route(url => new URL(url).pathname.startsWith('/api/'), async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (url.pathname === '/api/companies/company-unknown/account') return route.fulfill({ status: 404, json: {} })
    if (url.pathname === '/api/opportunities/workspace') { workspaceCalls += 1; return route.fulfill({ status: 500, json: {} }) }
    if (url.pathname === '/api/commercial-pursuits') return route.fulfill({ json: { items: [], counts: { total: 0, active: 0, needs_attention: 0 }, total_matching: 0, has_more: false, next_offset: null } })
    return route.fulfill({ status: 404, json: {} })
  })

  await page.goto('/?view=workspace&accountBrowse=1&account=company-unknown')
  await expect(page.getByRole('heading', { name: 'Saved account unavailable' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Open Companies' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Commercial intelligence for constrained power.' })).toHaveCount(0)
  expect(workspaceCalls).toBe(0)
})
