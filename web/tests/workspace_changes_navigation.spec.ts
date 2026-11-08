import { expect, test, type Page } from '@playwright/test'
import { mockDemandSummary } from './mock-demand-summary'

const need = {
  id: 'need-a', project_id: 'project-a', name: 'Test data center', location: 'Austin, TX', tier: 'Signal', workflow_status: 'New', activity: 'construction',
  rationale: 'Fresh canonical assessment.', signal_evidence_state: 'active', conflict_state: 'Not assessed', required_mw: null, supply: 'Unknown', start_window: null, duration: null,
  evidence: [], missing_facts: ['Activity-specific load'], project_identity_key: 'test', commercial_disposition: 'RESEARCH', commercial_reason: 'Load remains unknown.', commercial_next_question: 'Who owns the electrical scope?', commercial_next_action: 'Research the project contractor.', commercial_organization: null,
} as any

const emptyChanges = { items: [], counts: { discovered: 0, changed: 0, promoted: 0, closed: 0, review_exception: 0 }, total_unreviewed: 0, offset: 0, limit: 50, next_offset: null, evaluated_at: '2026-10-20T12:00:00Z', baseline_identity: '00000000-0000-4000-8000-000000000001', baseline_reviewed_at: null, first_use: true, token: 'a'.repeat(64), source_health_exceptions: [] }
const validUntil = '2099-01-01T00:00:00Z'
const project = { id: 'project-a', project_id: 'project-a', name: 'Test data center', company: 'Example operator', location: 'Austin, TX', sector: 'data_centers', asset_type: 'data_center', priority_score: null, representative_need_id: 'need-a', needs: [{ id: 'need-a', project_id: 'project-a', activity: 'construction', tier: 'Signal', commercial_disposition: 'RESEARCH', rationale: 'Fresh canonical assessment.' }], need_count: 1, event: { kind: 'permit_issued', label: 'Fresh canonical assessment.', date: '2026-10-18', source: 'Synthetic fixture', evidence_refs: [] }, shortlist_assessment: { why_now: 'Fresh canonical assessment.', next_step: 'Review the current source-backed filing.' }, contact: [], power_summary: 'Load remains unknown.', next_action: 'Research the project contractor.' }
const projectPage = { items: [project], total: 1, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'project-cohort', generation: 'synthetic', valid_until: validUntil }
const group = { id: 'cg_example_operator', name: 'Example operator', role: 'operator', group_kind: 'resolved_identity', project_count: 1, total_known_project_count: 1, relevant_project_count: 1, eligible_need_count: 1, pursued_eligible_need_count: 0, need_count: 1, sectors: ['data_centers'], featured_project: project }

async function mockReports(page: Page) {
  await page.route(url => url.pathname.startsWith('/api/'), route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (url.pathname === '/api/opportunities/demand-summary') return route.fulfill({ json: { availability: 'unavailable', counts_complete: true, sector: url.searchParams.get('sector') ?? 'all', totals: { identified_records: 0, known_mw_records: 0, unknown_records: 0, conflicted_records: 0 }, classes: { documented: { mw: null, record_count: 0 }, calculated: { mw: null, record_count: 0 }, estimated: { mw: null, record_count: 0 } }, provenance: { contract: 'synthetic', source_count: 0, latest_evidence_at: null }, limitations: [] } })
    if (url.pathname === '/api/opportunities/groups') return route.fulfill({ json: { items: [group], totals: { accounts: 1, projects: 1, needs: 1 }, total: 1, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'groups', generation: 'synthetic', valid_until: validUntil } })
    if (url.pathname === `/api/opportunities/groups/${group.id}/open`) return route.fulfill({ json: { group, projects: projectPage, parent_cohort_token: 'groups', generation: 'synthetic', valid_until: validUntil } })
    if (url.pathname === `/api/opportunities/groups/${group.id}/projects`) return route.fulfill({ json: projectPage })
    if (url.pathname === '/api/projects/project-a/account') return route.fulfill({ json: { id: group.id, name: group.name, group_kind: group.group_kind, project_id: 'project-a' } })
    if (url.pathname === '/api/opportunities/projects') return route.fulfill({ json: projectPage })
    if (url.pathname === '/api/opportunities') return route.fulfill({ json: [], headers: { 'X-Total-Count': '0', 'X-Group-Total-Count': '0', 'X-Cohort-Token': 'tier', 'X-Limit': '1', 'X-Offset': '0' } })
    if (url.pathname === '/api/commercial-pursuits') return route.fulfill({ json: { items: [], counts: { total: 0, active: 0, needs_attention: 0 } } })
    if (url.pathname === '/api/opportunities/workspace/changes') return route.fulfill({ json: emptyChanges })
    if (url.pathname === '/api/opportunities/needs/need-a/history') return route.fulfill({ json: { ...need, active: true, updated_at: '2026-10-20T12:00:00Z' } })
    if (url.pathname === '/api/opportunities/needs/need-a') return route.fulfill({ json: need })
    return route.fulfill({ json: [] })
  })
  await mockDemandSummary(page)
}

async function openReports(page: Page) {
  await page.goto('/?view=workspace&panel=reports')
  await expect(page.getByRole('region', { name: 'Reports' })).toBeVisible()
}

test('browser Back re-reads the same selected need after identity is cleared', async ({ page }) => {
  let detailReads = 0
  await mockReports(page)
  await page.route('**/api/opportunities/workspace/changes?*', route => {
    const offset = Number(new URL(route.request().url()).searchParams.get('offset') ?? 0)
    const items = Array.from({ length: 50 }, (_, index) => ({
      event_key: `change:${offset + index + 1}`, category: 'changed', title: `Change ${offset + index + 1}`,
      detail: 'Synthetic retained change', created_at: '2026-10-20T12:00:00Z', source_date: null,
      project_id: 'project-a', before_state: null, after_state: null, needs: [{ id: 'need-a', name: 'Test data center', location: 'Austin, TX', active: true, tier: 'Lead' }], sources: [],
    }))
    return route.fulfill({ json: { ...emptyChanges, items, total_unreviewed: 100, offset, next_offset: offset === 0 ? 50 : null } })
  })
  await page.route('**/api/opportunities/needs/need-a*', route => { detailReads += 1; return route.fulfill({ json: need }) })
  await openReports(page)
  const panel = page.locator('.wh-changes')
  await panel.locator(':scope > details > summary').click()
  await panel.getByRole('button', { name: 'Next changes' }).click()
  await expect(panel.getByRole('heading', { name: 'Change 51', exact: true })).toBeVisible()
  await expect(panel.getByText('Showing 51–100 of 100 changes')).toBeVisible()
  await page.locator('.wh-change-footer').scrollIntoViewIfNeeded()
  await panel.getByRole('button', { name: /Test data center · Austin, TX ·/ }).first().click()
  await expect(page.getByRole('heading', { name: 'Test data center' })).toBeVisible()
  const readsBeforeBack = detailReads
  await page.goBack()
  const report = page.getByRole('region', { name: 'Reports' })
  const restoredChanges = report.locator('.wh-changes')
  await expect(restoredChanges.getByRole('heading', { name: 'Change 51', exact: true })).toBeVisible()
  await expect(restoredChanges.getByText('Showing 51–100 of 100 changes')).toBeVisible()
  await restoredChanges.getByRole('button', { name: /Test data center · Austin, TX · Change 51/ }).click()
  await expect.poll(() => detailReads).toBeGreaterThan(readsBeforeBack)
  await expect(page.getByRole('heading', { name: 'Test data center' })).toBeVisible()
})

test('active change links use canonical workspace readback instead of historical stored tier', async ({ page }) => {
  await mockReports(page)
  const activeChange = {
    ...emptyChanges,
    items: [{
      event_key: 'fact:33333333-3333-4333-8333-333333333333', category: 'changed', title: 'Call fact accepted: demand', detail: 'Synthetic fixture',
      created_at: '2026-10-20T11:00:00Z', source_date: null, project_id: 'project-a', before_state: null,
      after_state: { fact_type: 'demand', value: { mw: '12' } }, needs: [{ id: 'need-a', name: 'Synthetic Facility', location: 'Austin, TX', active: true, tier: 'Lead' }],
      sources: [], fact_version_id: '44444444-4444-4444-8444-444444444444', fact_type: 'demand', decision: 'accepted', reason: 'Confirmed', actor: 'Operator', confirmed_at: '2026-10-20T10:00:00Z', source_reference: null,
    }],
    total_unreviewed: 1, counts: { ...emptyChanges.counts, changed: 1 },
  }
  await page.route('**/api/opportunities/workspace/changes*', route => route.fulfill({ json: activeChange }))
  await page.route('**/api/opportunities/needs/need-a?*', route => route.fulfill({ json: { ...need, tier: 'Signal' } }))
  let historicalReads = 0
  await page.route('**/api/opportunities/needs/need-a/history', route => { historicalReads += 1; return route.fulfill({ json: { ...need, active: true, tier: 'Lead' } }) })
  await openReports(page)
  const panel = page.locator('.wh-changes')
  await panel.locator(':scope > details > summary').click()
  await panel.getByRole('button', { name: /Synthetic Facility · Austin, TX · demand/ }).click()
  await expect(page.getByRole('heading', { name: 'Test data center' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Example operator customer group' })).toContainText('Fresh canonical assessment.')
  await expect(page.locator('.cod-panel')).not.toContainText('Lead')
  expect(historicalReads).toBe(0)
})

test('active change link hides a previously stored Lead while canonical readback is pending or fails', async ({ page }) => {
  await mockReports(page)
  const activeChange = {
    ...emptyChanges,
    items: [{
      event_key: 'fact:55555555-5555-4555-8555-555555555555', category: 'changed', title: 'Call fact accepted: demand', detail: 'Synthetic fixture',
      created_at: '2026-10-20T11:00:00Z', source_date: null, project_id: 'project-a', before_state: null,
      after_state: { fact_type: 'demand', value: { mw: '12' } }, needs: [{ id: 'need-a', name: 'Synthetic Facility', location: 'Austin, TX', active: true, tier: 'Lead' }],
      sources: [], fact_version_id: '66666666-6666-4666-8666-666666666666', fact_type: 'demand', decision: 'accepted', reason: 'Confirmed', actor: 'Operator', confirmed_at: '2026-10-20T10:00:00Z', source_reference: null,
    }],
    total_unreviewed: 1, counts: { ...emptyChanges.counts, changed: 1 },
  }
  await page.route('**/api/opportunities/workspace/changes*', route => route.fulfill({ json: activeChange }))
  await page.route('**/api/opportunities/needs/need-a?*', route => route.fulfill({ status: 503, json: { detail: 'Fresh qualification unavailable' } }))
  let historicalReads = 0
  await page.route('**/api/opportunities/needs/need-a/history', route => { historicalReads += 1; return route.fulfill({ json: { ...need, active: true, tier: 'Lead' } }) })
  await openReports(page)
  const panel = page.locator('.wh-changes')
  await panel.locator(':scope > details > summary').click()
  await panel.getByRole('button', { name: /Synthetic Facility · Austin, TX · demand/ }).click()
  await expect(page.getByRole('alert')).toContainText('GridLens could not complete this request (503)')
  await expect(page.locator('.cod-panel')).not.toContainText('Lead')
  expect(historicalReads).toBe(0)
})
