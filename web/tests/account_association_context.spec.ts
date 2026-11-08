import { expect, test } from '@playwright/test'
import { mockDemandSummary } from './mock-demand-summary'

const validUntil = new Date(Date.now() + 60 * 60 * 1000).toISOString()
const account = (id: string, name: string) => ({ id, name, role: 'operator', group_kind: 'resolved_identity', project_count: 1, relevant_project_count: 1, total_known_project_count: 1, need_count: 1, eligible_need_count: 1, sectors: ['data_centers'] })
const need = (id: string, projectId: string) => ({ id, project_id: projectId, name: `Synthetic project ${projectId}`, location: 'Austin, TX', tier: 'Lead', workflow_status: 'New', activity: 'construction', rationale: 'Synthetic evidence supports review.', signal_evidence_state: 'active', conflict_state: 'Not assessed', required_mw: null, supply: 'Unknown', start_window: null, duration: null, evidence: [], missing_facts: [], project_identity_key: 'synthetic', commercial_disposition: 'RESEARCH', commercial_reason: 'Demand remains unknown.', commercial_next_question: 'Who owns the scope?', commercial_next_action: 'Review retained evidence.', commercial_organization: null })
const projectPage = { items: [{ id: 'asset-b', project_id: 'project-b', project_ids: ['project-b'], name: 'Synthetic project project-b', company: 'Synthetic Account B', location: 'Austin, TX', sector: 'data_centers', asset_type: 'data_center', priority_score: null, representative_need_id: 'need-b', needs: [], need_count: 1, event: null, contact: [], power_summary: null, power_summary_kind: 'unknown', next_action: null, updated_at: null }], total: 1, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'synthetic-projects', generation: 'synthetic', valid_until: validUntil }
const emptyPursuits = { items: [], counts: { total: 0, active: 0, needs_attention: 0 }, total_matching: 0, has_more: false, next_offset: null }

test('stale account A and selected project B clears the unrelated account context', async ({ page }) => {
  await mockDemandSummary(page)
  await page.route(url => new URL(url).pathname.startsWith('/api/'), async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (url.pathname === '/api/opportunities/groups') return route.fulfill({ json: { items: [account('cg_a', 'Synthetic Account A')], total: 1, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'groups-a', generation: 'synthetic' } })
    if (url.pathname === '/api/opportunities/needs/need-b') return route.fulfill({ json: need('need-b', 'project-b') })
    if (url.pathname === '/api/opportunities/projects') return route.fulfill({ json: projectPage })
    if (url.pathname === '/api/projects/project-b/account') return route.fulfill({ json: account('cg_b', 'Synthetic Account B') })
    if (url.pathname === '/api/commercial-pursuits') return route.fulfill({ json: emptyPursuits })
    return route.fulfill({ status: 404, json: {} })
  })

  await page.goto('/?view=workspace&groupBrowse=1&account=cg_a&project=project-b&need=need-b')
  await expect.poll(() => new URL(page.url()).searchParams.get('account')).toBeNull()
  const params = new URL(page.url()).searchParams
  expect(params.get('project')).toBeNull()
  expect(params.get('need')).toBe('need-b')
  await expect(page.getByText('This project belongs to a different current account. The saved account link was cleared.')).toBeVisible()
  await expect(page.getByRole('region', { name: 'Company Synthetic Account A' })).toHaveCount(0)
})

test('a delayed old account validation cannot clear a newer account and project route', async ({ page }) => {
  let releaseA!: () => void
  const waitA = new Promise<void>(resolve => { releaseA = resolve })
  await mockDemandSummary(page)
  await page.route(url => new URL(url).pathname.startsWith('/api/'), async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (url.pathname === '/api/opportunities/groups') return route.fulfill({ json: { items: [account('cg_a', 'Synthetic Account A'), account('cg_b', 'Synthetic Account B')], total: 2, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'groups-current', generation: 'synthetic' } })
    if (url.pathname === '/api/opportunities/needs/need-a') return route.fulfill({ json: need('need-a', 'project-a') })
    if (url.pathname === '/api/opportunities/needs/need-b') return route.fulfill({ json: need('need-b', 'project-b') })
    if (url.pathname === '/api/opportunities/projects') return route.fulfill({ json: projectPage })
    if (url.pathname === '/api/projects/project-a/account') { await waitA; try { return await route.fulfill({ json: account('cg_old', 'Synthetic Old Account') }) } catch { return } }
    if (url.pathname === '/api/projects/project-b/account') return route.fulfill({ json: account('cg_b', 'Synthetic Account B') })
    if (url.pathname === '/api/opportunities/groups/cg_b/open') return route.fulfill({ json: { group: account('cg_b', 'Synthetic Account B'), projects: { items: [], total: 0, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'projects-b', generation: 'synthetic', valid_until: validUntil }, parent_cohort_token: 'parent-b', generation: 'synthetic', valid_until: validUntil } })
    if (url.pathname === '/api/commercial-pursuits') return route.fulfill({ json: emptyPursuits })
    return route.fulfill({ status: 404, json: {} })
  })

  const oldValidation = page.waitForRequest(request => new URL(request.url()).pathname === '/api/projects/project-a/account')
  await page.goto('/?view=workspace&groupBrowse=1&account=cg_a&project=project-a&need=need-a')
  await oldValidation
  await page.evaluate(() => {
    history.pushState(history.state, '', '/?view=workspace&groupBrowse=1&account=cg_b&project=project-b&need=need-b')
    dispatchEvent(new PopStateEvent('popstate'))
  })
  await expect(page.getByRole('region', { name: 'Company Synthetic Account B' })).toBeVisible()
  releaseA()
  await expect.poll(() => new URL(page.url()).searchParams.get('account')).toBe('cg_b')
  const params = new URL(page.url()).searchParams
  expect(params.get('project')).toBe('project-b')
  expect(params.get('need')).toBe('need-b')
  await expect(page.getByText(/different current account/)).toHaveCount(0)
})
