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

async function openSecondaryRoute(page: Page, name: 'Research' | 'Signals') {
  const menu = page.locator('.wh-account')
  if (await menu.getAttribute('open') === null) await menu.locator('summary').click()
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
      return json({ items: groups.slice(offset, offset + limit), total: groups.length, count_unit: 'groups', limit, offset, cohort_token: 'group-fixture', generation: 1 })
    }
    if (path.startsWith('/api/opportunities/groups/') && path.endsWith('/projects')) {
      expect(new URL(route.request().url()).searchParams.get('parent_cohort_token')).toBe('group-fixture')
      const groupId = path.split('/')[4]
      const projects = items.map(item => ({ id: item.project_id ?? item.id, project_id: item.project_id ?? item.id, name: item.name, company: item.title_company ?? null, location: item.location, sector: item.asset_type === 'data_center' ? 'data_centers' : item.asset_type ? 'oil_gas' : null, asset_type: item.asset_type ?? null, priority_score: null, representative_need_id: item.id, needs: [{ id: item.id, project_id: item.project_id ?? item.id, name: item.name, browse_title: item.name, activity: item.activity, location: item.location, tier: item.tier, commercial_preview: { disposition: item.intelligence_card?.disposition ?? 'RESEARCH' } }], need_count: 1, event: { kind: 'permit_issued', label: 'Permit issued', date: '2026-09-30', source: 'Synthetic fixture', evidence_refs: [] }, contact: [], contact_people: [], power_summary: item.rationale, next_action: item.next_action, updated_at: stamp })).filter(project => `group-${project.project_id}` === groupId)
      return json({ items: projects, total: projects.length, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'child-fixture', generation: 1 })
    }
    if (path === '/api/opportunities/projects') {
      const params = new URL(route.request().url()).searchParams
      const query = (params.get('search') ?? '').toLocaleLowerCase()
      const projects = items.map(item => ({ id: item.project_id ?? item.id, project_id: item.project_id ?? item.id, name: item.name, company: item.title_company ?? null, location: item.location, sector: item.asset_type === 'data_center' ? 'data_centers' : item.asset_type ? 'oil_gas' : null, asset_type: item.asset_type ?? null, priority_score: null, representative_need_id: item.id, needs: [{ id: item.id, project_id: item.project_id ?? item.id, name: item.name, browse_title: item.name, activity: item.activity, location: item.location, tier: item.tier, commercial_preview: { disposition: item.intelligence_card?.disposition ?? 'RESEARCH' } }], need_count: 1, event: { kind: 'permit_issued', label: 'Permit issued', date: '2026-09-30', source: 'Synthetic fixture', evidence_refs: [] }, contact: [], contact_people: [], power_summary: item.rationale, next_action: item.next_action, updated_at: stamp })).filter(project => !query || `${project.name} ${project.company ?? ''} ${project.location ?? ''}`.toLocaleLowerCase().includes(query))
      const offset = Number(params.get('offset') ?? 0), limit = 25
      return json({ items: projects.slice(offset, offset + limit), total: projects.length, count_unit: 'projects', limit, offset, cohort_token: 'project-fixture', generation: 1 })
    }
    if (path === '/api/opportunities/workspace') {
      const params = new URL(route.request().url()).searchParams
      const offset = Number(params.get('offset') ?? 0), limit = 25
      const filtered = items.filter(item => (!params.get('tier') || item.tier === params.get('tier')) && (!params.get('geography') || item.location === params.get('geography')) && (!params.get('industry') || item.asset_type === params.get('industry')) && (!params.get('search') || `${item.name} ${item.location}`.toLowerCase().includes(params.get('search')!.toLowerCase())))
      return json({ items: filtered.slice(offset, offset + limit), total: filtered.length, counts: { action_now: 0, research: 0, watch: 0, reject: 0 }, offset, limit, next_offset: offset + limit < filtered.length ? offset + limit : null, cohort_token: 'workspace-fixture', count_unit: 'power needs', changes_available: false })
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
  await page.goto('/environment?groupBrowse=1')
  await expect(page.getByRole('heading', { name: 'Search opportunities' })).toBeVisible()
  await page.getByRole('button', { name: /Test project d/ }).click()
  await expect(page.getByRole('heading', { name: 'Test project d', exact: true })).toBeVisible()
  await page.getByRole('button', { name: /Test project a/ }).click()
  await page.locator('.project-card').filter({ has: page.getByRole('heading', { name: 'Test project a' }) }).getByRole('button', { name: 'View project details' }).click()
  await expect(page.locator('.project-first-detail h2')).toHaveText('Test project a')
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  await expect(page.getByRole('link', { name: 'Test evidence 2' })).toBeVisible()
  await page.getByRole('button', { name: /Back to power needs/ }).click()
  await expect(page.getByRole('heading', { name: 'Test project d', exact: true })).toBeVisible()
  await page.goForward()
  await expect(page.locator('.project-first-detail h2')).toHaveText('Test project a')
})

test('legacy action deep link restores selected need without retired call preparation', async ({ page }) => {
  await mock(page, [opportunity('a', 'Austin, TX')])
  const writes: string[] = []
  page.on('request', request => { if (request.method() === 'POST') writes.push(request.url()) })
  await mockDemandSummary(page)
  await page.goto('/environment?view=environment&mode=action&state=Texas&need=a&groupBrowse=1')
  await expect(page.locator('.project-first-detail h2')).toHaveText('Test project a')
  await page.locator('.wh-account summary').click()
  await expect(page.getByRole('button', { name: 'Research', exact: true }).first()).toBeVisible()
  await expect(page.getByLabel('Call note')).toHaveCount(0)
  expect(writes).toEqual([])
})

test('legacy environment URL reaches project results without workspace or map requests', async ({ page }) => {
  const requests: string[] = []
  await mock(page, [opportunity('a', 'Austin, TX'), opportunity('dc', 'Washington, DC')])
  page.on('request', request => requests.push(new URL(request.url()).pathname))
  await mockDemandSummary(page)
  await page.goto('/environment?groupBrowse=1')
  await expect(page.getByRole('heading', { name: 'Search opportunities' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Test project dc' })).toBeVisible()
  expect(requests).toContain('/api/opportunities/groups')
  expect(requests).not.toContain('/api/opportunities/workspace')
  expect(requests).not.toContain('/api/opportunities/map-window')
})

test('secondary account browsing uses bounded server pagination instead of map-window data', async ({ page }) => {
  const requests: URL[] = []
  await mock(page, Array.from({ length: 60 }, (_, i) => opportunity(`n${i}`, 'Austin, TX')))
  page.on('request', request => requests.push(new URL(request.url())))
  await mockDemandSummary(page)
  await page.goto('/?view=workspace&accountBrowse=1')
  await expect(page.getByText('Showing 1–25 of 60')).toBeVisible()
  await page.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(page.getByText('Showing 26–50 of 60')).toBeVisible()
  expect(requests.some(url => url.pathname === '/api/opportunities/workspace' && url.searchParams.get('offset') === '25')).toBe(true)
  expect(requests.some(url => url.pathname === '/api/opportunities/map-window')).toBe(false)
})









test('Back and Forward wait for the matching page before restoring each queue position', async ({ page }) => {
  const items = Array.from({ length: 60 }, (_, i) => opportunity(`history-${i}`, 'Austin, TX'))
  await mock(page, items)
  let delayFirstPage = false, delayed = false
  let release: (() => void) | undefined
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/opportunities/workspace?*', async route => {
    const params = new URL(route.request().url()).searchParams
    const offset = Number(params.get('offset') ?? 0)
    if (delayFirstPage && offset === 0 && !delayed) { delayed = true; await gate }
    await route.fulfill({ json: { items: items.slice(offset, offset + 25), total: 60, counts: { action_now: 0, research: 0, watch: 0, reject: 0 }, offset, limit: 25, next_offset: offset < 50 ? offset + 25 : null, cohort_token: 'workspace-fixture', count_unit: 'power needs', changes_available: false } })
  })
  try {
  await mockDemandSummary(page)
  await page.goto('/?view=workspace&accountBrowse=1')
    await expect(page.getByText('Showing 1–25 of 60')).toBeVisible()
    const first = page.locator('[data-need-row="history-7"]')
    await first.focus()
    await page.locator('.wh-list').evaluate(el => { el.scrollTop = 200 })
    const firstScroll = await page.locator('.wh-list').evaluate(el => el.scrollTop)
    await page.getByRole('button', { name: 'Next', exact: true }).evaluate(button => (button as HTMLButtonElement).click())
    await expect(page.getByText('Showing 26–50 of 60')).toBeVisible()
    const second = page.locator('[data-need-row="history-32"]')
    await second.focus()
    await page.locator('.wh-list').evaluate(el => { el.scrollTop = 300 })
    const secondScroll = await page.locator('.wh-list').evaluate(el => el.scrollTop)
    await page.getByRole('button', { name: 'Next', exact: true }).evaluate(button => (button as HTMLButtonElement).click())
    await expect(page.getByText('Showing 51–60 of 60')).toBeVisible()
    await page.goBack()
    await expect(page.getByText('Showing 26–50 of 60')).toBeVisible()
    await expect.poll(() => page.locator('.wh-list').evaluate(el => el.scrollTop)).toBe(secondScroll)
    await expect(second).toBeFocused()
    delayFirstPage = true
    await page.goBack()
    await expect.poll(() => delayed).toBe(true)
    await expect(page.getByText('Showing 1–25 of 60')).toHaveCount(0)
    release?.()
    await expect(page.getByText('Showing 1–25 of 60')).toBeVisible()
    await expect.poll(() => page.locator('.wh-list').evaluate(el => el.scrollTop)).toBe(firstScroll)
    await expect(first).toBeFocused()
    await page.goForward()
    await expect(page.getByText('Showing 26–50 of 60')).toBeVisible()
    await expect.poll(() => page.locator('.wh-list').evaluate(el => el.scrollTop)).toBe(secondScroll)
  } finally { release?.() }
})

test('section navigation keeps Opportunities and Signals searches independent through reload and history', async ({ page }) => {
  const requests: URL[] = []
  await mock(page, [opportunity('alpha', 'Austin, TX')])
  page.on('request', request => { const url = new URL(request.url()); if (url.pathname === '/api/opportunities/groups') requests.push(url) })
  await mockDemandSummary(page)
  await page.goto('/?view=workspace&q=alpha&groupBrowse=1')
  await expect(page.getByRole('textbox', { name: 'Search opportunities' })).toHaveValue('alpha')
  await openSecondaryRoute(page, 'Signals')
  await page.getByRole('textbox', { name: 'Search projects' }).fill('beta')
  await expect.poll(() => new URL(page.url()).searchParams.get('q')).toBe('beta')
  await page.getByRole('button', { name: 'Opportunities', exact: true }).click()
  await expect(page.getByRole('textbox', { name: 'Search opportunities' })).toHaveValue('alpha')
  expect(new URL(page.url()).searchParams.get('q')).toBe('alpha')
  expect(new URL(page.url()).searchParams.has('decision')).toBe(false)
  await expect.poll(() => requests.at(-1)?.searchParams.get('search')).toBe('alpha')
  await page.reload()
  await expect(page.getByRole('textbox', { name: 'Search opportunities' })).toHaveValue('alpha')
  await page.goBack()
  await expect(page.getByRole('textbox', { name: 'Search projects' })).toHaveValue('beta')
  await page.goForward()
  await expect(page.getByRole('textbox', { name: 'Search opportunities' })).toHaveValue('alpha')
  expect(new URL(page.url()).searchParams.get('q')).toBe('alpha')
})

test('Research navigation keeps Opportunities search and selection state independent', async ({ page }) => {
  await mock(page, [opportunity('a', 'Austin, TX')])
  await mockDemandSummary(page)
  await page.goto('/?view=workspace&q=a&groupBrowse=1')
  await openSecondaryRoute(page, 'Research')
  await expect(page.getByRole('heading', { name: 'Research', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /WATCH|ACTION NOW|REJECT/i })).toHaveCount(0)
  await page.getByRole('button', { name: 'Opportunities', exact: true }).click()
  await expect(page.getByRole('textbox', { name: 'Search opportunities' })).toHaveValue('a')
  expect(new URL(page.url()).searchParams.has('disposition')).toBe(false)
  expect(new URL(page.url()).searchParams.has('researchNeed')).toBe(false)
  await page.reload()
  await expect(page.getByRole('navigation', { name: 'Project type' }).getByRole('button', { name: 'All', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await page.goBack()
  await expect(page.getByRole('heading', { name: 'Research', exact: true })).toBeVisible()
  await page.goForward()
  await expect(page.getByRole('textbox', { name: 'Search opportunities' })).toHaveValue('a')
  expect(new URL(page.url()).searchParams.has('disposition')).toBe(false)
})
