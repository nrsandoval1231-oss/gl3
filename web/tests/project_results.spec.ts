import { expect, test } from '@playwright/test'

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

test('synthetic default All scope explains the qualified empty state', async ({ page }) => {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: { ...projectPage, items: [], total: 0, results_scope: 'qualified' } }))
  await page.goto('/')
  await expect(page.getByText('No qualified power opportunities yet. Choose Oil & Gas or Data Centers, or search, to explore early project signals.')).toBeVisible()
})

test('synthetic project results use the project contract, category filters, and honest contact/event labels', async ({ page }) => {
  const requests: URL[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/projects?*', route => {
    requests.push(new URL(route.request().url()))
    return route.fulfill({ json: projectPage })
  })
  await page.goto('/?view=workspace')
  await expect(page.getByRole('heading', { name: 'Search opportunities' })).toBeVisible()
  await expect(page.getByText('1 project')).toBeVisible()
  await expect(page.getByText('Permit issued · 2026-10-21')).toBeVisible()
  await expect(page.getByText('Jordan Sample · Listed owner contact · M/E Design LLC')).toBeVisible()
  await expect(page.locator('.project-card')).not.toContainText('Power relevance is under review.')
  await expect(page.locator('.project-card')).toContainText('Discovery call · Power need unconfirmed')
  await expect(page.getByText('No verified direct method')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Source' })).toHaveAttribute('href', 'https://example.test/source')
  await expect(page.getByRole('link', { name: 'Call direct' })).toHaveCount(0)
  await expect(page.locator('.project-tier')).toHaveText('Signal')
  await expect(page.locator('.project-card .project-next')).toHaveText('Discovery call · Power need unconfirmed')
  await page.getByRole('button', { name: 'Data Centers' }).click()
  await expect.poll(() => requests.some(url => url.searchParams.get('sector') === 'data_centers')).toBeTruthy()
  await expect(page.locator('.project-needs summary')).toHaveText('2 related power needs')
  for (const width of [390, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 })
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  }
})

test('synthetic project pagination retains its cohort and browser Back restores search and sector', async ({ page }) => {
  const requests: URL[] = []
  let fail = false
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/projects?*', route => {
    const url = new URL(route.request().url()); requests.push(url)
    if (fail) return route.fulfill({ status: 503, json: { detail: 'Synthetic failure' } })
    const offset = Number(url.searchParams.get('offset') ?? 0)
    return route.fulfill({ json: { ...projectPage, items: offset ? [] : Array.from({ length: 25 }, (_, index) => ({ ...sample, id: `synthetic-${index}`, name: `Synthetic project ${index}` })), total: 27, offset, cohort_token: 'synthetic-page-cohort' } })
  })
  await page.goto('/?view=workspace&q=example&sector=oil_gas')
  await expect(page.getByText('27 projects')).toBeVisible()
  await page.getByRole('button', { name: 'Next' }).click()
  await expect.poll(() => requests.some(url => url.searchParams.get('offset') === '25')).toBeTruthy()
  await page.getByRole('button', { name: 'Previous' }).click()
  await expect.poll(() => requests.some(url => url.searchParams.get('offset') === '0' && url.searchParams.get('cohort_token') === 'synthetic-page-cohort')).toBeTruthy()
  fail = true
  await page.getByRole('button', { name: 'Data Centers' }).click()
  await expect(page.getByRole('alert')).toContainText('Could not load projects')
  await expect(page.getByRole('heading', { name: 'Synthetic project 0' })).toHaveCount(0)
  fail = false
  await page.getByRole('button', { name: 'Retry' }).click()
  await expect(page.getByRole('heading', { name: 'Synthetic project 0' })).toBeVisible()
})

test('synthetic stale cohort conflict drops page token and reloads first page without stale cards', async ({ page }) => {
  let conflict = false
  let releaseFresh: (() => void) | undefined
  const requests: URL[] = []
  const oldItems = Array.from({ length: 25 }, (_, index) => ({ ...sample, id: `old-${index}`, name: `Old cohort project ${index}` }))
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/projects?*', async route => {
    const url = new URL(route.request().url())
    requests.push(url)
    const offset = Number(url.searchParams.get('offset') ?? 0)
    if (offset === 25) {
      conflict = true
      return route.fulfill({ status: 409, json: { detail: 'cohort changed' } })
    }
    if (conflict) {
      await new Promise<void>(resolve => { releaseFresh = resolve })
      return route.fulfill({ json: { ...projectPage, items: [{ ...sample, id: 'fresh-project', name: 'Fresh cohort project' }], total: 1, offset: 0, limit: 25, cohort_token: 'fresh-cohort' } })
    }
    return route.fulfill({ json: { ...projectPage, items: oldItems, total: 50, offset: 0, limit: 25, cohort_token: 'old-cohort' } })
  })
  await page.goto('/')
  await expect(page.getByText('50 projects')).toBeVisible()
  await page.getByRole('button', { name: 'Next' }).click()
  await expect(page.locator('.project-results-notice')).toContainText('Project results changed')
  await expect.poll(() => requests.some(url => url.searchParams.get('offset') === '0' && !url.searchParams.has('cohort_token'))).toBeTruthy()
  await expect(page.locator('.project-card')).toHaveCount(0)
  expect(new URL(page.url()).searchParams.has('cohort_token')).toBe(false)
  expect(new URL(page.url()).searchParams.has('offset')).toBe(false)
  releaseFresh?.()
  await expect(page.getByRole('heading', { name: 'Fresh cohort project' })).toBeVisible()
  await expect(page.getByText('Old cohort project 0')).toHaveCount(0)
})

test('synthetic detail reloads the selected project by exact need and fails closed until retry', async ({ page }) => {
  let failPreparedRead = true
  const exactReads: URL[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/projects?*', route => {
    const url = new URL(route.request().url())
    const needId = url.searchParams.get('need_id')
    if (needId) {
      exactReads.push(url)
      if (failPreparedRead) return route.fulfill({ status: 503, json: { detail: 'Synthetic prepared read failure' } })
      return route.fulfill({ json: { ...projectPage, items: [{ ...sample, power_summary: 'Facility demand is source-supported at 120 MW; temporary bridge demand is not established.', power_summary_kind: 'facility_demand', contact: [{ kind: 'call', label: 'Call Example Energy', href: 'tel:+15555550100' }], contact_people: [{ record_type: 'contact_person', company: 'M/E Design LLC', name: 'Luis Sample', role: 'owner developer', source_url: 'https://example.test/owner' }] }] } })
    }
    return route.fulfill({ json: projectPage })
  })
  await page.route('**/api/opportunities/needs/need-synthetic-1*', route => route.fulfill({ json: { id: 'need-synthetic-1', project_id: 'project-synthetic-1', name: 'Stale internal title', activity: 'construction', tier: 'Signal', rationale: 'Internal diagnostic rationale must not appear in the landing detail.', evidence: [] } }))
  await page.goto('/')
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
  await page.route('**/api/opportunities/projects?*', route => {
    const url = new URL(route.request().url())
    if (url.searchParams.has('need_id')) return route.fulfill({ json: { ...projectPage, total: 1, limit: 1, items: [{ ...sample, name: 'Synthetic tablet well' }] } })
    return route.fulfill({ json: { ...projectPage, total: 25, items: Array.from({ length: 25 }, (_, index) => ({ ...sample, id: `tablet-${index}` })) } })
  })
  await page.route('**/api/opportunities/needs/need-synthetic-1*', route => route.fulfill({ json: {
    id: 'need-synthetic-1', project_id: 'project-synthetic-1', name: 'Synthetic tablet well',
    browse_title: 'Synthetic tablet well', location: 'Martin County, TX', tier: 'Signal',
    activity: 'drilling', supply: 'Unknown', required_mw: null, start_window: null, duration: null,
    evidence: [], missing_facts: [], rationale: 'Power demand is unconfirmed.',
  } }))
  await page.goto('/?view=workspace&sector=oil_gas')
  await expect(page.locator('.project-card')).toHaveCount(25)
  await page.getByRole('button', { name: 'View project details', exact: true }).first().click()
  await expect(page.locator('.project-first-detail h2')).toHaveText('Synthetic tablet well')
  await expect(page.locator('.project-first-detail h2')).toBeInViewport()
  await expect(page.locator('.project-results')).toBeHidden()
  await page.getByRole('button', { name: 'Back to power needs', exact: true }).click()
  await expect(page.locator('.project-results')).toBeVisible()
})
