import { mockDemandSummary } from './mock-demand-summary'
import { expect, test, type Page } from '@playwright/test'
import type { OpportunityGroup, ProjectResult } from '../src/api/client'

const accountId = 'cg_north'
const companyId = 'company-1'
const companyName = 'Northstar Compute'
const project = (index: number): ProjectResult => {
  const id = `project-${index}`
  const needId = `need-${index}`
  return {
    id, project_id: id, name: index === 1 ? 'Cedar Ridge campus' : index === 2 ? 'South plant' : `Synthetic project ${index}`,
    company: companyName, customer_identity_id: companyId, location: 'Austin, TX', sector: 'data_centers', asset_type: 'data_center', priority_score: null,
    representative_need_id: needId, need_count: 1,
    needs: [{ id: needId, project_id: id, name: index === 1 ? 'Cedar Ridge campus' : `Synthetic need ${index}`, activity: index === 1 ? 'construction' : 'commissioning', tier: 'Prospect' }],
    eligible_need_ids: index === 1 ? [needId] : [],
    event: { kind: 'construction', label: 'Synthetic construction planned', date: '2026-10-20', source: 'https://example.invalid/synthetic-source' },
    contact: index === 1 ? [
      { kind: 'email', label: 'Email Jordan Lee', href: 'mailto:jordan@example.invalid', name: 'Jordan Lee', title: 'Facilities Director', company: companyName, responsibility: 'Facilities project contact' },
      { kind: 'phone', label: 'Call Jordan Lee', href: 'tel:+15125550123', name: 'Jordan Lee', title: 'Facilities Director', company: companyName },
      { kind: 'email', label: 'Unsafe contact', href: 'javascript:alert(1)', name: 'Suppressed Contact', company: companyName },
    ] : [],
    power_summary: index === 1 ? '12 MW reported' : null, power_summary_kind: index === 1 ? 'activity_requirement' : 'unknown', next_action: null,
    shortlist_assessment: index === 1 ? { eligible: true, reasons: [], evidence_refs: [], why_now: 'Synthetic construction activity is planned.', next_step: 'Confirm commissioning timing.' } : null,
    updated_at: null,
  }
}

const accountGroup = (id = accountId, name = companyName, groupKind: OpportunityGroup['group_kind'] = 'resolved_identity', projectTotal = 2): OpportunityGroup => ({
  id, name, role: groupKind === 'unresolved' ? 'unresolved' : 'customer', group_kind: groupKind,
  project_count: projectTotal, total_known_project_count: projectTotal, relevant_project_count: id === accountId ? 1 : 0, need_count: projectTotal,
  sectors: ['data_centers'], featured_project: id === accountId ? project(1) : null,
})

type BrowseOptions = {
  groups?: OpportunityGroup[]
  groupOffset409Once?: boolean
  child409AtOffset?: number
  projectTotal?: number
  failOpenOnce?: string
  projectOwner?: string | null
}

async function installAccountFirst(page: Page, options: BrowseOptions = {}) {
  await mockDemandSummary(page)
  const groups = options.groups ?? [accountGroup(), accountGroup('cg_unresolved', 'Unresolved customer project', 'unresolved', 1)]
  const parentQueries: URL[] = [], childQueries: URL[] = [], opens: URL[] = [], resolutions: string[] = []
  let openFailure = options.failOpenOnce ?? ''
  let childFailureUsed = false
  let parentFailureUsed = false
  await page.route(url => new URL(url).pathname.startsWith('/api/') && !new URL(url).pathname.includes('demand-summary'), async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (url.pathname === '/api/companies/company-1/account') {
      resolutions.push(companyId)
      return route.fulfill({ json: { id: accountId, name: companyName, group_kind: 'resolved_identity' } })
    }
    if (url.pathname === `/api/projects/project-1/account`) {
      if (options.projectOwner === null) return route.fulfill({ status: 404, json: {} })
      return route.fulfill({ json: { id: options.projectOwner ?? accountId, name: options.projectOwner === 'cg_other' ? 'Different Operator' : companyName, group_kind: 'resolved_identity', project_id: 'project-1' } })
    }
    if (url.pathname === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (url.pathname === '/api/opportunities/groups') {
      parentQueries.push(url)
      const offset = Number(url.searchParams.get('offset') ?? 0)
      if (options.groupOffset409Once && offset === 25 && !parentFailureUsed) { parentFailureUsed = true; return route.fulfill({ status: 409, json: { detail: 'synthetic cohort expired' } }) }
      const search = (url.searchParams.get('search') ?? '').toLowerCase()
      const matched = groups.filter(group => !search || group.name.toLowerCase().includes(search) || (group.featured_project?.name.toLowerCase().includes(search) ?? false))
      return route.fulfill({ json: { items: matched.slice(offset, offset + 25), total: matched.length, count_unit: 'groups', limit: 25, offset, cohort_token: 'synthetic-parent-cohort', generation: 'synthetic', facets: { regions: ['Austin, TX'], stages: ['Construction'] } } })
    }
    if (url.pathname === '/api/opportunities/projects') {
      const offset = Number(url.searchParams.get('offset') ?? 0)
      const total = options.projectTotal ?? 2
      const limit = Number(url.searchParams.get('limit') ?? 25)
      const items = Array.from({ length: Math.max(0, Math.min(limit, total - offset)) }, (_, index) => {
        const result = project(offset + index + 1)
        return { ...result, id: result.project_id, project_ids: [result.project_id] }
      })
      return route.fulfill({ json: { items, total, count_unit: 'projects', limit, offset, cohort_token: 'synthetic-project-count', generation: 'synthetic', valid_until: '2099-01-01T00:00:00Z' } })
    }
    if (/^\/api\/opportunities\/groups\/[^/]+\/open$/.test(url.pathname)) {
      opens.push(url)
      const id = url.pathname.split('/')[4]
      if (openFailure === id) return route.fulfill({ status: 503, json: { detail: 'synthetic account read failure' } })
      const group = groups.find(item => item.id === id) ?? accountGroup(id, 'Unavailable account', 'unresolved')
      const total = options.projectTotal ?? group.project_count
      const items = Array.from({ length: Math.min(25, total) }, (_, index) => project(index + 1))
      return route.fulfill({ json: { group: { ...group, featured_project: group.featured_project ?? (id === accountId ? project(1) : null) }, parent_cohort_token: 'synthetic-parent-cohort', generation: 'synthetic', valid_until: '2099-01-01T00:00:00Z', projects: { items, total, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'synthetic-child-cohort', generation: 'synthetic', valid_until: '2099-01-01T00:00:00Z' } } })
    }
    if (/^\/api\/opportunities\/groups\/[^/]+\/projects$/.test(url.pathname)) {
      childQueries.push(url)
      const offset = Number(url.searchParams.get('offset') ?? 0)
      if (options.child409AtOffset === offset && !childFailureUsed) { childFailureUsed = true; return route.fulfill({ status: 409, json: { detail: 'synthetic child cohort expired' } }) }
      const total = options.projectTotal ?? 2
      const items = Array.from({ length: Math.max(0, Math.min(25, total - offset)) }, (_, index) => project(offset + index + 1))
      return route.fulfill({ json: { items, total, count_unit: 'projects', limit: 25, offset, cohort_token: 'synthetic-child-cohort', parent_cohort_token: 'synthetic-parent-cohort', generation: 'synthetic', valid_until: '2099-01-01T00:00:00Z' } })
    }
    if (url.pathname.startsWith('/api/opportunities/needs/')) {
      const id = url.pathname.split('/').pop() ?? 'need-1'
      const projectId = id === 'need-unresolved' ? 'project-unresolved' : id.replace('need-', 'project-')
      return route.fulfill({ json: { id, project_id: projectId, name: projectId === 'project-1' ? 'Cedar Ridge campus' : projectId, browse_title: projectId === 'project-1' ? 'Cedar Ridge campus' : projectId, location: 'Austin, TX', tier: 'Lead', workflow_status: 'New', activity: 'construction', rationale: 'Synthetic retained project evidence supports review.', signal_evidence_state: 'active', conflict_state: 'Not assessed', required_mw: null, supply: 'Unknown', start_window: null, duration: null, evidence: [], missing_facts: [], project_identity_key: `synthetic-${projectId}`, commercial_disposition: 'RESEARCH', commercial_reason: 'Synthetic evidence supports review.', commercial_next_question: 'Who owns the scope?', commercial_next_action: 'Review retained evidence.', commercial_organization: null } })
    }    if (url.pathname === '/api/commercial-pursuits') return route.fulfill({ json: { items: [], counts: { total: 0, active: 0, needs_attention: 0 }, total_matching: 0, has_more: false, next_offset: null } })
    if (url.pathname === '/api/opportunities/workspace/changes') return route.fulfill({ json: { items: [], counts: { discovered: 0, changed: 0, promoted: 0, closed: 0, review_exception: 0 }, total_unreviewed: 0, offset: 0, limit: 50, next_offset: null, baseline_identity: 'synthetic', token: 'synthetic', source_health_exceptions: [] } })
    return route.fulfill({ json: [] })
  })
  return { parentQueries, childQueries, opens, resolutions, recoverOpen: () => { openFailure = '' } }
}

test('account-first browse opens distinct projects, selected need and unresolved account detail', async ({ page }) => {
  const browse = await installAccountFirst(page)
  await page.goto('/?view=workspace&groupBrowse=1&shortlist=0')
  await expect(page.locator('.customer-group')).toHaveCount(2)
  await expect(page.getByRole('region', { name: /Northstar Compute customer group/ })).toContainText('Cedar Ridge campus')
  await page.getByRole('region', { name: /Northstar Compute customer group/ }).getByRole('button', { name: /Northstar Compute/ }).click()
  await expect(page).toHaveURL(/account=cg_north/)
  const detail = page.getByRole('region', { name: 'Company Northstar Compute' })
  await expect(detail.getByRole('heading', { name: 'Projects' })).toBeVisible()
  await expect(detail).toContainText('Cedar Ridge campus')
  await expect(detail).toContainText('South plant')
  await expect(detail).not.toContainText('evidence-')
  await detail.getByRole('button', { name: /Open project detail Cedar Ridge campus/ }).click()
  await expect(page).toHaveURL(/need=need-1/)
  await expect(page).toHaveURL(/project=project-1/)
  await expect(page).toHaveURL(/account=cg_north/)
  await expect(page.getByRole('complementary', { name: 'Opportunity detail' })).toBeVisible()
  await page.goBack()
  await expect(page.getByRole('region', { name: 'Company Northstar Compute' })).toBeVisible()
  await page.goBack()
  await expect(page.locator('.customer-group')).toHaveCount(2)
  await page.getByRole('region', { name: /Unresolved customer project customer group/ }).getByRole('button', { name: /Unresolved customer project/ }).click()
  await expect(page.getByRole('region', { name: 'Group Unresolved customer project' })).toBeVisible()
  expect(browse.parentQueries.some(url => url.searchParams.get('group_by') === null)).toBeTruthy()
})

test('account cards prefer an optional brief, keep abstained claims withheld, and expose only its permitted contact route', async ({ page }) => {
  const brief = {
    version: 'synthetic-v1',
    why_now: { text: null, source_date: null, scope: null, sources: [] },
    power_need: { amount_class: 'unknown' as const, scope: 'Temporary package', value: null, unit: null, status: 'unknown', limitations: ['Activity-specific power need is unknown; unknown is not zero.', 'The 40 MW figure is campus nameplate and does not establish rental load.'] },
    best_contact: { contact: 'Jordan Fixture', href: 'tel:+15125550123', kind: 'call' as const, route_kind: 'person_method' as const, authority: 'Unknown; confirm for this need.', deliverability: 'Unknown; route has not been verified for delivery.', sources: [] },
    next_action: { text: 'Confirm the temporary package scope from source evidence.', kind: 'confirm_need', source: null },
    freshness: { as_of: '2026-11-08T00:00:00Z', status: 'current_source', source_date: null },
    limitations: ['No current source citation is available for a why-now statement.'],
    sources: [{ title: 'Synthetic accepted source', url: 'https://example.invalid/synthetic-source', evidence_id: 'synthetic-source-1', date: '2026-11-04' }],
  }
  const featured = { ...project(1), commercial_brief: brief }
  const group = { ...accountGroup(), featured_project: featured }
  const writes: string[] = []
  await installAccountFirst(page, { groups: [group] })
  page.on('request', request => {
    const url = new URL(request.url())
    if (url.pathname.startsWith('/api/') && request.method() !== 'GET') writes.push(`${request.method()} ${url.pathname}`)
  })
  await page.goto('/?view=workspace&groupBrowse=1&shortlist=1')
  const card = page.getByRole('region', { name: /Northstar Compute customer group/ })
  await expect(card.getByText('Why now is not established from current evidence.')).toBeVisible()
  await expect(card.getByText('Synthetic construction activity is planned.')).toHaveCount(0)
  await expect(card.getByText('Temporary package', { exact: true })).toBeVisible()
  await expect(card.getByText('Amount unknown; not zero.', { exact: true })).toHaveCount(0)
  await expect(card.getByText(/unknown is not zero/)).toHaveCount(0)
  await expect(card.getByText(/40 MW figure is campus nameplate and does not establish rental load/)).toBeVisible()
  await expect(card.getByRole('link', { name: /Call Jordan Fixture/ })).toHaveAttribute('href', 'tel:+15125550123')
  await expect(card.locator('details.customer-brief-contact-confidence')).toHaveCount(0)
  await expect(card.getByText(brief.next_action.text, { exact: true })).toBeVisible()
  await expect(card.getByText('Current Source', { exact: true })).toHaveCount(0)
  const sources = card.locator('details.customer-brief-sources')
  await expect(sources).not.toHaveAttribute('open', '')
  await expect(sources.locator('summary')).toHaveText('Sources')
  await expect(sources.getByText('Contact authority: Unknown; confirm for this need.')).toBeHidden()
  await expect(sources.getByText('Contact deliverability: Unknown; route has not been verified for delivery.')).toBeHidden()
  await expect(sources.getByRole('link', { name: 'Synthetic accepted source' })).toHaveCount(0)
  await sources.locator('summary').click()
  await expect(sources).toContainText('Contact authority: Unknown; confirm for this need.')
  await expect(sources).toContainText('Contact deliverability: Unknown; route has not been verified for delivery.')
  await expect(sources.getByRole('link', { name: 'Synthetic accepted source' })).toHaveAttribute('href', 'https://example.invalid/synthetic-source')
  expect(writes).toEqual([])
})

test('a brief with no best contact does not repeat an unavailable-contact block or restore legacy routes', async ({ page }) => {
  const brief = {
    version: 'synthetic-v1',
    why_now: { text: 'A synthetic accepted source documents a construction milestone.', source_date: null, scope: null, sources: [] },
    power_need: { amount_class: 'unknown' as const, scope: null, value: null, unit: null, status: 'unknown', limitations: [] },
    best_contact: null,
    next_action: { text: 'Review the accepted source before deciding whether to follow up.', kind: 'review_source', source: null },
    freshness: { as_of: null, status: 'unknown', source_date: null },
    limitations: [],
    sources: [],
  }
  const group = { ...accountGroup(), featured_project: { ...project(1), commercial_brief: brief } }
  await installAccountFirst(page, { groups: [group] })
  await page.goto('/?view=workspace&groupBrowse=1&shortlist=1')
  const card = page.getByRole('region', { name: /Northstar Compute customer group/ })
  await expect(card.locator('[aria-label="Best contact"]')).toHaveCount(0)
  await expect(card.locator('.customer-brief-claim').filter({ hasText: 'Power need' })).toHaveCount(0)
  await expect(card.getByText('Suppressed Contact')).toHaveCount(0)
  await expect(card.getByText(brief.next_action.text, { exact: true })).toBeVisible()
})

test('account cards use only the exact representative need contact when the project brief omits it', async ({ page }) => {
  const brief = {
    version: 'synthetic-v1',
    why_now: { text: 'A synthetic retained source documents the representative project milestone.', source_date: null, scope: null, sources: [] },
    power_need: { amount_class: 'unknown' as const, scope: null, value: null, unit: null, status: 'unknown', limitations: [] },
    best_contact: null,
    next_action: { text: 'Review the retained project source before deciding on follow-up.', kind: 'review_source', source: null },
    freshness: { as_of: null, status: 'unknown', source_date: null },
    limitations: [],
    sources: [],
  }
  const makeContact = (contact: string, href: string) => ({
    contact, href, kind: 'call' as const, route_kind: 'person_method' as const,
    authority: 'Unknown; confirm for this need.', deliverability: 'Unverified public route.', sources: [],
  })
  const representativeNeed = { ...project(1).needs[0], commercial_brief: { ...brief, best_contact: makeContact('Jordan Representative', 'tel:+15125550124') } }
  const otherNeed = { ...project(2).needs[0], commercial_brief: { ...brief, best_contact: makeContact('Wrong Other Need', 'tel:+15125550125') } }
  const featured = {
    ...project(1), commercial_brief: brief, representative_need_id: representativeNeed.id,
    needs: [representativeNeed, otherNeed],
  }
  const noExactRepresentative = {
    ...project(2), commercial_brief: brief, representative_need_id: 'need-does-not-exist',
    needs: [otherNeed],
  }
  const groups = [
    { ...accountGroup(), featured_project: featured },
    { ...accountGroup('cg_other_operator', 'Other Operator'), featured_project: noExactRepresentative },
  ]
  await installAccountFirst(page, { groups })
  await page.goto('/?view=workspace&groupBrowse=1&shortlist=1')
  const primaryCard = page.getByRole('region', { name: /Northstar Compute customer group/ })
  await expect(primaryCard.getByRole('link', { name: /Call Jordan Representative/ })).toHaveAttribute('href', 'tel:+15125550124')
  await expect(primaryCard.getByRole('link', { name: /Wrong Other Need/ })).toHaveCount(0)
  const noMatchCard = page.getByRole('region', { name: /Other Operator customer group/ })
  await expect(noMatchCard.locator('[aria-label="Best contact"]')).toHaveCount(0)
})

test('legacy company UUID links resolve to the canonical account and reload in the shared detail', async ({ page }) => {
  const browse = await installAccountFirst(page)
  await page.goto('/?view=workspace&accountBrowse=1&account=company-1')
  await expect(page).toHaveURL(/groupBrowse=1/)
  await expect(page).toHaveURL(/account=cg_north/)
  await expect(page.getByRole('heading', { name: companyName })).toBeVisible()
  expect(browse.resolutions).toContain(companyId)
  await page.reload()
  await expect(page.getByRole('heading', { name: companyName })).toBeVisible()
  await expect(page).toHaveURL(/account=cg_north/)
  await expect(page.getByRole('region', { name: 'Account overview' })).toContainText('Synthetic construction activity is planned.')
})

test('group account pages use server filters and restore page, cohort and search history', async ({ page }) => {
  const groups = Array.from({ length: 26 }, (_, index) => accountGroup(`cg_company_${String(index + 1).padStart(2, '0')}`, `Synthetic Company ${String(index + 1).padStart(2, '0')}`, 'resolved_identity', 1))
  const browse = await installAccountFirst(page, { groups })
  await page.goto('/?view=workspace&groupBrowse=1&shortlist=0')
  await expect(page.locator('.customer-group')).toHaveCount(25)
  await page.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(page).toHaveURL(/offset=25/)
  await expect(page.locator('.customer-group')).toHaveCount(1)
  expect(browse.parentQueries.at(-1)?.searchParams.get('offset')).toBe('25')
  expect(browse.parentQueries.at(-1)?.searchParams.get('cohort_token')).toBe('synthetic-parent-cohort')
  await page.reload()
  await expect(page.locator('.customer-group')).toHaveCount(1)
  await expect(page).toHaveURL(/offset=25/)
  await page.getByRole('textbox', { name: 'Search accounts and projects' }).fill('Company 02')
  await expect(page.locator('.customer-group')).toHaveCount(1)
  await expect.poll(() => browse.parentQueries.at(-1)?.searchParams.get('search')).toBe('Company 02')
  expect(browse.parentQueries.at(-1)?.searchParams.get('offset')).toBe('0')
  expect(browse.parentQueries.at(-1)?.searchParams.get('cohort_token')).toBeNull()
})

test('expired account-group page cohort resets to the first page and explains the refresh', async ({ page }) => {
  const groups = Array.from({ length: 26 }, (_, index) => accountGroup(`cg_company_${String(index + 1).padStart(2, '0')}`, `Synthetic Company ${String(index + 1).padStart(2, '0')}`, 'resolved_identity', 1))
  const browse = await installAccountFirst(page, { groups, groupOffset409Once: true })
  await page.goto('/?view=workspace&groupBrowse=1&shortlist=0')
  await expect(page.locator('.customer-group')).toHaveCount(25)
  await page.getByRole('button', { name: 'Next', exact: true }).click()
  await expect.poll(() => page.locator('.customer-group').count()).toBe(25)
  await expect(page.locator('.project-results-notice')).toContainText('Results changed. Reloaded from the first page.')
  await expect(page).not.toHaveURL(/offset=25/)
  expect(browse.parentQueries.filter(url => url.searchParams.get('offset') === '25')).toHaveLength(1)
  expect(browse.parentQueries.at(-1)?.searchParams.get('offset')).toBe('0')
})

test('a saved account URL resolves its canonical identity before showing account content', async ({ page }) => {
  const browse = await installAccountFirst(page)
  await page.goto('/?view=workspace&accountBrowse=1&account=company-1&q=Northstar')
  await expect(page.getByRole('heading', { name: companyName })).toBeVisible()
  await expect.poll(() => browse.opens.at(-1)?.searchParams.get('search')).toBe('Northstar')
  await expect(page).toHaveURL(/account=cg_north/)
  await expect(page).toHaveURL(/q=Northstar/)
  await page.locator('.wh-account summary').click()
  await expect(page.locator('.wh-account').getByRole('button', { name: 'Research progress' })).toBeVisible()
})

test('account project detail shows a retry after read failure without changing the canonical route', async ({ page }) => {
  const browse = await installAccountFirst(page, { failOpenOnce: accountId })
  await page.goto('/?view=workspace&groupBrowse=1&account=cg_north')
  await expect(page.getByRole('alert')).toContainText('Could not open current operator/customer results (503).')
  await expect(page).toHaveURL(/account=cg_north/)
  browse.recoverOpen()
  await page.getByRole('alert').getByRole('button', { name: 'Retry' }).click()
  await expect(page.getByRole('heading', { name: companyName })).toBeVisible()
  expect(browse.opens.filter(url => url.pathname.endsWith('/open')).length).toBeGreaterThanOrEqual(3)
})

test('unresolved account project reads remain available through the shared account detail', async ({ page }) => {
  const browse = await installAccountFirst(page, { groups: [accountGroup('cg_unresolved', 'Unresolved customer project', 'unresolved', 1)], failOpenOnce: 'cg_unresolved' })
  await page.goto('/?view=workspace&groupBrowse=1&shortlist=0')
  await page.locator('.customer-group').getByRole('button', { name: /Unresolved customer project/ }).click()
  await expect(page.getByRole('alert')).toContainText('Could not open current operator/customer results (503).')
  browse.recoverOpen()
  await page.getByRole('alert').getByRole('button', { name: 'Retry' }).click()
  await expect(page.getByRole('heading', { name: 'Unresolved customer project' })).toBeVisible()
  expect(browse.opens.some(url => url.pathname.endsWith('/cg_unresolved/open'))).toBeTruthy()
})

test('account project navigation restores matched project context through reload, Back and Forward', async ({ page }) => {
  const browse = await installAccountFirst(page, { projectTotal: 26 })
  await page.goto('/?view=workspace&groupBrowse=1&account=cg_north&project=project-26')
  const detail = page.getByRole('region', { name: 'Company Northstar Compute' })
  await expect(detail.getByRole('button', { name: 'Load more projects' })).toBeVisible()
  await detail.getByRole('button', { name: 'Load more projects' }).click()
  await expect(detail.locator('[data-project-id="project-26"]')).toBeVisible()
  await expect(detail.locator('[data-project-id="project-26"]')).toHaveAttribute('aria-current', 'location')
  await page.reload()
  const refreshed = page.getByRole('region', { name: 'Company Northstar Compute' })
  await expect(refreshed.locator('[data-project-id="project-26"]')).toBeVisible()
  await expect(refreshed.locator('[data-project-id="project-26"]')).toHaveAttribute('aria-current', 'location')
  await expect(refreshed.getByRole('button', { name: 'Load more projects' })).toHaveCount(0)
  expect(browse.opens.some(url => url.searchParams.get('shortlist') === 'true')).toBeTruthy()
})

test('expired nested account project pages recover with current cohort tokens', async ({ page }) => {
  const browse = await installAccountFirst(page, { projectTotal: 26, child409AtOffset: 25 })
  await page.goto('/?view=workspace&groupBrowse=1&shortlist=0&account=cg_north')
  const detail = page.getByRole('region', { name: 'Company Northstar Compute' })
  await expect(detail.getByRole('button', { name: 'Load more projects' })).toBeVisible()
  await detail.getByRole('button', { name: 'Load more projects' }).click()
  await expect(detail.locator('.cmp-projects li')).toHaveCount(26)
  expect(browse.childQueries.map(url => url.searchParams.get('offset'))).toEqual(['25', '25'])
})

test('search changes discard a delayed previous group response', async ({ page }) => {
  const groups = [accountGroup('cg_alpha', 'Alpha Synthetic Account',  'resolved_identity', 1), accountGroup('cg_beta', 'Beta Synthetic Account', 'resolved_identity', 1)]
  let releaseAlpha!: () => void
  let held = false
  const queries: URL[] = []
  await installAccountFirst(page, { groups })
  await page.route(url => new URL(url).pathname === '/api/opportunities/groups', async route => {
    const url = new URL(route.request().url()); queries.push(url)
    if (url.searchParams.get('search') === 'Alpha' && !held) {
      held = true
      await new Promise<void>(resolve => { releaseAlpha = resolve })
      try { await route.fulfill({ json: { items: [groups[0]], total: 1, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'old-alpha', generation: 'synthetic' } }) } catch { return }
      return
    }
    const value = url.searchParams.get('search') === 'Beta' ? groups[1] : groups[0]
    return route.fulfill({ json: { items: [value], total: 1, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'current-search', generation: 'synthetic' } })
  })
  await page.goto('/?view=workspace&groupBrowse=1&shortlist=0')
  await page.getByRole('textbox', { name: 'Search accounts and projects' }).fill('Alpha')
  await expect.poll(() => queries.some(url => url.searchParams.get('search') === 'Alpha')).toBe(true)
  await page.getByRole('textbox', { name: 'Search accounts and projects' }).fill('Beta')
  await expect(page.locator('.customer-group')).toContainText('Beta Synthetic Account')
  releaseAlpha?.()
  await expect(page.locator('.customer-group')).toContainText('Beta Synthetic Account')
  await expect(page.locator('.customer-group')).not.toContainText('Alpha Synthetic Account')
})

for (const scenario of [
  { label: 'different current account', owner: 'cg_other', notice: 'This project belongs to a different current account.' },
  { label: 'retracted account membership', owner: null, notice: 'selected project is not currently assigned to this account' },
]) {
  test(`selected project clears saved account context when it has a ${scenario.label}`, async ({ page }) => {
    await installAccountFirst(page, { projectOwner: scenario.owner })
    await page.goto('/?view=workspace&groupBrowse=1&account=cg_north&project=project-1&need=need-1')
    await expect(page.getByRole('complementary', { name: 'Opportunity detail' })).toBeVisible()
    await expect(page.getByText(scenario.notice)).toBeVisible()
    await expect(page).toHaveURL(/need=need-1/)
    await expect(page).not.toHaveURL(/account=/)
    await expect(page).not.toHaveURL(/project=/)
    await expect(page.getByText(scenario.notice)).toBeVisible()
  })
}

test('only valid projected contact routes remain actionable after reload', async ({ page }) => {
  const writes: string[] = []
  await installAccountFirst(page)
  page.on('request', request => { if (request.method() !== 'GET') writes.push(request.url()) })
  await page.goto('/?view=workspace&groupBrowse=1&account=cg_north')
  const overview = page.getByRole('region', { name: 'Account overview' })
  await expect(overview.getByRole('link', { name: 'Email Jordan Lee' })).toHaveAttribute('href', 'mailto:jordan@example.invalid')
  await expect(overview).not.toContainText('Suppressed Contact')
  await expect(overview).not.toContainText('javascript:')
  await page.reload()
  const refreshed = page.getByRole('region', { name: 'Account overview' })
  await expect(refreshed.getByRole('link', { name: 'Email Jordan Lee' })).toBeVisible()
  await expect(refreshed).not.toContainText('Suppressed Contact')
  expect(writes).toEqual([])
})
