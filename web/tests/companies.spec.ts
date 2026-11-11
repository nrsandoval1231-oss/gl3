import { mockDemandSummary } from './mock-demand-summary'
import { expect, test, type Page } from '@playwright/test'
import type { OpportunityGroup } from '../src/api/client'

const groups: OpportunityGroup[] = [
  { id: 'cg_north', name: 'Northstar Energy', role: 'operator', group_kind: 'resolved_identity', project_count: 2, total_known_project_count: 2, relevant_project_count: 1, need_count: 3, priority_score: 71, sectors: ['oil_gas'] },
  { id: 'cg_name', name: 'Acme Power', role: 'customer', group_kind: 'same_name_unconfirmed', identity_count: 3, project_count: 4, total_known_project_count: 4, relevant_project_count: 0, need_count: 4, priority_score: null, sectors: [] },
  { id: 'cg_cedar', name: 'Cedar Compute', role: 'customer', group_kind: 'resolved_identity', project_count: 1, total_known_project_count: 1, relevant_project_count: 1, need_count: 1, priority_score: null, sectors: ['data_centers'] },
]
const project = (id: string, name: string, extra: Record<string, unknown> = {}) => ({ id, project_id: id, name, company: 'Northstar Energy', customer_identity_id: 'company-north', location: 'Midland, TX', sector: 'oil_gas', asset_type: 'Compressor station', priority_score: 71, representative_need_id: `need-${id}`, need_count: 1, needs: [{ id: `need-${id}`, project_id: id, tier: 'Prospect' }], event: null, contact: [], power_summary: null, power_summary_kind: 'unknown', next_action: null, updated_at: null, ...extra })
const pursuit = { id: 'pursuit-1', need_id: 'need-p1', project_id: 'p1', stage: 'Engaged', title: 'Mesa pursuit', location: null, tier: 'Prospect', required_mw: null, start_window: null, contact: null, contact_status: 'unknown', attention: [], attention_labels: [], next_task: null, created_at: '2026-10-01T00:00:00Z', stage_changed_at: '2026-10-01T00:00:00Z' }

async function mock(page: Page, opts: { groupsStatus?: number; pursuits?: unknown[] } = {}) {
  const groupQueries: URL[] = []
  const projectQueries: URL[] = []
  await mockDemandSummary(page)
  await page.route(url => url.pathname.startsWith('/api/') && !url.pathname.includes('demand-summary'), route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (url.pathname === '/api/opportunities/groups') {
      groupQueries.push(url)
      if (opts.groupsStatus) return route.fulfill({ status: opts.groupsStatus, json: {} })
      const q = (url.searchParams.get('search') ?? '').toLowerCase(), sector = url.searchParams.get('sector')
      const items = groups.filter(g => (!q || g.name.toLowerCase().includes(q)) && (!sector || sector === 'all' || g.sectors.includes(sector)))
      return route.fulfill({ json: { items, total: items.length, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'c1', generation: 'g' } })
    }
    if (url.pathname === '/api/opportunities/projects') { projectQueries.push(url); return route.fulfill({ json: { items: [], total: 7, count_unit: 'projects', limit: 1, offset: 0, cohort_token: 'p', generation: 'g', valid_until: '2099-01-01T00:00:00Z' } }) }
    if (url.pathname === '/api/opportunities/groups/cg_north/open') return route.fulfill({ json: { group: { ...groups[0], featured_project: project('p1', 'Mesa compressor', { power_summary: '12 MW reported', power_summary_kind: 'activity_requirement', contact: [{ kind: 'email', label: 'Email contact', href: 'mailto:buyer@northstar.example', name: 'Jordan Lee', title: 'Facilities Director' }], shortlist_assessment: { eligible: true, reasons: [], evidence_refs: [], why_now: 'A compressor project is under construction.', next_step: 'Confirm commissioning timing.' } }), total_known_project_count: 2 }, parent_cohort_token: 'c1', generation: 'g', valid_until: '2099-01-01T00:00:00Z', projects: { items: [project('p1', 'Mesa compressor', { power_summary: '12 MW reported', power_summary_kind: 'activity_requirement', contact: [{ kind: 'email', label: 'Email contact', href: 'mailto:buyer@northstar.example', name: 'Jordan Lee', title: 'Facilities Director' }] }), project('p2', 'Basin plant')], total: 2, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'cp', generation: 'g', valid_until: '2099-01-01T00:00:00Z' } } })
    if (url.pathname === '/api/opportunities/groups/cg_name/open') return route.fulfill({ json: { group: { ...groups[1], sectors: [] }, parent_cohort_token: 'c1', generation: 'g', valid_until: '2099-01-01T00:00:00Z', projects: { items: [], total: 0, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'pc', generation: 'g', valid_until: '2099-01-01T00:00:00Z' } } })
    if (url.pathname === '/api/opportunities/groups/cg_gone/open') return route.fulfill({ status: 404, json: {} })
    if (url.pathname === '/api/commercial-pursuits') {
      const all = (opts.pursuits ?? []) as unknown[]
      const limit = Number(url.searchParams.get('limit') ?? 100), offset = Number(url.searchParams.get('offset') ?? 0)
      const items = all.slice(offset, offset + limit), next = offset + limit < all.length ? offset + limit : null
      return route.fulfill({ json: { items, counts: { total: all.length, active: all.length, needs_attention: 0 }, total_matching: all.length, has_more: next !== null, next_offset: next } })
    }
    if (url.pathname === '/api/customer-accounts/company-north/contacts') return route.fulfill({ json: { company_id: 'company-north', research_required: true, contacts: [], imported_unverified: [] } })
    if (url.pathname.startsWith('/api/opportunities/needs/')) return route.fulfill({ json: { id: url.pathname.split('/').pop(), project_id: 'p1', name: 'Mesa compressor', browse_title: 'Mesa compressor', location: 'Midland, TX', tier: 'Prospect', workflow_status: 'New', activity: 'construction', rationale: 'Fixture', signal_evidence_state: 'active', conflict_state: 'Not assessed', required_mw: null, supply: 'Unknown', start_window: null, duration: null, evidence: [], missing_facts: [] } })
    if (url.pathname === '/api/opportunities/workspace/changes') return route.fulfill({ json: { items: [], counts: { discovered: 0, changed: 0, promoted: 0, closed: 0, review_exception: 0 }, total_unreviewed: 0, offset: 0, limit: 50, next_offset: null, baseline_identity: 't', token: 't', source_health_exceptions: [] } })
    return route.fulfill({ json: [] })
  })
  return { groupQueries, projectQueries }
}

test('directory shows only supplied fields, searches, and omits unsupported columns', async ({ page }) => {
  const queries = await mock(page)
  await page.goto('/?view=workspace&panel=companies')
  const panel = page.getByRole('region', { name: 'Companies' })
  await expect(panel.getByRole('status')).toContainText('3 operator/customer groups · 7 projects')
  await expect(panel.getByRole('status')).not.toContainText('0 projects')
  await expect(queries.projectQueries[0]?.searchParams.get('include_signals')).toBe('true')
  await expect(panel).toContainText('not a count of confirmed companies')
  await expect(panel.getByRole('heading', { name: 'Companies', level: 1 })).toBeVisible()
  const table = panel.getByRole('table', { name: 'Companies' })
  await expect(table.getByRole('columnheader')).toHaveText(['Company', 'Projects', 'Open'])
  await expect(table.getByRole('row').nth(1)).toContainText('Northstar Energy')
  await expect(table.getByRole('row').nth(1)).not.toContainText('71')
  await expect(table.getByRole('row').nth(2)).toContainText('Acme Power')
  await expect(table.getByRole('row').nth(2)).toContainText('Name group')
  await expect(table.getByRole('row').nth(2)).toContainText('Same source-reported name; company identities are not linked.')
  await expect(table.getByRole('row').nth(2)).toContainText('3 separate company identities')
  await expect(table.getByRole('row').nth(2)).not.toContainText('Customer')
  await expect(table.getByRole('row').nth(3)).not.toContainText('Priority score')
  await expect(table).not.toContainText('Total MW')
  await expect(table).not.toContainText(/\b0 MW\b/)
  await expect(panel).toContainText('Total MW and linked pursuits are not part of the company list')
  await expect(page.getByRole('link', { name: 'Back to Opportunities' })).toHaveAttribute('href', /shortlist=1/)
  await panel.getByRole('searchbox', { name: 'Search companies', exact: true }).fill('cedar')
  await expect(table.getByRole('row')).toHaveCount(2)
  await expect(panel.getByRole('status')).toContainText('1 operator/customer group matching search')
  expect(queries.groupQueries.some(url => url.searchParams.get('search') === 'cedar')).toBeTruthy()
  await panel.getByRole('searchbox', { name: 'Search companies', exact: true }).fill('')
  await panel.getByRole('button', { name: 'Data Centers' }).click()
  await expect(table.getByRole('row')).toHaveCount(2)
  await expect(page).toHaveURL(/cs=data_centers/)
})

test('opening a company uses panel/company params, keeps context on back/forward, links pursuits and opportunities', async ({ page }) => {
  await mock(page, { pursuits: [pursuit] })
  await page.goto('/?view=workspace&panel=companies')
  const panel = page.getByRole('region', { name: 'Companies' })
  await panel.getByRole('searchbox', { name: 'Search companies', exact: true }).fill('north')
  await expect(panel.getByRole('table', { name: 'Companies' }).getByRole('row')).toHaveCount(2)
  await panel.getByRole('button', { name: 'Open Northstar Energy' }).click()
  await expect(page).toHaveURL(/panel=companies/)
  await expect(page).toHaveURL(/company=cg_north/)
  const company = page.getByRole('region', { name: 'Company Northstar Energy' })
  await expect(company.getByRole('heading', { name: 'Northstar Energy', exact: true })).toBeVisible()
  await expect(company).toContainText('12 MW reported')
  await expect(company).not.toContainText('Power: Unknown')
  await expect(company.getByRole('region', { name: 'Linked pursuits' })).toContainText('Mesa pursuit')
  await expect(company.getByRole('region', { name: 'Linked pursuits' })).toContainText('Mesa pursuit · Engaged')
  await expect(company.getByRole('region', { name: 'Account overview' }).getByRole('link', { name: 'Email Jordan Lee' })).toHaveAttribute('href', 'mailto:buyer@northstar.example')
  await expect(company.getByRole('button', { name: /Open project detail Mesa compressor/ })).toBeVisible()
  await expect(page.getByRole('searchbox', { name: 'Search companies', exact: true })).toBeHidden()
  await page.goBack()
  await expect(page).not.toHaveURL(/company=/)
  await expect(page.getByRole('searchbox', { name: 'Search companies', exact: true })).toHaveValue('north')
  await page.goForward()
  await expect(page.getByRole('heading', { name: 'Northstar Energy', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '← Back to companies' }).click()
  await expect(page).not.toHaveURL(/company=/)
  await expect(page).toHaveURL(/panel=companies/)
  await page.getByRole('button', { name: 'Open Northstar Energy' }).click()
  await page.getByRole('button', { name: /Open project detail Mesa compressor/ }).click()
  await expect(page).toHaveURL(/need=need-p1/)
  await expect(page).toHaveURL(/account=cg_north/)
  await expect(page).toHaveURL(/project=p1/)
  await expect(page.getByRole('region', { name: 'Companies' })).toHaveCount(0)
  await page.goBack()
  await expect(page.getByRole('region', { name: 'Company Northstar Energy' })).toBeVisible()
})

test('company deep link reloads, unavailable company and list errors are honest', async ({ page }) => {
  await mock(page, { pursuits: [] })
  await page.goto('/?view=workspace&panel=companies&company=cg_north')
  await expect(page.getByRole('region', { name: 'Linked pursuits' })).toContainText('No pursuits are linked')
  await page.goto('/?view=workspace&panel=companies&company=cg_gone')
  await expect(page.getByRole('alert')).toContainText('no longer available')
})

test('directory error offers retry and never shows counts', async ({ page }) => {
  await mock(page, { groupsStatus: 500 })
  await page.goto('/?view=workspace&panel=companies')
  const panel = page.getByRole('region', { name: 'Companies' })
  await expect(panel.getByRole('alert')).toContainText('Could not load operator/customer groups (500)')
  await expect(panel.getByRole('button', { name: 'Retry' })).toBeVisible()
  await expect(panel.getByRole('status')).toContainText('Group count unavailable')
})

test('directory and company view fit 390px without horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mock(page, { pursuits: [pursuit] })
  await page.goto('/?view=workspace&panel=companies')
  const brand = page.locator('.canonical-header__brand')
  await expect(brand).toHaveAttribute('aria-label', 'GridLens — Commercial Intelligence for Constrained Power')
  expect(await page.locator('.canonical-header__brand-art').evaluate(element => { const image = element as HTMLImageElement; return Math.abs(image.width / image.height - image.naturalWidth / image.naturalHeight) })).toBeLessThan(0.05)
  await page.screenshot({ path: test.info().outputPath('mobile-header.png'), fullPage: true })
  await expect(page.getByRole('button', { name: 'Open Northstar Energy' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  await page.getByRole('button', { name: 'Open Northstar Energy' }).click()
  await expect(page.getByRole('heading', { name: 'Northstar Energy', exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  await page.setViewportSize({ width: 1440, height: 900 })
  expect(await page.locator('.canonical-header__brand-art').evaluate(element => { const image = element as HTMLImageElement; return Math.abs(image.width / image.height - image.naturalWidth / image.naturalHeight) })).toBeLessThan(0.05)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  await page.screenshot({ path: test.info().outputPath('desktop-header.png'), fullPage: true })
})

test('header Companies item while a company is open returns to the directory and Back restores the company', async ({ page }) => {
  await mock(page)
  await page.goto('/?view=workspace&panel=companies')
  await page.getByRole('button', { name: 'Open Northstar Energy' }).click()
  await expect(page.getByRole('region', { name: 'Company Northstar Energy' })).toBeVisible()
  await page.getByRole('banner').getByRole('button', { name: 'Companies' }).click()
  await expect(page.getByRole('region', { name: 'Company Northstar Energy' })).toHaveCount(0)
  await expect(page.getByRole('searchbox', { name: 'Search companies', exact: true })).toBeVisible()
  await expect(page).not.toHaveURL(/company=/)
  await page.goBack()
  await expect(page).toHaveURL(/company=cg_north/)
  await expect(page.getByRole('region', { name: 'Company Northstar Energy' })).toBeVisible()
})

test('session end clears company names, projects, contacts and linked pursuits', async ({ page }) => {
  await mock(page, { pursuits: [pursuit] })
  await page.goto('/?view=workspace&panel=companies&company=cg_north')
  const company = page.getByRole('region', { name: 'Company Northstar Energy' })
  await expect(company.getByRole('region', { name: 'Account overview' }).getByRole('link', { name: 'Email Jordan Lee' })).toBeVisible()
  await expect(company.getByRole('region', { name: 'Linked pursuits' })).toContainText('Mesa pursuit')
  await page.evaluate(() => window.dispatchEvent(new Event('gl3-clear-continuity')))
  const panel = page.getByRole('region', { name: 'Companies' })
  await expect(panel.getByRole('alert')).toContainText('Your session ended. Sign in again.')
  for (const text of ['Northstar Energy', 'Cedar Compute', 'Mesa pursuit', 'Mesa compressor', 'Jordan Lee', 'Checking your pursuits', '7 projects']) await expect(page.getByText(text)).toHaveCount(0)
  await expect(page.getByRole('table', { name: 'Companies' })).toHaveCount(0)
})

test('session end on the directory clears group names and counts', async ({ page }) => {
  await mock(page)
  await page.goto('/?view=workspace&panel=companies')
  await expect(page.getByRole('button', { name: 'Open Northstar Energy' })).toBeVisible()
  await page.evaluate(() => window.dispatchEvent(new Event('gl3-clear-continuity')))
  await expect(page.getByRole('region', { name: 'Companies' }).getByRole('alert')).toContainText('Your session ended')
  await expect(page.getByText('Northstar Energy')).toHaveCount(0)
  await expect(page.getByText(/operator\/customer groups/)).toHaveCount(0)
})

test('same-name groups remain visibly unresolved rather than being described as one confirmed account', async ({ page }) => {
  await mock(page, { pursuits: [] })
  const solo = { ...groups[1], identity_count: 1 }
  await page.route('**/api/opportunities/groups?**', route => route.fulfill({ json: { items: [solo], total: 1, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'c1', generation: 'g' } }))
  await page.goto('/?view=workspace&panel=companies&company=cg_name')
  const group = page.getByRole('region', { name: 'Group Acme Power' })
  await expect(group).toContainText('Same source-reported name; company identities are not linked.')
  await expect(group).toContainText('4 known projects')
  await expect(group.getByRole('button', { name: '← Back to the directory' })).toBeVisible()
})

test('linked pursuits include a pursuit that is only on the second page of the store load', async ({ page }) => {
  const fillers = Array.from({ length: 249 }, (_, index) => ({ ...pursuit, id: `filler-${index}`, need_id: `need-filler-${index}`, project_id: `project-filler-${index}`, title: `Filler ${index}` }))
  const all = [...fillers.slice(0, 230), pursuit, ...fillers.slice(230)]
  expect(all).toHaveLength(250)
  const pages: string[] = []
  page.on('request', request => { const url = new URL(request.url()); if (url.pathname === '/api/commercial-pursuits') pages.push(`${url.searchParams.get('limit')}:${url.searchParams.get('offset')}`) })
  await mock(page, { pursuits: all })
  await page.goto('/?view=workspace&panel=companies')
  const panel = page.getByRole('region', { name: 'Companies' })
  await panel.getByRole('button', { name: 'Open Northstar Energy' }).click()
  const linked = page.getByRole('region', { name: 'Company Northstar Energy' }).getByRole('region', { name: 'Linked pursuits' })
  await expect(linked).toContainText('Mesa pursuit · Engaged')
  await expect(linked).not.toContainText('may be incomplete')
  expect(pages.slice(0, 2)).toEqual(['200:null', '200:200'])
})

test('a capped pursuit load says the linked count may be incomplete', async ({ page }) => {
  const all = Array.from({ length: 2300 }, (_, index) => ({ ...pursuit, id: `filler-${index}`, need_id: `need-filler-${index}`, project_id: `project-filler-${index}`, title: `Filler ${index}` }))
  await mock(page, { pursuits: all })
  await page.goto('/?view=workspace&panel=companies')
  await page.getByRole('region', { name: 'Companies' }).getByRole('button', { name: 'Open Northstar Energy' }).click()
  const linked = page.getByRole('region', { name: 'Company Northstar Energy' }).getByRole('region', { name: 'Linked pursuits' })
  await expect(linked).toContainText('Only the first 2000 pursuits could be checked; links may be incomplete.')
})

test('a background pursuit 401 clears company names, projects, contacts and linked pursuits', async ({ page }) => {
  await mock(page, { pursuits: [pursuit] })
  await page.goto('/?view=workspace&panel=companies&company=cg_north')
  const company = page.getByRole('region', { name: 'Company Northstar Energy' })
  await expect(company.getByRole('region', { name: 'Linked pursuits' })).toContainText('Mesa pursuit')
  // The client announces this event on a background pursuit 401 (never gl3-clear-continuity).
  await page.evaluate(() => window.dispatchEvent(new Event('gl3-pursuits-session-ended')))
  await expect(page.getByRole('region', { name: 'Companies' }).getByRole('alert')).toContainText('Your session ended. Sign in again.')
  // Scoped to the Companies panel: a pursuit-only end must not wipe unrelated Opportunities views elsewhere in the shell.
  const panel = page.getByRole('region', { name: 'Companies' })
  for (const text of ['Northstar Energy', 'Mesa pursuit', 'Mesa compressor', 'Research Required']) await expect(panel.getByText(text)).toHaveCount(0)
})
