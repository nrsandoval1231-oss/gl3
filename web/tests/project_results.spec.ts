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
const groupPage = { items: [group], total: 1, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'synthetic-group-cohort', generation: '1' }

test('default root and header navigation browse customer groups with project children and server-side cohort controls', async ({ page }) => {
  const parentRequests: URL[] = []
  const childRequests: URL[] = []
  const demandScopes: string[] = []
  const customers = Array.from({ length: 26 }, (_, index) => ({
    ...group,
    id: index === 0 ? 'cross-sector-customer' : index === 25 ? 'filter-edge-customer' : `customer-${index}`,
    name: index === 0 ? 'Cross Sector Customer' : index === 25 ? 'Filter Edge Customer' : `Customer ${String(index).padStart(2, '0')}`,
    role: 'customer',
    project_count: index === 0 ? 2 : 1,
    priority_score: index === 0 ? 88 : index === 25 ? 77 : null,
    sectors: index === 0 ? ['oil_gas', 'data_centers'] : ['oil_gas'],
  }))
  const childProjects = [
    { ...sample, id: 'dc-project', project_id: 'dc-project', name: 'Customer Data Center', company: 'Cross Sector Customer', sector: 'data_centers', location: 'Austin, TX', event: { ...sample.event, kind: 'construction_notice', label: 'Construction notice' } },
    { ...sample, id: 'oil-project', project_id: 'oil-project', name: 'Customer Oil Field', company: 'Cross Sector Customer', sector: 'oil_gas', location: 'Permian Basin, TX' },
  ]
  const edgeProject = {
    ...sample, id: 'filter-edge-project', project_id: 'filter-edge-project', customer_identity_id: 'filter-edge-company',
    name: 'Filter Edge Site', company: 'Filter Edge Customer', representative_need_id: 'need-filter-edge',
    needs: [{ id: 'need-filter-edge', project_id: 'filter-edge-project', browse_title: 'Filter Edge Site', location: 'Austin, TX', activity: 'construction', tier: 'Signal' }],
    need_count: 1, contact_people: [], contact: [{ kind: 'call', label: 'Call Filter Edge Customer', href: 'tel:+15555550125', company: 'Filter Edge Customer' }],
  }
  let parentToken = 'default-customer-cohort'
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/demand-summary?*', route => {
    const sector = new URL(route.request().url()).searchParams.get('sector') ?? 'all'
    demandScopes.push(sector)
    return route.fulfill({ json: { availability: 'available', sector, as_of: null, totals: { identified_records: 1, known_mw_records: 1, unknown_records: 0, conflicted_records: 0 }, classes: { documented: { mw: sector === 'oil_gas' ? 3 : sector === 'data_centers' ? 5 : 11, record_count: 1 }, calculated: { mw: null, record_count: 0 }, estimated: { mw: null, record_count: 0 } }, provenance: { contract: 'equipment-demand-v1', source_count: 1, latest_evidence_at: null }, limitations: [] } })
  })
  await page.route('**/api/opportunities/groups?*', route => {
    const url = new URL(route.request().url())
    parentRequests.push(url)
    const offset = Number(url.searchParams.get('offset') ?? 0)
    parentToken = url.searchParams.get('cohort_token') ?? (url.searchParams.get('search') || url.searchParams.get('region') || url.searchParams.get('stage') || url.searchParams.get('priority') || url.searchParams.get('sort') !== 'priority' || url.searchParams.get('sector') !== 'all' ? `customer-cohort-${url.searchParams.get('sort')}-${url.searchParams.get('region') ?? 'all'}` : 'default-customer-cohort')
    const matches = customers.filter(customer => {
      if (url.searchParams.get('sector') === 'data_centers' && customer.id !== 'cross-sector-customer') return false
      if (url.searchParams.get('search') && !customer.name.toLowerCase().includes(url.searchParams.get('search')!.toLowerCase())) return false
      if (url.searchParams.get('region') && (customer.id !== 'filter-edge-customer' || url.searchParams.get('region') !== 'Austin, TX')) return false
      if (url.searchParams.get('stage') && (customer.id !== 'filter-edge-customer' || url.searchParams.get('stage') !== 'Construction notice')) return false
      if (url.searchParams.get('priority') === 'ranked' && customer.priority_score == null) return false
      if (url.searchParams.get('priority') === 'unranked' && customer.priority_score != null) return false
      return true
    })
    if (url.searchParams.get('sort') === 'company') matches.sort((left, right) => left.name.localeCompare(right.name))
    else if (url.searchParams.get('sort') === 'priority') matches.sort((left, right) => (right.priority_score ?? -1) - (left.priority_score ?? -1) || left.name.localeCompare(right.name))
    return route.fulfill({ json: {
      items: matches.slice(offset, offset + 25), total: matches.length, count_unit: 'groups', limit: 25, offset,
      cohort_token: parentToken, generation: 'synthetic-default-generation', facets: { regions: ['Permian Basin, TX', 'Austin, TX'], stages: ['Construction notice', 'Permit issued'] },
    } })
  })
  await page.route('**/api/opportunities/groups/*/projects?*', route => {
    const url = new URL(route.request().url())
    childRequests.push(url)
    const items = url.pathname.includes('filter-edge-customer') ? [edgeProject] : childProjects
    return route.fulfill({ json: { items, total: items.length, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'customer-project-cohort', parent_cohort_token: parentToken, generation: 'synthetic-default-generation' } })
  })
  await page.route('**/api/opportunities/projects?*', route => {
    const needId = new URL(route.request().url()).searchParams.get('need_id')
    const items = needId === 'need-filter-edge' ? [edgeProject] : []
    return route.fulfill({ json: { items, total: items.length, count_unit: 'projects', limit: 1, offset: 0, cohort_token: 'filter-edge-detail-cohort', generation: 'synthetic-default-generation' } })
  })
  await page.route('**/api/opportunities/needs/need-filter-edge*', route => route.fulfill({ json: {
    id: 'need-filter-edge', project_id: 'filter-edge-project', name: 'Filter Edge Site', browse_title: 'Filter Edge Site',
    location: 'Austin, TX', tier: 'Signal', activity: 'construction', supply: 'Unknown', required_mw: null,
    start_window: null, duration: null, evidence: [], missing_facts: [], rationale: 'Synthetic source-backed fixture.',
  } }))
  await page.goto('/')
  await expect(page.locator('.cfr-kpis')).toBeVisible()
  await expect(page.locator('.cfr-kpis article').first().locator('strong')).toHaveText('11 MW')
  await expect(page.locator('.customer-group')).toHaveCount(25)
  await expect(page.locator('.project-results-count')).toContainText('26')
  expect(parentRequests[0].searchParams.get('sector')).toBe('all')
  expect(parentRequests[0].searchParams.get('sort')).toBe('priority')
  await page.goto('/?view=workspace')
  await expect(page.locator('.customer-group')).toHaveCount(25)
  expect(parentRequests.at(-1)?.searchParams.get('sector')).toBe('all')
  await page.locator('.customer-group').filter({ hasText: 'Cross Sector Customer' }).locator('.customer-group-toggle').click()
  await expect(page.getByRole('heading', { name: 'Customer Data Center' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Customer Oil Field' })).toBeVisible()
  expect(childRequests[0].searchParams.get('parent_cohort_token')).toBe('default-customer-cohort')
  expect(childRequests[0].searchParams.get('sector')).toBe('all')
  expect(childRequests[0].searchParams.get('sort')).toBe('priority')
  await page.getByRole('button', { name: 'Data Centers', exact: true }).click()
  await expect.poll(() => parentRequests.at(-1)?.searchParams.get('sector')).toBe('data_centers')
  await expect.poll(() => demandScopes.at(-1)).toBe('data_centers')
  await expect(page.locator('.cfr-kpis article').first().locator('strong')).toHaveText('5 MW')
  expect(new URL(page.url()).searchParams.get('sector')).toBe('data_centers')
  await page.getByRole('button', { name: 'All', exact: true }).click()
  await page.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(page.locator('.customer-group')).toHaveCount(1)
  // Priority order places the two ranked fixtures before the unranked customer names.
  await expect(page.getByRole('button', { name: /Customer 24/ })).toBeVisible()
  expect(parentRequests.at(-1)?.searchParams.get('cohort_token')).toBeTruthy()
  await page.getByRole('button', { name: 'Previous', exact: true }).click()
  await expect(page.locator('.customer-group')).toHaveCount(25)

  await page.locator('.wh-account summary').click()
  await page.getByRole('button', { name: 'Signals', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Signals' })).toBeVisible()
  await page.locator('.wh-account summary').click()
  await page.getByRole('button', { name: 'Opportunities', exact: true }).click()
  await expect(page.locator('.customer-group')).toHaveCount(25)
  await expect(page.getByRole('textbox', { name: 'Search opportunities' })).toBeVisible()

  await expect(page.locator('.customer-group').nth(1)).toContainText('Filter Edge Customer')
  await page.getByRole('combobox', { name: 'Sort opportunities' }).selectOption('company')
  await expect.poll(() => parentRequests.at(-1)?.searchParams.get('sort')).toBe('company')
  await expect(page.locator('.customer-group').first()).toContainText('Cross Sector Customer')
  await expect(page.locator('.customer-group').nth(1)).toContainText('Customer 01')
  await expect(page.locator('.customer-group').filter({ hasText: 'Filter Edge Customer' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(page.locator('.customer-group')).toHaveCount(1)
  await expect(page.locator('.customer-group')).toContainText('Filter Edge Customer')
  await page.getByRole('button', { name: 'Previous', exact: true }).click()
  await expect(page.locator('.customer-group')).toHaveCount(25)
  await page.getByRole('combobox', { name: 'Region' }).selectOption('Austin, TX')
  await expect.poll(() => parentRequests.at(-1)?.searchParams.get('region')).toBe('Austin, TX')
  await expect(page.locator('.customer-group')).toHaveCount(1)
  await expect(page.locator('.customer-group')).toContainText('Filter Edge Customer')
  await page.getByRole('combobox', { name: 'Stage' }).selectOption('Construction notice')
  await expect.poll(() => parentRequests.at(-1)?.searchParams.get('stage')).toBe('Construction notice')
  await expect(page.locator('.customer-group')).toHaveCount(1)
  await page.getByRole('combobox', { name: 'Priority' }).selectOption('ranked')
  await expect.poll(() => parentRequests.at(-1)?.searchParams.get('priority')).toBe('ranked')
  await expect(page.locator('.customer-group')).toHaveCount(1)
  await page.getByRole('textbox', { name: 'Search opportunities' }).fill('Filter Edge Customer')
  await expect.poll(() => parentRequests.at(-1)?.searchParams.get('search')).toBe('Filter Edge Customer')
  await expect(page.locator('.customer-group')).toHaveCount(1)
  await expect(page.locator('.customer-group')).toContainText('Filter Edge Customer')
  const state = new URL(page.url()).searchParams
  expect(state.get('sort')).toBe('company')
  expect(state.get('region')).toBe('Austin, TX')
  expect(state.get('stage')).toBe('Construction notice')
  expect(state.get('priority')).toBe('ranked')
  expect(parentRequests.slice(-4).every(url => url.searchParams.get('offset') === '0')).toBe(true)
  await page.locator('.customer-group').filter({ hasText: 'Filter Edge Customer' }).locator('.customer-group-toggle').click()
  await expect(page.getByRole('heading', { name: 'Filter Edge Site' })).toBeVisible()
  expect(childRequests.at(-1)?.searchParams.get('parent_cohort_token')).toBe(parentToken)
  for (const [key, value] of [['search', 'Filter Edge Customer'], ['sector', 'all'], ['sort', 'company'], ['region', 'Austin, TX'], ['stage', 'Construction notice'], ['priority', 'ranked']]) {
    expect(childRequests.at(-1)?.searchParams.get(key)).toBe(value)
  }
  await page.locator('.customer-group').filter({ hasText: 'Filter Edge Customer' }).getByRole('button', { name: 'View project details' }).click()
  await expect(page).toHaveURL(/need=need-filter-edge/)
  const selectedDetail = page.locator('.wh-detail')
  await expect(selectedDetail.getByRole('heading', { name: 'Filter Edge Site', exact: true })).toBeVisible()
  await expect(selectedDetail).toContainText('Filter Edge Customer')
  await expect(selectedDetail.getByRole('link', { name: 'Call Filter Edge Customer' })).toHaveAttribute('href', 'tel:+15555550125')
  await page.getByRole('button', { name: 'Back to power needs', exact: true }).click()
  await expect(page.getByRole('textbox', { name: 'Search opportunities' })).toHaveValue('Filter Edge Customer')
  await expect(page.getByRole('combobox', { name: 'Sort opportunities' })).toHaveValue('company')
  await expect(page.getByRole('combobox', { name: 'Region' })).toHaveValue('Austin, TX')
  await expect(page.getByRole('combobox', { name: 'Stage' })).toHaveValue('Construction notice')
  await expect(page.getByRole('combobox', { name: 'Priority' })).toHaveValue('ranked')
  const restoredGroup = page.locator('.customer-group').filter({ hasText: 'Filter Edge Customer' })
  await expect(restoredGroup.locator('.customer-group-toggle')).toHaveAttribute('aria-expanded', 'true')
  await expect(restoredGroup.getByRole('heading', { name: 'Filter Edge Site' })).toBeVisible()
})

test('legacy flat sort and malformed offset links normalize to a valid default grouped URL and request', async ({ page }) => {
  const requests: URL[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?*', route => {
    const url = new URL(route.request().url())
    requests.push(url)
    return route.fulfill({ json: { ...groupPage, items: [{ ...group, group_kind: 'resolved_identity' }] } })
  })
  await page.goto('/?sort=project&offset=-5')
  await expect(page.locator('.customer-group')).toHaveCount(1)
  await expect.poll(() => requests.length).toBeGreaterThan(0)
  expect(requests[0].searchParams.get('sort')).toBe('priority')
  expect(requests[0].searchParams.get('offset')).toBe('0')
  const normalizedUrl = new URL(page.url())
  expect(normalizedUrl.searchParams.has('sort')).toBe(false)
  expect(normalizedUrl.searchParams.has('offset')).toBe(false)
})

test('synthetic same-name group keeps three source identities and contacts independent through detail and Back', async ({ page }) => {
  // Mocked fixtures verify rendering and navigation only; source eligibility is covered by backend tests.
  const makeProject = (suffix: string, identity: string, contactLabel: string, phone: string) => ({
    ...sample,
    id: `amazon-pecos-${suffix}`,
    project_id: `amazon-pecos-${suffix}`,
    customer_identity_id: `pecos-company-${suffix}`,
    name: 'AMAZON PECOS Facility',
    company: identity,
    contact_people: [],
    representative_need_id: `need-amazon-${suffix}`,
    needs: [{ id: `need-amazon-${suffix}`, project_id: `amazon-pecos-${suffix}`, browse_title: 'AMAZON PECOS Facility', activity: 'construction', tier: 'Signal' }],
    need_count: 1,
    contact: [{ kind: 'call', label: contactLabel, href: `tel:${phone}`, company: identity }],
  })
  const projects = [
    makeProject('a', 'PECOS identity A', 'Call PECOS A', '+15555550101'),
    makeProject('b', 'PECOS identity B', 'Call PECOS B', '+15555550102'),
    makeProject('c', 'PECOS identity C', 'Call PECOS C', '+15555550103'),
  ]
  const group = {
    id: 'same-name-amazon-pecos', name: 'AMAZON', role: 'customer', group_kind: 'same_name_unconfirmed', identity_count: 3,
    project_count: 3, need_count: 3, sectors: ['oil_gas'],
  }
  const detailReads: string[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: {
    items: [group], total: 1, count_unit: 'groups', limit: 25, offset: 0,
    cohort_token: 'amazon-name-cohort', generation: 'synthetic-amazon-generation', facets: { regions: [], stages: [] },
  } }))
  await page.route('**/api/opportunities/groups/same-name-amazon-pecos/projects?*', route => route.fulfill({ json: {
    items: projects, total: 3, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'amazon-project-cohort',
    parent_cohort_token: 'amazon-name-cohort', generation: 'synthetic-amazon-generation',
  } }))
  await page.route('**/api/opportunities/projects?*', route => {
    const url = new URL(route.request().url())
    const needId = url.searchParams.get('need_id')
    if (!needId) return route.fulfill({ json: { items: [], total: 0, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'unused', generation: 'synthetic' } })
    detailReads.push(needId)
    const project = projects.find(item => item.representative_need_id === needId)
    return route.fulfill({ json: { items: project ? [project] : [], total: project ? 1 : 0, count_unit: 'projects', limit: 1, offset: 0, cohort_token: `detail-${needId}`, generation: 'synthetic-amazon-generation' } })
  })
  await page.route('**/api/opportunities/needs/need-amazon-*', route => {
    const needId = new URL(route.request().url()).pathname.split('/').at(-1)!
    const project = projects.find(item => item.representative_need_id === needId)
    return route.fulfill({ json: {
      id: needId, project_id: project?.project_id, name: 'AMAZON PECOS Facility', browse_title: 'AMAZON PECOS Facility',
      location: 'Pecos, TX', tier: 'Signal', activity: 'construction', supply: 'Unknown', required_mw: null,
      start_window: null, duration: null, evidence: [], missing_facts: [], rationale: 'Synthetic source-backed fixture.',
    } })
  })

  await page.goto('/')
  const groupRegion = page.getByRole('region', { name: 'AMAZON name group' })
  const groupToggle = page.getByRole('button', { name: /AMAZON/ })
  await expect(groupRegion).toContainText('Name group')
  await expect(groupRegion.getByText('Same source-reported name; company identities are not linked.', { exact: true })).toBeVisible()
  await expect(groupRegion.getByText('3 separate company identities', { exact: true })).toBeVisible()
  await groupToggle.click()
  await expect(groupToggle).toHaveAttribute('aria-expanded', 'true')
  await expect(groupRegion).toContainText('Name group')
  await expect(groupRegion.getByText('Same source-reported name; company identities are not linked.', { exact: true })).toBeVisible()
  await expect(groupRegion.getByText('3 separate company identities', { exact: true })).toBeVisible()
  const cards = page.locator('.customer-group-projects .project-card')
  await expect(cards).toHaveCount(3)
  await expect(groupRegion.locator('.customer-group-name')).toHaveText('AMAZON')
  for (const [index, ownLabel, ownHref, otherLabels] of [
    [0, 'Call PECOS A', 'tel:+15555550101', ['Call PECOS B', 'Call PECOS C']],
    [1, 'Call PECOS B', 'tel:+15555550102', ['Call PECOS A', 'Call PECOS C']],
    [2, 'Call PECOS C', 'tel:+15555550103', ['Call PECOS A', 'Call PECOS B']],
  ] as const) {
    const card = cards.nth(index)
    await expect(card.locator('h3')).toHaveText('AMAZON PECOS Facility')
    await expect(card).toContainText(`PECOS identity ${String.fromCharCode(65 + index)}`)
    await expect(card.getByRole('link', { name: ownLabel })).toHaveAttribute('href', ownHref)
    for (const otherLabel of otherLabels) await expect(card.getByRole('link', { name: otherLabel })).toHaveCount(0)

    await card.getByRole('button', { name: 'View project details' }).click()
    const suffix = String.fromCharCode(97 + index)
    await expect(page).toHaveURL(new RegExp(`need=need-amazon-${suffix}`))
    await expect.poll(() => detailReads.at(-1)).toBe(`need-amazon-${suffix}`)
    const detail = page.locator('.project-first-detail')
    await expect(detail.locator('h2')).toHaveText('AMAZON PECOS Facility')
    await expect(detail).toContainText(`PECOS identity ${String.fromCharCode(65 + index)}`)
    await expect(detail.getByRole('link', { name: ownLabel })).toHaveAttribute('href', ownHref)
    for (const otherLabel of otherLabels) await expect(detail.getByRole('link', { name: otherLabel })).toHaveCount(0)
    await page.getByRole('button', { name: 'Back to power needs', exact: true }).click()
    await expect(cards).toHaveCount(3)
    await expect(groupRegion.getByText('3 separate company identities', { exact: true })).toBeVisible()
  }
  expect([...new Set(detailReads)]).toEqual(['need-amazon-a', 'need-amazon-b', 'need-amazon-c'])
})

test('synthetic default All scope shows neutral group wording without a qualified-only empty message', async ({ page }) => {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: { ...groupPage, items: [], total: 0 } }))
  await page.goto('/')
  await expect(page.getByText('No groups match this search.')).toBeVisible()
})

test('legacy groupBrowse URL keeps unresolved groups explicit without implying a resolved organization', async ({ page }) => {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: { ...groupPage, items: [{ ...group, role: 'unresolved', name: 'Unresolved source entity' }] } }))
  await page.goto('/?groupBrowse=1')
  await expect(page.locator('.customer-group')).toContainText('Operator/customer unresolved')
  await expect(page.locator('.project-results-count')).toHaveText('1 group')
})

test('synthetic project results use the project contract, category filters, and honest contact/event labels', async ({ page }) => {
  const requests: URL[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?*', async route => {
    requests.push(new URL(route.request().url()))
    return route.fulfill({ json: groupPage })
  })
  await page.route('**/api/opportunities/groups/group-synthetic-1/projects?*', route => route.fulfill({ json: projectPage }))
  await page.goto('/?view=workspace')
  await expect(page.getByRole('heading', { name: 'Search opportunities' })).toBeVisible()
  await expect(page.getByText('1 group')).toBeVisible()
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
  await expect(page.locator('.project-results-count')).toHaveText('27 groups')
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
  await expect(page.locator('.project-results-count')).toHaveText('50 groups')
  await page.getByRole('button', { name: 'Next' }).click()
  await expect(page.locator('.project-results-count')).toContainText('Results changed')
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
  await expect(page.getByText('1 group')).toBeVisible()
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

test('pending parent groups wait for Retry-After then reopen the same filtered cohort', async ({ page }) => {
  await page.clock.install({ time: new Date('2026-10-29T11:59:00Z') })
  let pauseClock: Promise<void> | undefined
  const requests: URL[] = []
  let pending = true
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
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
  await page.goto('/?view=workspace&q=Permian&sector=oil_gas')
  await expect(page.getByRole('status')).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.getByRole('status').filter({ hasText: /Retrying automatically/i })).toBeVisible()
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

test('pending first child read waits before atomic open of the same group', async ({ page }) => {
  await page.clock.install({ time: new Date('2026-10-29T11:59:00Z') })
  const childRequests: URL[] = []
  const openRequests: URL[] = []
  const neighbor = { ...group, id: 'neighbor-group', name: 'Unchanged Operator', project_count: 4 }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: { ...groupPage, items: [group, neighbor] } }))
  await page.route('**/api/opportunities/groups/group-synthetic-1/projects?*', route => {
    childRequests.push(new URL(route.request().url()))
    return route.fulfill({
      status: 503,
      headers: { 'X-Qualification-State': 'pending', 'Retry-After': '5' },
      json: { detail: 'qualification pending' },
    })
  })
  await page.route('**/api/opportunities/groups/group-synthetic-1/open?*', route => {
    const url = new URL(route.request().url())
    openRequests.push(url)
    return route.fulfill({ json: {
      group: { ...group, name: 'Fresh Energy Customer', role: 'customer', project_count: 1 },
      projects: { ...projectPage, items: [{ ...sample, name: 'Freshly opened project' }] },
      parent_cohort_token: 'fresh-parent-cohort',
      generation: 'fresh-generation',
    } })
  })
  await page.goto('/?view=workspace&q=Permian&sector=oil_gas')
  await expect(page.getByRole('button', { name: /Example Energy/ })).toBeVisible()
  await page.clock.pauseAt(new Date('2026-10-29T12:00:00Z'))
  await page.getByRole('button', { name: /Example Energy/ }).click()
  await expect(page.getByText('Loading projects…')).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect.poll(() => childRequests.length).toBe(1)
  // Count the Retry-After interval from the moment the client has handled the
  // pending response and installed its timer, not from route entry.
  await expect(page.getByRole('status').filter({ hasText: /Retrying this group automatically/i })).toBeVisible()
  await page.clock.runFor(4999)
  expect(openRequests).toHaveLength(0)
  await page.clock.runFor(1)
  await expect.poll(() => openRequests.length).toBe(1)
  await expect(page.getByRole('heading', { name: 'Freshly opened project' })).toBeVisible()
  await expect(page.getByRole('button', { name: /Fresh Energy Customer/ })).toHaveAttribute('aria-expanded', 'true')
  await expect(page.getByRole('button', { name: /Unchanged Operator/ })).toContainText('4 projects')
  expect(openRequests[0].pathname).toBe('/api/opportunities/groups/group-synthetic-1/open')
  expect(openRequests[0].searchParams.get('search')).toBe('Permian')
  expect(openRequests[0].searchParams.get('sector')).toBe('oil_gas')
  expect(openRequests[0].searchParams.has('parent_cohort_token')).toBe(false)
  expect(openRequests[0].searchParams.has('cohort_token')).toBe(false)
  expect(openRequests[0].searchParams.has('offset')).toBe(false)
  expect(childRequests).toHaveLength(1)
})

test('409 opens atomically and a pending open retries to the fresh same-group page', async ({ page }) => {
  await page.clock.install({ time: new Date('2030-01-01T00:00:00Z') })
  const childRequests: URL[] = []
  const openRequests: URL[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: { ...groupPage, cohort_token: 'parent-list-cohort' } }))
  await page.route('**/api/opportunities/groups/group-synthetic-1/projects?*', route => {
    childRequests.push(new URL(route.request().url()))
    return route.fulfill({ status: 409, json: { detail: 'parent cohort changed' } })
  })
  await page.route('**/api/opportunities/groups/group-synthetic-1/open?*', route => {
    const url = new URL(route.request().url())
    openRequests.push(url)
    if (openRequests.length === 1) {
      return route.fulfill({
        status: 503,
        headers: { 'X-Qualification-State': 'pending', 'Retry-After': '5' },
        json: { detail: 'qualification pending' },
      })
    }
    return route.fulfill({ json: {
      group: { ...group, name: 'Fresh atomic customer', role: 'customer', project_count: 1 },
      projects: { ...projectPage, items: [{ ...sample, name: 'Fresh atomic project' }] },
      parent_cohort_token: 'fresh-parent-token',
      generation: 'fresh-generation',
    } })
  })
  await page.goto('/?view=workspace&q=Permian')
  await expect(page.getByRole('button', { name: /Example Energy/ })).toBeVisible()
  // Freeze the clock before the pending open creates its Retry-After timer so
  // test setup and route handling cannot consume part of the 5-second window.
  await page.clock.pauseAt(new Date('2030-01-01T00:01:00Z'))
  await page.getByRole('button', { name: /Example Energy/ }).click()
  await expect.poll(() => childRequests.length).toBe(1)
  await expect.poll(() => openRequests.length).toBe(1)
  await expect(page.getByText('Loading projects…')).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await page.clock.fastForward(4999)
  expect(openRequests).toHaveLength(1)
  await page.clock.fastForward(1)
  await expect.poll(() => openRequests.length).toBe(2)
  await expect(page.getByRole('heading', { name: 'Fresh atomic project' })).toBeVisible()
  await expect(page.getByRole('button', { name: /Fresh atomic customer/ })).toHaveAttribute('aria-expanded', 'true')
  expect(childRequests).toHaveLength(1)
  expect(openRequests.every(url => url.pathname.endsWith('/group-synthetic-1/open'))).toBe(true)
  for (const url of openRequests) {
    expect(url.searchParams.has('parent_cohort_token')).toBe(false)
    expect(url.searchParams.has('cohort_token')).toBe(false)
    expect(url.searchParams.has('offset')).toBe(false)
  }
})

test('parent pending retries stop after four active reads and manual retry starts over', async ({ page }) => {
  await page.clock.install({ time: new Date('2026-10-29T11:59:00Z') })
  let pauseClock: Promise<void> | undefined
  let requests = 0
  let pending = true
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
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
  await page.goto('/')
  await expect(page.getByRole('status')).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.getByRole('status').filter({ hasText: /Retrying automatically/i })).toBeVisible()
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
    await page.goto('/')
    await expect(page.getByRole('alert')).toContainText('503')
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
  await page.goto('/')
  await expect(page.getByRole('status').filter({ hasText: /Retrying automatically/i })).toBeVisible()
  const initialPendingRequests = requests.length
  expect(initialPendingRequests).toBeGreaterThan(0)
  await page.getByRole('textbox', { name: 'Search opportunities' }).fill('fresh')
  await expect(page.getByRole('button', { name: /Superseding search result/ })).toBeVisible()
  expect(requests).toHaveLength(initialPendingRequests + 1)
  await page.clock.fastForward(5000)
  expect(requests).toHaveLength(initialPendingRequests + 1)
  expect(requests.slice(0, initialPendingRequests).every(url => !url.searchParams.has('search'))).toBe(true)
  expect(requests[initialPendingRequests].searchParams.get('search')).toBe('fresh')
  await expect(page.getByRole('button', { name: /Superseding search result/ })).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('collapsing a group cancels its pending child retry before atomic reopen', async ({ page }) => {
  await page.clock.install()
  let childReads = 0
  let openReads = 0
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: groupPage }))
  await page.route('**/api/opportunities/groups/group-synthetic-1/projects?*', route => {
    childReads += 1
    return route.fulfill({
      status: 503,
      headers: { 'X-Qualification-State': 'pending', 'Retry-After': '5' },
      json: { detail: 'qualification pending' },
    })
  })
  await page.route('**/api/opportunities/groups/group-synthetic-1/open?*', route => {
    openReads += 1
    return route.fulfill({ json: {
      group,
      projects: projectPage,
      parent_cohort_token: 'fresh-parent-token',
      generation: 'fresh-generation',
    } })
  })
  await page.goto('/')
  const groupToggle = page.getByRole('button', { name: /Example Energy/ })
  await groupToggle.click()
  await expect(page.getByText('Loading projects…')).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect.poll(() => childReads).toBe(1)
  const groupCard = page.locator('.customer-group').filter({ hasText: 'Example Energy' })
  await expect(groupCard.getByRole('status').filter({ hasText: /Retrying this group automatically/i })).toBeVisible()
  await groupToggle.click()
  await expect(groupToggle).toHaveAttribute('aria-expanded', 'false')
  await expect(groupCard.getByRole('status')).toHaveCount(0)
  await page.clock.fastForward(5000)
  expect(childReads).toBe(1)
  expect(openReads).toBe(0)
  await expect(page.getByRole('heading', { name: 'Example Compressor Station' })).toHaveCount(0)
})

test('pending atomic open exhaustion is bounded and manual retry starts a new cycle', async ({ page }) => {
  await page.clock.install()
  let childReads = 0
  let openReads = 0
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: groupPage }))
  await page.route('**/api/opportunities/groups/group-synthetic-1/projects?*', route => {
    childReads += 1
    if (childReads === 1) return route.fulfill({ status: 409, json: { detail: 'parent cohort changed' } })
    return route.fulfill({ json: { ...projectPage, items: [{ ...sample, name: 'Manually retried project' }] } })
  })
  await page.route('**/api/opportunities/groups/group-synthetic-1/open?*', route => {
    openReads += 1
    if (openReads <= 4) {
      return route.fulfill({
        status: 503,
        headers: { 'X-Qualification-State': 'pending', 'Retry-After': '1' },
        json: { detail: 'qualification pending' },
      })
    }
    return route.fulfill({ json: {
      group,
      projects: { ...projectPage, items: [{ ...sample, name: 'Manually retried project' }] },
      parent_cohort_token: 'fresh-parent-token',
      generation: 'fresh-generation',
    } })
  })
  await page.goto('/')
  await page.getByRole('button', { name: /Example Energy/ }).click()
  await expect.poll(() => openReads).toBe(1)
  await expect(page.getByRole('alert')).toHaveCount(0)
  for (let attempt = 2; attempt <= 3; attempt += 1) {
    await page.clock.fastForward(1000)
    await expect.poll(() => openReads).toBe(attempt)
    await expect(page.getByRole('alert')).toHaveCount(0)
  }
  await page.clock.fastForward(1000)
  await expect.poll(() => openReads).toBe(4)
  await expect(page.getByRole('alert')).toContainText(/still being prepared/i)
  const groupCard = page.locator('.customer-group').filter({ hasText: 'Example Energy' })
  await expect(groupCard.getByRole('status').filter({ hasText: /Retrying this group automatically/i })).toHaveCount(0)
  const attemptsBeforeManualRetry = childReads + openReads
  await page.getByRole('button', { name: /Retry|Reload/i }).last().click()
  await expect(page.getByRole('heading', { name: 'Manually retried project' })).toBeVisible()
  expect(childReads + openReads).toBe(attemptsBeforeManualRetry + 1)
})

test('collapsing one pending group clears only its retry status and preserves the other group', async ({ page }) => {
  await page.clock.install()
  const first = group
  const second = { ...group, id: 'group-synthetic-2', name: 'Second Energy', project_count: 2 }
  const childReads: string[] = []
  const openReads: string[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: { ...groupPage, items: [first, second] } }))
  await page.route('**/api/opportunities/groups/*/projects?*', route => {
    const groupId = new URL(route.request().url()).pathname.split('/').at(-2)!
    childReads.push(groupId)
    return route.fulfill({
      status: 503,
      headers: { 'X-Qualification-State': 'pending', 'Retry-After': '5' },
      json: { detail: 'qualification pending' },
    })
  })
  await page.route('**/api/opportunities/groups/*/open?*', route => {
    const groupId = new URL(route.request().url()).pathname.split('/').at(-2)!
    openReads.push(groupId)
    return route.fulfill({ json: {
      group: groupId === second.id ? second : first,
      projects: projectPage,
      parent_cohort_token: 'fresh-parent-token',
      generation: 'fresh-generation',
    } })
  })
  await page.goto('/')
  const firstCard = page.locator('.customer-group').filter({ hasText: first.name })
  const secondCard = page.locator('.customer-group').filter({ hasText: second.name })
  await firstCard.getByRole('button', { name: /Example Energy/ }).click()
  await expect(firstCard.getByRole('status').filter({ hasText: /Retrying this group automatically/i })).toBeVisible()
  await secondCard.getByRole('button', { name: /Second Energy/ }).click()
  await expect(secondCard.getByRole('status').filter({ hasText: /Retrying this group automatically/i })).toBeVisible()
  expect(childReads).toEqual([first.id, second.id])

  await firstCard.getByRole('button', { name: /Example Energy/ }).click()
  await expect(firstCard.getByRole('status')).toHaveCount(0)
  await expect(secondCard.getByRole('status').filter({ hasText: /Retrying this group automatically/i })).toBeVisible()
  await expect(secondCard.getByRole('button', { name: /Second Energy/ })).toHaveAttribute('aria-expanded', 'true')

  await page.clock.fastForward(5000)
  await expect.poll(() => openReads).toEqual([second.id])
  await expect(firstCard.getByRole('button', { name: /Example Energy/ })).toHaveAttribute('aria-expanded', 'false')
  await expect(secondCard.getByRole('heading', { name: 'Example Compressor Station' })).toBeVisible()
})

test('leaving opportunities during atomic-open wait cancels the retry timer', async ({ page }) => {
  await page.clock.install()
  let childReads = 0
  let openReads = 0
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: groupPage }))
  await page.route('**/api/opportunities/groups/group-synthetic-1/projects?*', route => {
    childReads += 1
    return route.fulfill({ status: 409, json: { detail: 'parent cohort changed' } })
  })
  await page.route('**/api/opportunities/groups/group-synthetic-1/open?*', route => {
    openReads += 1
    return route.fulfill({
      status: 503,
      headers: { 'X-Qualification-State': 'pending', 'Retry-After': '5' },
      json: { detail: 'qualification pending' },
    })
  })
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({
    status: 503,
    json: { detail: 'Synthetic research cohort unavailable' },
  }))
  await page.goto('/')
  const groupCard = page.locator('.customer-group').filter({ hasText: 'Example Energy' })
  await groupCard.getByRole('button', { name: /Example Energy/ }).click()
  await expect.poll(() => childReads).toBe(1)
  await expect.poll(() => openReads).toBe(1)
  await expect(groupCard.getByRole('status').filter({ hasText: /Retrying this group automatically/i })).toBeVisible()

  // SPA navigation unmounts ProjectResults while preserving the browser realm
  // and the pending fake-clock timer.
  await page.locator('.wh-account summary').click()
  await page.getByRole('button', { name: 'Research', exact: true }).click()
  await expect(page.getByRole('main', { name: 'Automated research' })).toBeVisible()
  await page.clock.fastForward(5000)
  expect(openReads).toBe(1)
})

test('rapid project searches debounce and an older response cannot replace the newest results', async ({ page }) => {
  let releaseOld: (() => void) | undefined
  let oldRequested: (() => void) | undefined
  const oldStarted = new Promise<void>(resolve => { oldRequested = resolve })
  const searches: string[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
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
  await page.goto('/?q=seed')
  await expect(page.getByRole('button', { name: /Example Energy/ })).toBeVisible()
  const diaRequest = page.waitForRequest(request => new URL(request.url()).searchParams.get('search') === 'Dia')
  const input = page.getByRole('textbox', { name: 'Search opportunities' })
  await input.fill('D')
  await input.fill('Di')
  await input.fill('Dia')
  await diaRequest
  await oldStarted
  const latestRequest = page.waitForRequest(request => new URL(request.url()).searchParams.get('search') === 'Diamondback')
  await input.fill('Diamondback')
  await latestRequest
  await expect(page.getByRole('button', { name: /Diamondback Operator/ })).toBeVisible()
  releaseOld?.()
  await expect(page.getByRole('button', { name: /Diamondback Operator/ })).toBeVisible()
  await expect(page.getByText('Old search result')).toHaveCount(0)
  expect(searches.filter(value => ['D', 'Di'].includes(value))).toEqual([])
})

test('refresh keeps the rendered cohort labeled as updating and clears it when the filter changes', async ({ page }) => {
  let refresh = false
  let releaseDataCenters: (() => void) | undefined
  let dataCentersRequested: (() => void) | undefined
  const dataCentersStarted = new Promise<void>(resolve => { dataCentersRequested = resolve })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
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
  await page.goto('/')
  await expect(page.getByRole('button', { name: /Example Energy/ })).toBeVisible()
  refresh = true
  await page.getByRole('button', { name: 'Refresh project results' }).click()
  await expect(page.getByRole('status')).toContainText('Updating results')
  await expect(page.getByRole('status')).toContainText('qualification may have changed')
  await expect(page.getByRole('button', { name: /Example Energy/ })).toBeVisible()
  await page.getByRole('button', { name: 'Data Centers' }).click()
  await dataCentersStarted
  await expect(page.getByRole('status')).toContainText('Showing prior operator/customer summaries')
  await expect(page.getByRole('button', { name: /Example Energy/ })).toBeDisabled()
  releaseDataCenters?.()
  await expect(page.getByRole('button', { name: /Data Center Owner/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /Example Energy/ })).toHaveCount(0)
})

test('expanded project pages survive More-menu navigation and return to the same browse context', async ({ page }) => {
  let childReads = 0
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: groupPage }))
  await page.route('**/api/opportunities/groups/group-synthetic-1/projects?*', route => { childReads += 1; return route.fulfill({ json: projectPage }) })
  await page.route('**/api/opportunities?*', route => route.fulfill({ json: [] }))
  await page.goto('/?q=Diamondback&sector=oil_gas')
  await page.getByRole('button', { name: /Example Energy/ }).click()
  await expect(page.getByRole('heading', { name: 'Example Compressor Station' })).toBeVisible()
  await page.locator('.wh-account summary').click()
  await page.getByRole('button', { name: 'Signals', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Signals' })).toBeVisible()
  await page.locator('.wh-account summary').click()
  await page.getByRole('button', { name: 'Opportunities', exact: true }).click()
  await expect(page.getByRole('button', { name: /Example Energy/ })).toHaveAttribute('aria-expanded', 'true')
  await expect(page.getByRole('heading', { name: 'Example Compressor Station' })).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Search opportunities' })).toHaveValue('Diamondback')
  expect(new URL(page.url()).searchParams.get('sector')).toBe('oil_gas')
  expect(childReads).toBe(1)
  await expect(page.locator('.wh-account[open]')).toHaveCount(0)
})

test('Signals and source health distinguish a loading request from terminal unavailability', async ({ page }) => {
  let failSignals = false
  let releaseHealth: (() => void) | undefined
  let healthRequested: (() => void) | undefined
  const healthStarted = new Promise<void>(resolve => { healthRequested = resolve })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
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
  await page.route('**/api/opportunities/groups?*', route => {
    groupReads += 1
    return expireSession ? route.fulfill({ status: 401, json: { detail: 'Authentication required' } }) : route.fulfill({ json: groupPage })
  })
  await page.route('**/api/opportunities?*', route => route.fulfill({ json: [] }))
  await page.goto('/')
  await expect(page.getByRole('button', { name: /Example Energy/ })).toBeVisible()
  const initialGroupReads = groupReads
  expireSession = true
  await page.getByRole('button', { name: 'Refresh project results' }).click()
  await expect(page.getByRole('alert')).toContainText('Your session ended')
  await expect.poll(() => groupReads).toBeGreaterThan(initialGroupReads)
  await expect(page.getByRole('button', { name: /Example Energy/ })).toHaveCount(0)
  await page.locator('.wh-account summary').click()
  await page.getByRole('button', { name: 'Signals', exact: true }).click()
  await page.locator('.wh-account summary').click()
  await page.getByRole('button', { name: 'Opportunities', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Your session ended')
  await expect(page.getByRole('button', { name: /Example Energy/ })).toHaveCount(0)
  expect(groupReads).toBeGreaterThan(initialGroupReads + 1)
})

test('a session expiry from Signals clears the browse cache while results are unmounted', async ({ page }) => {
  let groupReads = 0
  let serviceUnavailable = false
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?*', route => {
    groupReads += 1
    return serviceUnavailable ? route.fulfill({ status: 503, headers: { 'X-Qualification-State': 'pending', 'Retry-After': '60' }, json: { detail: 'qualification pending' } }) : route.fulfill({ json: groupPage })
  })
  await page.route('**/api/opportunities?*', route => route.fulfill({ status: 401, json: { detail: 'Authentication required' } }))
  await page.goto('/')
  await expect(page.getByRole('button', { name: /Example Energy/ })).toBeVisible()
  const initialGroupReads = groupReads
  await page.locator('.wh-account summary').click()
  await page.getByRole('button', { name: 'Signals', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Your session ended')
  serviceUnavailable = true
  await page.locator('.wh-account summary').click()
  await page.getByRole('button', { name: 'Opportunities', exact: true }).click()
  await expect(page.getByRole('status')).toBeVisible()
  await expect(page.getByRole('button', { name: /Example Energy/ })).toHaveCount(0)
  expect(groupReads).toBeGreaterThan(initialGroupReads)
})

test('cached browse context expires at the backend valid-until boundary', async ({ page }) => {
  await page.clock.install({ time: new Date('2026-10-29T11:59:00Z') })
  let pauseClock: Promise<void> | undefined
  let groupReads = 0
  let expired = false
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?*', async route => {
    // Let the app mount, then freeze before any browse response creates timers.
    // StrictMode handlers share one pause; wall-time assertions cannot age TTLs.
    await (pauseClock ??= page.clock.pauseAt(new Date('2026-10-29T12:00:00Z')))
    groupReads += 1
    const name = expired ? 'Current after generation expiry' : 'Before generation expiry'
    const validUntil = expired ? '2026-10-29T12:01:00Z' : '2026-10-29T12:00:02Z'
    return route.fulfill({ json: { ...groupPage, items: [{ ...group, id: `expiry-${groupReads}`, name }], as_of: '2026-10-29T11:59:00Z', valid_until: validUntil, qualification_state: 'current', refresh_state: 'current' } })
  })
  await page.goto('/')
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

test('mounted child details disappear at their independent generation expiry', async ({ page }) => {
  await page.clock.install({ time: new Date('2026-10-29T12:00:00Z') })
  let childReads = 0
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: { ...groupPage, as_of: '2026-10-29T11:59:00Z', valid_until: '2026-10-29T12:00:20Z', qualification_state: 'current', refresh_state: 'current' } }))
  await page.route('**/api/opportunities/groups/group-synthetic-1/projects?*', route => {
    childReads += 1
    const validUntil = childReads === 1 ? '2026-10-29T12:00:02Z' : '2026-10-29T12:00:20Z'
    const label = childReads === 1 ? 'Expired child contact' : 'Current child contact'
    return route.fulfill({ json: { ...projectPage, valid_until: validUntil, qualification_state: 'current', refresh_state: 'current', items: [{ ...sample, contact: [{ kind: 'call', label, href: 'tel:+15555550100' }] }] } })
  })
  await page.goto('/')
  const groupButton = page.getByRole('button', { name: /Example Energy/ })
  await groupButton.click()
  await expect(page.getByRole('link', { name: 'Expired child contact' })).toBeVisible()
  await page.clock.fastForward(2_100)
  await expect(page.getByRole('link', { name: 'Expired child contact' })).toHaveCount(0)
  await expect(groupButton).toHaveAttribute('aria-expanded', 'false')
  await groupButton.click()
  await expect(page.getByRole('link', { name: 'Current child contact' })).toBeVisible()
  expect(childReads).toBe(2)
})

test('cache read drops an expired child generation while retaining the valid parent summary', async ({ page }) => {
  await page.clock.install({ time: new Date('2026-10-29T12:00:00Z') })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: { ...groupPage, as_of: '2026-10-29T11:59:00Z', valid_until: '2026-10-29T12:00:20Z', qualification_state: 'current', refresh_state: 'current' } }))
  await page.route('**/api/opportunities/groups/group-synthetic-1/projects?*', route => route.fulfill({ json: { ...projectPage, valid_until: '2026-10-29T12:00:02Z', qualification_state: 'current', refresh_state: 'current', items: [{ ...sample, contact: [{ kind: 'call', label: 'Expired cached contact', href: 'tel:+15555550100' }] }] } }))
  await page.route('**/api/opportunities?*', route => route.fulfill({ json: [] }))
  await page.goto('/')
  await page.getByRole('button', { name: /Example Energy/ }).click()
  await expect(page.getByRole('link', { name: 'Expired cached contact' })).toBeVisible()
  await page.locator('.wh-account summary').click()
  await page.getByRole('button', { name: 'Signals', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Signals' })).toBeVisible()
  await page.clock.fastForward(2_100)
  await page.locator('.wh-account summary').click()
  await page.getByRole('button', { name: 'Opportunities', exact: true }).click()
  await expect(page.getByRole('button', { name: /Example Energy/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /Example Energy/ })).toHaveAttribute('aria-expanded', 'false')
  await expect(page.getByRole('link', { name: 'Expired cached contact' })).toHaveCount(0)
})
