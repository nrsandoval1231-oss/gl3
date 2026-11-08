import { mockDemandSummary } from './mock-demand-summary'
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
const projectPage = { items: [sample], total: 1, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'synthetic-cohort', generation: 'synthetic-project-generation', valid_until: '2099-01-01T00:00:00Z' }
const group = { id: 'group-synthetic-1', name: 'Example Energy', role: 'operator', operator_number: '123456', project_count: 1, need_count: 2, priority_score: null, sectors: ['oil_gas'] }
const groupPage = { items: [group], total: 1, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'synthetic-group-cohort', generation: '1' }

test('account-first list filters and pages the entire server cohort before opening shared account detail', async ({ page }) => {
  const requests: URL[] = []
  const accounts = Array.from({ length: 26 }, (_, index) => ({
    ...group,
    id: index === 25 ? 'cg_filter_edge_customer' : `cg_customer_${index}`,
    name: index === 25 ? 'Filter Edge Customer' : `Customer ${String(index).padStart(2, '0')}`,
    role: 'customer',
    project_count: 1,
  }))
  const edgeProject = {
    ...sample, id: 'filter-edge-project', project_id: 'filter-edge-project', customer_identity_id: 'cg_filter_edge_customer',
    name: 'Filter Edge Site', company: 'Filter Edge Customer', representative_need_id: 'need-filter-edge',
    needs: [{ id: 'need-filter-edge', project_id: 'filter-edge-project', browse_title: 'Filter Edge Site', location: 'Austin, TX', activity: 'construction', tier: 'Signal' }],
    need_count: 1, contact_people: [], contact: [{ kind: 'call', label: 'Call Filter Edge Buyer', name: 'Filter Edge Buyer', href: 'tel:+15555550125', company: 'Filter Edge Customer' }],
  }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => {
    const url = new URL(route.request().url()); requests.push(url)
    const offset = Number(url.searchParams.get('offset') ?? 0)
    const matches = accounts.filter(account => {
      const query = url.searchParams.get('search')?.toLocaleLowerCase()
      if (query && !account.name.toLocaleLowerCase().includes(query)) return false
      if (url.searchParams.get('sector') === 'data_centers' && account.id !== 'cg_customer_0') return false
      if (url.searchParams.get('region') && (account.id !== 'cg_filter_edge_customer' || url.searchParams.get('region') !== 'Austin, TX')) return false
      if (url.searchParams.get('stage') && (account.id !== 'cg_filter_edge_customer' || url.searchParams.get('stage') !== 'Construction notice')) return false
      if (url.searchParams.get('priority') === 'ranked' && account.id !== 'cg_filter_edge_customer') return false
      return true
    })
    if (url.searchParams.get('sort') === 'company') matches.sort((a, b) => a.name.localeCompare(b.name))
    return route.fulfill({ json: {
      items: matches.slice(offset, offset + 25), total: matches.length, count_unit: 'groups', limit: 25, offset,
      cohort_token: url.searchParams.get('cohort_token') ?? 'account-list-cohort', generation: 'synthetic-account-generation',
      facets: { regions: ['Austin, TX'], stages: ['Construction notice'] },
    } })
  })
  await page.route('**/api/opportunities/groups/cg_filter_edge_customer/open?*', route => route.fulfill({ json: {
    group: { ...accounts[25], group_kind: 'resolved_identity', total_known_project_count: 1 },
    projects: { items: [edgeProject], total: 1, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'edge-child', generation: 'synthetic-account-generation', valid_until: '2099-01-01T00:00:00Z' },
    parent_cohort_token: 'account-list-cohort', generation: 'synthetic-account-generation',
  } }))
  await page.route('**/api/opportunities/needs/need-filter-edge*', route => route.fulfill({ json: {
    id: 'need-filter-edge', project_id: 'filter-edge-project', name: 'Filter Edge Site', browse_title: 'Filter Edge Site',
    location: 'Austin, TX', tier: 'Signal', activity: 'construction', supply: 'Unknown', required_mw: null,
    start_window: null, duration: null, evidence: [], missing_facts: [], rationale: 'Synthetic source-backed fixture.',
    associated_account: { company_identity_id: 'cg_filter_edge_customer', name: 'Filter Edge Customer', support_status: 'current' },
  } }))
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: { ...projectPage, items: [edgeProject], total: 1, count_unit: 'projects', limit: 1, offset: 0 } }))
  await page.route('**/api/projects/filter-edge-project/account', route => route.fulfill({ json: { id: 'cg_filter_edge_customer', name: 'Filter Edge Customer', group_kind: 'resolved_identity', project_id: 'filter-edge-project' } }))
  await page.route('**/api/commercial-pursuits*', route => route.fulfill({ json: { items: [], counts: { total: 0, active: 0, needs_attention: 0 }, total_matching: 0, has_more: false, next_offset: null } }))

  await page.goto('/?view=workspace&groupBrowse=1&shortlist=0')
  await expect(page.getByRole('heading', { name: 'Customer accounts' })).toBeVisible()
  await expect(page.locator('.cfr-kpis')).toHaveCount(0)
  await expect(page.locator('.customer-group')).toHaveCount(25)
  await expect(page.locator('.project-results-count')).toHaveText('26 accounts')
  expect(requests[0].searchParams.get('sector')).toBe('all')
  expect(requests[0].searchParams.get('shortlist')).toBe('false')

  await page.getByRole('button', { name: 'Data Centers', exact: true }).click()
  await expect.poll(() => requests.at(-1)?.searchParams.get('sector')).toBe('data_centers')
  await expect(page.locator('.customer-group')).toHaveCount(1)
  await expect(page.locator('.customer-group')).toContainText('Customer 00')
  expect(new URL(page.url()).searchParams.get('sector')).toBe('data_centers')
  await page.getByRole('button', { name: 'All', exact: true }).click()
  await page.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(page.locator('.customer-group')).toHaveCount(1)
  await expect(page.locator('.customer-group')).toContainText('Filter Edge Customer')
  expect(requests.at(-1)?.searchParams.get('cohort_token')).toBeTruthy()
  await page.getByRole('button', { name: 'Previous', exact: true }).click()
  await expect(page.locator('.customer-group')).toHaveCount(25)

  await page.getByText('More filters and sorting', { exact: true }).click()
  await page.getByRole('combobox', { name: 'Sort opportunities' }).selectOption('company')
  await expect.poll(() => requests.at(-1)?.searchParams.get('sort')).toBe('company')
  await page.getByRole('combobox', { name: 'Region' }).selectOption('Austin, TX')
  await expect.poll(() => requests.at(-1)?.searchParams.get('region')).toBe('Austin, TX')
  await page.getByRole('combobox', { name: 'Stage' }).selectOption('Construction notice')
  await expect.poll(() => requests.at(-1)?.searchParams.get('stage')).toBe('Construction notice')
  await page.getByRole('combobox', { name: 'Priority' }).selectOption('ranked')
  await expect.poll(() => requests.at(-1)?.searchParams.get('priority')).toBe('ranked')
  const search = page.getByRole('textbox', { name: 'Search accounts and projects' })
  await search.fill('Filter Edge Customer')
  await expect.poll(() => requests.at(-1)?.searchParams.get('search')).toBe('Filter Edge Customer')
  await expect(page.locator('.customer-group')).toHaveCount(1)
  await expect(page.locator('.customer-group')).toContainText('Filter Edge Customer')
  const current = new URL(page.url()).searchParams
  expect(current.get('sort')).toBe('company')
  expect(current.get('region')).toBe('Austin, TX')
  expect(current.get('stage')).toBe('Construction notice')
  expect(current.get('priority')).toBe('ranked')
  expect(current.get('shortlist')).toBe('0')
  expect(requests.slice(-4).every(url => url.searchParams.get('offset') === '0')).toBe(true)

  await page.locator('.customer-group').getByRole('button', { name: /Filter Edge Customer/ }).click()
  const account = page.getByRole('region', { name: 'Company Filter Edge Customer' })
  await expect(account.getByRole('region', { name: 'Account projects' })).toBeVisible()
  const projectRow = account.locator('[data-project-id="filter-edge-project"]')
  await expect(account.getByRole('region', { name: 'Account overview' }).getByRole('link', { name: 'Call Filter Edge Buyer' })).toHaveAttribute('href', 'tel:+15555550125')
  await projectRow.getByRole('button', { name: /Open project detail/ }).click()
  await expect(page).toHaveURL(/need=need-filter-edge/)
  await expect(page).toHaveURL(/account=cg_filter_edge_customer/)
  const selectedDetail = page.getByRole('complementary', { name: 'Opportunity detail' })
  await expect(selectedDetail.getByRole('heading', { name: 'Filter Edge Site', exact: true })).toBeVisible()
  await page.goBack()
  await expect(page.getByRole('heading', { name: 'Filter Edge Customer', exact: true })).toBeVisible()
  await page.goBack()
  await expect(search).toHaveValue('Filter Edge Customer')
  await page.getByText('More filters and sorting', { exact: true }).click()
  await expect(page.getByRole('combobox', { name: 'Sort opportunities' })).toHaveValue('company')
  await expect(page.getByRole('combobox', { name: 'Region' })).toHaveValue('Austin, TX')
  await expect(page.getByRole('combobox', { name: 'Stage' })).toHaveValue('Construction notice')
  await expect(page.getByRole('combobox', { name: 'Priority' })).toHaveValue('ranked')
  expect(new URL(page.url()).searchParams.has('sector')).toBe(false)
})
test('legacy flat sort and malformed offset links normalize to a valid default grouped URL and request', async ({ page }) => {
  const requests: URL[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => {
    const url = new URL(route.request().url())
    requests.push(url)
    return route.fulfill({ json: { ...groupPage, items: [{ ...group, group_kind: 'resolved_identity' }] } })
  })
  await page.goto('/?sort=project&offset=-5&groupBrowse=1&shortlist=0')
  await expect(page.locator('.customer-group')).toHaveCount(1)
  await expect.poll(() => requests.length).toBeGreaterThan(0)
  expect(requests[0].searchParams.get('sort')).toBe('priority')
  expect(requests[0].searchParams.get('offset')).toBe('0')
  const normalizedUrl = new URL(page.url())
  expect(normalizedUrl.searchParams.has('sort')).toBe(false)
  expect(normalizedUrl.searchParams.has('offset')).toBe(false)
})

test('account shortlist cards show useful location, sector, and the best supported contact', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const featured = { ...sample, contact: [
    { kind: 'call', label: 'Company switchboard', href: 'tel:+15555550100', route_kind: 'company_route' },
    { kind: 'email', label: 'Email buyer', href: 'mailto:buyer@example.test', name: 'Alex Buyer', title: 'Power Procurement', company: 'Example Energy', route_kind: 'named_contact' },
  ] }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: { ...groupPage, items: [{ ...group, featured_project: featured }] } }))
  await page.goto('/?groupBrowse=1&shortlist=1')
  const card = page.locator('.customer-group')
  await expect(card).toContainText('Permian Basin, TX')
  await expect(card).toContainText('Oil & Gas')
  await expect(card).toContainText('Alex Buyer')
  await expect(card).toContainText('Power Procurement')
  await expect(card.getByRole('link', { name: 'Email Alex Buyer' })).toHaveAttribute('href', 'mailto:buyer@example.test')
  await expect(card).not.toContainText('Operator 123456')
  await expect.poll(() => card.getByRole('link', { name: 'Email Alex Buyer' }).evaluate(element => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44)
})

test('same-name account detail retains three distinct project identities and their contact routes', async ({ page }) => {
  const projects = ['a', 'b', 'c'].map((suffix, index) => ({
    ...sample,
    id: `amazon-pecos-${suffix}`, project_id: `amazon-pecos-${suffix}`,
    name: 'AMAZON PECOS Facility', company: `PECOS identity ${String.fromCharCode(65 + index)}`,
    representative_need_id: `need-amazon-${suffix}`,
    needs: [{ id: `need-amazon-${suffix}`, project_id: `amazon-pecos-${suffix}`, browse_title: 'AMAZON PECOS Facility', activity: 'construction', tier: 'Signal' }],
    need_count: 1, contact_people: [], contact: [],
  }))
  const group = { id: 'same-name-amazon-pecos', name: 'AMAZON', role: 'customer', group_kind: 'same_name_unconfirmed', identity_count: 3, project_count: 3, need_count: 3, sectors: ['oil_gas'] }
  const detailReads: string[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: { items: [group], total: 1, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'amazon-name-cohort', generation: 'synthetic-amazon-generation', facets: { regions: [], stages: [] } } }))
  await page.route('**/api/opportunities/groups/same-name-amazon-pecos/open?*', route => route.fulfill({ json: {
    group, parent_cohort_token: 'amazon-name-cohort', generation: 'synthetic-amazon-generation',
    valid_until: '2099-01-01T00:00:00Z', projects: { items: projects, total: 3, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'amazon-project-cohort', generation: 'synthetic-amazon-generation', valid_until: '2099-01-01T00:00:00Z' },
  } }))
  await page.route('**/api/opportunities/projects?*', route => {
    const needId = new URL(route.request().url()).searchParams.get('need_id')
    const project = projects.find(item => item.representative_need_id === needId)
    return route.fulfill({ json: { items: project ? [project] : [], total: project ? 1 : 0, count_unit: 'projects', limit: 1, offset: 0, cohort_token: `detail-${needId}`, generation: 'synthetic-amazon-generation', valid_until: '2099-01-01T00:00:00Z' } })
  })
  await page.route('**/api/opportunities/needs/need-amazon-*', route => {
    const needId = new URL(route.request().url()).pathname.split('/').at(-1)!
    const index = needId.endsWith('-a') ? 0 : needId.endsWith('-b') ? 1 : 2
    const suffix = String.fromCharCode(65 + index)
    detailReads.push(needId)
    const email = `buyer-${suffix.toLowerCase()}@example.invalid`
    const phone = `+1555555010${index + 1}`
    return route.fulfill({ json: {
      id: needId, project_id: `amazon-pecos-${suffix.toLowerCase()}`, name: 'AMAZON PECOS Facility', browse_title: 'AMAZON PECOS Facility',
      location: 'Pecos, TX', tier: 'Signal', activity: 'construction', supply: 'Unknown', required_mw: null,
      start_window: null, duration: null, evidence: [], missing_facts: [], rationale: 'Synthetic source-backed fixture.',
      intelligence_card: { contacts: [{ claim_id: `claim-${suffix}`, company: `PECOS identity ${suffix}`, name: `Buyer ${suffix}`, title: 'Synthetic project contact', role: 'Project contact', responsibility: 'Verified project responsibility', purchasing_authority: 'Requires confirmation', methods: [{ kind: 'email', value: email, href: `mailto:${email}`, verified_at: '2026-11-01T00:00:00Z' }, { kind: 'phone', value: phone, href: `tel:${phone}`, verified_at: '2026-11-01T00:00:00Z' }], sources: [] }], fields: [], evidence: [] },
    } })
  })

  await page.goto('/?groupBrowse=1&shortlist=0')
  const groupCard = page.getByRole('region', { name: 'AMAZON name group' })
  await expect(groupCard).toContainText('Name group')
  await expect(groupCard.getByText('Same source-reported name; company identities are not linked.', { exact: true })).toBeVisible()
  await expect(groupCard.getByText('3 separate company identities', { exact: true })).toBeVisible()
  await groupCard.getByRole('button', { name: /AMAZON/ }).click()
  const account = page.getByRole('region', { name: 'Group AMAZON' })
  await expect(account.getByRole('heading', { name: 'Projects' })).toBeVisible()
  const rows = account.locator('.cmp-projects li')
  await expect(rows).toHaveCount(3)
  for (let index = 0; index < 3; index += 1) {
    const row = rows.nth(index)
    const suffix = String.fromCharCode(65 + index)
    await expect(row.locator('strong')).toHaveText('AMAZON PECOS Facility')
    await row.getByRole('button', { name: /Open project detail/ }).click()
    const detail = page.getByRole('complementary', { name: 'Opportunity detail' })
    await expect(detail.getByRole('heading', { name: 'AMAZON PECOS Facility', exact: true })).toBeVisible()
    await expect(detail).toContainText(`PECOS identity ${suffix}`)
    await expect(detail.getByRole('link', { name: `Email buyer-${suffix.toLowerCase()}@example.invalid` })).toHaveAttribute('href', `mailto:buyer-${suffix.toLowerCase()}@example.invalid`)
    await expect(detail.getByRole('link', { name: `Call +1555555010${index + 1}` })).toHaveAttribute('href', `tel:+1555555010${index + 1}`)
    if (index === 0) {
      await page.setViewportSize({ width: 390, height: 844 })
      await expect.poll(() => detail.locator('.cod-back').evaluate(element => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44)
      await expect.poll(() => detail.locator('.cod-contact-button').first().evaluate(element => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44)
      await expect.poll(() => detail.locator('.cod-actions button').first().evaluate(element => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44)
    }
    await expect.poll(() => detailReads.at(-1)).toBe(`need-amazon-${suffix.toLowerCase()}`)
    await page.goBack()
    await expect(account.getByRole('heading', { name: 'Projects' })).toBeVisible()
    await expect(rows).toHaveCount(3)
  }
  expect([...new Set(detailReads)]).toEqual(['need-amazon-a', 'need-amazon-b', 'need-amazon-c'])
})
test('synthetic default All scope shows neutral group wording without a qualified-only empty message', async ({ page }) => {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: { ...groupPage, items: [], total: 0 } }))
  await page.goto('/?groupBrowse=1&shortlist=0')
  await expect(page.getByText('No accounts are available in this scope.')).toBeVisible()
})

test('legacy groupBrowse URL keeps unresolved groups explicit without implying a resolved organization', async ({ page }) => {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: { ...groupPage, items: [{ ...group, role: 'unresolved', name: 'Unresolved source entity' }] } }))
  await page.goto('/?groupBrowse=1&shortlist=0')
  await expect(page.locator('.customer-group')).toContainText('Operator/customer unresolved')
  await expect(page.locator('.project-results-count')).toHaveText('1 account')
})

test('shared account detail keeps project source context and rejects unsafe contact routes at every viewport', async ({ page }) => {
  const requests: URL[] = []
  const project = { ...sample, event: { ...sample.event, source: 'https://example.test/source' } }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => { requests.push(new URL(route.request().url())); return route.fulfill({ json: groupPage }) })
  await page.route('**/api/opportunities/groups/group-synthetic-1/open?*', route => route.fulfill({ json: {
    group: { ...group, group_kind: 'resolved_identity', total_known_project_count: 1 }, parent_cohort_token: 'synthetic-group-cohort', generation: 'synthetic',
    projects: { ...projectPage, items: [project] },
  } }))
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: { ...projectPage, items: [project] } }))
  await page.route('**/api/opportunities/needs/need-synthetic-1*', route => route.fulfill({ json: {
    id: 'need-synthetic-1', project_id: 'project-synthetic-1', name: 'Example Compressor Station', browse_title: 'Example Compressor Station',
    location: 'Permian Basin, TX', tier: 'Signal', activity: 'drilling', supply: 'Unknown', required_mw: null,
    start_window: null, duration: null, evidence: [], missing_facts: [], rationale: 'Synthetic source-backed fixture.',
    associated_account: { company_identity_id: 'group-synthetic-1', name: 'Example Energy', support_status: 'current' },
  } }))
  await page.goto('/?view=workspace&groupBrowse=1&shortlist=0')
  await expect(page.getByRole('heading', { name: 'Customer accounts' })).toBeVisible()
  await expect(page.locator('.project-results-count')).toHaveText('1 account')
  await page.locator('.customer-group').getByRole('button', { name: /Example Energy/ }).click()
  const account = page.getByRole('region', { name: 'Company Example Energy' })
  const row = account.locator('[data-project-id="project-synthetic-1"]')
  await expect(row).toContainText('Permit issued')
  await expect(row).not.toContainText('Power relevance is under review.')
  await row.getByText('Sources', { exact: true }).click()
  await expect(row.getByRole('link', { name: 'Open source' })).toHaveAttribute('href', 'https://example.test/source')
  await expect(row.getByRole('link', { name: 'Call direct' })).toHaveCount(0)
  await expect(account.getByRole('region', { name: 'Account overview' })).toContainText('No current business contact route is available.')
  await row.getByRole('button', { name: /Open project detail/ }).click()
  const detail = page.getByRole('complementary', { name: 'Opportunity detail' })
  await expect(detail.getByRole('heading', { name: 'Example Compressor Station', exact: true })).toBeVisible()
  await expect(detail.getByRole('link', { name: 'Call direct' })).toHaveCount(0)
  expect(new URL(page.url()).searchParams.get('account')).toBe('group-synthetic-1')
  await page.goBack()
  await expect(account.getByRole('heading', { name: 'Projects' })).toBeVisible()
  await account.getByRole('button', { name: 'Back to accounts' }).click()
  await page.getByRole('button', { name: 'Data Centers', exact: true }).click()
  await expect.poll(() => requests.at(-1)?.searchParams.get('sector')).toBe('data_centers')
  for (const width of [390, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 })
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  }
})
test('synthetic project pagination retains its cohort and browser Back restores search and sector', async ({ page }) => {
  const requests: URL[] = []
  let fail = false
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => {
    const url = new URL(route.request().url()); requests.push(url)
    if (fail) return route.fulfill({ status: 503, json: { detail: 'Synthetic failure' } })
    const offset = Number(url.searchParams.get('offset') ?? 0)
    return route.fulfill({ json: { ...groupPage, items: offset ? [] : Array.from({ length: 25 }, (_, index) => ({ ...group, id: `synthetic-${index}`, name: `Synthetic customer ${index}` })), total: 27, offset, cohort_token: 'synthetic-page-cohort' } })
  })
  await page.goto('/?view=workspace&q=example&sector=oil_gas&groupBrowse=1&shortlist=0')
  await expect(page.locator('.project-results-count')).toHaveText('27 accounts')
  await page.getByRole('button', { name: 'Next' }).click()
  await expect.poll(() => requests.some(url => url.searchParams.get('offset') === '25')).toBeTruthy()
  await page.getByRole('button', { name: 'Previous' }).click()
  await expect.poll(() => requests.some(url => url.searchParams.get('offset') === '0' && url.searchParams.get('cohort_token') === 'synthetic-page-cohort')).toBeTruthy()
  fail = true
  await page.getByRole('button', { name: 'Data Centers' }).click()
  await expect(page.getByRole('alert')).toContainText('Could not load accounts')
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
  await mockDemandSummary(page)
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
  await page.goto('/?groupBrowse=1&shortlist=0')
  await expect(page.locator('.project-results-count')).toHaveText('50 accounts')
  await page.getByRole('button', { name: 'Next' }).click()
  // The initial load is also an offset-0 request without a token, so only a request AFTER the conflicting
  // offset-25 one proves the first-page reload, and only a held handler proves releaseFresh is armed.
  await expect.poll(() => { const conflictAt = requests.findIndex(url => url.searchParams.get('offset') === '25'); return conflictAt >= 0 && requests.slice(conflictAt + 1).some(url => url.searchParams.get('offset') === '0' && !url.searchParams.has('cohort_token')) }).toBeTruthy()
  await expect.poll(() => Boolean(releaseFresh)).toBe(true)
  await expect(page.locator('.project-results-count')).toContainText('Results changed. Reloaded from the first page.')
  await expect(page.getByText('Old cohort customer 0')).toHaveCount(0)
  expect(new URL(page.url()).searchParams.has('cohort_token')).toBe(false)
  expect(new URL(page.url()).searchParams.has('offset')).toBe(false)
  releaseFresh?.()
  await expect(page.getByRole('heading', { name: 'Fresh cohort customer' })).toBeVisible()
  await expect(page.getByText('Old cohort customer 0')).toHaveCount(0)
})

test('synthetic account detail exposes every project through independent load-more pagination', async ({ page }) => {
  const projectRequests: URL[] = []
  const projectsAt = (offset: number) => Array.from({ length: Math.min(25, 144 - offset) }, (_, index) => ({ ...sample, id: `well-${offset + index}`, project_id: `well-${offset + index}`, name: `Pioneer well ${offset + index + 1}` }))
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: groupPage }))
  await page.route('**/api/opportunities/groups/group-synthetic-1/open?*', route => route.fulfill({ json: {
    group: { ...group, group_kind: 'resolved_identity', total_known_project_count: 144, project_count: 144 },
    projects: { ...projectPage, items: projectsAt(0), total: 144, limit: 25, cohort_token: 'operator-project-cohort', valid_until: '2099-01-01T00:00:00Z' },
    parent_cohort_token: 'synthetic-group-cohort', generation: 'synthetic-generation', valid_until: '2099-01-01T00:00:00Z',
  } }))
  await page.route('**/api/opportunities/groups/group-synthetic-1/projects?*', route => {
    const url = new URL(route.request().url()); projectRequests.push(url)
    const offset = Number(url.searchParams.get('offset') ?? 0)
    expect(url.searchParams.get('parent_cohort_token')).toBe('synthetic-group-cohort')
    return route.fulfill({ json: { ...projectPage, items: projectsAt(offset), total: 144, offset, limit: 25, cohort_token: 'operator-project-cohort', valid_until: '2099-01-01T00:00:00Z' } })
  })
  await page.goto('/?groupBrowse=1&shortlist=0')
  await expect(page.locator('.project-results-count')).toHaveText('1 account')
  await page.getByRole('button', { name: /Example Energy/ }).click()
  const account = page.getByRole('region', { name: 'Company Example Energy' })
  await expect(account.locator('.cmp-projects li')).toHaveCount(25)
  await expect(account.locator('.cmp-projects li').first()).toContainText('Pioneer well 1')
  await expect(account).toContainText('144 known projects')
  for (let pageIndex = 1; pageIndex < 6; pageIndex++) {
    await account.getByRole('button', { name: 'Load more projects' }).click()
    await expect.poll(() => projectRequests.some(url => url.searchParams.get('offset') === String(pageIndex * 25) && url.searchParams.get('cohort_token') === 'operator-project-cohort')).toBeTruthy()
    await expect(account.locator('.cmp-projects li')).toHaveCount(Math.min((pageIndex + 1) * 25, 144))
  }
  await expect(account.locator('.cmp-projects li')).toHaveCount(144)
  await expect(account.locator('.cmp-projects li').last()).toContainText('Pioneer well 144')
  expect(projectRequests.map(url => url.searchParams.get('offset'))).toEqual(['25', '50', '75', '100', '125'])
})

test('synthetic account project-page conflict reopens the same account with fresh parent context', async ({ page }) => {
  const pageReads: URL[] = []
  let openReads = 0
  let stalePageConflict = false
  const otherGroup = { ...group, id: 'other-group', name: 'Unchanged Source Operator', role: 'operator' as const, project_count: 4 }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: { ...groupPage, items: [group, otherGroup], total: 2, cohort_token: 'original-list-token' } }))
  await page.route('**/api/opportunities/groups/group-synthetic-1/projects?*', route => {
    const url = new URL(route.request().url()); pageReads.push(url)
    if (!stalePageConflict && url.searchParams.get('cohort_token') === 'old-child-token') { stalePageConflict = true; return route.fulfill({ status: 409, json: { detail: 'parent cohort changed' } }) }
    return route.fulfill({ json: { ...projectPage, items: [{ ...sample, id: 'fresh-page-project', name: 'Fresh page project' }], total: 3, offset: 1, limit: 25, cohort_token: 'fresh-child-token', valid_until: '2099-01-01T00:00:00Z' } })
  })
  await page.route('**/api/opportunities/groups/group-synthetic-1/open?*', route => {
    openReads += 1
    const url = new URL(route.request().url())
    expect(url.searchParams.has('parent_cohort_token')).toBe(false)
    expect(url.searchParams.has('cohort_token')).toBe(false)
    expect(url.searchParams.has('offset')).toBe(false)
    return route.fulfill({ json: { group: { ...group, name: 'Fresh Energy Customer', role: 'customer', project_count: 3 }, projects: { ...projectPage, items: [{ ...sample, id: `initial-project-${openReads}`, name: stalePageConflict ? 'Fresh first-page project' : 'Initial project' }], total: 3, cohort_token: stalePageConflict ? 'fresh-child-token' : 'old-child-token', valid_until: '2099-01-01T00:00:00Z' }, parent_cohort_token: stalePageConflict ? 'fresh-parent-cohort' : 'old-parent-token', generation: 'fresh-generation', valid_until: '2099-01-01T00:00:00Z' } })
  })
  await page.goto('/?groupBrowse=1&shortlist=0')
  await page.getByRole('button', { name: /Energy/ }).first().click()
  const account = page.getByRole('region', { name: 'Company Fresh Energy Customer' })
  await expect(account.locator('.cmp-projects li strong', { hasText: 'Initial project' })).toBeVisible()
  await account.getByRole('button', { name: 'Load more projects' }).click()
  await expect(account.locator('.cmp-projects li strong', { hasText: 'Fresh first-page project' })).toBeVisible()
  await expect(account.locator('.cmp-projects li strong', { hasText: 'Fresh page project' })).toBeVisible()
  expect(pageReads.map(url => url.searchParams.get('cohort_token'))).toEqual(['old-child-token', 'fresh-child-token'])
  expect(pageReads[0].searchParams.get('parent_cohort_token')).toBe('old-parent-token')
  expect(pageReads[1].searchParams.get('parent_cohort_token')).toBe('fresh-parent-cohort')
  expect(openReads).toBeGreaterThan(1)
  await account.getByRole('button', { name: 'Back to accounts' }).click()
  await expect(page.getByRole('button', { name: /Unchanged Source Operator/ })).toBeVisible()
  // The test entered from an unpaged account list; account detail recovery must
  // keep project tokens separate, while list-token restoration is covered below.
  expect(new URL(page.url()).searchParams.has('cohort_token')).toBe(false)
})

test('synthetic account project-page conflict fresh-opens page one and keeps list token separate', async ({ page }) => {
  const childRequests: URL[] = []
  const groupRequests: URL[] = []
  let openReads = 0
  let stalePageConflict = false
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => { const url = new URL(route.request().url()); groupRequests.push(url); return route.fulfill({ json: { ...groupPage, total: 50, cohort_token: 'original-list-token' } }) })
  await page.route('**/api/opportunities/groups/group-synthetic-1/projects?*', route => {
    const url = new URL(route.request().url()); childRequests.push(url)
    if (!stalePageConflict && url.searchParams.get('cohort_token') === 'old-child-token') { stalePageConflict = true; return route.fulfill({ status: 409, json: { detail: 'parent cohort changed' } }) }
    return route.fulfill({ json: { ...projectPage, total: 50, offset: 25, limit: 25, cohort_token: 'opened-child-token', items: Array.from({ length: 25 }, (_, index) => ({ ...sample, id: `fresh-child-${index}`, name: `Fresh child ${index}` })) } })
  })
  await page.route('**/api/opportunities/groups/group-synthetic-1/open?*', route => {
    openReads += 1
    const firstPage = stalePageConflict ? Array.from({ length: 25 }, (_, index) => ({ ...sample, id: `fresh-first-${index}`, name: `Fresh first page project ${index + 1}` })) : Array.from({ length: 25 }, (_, index) => ({ ...sample, id: `old-child-${index}`, name: `Old child ${index}` }))
    return route.fulfill({ json: { group: { ...group, total_known_project_count: 50 }, projects: { ...projectPage, total: 50, items: firstPage, cohort_token: stalePageConflict ? 'opened-child-token' : 'old-child-token', valid_until: '2099-01-01T00:00:00Z' }, parent_cohort_token: stalePageConflict ? 'opened-group-parent-token' : 'old-parent-token', generation: 'fresh-generation', valid_until: '2099-01-01T00:00:00Z' } })
  })
  await page.goto('/?groupBrowse=1&shortlist=0')
  await page.getByRole('button', { name: /Example Energy/ }).click()
  const account = page.getByRole('region', { name: 'Company Example Energy' })
  await account.getByRole('button', { name: 'Load more projects' }).click()
  await expect(account.locator('.cmp-projects li').filter({ has: page.getByText('Fresh first page project 1', { exact: true }) })).toBeVisible()
  await expect(account.locator('.cmp-projects li').filter({ has: page.getByText('Fresh child 0', { exact: true }) })).toBeVisible()
  expect(openReads).toBeGreaterThan(1)
  await expect.poll(() => childRequests.at(-1)?.searchParams.get('parent_cohort_token')).toBe('opened-group-parent-token')
  await account.getByRole('button', { name: 'Back to accounts' }).click()
  await page.getByRole('button', { name: 'Next' }).click()
  await expect.poll(() => groupRequests.at(-1)?.searchParams.get('cohort_token')).toBe('original-list-token')
})

test('synthetic account project conflict stops when the refreshed account is unavailable', async ({ page }) => {
  let openReads = 0
  let pageConflict = false
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: groupPage }))
  await page.route('**/api/opportunities/groups/group-synthetic-1/open?*', route => {
    openReads += 1
    if (!pageConflict) return route.fulfill({ json: { group, projects: { ...projectPage, items: Array.from({ length: 25 }, (_, index) => ({ ...sample, id: `old-${index}` })), total: 30, cohort_token: 'expired-child', valid_until: '2099-01-01T00:00:00Z' }, parent_cohort_token: 'old-parent', generation: 'old', valid_until: '2099-01-01T00:00:00Z' } })
    return route.fulfill({ status: 404, json: { detail: 'missing group' } })
  })
  await page.route('**/api/opportunities/groups/group-synthetic-1/projects?*', route => { pageConflict = true; return route.fulfill({ status: 409, json: { detail: 'parent cohort changed' } }) })
  await page.goto('/?groupBrowse=1&shortlist=0')
  await page.getByRole('button', { name: /Example Energy/ }).click()
  const account = page.getByRole('region', { name: 'Company Example Energy' })
  const initialOpenReads = openReads
  await account.getByRole('button', { name: 'Load more projects' }).click()
  await expect(account.getByRole('alert')).toContainText('no longer available')
  expect(openReads).toBe(initialOpenReads + 1)
  await expect(account.locator('.cmp-projects li')).toHaveCount(0)
})

test('synthetic delayed account recovery cannot restore a project page after search changes', async ({ page }) => {
  let releaseOpen: (() => void) | undefined
  let openRequested: (() => void) | undefined
  let openReads = 0
  const requested = new Promise<void>(resolve => { openRequested = resolve })
  let pageConflict = false
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => {
    const fresh = Boolean(new URL(route.request().url()).searchParams.get('search'))
    return route.fulfill({ json: { ...groupPage, items: [{ ...group, id: fresh ? 'fresh-group' : group.id, name: fresh ? 'Fresh Search Operator' : group.name }] } })
  })
  await page.route('**/api/opportunities/groups/group-synthetic-1/projects?*', route => { pageConflict = true; return route.fulfill({ status: 409, json: { detail: 'parent cohort changed' } }) })
  await page.route('**/api/opportunities/groups/group-synthetic-1/open?*', async route => {
    openReads += 1
    if (!pageConflict) return route.fulfill({ json: { group, projects: { ...projectPage, items: Array.from({ length: 25 }, (_, index) => ({ ...sample, id: `old-${index}` })), total: 50, cohort_token: 'old-child', valid_until: '2099-01-01T00:00:00Z' }, parent_cohort_token: 'old-parent', generation: 'old', valid_until: '2099-01-01T00:00:00Z' } })
    openRequested?.()
    await new Promise<void>(resolve => { releaseOpen = resolve })
    try { await route.fulfill({ json: { group, projects: projectPage, parent_cohort_token: 'stale-open-token', generation: 'stale' } }) } catch { /* Superseded requests are aborted. */ }
  })
  await page.goto('/?groupBrowse=1&shortlist=0')
  await page.getByRole('button', { name: /Example Energy/ }).click()
  const account = page.getByRole('region', { name: 'Company Example Energy' })
  await account.getByRole('button', { name: 'Load more projects' }).click()
  await requested
  await account.getByRole('button', { name: 'Back to accounts' }).click()
  await page.getByRole('textbox', { name: 'Search accounts and projects' }).fill('fresh')
  await expect(page.getByRole('button', { name: /Fresh Search Operator/ })).toBeVisible()
  releaseOpen?.()
  await expect(page.getByRole('region', { name: 'Company Example Energy' })).toHaveCount(0)
  await expect(page.getByText('Old search project')).toHaveCount(0)
})

test('synthetic delayed account project page cannot repopulate results after a search change', async ({ page }) => {
  let releaseChild: (() => void) | undefined
  let childRequested: (() => void) | undefined
  const requested = new Promise<void>(resolve => { childRequested = resolve })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => {
    const url = new URL(route.request().url())
    const fresh = Boolean(url.searchParams.get('search'))
    return route.fulfill({ json: { ...groupPage, cohort_token: fresh ? 'fresh-search-cohort' : 'old-search-cohort', items: [{ ...group, id: fresh ? 'fresh-group' : group.id, name: fresh ? 'Fresh Search Operator' : group.name }] } })
  })
  await page.route('**/api/opportunities/groups/group-synthetic-1/open?*', route => route.fulfill({ json: { group, projects: { ...projectPage, items: Array.from({ length: 25 }, (_, index) => ({ ...sample, id: `old-${index}` })), total: 50, cohort_token: 'old-search-child-cohort', valid_until: '2099-01-01T00:00:00Z' }, parent_cohort_token: 'old-search-parent', generation: 'old', valid_until: '2099-01-01T00:00:00Z' } }))
  await page.route('**/api/opportunities/groups/*/projects?*', async route => {
    childRequested?.()
    await new Promise<void>(resolve => { releaseChild = resolve })
    try {
      await route.fulfill({ json: { ...projectPage, cohort_token: 'old-search-child-cohort', items: [{ ...sample, id: 'old-search-project', name: 'Old search project' }] } })
    } catch { /* The browser correctly aborts this superseded request. */ }
  })
  await page.goto('/?groupBrowse=1&shortlist=0')
  await page.getByRole('button', { name: /Example Energy/ }).click()
  const account = page.getByRole('region', { name: 'Company Example Energy' })
  await account.getByRole('button', { name: 'Load more projects' }).click()
  await requested
  await account.getByRole('button', { name: 'Back to accounts' }).click()
  await page.getByRole('textbox', { name: 'Search accounts and projects' }).fill('fresh')
  await expect(page.getByRole('button', { name: /Fresh Search Operator/ })).toBeVisible()
  releaseChild?.()
  await expect(page.getByRole('region', { name: 'Company Example Energy' })).toHaveCount(0)
  await expect(page.getByText('Old search project')).toHaveCount(0)
})

test('account detail action is visible and usable on desktop and mobile', async ({ page }) => {
  const screenshotRoot = resolve(process.cwd(), '..', '.artifacts', 'release-operator-customer-20261027')
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: groupPage }))
  await page.route('**/api/opportunities/groups/group-synthetic-1/open?*', route => route.fulfill({ json: { group: { ...group, group_kind: 'resolved_identity' }, projects: projectPage, parent_cohort_token: 'parent', generation: 'current', valid_until: '2099-01-01T00:00:00Z' } }))
  await page.goto('/?groupBrowse=1&shortlist=0')
  const groupButton = page.getByRole('button', { name: /Example Energy/ })
  await expect.poll(() => groupButton.evaluate(element => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44)
  await groupButton.click()
  const account = page.getByRole('region', { name: 'Company Example Energy' })
  await expect(account).toBeVisible()
  await expect(account.getByRole('region', { name: 'Account projects' })).toBeVisible()
  await page.screenshot({ path: resolve(screenshotRoot, 'account-detail-desktop.png'), fullPage: true })

  await page.setViewportSize({ width: 390, height: 844 })
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  await expect.poll(() => account.getByRole('button', { name: 'Back to accounts' }).evaluate(element => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44)
  await expect.poll(() => account.locator('.cmp-project-links button').first().evaluate(element => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44)
  await expect.poll(() => account.locator('.cmp-projects details>summary').first().evaluate(element => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44)
  await page.screenshot({ path: resolve(screenshotRoot, 'account-detail-mobile.png'), fullPage: true })
  await account.getByRole('button', { name: 'Back to accounts' }).click()
  await expect(page.getByRole('button', { name: /Example Energy/ })).toBeVisible()
})

test('synthetic detail reloads the selected project by exact need and fails closed until retry', async ({ page }) => {
  let failPreparedRead = true
  const exactReads: URL[] = []
  const detailAccount = { ...group, id: 'cg_detail-synthetic', group_kind: 'resolved_identity' as const }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: { ...groupPage, items: [detailAccount] } }))
  await page.route('**/api/opportunities/groups/cg_detail-synthetic/open?*', route => route.fulfill({ json: { group: detailAccount, projects: { ...projectPage, valid_until: '2099-01-01T00:00:00Z' }, parent_cohort_token: 'parent', generation: 'current', valid_until: '2099-01-01T00:00:00Z' } }))
  await page.route('**/api/projects/project-synthetic-1/account', route => route.fulfill({ json: { ...detailAccount, project_id: 'project-synthetic-1' } }))
  await page.route('**/api/opportunities/projects?*', route => { const url = new URL(route.request().url()); if (url.searchParams.has('need_id')) { exactReads.push(url); if (failPreparedRead) return route.fulfill({ status: 503, json: { detail: 'Synthetic prepared read failure' } }) }; return route.fulfill({ json: { ...projectPage, valid_until: '2099-01-01T00:00:00Z', items: [{ ...sample, power_summary: 'Facility demand is source-supported at 120 MW; temporary bridge demand is not established.', power_summary_kind: 'facility_demand', contact: [{ kind: 'call', label: 'Call Example Energy', href: 'tel:+15555550100' }], contact_people: [{ record_type: 'contact_person', company: 'M/E Design LLC', name: 'Luis Sample', role: 'owner developer', source_url: 'https://example.test/owner' }] }] } }) })
  await page.route('**/api/opportunities/needs/need-synthetic-1*', route => route.fulfill({ json: { id: 'need-synthetic-1', project_id: 'project-synthetic-1', name: 'Stale internal title', activity: 'construction', tier: 'Signal', rationale: 'Internal diagnostic rationale must not appear in the landing detail.', evidence: [] } }))
  await page.goto('/?groupBrowse=1&shortlist=0')
  await page.getByRole('button', { name: /Example Energy/ }).click()
  const account = page.getByRole('region', { name: 'Company Example Energy' })
  await account.getByRole('button', { name: /Open project detail/ }).click()
  const detail = page.getByRole('complementary', { name: 'Opportunity detail' })
  await expect(detail.getByRole('alert')).toContainText('503')
  await expect(detail.getByText('Jordan Sample')).toHaveCount(0)
  await expect(detail.getByText(/Internal diagnostic rationale/)).toHaveCount(0)
  expect(exactReads.at(-1)?.searchParams.get('need_id')).toBe('need-synthetic-1')

  failPreparedRead = false
  await page.getByRole('button', { name: 'Retry' }).click()
  await expect(detail).toContainText('Example Compressor Station')
  await expect(detail).toContainText('No appropriate business phone or email is available in retained contact evidence.')
  await expect(detail.getByText(/Sources/)).toBeVisible()
  expect(exactReads.at(-1)?.searchParams.get('need_id')).toBe('need-synthetic-1')
  await expect(detail).not.toContainText('Internal diagnostic rationale')
  await expect(page.locator('.wh-customer-metrics')).toHaveCount(0)
})

test('synthetic tablet account project selection opens detail in the viewport', async ({ page }) => {
  await page.setViewportSize({ width: 768, height: 900 })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: { ...groupPage, items: [{ ...group, project_count: 25 }] } }))
  await page.route('**/api/opportunities/groups/group-synthetic-1/open?*', route => route.fulfill({ json: { group, projects: { ...projectPage, total: 25, items: Array.from({ length: 25 }, (_, index) => ({ ...sample, id: `tablet-${index}` })), valid_until: '2099-01-01T00:00:00Z' }, parent_cohort_token: 'parent', generation: 'current', valid_until: '2099-01-01T00:00:00Z' } }))
  await page.route('**/api/opportunities/projects?*', route => { const url = new URL(route.request().url()); return route.fulfill({ json: { ...projectPage, items: [{ ...sample, name: url.searchParams.has('need_id') ? 'Synthetic tablet well' : sample.name }] } }) })
  await page.route('**/api/opportunities/needs/need-synthetic-1*', route => route.fulfill({ json: {
    id: 'need-synthetic-1', project_id: 'project-synthetic-1', name: 'Synthetic tablet well',
    browse_title: 'Synthetic tablet well', location: 'Martin County, TX', tier: 'Signal',
    activity: 'drilling', supply: 'Unknown', required_mw: null, start_window: null, duration: null,
    evidence: [], missing_facts: [], rationale: 'Power demand is unconfirmed.',
  } }))
  await page.goto('/?view=workspace&sector=oil_gas&groupBrowse=1&shortlist=0')
  await page.getByRole('button', { name: /Example Energy/ }).click()
  const account = page.getByRole('region', { name: 'Company Example Energy' })
  await expect(account.locator('.cmp-projects li')).toHaveCount(25)
  await account.getByRole('button', { name: /Open project detail/ }).first().click()
  const detailTitle = page.locator('.cod-account-first-detail h2')
  await expect(detailTitle).toHaveText('Synthetic tablet well')
  await expect(account).toBeHidden()
  await expect(detailTitle).toBeInViewport()
  await page.getByRole('button', { name: '← Back to account' }).click()
  await expect(account.getByRole('heading', { name: 'Projects' })).toBeVisible()
})

test('pending parent groups wait for Retry-After then reopen the same filtered cohort', async ({ page }) => {
  await page.clock.install({ time: new Date('2026-10-29T11:59:00Z') })
  let pauseClock: Promise<void> | undefined
  const requests: URL[] = []
  let pending = true
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', async route => {
    // Let the app mount, then freeze before any browse response creates timers.
    // StrictMode handlers share one pause; wall-time assertions cannot age TTLs.
    await (pauseClock ??= page.clock.pauseAt(new Date('2026-10-29T12:00:00Z')))
    const url = new URL(route.request().url())
    requests.push(url)
    // StrictMode's cancelled mount request may never reach the route handler.
    // Response state is independent of how many initial requests were observed.
    if (pending) {
      return route.fulfill({
        status: 503,
        headers: { 'X-Qualification-State': 'pending', 'Retry-After': '5' },
        json: { detail: 'qualification pending' },
      })
    }
    return route.fulfill({ json: { ...groupPage, items: [{ ...group, name: 'Fresh parent group' }] } })
  })
  await page.goto('/?view=workspace&q=Permian&sector=oil_gas&groupBrowse=1&shortlist=0')
  await expect(page.getByRole('status')).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.getByRole('status').filter({ hasText: /still being prepared.*Retrying automatically/i })).toBeVisible()
  const initialRequests = requests.length
  expect(initialRequests).toBeGreaterThan(0)
  await page.clock.runFor(4999)
  expect(requests).toHaveLength(initialRequests)
  await expect(page.getByRole('alert')).toHaveCount(0)
  pending = false
  await page.clock.runFor(1)
  await expect.poll(() => requests.length).toBe(initialRequests + 1)
  await expect(page.getByRole('button', { name: /Fresh parent group/ })).toBeVisible()
  expect(requests.every(url => url.searchParams.get('search') === 'Permian')).toBe(true)
  expect(requests.every(url => url.searchParams.get('sector') === 'oil_gas')).toBe(true)
})

test('pending account detail open waits for Retry-After with the selected account and filters intact', async ({ page }) => {
  await page.clock.install({ time: new Date('2026-10-29T11:59:00Z') })
  const openRequests: URL[] = []
  let pending = true
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: groupPage }))
  await page.route('**/api/opportunities/groups/group-synthetic-1/open?*', route => {
    const url = new URL(route.request().url())
    openRequests.push(url)
    if (pending) return route.fulfill({ status: 503, headers: { 'X-Qualification-State': 'pending', 'Retry-After': '5' }, json: { detail: 'qualification pending' } })
    return route.fulfill({ json: {
      group: { ...group, name: 'Fresh Energy Customer', role: 'customer', project_count: 1 },
      projects: { ...projectPage, items: [{ ...sample, name: 'Freshly opened project' }], valid_until: '2099-01-01T00:00:00Z' },
      parent_cohort_token: 'fresh-parent-cohort',
      generation: 'fresh-generation',
      valid_until: '2099-01-01T00:00:00Z',
    } })
  })
  await page.goto('/?view=workspace&q=Permian&sector=oil_gas&groupBrowse=1&shortlist=0')
  await expect(page.getByRole('button', { name: /Example Energy/ })).toBeVisible()
  await page.clock.pauseAt(new Date('2026-10-29T12:00:00Z'))
  await page.getByRole('button', { name: /Example Energy/ }).click()
  await expect(page.getByText('Loading account details…')).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect.poll(() => openRequests.length).toBeGreaterThan(0)
  const initialRequests = openRequests.length
  await page.clock.runFor(4999)
  expect(openRequests).toHaveLength(initialRequests)
  pending = false
  await page.clock.runFor(1)
  await expect.poll(() => openRequests.length).toBe(initialRequests + 1)
  await expect(page.getByRole('region', { name: 'Company Fresh Energy Customer' }).locator('.cmp-projects li strong', { hasText: 'Freshly opened project' })).toBeVisible()
  expect(openRequests.every(url => url.pathname === '/api/opportunities/groups/group-synthetic-1/open')).toBe(true)
  expect(openRequests.every(url => url.searchParams.get('search') === 'Permian')).toBe(true)
  expect(openRequests.every(url => url.searchParams.get('sector') === 'oil_gas')).toBe(true)
  expect(openRequests.every(url => url.searchParams.get('shortlist') === 'false')).toBe(true)
  expect(openRequests.every(url => !url.searchParams.has('parent_cohort_token') && !url.searchParams.has('cohort_token') && !url.searchParams.has('offset'))).toBe(true)
})

test('account project conflict reopens atomically and pending recovery retries with the fresh parent token', async ({ page }) => {
  await page.clock.install({ time: new Date('2030-01-01T00:00:00Z') })
  const pageRequests: URL[] = []
  const openRequests: URL[] = []
  let conflictStarted = false
  let pendingOpen = true
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: { ...groupPage, cohort_token: 'parent-list-cohort' } }))
  await page.route('**/api/opportunities/groups/group-synthetic-1/projects?*', route => {
    const url = new URL(route.request().url()); pageRequests.push(url)
    if (!conflictStarted && url.searchParams.get('offset') === '25') { conflictStarted = true; return route.fulfill({ status: 409, json: { detail: 'parent cohort changed' } }) }
    return route.fulfill({ json: { ...projectPage, items: [{ ...sample, id: 'fresh-page', name: 'Fresh recovery page' }], total: 30, offset: 25, cohort_token: 'fresh-child-token', valid_until: '2099-01-01T00:00:00Z' } })
  })
  await page.route('**/api/opportunities/groups/group-synthetic-1/open?*', route => {
    const url = new URL(route.request().url())
    openRequests.push(url)
    if (conflictStarted && pendingOpen) return route.fulfill({ status: 503, headers: { 'X-Qualification-State': 'pending', 'Retry-After': '5' }, json: { detail: 'qualification pending' } })
    return route.fulfill({ json: {
      group: { ...group, name: 'Fresh atomic customer', role: 'customer', project_count: 30 },
      projects: { ...projectPage, items: Array.from({ length: 25 }, (_, index) => ({ ...sample, id: conflictStarted ? `fresh-${index}` : `old-${index}`, name: conflictStarted ? `Fresh project ${index + 1}` : `Old project ${index + 1}` })), total: 30, cohort_token: conflictStarted ? 'fresh-child-token' : 'old-child-token', valid_until: '2099-01-01T00:00:00Z' },
      parent_cohort_token: conflictStarted ? 'fresh-parent-token' : 'old-parent-token',
      generation: 'fresh-generation',
      valid_until: '2099-01-01T00:00:00Z',
    } })
  })
  await page.goto('/?view=workspace&q=Permian&groupBrowse=1&shortlist=0')
  await expect(page.getByRole('button', { name: /Example Energy/ })).toBeVisible()
  // Freeze the clock before the pending open creates its Retry-After timer so
  // test setup and route handling cannot consume part of the 5-second window.
  await page.clock.pauseAt(new Date('2030-01-01T00:01:00Z'))
  await page.getByRole('button', { name: /Example Energy/ }).click()
  const account = page.getByRole('region', { name: 'Company Fresh atomic customer' })
  await expect(account.locator('.cmp-projects li')).toHaveCount(25)
  await account.getByRole('button', { name: 'Load more projects' }).click()
  await expect.poll(() => pageRequests.some(url => url.searchParams.get('offset') === '25')).toBe(true)
  await expect.poll(() => openRequests.length).toBeGreaterThan(1)
  await expect(page.getByRole('alert')).toHaveCount(0)
  await page.clock.fastForward(4999)
  expect(openRequests.length).toBeGreaterThan(1)
  const requestsBeforeRetry = openRequests.length
  pendingOpen = false
  await page.clock.fastForward(1)
  await expect.poll(() => openRequests.length).toBe(requestsBeforeRetry + 1)
  await expect(account.locator('.cmp-projects li')).toHaveCount(26)
  expect(pageRequests.at(-1)?.searchParams.get('cohort_token')).toBe('fresh-child-token')
  expect(pageRequests.at(-1)?.searchParams.get('parent_cohort_token')).toBe('fresh-parent-token')
  expect(openRequests.slice(-2).every(url => url.pathname.endsWith('/group-synthetic-1/open') && !url.searchParams.has('parent_cohort_token') && !url.searchParams.has('cohort_token') && !url.searchParams.has('offset'))).toBe(true)
  await account.getByRole('button', { name: 'Back to accounts' }).click()
  // Parent list context is only sent when the user pages the account list;
  // this route starts on page one and should not acquire a child project token.
  expect(new URL(page.url()).searchParams.has('cohort_token')).toBe(false)
})

test('parent pending retries stop after four active reads and manual retry starts over', async ({ page }) => {
  await page.clock.install({ time: new Date('2026-10-29T11:59:00Z') })
  let pauseClock: Promise<void> | undefined
  let requests = 0
  let pending = true
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', async route => {
    // Let the app mount, then freeze before any browse response creates timers.
    // StrictMode handlers share one pause; wall-time assertions cannot age TTLs.
    await (pauseClock ??= page.clock.pauseAt(new Date('2026-10-29T12:00:00Z')))
    requests += 1
    if (pending) {
      return route.fulfill({
        status: 503,
        headers: { 'X-Qualification-State': 'pending', 'Retry-After': '1' },
        json: { detail: 'qualification pending' },
      })
    }
    return route.fulfill({ json: groupPage })
  })
  await page.goto('/?groupBrowse=1&shortlist=0')
  await expect(page.getByRole('status')).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.getByRole('status').filter({ hasText: /still being prepared.*Retrying automatically/i })).toBeVisible()
  const initialRequests = requests
  expect(initialRequests).toBeGreaterThan(0)
  for (let retry = 1; retry <= 2; retry += 1) {
    // Advance the paused clock through each retry deadline, processing due
    // callbacks while the surrounding assertions leave virtual time unchanged.
    await page.clock.runFor(1000)
    await expect.poll(() => requests).toBe(initialRequests + retry)
    await expect(page.getByRole('alert')).toHaveCount(0)
  }
  await page.clock.runFor(1000)
  await expect.poll(() => requests).toBe(initialRequests + 3)
  await expect(page.getByRole('alert')).toContainText(/still being prepared/i)
  await expect(page.getByRole('status').filter({ hasText: /Retrying automatically/i })).toHaveCount(0)
  await page.clock.runFor(30000)
  expect(requests).toBe(initialRequests + 3)
  pending = false
  await page.getByRole('button', { name: /Retry|Reload/i }).last().click()
  await expect(page.getByRole('button', { name: /Example Energy/ })).toBeVisible()
  expect(requests).toBe(initialRequests + 4)
})

const generic503Variants: { name: string; headers: Record<string, string> }[] = [
  { name: 'without headers', headers: {} },
  {
    name: 'with current and Retry-After headers',
    headers: { 'X-Qualification-State': 'current', 'Retry-After': '5' },
  },
]
for (const variant of generic503Variants) {
  test(`generic 503 ${variant.name} is not pending and does not auto-retry`, async ({ page }) => {
    await page.clock.install()
    let requests = 0
    let failing = true
    await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
    await page.route('**/api/opportunities/groups?*', route => {
      requests += 1
      if (failing) {
        return route.fulfill({
          status: 503,
          headers: variant.headers,
          json: { detail: 'temporarily unavailable' },
        })
      }
      return route.fulfill({ json: groupPage })
    })
    await page.goto('/?groupBrowse=1&shortlist=0')
    await expect(page.getByRole('alert')).toContainText('Could not load accounts')
    await page.waitForLoadState('networkidle')
    const initialRequests = requests
    expect(initialRequests).toBeGreaterThan(0)
    await page.clock.fastForward(30000)
    expect(requests).toBe(initialRequests)
    failing = false
    await page.getByRole('button', { name: 'Retry' }).click()
    await expect(page.getByRole('button', { name: /Example Energy/ })).toBeVisible()
    expect(requests).toBe(initialRequests + 1)
  })
}

test('pending parent retry timer is cancelled when a new search supersedes it', async ({ page }) => {
  await page.clock.install()
  const requests: URL[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => {
    const url = new URL(route.request().url())
    requests.push(url)
    if (!url.searchParams.has('search')) {
      return route.fulfill({
        status: 503,
        headers: { 'X-Qualification-State': 'pending', 'Retry-After': '5' },
        json: { detail: 'qualification pending' },
      })
    }
    return route.fulfill({ json: { ...groupPage, items: [{ ...group, name: 'Superseding search result' }] } })
  })
  await page.goto('/?groupBrowse=1&shortlist=0')
  await expect(page.getByRole('status').filter({ hasText: /still being prepared.*Retrying automatically/i })).toBeVisible()
  const initialPendingRequests = requests.length
  expect(initialPendingRequests).toBeGreaterThan(0)
  await page.getByRole('textbox', { name: 'Search accounts and projects' }).fill('fresh')
  await expect(page.getByRole('button', { name: /Superseding search result/ })).toBeVisible()
  expect(requests).toHaveLength(initialPendingRequests + 1)
  await page.clock.fastForward(5000)
  expect(requests).toHaveLength(initialPendingRequests + 1)
  expect(requests.slice(0, initialPendingRequests).every(url => !url.searchParams.has('search'))).toBe(true)
  expect(requests[initialPendingRequests].searchParams.get('search')).toBe('fresh')
  await expect(page.getByRole('button', { name: /Superseding search result/ })).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('switching away from an account cancels its pending project-page retry', async ({ page }) => {
  await page.clock.install()
  const pageReads: URL[] = []
  const first = { ...group, id: 'group-synthetic-1', name: 'Example Energy' }
  const second = { ...group, id: 'group-synthetic-2', name: 'Second Energy' }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: { ...groupPage, items: [first, second] } }))
  await page.route('**/api/opportunities/groups/group-synthetic-1/projects?*', route => {
    const url = new URL(route.request().url()); pageReads.push(url)
    return route.fulfill({ status: 503, headers: { 'X-Qualification-State': 'pending', 'Retry-After': '5' }, json: { detail: 'qualification pending' } })
  })
  await page.route('**/api/opportunities/groups/*/open?*', route => {
    const id = new URL(route.request().url()).pathname.split('/').at(-2)!
    const selected = id === first.id ? first : second
    return route.fulfill({ json: { group: selected, projects: { ...projectPage, items: Array.from({ length: 25 }, (_, index) => ({ ...sample, id: `${id}-${index}`, name: `${selected.name} project ${index + 1}` })), total: 50, cohort_token: `${id}-child`, valid_until: '2099-01-01T00:00:00Z' }, parent_cohort_token: `${id}-parent`, generation: 'fresh-generation', valid_until: '2099-01-01T00:00:00Z' } })
  })
  await page.goto('/?groupBrowse=1&shortlist=0')
  await page.getByRole('button', { name: /Example Energy/ }).click()
  const firstAccount = page.getByRole('region', { name: 'Company Example Energy' })
  await firstAccount.getByRole('button', { name: 'Load more projects' }).click()
  await expect.poll(() => pageReads.length).toBe(1)
  await expect(firstAccount.getByRole('button', { name: 'Loading…' })).toBeDisabled()
  await firstAccount.getByRole('button', { name: 'Back to accounts' }).click()
  await page.getByRole('button', { name: /Second Energy/ }).click()
  const secondAccount = page.getByRole('region', { name: 'Company Second Energy' })
  await expect(secondAccount.locator('.cmp-projects li strong').first()).toHaveText('Second Energy project 1')
  await page.clock.fastForward(5000)
  expect(pageReads).toHaveLength(1)
  await expect(secondAccount.locator('.cmp-projects li strong').first()).toHaveText('Second Energy project 1')
  await expect(page.getByRole('region', { name: 'Company Example Energy' })).toHaveCount(0)
})

test('pending shared account detail retries are bounded and manual retry starts a new cycle', async ({ page }) => {
  await page.clock.install()
  let openReads = 0
  let pending = true
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: groupPage }))
  await page.route('**/api/opportunities/groups/group-synthetic-1/open?*', route => {
    openReads += 1
    if (pending) return route.fulfill({ status: 503, headers: { 'X-Qualification-State': 'pending', 'Retry-After': '1' }, json: { detail: 'qualification pending' } })
    return route.fulfill({ json: {
      group,
      projects: { ...projectPage, items: [{ ...sample, name: 'Manually retried project' }], valid_until: '2099-01-01T00:00:00Z' },
      parent_cohort_token: 'fresh-parent-token',
      generation: 'fresh-generation',
      valid_until: '2099-01-01T00:00:00Z',
    } })
  })
  await page.goto('/?groupBrowse=1&shortlist=0')
  await page.getByRole('button', { name: /Example Energy/ }).click()
  await expect.poll(() => openReads).toBeGreaterThan(0)
  await expect(page.getByRole('alert')).toHaveCount(0)
  await page.waitForLoadState('networkidle')
  const initialReads = openReads
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    await page.clock.fastForward(1000)
    await expect.poll(() => openReads).toBe(initialReads + attempt)
    if (attempt < 3) await expect(page.getByRole('alert')).toHaveCount(0)
  }
  const account = page.getByRole('region', { name: 'Company Example Energy' })
  await expect(account.getByRole('alert')).toContainText(/still being prepared/i)
  await page.clock.fastForward(30000)
  expect(openReads).toBe(initialReads + 3)
  pending = false
  await account.getByRole('button', { name: 'Retry' }).click()
  await expect(account.locator('.cmp-projects li strong', { hasText: 'Manually retried project' })).toBeVisible()
  expect(openReads).toBe(initialReads + 4)
})

test('selecting another account cancels the previous account-detail retry', async ({ page }) => {
  await page.clock.install()
  const first = group
  const second = { ...group, id: 'group-synthetic-2', name: 'Second Energy', project_count: 2 }
  const openReads: URL[] = []
  let firstPending = true
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: { ...groupPage, items: [first, second] } }))
  await page.route('**/api/opportunities/groups/*/open?*', route => {
    const url = new URL(route.request().url())
    const groupId = url.pathname.split('/').at(-2)!
    openReads.push(url)
    if (groupId === first.id && firstPending) return route.fulfill({ status: 503, headers: { 'X-Qualification-State': 'pending', 'Retry-After': '5' }, json: { detail: 'qualification pending' } })
    return route.fulfill({ json: {
      group: groupId === second.id ? second : first,
      projects: { ...projectPage, valid_until: '2099-01-01T00:00:00Z' },
      parent_cohort_token: 'fresh-parent-token',
      generation: 'fresh-generation',
      valid_until: '2099-01-01T00:00:00Z',
    } })
  })
  await page.goto('/?groupBrowse=1&shortlist=0')
  await page.getByRole('button', { name: /Example Energy/ }).click()
  const firstAccount = page.getByRole('region', { name: 'Company Example Energy' })
  await expect(firstAccount.getByText('Loading account details…')).toBeVisible()
  await expect.poll(() => openReads.length).toBeGreaterThan(0)
  await firstAccount.getByRole('button', { name: 'Back to accounts' }).click()
  firstPending = false
  await page.getByRole('button', { name: /Second Energy/ }).click()
  const secondAccount = page.getByRole('region', { name: 'Company Second Energy' })
  await expect(secondAccount.getByRole('heading', { name: 'Projects' })).toBeVisible()
  const readsAfterSecondAccount = openReads.length
  expect(openReads.at(-1)?.pathname.split('/').at(-2)).toBe(second.id)
  await page.clock.fastForward(5000)
  expect(openReads).toHaveLength(readsAfterSecondAccount)
  await expect(secondAccount.getByRole('heading', { name: 'Projects' })).toBeVisible()
})

test('leaving opportunities during pending account detail cancels the retry timer', async ({ page }) => {
  await page.clock.install()
  let openReads = 0
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: groupPage }))
  await page.route('**/api/opportunities?*', route => route.fulfill({ json: [] }))
  await page.route('**/api/opportunities/groups/group-synthetic-1/open?*', route => {
    openReads += 1
    return route.fulfill({
      status: 503,
      headers: { 'X-Qualification-State': 'pending', 'Retry-After': '5' },
      json: { detail: 'qualification pending' },
    })
  })
  await page.goto('/?groupBrowse=1&shortlist=0')
  await page.getByRole('button', { name: /Example Energy/ }).click()
  await expect(page.getByRole('region', { name: 'Company Example Energy' }).getByText('Loading account details…')).toBeVisible()
  await expect.poll(() => openReads).toBeGreaterThan(0)
  const readsBeforeNavigation = openReads
  // Navigation unmounts account detail while preserving the browser realm and timer.
  await page.locator('.wh-account summary').click()
  await page.getByRole('button', { name: 'Signals', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Signals' })).toBeVisible()
  await page.clock.fastForward(5000)
  expect(openReads).toBe(readsBeforeNavigation)
})

test('rapid project searches debounce and an older response cannot replace the newest results', async ({ page }) => {
  let releaseOld: (() => void) | undefined
  let oldRequested: (() => void) | undefined
  const oldStarted = new Promise<void>(resolve => { oldRequested = resolve })
  const searches: string[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', async route => {
    const url = new URL(route.request().url()), query = url.searchParams.get('search') ?? ''
    searches.push(query)
    if (query === 'seed') return route.fulfill({ json: groupPage })
    if (query === 'Dia') {
      oldRequested?.()
      await new Promise<void>(resolve => { releaseOld = resolve })
      try { await route.fulfill({ json: { ...groupPage, items: [{ ...group, id: 'old-search-group', name: 'Old search result' }] } }) } catch { /* Search superseded this response. */ }
      return
    }
    return route.fulfill({ json: { ...groupPage, items: [{ ...group, id: 'diamondback-group', name: 'Diamondback Operator' }] } })
  })
  await page.goto('/?q=seed&groupBrowse=1&shortlist=0')
  await expect(page.getByRole('button', { name: /Example Energy/ })).toBeVisible()
  const diaRequest = page.waitForRequest(request => new URL(request.url()).searchParams.get('search') === 'Dia')
  const input = page.getByRole('textbox', { name: 'Search accounts and projects' })
  await input.fill('D')
  await input.fill('Di')
  await input.fill('Dia')
  await diaRequest
  await oldStarted
  const latestRequest = page.waitForRequest(request => new URL(request.url()).searchParams.get('search') === 'Diamondback')
  await input.fill('Diamondback')
  await expect(page.getByRole('status')).toContainText('Updating account search')
  await expect(page.locator('.customer-group-list')).toHaveCount(0)
  await latestRequest
  await expect(page.getByRole('button', { name: /Diamondback Operator/ })).toBeVisible()
  releaseOld?.()
  await expect(page.getByRole('button', { name: /Diamondback Operator/ })).toBeVisible()
  await expect(page.getByText('Old search result')).toHaveCount(0)
  expect(searches.filter(value => ['D', 'Di'].includes(value))).toEqual([])
})

test('returning to a cached search shows only that cohort while its fresh read is pending', async ({ page }) => {
  let holdSeed = false
  let releaseSeed!: () => void
  let seedPending = Promise.resolve()
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', async route => {
    const query = new URL(route.request().url()).searchParams.get('search') ?? ''
    if (query === 'seed' && holdSeed) await seedPending
    const item = query === 'seed'
      ? { ...group, id: 'cached-seed-group', name: 'Cached Seed Group' }
      : { ...group, id: 'other-search-group', name: 'Other Search Group' }
    await route.fulfill({ json: { ...groupPage, items: [item], total: 1, cohort_token: `${query || 'empty'}-search-cohort` } })
  })
  await page.goto('/?q=seed&groupBrowse=1&shortlist=0')
  await expect(page.getByRole('button', { name: /Cached Seed Group/ })).toBeVisible()
  const input = page.getByRole('textbox', { name: 'Search accounts and projects' })
  await input.fill('other')
  await expect(page.getByRole('button', { name: /Other Search Group/ })).toBeVisible()
  holdSeed = true
  seedPending = new Promise<void>(resolveSeed => { releaseSeed = resolveSeed })
  await input.fill('seed')
  await expect(page.getByRole('status')).toContainText('Refreshing accounts')
  await expect(page.getByRole('button', { name: /Cached Seed Group/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /Other Search Group/ })).toHaveCount(0)
  releaseSeed()
  await expect(page.locator('.project-results')).toHaveAttribute('aria-busy', 'false')
  await expect(page.getByRole('button', { name: /Cached Seed Group/ })).toBeVisible()
})

test('refresh keeps the rendered cohort labeled as updating and clears it when the filter changes', async ({ page }) => {
  let refresh = false
  let releaseDataCenters: (() => void) | undefined
  let dataCentersRequested: (() => void) | undefined
  const dataCentersStarted = new Promise<void>(resolve => { dataCentersRequested = resolve })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', async route => {
    const url = new URL(route.request().url())
    if (refresh && url.searchParams.get('sector') !== 'data_centers') return route.fulfill({ status: 503, headers: { 'X-Qualification-State': 'pending', 'Retry-After': '60' }, json: { detail: 'qualification pending' } })
    if (url.searchParams.get('sector') === 'data_centers') {
      dataCentersRequested?.()
      await new Promise<void>(resolve => { releaseDataCenters = resolve })
      return route.fulfill({ json: { ...groupPage, items: [{ ...group, id: 'dc-group', name: 'Data Center Owner' }], total: 1 } })
    }
    return route.fulfill({ json: { ...groupPage, as_of: '2026-10-29T15:00:00Z', generation_id: 'synthetic-current-generation', qualification_state: 'current', refresh_state: 'current' } })
  })
  await page.goto('/?groupBrowse=1&shortlist=0')
  await expect(page.getByRole('button', { name: /Example Energy/ })).toBeVisible()
  refresh = true
  await page.getByRole('button', { name: 'Refresh customer accounts' }).click()
  await expect(page.getByRole('status')).toContainText('Retrying automatically')
  await expect(page.getByRole('button', { name: /Example Energy/ })).toBeVisible()
  await page.getByRole('button', { name: 'Data Centers' }).click()
  await dataCentersStarted
  await expect(page.getByRole('status')).toContainText('Refreshing accounts; previous results are hidden.')
  await expect(page.locator('.customer-group-list')).toHaveCount(0)
  releaseDataCenters?.()
  await expect(page.getByRole('button', { name: /Data Center Owner/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /Example Energy/ })).toHaveCount(0)
})

test('account detail survives More-menu navigation and returns to the same browse context', async ({ page }) => {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: groupPage }))
  await page.route('**/api/opportunities/groups/group-synthetic-1/open?*', route => route.fulfill({ json: { group, projects: projectPage, parent_cohort_token: 'browse-parent', generation: 'current', valid_until: '2099-01-01T00:00:00Z' } }))
  await page.route('**/api/opportunities?*', route => route.fulfill({ json: [] }))
  await page.goto('/?q=Diamondback&sector=oil_gas&groupBrowse=1&shortlist=0')
  await page.getByRole('button', { name: /Example Energy/ }).click()
  const account = page.getByRole('region', { name: 'Company Example Energy' })
  await expect(account.locator('.cmp-projects li strong', { hasText: /^Example Compressor Station$/ })).toBeVisible()
  expect(new URL(page.url()).searchParams.get('account')).toBe('group-synthetic-1')
  await page.locator('.wh-account summary').click()
  await page.getByRole('button', { name: 'Signals', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Signals' })).toBeVisible()
  await page.locator('.wh-account summary').click()
  await page.getByRole('button', { name: 'Opportunities', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Company Example Energy' }).getByRole('heading', { name: 'Projects' })).toBeVisible()
  expect(new URL(page.url()).searchParams.get('q')).toBe('Diamondback')
  expect(new URL(page.url()).searchParams.get('account')).toBe('group-synthetic-1')
  expect(new URL(page.url()).searchParams.get('sector')).toBe('oil_gas')
  await expect(page.locator('.cmp-projects li')).toHaveCount(1)
  await expect(page.locator('.wh-account[open]')).toHaveCount(0)
})

test('Signals and source health distinguish a loading request from terminal unavailability', async ({ page }) => {
  let failSignals = false
  let releaseHealth: (() => void) | undefined
  let healthRequested: (() => void) | undefined
  const healthStarted = new Promise<void>(resolve => { healthRequested = resolve })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities?*', route => failSignals ? route.fulfill({ status: 503, json: { detail: 'Signals workspace unavailable' } }) : route.fulfill({ json: [] }))
  await page.route('**/api/health', async route => {
    healthRequested?.()
    await new Promise<void>(resolve => { releaseHealth = resolve })
    return route.fulfill({ status: 503, json: { detail: 'Health unavailable' } })
  })
  await page.route('**/api/ingestion?*', route => route.fulfill({ json: { items: [], total: 0, limit: 25, offset: 0 } }))
  failSignals = true
  await page.goto('/?view=signals')
  await expect(page.getByText('Loading Signals…')).toHaveCount(0)
  await expect(page.getByText('Signals unavailable')).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('503')
  await expect(page.getByRole('status').filter({ hasText: 'Loading current Signal cohort' })).toHaveCount(0)
  await page.goto('/?view=ingestion')
  await healthStarted
  await expect(page.getByText('Loading source health…')).toBeVisible()
  releaseHealth?.()
  await expect(page.getByText('Source health unavailable').first()).toBeVisible()
  await expect(page.getByText('Loading source health…')).toHaveCount(0)
})

test('source health labels latest check separately from recent schedule freshness', async ({ page }) => {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/health', route => route.fulfill({ json: {
    backlog: 0,
    pending_interpretations: 0,
    sources: [{ id: 'houston-building-permits', status: 'Checked—No Change', enabled: true, freshness: 'FAILED', last_attempt: null, last_success: null, new_records: 0, changed_records: 0, parse_failures: 0 }],
  } }))
  await page.route('**/api/ingestion?*', route => route.fulfill({ json: { items: [], total: 0, limit: 25, offset: 0 } }))
  await page.goto('/?view=ingestion')

  const source = page.locator('.wh-source-row').filter({ hasText: 'houston-building-permits' })
  await expect(source.locator('span')).toContainText('Latest check: Checked—No Change')
  await expect(source.locator('span')).toContainText('Schedule freshness: FAILED')
  await expect(source.getByText('Schedule freshness summarizes recent schedule history and can differ from the latest check when earlier outcomes differ.')).toBeVisible()
})

test('source health preserves unknown outcome values when a partial payload omits them', async ({ page }) => {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/health', route => route.fulfill({ json: {
    backlog: 0,
    pending_interpretations: 0,
    sources: [{ id: 'city-permits' }],
  } }))
  await page.route('**/api/ingestion?*', route => route.fulfill({ json: { items: [], total: 0, limit: 25, offset: 0 } }))
  await page.goto('/?view=ingestion')

  const source = page.locator('.wh-source-row').filter({ hasText: 'city-permits' })
  await expect(source.locator('span')).toHaveText('Latest check: Unknown · Unknown · Schedule freshness: Unknown')
  await expect(source.getByText('Schedule freshness summarizes recent schedule history and can differ from the latest check when earlier outcomes differ.')).toHaveCount(0)
})

test('a session failure removes the cached browse surface before a later return', async ({ page }) => {
  let groupReads = 0
  let expireSession = false
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route(url => new URL(url).pathname === '/api/opportunities/groups', route => {
    groupReads += 1
    return expireSession ? route.fulfill({ status: 401, json: { detail: 'Authentication required' } }) : route.fulfill({ json: groupPage })
  })
  await page.route(url => new URL(url).pathname === '/api/opportunities', route => route.fulfill({ json: [] }))
  await page.goto('/?groupBrowse=1&shortlist=0')
  await expect(page.getByRole('button', { name: /Example Energy/ })).toBeVisible()
  const initialGroupReads = groupReads
  expireSession = true
  await page.getByRole('button', { name: 'Refresh customer accounts' }).click()
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await expect.poll(() => groupReads).toBeGreaterThan(initialGroupReads)
  await expect(page.getByRole('button', { name: /Example Energy/ })).toHaveCount(0)
  await expect(page).toHaveURL(/groupBrowse=1/)
})

test('a session expiry from Signals clears the browse cache while results are unmounted', async ({ page }) => {
  let groupReads = 0
  let expireSession = false
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route(url => new URL(url).pathname === '/api/opportunities/groups', route => {
    groupReads += 1
    return route.fulfill({ json: groupPage })
  })
  await page.route(url => new URL(url).pathname === '/api/opportunities', route => expireSession ? route.fulfill({ status: 401, json: { detail: 'Authentication required' } }) : route.fulfill({ json: [] }))
  await page.goto('/?groupBrowse=1&shortlist=0')
  await expect(page.getByRole('button', { name: /Example Energy/ })).toBeVisible()
  await page.locator('.wh-account summary').click()
  expireSession = true
  await page.getByRole('button', { name: 'Signals', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await expect(page.getByRole('button', { name: /Example Energy/ })).toHaveCount(0)
  await expect(page).toHaveURL(/view=signals/)
  expect(groupReads).toBeGreaterThan(0)
})

test('cached browse context expires at the backend valid-until boundary', async ({ page }) => {
  await page.clock.install({ time: new Date('2026-10-29T11:59:00Z') })
  let pauseClock: Promise<void> | undefined
  let groupReads = 0
  let expired = false
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', async route => {
    // Let the app mount, then freeze before any browse response creates timers.
    // StrictMode handlers share one pause; wall-time assertions cannot age TTLs.
    await (pauseClock ??= page.clock.pauseAt(new Date('2026-10-29T12:00:00Z')))
    groupReads += 1
    const name = expired ? 'Current after generation expiry' : 'Before generation expiry'
    const validUntil = expired ? '2026-10-29T12:01:00Z' : '2026-10-29T12:00:02Z'
    return route.fulfill({ json: { ...groupPage, items: [{ ...group, id: `expiry-${groupReads}`, name }], as_of: '2026-10-29T11:59:00Z', valid_until: validUntil, qualification_state: 'current', refresh_state: 'current' } })
  })
  await page.goto('/?groupBrowse=1&shortlist=0')
  await expect(page.getByRole('button', { name: /Before generation expiry/ })).toBeVisible()
  // Cross the server expiry while keeping network/render waits outside the
  // virtual clock. The initial generation always gets its full two-second TTL.
  const initialReads = groupReads
  expired = true
  await page.clock.runFor(2_100)
  await expect(page.getByRole('button', { name: /Current after generation expiry/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /Before generation expiry/ })).toHaveCount(0)
  expect(groupReads).toBeGreaterThan(initialReads)
})

test('mounted account project details and contacts disappear at their independent generation expiry', async ({ page }) => {
  await page.clock.install({ time: new Date('2026-10-29T12:00:00Z') })
  let openReads = 0
  let freshGeneration = false
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: { ...groupPage, as_of: '2026-10-29T11:59:00Z', valid_until: '2026-10-29T12:00:20Z', qualification_state: 'current', refresh_state: 'current' } }))
  await page.route('**/api/opportunities/groups/group-synthetic-1/open?*', route => {
    openReads += 1
    const validUntil = freshGeneration ? '2026-10-29T12:00:20Z' : '2026-10-29T12:00:02Z'
    const name = freshGeneration ? 'Current buyer' : 'Expired buyer'
    return route.fulfill({ json: { group: { ...group, group_kind: 'resolved_identity' }, projects: { ...projectPage, valid_until: validUntil, qualification_state: 'current', refresh_state: 'current', items: [{ ...sample, contact: [{ kind: 'call', label: 'Call business contact', name, href: 'tel:+15555550100' }] }] }, parent_cohort_token: 'parent', generation: `account-${openReads}`, valid_until: '2026-10-29T12:00:20Z', qualification_state: 'current', refresh_state: 'current' } })
  })
  await page.goto('/?groupBrowse=1&shortlist=0')
  const groupButton = page.getByRole('button', { name: /Example Energy/ })
  await groupButton.click()
  const account = page.getByRole('region', { name: 'Company Example Energy' })
  await expect(page.getByRole('link', { name: 'Call Expired buyer' })).toBeVisible()
  freshGeneration = true
  await page.clock.fastForward(2_100)
  await expect(page.getByRole('link', { name: 'Call Expired buyer' })).toHaveCount(0)
  await expect(account.getByRole('link', { name: 'Call Current buyer' })).toBeVisible()
  expect(openReads).toBeGreaterThan(1)
  expect(new URL(page.url()).searchParams.get('account')).toBe('group-synthetic-1')
})

test('an already expired account project snapshot stays hidden while retaining the account scope', async ({ page }) => {
  await page.clock.install({ time: new Date('2026-10-29T12:00:00Z') })
  let openReads = 0
  let freshSnapshot = false
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: { ...groupPage, as_of: '2026-10-29T11:59:00Z', valid_until: '2026-10-29T12:00:20Z', qualification_state: 'current', refresh_state: 'current' } }))
  await page.route('**/api/opportunities/groups/group-synthetic-1/open?*', route => {
    openReads += 1
    const name = freshSnapshot ? 'Current cached buyer' : 'Expired cached buyer'
    const validUntil = freshSnapshot ? '2026-10-29T12:10:00Z' : '2026-10-29T11:59:59Z'
    return route.fulfill({ json: { group: { ...group, group_kind: 'resolved_identity' }, projects: { ...projectPage, valid_until: validUntil, qualification_state: 'current', refresh_state: 'current', items: [{ ...sample, contact: [{ kind: 'call', label: 'Call business contact', name, href: 'tel:+15555550100' }] }] }, parent_cohort_token: 'parent', generation: 'account', valid_until: '2026-10-29T12:10:00Z', qualification_state: 'current', refresh_state: 'current' } })
  })
  await page.goto('/?groupBrowse=1&shortlist=0')
  await page.getByRole('button', { name: /Example Energy/ }).click()
  const account = page.getByRole('region', { name: 'Company Example Energy' })
  await expect(account.getByRole('alert')).toContainText('expired')
  await expect(account.getByRole('link', { name: 'Call Expired cached buyer' })).toHaveCount(0)
  expect(new URL(page.url()).searchParams.get('account')).toBe('group-synthetic-1')
  const readsBeforeWait = openReads
  await page.clock.fastForward(30000)
  expect(openReads).toBe(readsBeforeWait)
  await expect(account.getByRole('alert')).toContainText('expired')
  freshSnapshot = true
  await account.getByRole('button', { name: 'Retry' }).click()
  await expect(account.getByRole('link', { name: 'Call Current cached buyer' })).toBeVisible()
  expect(openReads).toBeGreaterThan(1)
})
