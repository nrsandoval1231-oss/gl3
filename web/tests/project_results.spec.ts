import { expect, test } from '@playwright/test'
import { resolve } from 'node:path'

// Synthetic mocked contract fixtures only; this does not claim real corpus validation.
const sample = {
  id: 'project-synthetic-1', project_id: 'project-synthetic-1', name: 'Example Compressor Station', company: 'Example Energy',
  location: 'Permian Basin, TX', sector: 'oil_gas', asset_type: 'Compressor station', priority_score: null,
  representative_need_id: 'need-synthetic-1', need_count: 2,
  needs: [{ id: 'need-synthetic-1', project_id: 'project-synthetic-1', location: 'Permian Basin, TX', activity: 'drilling', tier: 'Signal', commercial_preview: { disposition: 'ACTION NOW' } }, { id: 'need-synthetic-2', project_id: 'project-synthetic-1', location: 'Permian Basin, TX', activity: 'drilling' }],
  event: { kind: 'permit_issued', label: 'Permit issued', date: '2026-10-21', source: 'Synthetic official filing', evidence_refs: [] },
  contact: [{ kind: 'unverified', label: 'Call direct', href: 'javascript:alert(1)' }], contact_people: [{ record_type: 'contact_person', company: 'M/E Design LLC', name: 'Jordan Sample', role: 'owner developer', responsibility: 'Verified project responsibility', purchasing_authority: 'Requires confirmation for this power package', source_url: 'https://example.test/source' }], power_summary: 'Power relevance is under review.', power_summary_kind: 'unknown', next_action: 'Review the source-backed site details.', updated_at: '2026-10-22T00:00:00Z',
}
const projectPage = { items: [sample], total: 1, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'synthetic-cohort', generation: 1 }
const group = { id: 'group-synthetic-1', name: 'Example Energy', role: 'operator', operator_number: '123456', project_count: 1, need_count: 2, priority_score: null, sectors: ['oil_gas'] }
const groupPage = { items: [group], total: 1, count_unit: 'operators and customers', limit: 25, offset: 0, cohort_token: 'synthetic-group-cohort', generation: '1' }

test('synthetic default All scope shows operator/customer groups without a qualified-only empty message', async ({ page }) => {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: { ...groupPage, items: [], total: 0 } }))
  await page.goto('/')
  await expect(page.getByText('No operator/customer groups match this search.')).toBeVisible()
})

test('synthetic unresolved group role is explicit and never implies a resolved organization', async ({ page }) => {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: { ...groupPage, items: [{ ...group, role: 'unresolved', name: 'Unresolved source entity' }] } }))
  await page.goto('/')
  await expect(page.locator('.customer-group')).toContainText('Operator/customer unresolved')
  await expect(page.locator('.project-results-count')).toHaveText('1 operator/customer group')
})

test('synthetic project results use the project contract, category filters, and honest contact/event labels', async ({ page }) => {
  const requests: URL[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?*', route => {
    requests.push(new URL(route.request().url()))
    return route.fulfill({ json: groupPage })
  })
  await page.route('**/api/opportunities/groups/group-synthetic-1/projects?*', route => route.fulfill({ json: projectPage }))
  await page.goto('/?view=workspace')
  await expect(page.getByRole('heading', { name: 'Search opportunities' })).toBeVisible()
  await expect(page.getByText('1 operator/customer group')).toBeVisible()
  await page.getByRole('button', { name: /Example Energy/ }).click()
  await expect(page.getByText('Permit issued · 2026-10-21')).toBeVisible()
  await expect(page.getByText('Jordan Sample · Listed owner contact · M/E Design LLC')).toBeVisible()
  await expect(page.locator('.project-card')).not.toContainText('Power relevance is under review.')
  await expect(page.locator('.project-card')).toContainText('Discovery call · Power need unconfirmed')
  await expect(page.getByText('No verified direct method')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Source' })).toHaveAttribute('href', 'https://example.test/source')
  await expect(page.getByRole('link', { name: 'Call direct' })).toHaveCount(0)
  await expect(page.locator('.project-tier')).toHaveText('Signal')
  await expect(page.locator('.project-card .project-next')).toHaveText('Discovery call · Power need unconfirmed')
  await expect(page.locator('.project-needs summary')).toHaveText('2 related power needs')
  await page.getByRole('button', { name: 'Data Centers' }).click()
  await expect.poll(() => requests.some(url => url.searchParams.get('sector') === 'data_centers')).toBeTruthy()
  for (const width of [390, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 })
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  }
})

test('synthetic project pagination retains its cohort and browser Back restores search and sector', async ({ page }) => {
  const requests: URL[] = []
  let fail = false
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?*', route => {
    const url = new URL(route.request().url()); requests.push(url)
    if (fail) return route.fulfill({ status: 503, json: { detail: 'Synthetic failure' } })
    const offset = Number(url.searchParams.get('offset') ?? 0)
    return route.fulfill({ json: { ...groupPage, items: offset ? [] : Array.from({ length: 25 }, (_, index) => ({ ...group, id: `synthetic-${index}`, name: `Synthetic customer ${index}` })), total: 27, offset, cohort_token: 'synthetic-page-cohort' } })
  })
  await page.goto('/?view=workspace&q=example&sector=oil_gas')
  await expect(page.locator('.project-results-count')).toHaveText('27 operator/customer groups')
  await page.getByRole('button', { name: 'Next' }).click()
  await expect.poll(() => requests.some(url => url.searchParams.get('offset') === '25')).toBeTruthy()
  await page.getByRole('button', { name: 'Previous' }).click()
  await expect.poll(() => requests.some(url => url.searchParams.get('offset') === '0' && url.searchParams.get('cohort_token') === 'synthetic-page-cohort')).toBeTruthy()
  fail = true
  await page.getByRole('button', { name: 'Data Centers' }).click()
  await expect(page.getByRole('alert')).toContainText('Could not load operator/customer groups')
  await expect(page.getByRole('heading', { name: 'Synthetic customer 0' })).toHaveCount(0)
  fail = false
  await page.getByRole('button', { name: 'Retry' }).click()
  await expect(page.getByRole('heading', { name: 'Synthetic customer 0' })).toBeVisible()
})

test('synthetic stale cohort conflict drops page token and reloads first page without stale cards', async ({ page }) => {
  let conflict = false
  let releaseFresh: (() => void) | undefined
  const requests: URL[] = []
  const oldItems = Array.from({ length: 25 }, (_, index) => ({ ...group, id: `old-${index}`, name: `Old cohort customer ${index}` }))
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?*', async route => {
    const url = new URL(route.request().url())
    requests.push(url)
    const offset = Number(url.searchParams.get('offset') ?? 0)
    if (offset === 25) {
      conflict = true
      return route.fulfill({ status: 409, json: { detail: 'cohort changed' } })
    }
    if (conflict) {
      await new Promise<void>(resolve => { releaseFresh = resolve })
      return route.fulfill({ json: { ...groupPage, items: [{ ...group, id: 'fresh-customer', name: 'Fresh cohort customer' }], total: 1, offset: 0, limit: 25, cohort_token: 'fresh-cohort' } })
    }
    return route.fulfill({ json: { ...groupPage, items: oldItems, total: 50, offset: 0, limit: 25, cohort_token: 'old-cohort' } })
  })
  await page.goto('/')
  await expect(page.locator('.project-results-count')).toHaveText('50 operator/customer groups')
  await page.getByRole('button', { name: 'Next' }).click()
  await expect(page.locator('.project-results-notice')).toContainText('Results changed')
  await expect.poll(() => requests.some(url => url.searchParams.get('offset') === '0' && !url.searchParams.has('cohort_token'))).toBeTruthy()
  await expect(page.locator('.project-card')).toHaveCount(0)
  expect(new URL(page.url()).searchParams.has('cohort_token')).toBe(false)
  expect(new URL(page.url()).searchParams.has('offset')).toBe(false)
  releaseFresh?.()
  await expect(page.getByRole('heading', { name: 'Fresh cohort customer' })).toBeVisible()
  await expect(page.getByText('Old cohort customer 0')).toHaveCount(0)
})

test('synthetic operator groups expose every project through independent nested pagination', async ({ page }) => {
  const nestedRequests: URL[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: groupPage }))
  await page.route('**/api/opportunities/groups/group-synthetic-1/projects?*', route => {
    const url = new URL(route.request().url()); nestedRequests.push(url)
    expect(url.searchParams.get('parent_cohort_token')).toBe('synthetic-group-cohort')
    const offset = Number(url.searchParams.get('offset') ?? 0)
    const items = Array.from({ length: Math.min(25, 144 - offset) }, (_, index) => ({ ...sample, id: `well-${offset + index}`, name: `Pioneer well ${offset + index + 1}` }))
    return route.fulfill({ json: { ...projectPage, items, total: 144, offset, limit: 25, cohort_token: 'operator-project-cohort' } })
  })
  await page.goto('/')
  await expect(page.getByText('1 operator/customer group')).toBeVisible()
  await page.getByRole('button', { name: /Example Energy/ }).click()
  await expect(page.getByRole('heading', { name: 'Pioneer well 1', exact: true })).toBeVisible()
  await expect(page.getByText('1–25 of 144 projects')).toBeVisible()
  for (let pageIndex = 1; pageIndex < 6; pageIndex++) {
    await page.getByRole('button', { name: 'Next' }).last().click()
    await expect.poll(() => nestedRequests.some(url => url.searchParams.get('offset') === String(pageIndex * 25) && url.searchParams.get('cohort_token') === 'operator-project-cohort')).toBeTruthy()
  }
  await expect(page.getByRole('heading', { name: 'Pioneer well 126', exact: true })).toBeVisible()
  await expect(page.getByText('126–144 of 144 projects')).toBeVisible()
})

test('synthetic nested cohort conflict atomically opens the same group with its fresh parent token', async ({ page }) => {
  let nestedReads = 0
  let openReads = 0
  const otherGroup = { ...group, id: 'other-group', name: 'Unchanged Source Operator', role: 'operator' as const, project_count: 4 }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: { ...groupPage, items: [group, otherGroup], total: 2, cohort_token: 'original-list-token' } }))
  await page.route('**/api/opportunities/groups/group-synthetic-1/projects?*', route => { nestedReads += 1; return route.fulfill({ status: 409, json: { detail: 'parent cohort changed' } }) })
  await page.route('**/api/opportunities/groups/group-synthetic-1/open?*', route => {
    openReads += 1
    const url = new URL(route.request().url())
    expect(url.searchParams.has('parent_cohort_token')).toBe(false)
    expect(url.searchParams.has('cohort_token')).toBe(false)
    expect(url.searchParams.has('offset')).toBe(false)
    return route.fulfill({ json: { group: { ...group, name: 'Fresh Energy Customer', role: 'customer', project_count: 3 }, projects: { ...projectPage, items: [{ ...sample, name: 'Fresh open project' }], cohort_token: 'fresh-child-token' }, parent_cohort_token: 'fresh-parent-cohort', generation: 'fresh-generation' } })
  })
  await page.goto('/')
  await page.getByRole('button', { name: /Energy/ }).first().click()
  await expect(page.getByRole('heading', { name: 'Fresh open project' })).toBeVisible()
  await expect(page.getByRole('button', { name: /Fresh Energy Customer/ })).toHaveAttribute('aria-expanded', 'true')
  const refreshedGroup = page.getByRole('region', { name: 'Fresh Energy Customer customer group' })
  await expect(refreshedGroup.locator('.customer-group-heading small')).toContainText('Customer')
  await expect(refreshedGroup.locator('.customer-group-count')).toHaveText('3 projects')
  await expect(page.getByRole('button', { name: /Unchanged Source Operator/ })).toContainText('4 projects')
  await expect(page.getByRole('button', { name: /Unchanged Source Operator/ })).toContainText('Operator')
  expect(nestedReads).toBe(1)
  expect(openReads).toBe(1)
  await page.getByRole('button', { name: /Fresh Energy Customer/ }).click()
  await expect(page.getByRole('region', { name: 'Example Energy customer group' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Fresh open project' })).toHaveCount(0)
  await page.getByRole('button', { name: /Example Energy/ }).click()
  await expect(page.getByRole('heading', { name: 'Fresh open project' })).toBeVisible()
  expect(nestedReads).toBe(2)
  expect(openReads).toBe(2)
})

test('synthetic paginated child conflict fresh-opens page one and keeps parent-list token separate', async ({ page }) => {
  const childRequests: URL[] = []
  const groupRequests: URL[] = []
  let openReads = 0
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?*', route => { const url = new URL(route.request().url()); groupRequests.push(url); return route.fulfill({ json: { ...groupPage, total: 50, cohort_token: 'original-list-token' } }) })
  await page.route('**/api/opportunities/groups/group-synthetic-1/projects?*', route => {
    const url = new URL(route.request().url()); childRequests.push(url)
    if (url.searchParams.get('offset') === '25') return route.fulfill({ status: 409, json: { detail: 'parent cohort changed' } })
    return route.fulfill({ json: { ...projectPage, total: 50, limit: 25, cohort_token: 'old-child-token', items: Array.from({ length: 25 }, (_, index) => ({ ...sample, id: `child-${index}` })) } })
  })
  await page.route('**/api/opportunities/groups/group-synthetic-1/open?*', route => {
    openReads += 1
    return route.fulfill({ json: { group, projects: { ...projectPage, total: 30, items: [{ ...sample, id: 'fresh-first-page', name: 'Fresh first page project' }] }, parent_cohort_token: 'opened-group-parent-token', generation: 'fresh-generation' } })
  })
  await page.goto('/')
  await page.getByRole('button', { name: /Example Energy/ }).click()
  await page.locator('.customer-group-projects .project-paging').getByRole('button', { name: 'Next' }).click()
  await expect(page.getByRole('heading', { name: 'Fresh first page project' })).toBeVisible()
  expect(openReads).toBe(1)
  await page.locator('.customer-group-projects .project-paging').getByRole('button', { name: 'Next' }).click()
  await expect.poll(() => childRequests.at(-1)?.searchParams.get('parent_cohort_token')).toBe('opened-group-parent-token')
  await page.locator('.project-results > .project-paging').getByRole('button', { name: 'Next' }).click()
  await expect.poll(() => groupRequests.at(-1)?.searchParams.get('cohort_token')).toBe('original-list-token')
})

test('synthetic nested conflict stops when atomic open reports the group missing', async ({ page }) => {
  let openReads = 0
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: groupPage }))
  await page.route('**/api/opportunities/groups/group-synthetic-1/projects?*', route => route.fulfill({ status: 409, json: { detail: 'parent cohort changed' } }))
  await page.route('**/api/opportunities/groups/group-synthetic-1/open?*', route => { openReads += 1; return route.fulfill({ status: 404, json: { detail: 'missing group' } }) })
  await page.goto('/')
  await page.getByRole('button', { name: /Example Energy/ }).click()
  await expect(page.getByRole('status')).toContainText('no longer available')
  expect(openReads).toBe(1)
  await expect(page.getByRole('button', { name: /Example Energy/ })).toHaveAttribute('aria-expanded', 'false')
})

test('synthetic delayed atomic open cannot restore a child after the search changes', async ({ page }) => {
  let releaseOpen: (() => void) | undefined
  let openRequested: (() => void) | undefined
  const requested = new Promise<void>(resolve => { openRequested = resolve })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?*', route => {
    const fresh = Boolean(new URL(route.request().url()).searchParams.get('search'))
    return route.fulfill({ json: { ...groupPage, items: [{ ...group, id: fresh ? 'fresh-group' : group.id, name: fresh ? 'Fresh Search Operator' : group.name }] } })
  })
  await page.route('**/api/opportunities/groups/group-synthetic-1/projects?*', route => route.fulfill({ status: 409, json: { detail: 'parent cohort changed' } }))
  await page.route('**/api/opportunities/groups/group-synthetic-1/open?*', async route => {
    openRequested?.()
    await new Promise<void>(resolve => { releaseOpen = resolve })
    try { await route.fulfill({ json: { group, projects: projectPage, parent_cohort_token: 'stale-open-token', generation: 'stale' } }) } catch { /* Superseded requests are aborted. */ }
  })
  await page.goto('/')
  await page.getByRole('button', { name: /Example Energy/ }).click()
  await requested
  await page.getByRole('textbox', { name: 'Search opportunities' }).fill('fresh')
  await expect(page.getByRole('button', { name: /Fresh Search Operator/ })).toBeVisible()
  releaseOpen?.()
  await expect(page.getByRole('heading', { name: 'Example Compressor Station', exact: true })).toHaveCount(0)
  await expect(page.locator('.project-card')).toHaveCount(0)
})

test('synthetic delayed child response cannot repopulate results after a search change', async ({ page }) => {
  let releaseChild: (() => void) | undefined
  let childRequested: (() => void) | undefined
  const requested = new Promise<void>(resolve => { childRequested = resolve })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?*', route => {
    const url = new URL(route.request().url())
    const fresh = Boolean(url.searchParams.get('search'))
    return route.fulfill({ json: { ...groupPage, cohort_token: fresh ? 'fresh-search-cohort' : 'old-search-cohort', items: [{ ...group, id: fresh ? 'fresh-group' : group.id, name: fresh ? 'Fresh Search Operator' : group.name }] } })
  })
  await page.route('**/api/opportunities/groups/*/projects?*', async route => {
    childRequested?.()
    await new Promise<void>(resolve => { releaseChild = resolve })
    try {
      await route.fulfill({ json: { ...projectPage, cohort_token: 'old-search-child-cohort', items: [{ ...sample, id: 'old-search-project', name: 'Old search project' }] } })
    } catch { /* The browser correctly aborts this superseded request. */ }
  })
  await page.goto('/')
  await page.getByRole('button', { name: /Example Energy/ }).click()
  await requested
  await page.getByRole('textbox', { name: 'Search opportunities' }).fill('fresh')
  await expect(page.getByRole('button', { name: /Fresh Search Operator/ })).toBeVisible()
  releaseChild?.()
  await expect(page.getByRole('heading', { name: 'Old search project', exact: true })).toHaveCount(0)
  await expect(page.locator('.project-card')).toHaveCount(0)
})

test('operator group disclosure is visible and tappable on desktop and mobile', async ({ page }) => {
  const screenshotRoot = resolve(process.cwd(), '..', '.artifacts', 'release-operator-customer-20261027')
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: groupPage }))
  await page.route('**/api/opportunities/groups/group-synthetic-1/projects?*', route => route.fulfill({ json: projectPage }))
  await page.goto('/')
  const groupButton = page.getByRole('button', { name: /Example Energy/ })
  const chevron = groupButton.locator('.customer-group-chevron')
  await expect(groupButton).toHaveAttribute('aria-expanded', 'false')
  await expect(chevron).toBeVisible()
  await expect.poll(() => groupButton.evaluate(element => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44)
  await expect.poll(() => chevron.evaluate(element => getComputedStyle(element).transform)).toBe('none')
  await page.screenshot({ path: resolve(screenshotRoot, 'group-closed-desktop.png'), fullPage: true })

  await groupButton.click()
  await expect(groupButton).toHaveAttribute('aria-expanded', 'true')
  await expect(page.getByRole('heading', { name: 'Example Compressor Station', exact: true })).toBeVisible()
  await expect.poll(() => chevron.evaluate(element => getComputedStyle(element).transform)).not.toBe('none')
  await page.screenshot({ path: resolve(screenshotRoot, 'group-open-desktop.png'), fullPage: true })

  await page.setViewportSize({ width: 390, height: 844 })
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  await page.screenshot({ path: resolve(screenshotRoot, 'group-open-mobile.png'), fullPage: true })
  await groupButton.click()
  await expect(groupButton).toHaveAttribute('aria-expanded', 'false')
  await expect.poll(() => chevron.evaluate(element => getComputedStyle(element).transform)).toBe('none')
  await page.screenshot({ path: resolve(screenshotRoot, 'group-closed-mobile.png'), fullPage: true })
})

test('synthetic detail reloads the selected project by exact need and fails closed until retry', async ({ page }) => {
  let failPreparedRead = true
  const exactReads: URL[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: groupPage }))
  await page.route('**/api/opportunities/groups/group-synthetic-1/projects?*', route => {
    return route.fulfill({ json: projectPage })
  })
  await page.route('**/api/opportunities/projects?*', route => { const url = new URL(route.request().url()); if (url.searchParams.has('need_id')) { exactReads.push(url); if (failPreparedRead) return route.fulfill({ status: 503, json: { detail: 'Synthetic prepared read failure' } }) }; return route.fulfill({ json: { ...projectPage, items: [{ ...sample, power_summary: 'Facility demand is source-supported at 120 MW; temporary bridge demand is not established.', power_summary_kind: 'facility_demand', contact: [{ kind: 'call', label: 'Call Example Energy', href: 'tel:+15555550100' }], contact_people: [{ record_type: 'contact_person', company: 'M/E Design LLC', name: 'Luis Sample', role: 'owner developer', source_url: 'https://example.test/owner' }] }] } }) })
  await page.route('**/api/opportunities/needs/need-synthetic-1*', route => route.fulfill({ json: { id: 'need-synthetic-1', project_id: 'project-synthetic-1', name: 'Stale internal title', activity: 'construction', tier: 'Signal', rationale: 'Internal diagnostic rationale must not appear in the landing detail.', evidence: [] } }))
  await page.goto('/')
  await page.getByRole('button', { name: /Example Energy/ }).click()
  await page.getByRole('button', { name: 'View project details' }).click()
  await expect(page.getByRole('alert')).toContainText('Current project details are unavailable')
  await expect(page.locator('.project-first-detail').getByText('Jordan Sample')).toHaveCount(0)
  await expect(page.locator('.project-first-detail').getByText(/Internal diagnostic rationale/)).toHaveCount(0)
  expect(exactReads.at(-1)?.searchParams.get('need_id')).toBe('need-synthetic-1')

  failPreparedRead = false
  await page.getByRole('button', { name: 'Retry' }).click()
  await expect(page.locator('.project-first-detail')).toContainText('Example Compressor Station')
  await expect(page.locator('.project-first-detail')).toContainText('Luis Sample')
  await expect(page.locator('.project-first-detail')).toContainText('Listed owner contact')
  await expect(page.locator('.project-first-detail')).not.toContainText('Owner Developer')
  await expect(page.locator('.project-detail-contact').filter({ hasText: 'Luis Sample' })).toContainText('M/E Design LLC')
  await expect(page.locator('.project-detail-contact').filter({ hasText: 'Luis Sample' })).not.toContainText('Example Energy')
  await expect(page.getByRole('link', { name: 'Call Example Energy' })).toHaveAttribute('href', 'tel:+15555550100')
  await expect(page.locator('.project-first-detail')).toContainText('Discuss project power plans with Example Energy.')
  await expect(page.locator('.project-first-detail')).toContainText('Facility demand: Facility demand is source-supported at 120 MW; temporary bridge demand is not established.')
  await expect(page.locator('.project-first-detail')).not.toContainText('Internal diagnostic rationale')
  await expect(page.locator('.wh-customer-metrics')).toHaveCount(0)
})

test('synthetic tablet selection opens detail in the viewport above an unfiltered 25-card list', async ({ page }) => {
  await page.setViewportSize({ width: 768, height: 900 })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: { ...groupPage, items: [{ ...group, project_count: 25 }] } }))
  await page.route('**/api/opportunities/groups/group-synthetic-1/projects?*', route => route.fulfill({ json: { ...projectPage, total: 25, items: Array.from({ length: 25 }, (_, index) => ({ ...sample, id: `tablet-${index}` })) } }))
  await page.route('**/api/opportunities/projects?*', route => { const url = new URL(route.request().url()); return route.fulfill({ json: { ...projectPage, items: [{ ...sample, name: url.searchParams.has('need_id') ? 'Synthetic tablet well' : sample.name }] } }) })
  await page.route('**/api/opportunities/needs/need-synthetic-1*', route => route.fulfill({ json: {
    id: 'need-synthetic-1', project_id: 'project-synthetic-1', name: 'Synthetic tablet well',
    browse_title: 'Synthetic tablet well', location: 'Martin County, TX', tier: 'Signal',
    activity: 'drilling', supply: 'Unknown', required_mw: null, start_window: null, duration: null,
    evidence: [], missing_facts: [], rationale: 'Power demand is unconfirmed.',
  } }))
  await page.goto('/?view=workspace&sector=oil_gas')
  await page.getByRole('button', { name: /Example Energy/ }).click()
  await expect(page.locator('.project-card')).toHaveCount(25)
  await page.getByRole('button', { name: 'View project details', exact: true }).first().click()
  await expect(page.locator('.project-first-detail h2')).toHaveText('Synthetic tablet well')
  await expect(page.locator('.project-first-detail h2')).toBeInViewport()
  await expect(page.locator('.project-results')).toBeHidden()
  await page.getByRole('button', { name: 'Back to power needs', exact: true }).click()
  await expect(page.locator('.project-results')).toBeVisible()
})
