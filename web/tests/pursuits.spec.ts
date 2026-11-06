import { expect, test, type Page, type Route } from '@playwright/test'
import { mockDemandSummary } from './mock-demand-summary'

// SYNTHETIC UI TEST FIXTURE ONLY — names, contacts, dates and power values are fabricated; no real company or site is described.

type Task = { id: string; description: string; due_date: string | null; completed_at: string | null }
type Pursuit = Record<string, any> & { id: string; need_id: string; tasks: Task[]; activity: any[] }

const contact = { name: 'Alex Test Contact', role: 'Synthetic Role', company: 'Example Compute Holdings (test fixture)', phone: '+1 206 555 0184', email: 'alex@example.test' }
const pursuit = (id: string, needId: string, extra: Record<string, unknown> = {}): Pursuit => ({
  id, need_id: needId, project_id: `project-${id}`, stage: 'New', title: `Synthetic Campus ${id.toUpperCase()}`, location: 'Phoenix, AZ', tier: 'Lead',
  required_mw: null, start_window: null, contact, contact_status: 'available', attention: [], attention_labels: [], next_task: null,
  created_at: '2026-11-01T12:00:00Z', stage_changed_at: '2026-11-01T12:00:00Z', tasks: [], activity: [{ id: `a-${id}`, kind: 'created', summary: 'Added to Pursuits', detail: null, occurred_at: '2026-11-01T12:00:00Z' }], ...extra,
})
const opportunity = {
  id: 'need-1', project_id: 'project-1', name: 'Synthetic Opportunity One', browse_title: 'Synthetic Opportunity One', location: 'Phoenix, AZ', tier: 'Lead', workflow_status: 'New',
  activity: 'data center construction', rationale: 'A retained notice identifies a campus project.', signal_evidence_state: 'active_evidence', required_mw: null, start_window: null,
  duration: null, supply: 'Unknown', next_action: 'Confirm the fixture package.', conflict_state: 'Not assessed', title_company: 'Synthetic Holdings', commercial_organization: 'Synthetic Holdings',
  evidence: [], missing_facts: [], intelligence_card: undefined,
}
const project = {
  id: 'project-1', project_id: 'project-1', name: 'Synthetic Holdings · Synthetic Opportunity One', company: 'Synthetic Holdings', location: 'Phoenix, AZ',
  sector: 'data_centers', asset_type: 'data_center_campus', priority_score: null, representative_need_id: 'need-1', need_count: 1,
  needs: [{ id: 'need-1', project_id: 'project-1', tier: 'Lead', activity: 'data center construction' }],
  event: null, contact: [], contact_people: [], power_summary: null, power_summary_kind: 'unknown', next_action: 'Confirm fixture details.', updated_at: '2026-10-21T00:00:00Z',
}
const emptyProjects = { items: [project], total: 1, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'pursuit-fixture', generation: 'synthetic-fixture' }
const summary = (p: Pursuit) => { const { tasks, activity, ...rest } = p; return { ...rest, next_task: tasks.find(t => !t.completed_at) ?? null } }

type Log = { method: string; path: string; search: string; body: any }
async function setup(page: Page, seed: Pursuit[], hooks: { failActivity?: number; failTask?: boolean; unauthorizedStage?: boolean; listUnauthorizedAfterWrite?: boolean; listUnauthorized?: boolean; holdList?: Promise<void>; holdLookup?: Promise<void>; lookupUnauthorized?: boolean; listFails?: boolean } = {}) {
  const store = new Map(seed.map(p => [p.id, p]))
  const log: Log[] = []
  let activityFailures = hooks.failActivity ?? 0
  let wrote = false
  const counts = () => { const all = [...store.values()]; return { total: all.length, active: all.filter(p => !['Won', 'Lost'].includes(p.stage)).length, needs_attention: all.filter(p => p.attention.length).length } }
  await mockDemandSummary(page)
  await page.route(url => url.pathname.startsWith('/api/'), async (route: Route) => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method()
    let body: any = null
    try { body = request.postDataJSON() } catch { /* no body */ }
    if (path.startsWith('/api/commercial-pursuits')) log.push({ method, path, search: url.search, body })
    if (path === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (path === '/api/opportunities/needs/need-1') return route.fulfill({ json: opportunity })
    if (path === '/api/opportunities/projects') return route.fulfill({ json: emptyProjects })
    if (path === '/api/commercial-pursuits' && method === 'GET') {
      const lookup = url.searchParams.has('need_id')
      if (lookup && hooks.lookupUnauthorized) return route.fulfill({ status: 401, json: { detail: 'Not authenticated' } })
      if (lookup && hooks.holdLookup) await hooks.holdLookup
      if (!lookup && hooks.holdList) await hooks.holdList
      if (!lookup && hooks.listFails) return route.fulfill({ status: 500, json: { detail: 'Unavailable' } })
      if (hooks.listUnauthorized || (hooks.listUnauthorizedAfterWrite && wrote)) return route.fulfill({ status: 401, json: { detail: 'Not authenticated' } })
      let items = [...store.values()]
      if (url.searchParams.get('needs_attention') === 'true') items = items.filter(p => p.attention.length)
      if (url.searchParams.get('active_only') === 'true') items = items.filter(p => !['Won', 'Lost'].includes(p.stage))
      if (url.searchParams.get('need_id')) items = items.filter(p => p.need_id === url.searchParams.get('need_id'))
      return route.fulfill({ json: { items: items.map(summary), counts: counts() } })
    }
    if (path === '/api/commercial-pursuits' && method === 'POST') {
      await new Promise(resolve => setTimeout(resolve, 150))
      const created = pursuit('p-new', body.need_id)
      store.set(created.id, created)
      return route.fulfill({ status: 201, json: created })
    }
    const match = /^\/api\/commercial-pursuits\/([^/]+)(?:\/(tasks|activity)(?:\/([^/]+))?)?$/.exec(path)
    const found = match ? store.get(match[1]) : undefined
    if (match && !found) return route.fulfill({ status: 404, json: { detail: 'Pursuit not found' } })
    if (match && found) {
      const [, , kind, taskId] = match
      if (!kind && method === 'GET') return route.fulfill({ json: found })
      if (!kind && method === 'PATCH' && hooks.unauthorizedStage) return route.fulfill({ status: 401, json: { detail: 'Not authenticated' } })
      if (!kind && method === 'PATCH') { wrote = true; found.stage = body.stage; return route.fulfill({ json: found }) }
      if (kind === 'tasks' && method === 'POST') {
        if (hooks.failTask) return route.fulfill({ status: 500, json: { detail: 'Task store unavailable' } })
        found.tasks.push({ id: `t${found.tasks.length + 1}`, description: body.description, due_date: body.due_date ?? null, completed_at: null })
        return route.fulfill({ status: 201, json: found })
      }
      if (kind === 'tasks' && method === 'PATCH') {
        const task = found.tasks.find(t => t.id === taskId)!
        if (body.completed === true) task.completed_at = '2026-11-02T10:00:00Z'
        if (body.completed === false) task.completed_at = null
        if (body.description) task.description = body.description
        if (body.due_date) task.due_date = body.due_date
        if (body.clear_due_date) task.due_date = null
        return route.fulfill({ json: found })
      }
      if (kind === 'activity' && method === 'POST') {
        if (activityFailures > 0) { activityFailures -= 1; return route.fulfill({ status: 500, json: { detail: 'Activity store unavailable' } }) }
        found.activity.unshift({ id: `a${found.activity.length + 1}`, kind: body.kind, summary: body.summary, detail: body.detail, occurred_at: '2026-11-02T10:00:00Z' })
        return route.fulfill({ status: 201, json: found })
      }
    }
    return route.fulfill({ json: [] })
  })
  return { log, store, writes: () => log.filter(entry => entry.method !== 'GET') }
}

const attention = (labels: string[]) => ({ attention: labels.map(label => label.toLowerCase().replaceAll(' ', '_')), attention_labels: labels })

test('Add to Pursuit shows In Pursuits, bumps the nav badge and never double-creates', async ({ page }) => {
  const api = await setup(page, [])
  await page.goto('/?view=workspace&projectBrowse=1&need=need-1')
  const add = page.getByRole('button', { name: 'Add to Pursuit' })
  await expect(add).toBeVisible()
  await expect(page.getByRole('button', { name: 'View Full Details' })).toBeVisible()
  await expect(page.getByTestId('nav-badge-pursuits')).toHaveCount(0)
  await add.dblclick()
  await expect(page.getByRole('link', { name: 'In Pursuits' })).toHaveAttribute('href', '/?view=pursuits&pursuit=p-new')
  await expect(page.getByTestId('nav-badge-pursuits')).toHaveText('1')
  expect(api.writes().filter(entry => entry.method === 'POST')).toHaveLength(1)
  expect(api.writes()[0].body).toEqual({ need_id: 'need-1' })
  // In-app navigation to the new pursuit, no reload.
  await page.evaluate(() => { (window as any).__marker = 1 })
  await page.getByRole('link', { name: 'In Pursuits' }).click()
  await expect(page).toHaveURL(/view=pursuits&pursuit=p-new/)
  await expect(page.getByRole('heading', { name: 'Synthetic Campus P-NEW' })).toBeVisible()
  expect(await page.evaluate(() => (window as any).__marker)).toBe(1)
})

test('Add to Pursuit failure shows an inline error and the button stays usable', async ({ page }) => {
  await setup(page, [])
  let attempts = 0
  await page.route('**/api/commercial-pursuits', async (route, request) => {
    if (request.method() !== 'POST') return route.fallback()
    attempts += 1
    if (attempts === 1) return route.fulfill({ status: 500, json: { detail: 'Pursuit store unavailable' } })
    return route.fulfill({ status: 201, json: pursuit('p-new', 'need-1') })
  })
  await page.goto('/?view=workspace&projectBrowse=1&need=need-1')
  await page.getByRole('button', { name: 'Add to Pursuit' }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'Could not add to Pursuits' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Add to Pursuit' })).toBeEnabled()
  await page.getByRole('button', { name: 'Add to Pursuit' }).click()
  await expect(page.getByRole('link', { name: 'In Pursuits' })).toBeVisible()
})

test('an opportunity that already has a pursuit starts as In Pursuits', async ({ page }) => {
  await setup(page, [pursuit('p1', 'need-1')])
  await page.goto('/?view=workspace&projectBrowse=1&need=need-1')
  await expect(page.getByRole('link', { name: 'In Pursuits' })).toHaveAttribute('href', '/?view=pursuits&pursuit=p1')
  await expect(page.getByRole('button', { name: 'Add to Pursuit' })).toHaveCount(0)
  await expect(page.getByTestId('nav-badge-pursuits')).toHaveText('1')
})

test('existing pursuit is found by need_id lookup when the store list failed to load', async ({ page }) => {
  await setup(page, [pursuit('p1', 'need-1')])
  let listCalls = 0
  await page.route('**/api/commercial-pursuits?*', async (route, request) => {
    const url = new URL(request.url())
    if (!url.searchParams.get('need_id')) { listCalls += 1; return route.fulfill({ status: 503, json: { detail: 'unavailable' } }) }
    return route.fallback()
  })
  await page.goto('/?view=workspace&projectBrowse=1&need=need-1')
  await expect(page.getByRole('link', { name: 'In Pursuits' })).toBeVisible()
  expect(listCalls).toBeGreaterThan(0)
})

test('Pursuits list, counts and the Needs Attention filter use only API fields', async ({ page }) => {
  const api = await setup(page, [
    pursuit('p1', 'need-a', { required_mw: '120', start_window: '2027-Q2', ...attention(['Follow-up overdue']) }),
    pursuit('p2', 'need-b', { stage: 'Won' }),
    pursuit('p3', 'need-c', { contact: null, contact_status: 'missing', ...attention(['No usable contact method']) }),
  ])
  await page.goto('/?view=pursuits')
  await expect(page.getByRole('heading', { name: 'Pursuits', level: 1 })).toBeVisible()
  await expect(page.locator('.pu-heading').getByText('2 active pursuits')).toBeVisible()
  await expect(page.getByTestId('attention-count')).toHaveText('2')
  await expect(page.locator('.pu-card')).toHaveCount(3)
  const first = page.locator('.pu-card', { hasText: 'Synthetic Campus P1' })
  await expect(first).toContainText('120 MW')
  await expect(first).toContainText('Power timing')
  await expect(first).toContainText('2027-Q2')
  await expect(first).toContainText('Follow-up overdue')
  await expect(page.locator('.pu-card', { hasText: 'Synthetic Campus P2' })).toContainText('Unknown')
  await expect(page.locator('.pu-card', { hasText: 'Synthetic Campus P2' })).not.toContainText(/\b0 MW\b/)
  await expect(page.locator('.pu-page')).not.toContainText(/confidence/i)
  await page.getByRole('button', { name: /^Active/ }).click()
  await expect(page.locator('.pu-card')).toHaveCount(2)
  await expect(page).toHaveURL(/filter=active/)
  expect(api.log.some(entry => entry.method === 'GET' && entry.search.includes('active_only=true') && entry.search.includes('limit=200'))).toBe(true)
  await expect(page.getByRole('button', { name: /Needs Attention/ })).toContainText('2 need attention')
  await page.getByRole('button', { name: /Needs Attention/ }).click()
  await expect(page.locator('.pu-card')).toHaveCount(2)
  await expect(page.locator('.pu-card', { hasText: 'Synthetic Campus P2' })).toHaveCount(0)
  expect(api.log.some(entry => entry.method === 'GET' && entry.search.includes('needs_attention=true'))).toBe(true)
  await expect(page.locator('.pu-card', { hasText: 'Synthetic Campus P3' })).toContainText('No usable contact method')
})

test('stage stepper PATCHes the stage and contact links never change it', async ({ page }) => {
  const api = await setup(page, [pursuit('p1', 'need-a')])
  await page.goto('/?view=pursuits&pursuit=p1')
  const status = page.getByRole('region', { name: 'Pursuit status' })
  await expect(status.getByRole('button', { name: /New/ })).toHaveAttribute('aria-current', 'step')
  await expect(page.getByRole('link', { name: 'Call +1 206 555 0184' })).toHaveAttribute('href', 'tel:+12065550184')
  await expect(page.getByRole('link', { name: 'Email alex@example.test' })).toHaveAttribute('href', 'mailto:alex@example.test')
  await page.locator('a[href^="tel:"], a[href^="mailto:"]').evaluateAll(links => links.forEach(link => link.addEventListener('click', event => event.preventDefault())))
  await page.getByRole('link', { name: /^Call/ }).click()
  await page.getByRole('link', { name: /^Email/ }).click()
  expect(api.writes()).toHaveLength(0)
  await status.getByRole('button', { name: /Engaged/ }).click()
  await expect(status.getByRole('button', { name: /Engaged/ })).toHaveAttribute('aria-current', 'step')
  expect(api.writes()).toEqual([expect.objectContaining({ method: 'PATCH', path: '/api/commercial-pursuits/p1', body: { stage: 'Engaged' } })])
  await status.getByRole('button', { name: 'Mark as Lost' }).click()
  await expect(page.getByRole('button', { name: 'Closed as Lost' })).toBeDisabled()
  expect(api.writes()[1].body).toEqual({ stage: 'Lost' })
})

test('follow-up tasks can be added and completed; a failed add keeps the typed input', async ({ page }) => {
  const api = await setup(page, [pursuit('p1', 'need-a')])
  await page.goto('/?view=pursuits&pursuit=p1')
  const card = page.getByRole('region', { name: 'Next Action' })
  await expect(card).toContainText('No follow-up scheduled')
  await card.getByLabel('Follow-up description').fill('Send load letter')
  await card.getByLabel('Follow-up due date (optional)').fill('2026-12-01')
  await card.getByRole('button', { name: 'Add follow-up' }).click()
  await expect(card.getByText('Send load letter')).toBeVisible()
  expect(api.writes()[0]).toMatchObject({ method: 'POST', path: '/api/commercial-pursuits/p1/tasks', body: { description: 'Send load letter', due_date: '2026-12-01' } })
  await card.getByLabel('Complete follow-up: Send load letter').click()
  await expect(page.getByText('Completed (1)')).toBeVisible()
  expect(api.writes()[1]).toMatchObject({ method: 'PATCH', path: '/api/commercial-pursuits/p1/tasks/t1', body: { completed: true } })
})

test('a failed task write shows an error and keeps the typed task', async ({ page }) => {
  await setup(page, [pursuit('p1', 'need-a')], { failTask: true })
  await page.goto('/?view=pursuits&pursuit=p1')
  const card = page.getByRole('region', { name: 'Next Action' })
  await card.getByLabel('Follow-up description').fill('Call the utility')
  await card.getByRole('button', { name: 'Add follow-up' }).click()
  await expect(card.getByRole('alert')).toContainText('Task store unavailable')
  await expect(card.getByLabel('Follow-up description')).toHaveValue('Call the utility')
})

test('activity is only recorded after the explicit confirm action and survives a failed write', async ({ page }) => {
  const api = await setup(page, [pursuit('p1', 'need-a')], { failActivity: 1 })
  await page.goto('/?view=pursuits&pursuit=p1')
  const form = page.getByRole('region', { name: 'Activity' })
  await form.getByLabel('Type').selectOption('email')
  await form.getByLabel('Summary').fill('Sent the intro email')
  await form.getByLabel('Details (optional)').fill('Asked about the 2027 timeline')
  await page.locator('a[href^="tel:"], a[href^="mailto:"]').evaluateAll(links => links.forEach(link => link.addEventListener('click', event => event.preventDefault())))
  await page.getByRole('link', { name: /^Email/ }).click()
  expect(api.writes()).toHaveLength(0)
  await form.getByRole('button', { name: 'Log as happened' }).click()
  await expect(form.getByRole('alert')).toContainText('Activity store unavailable')
  await expect(form.getByLabel('Summary')).toHaveValue('Sent the intro email')
  await expect(form.getByLabel('Details (optional)')).toHaveValue('Asked about the 2027 timeline')
  await form.getByRole('button', { name: 'Log as happened' }).click()
  await expect(form.getByLabel('Summary')).toHaveValue('')
  await expect(form.locator('.pu-activity')).toContainText('Sent the intro email')
  const posts = api.writes().filter(entry => entry.path.endsWith('/activity'))
  expect(posts).toHaveLength(2)
  expect(posts[1].body).toMatchObject({ kind: 'email', summary: 'Sent the intro email', detail: 'Asked about the 2027 timeline', confirmed: true })
  expect(posts[1].body.client_id).toMatch(/^[0-9a-f-]{36}$/)
  // The retry of the same entry is idempotent; a new entry gets a new id.
  expect(posts[0].body.client_id).toBe(posts[1].body.client_id)
  await form.getByLabel('Summary').fill('Another note')
  await form.getByRole('button', { name: 'Log as happened' }).click()
  await expect(form.locator('.pu-activity')).toContainText('Another note')
  expect(api.writes().filter(entry => entry.path.endsWith('/activity'))[2].body.client_id).not.toBe(posts[1].body.client_id)
})

test('missing contact shows a clear state with an evidence link and no Call or Email buttons', async ({ page }) => {
  await setup(page, [pursuit('p1', 'need-a', { contact: null, contact_status: 'missing', ...attention(['No usable contact method']) })])
  await page.goto('/?view=pursuits&pursuit=p1')
  const region = page.getByRole('region', { name: 'Contact' })
  await expect(region).toContainText('No usable contact method')
  await expect(region.getByRole('link', { name: /evidence/i })).toHaveAttribute('href', '/?view=workspace&need=need-a')
  await expect(page.getByRole('link', { name: /^Call/ })).toHaveCount(0)
  await expect(page.getByRole('link', { name: /^Email/ })).toHaveCount(0)
})

test('phone-only contact exposes only Call; unsafe values never become links', async ({ page }) => {
  await setup(page, [pursuit('p1', 'need-a', { contact: { ...contact, phone: '(206) 555-0184', email: 'bad address@x' } })])
  await page.goto('/?view=pursuits&pursuit=p1')
  await expect(page.getByRole('link', { name: /^Email/ })).toHaveCount(0)
  const href = await page.getByRole('link', { name: /^Call/ }).getAttribute('href')
  expect(href).toBe('tel:2065550184')
  await expect(page.getByText('bad address@x')).toBeVisible()
})

test('deep link, back and forward restore selection and filter without a reload', async ({ page }) => {
  await setup(page, [pursuit('p1', 'need-a'), pursuit('p2', 'need-b', attention(['Follow-up overdue']))])
  await page.goto('/?view=pursuits&filter=attention&pursuit=p2')
  await expect(page.getByRole('heading', { name: 'Synthetic Campus P2', level: 2 })).toBeVisible()
  await expect(page.getByRole('button', { name: /Needs Attention/ })).toHaveAttribute('aria-pressed', 'true')
  await page.evaluate(() => { (window as any).__marker = 7 })
  await page.getByRole('button', { name: '← Pursuits' }).click()
  await expect(page).toHaveURL(/filter=attention/)
  await expect(page).not.toHaveURL(/pursuit=/)
  await expect(page.getByText('Select a pursuit')).toBeVisible()
  await page.goBack()
  await expect(page.getByRole('heading', { name: 'Synthetic Campus P2', level: 2 })).toBeVisible()
  await page.goForward()
  await expect(page.getByText('Select a pursuit')).toBeVisible()
  await expect(page.getByRole('button', { name: /Needs Attention/ })).toHaveAttribute('aria-pressed', 'true')
  expect(await page.evaluate(() => (window as any).__marker)).toBe(7)
})

test('header Pursuits button and account-menu Research route to separate views', async ({ page }) => {
  await setup(page, [pursuit('p1', 'need-a')])
  await page.goto('/?view=workspace')
  await page.getByRole('navigation', { name: 'Primary navigation' }).getByRole('button', { name: /Pursuits/ }).click()
  await expect(page).toHaveURL(/view=pursuits/)
  await expect(page.getByRole('heading', { name: 'Pursuits', level: 1 })).toBeVisible()
  await page.locator('.wh-account summary').click()
  await page.locator('.wh-account').getByRole('button', { name: 'Research' }).click()
  await expect(page).toHaveURL(/view=research/)
  await expect(page.getByRole('heading', { name: 'Pursuits', level: 1 })).toHaveCount(0)
})

test('phone width has no horizontal overflow in list or detail', async ({ page }) => {
  await setup(page, [pursuit('p1', 'need-a', { title: 'A very long synthetic campus name that must wrap cleanly on a narrow phone screen without scrolling', required_mw: '120', start_window: '2027-Q2', ...attention(['Follow-up overdue', 'Source-reported power timing within 30 days']) })])
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/?view=pursuits')
  await expect(page.locator('.pu-card')).toHaveCount(1)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.locator('.pu-card').click()
  await expect(page.getByRole('heading', { level: 2 })).toBeVisible()
  await expect(page.locator('.pu-list-panel')).toBeHidden()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.getByRole('button', { name: '← Pursuits' }).click()
  await expect(page.locator('.pu-card')).toBeVisible()
})

test('an ended session removes pursuit contact data and shows a session-ended state', async ({ page }) => {
  await setup(page, [pursuit('p1', 'need-a')], { unauthorizedStage: true })
  await page.goto('/?view=pursuits&pursuit=p1')
  await expect(page.getByText('alex@example.test').first()).toBeVisible()
  await page.getByRole('region', { name: 'Pursuit status' }).getByRole('button', { name: /Engaged/ }).click()
  await expect(page.getByText('alex@example.test')).toHaveCount(0)
  await expect(page.getByText('+1 206 555 0184')).toHaveCount(0)
  await expect(page.locator('.pu-card')).toHaveCount(0)
  await expect(page.getByText('Your session ended. Sign in again.').first()).toBeVisible()
})

test('the continuity event clears pursuit data on screen', async ({ page }) => {
  await setup(page, [pursuit('p1', 'need-a')])
  await page.goto('/?view=pursuits&pursuit=p1')
  await expect(page.getByText('alex@example.test').first()).toBeVisible()
  await page.evaluate(() => window.dispatchEvent(new Event('gl3-clear-continuity')))
  await expect(page.getByText('alex@example.test')).toHaveCount(0)
  await expect(page.locator('.pu-card')).toHaveCount(0)
  await expect(page.getByText('Your session ended. Sign in again.').first()).toBeVisible()
})

test('typing a due date saves only on blur and rejects years outside 2000-2100', async ({ page }) => {
  const api = await setup(page, [pursuit('p1', 'need-a', { tasks: [{ id: 't1', description: 'Call back', due_date: null, completed_at: null }] })])
  await page.goto('/?view=pursuits&pursuit=p1')
  const due = page.getByLabel('Due date for: Call back')
  await due.fill('0002-03-04')
  expect(api.writes()).toHaveLength(0)
  await due.blur()
  await expect(page.getByText('Choose a due date between 2000 and 2100.')).toBeVisible()
  expect(api.writes()).toHaveLength(0)
  await due.fill('2027-03-04')
  expect(api.writes()).toHaveLength(0)
  await due.blur()
  await expect.poll(() => api.writes().length).toBe(1)
  expect(api.writes()[0].body).toEqual({ due_date: '2027-03-04' })
})

test('activity times are labelled as logged times', async ({ page }) => {
  await setup(page, [pursuit('p1', 'need-a')])
  await page.goto('/?view=pursuits&pursuit=p1')
  await expect(page.getByRole('region', { name: 'Activity' }).locator('time')).toContainText(/^Logged /)
})

test('no URL filter means All even after visiting another filter', async ({ page }) => {
  await setup(page, [pursuit('p1', 'need-a'), pursuit('p2', 'need-b', { stage: 'Won' })])
  await page.goto('/?view=pursuits&filter=active')
  await expect(page.locator('.pu-card')).toHaveCount(1)
  await page.goto('/?view=workspace')
  await page.getByRole('navigation', { name: 'Primary navigation' }).getByRole('button', { name: /Pursuits/ }).click()
  await expect(page.getByRole('button', { name: 'All Pursuits' })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('.pu-card')).toHaveCount(2)
})

test('header badge and attention count have descriptive accessible names', async ({ page }) => {
  await setup(page, [pursuit('p1', 'need-a', attention(['Follow-up overdue'])), pursuit('p2', 'need-b')])
  await page.goto('/?view=pursuits')
  await expect(page.getByRole('navigation', { name: 'Primary navigation' }).getByRole('button', { name: 'Pursuits 2 active pursuits' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Needs Attention 1 needs attention' })).toBeVisible()
})

test('legacy view=pursuits links carrying research parameters open Research', async ({ page }) => {
  await setup(page, [pursuit('p1', 'need-a')])
  await page.goto('/?view=pursuits&q=Northstar')
  await expect(page.getByRole('heading', { name: 'Pursuits', level: 1 })).toHaveCount(0)
  await page.goto('/?view=pursuits&researchNeed=need-1')
  await expect(page.getByRole('heading', { name: 'Pursuits', level: 1 })).toHaveCount(0)
})

/** Counts the two session events in the page so a test can tell a narrow pursuit-session end from a global continuity wipe. */
async function countSessionEvents(page: Page) {
  await page.addInitScript(() => {
    const seen = { continuity: 0, pursuits: 0 }; (window as any).__sessionEvents = seen
    addEventListener('gl3-clear-continuity', () => { seen.continuity += 1 }); addEventListener('gl3-pursuits-session-ended', () => { seen.pursuits += 1 })
  })
  return () => page.evaluate(() => ({ ...(window as any).__sessionEvents }))
}

test('a background 401 empties the open Pursuits list and detail without a global continuity wipe', async ({ page }) => {
  await setup(page, [pursuit('p1', 'need-a', { tasks: [{ id: 't1', description: 'Send synthetic follow-up', due_date: null, completed_at: null }] }), pursuit('p2', 'need-b')], { listUnauthorizedAfterWrite: true })
  const events = await countSessionEvents(page)
  await page.goto('/?view=pursuits&pursuit=p1')
  await expect(page.getByText('alex@example.test').first()).toBeVisible()
  await expect(page.getByText('+1 206 555 0184').first()).toBeVisible()
  await expect(page.getByText('Send synthetic follow-up').first()).toBeVisible()
  await expect(page.getByText('Added to Pursuits').first()).toBeVisible()
  // The write succeeds; its follow-up store refresh is a background read that now returns 401.
  await page.getByRole('region', { name: 'Pursuit status' }).getByRole('button', { name: /Engaged/ }).click()
  await expect(page.getByText('Your session ended. Sign in again.').first()).toBeVisible()
  for (const text of ['alex@example.test', '+1 206 555 0184', 'Send synthetic follow-up', 'Added to Pursuits', 'Synthetic Campus P1', 'Synthetic Campus P2']) await expect(page.getByText(text)).toHaveCount(0)
  await expect(page.locator('.pu-card')).toHaveCount(0)
  const seen = await events()
  expect(seen.pursuits).toBeGreaterThan(0)
  expect(seen.continuity).toBe(0)
})

test('a background 401 on the nav-count read ends an open Pursuits list', async ({ page }) => {
  await setup(page, [pursuit('p1', 'need-a')])
  await page.goto('/?view=pursuits')
  await expect(page.locator('.pu-card')).toHaveCount(1)
  await page.evaluate(() => window.dispatchEvent(new Event('gl3-pursuits-session-ended')))
  await expect(page.getByText('alex@example.test')).toHaveCount(0)
  await expect(page.locator('.pu-card')).toHaveCount(0)
  await expect(page.getByText('Your session ended. Sign in again.').first()).toBeVisible()
})

test('a background pursuit 401 leaves Opportunities search and the selected opportunity intact', async ({ page }) => {
  await setup(page, [], { listUnauthorized: true })
  const events = await countSessionEvents(page)
  await page.goto('/?view=workspace&projectBrowse=1&need=need-1')
  await expect(page.getByRole('button', { name: 'View Full Details' })).toBeVisible()
  const search = page.getByRole('searchbox', { name: 'Search companies, projects, contacts and opportunities' })
  await search.fill('synthetic query')
  await expect.poll(async () => (await events()).pursuits).toBeGreaterThan(0)
  expect((await events()).continuity).toBe(0)
  await expect(search).toHaveValue('synthetic query')
  await expect(page.getByRole('button', { name: 'View Full Details' })).toBeVisible()
  await expect(page).toHaveURL(/need=need-1/)
  await expect(page.getByText('Your session ended. Sign in again.')).toHaveCount(0)
})

/**
 * Holds the page's Pursuits list response, then releases it and dispatches the ended event a chosen number of microtask hops apart.
 * React flushes the ended update in a microtask after the event, so only a response callback already queued ahead of that flush can run before the request is aborted; sweeping the hop count reaches that window regardless of exact promise depth.
 */
for (const hops of [3, 4, 5, 6, 7]) {
  test(`a Pursuits list resolving in the microtask race with the ended event does not restore cards or contacts (${hops} hops)`, async ({ page }) => {
    await setup(page, [pursuit('p1', 'need-a'), pursuit('p2', 'need-b')])
    await page.addInitScript(() => {
      const original = window.fetch.bind(window)
      let open!: () => void
      const gate = new Promise<void>(resolve => { open = resolve })
      ;(window as any).__endThenRelease = (count: number) => {
        open()
        let chain: Promise<void> = Promise.resolve()
        for (let index = 0; index < count; index += 1) chain = chain.then(() => {})
        void chain.then(() => window.dispatchEvent(new Event('gl3-pursuits-session-ended')))
      }
      window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
        if (!/\/api\/commercial-pursuits\?/.test(url) || /need_id=/.test(url)) return original(input, init)
        // A buffered stand-in whose json() settles in microtasks only, so nothing yields to the renderer before the callbacks.
        return original(input, init).then(async response => { const body = await response.text(), status = response.status; await gate; return { ok: true, status, json: () => Promise.resolve(JSON.parse(body)) } as unknown as Response })
      }
    })
    await page.goto('/?view=pursuits')
    await expect(page.getByRole('status', { name: 'Loading pursuits' })).toBeVisible()
    await page.waitForTimeout(300)
    await page.evaluate(count => (window as any).__endThenRelease(count), hops)
    await expect(page.getByText('Your session ended. Sign in again.').first()).toBeVisible()
    await page.waitForTimeout(300)
    for (const text of ['Synthetic Campus P1', 'Synthetic Campus P2', 'Alex Test Contact', 'alex@example.test', '+1 206 555 0184']) await expect(page.getByText(text)).toHaveCount(0)
    await expect(page.locator('.pu-card')).toHaveCount(0)
  })
}

test('a held Add-to-Pursuit lookup resolving after the session ended does not show In Pursuits', async ({ page }) => {
  let release!: () => void
  const held = new Promise<void>(resolve => { release = resolve })
  await setup(page, [pursuit('p1', 'need-1')], { holdLookup: held, listFails: true })
  await page.goto('/?view=workspace&projectBrowse=1&need=need-1')
  await expect(page.getByRole('button', { name: 'View Full Details' })).toBeVisible()
  await page.evaluate(() => window.dispatchEvent(new Event('gl3-pursuits-session-ended')))
  release()
  await page.evaluate(() => new Promise(resolve => setTimeout(resolve, 300)))
  await expect(page.getByRole('link', { name: 'In Pursuits' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Add to Pursuit' })).toBeEnabled()
})

test('a background 401 on the lookup invalidates an earlier shared list read even when the store is empty', async ({ page }) => {
  let release!: () => void
  const held = new Promise<void>(resolve => { release = resolve })
  await setup(page, [pursuit('p1', 'need-1')], { holdList: held, lookupUnauthorized: true })
  const events = await countSessionEvents(page)
  await page.goto('/?view=workspace&projectBrowse=1&need=need-1')
  await expect(page.getByRole('button', { name: 'View Full Details' })).toBeVisible()
  await expect.poll(async () => (await events()).pursuits).toBeGreaterThan(0)
  release()
  await page.evaluate(() => new Promise(resolve => setTimeout(resolve, 300)))
  await expect(page.getByRole('link', { name: 'In Pursuits' })).toHaveCount(0)
  await expect(page.getByRole('navigation', { name: 'Primary navigation' }).getByRole('button', { name: /Pursuits \d+ active/ })).toHaveCount(0)
})
