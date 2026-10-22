import { expect, test } from '@playwright/test'

const accountRow = {
  id: 'need-1', project_id: 'project-1', browse_title: 'Cedar Ridge campus', location: 'Austin, TX', tier: 'Prospect',
  activity_key: 'construction', required_mw: '12', start_window: '2027', duration: null, supply: 'Unknown',
  evidence_count: 1, commercial_disposition: null, commercial_reason: 'Timing requires confirmation.', commercial_next_question: 'Who controls power procurement?', commercial_next_action: 'Verify the project power package.', commercial_organization: 'Northstar Compute',
  company_identity_id: 'company-1', account_name: 'Northstar Compute', asset_type: 'data_center', account_aliases: ['Northstar', 'NORTHSTAR COMPUTE'], supporting_evidence_count: 8, last_evidence_update: '2026-10-20', project_count: 2, need_count: 3, matching_project_count: 2, matching_need_count: 2,
}
const accountWorkspace = (params: URLSearchParams, items = [accountRow]) => ({
  items, total: items.length, counts: { action_now: 0, research: items.length, watch: 0, reject: 0 }, offset: Number(params.get('offset') ?? 0), limit: 25, next_offset: null,
  cohort_token: 'accounts-cohort', count_unit: 'company accounts', changes_available: false,
})

test('account queue uses server grouping, opens paginated projects, and retains unresolved research access', async ({ page }) => {
  const workspaceQueries: string[] = []
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (url.pathname === '/api/opportunities/workspace') { workspaceQueries.push(url.search); return route.fulfill({ json: accountWorkspace(url.searchParams) }) }
    if (url.pathname === '/api/opportunities/workspace/changes') return route.fulfill({ json: { items: [], counts: { discovered: 0, changed: 0, promoted: 0, closed: 0, review_exception: 0 }, total_unreviewed: 0, offset: 0, limit: 50, next_offset: null, baseline_identity: 'test', token: 'test', source_health_exceptions: [] } })
    if (url.pathname === '/api/customer-accounts/company-1/projects') { const offset = Number(url.searchParams.get('need_offset') ?? 0); return route.fulfill({ json: { account: { company_identity_id: 'company-1', name: 'Northstar Compute', aliases: ['Northstar', 'NORTHSTAR COMPUTE'], project_count: 2, need_count: 27, supporting_evidence_count: 8, last_evidence_update: '2026-10-20', qualification_tiers: ['Prospect'], highest_priority_need: { activity_key: 'construction', required_mw: '12', start_window: '2027', tier: 'Prospect', industry: null, location: 'Austin, TX', commercial_disposition: 'RESEARCH', commercial_reason: 'Timing needs confirmation.', commercial_next_action: 'Verify project power package.' } }, items: [{ id: 'project-1', name: 'Cedar Ridge campus', location: 'Austin, TX', customer_role: 'Developer', need_count: 26, need_next_offset: offset ? null : 25, needs: offset ? [] : [{ id: 'need-1', project_id: 'project-1', tier: 'Prospect', activity_key: 'construction', required_mw: '12', start_window: '2027', duration: null, supply: 'Unknown' }] }, { id: 'project-2', name: 'South plant', location: 'Austin, TX', customer_role: 'Owner', need_count: 1, need_next_offset: null, needs: [{ id: 'need-2', project_id: 'project-2', tier: 'Signal', activity_key: 'commissioning', required_mw: null, start_window: null, duration: null, supply: 'Unknown' }] }], total: 2, limit: 25, offset: 0, next_offset: null } }) }
    if (url.pathname === '/api/opportunities/needs/need-1') return route.fulfill({ json: { ...accountRow, commercial_disposition: null, name: accountRow.browse_title, workflow_status: 'New', activity: 'construction', rationale: 'Retained project evidence supports review.', signal_evidence_state: 'active', conflict_state: 'Not assessed', associated_account: { company_identity_id: 'company-1', name: 'Northstar Compute', role: 'asset_operator', basis: 'Retained current operator role evidence.', support_status: 'current', evidence_refs: [{ namespace: 'retained-evidence', id: 'evidence-1', retained_evidence_id: 'evidence-1' }] }, intelligence_card: { disposition: 'WATCH', completeness: { supported: 1, total: 2 }, fields: [], contacts: [], evidence: [], research_gaps: [], policy_version: 'test', need_id: 'need-1', project_id: 'project-1', input_fingerprint: 'test', qualification: 'Prospect', next_contact_path: '', next_action: '', last_intelligence_update: '2026-10-20', research_enabled: false }, evidence: [], missing_facts: [] } })
    if (url.pathname === '/api/opportunities/needs/need-unresolved') return route.fulfill({ json: { ...accountRow, id: 'need-unresolved', project_id: 'unresolved-1', name: 'West parcel', browse_title: 'West parcel', commercial_organization: 'Northstar subcontractor', workflow_status: 'New', activity: 'construction', rationale: 'Retained project evidence supports review.', signal_evidence_state: 'active', conflict_state: 'Not assessed', evidence: [], missing_facts: [] } })
    if (url.pathname === '/api/customer-accounts/unresolved') { const offset = Number(url.searchParams.get('offset') ?? 0); return route.fulfill({ json: { items: offset ? [] : [{ project_id: 'unresolved-1', project_name: 'West parcel', location: 'Austin, TX', organization: 'Northstar subcontractor', role: 'Electrical contractor', reason: 'Customer identity needs review.', need_id: 'need-unresolved' }, { project_id: 'unresolved-2', project_name: 'East parcel', location: null, organization: 'Electrical subcontractor', role: 'Electrical contractor', reason: 'No eligible power need.', need_id: null, no_eligible_need: true }], total: 26, limit: 25, offset } }) }
    return route.fulfill({ json: [] })
  })
  await page.goto('/?view=workspace')
  await expect(page.getByRole('heading', { name: 'Customer accounts' })).toBeVisible()
  await expect(page.getByRole('button', { name: /Northstar Compute/ })).toContainText('2 projects · 3 power needs')
  expect(workspaceQueries[0]).toContain('group_by=account')
  await expect(page.locator('.ci-account-list')).not.toContainText('permit')
  await expect(page.locator('.ci-account-list button')).toContainText('data center · Prospect')
  await expect(page.locator('.ci-account-list button')).not.toContainText('NORTHSTAR COMPUTE')
  await page.getByRole('button', { name: /Northstar Compute/ }).focus()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/account=company-1/)
  await expect(page.getByRole('heading', { name: 'Cedar Ridge campus' })).toBeVisible()
  await expect(page.locator('.ci-accounts')).toContainText('Also known as: Northstar')
  await expect(page.locator('.ci-accounts')).not.toContainText('NORTHSTAR COMPUTE')
  await expect(page.locator('.ci-accounts')).toContainText('8 supporting evidence items')
  await page.getByRole('button', { name: 'Cedar Ridge campus' }).click()
  await expect(page).toHaveURL(/project=project-1/)
  await expect(page.locator('.ci-need')).toHaveCount(1)
  await page.reload()
  await expect(page.getByRole('button', { name: 'Cedar Ridge campus' })).toHaveAttribute('aria-pressed', 'true')
  await page.locator('[aria-label="Cedar Ridge campus power need pages"]').getByRole('button', { name: 'Next' }).click()
  await expect(page).toHaveURL(/need_offset=25/)
  await expect(page.locator('.ci-need')).toHaveCount(0)
  await page.locator('[aria-label="Cedar Ridge campus power need pages"]').getByRole('button', { name: 'Previous' }).click()
  await page.getByRole('button', { name: /construction · 12 MW/ }).click()
  await expect(page).toHaveURL(/need=need-1/)
  await expect(page).toHaveURL(/account=company-1/)
  await expect(page).toHaveURL(/project=project-1/)
  await expect(page.locator('.wh-detail')).toBeVisible()
  await expect(page.locator('.wh-tier-badge')).toContainText('WATCH')
  await expect(page.locator('.wh-group-context')).toContainText('Northstar Compute · asset operator')
  await expect(page.locator('.wh-group-context')).toContainText('Buying authority is not established')
  await expect(page.getByRole('button', { name: 'Overview', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await page.reload()
  await expect(page).toHaveURL(/account=company-1/)
  await expect(page).toHaveURL(/project=project-1/)
  await expect(page.getByRole('button', { name: 'Overview', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('.wh-evidence details[open]')).toHaveCount(0)
  await page.goBack()
  await expect(page).toHaveURL(/account=company-1/)
  await expect(page.getByRole('heading', { name: 'Cedar Ridge campus' })).toBeVisible()
  await page.getByRole('button', { name: 'All accounts' }).click()
  await expect(page.locator('.ci-unresolved')).toContainText('Projects needing customer research')
  await page.locator('.ci-unresolved summary').click()
  await expect(page.getByRole('button', { name: 'Review this power need' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Research Electrical subcontractor' })).toHaveAttribute('href', /pursuitQuery=/)
  await expect(page.locator('.ci-unresolved')).toContainText('Customer needs confirmation')
  await page.locator('.ci-unresolved').getByRole('button', { name: 'Next' }).click()
  await expect(page.locator('.ci-unresolved')).not.toContainText('West parcel')
  await page.locator('.ci-unresolved').getByRole('button', { name: 'Previous' }).click()
  await expect(page.locator('.ci-unresolved')).toContainText('West parcel')
  await page.getByRole('button', { name: 'Review this power need' }).click()
  await expect(page).toHaveURL(/need=need-unresolved/)
  await expect(page).not.toHaveURL(/account=/)
  await expect(page.getByRole('button', { name: 'Overview', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
})

test('account deep links reload profile and filters remain server-side', async ({ page }) => {
  const queries: URLSearchParams[] = []
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (url.pathname === '/api/opportunities/workspace') { queries.push(url.searchParams); return route.fulfill({ json: accountWorkspace(url.searchParams, []) }) }
    if (url.pathname === '/api/opportunities/workspace/changes') return route.fulfill({ json: { items: [], counts: { discovered: 0, changed: 0, promoted: 0, closed: 0, review_exception: 0 }, total_unreviewed: 0, offset: 0, limit: 50, next_offset: null, baseline_identity: 'test', token: 'test', source_health_exceptions: [] } })
    if (url.pathname.endsWith('/projects')) return route.fulfill({ json: { account: { company_identity_id: 'company-1', name: 'Northstar Compute', aliases: ['Northstar', 'NORTHSTAR COMPUTE'], project_count: 2, need_count: 3, supporting_evidence_count: 4, last_evidence_update: '2026-10-20' }, items: [], total: 2, limit: 25, offset: 0 } })
    if (url.pathname.endsWith('/unresolved')) return route.fulfill({ json: { items: [], total: 0, limit: 25, offset: 0 } })
    return route.fulfill({ json: [] })
  })
  await page.goto('/?view=workspace&account=company-1')
  await expect(page.getByRole('heading', { name: 'Northstar Compute' })).toBeVisible()
  await expect(page.locator('.ci-accounts')).toContainText('Also known as: Northstar')
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Northstar Compute' })).toBeVisible()
  await page.getByLabel('Search opportunities').fill('Northstar')
  await expect.poll(() => queries.at(-1)?.get('search')).toBe('Northstar')
  expect(queries.at(-1)?.get('group_by')).toBe('account')
  await page.getByRole('button', { name: 'Notifications' }).click()
  await expect(page).not.toHaveURL(/account=/)
  await expect(page.locator('.wh-tools')).toHaveAttribute('open', '')
})

test('primary account pages are server driven and preserve cohort and history', async ({ page }) => {
  const rows = Array.from({ length: 26 }, (_, index) => ({ ...accountRow, id: `need-${index + 1}`, project_id: `project-${index + 1}`, company_identity_id: `company-${index + 1}`, account_name: `Company ${String(index + 1).padStart(2, '0')}` }))
  const queries: URLSearchParams[] = []
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (url.pathname === '/api/opportunities/workspace') {
      const params = url.searchParams, offset = Number(params.get('offset') ?? 0)
      queries.push(new URLSearchParams(params))
      return route.fulfill({ json: { items: rows.slice(offset, offset + 25), total: rows.length, counts: { action_now: 0, research: rows.length, watch: 0, reject: 0 }, offset, limit: 25, next_offset: offset + 25 < rows.length ? offset + 25 : null, cohort_token: 'fixed-account-cohort', count_unit: 'company accounts', changes_available: false } })
    }
    if (url.pathname === '/api/opportunities/workspace/changes') return route.fulfill({ json: { items: [], counts: { discovered: 0, changed: 0, promoted: 0, closed: 0, review_exception: 0 }, total_unreviewed: 0, offset: 0, limit: 50, next_offset: null, baseline_identity: 'test', token: 'test', source_health_exceptions: [] } })
    if (url.pathname.endsWith('/unresolved')) return route.fulfill({ json: { items: [], total: 0, limit: 25, offset: 0 } })
    if (url.pathname.endsWith('/projects')) return route.fulfill({ json: { items: [], total: 0, limit: 25, offset: 0 } })
    return route.fulfill({ json: [] })
  })
  await page.goto('/?view=workspace')
  await expect(page.locator('.ci-account-list button')).toHaveCount(25)
  const pager = page.getByRole('navigation', { name: 'Customer account pages' })
  await expect(pager).toContainText('Accounts 1–25 of 26')
  await pager.getByRole('button', { name: 'Next' }).click()
  await expect(page).toHaveURL(/offset=25/)
  await expect(page).toHaveURL(/cohort_token=fixed-account-cohort/)
  await expect(page.locator('.ci-account-list button')).toHaveCount(1)
  expect(queries.at(-1)?.get('offset')).toBe('25')
  expect(queries.at(-1)?.get('cohort_token')).toBe('fixed-account-cohort')
  await page.goBack()
  await expect(page.locator('.ci-account-list button')).toHaveCount(25)
  await page.goForward()
  await expect(page.locator('.ci-account-list button')).toHaveCount(1)
  await page.getByLabel('Search opportunities').fill('Company')
  await expect.poll(() => queries.at(-1)?.get('search')).toBe('Company')
  expect(queries.at(-1)?.get('offset')).toBe('0')
  expect(queries.at(-1)?.get('cohort_token')).toBeNull()
})

test('primary account pager resets a stale cohort on 409', async ({ page }) => {
  const rows = Array.from({ length: 26 }, (_, index) => ({ ...accountRow, id: `need-${index + 1}`, project_id: `project-${index + 1}`, company_identity_id: `company-${index + 1}`, account_name: `Company ${String(index + 1).padStart(2, '0')}` }))
  const queries: URLSearchParams[] = []
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (url.pathname === '/api/opportunities/workspace') {
      const params = url.searchParams, offset = Number(params.get('offset') ?? 0)
      queries.push(new URLSearchParams(params))
      if (offset === 25) return route.fulfill({ status: 409, json: { detail: 'cohort expired' } })
      return route.fulfill({ json: { items: rows.slice(offset, offset + 25), total: rows.length, counts: { action_now: 0, research: rows.length, watch: 0, reject: 0 }, offset, limit: 25, next_offset: 25, cohort_token: 'fresh-account-cohort', count_unit: 'company accounts', changes_available: false } })
    }
    if (url.pathname === '/api/opportunities/workspace/changes') return route.fulfill({ json: { items: [], counts: { discovered: 0, changed: 0, promoted: 0, closed: 0, review_exception: 0 }, total_unreviewed: 0, offset: 0, limit: 50, next_offset: null, baseline_identity: 'test', token: 'test', source_health_exceptions: [] } })
    if (url.pathname.endsWith('/unresolved')) return route.fulfill({ json: { items: [], total: 0, limit: 25, offset: 0 } })
    if (url.pathname.endsWith('/projects')) return route.fulfill({ json: { items: [], total: 0, limit: 25, offset: 0 } })
    return route.fulfill({ json: [] })
  })
  await page.goto('/?view=workspace&account=company-1')
  await expect(page.getByRole('heading', { name: 'Company 01' })).toBeVisible()
  await page.getByRole('navigation', { name: 'Customer account pages' }).getByRole('button', { name: 'Next' }).click()
  await expect.poll(() => queries.length).toBe(3)
  await expect.poll(() => new URL(page.url()).searchParams.get('offset')).toBe('0')
  await expect.poll(() => new URL(page.url()).searchParams.get('cohort_token')).toBeNull()
  await expect(page).toHaveURL(/account=company-1/)
  await expect(page.getByRole('heading', { name: 'Company 01' })).toBeVisible()
  expect(queries[1].get('cohort_token')).toBe('fresh-account-cohort')
  expect(queries[2].get('offset')).toBe('0')
  expect(queries[2].get('cohort_token')).toBeNull()
})

test('expired workspace cohort restarts pagination and keeps the selected account profile', async ({ page }) => {
  let requests = 0
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (url.pathname === '/api/opportunities/workspace') {
      requests += 1
      if (requests === 1) return route.fulfill({ status: 409, json: { detail: 'cohort expired' } })
      return route.fulfill({ json: accountWorkspace(url.searchParams) })
    }
    if (url.pathname === '/api/opportunities/workspace/changes') return route.fulfill({ json: { items: [], counts: { discovered: 0, changed: 0, promoted: 0, closed: 0, review_exception: 0 }, total_unreviewed: 0, offset: 0, limit: 50, next_offset: null, baseline_identity: 'test', token: 'test', source_health_exceptions: [] } })
    if (url.pathname.endsWith('/projects')) return route.fulfill({ json: { items: [], total: 0, limit: 25, offset: 0 } })
    if (url.pathname.endsWith('/unresolved')) return route.fulfill({ json: { items: [], total: 0, limit: 25, offset: 0 } })
    return route.fulfill({ json: [] })
  })
  await page.goto('/?view=workspace&account=company-1&offset=25&cohort_token=expired')
  await expect(page.getByRole('heading', { name: 'Northstar Compute' })).toBeVisible()
  await expect.poll(() => new URL(page.url()).searchParams.get('offset')).toBe('0')
  await expect.poll(() => new URL(page.url()).searchParams.get('cohort_token')).toBeNull()
  await expect(page).toHaveURL(/account=company-1/)
  expect(requests).toBe(2)
})

test('account project errors expose an explicit retry without changing the account route', async ({ page }) => {
  let attempts = 0
  let unavailable = true
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (url.pathname === '/api/opportunities/workspace') return route.fulfill({ json: accountWorkspace(url.searchParams, []) })
    if (url.pathname === '/api/opportunities/workspace/changes') return route.fulfill({ json: { items: [], counts: { discovered: 0, changed: 0, promoted: 0, closed: 0, review_exception: 0 }, total_unreviewed: 0, offset: 0, limit: 50, next_offset: null, baseline_identity: 'test', token: 'test', source_health_exceptions: [] } })
    if (url.pathname.endsWith('/projects')) {
      attempts += 1
      if (unavailable) return route.fulfill({ status: 503, json: { detail: 'temporarily unavailable' } })
      return route.fulfill({ json: { account: { company_identity_id: 'company-1', name: 'Northstar Compute', project_count: 2, need_count: 3 }, items: [], total: 2, limit: 25, offset: 0 } })
    }
    if (url.pathname.endsWith('/unresolved')) return route.fulfill({ json: { items: [], total: 0, limit: 25, offset: 0 } })
    return route.fulfill({ json: [] })
  })
  await page.goto('/?view=workspace&account=company-1')
  await expect(page.locator('.ci-accounts')).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('could not load this account')
  await expect(page).toHaveURL(/account=company-1/)
  unavailable = false
  await page.getByRole('alert').getByRole('button', { name: 'Retry' }).click()
  await expect(page.getByRole('heading', { name: 'Northstar Compute' })).toBeVisible()
  expect(attempts).toBeGreaterThanOrEqual(2)
})

test('unresolved customer project failures remain visible and retry successfully', async ({ page }) => {
  let attempts = 0
  let unavailable = true
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (url.pathname === '/api/opportunities/workspace') return route.fulfill({ json: accountWorkspace(url.searchParams, []) })
    if (url.pathname === '/api/opportunities/workspace/changes') return route.fulfill({ json: { items: [], counts: { discovered: 0, changed: 0, promoted: 0, closed: 0, review_exception: 0 }, total_unreviewed: 0, offset: 0, limit: 50, next_offset: null, baseline_identity: 'test', token: 'test', source_health_exceptions: [] } })
    if (url.pathname.endsWith('/unresolved')) {
      attempts += 1
      if (unavailable) return route.fulfill({ status: 503, json: { detail: 'temporarily unavailable' } })
      return route.fulfill({ json: { items: [], total: 0, limit: 25, offset: 0 } })
    }
    return route.fulfill({ json: [] })
  })
  await page.goto('/?view=workspace')
  await page.locator('.ci-unresolved summary').click()
  await expect(page.locator('.ci-unresolved')).toContainText('Unresolved customer projects could not be loaded')
  unavailable = false
  await page.locator('.ci-unresolved').getByRole('button', { name: 'Retry' }).click()
  await expect(page.locator('.ci-unresolved')).toContainText('(0)')
  expect(attempts).toBeGreaterThanOrEqual(2)
})

for (const scenario of [
  { label: 'mismatched account identity', association: { company_identity_id: 'company-2', name: 'Different Operator', role: 'asset_operator', basis: 'Current retained operator evidence.', support_status: 'current', evidence_refs: [] }, notice: 'Current evidence associates this need with Different Operator.' },
  { label: 'retracted account identity', association: null, notice: 'current evidence does not support an account association' },
]) {
  test(`detail clears a ${scenario.label} from the saved account URL`, async ({ page }) => {
    await page.route(url => url.pathname.startsWith('/api/'), async route => {
      const url = new URL(route.request().url())
      if (url.pathname === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
      if (url.pathname === '/api/opportunities/workspace') return route.fulfill({ json: accountWorkspace(url.searchParams) })
      if (url.pathname === '/api/opportunities/workspace/changes') return route.fulfill({ json: { items: [], counts: { discovered: 0, changed: 0, promoted: 0, closed: 0, review_exception: 0 }, total_unreviewed: 0, offset: 0, limit: 50, next_offset: null, baseline_identity: 'test', token: 'test', source_health_exceptions: [] } })
      if (url.pathname === '/api/customer-accounts/company-1/projects') return route.fulfill({ json: { account: { company_identity_id: 'company-1', name: 'Northstar Compute', aliases: [], project_count: 1, need_count: 1 }, items: [], total: 1, limit: 25, offset: 0 } })
      if (url.pathname === '/api/opportunities/needs/need-1') return route.fulfill({ json: { id: 'need-1', project_id: 'project-1', name: 'Cedar Ridge campus', location: 'Austin, TX', tier: 'Prospect', workflow_status: 'UNKNOWN', activity: 'construction', rationale: 'Review required.', signal_evidence_state: 'active_evidence', required_mw: null, start_window: null, duration: null, supply: 'Unknown', next_action: 'Research', conflict_state: 'unknown', evidence: [], associated_account: scenario.association } })
      if (url.pathname === '/api/power-needs/need-1/brief') return route.fulfill({ json: { status: 'unavailable' } })
      if (url.pathname === '/api/power-needs/need-1/title') return route.fulfill({ json: { status: 'unavailable', result: null, citations: [], generated_at: null, model: null } })
      if (url.pathname === '/api/customer-accounts/unresolved') return route.fulfill({ json: { items: [], total: 0, limit: 25, offset: 0 } })
      return route.fulfill({ json: [] })
    })
    await page.goto('/?view=workspace&account=company-1&project=project-1&need=need-1')
    await expect(page.locator('.wh-detail')).toBeVisible()
    await expect(page.locator('.wh-integrity')).toContainText(scenario.notice)
    await expect(page).toHaveURL(/need=need-1/)
    await expect(page).not.toHaveURL(/account=/)
    await expect(page).not.toHaveURL(/project=/)
    await expect(page.locator('.wh-record-identity')).toContainText('Cedar Ridge campus')
    if (scenario.association) await expect(page.locator('.wh-group-context')).toContainText('Different Operator')
    else await expect(page.locator('.wh-group-context')).toHaveCount(0)
  })
}
