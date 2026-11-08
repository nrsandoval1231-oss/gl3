import { expect, test, type Page } from '@playwright/test'
import { mockDemandSummary } from './mock-demand-summary'

const validUntil = new Date(Date.now() + 60 * 60 * 1000).toISOString()
const account = (id: string, name: string, featured_project: unknown = null) => ({ id, name, role: 'operator', group_kind: 'resolved_identity', project_count: 26, relevant_project_count: 1, total_known_project_count: 26, need_count: 26, sectors: ['oil_gas'], featured_project })
const project = (id: string, extra: Record<string, unknown> = {}) => ({
  id, project_id: id, name: `Synthetic project ${id}`, company: 'Synthetic Operator', customer_identity_id: 'company-synthetic', location: 'Midland, TX', sector: 'oil_gas', asset_type: 'Compressor station', priority_score: null,
  representative_need_id: `need-${id}`, need_count: 1, needs: [{ id: `need-${id}`, project_id: id, name: `Synthetic need ${id}` }], event: { kind: 'construction', label: 'Synthetic construction planned', date: null, source: 'https://example.invalid/synthetic-source' }, contact: [{ kind: 'email', label: 'Email buyer', href: 'mailto:buyer@example.invalid', name: 'Synthetic Buyer', title: 'Project Contact', responsibility: 'Project inquiry' }],
  power_summary: null, power_summary_kind: 'unknown', next_action: null, shortlist_assessment: { eligible: true, reasons: [], evidence_refs: [], why_now: 'Synthetic construction activity is planned.', next_step: 'Confirm the commissioning window.' }, updated_at: null, ...extra,
})

async function install(page: Page, options: { delayCedar?: () => Promise<void>; childExpiredOnce?: boolean; expireAtOffset?: number; projectTotal?: number } = {}) {
  await mockDemandSummary(page)
  await page.route(url => new URL(url).pathname.startsWith('/api/'), async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (url.pathname === '/api/opportunities/groups') {
      const items = [account('cg_north', 'Synthetic North'), account('cg_cedar', 'Synthetic Cedar')]
      return route.fulfill({ json: { items, total: items.length, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'groups-token', generation: 'synthetic' } })
    }
    if (url.pathname === '/api/opportunities/projects') return route.fulfill({ json: { items: [], total: 26, count_unit: 'projects', limit: 1, offset: 0, cohort_token: 'count-token', generation: 'synthetic', valid_until: validUntil } })
    if (/^\/api\/opportunities\/groups\/cg_(north|cedar)\/open$/.test(url.pathname)) {
      if (url.pathname.includes('cedar')) await options.delayCedar?.()
      const id = url.pathname.includes('cedar') ? 'cg_cedar' : 'cg_north'
      const name = id === 'cg_cedar' ? 'Synthetic Cedar' : 'Synthetic North'
      const eligible = [`need-${id}-p1`, `need-${id}-p1-phase2`]
      const featured = project(`${id}-p1`, { company: name, needs: [{ id: eligible[0], activity: 'Compressor expansion' }, { id: eligible[1], activity: 'Capacity upgrade' }], eligible_need_ids: eligible, contact: [{ kind: 'email', label: 'Email buyer', href: `mailto:${id}@example.invalid`, name: `${name} Buyer`, title: 'Project Contact' }] })
      const total = options.projectTotal ?? 26
      const items = Array.from({ length: 25 }, (_, index) => project(`${id}-p${index + 1}`, { company: name, needs: index === 0 ? featured.needs : [{ id: `need-${id}-p${index + 1}`, activity: 'Routine document update' }], eligible_need_ids: index === 0 ? eligible : [] }))
      return route.fulfill({ json: { group: { ...account(id, name, featured), relevant_project_count: 1, project_count: total, total_known_project_count: total }, parent_cohort_token: 'parent-current', generation: 'synthetic', valid_until: validUntil, projects: { items, total, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'child-current', generation: 'synthetic', valid_until: validUntil } } })
    }
    if (url.pathname.endsWith('/projects')) {
      const offset = Number(url.searchParams.get('offset') ?? 0)
      if (options.childExpiredOnce && (options.expireAtOffset === undefined || offset === options.expireAtOffset)) {
        options.childExpiredOnce = false
        return route.fulfill({ status: 409, json: {} })
      }
      const accountId = url.pathname.includes('cg_cedar') ? 'cg_cedar' : 'cg_north'
      const total = options.projectTotal ?? 26
      const items = Array.from({ length: Math.max(0, Math.min(25, total - offset)) }, (_, index) => project(`${accountId}-p${offset + index + 1}`))
      return route.fulfill({ json: { items, total, count_unit: 'projects', limit: 25, offset, cohort_token: 'child-current', generation: 'synthetic', valid_until: validUntil } })
    }
    if (url.pathname === '/api/commercial-pursuits') return route.fulfill({ json: { items: [], counts: { total: 0, active: 0, needs_attention: 0 }, total_matching: 0, has_more: false, next_offset: null } })
    if (url.pathname === '/api/opportunities/workspace/changes') return route.fulfill({ json: { items: [], counts: { discovered: 0, changed: 0, promoted: 0, closed: 0, review_exception: 0 }, total_unreviewed: 0, offset: 0, limit: 50, next_offset: null, baseline_identity: 'synthetic', token: 'synthetic', source_health_exceptions: [] } })
    return route.fulfill({ json: [] })
  })
}

test('synthetic account detail recovers once from an expired child cohort and exposes all 26 projects', async ({ page }) => {
  const childOffsets: string[] = [], openCalls: string[] = []
  await install(page, { childExpiredOnce: true })
  page.on('request', request => {
    const url = new URL(request.url())
    if (url.pathname.endsWith('/projects') && url.pathname.includes('/groups/')) childOffsets.push(url.searchParams.get('offset') ?? '')
    if (url.pathname.endsWith('/open') && url.pathname.includes('/groups/')) openCalls.push(url.searchParams.get('shortlist') ?? '')
  })
  await page.goto('/?view=workspace&panel=companies&company=cg_north')
  const detail = page.getByRole('region', { name: 'Company Synthetic North' })
  await expect(detail.getByRole('heading', { name: 'Projects' })).toBeVisible()
  await expect(detail.getByRole('button', { name: 'Load more projects' })).toBeVisible()
  await detail.getByRole('button', { name: 'Load more projects' }).click()
  await expect(detail.locator('.cmp-projects li')).toHaveCount(26)
  expect(childOffsets).toEqual(['25', '25'])
  expect(openCalls.length).toBeGreaterThanOrEqual(2) // dev StrictMode may mount the detail twice
  expect(openCalls.every(value => value === 'false')).toBeTruthy()
  await expect(detail.getByRole('button', { name: 'Load more projects' })).toHaveCount(0)
})

test('synthetic later-page cohort expiry resets to the refreshed first page without skipping projects', async ({ page }) => {
  await install(page, { childExpiredOnce: true, expireAtOffset: 50, projectTotal: 76 })
  await page.goto('/?view=workspace&panel=companies&company=cg_north')
  const detail = page.getByRole('region', { name: 'Company Synthetic North' })
  await expect(detail.locator('.cmp-projects li')).toHaveCount(25)
  await detail.getByRole('button', { name: 'Load more projects' }).click()
  await expect(detail.locator('.cmp-projects li')).toHaveCount(50)
  await detail.getByRole('button', { name: 'Load more projects' }).click()
  await expect(detail.locator('.cmp-projects li')).toHaveCount(25)
  await expect(detail.getByRole('status')).toContainText('continue from the refreshed list')
  await expect(detail.getByRole('button', { name: 'Load more projects' })).toBeVisible()
})

test('synthetic account switch never flashes the previous account contact while the next detail is pending', async ({ page }) => {
  let releaseCedar!: () => void
  const cedarWait = new Promise<void>(resolve => { releaseCedar = resolve })
  await install(page, { delayCedar: () => cedarWait })
  await page.goto('/?view=workspace&panel=companies')
  const companies = page.getByRole('region', { name: 'Companies' })
  await companies.getByRole('button', { name: 'Open Synthetic North' }).click()
  const north = page.getByRole('region', { name: 'Company Synthetic North' })
  await expect(north.getByRole('link', { name: 'Email Synthetic North Buyer' })).toBeVisible()
  await north.getByRole('button', { name: '← Back to companies' }).click()
  await companies.getByRole('button', { name: 'Open Synthetic Cedar' }).click()
  const cedar = page.getByRole('region', { name: 'Company Synthetic Cedar' })
  await expect(cedar.getByRole('status')).toContainText('Loading account details')
  await expect(cedar.getByText('north@example.invalid')).toHaveCount(0)
  releaseCedar()
  await expect(cedar.getByRole('link', { name: 'Email Synthetic Cedar Buyer' })).toBeVisible()
})

test('synthetic account browsing never logs activity and session expiry clears account/contact content', async ({ page }) => {
  let mutations = 0
  await install(page)
  page.on('request', request => { if (request.method() !== 'GET' && request.url().includes('/api/commercial-pursuits')) mutations += 1 })
  await page.goto('/?view=workspace&panel=companies&company=cg_north')
  const detail = page.getByRole('region', { name: 'Company Synthetic North' })
  await expect(detail.getByRole('link', { name: 'Email Synthetic North Buyer' })).toBeVisible()
  await expect(detail.getByRole('button', { name: 'Add to Pursuit' }).first()).toBeVisible()
  expect(mutations).toBe(0)
  await page.evaluate(() => window.dispatchEvent(new Event('gl3-clear-continuity')))
  const panel = page.getByRole('region', { name: 'Companies' })
  await expect(panel.getByRole('alert')).toContainText('Your session ended')
  await expect(panel.getByText('Synthetic North Buyer')).toHaveCount(0)
  await expect(panel.getByText('Synthetic project cg_north-p1')).toHaveCount(0)
  expect(mutations).toBe(0)
})

test('synthetic shortlist account retains its featured reason and only offers eligible need choices', async ({ page }) => {
  const shortlistQueries: string[] = []
  await install(page)
  page.on('request', request => {
    const url = new URL(request.url())
    if (/\/api\/opportunities\/groups\/cg_north\/(open|projects)$/.test(url.pathname)) shortlistQueries.push(url.searchParams.get('shortlist') ?? '')
  })
  await page.goto('/?view=workspace&groupBrowse=1&account=cg_north&shortlist=1')
  const detail = page.getByRole('region', { name: 'Company Synthetic North' })
  await expect(detail.getByRole('region', { name: 'Account overview' })).toContainText('Synthetic construction activity is planned.')
  await expect(detail.locator('.cmp-meta')).toContainText('1 relevant project')
  await expect(detail.getByRole('combobox', { name: 'Choose an opportunity for Synthetic project cg_north-p1' })).toHaveValue('need-cg_north-p1')
  const choices = detail.getByRole('combobox', { name: 'Choose an opportunity for Synthetic project cg_north-p1' }).locator('option')
  await expect(choices).toHaveText(['Compressor expansion', 'Capacity upgrade'])
  await expect(detail.getByRole('button', { name: 'Add to Pursuit' })).toHaveCount(1)
  expect(shortlistQueries.length).toBeGreaterThan(0)
  expect(shortlistQueries.every(value => value === 'true')).toBeTruthy()
})
