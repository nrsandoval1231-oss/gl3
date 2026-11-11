import { openProjectFilters, setAccountMenuOpen } from './ui-helpers'
import { mockDemandSummary } from './mock-demand-summary'
import { expect, test, type Page, type Route } from '@playwright/test'
import type { Opportunity } from '../src/api/client'

// Test-only fixtures. They exercise layout and navigation, never production data.
const stamp = '2026-10-01T12:00:00Z'
const evidence = (n: number): Opportunity['evidence'][number] => ({
  source_id: 'test-source', document_number: `DOC-${n}`, content_hash: `fixturehash${n}0000`,
  url: `https://example.com/${n}`, title: `Test evidence ${n}`, published_at: null,
  event_date: '2026-09-30', event_date_label: 'Permit issue date', retrieved_at: stamp,
  abstract: 'Test-only abstract.', extraction_location: 'row', assessment_current: true,
} as Opportunity['evidence'][number])
const opportunity = (id: string, location: string | null): Opportunity => ({
  id, project_id: id, name: `Test project ${id}`, location, tier: 'Signal', workflow_status: 'UNKNOWN',
  activity: 'construction-power', rationale: 'Test rationale.', assessment_reason: 'Test assessment.',
  brief_status: 'unavailable', brief_stale: false, required_mw: null, start_window: null, duration: null,
  supply: 'Unknown', next_action: `Test next action ${id}.`, conflict_state: 'None recorded',
  title_company: `Test project ${id}`,
  signal_display_decision: 'SHOW', signal_display_decision_state: 'adjudicated', signal_evidence_state: 'active_evidence',
  missing_facts: ['Activity-specific load (MW)'], asset_type: 'data_center', evidence: [evidence(1), evidence(2)],
} as Opportunity)

async function openSecondaryRoute(page: Page, name: 'Research' | 'Research progress' | 'Signals') {
  const menu = page.locator('.workspace-account')
  if ((await menu.getByRole('button', { name: 'Account menu' }).getAttribute('aria-expanded')) !== 'true') await menu.getByRole('button', { name: 'Account menu' }).click()
  await menu.getByRole('button', { name, exact: true }).click()
}

async function mock(page: Page, items: Opportunity[], opportunities?: (route: Route) => Promise<void>, mapWindow?: (route: Route) => Promise<void>) {
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (!path.startsWith('/api/')) return route.continue()
    if (path === '/api/opportunities' && opportunities) return opportunities(route)
    if (path === '/api/opportunities/map-window' && mapWindow) return mapWindow(route)
    const json = (body: unknown, headers: Record<string, string> = {}) =>
      route.fulfill({ contentType: 'application/json', headers, body: JSON.stringify(body) })
    if (path === '/api/auth/session') return json({ authenticated: true })
    if (path === '/api/opportunities/groups') {
      const params = new URL(route.request().url()).searchParams
      const query = (params.get('search') ?? '').toLocaleLowerCase()
      const projects = items.map(item => ({ id: item.project_id ?? item.id, project_id: item.project_id ?? item.id, name: item.name, company: item.title_company ?? null, location: item.location, sector: item.asset_type === 'data_center' ? 'data_centers' : item.asset_type ? 'oil_gas' : null, asset_type: item.asset_type ?? null, priority_score: null, representative_need_id: item.id, needs: [{ id: item.id, project_id: item.project_id ?? item.id, name: item.name, browse_title: item.name, activity: item.activity, location: item.location, tier: item.tier, commercial_preview: { disposition: item.intelligence_card?.disposition ?? 'RESEARCH' } }], need_count: 1, event: { kind: 'permit_issued', label: 'Permit issued', date: '2026-09-30', source: 'Synthetic fixture', evidence_refs: [] }, contact: [], contact_people: [], power_summary: item.rationale, next_action: item.next_action, updated_at: stamp })).filter(project => !query || `${project.name} ${project.company ?? ''} ${project.location ?? ''}`.toLocaleLowerCase().includes(query))
      const groups = [...new Map(projects.map(project => [project.company ?? project.name, project])).values()].map(project => ({ id: `group-${project.id}`, name: project.company ?? project.name, role: project.company ? 'operator' : 'unresolved', operator_number: null, project_count: projects.filter(item => (item.company ?? item.name) === (project.company ?? project.name)).length, need_count: 1, priority_score: null, sectors: [project.sector].filter(Boolean) }))
      const offset = Number(params.get('offset') ?? 0), limit = 25
      return json({ items: groups.slice(offset, offset + limit), total: groups.length, count_unit: 'groups', limit, offset, cohort_token: 'group-fixture', generation: 'environment-synthetic', valid_until: '2099-01-01T00:00:00Z' })
    }
    if (/^\/api\/opportunities\/groups\/[^/]+\/open$/.test(path)) {
      const groupId = path.split('/')[4]
      const item = items.find(candidate => `group-${candidate.id}` === groupId)
      const projectId = item?.project_id ?? item?.id
      const project = item ? { id: projectId, project_id: projectId, name: item.name, company: item.title_company ?? null, location: item.location, sector: item.asset_type === 'data_center' ? 'data_centers' : item.asset_type ? 'oil_gas' : null, asset_type: item.asset_type ?? null, priority_score: null, representative_need_id: item.id, needs: [{ id: item.id, project_id: projectId, name: item.name, browse_title: item.name, activity: item.activity, location: item.location, tier: item.tier }], need_count: 1, event: { kind: 'permit_issued', label: 'Permit issued', date: '2026-09-30', source: 'Synthetic fixture', evidence_refs: [] }, contact: [], power_summary: item.rationale, next_action: item.next_action, updated_at: stamp } : null
      const group = item ? { id: groupId, name: item.title_company ?? item.name, role: item.title_company ? 'operator' : 'unresolved', project_count: 1, total_known_project_count: 1, need_count: 1, sectors: [project?.sector].filter(Boolean) } : { id: groupId, name: 'Unavailable account', role: 'unresolved', project_count: 0, total_known_project_count: 0, need_count: 0, sectors: [] }
      return json({ group, parent_cohort_token: 'group-fixture', generation: 'environment-synthetic', valid_until: '2099-01-01T00:00:00Z', projects: { items: project ? [project] : [], total: project ? 1 : 0, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'child-fixture', generation: 'environment-synthetic', valid_until: '2099-01-01T00:00:00Z' } })
    }
    if (path.startsWith('/api/opportunities/groups/') && path.endsWith('/projects')) {
      expect(new URL(route.request().url()).searchParams.get('parent_cohort_token')).toBe('group-fixture')
      const groupId = path.split('/')[4]
      const projects = items.map(item => ({ id: item.project_id ?? item.id, project_id: item.project_id ?? item.id, name: item.name, company: item.title_company ?? null, location: item.location, sector: item.asset_type === 'data_center' ? 'data_centers' : item.asset_type ? 'oil_gas' : null, asset_type: item.asset_type ?? null, priority_score: null, representative_need_id: item.id, needs: [{ id: item.id, project_id: item.project_id ?? item.id, name: item.name, browse_title: item.name, activity: item.activity, location: item.location, tier: item.tier, commercial_preview: { disposition: item.intelligence_card?.disposition ?? 'RESEARCH' } }], need_count: 1, event: { kind: 'permit_issued', label: 'Permit issued', date: '2026-09-30', source: 'Synthetic fixture', evidence_refs: [] }, contact: [], contact_people: [], power_summary: item.rationale, next_action: item.next_action, updated_at: stamp })).filter(project => `group-${project.project_id}` === groupId)
      return json({ items: projects, total: projects.length, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'child-fixture', generation: 'environment-synthetic', valid_until: '2099-01-01T00:00:00Z' })
    }
    if (path === '/api/opportunities/projects') {
      const params = new URL(route.request().url()).searchParams
      const query = (params.get('search') ?? '').toLocaleLowerCase()
      const projects = items.map(item => ({ id: item.project_id ?? item.id, project_id: item.project_id ?? item.id, name: item.name, company: item.title_company ?? null, location: item.location, sector: item.asset_type === 'data_center' ? 'data_centers' : item.asset_type ? 'oil_gas' : null, asset_type: item.asset_type ?? null, priority_score: null, representative_need_id: item.id, needs: [{ id: item.id, project_id: item.project_id ?? item.id, name: item.name, browse_title: item.name, activity: item.activity, location: item.location, tier: item.tier, commercial_preview: { disposition: item.intelligence_card?.disposition ?? 'RESEARCH' } }], need_count: 1, event: { kind: 'permit_issued', label: 'Permit issued', date: '2026-09-30', source: 'Synthetic fixture', evidence_refs: [] }, contact: [], contact_people: [], power_summary: item.rationale, next_action: item.next_action, updated_at: stamp })).filter(project => !query || `${project.name} ${project.company ?? ''} ${project.location ?? ''}`.toLocaleLowerCase().includes(query))
      const offset = Number(params.get('offset') ?? 0), limit = 25
      return json({ items: projects.slice(offset, offset + limit), total: projects.length, count_unit: 'projects', limit, offset, cohort_token: 'project-fixture', generation: 'environment-synthetic', valid_until: '2099-01-01T00:00:00Z' })
    }
    if (path === '/api/opportunities/workspace') {
      const params = new URL(route.request().url()).searchParams
      const offset = Number(params.get('offset') ?? 0), limit = 25
      const filtered = items.filter(item => (!params.get('tier') || item.tier === params.get('tier')) && (!params.get('geography') || item.location === params.get('geography')) && (!params.get('industry') || item.asset_type === params.get('industry')) && (!params.get('search') || `${item.name} ${item.location}`.toLowerCase().includes(params.get('search')!.toLowerCase())))
      return json({ items: filtered.slice(offset, offset + limit), total: filtered.length, counts: { action_now: 0, research: 0, watch: 0, reject: 0 }, offset, limit, next_offset: offset + limit < filtered.length ? offset + limit : null, cohort_token: 'workspace-fixture', count_unit: 'power needs', changes_available: false, valid_until: '2099-01-01T00:00:00Z' })
    }
    if (path === '/api/opportunities/workspace/changes') return json({ items: [], counts: { discovered: 0, changed: 0, promoted: 0, closed: 0, review_exception: 0 }, total_unreviewed: 0, offset: 0, limit: 50, next_offset: null, evaluated_at: stamp, baseline_identity: '00000000-0000-4000-8000-000000000001', baseline_reviewed_at: null, first_use: true, token: 'a'.repeat(64), source_health_exceptions: [] })
    if (path === '/api/opportunities') {
      const url = new URL(route.request().url())
      const limit = Number(url.searchParams.get('limit'))
      if (limit > 50) return route.fulfill({ status: 422, body: 'limit above API maximum' })
      const offset = Number(url.searchParams.get('offset') ?? 0)
      const pageItems = items.slice(offset, offset + limit)
      const next: Record<string, string> = offset + limit < items.length ? { 'X-Next-Offset': String(offset + limit) } : {}
      return json(pageItems, { 'X-Total-Count': String(items.length), 'X-Cohort-Token': 'c1', ...next })
    }
    if (path === '/api/opportunities/map-window') {
      const loaded = items.slice(0, 200)
      return json({ items: loaded, total_count: items.length, loaded_count: loaded.length,
        is_subset: loaded.length < items.length, window_limit: 200, group_total_count: items.length,
        cohort_token: 'map-cohort', decision_counts: { SHOW: 0, REVIEW: 0, HOLD: 0 } })
    }
    if (path.startsWith('/api/opportunities/needs/')) {
      const item = items.find((item) => item.id === path.split('/').at(-1))
      const tier = new URL(route.request().url()).searchParams.get('tier')
      return item && (!tier || item.tier === tier) ? json(item) : route.fulfill({ status: 404 })
    }
    if (path === '/api/ingestion') return json({ items: [], total: 0, limit: 25, offset: 0, next_offset: null })
    if (path === '/api/health') return json({ sources: [{ id: 's', enabled: true, status: 'Updated' }], backlog: 0, pending_interpretations: 0 })
    if (route.request().method() === 'GET' && path === '/api/intelligence/tasks') return json({ items: [] })
    if (route.request().method() === 'GET' && /^\/api\/intelligence\/needs\/[^/]+\/history$/.test(path)) return json({ items: [] })
    if (path.endsWith('/buying-chain')) return json({ project_id: 'a', status: 'complete', policy_version: 'v1', unresolved: [], runs: [], candidates: [] })
    return json([])
  })
}

test('project-first results keep geographically unknown projects reachable and restore selected need', async ({ page }) => {
  await mock(page, [opportunity('a', 'Austin, TX'), opportunity('d', null)])
  await mockDemandSummary(page)
  await page.goto('/environment?projectBrowse=1&shortlist=0')
  await expect(page.getByRole('heading', { name: 'Opportunities', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Test project d', exact: true }).click()
  const detail = page.getByRole('complementary', { name: 'Opportunity detail' })
  await expect(detail.getByRole('heading', { name: 'Test project d', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Test project a', exact: true }).click()
  await expect(detail.getByRole('heading', { name: 'Test project a', exact: true })).toBeVisible()
  await detail.getByRole('button', { name: 'View all evidence' }).click()
  await expect(page.getByRole('link', { name: 'Test evidence 2' })).toBeVisible()
  await page.goBack()
  await expect(detail.getByRole('heading', { name: 'Test project a', exact: true })).toBeVisible()
  await page.goBack()
  await expect(detail.getByRole('heading', { name: 'Test project d', exact: true })).toBeVisible()
  await page.goForward()
  await expect(detail.getByRole('heading', { name: 'Test project a', exact: true })).toBeVisible()
})

test('legacy action deep link restores selected need without retired call preparation', async ({ page }) => {
  await mock(page, [opportunity('a', 'Austin, TX')])
  const writes: string[] = []
  page.on('request', request => { if (request.method() === 'POST') writes.push(request.url()) })
  await mockDemandSummary(page)
  await page.goto('/environment?view=environment&mode=action&state=Texas&need=a&projectBrowse=1&shortlist=0')
  const detail = page.getByRole('complementary', { name: 'Opportunity detail' })
  await expect(detail.getByRole('heading', { name: 'Test project a', exact: true })).toBeVisible()
  await setAccountMenuOpen(page)
  await expect(page.getByRole('button', { name: 'Research progress', exact: true }).first()).toBeVisible()
  await expect(page.getByLabel('Call note')).toHaveCount(0)
  expect(writes).toEqual([])
})

test('legacy environment URL reaches project results without workspace or map requests', async ({ page }) => {
  const requests: string[] = []
  await mock(page, [opportunity('a', 'Austin, TX'), opportunity('dc', 'Washington, DC')])
  page.on('request', request => requests.push(new URL(request.url()).pathname))
  await mockDemandSummary(page)
  await page.goto('/environment?projectBrowse=1&shortlist=0')
  await expect(page.getByRole('heading', { name: 'Opportunities', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Test project dc', exact: true })).toBeVisible()
  expect(requests).toContain('/api/opportunities/projects')
  expect(requests).not.toContain('/api/opportunities/workspace')
  expect(requests).not.toContain('/api/opportunities/map-window')
})

test('default account browsing uses bounded server pagination instead of map-window data', async ({ page }) => {
  const requests: URL[] = []
  await mock(page, Array.from({ length: 60 }, (_, i) => opportunity(`n${i}`, 'Austin, TX')))
  page.on('request', request => requests.push(new URL(request.url())))
  await mockDemandSummary(page)
  await page.goto('/?view=workspace&groupBrowse=1&shortlist=0')
  await expect(page.getByRole('region', { name: 'Project opportunities' })).toContainText('60 accounts')
  await expect(page.locator('.project-paging span')).toHaveText('1–25 of 60 accounts')
  await page.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(page.locator('.project-paging span')).toHaveText('26–50 of 60 accounts')
  expect(requests.some(url => url.pathname === '/api/opportunities/groups' && url.searchParams.get('offset') === '25')).toBe(true)
  expect(requests.some(url => url.pathname === '/api/opportunities/map-window')).toBe(false)
})









test('Back and Forward restore the selected account from the current paged account list', async ({ page }) => {
  const items = Array.from({ length: 60 }, (_, i) => opportunity(`history-${i}`, 'Austin, TX'))
  await mock(page, items)
  await mockDemandSummary(page)
  await page.goto('/?view=workspace&groupBrowse=1&shortlist=0')
  await expect(page.locator('.project-paging span')).toHaveText('1–25 of 60 accounts')
  await page.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(page.locator('.project-paging span')).toHaveText('26–50 of 60 accounts')
  await expect(page).toHaveURL(/offset=25/)
  const accountButton = page.locator('.customer-group-toggle').first()
  const accountName = (await accountButton.locator('strong').textContent())?.trim() ?? ''
  await accountButton.click()
  await expect(page.getByRole('region', { name: `Company ${accountName}` })).toBeVisible()
  await page.goBack()
  await expect(page.locator('.project-paging span')).toHaveText('26–50 of 60 accounts')
  await expect(page).not.toHaveURL(/account=/)
  await page.goForward()
  await expect(page.getByRole('region', { name: `Company ${accountName}` })).toBeVisible()
  await expect(page.locator('.cmp-projects li')).toContainText(accountName)
})

test('section navigation keeps Opportunities and Signals searches independent through reload and history', async ({ page }) => {
  const requests: URL[] = []
  await mock(page, [opportunity('alpha', 'Austin, TX')])
  page.on('request', request => { const url = new URL(request.url()); if (url.pathname === '/api/opportunities/groups') requests.push(url) })
  await mockDemandSummary(page)
  await page.goto('/?view=workspace&q=alpha&groupBrowse=1&shortlist=0')
  await openProjectFilters(page)
  await expect(page.getByRole('textbox', { name: 'Search accounts and projects' })).toHaveValue('alpha')
  await openSecondaryRoute(page, 'Signals')
  await page.getByRole('textbox', { name: 'Search projects' }).fill('beta')
  await expect.poll(() => new URL(page.url()).searchParams.get('q')).toBe('beta')
  await page.getByRole('button', { name: 'Opportunities', exact: true }).click()
  await openProjectFilters(page)
  await expect(page.getByRole('textbox', { name: 'Search accounts and projects' })).toHaveValue('alpha')
  expect(new URL(page.url()).searchParams.get('q')).toBe('alpha')
  expect(new URL(page.url()).searchParams.has('decision')).toBe(false)
  await expect.poll(() => requests.at(-1)?.searchParams.get('search')).toBe('alpha')
  await page.reload()
  await openProjectFilters(page)
  await expect(page.getByRole('textbox', { name: 'Search accounts and projects' })).toHaveValue('alpha')
  await page.goBack()
  await expect(page.getByRole('textbox', { name: 'Search projects' })).toHaveValue('beta')
  await page.goForward()
  await openProjectFilters(page)
  await expect(page.getByRole('textbox', { name: 'Search accounts and projects' })).toHaveValue('alpha')
  expect(new URL(page.url()).searchParams.get('q')).toBe('alpha')
})

test('Research navigation keeps Opportunities search and selection state independent', async ({ page }) => {
  await mock(page, [opportunity('a', 'Austin, TX')])
  await mockDemandSummary(page)
  await page.goto('/?view=workspace&q=a&groupBrowse=1&shortlist=0')
  await openSecondaryRoute(page, 'Research progress')
  await expect(page.getByRole('heading', { name: 'Research progress', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /WATCH|ACTION NOW|REJECT/i })).toHaveCount(0)
  await page.getByRole('button', { name: 'Opportunities', exact: true }).click()
  await openProjectFilters(page)
  await expect(page.getByRole('textbox', { name: 'Search accounts and projects' })).toHaveValue('a')
  expect(new URL(page.url()).searchParams.has('disposition')).toBe(false)
  expect(new URL(page.url()).searchParams.has('researchNeed')).toBe(false)
  await page.reload()
  await openProjectFilters(page)
  await expect(page.getByRole('combobox', { name: 'Project type' })).toHaveValue('all')
  await page.goBack()
  await expect(page.getByRole('heading', { name: 'Research progress', exact: true })).toBeVisible()
  await page.goForward()
  await openProjectFilters(page)
  await expect(page.getByRole('textbox', { name: 'Search accounts and projects' })).toHaveValue('a')
  expect(new URL(page.url()).searchParams.has('disposition')).toBe(false)
})
