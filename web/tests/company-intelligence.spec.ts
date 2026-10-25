import { expect, test } from '@playwright/test'

const account = {
  id: 'need-1', project_id: 'project-1', browse_title: 'Cedar Ridge campus', location: 'Austin, TX', tier: 'Prospect', activity_key: 'construction', required_mw: '12', start_window: '2027', duration: null, supply: 'Unknown',
  evidence_count: 1, commercial_disposition: null, commercial_reason: 'Timing requires confirmation.', commercial_next_question: 'Who controls power procurement?', commercial_next_action: 'Verify the project power package.', commercial_organization: 'Northstar Compute',
  company_identity_id: 'company-1', account_name: 'Northstar Compute', account_aliases: [], asset_type: 'data_center', supporting_evidence_count: 0, last_evidence_update: null,
  project_count: 0, need_count: 0, matching_project_count: 0, matching_need_count: 0,
}
const workspace = (params: URLSearchParams, includeSecond = false) => ({ items: includeSecond ? [account, { ...account, id: 'need-2', project_id: 'project-2', company_identity_id: 'company-2', account_name: 'Northstar Labs', commercial_organization: 'Northstar Labs', project_count: 2, need_count: 2 }] : [account], total: includeSecond ? 2 : 1, counts: { action_now: 0, research: includeSecond ? 2 : 1, watch: 0, reject: 0 }, offset: Number(params.get('offset') ?? 0), limit: 25, next_offset: null, cohort_token: 'accounts-cohort', count_unit: 'company accounts', changes_available: false })
const graph = {
  company: { id: 'company-1', display_name: 'Northstar Compute', identifiers: [], aliases: [] },
  projects: [], relationships: [], evidence: [], limits: { projects: 100, relationships: 100 },
}

async function setup(page: import('@playwright/test').Page, options: { failGraph?: boolean; includeSecond?: boolean; includeEvidence?: boolean; includeImports?: boolean } = {}) {
  let failed = options.failGraph ?? false
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (url.pathname === '/api/opportunities/workspace') return route.fulfill({ json: workspace(url.searchParams, options.includeSecond) })
    if (url.pathname === '/api/opportunities/workspace/changes') return route.fulfill({ json: { items: [], counts: { discovered: 0, changed: 0, promoted: 0, closed: 0, review_exception: 0 }, total_unreviewed: 0, offset: 0, limit: 50, next_offset: null, baseline_identity: 'test', token: 'test', source_health_exceptions: [] } })
    if (url.pathname.endsWith('/projects')) {
      const companyId = url.pathname.split('/').at(-2) ?? 'company-1'
      const name = companyId === 'company-2' ? 'Northstar Labs' : 'Northstar Compute'
      return route.fulfill({ json: { account: { company_identity_id: companyId, name, project_count: companyId === 'company-2' ? 2 : 0, need_count: companyId === 'company-2' ? 2 : 0 }, items: [], total: 0, limit: 25, offset: 0 } })
    }
    if (url.pathname.endsWith('/contacts')) return route.fulfill({ json: { company_id: 'company-1', research_required: true, contacts: [], imported_unverified: options.includeImports ? [{ import_row_id: 'row-1', batch_id: 'batch-1', sheet: 'Leads', row_number: 7, company: 'Northstar Compute', name: 'Imported Person', title: 'Facilities', email: 'imported@example.invalid', phone: null, profile_url: null, assertion_status: 'imported_unverified', mailbox_verified: false }] : [] } })
    if (url.pathname.startsWith('/api/companies/') && url.pathname.endsWith('/graph')) {
      if (failed) return route.fulfill({ status: 503, json: { detail: 'unavailable' } })
      const companyId = url.pathname.split('/').at(-2) ?? 'company-1'
      const payload = options.includeEvidence ? {
        company: { ...graph.company, identifiers: [{ identifier_type: 'domain', value: 'northstar.example', evidence: { id: 'ev-1', title: 'Company project page', url: 'https://sources.example/project', source_id: 'source-1', content_hash: 'hash-1', observed_at: null } }], aliases: [{ identifier_type: 'alias', value: 'Northstar HQ', evidence: { id: 'ev-1', title: 'Company project page', url: 'https://sources.example/project', source_id: 'source-1', content_hash: 'hash-1', observed_at: null } }] },
        projects: [{ id: 'project-1', name: 'Cedar Ridge campus', location: 'Austin, TX', roles: [{ role: 'developer', organization_name: null, state: 'current', evidence: { id: 'ev-1', title: 'Company project page', url: 'https://sources.example/project', source_id: 'source-1', content_hash: 'hash-1', observed_at: null } }] }],
        relationships: [{ id: 'relationship-1', source_company_id: companyId, target_company_id: 'company-2', relationship_type: 'developer_of', status: 'current', version: 1, support_status: 'operator_assertion_unverified', reason: null, source_quote: 'Northstar may develop this project.', evidence: { id: 'ev-1', title: 'Company project page', url: 'javascript:alert(1)', source_id: 'source-1', content_hash: 'hash-1', observed_at: null } }],
        evidence: [{ id: 'ev-1', title: 'Company project page', url: 'https://sources.example/project', source_id: 'source-1', content_hash: 'hash-1', observed_at: null }], limits: graph.limits,
      } : graph
      return route.fulfill({ json: { ...payload, company: { ...payload.company, id: companyId, display_name: companyId === 'company-2' ? 'Northstar Labs' : 'Northstar Compute' } } })
    }
    if (url.pathname.endsWith('/unresolved')) return route.fulfill({ json: { items: [], total: 0, limit: 25, offset: 0 } })
    return route.fulfill({ json: [] })
  })
  return { allowGraph: () => { failed = false } }
}

test('company graph shows explicit unknowns and only evidence-backed aliases and safe source links', async ({ page }) => {
  await setup(page)
  await page.goto('/?view=workspace&account=company-1&accountBrowse=1')
  const panel = page.getByRole('region', { name: 'Company graph' })
  await expect(panel).toContainText('Identifiers not established.')
  await expect(panel).toContainText('Aliases not established by retained evidence.')
  await expect(panel).toContainText('No linked projects are established.')
  await expect(panel).toContainText('No company relationship assertions are available.')
  await expect(panel.getByText('Northstar', { exact: true })).toHaveCount(0)
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
})

test('company graph failure can be retried within the existing account panel', async ({ page }) => {
  const state = await setup(page, { failGraph: true })
  await page.goto('/?view=workspace&account=company-1&accountBrowse=1')
  const panel = page.getByRole('region', { name: 'Company graph' })
  await expect(panel).toContainText('Company context is unavailable.')
  state.allowGraph()
  await panel.getByRole('button', { name: 'Retry context' }).click()
  await expect(panel).toContainText('Identifiers not established.')
})

test('company graph switches identity when the selected account changes', async ({ page }) => {
  await setup(page, { includeSecond: true })
  await page.goto('/?view=workspace&account=company-1&accountBrowse=1')
  const panel = page.getByRole('region', { name: 'Company graph' })
  await expect(panel).toContainText('Northstar Compute')
  await page.getByRole('button', { name: 'All accounts' }).click()
  await page.getByRole('button', { name: '2 projects · 2 needs' }).click()
  await expect(panel).toContainText('Northstar Labs')
  await expect(panel).not.toContainText('Northstar Compute')
})

test('company graph displays nested evidence and permits only safe source URLs', async ({ page }) => {
  await setup(page, { includeEvidence: true })
  await page.goto('/?view=workspace&account=company-1&accountBrowse=1')
  const panel = page.getByRole('region', { name: 'Company graph' })
  await expect(panel.getByText('Northstar HQ')).toBeVisible()
  await expect(panel).toContainText('domain: northstar.example')
  await expect(panel).toContainText('Unverified operator assertion')
  await expect(panel).toContainText('Ledger state: current')
  await expect(panel).toContainText('Source quote')
  await expect(panel).toContainText('Their ledger state does not independently verify the relationship as fact.')
  await expect(panel).toContainText('Northstar may develop this project.')
  await expect(panel).not.toContainText('Verified relationship')
  await expect(panel.getByRole('link', { name: 'Open source' }).first()).toHaveAttribute('href', 'https://sources.example/project')
  await expect(panel.locator('a[href^="javascript:"]')).toHaveCount(0)
})

test('imported contact assertions stay visibly unverified and are not clickable routes', async ({ page }) => {
  await setup(page, { includeImports: true })
  await page.goto('/?view=workspace&account=company-1&accountBrowse=1')
  const panel = page.getByRole('region', { name: 'Contacts & Buying Chain' })
  await expect(panel).toContainText('Imported contacts · unverified')
  await expect(panel).toContainText('Imported assertions have not been verified.')
  await expect(panel.getByText('imported@example.invalid')).toBeVisible()
  await expect(panel.getByRole('link', { name: 'imported@example.invalid' })).toHaveCount(0)
})
