import { expect, test, type Page } from '@playwright/test'
import { mockDemandSummary } from './mock-demand-summary'

// SYNTHETIC UI TEST FIXTURE ONLY — names, contacts, dates and power values are fabricated.
// Covers the DEFAULT account-first browse: curated customer accounts, distinct projects,
// CanonicalOpportunityDetail, and need-scoped pursuit idempotency.

const sampleProject = {
  id: 'project-1', project_id: 'project-1', name: 'Example Energy · Example Compressor Station', company: 'Example Energy', customer_identity_id: 'company-1',
  location: 'Permian Basin, TX', sector: 'oil_gas', asset_type: 'compressor_station', priority_score: null, representative_need_id: 'need-1', need_count: 1,
  needs: [{ id: 'need-1', project_id: 'project-1', tier: 'Lead', activity: 'drilling' }],
  event: null, contact: [], contact_people: [], power_summary: null, power_summary_kind: 'unknown', next_action: 'Confirm fixture details.', updated_at: '2026-10-21T00:00:00Z',
}
const group = { id: 'group-1', name: 'Example Energy', role: 'operator', group_kind: 'resolved_identity', project_count: 1, total_known_project_count: 1, relevant_project_count: 1, eligible_need_count: 1, pursued_eligible_need_count: 0, need_count: 1, priority_score: null, sectors: ['oil_gas'], featured_project: sampleProject }
const need = {
  id: 'need-1', project_id: 'project-1', name: 'Example Compressor Station', browse_title: 'Example Compressor Station', location: 'Permian Basin, TX', tier: 'Lead', workflow_status: 'New',
  activity: 'drilling', rationale: 'Synthetic fixture.', signal_evidence_state: 'active_evidence', required_mw: null, start_window: null, duration: null, supply: 'Unknown',
  next_action: 'Confirm the fixture package.', conflict_state: 'Not assessed', title_company: 'Example Energy', commercial_organization: 'Example Energy', evidence: [], missing_facts: [],
}
const pursuit = (id: string, needId: string, extra: Record<string, unknown> = {}) => ({
  id, need_id: needId, project_id: `project-${id}`, stage: 'New', title: `Synthetic Pursuit ${id}`, location: null, tier: 'Lead', required_mw: null, start_window: null,
  contact: null, contact_status: 'unknown', attention: [], attention_labels: [], next_task: null, created_at: '2026-11-01T12:00:00Z', stage_changed_at: '2026-11-01T12:00:00Z', ...extra,
})

type Request = { method: string; search: string; body: any }
async function setup(page: Page, seed: ReturnType<typeof pursuit>[]) {
  const store = [...seed]
  const requests: Request[] = []
  await mockDemandSummary(page)
  await page.route(url => url.pathname.startsWith('/api/') && !url.pathname.includes('demand-summary'), route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method()
    if (path === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (path === '/api/opportunities/groups') return route.fulfill({ json: { items: [group], total: 1, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'g1', generation: 'g', valid_until: '2099-01-01T00:00:00Z' } })
    if (path === '/api/opportunities/groups/group-1/open') return route.fulfill({ json: {
      group,
      projects: { items: [sampleProject], total: 1, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'p1', generation: 'g', valid_until: '2099-01-01T00:00:00Z' },
      parent_cohort_token: 'g1', generation: 'g', valid_until: '2099-01-01T00:00:00Z',
    } })
    if (path.startsWith('/api/opportunities/groups/') && path.endsWith('/projects')) return route.fulfill({ json: { items: [sampleProject], total: 1, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'p1', parent_cohort_token: 'g1', generation: 'g', valid_until: '2099-01-01T00:00:00Z' } })
    if (path === '/api/opportunities/projects') return route.fulfill({ json: { items: [sampleProject], total: 1, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'p1', generation: 'g', valid_until: '2099-01-01T00:00:00Z' } })
    if (path === '/api/opportunities/needs/need-1') return route.fulfill({ json: need })
    if (path === '/api/commercial-pursuits') {
      let body: any = null
      try { body = request.postDataJSON() } catch { /* no body */ }
      requests.push({ method, search: url.search, body })
      if (method === 'POST') {
        const created = pursuit('p-new', body.need_id)
        store.unshift(created)
        return route.fulfill({ status: 201, json: created })
      }
      const limit = Number(url.searchParams.get('limit') ?? 100), offset = Number(url.searchParams.get('offset') ?? 0)
      let items = store
      if (url.searchParams.get('need_id')) items = items.filter(item => item.need_id === url.searchParams.get('need_id'))
      if (url.searchParams.get('active_only') === 'true') items = items.filter(item => !['Won', 'Lost'].includes(item.stage))
      const next = offset + limit < items.length ? offset + limit : null
      return route.fulfill({ json: { items: items.slice(offset, offset + limit), counts: { total: store.length, active: store.length, needs_attention: 0 }, total_matching: items.length, has_more: next !== null, next_offset: next } })
    }
    return route.fulfill({ json: [] })
  })
  return { requests, posts: () => requests.filter(entry => entry.method === 'POST') }
}

async function openDefaultDetail(page: Page) {
  await page.goto('/?view=workspace')
  expect(new URL(page.url()).searchParams.get('projectBrowse')).toBeNull()
  await expect(page.getByRole('heading', { name: 'Customers' })).toBeVisible()
  await page.getByRole('button', { name: 'View account details' }).click()
  await expect(page.getByRole('region', { name: 'Company Example Energy' })).toBeVisible()
  await page.getByRole('button', { name: /Open project detail .*Example Compressor Station/ }).click()
  await expect(page).toHaveURL(/need=need-1/)
  await expect(page.locator('.cod-panel')).toBeVisible()
}

async function openGroupDetail(page: Page) {
  await page.goto('/?view=workspace')
  await page.getByRole('button', { name: 'View account details' }).click()
  await expect(page.getByRole('region', { name: 'Company Example Energy' })).toBeVisible()
  await page.getByRole('button', { name: /Open project detail .*Example Compressor Station/ }).click()
  await expect(page).toHaveURL(/need=need-1/)
  await expect(page.locator('.cod-panel')).toBeVisible()
}

test('default browse: Add to Pursuit on the selected need creates once, shows In Pursuits and bumps the badge', async ({ page }) => {
  const api = await setup(page, [])
  await page.goto('/?view=workspace')
  // Nothing selected, so no pursuit action is offered.
  await expect(page.locator('.cod-panel').getByRole('button', { name: 'Add to Pursuit' })).toHaveCount(0)
  await openDefaultDetail(page)
  const add = page.locator('.cod-panel').getByRole('button', { name: 'Add to Pursuit' })
  await expect(add).toBeVisible()
  await expect(page.getByTestId('nav-badge-pursuits')).toHaveCount(0)
  await add.dblclick()
  const added = page.locator('.cod-panel').getByRole('link', { name: 'In Pursuits' })
  await expect(added).toHaveAttribute('href', '/?view=pursuits&pursuit=p-new')
  await expect(page.getByTestId('nav-badge-pursuits')).toHaveText('1')
  expect(api.posts()).toHaveLength(1)
  expect(api.posts()[0].body).toEqual({ need_id: 'need-1' })
  await expect(page.locator('.cod-panel').getByRole('button', { name: 'Add to Pursuit' })).toHaveCount(0)
})

test('default browse: an already-pursued need shows In Pursuits and never offers a second create', async ({ page }) => {
  const api = await setup(page, [pursuit('p1', 'need-1')])
  await openDefaultDetail(page)
  await expect(page.locator('.cod-panel').getByRole('link', { name: 'In Pursuits' })).toHaveAttribute('href', '/?view=pursuits&pursuit=p1')
  await expect(page.locator('.cod-panel').getByRole('button', { name: 'Add to Pursuit' })).toHaveCount(0)
  await expect(page.getByTestId('nav-badge-pursuits')).toHaveText('1')
  expect(api.posts()).toHaveLength(0)
})

test('default browse: the action is keyboard reachable on a phone-width detail with no horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const api = await setup(page, [])
  await openDefaultDetail(page)
  const add = page.locator('.cod-panel').getByRole('button', { name: 'Add to Pursuit' })
  await expect(add).toBeVisible()
  await add.focus()
  await page.keyboard.press('Enter')
  await expect(page.locator('.cod-panel').getByRole('link', { name: 'In Pursuits' })).toBeVisible()
  expect(api.posts()).toHaveLength(1)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})

test('a pursuit that is only on page two of the store load is found: In Pursuits, no create, no targeted lookup', async ({ page }) => {
  const fillers = Array.from({ length: 249 }, (_, index) => pursuit(`f${index}`, `need-filler-${index}`))
  const all = [...fillers.slice(0, 230), pursuit('p-late', 'need-1'), ...fillers.slice(230)]
  const api = await setup(page, all)
  await openDefaultDetail(page)
  await expect(page.locator('.cod-panel').getByRole('link', { name: 'In Pursuits' })).toHaveAttribute('href', '/?view=pursuits&pursuit=p-late')
  await expect(page.locator('.cod-panel').getByRole('button', { name: 'Add to Pursuit' })).toHaveCount(0)
  await expect(page.getByTestId('nav-badge-pursuits')).toHaveText('250')
  const reads = api.requests.filter(entry => entry.method === 'GET')
  expect(reads.map(entry => new URLSearchParams(entry.search).get('offset'))).toEqual([null, '200'])
  expect(reads.every(entry => new URLSearchParams(entry.search).get('limit') === '200')).toBe(true)
})

test('a truncated store load still runs the targeted lookup before offering Add to Pursuit', async ({ page }) => {
  const all = Array.from({ length: 2300 }, (_, index) => pursuit(`f${index}`, index === 2250 ? 'need-1' : `need-filler-${index}`))
  const api = await setup(page, all)
  await openDefaultDetail(page)
  await expect(page.locator('.cod-panel').getByRole('link', { name: 'In Pursuits' })).toHaveAttribute('href', '/?view=pursuits&pursuit=f2250')
  // The flat detail can resolve via the targeted lookup before the capped store paging finishes; wait for it.
  const storeReads = () => api.requests.filter(entry => entry.method === 'GET' && !new URLSearchParams(entry.search).get('need_id'))
  await expect.poll(() => storeReads().length).toBe(10)
  const reads = api.requests.filter(entry => entry.method === 'GET')
  expect(storeReads()).toHaveLength(10)
  expect(reads.some(entry => new URLSearchParams(entry.search).get('need_id') === 'need-1')).toBe(true)
})

test('account-first browse: Add to Pursuit creates once and shows In Pursuits', async ({ page }) => {
  const api = await setup(page, [])
  await openGroupDetail(page)
  const add = page.locator('.cod-panel').getByRole('button', { name: 'Add to Pursuit' })
  await expect(add).toBeVisible()
  await add.dblclick()
  await expect(page.locator('.cod-panel').getByRole('link', { name: 'In Pursuits' })).toHaveAttribute('href', '/?view=pursuits&pursuit=p-new')
  await expect(page.getByTestId('nav-badge-pursuits')).toHaveText('1')
  expect(api.posts()).toHaveLength(1)
  expect(api.posts()[0].body).toEqual({ need_id: 'need-1' })
})

test('Pursuits page shows Showing 200 of 250 and Load more fetches the rest', async ({ page }) => {
  const all = Array.from({ length: 250 }, (_, index) => pursuit(`f${index}`, `need-filler-${index}`))
  const api = await setup(page, all)
  await page.goto('/?view=pursuits')
  await expect(page.locator('.pu-cards > li')).toHaveCount(200)
  await expect(page.getByText('Showing 200 of 250')).toBeVisible()
  await page.getByRole('button', { name: 'Load more' }).click()
  await expect(page.locator('.pu-cards > li')).toHaveCount(250)
  await expect(page.getByText('Showing 200 of 250')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Load more' })).toHaveCount(0)
  const offsets = api.requests.map(entry => new URLSearchParams(entry.search).get('offset'))
  expect(offsets).toContain('200')
})

test('Pursuits page filters stay server-side when paging', async ({ page }) => {
  const all = Array.from({ length: 250 }, (_, index) => pursuit(`f${index}`, `need-filler-${index}`))
  const api = await setup(page, all)
  await page.goto('/?view=pursuits&filter=active')
  await expect(page.getByText('Showing 200 of 250')).toBeVisible()
  await page.getByRole('button', { name: 'Load more' }).click()
  await expect(page.locator('.pu-cards > li')).toHaveCount(250)
  // The nav store also pages (unfiltered); the list's own continuation must carry the server-side filter.
  const params = api.requests.map(entry => new URLSearchParams(entry.search))
  expect(params.some(query => query.get('offset') === '200' && query.get('active_only') === 'true')).toBe(true)
})
