import { expect, test, type Page } from '@playwright/test'

const validUntil = new Date(Date.now() + 60 * 60 * 1000).toISOString()
const evidence = {
  id: 'ev-1',
  title: 'Company project page',
  url: 'https://sources.example/project',
  source_id: 'source-1',
  content_hash: 'hash-1',
  observed_at: null,
}
const opportunity = (needId: string, projectId: string, companyId: string, companyName: string) => ({
  id: needId,
  project_id: projectId,
  name: 'Cedar Ridge campus',
  browse_title: 'Cedar Ridge campus',
  location: 'Austin, TX',
  activity: 'construction',
  tier: 'Prospect',
  rationale: 'Current retained evidence describes a campus project.',
  required_mw: '12',
  start_window: '2027',
  duration: null,
  supply: 'Unknown',
  evidence_count: 1,
  commercial_disposition: null,
  commercial_reason: 'Timing requires confirmation.',
  commercial_next_question: 'Who controls power procurement?',
  commercial_next_action: 'Verify the project power package.',
  commercial_organization: companyName,
  associated_account: {
    company_identity_id: companyId,
    name: companyName,
    role: 'owner_developer',
    basis: 'retained_source',
    support_status: 'current',
  },
  intelligence_card: {
    qualification: 'Prospect',
    evidence: [],
    contacts: [],
    fields: [],
    completeness: { supported: 0, total: 0 },
    ...(companyId === 'company-1' ? { evidence: [{
      reference: 'ev-1', title: evidence.title, url: evidence.url,
      source_date: '2026-10-27', verification_status: 'retained',
      extraction_method: 'source record', passage: 'Project construction is under way.',
    }] } : {}),
  },
  evidence: [],
  rank_reasons: [],
  contact: null,
  qualified_remaining_gap: null,
})

const projectPage = {
  items: [
    {
      id: 'project-view-1', project_id: 'project-1', project_ids: ['project-1'],
      name: 'Cedar Ridge campus', company: 'Northstar Compute', location: 'Austin, TX',
      sector: 'data_centers', asset_type: 'data_center', priority_score: 10,
      representative_need_id: 'need-1',
      needs: [{ id: 'need-1', project_id: 'project-1', name: 'Cedar Ridge campus',
        browse_title: 'Cedar Ridge campus', location: 'Austin, TX', activity: 'construction',
        tier: 'Prospect', commercial_preview: { disposition: 'RESEARCH' } }],
      need_count: 1, event: null, contact: [], contact_people: [], power_summary: null,
      power_amount_class: 'unknown', power_summary_kind: 'unknown', next_action: null,
      updated_at: '2026-10-27T00:00:00Z',
    },
    {
      id: 'project-view-2', project_id: 'project-2', project_ids: ['project-2'],
      name: 'Cedar Ridge campus', company: 'Northstar Labs', location: 'Austin, TX',
      sector: 'data_centers', asset_type: 'data_center', priority_score: 9,
      representative_need_id: 'need-2',
      needs: [{ id: 'need-2', project_id: 'project-2', name: 'Cedar Ridge campus',
        browse_title: 'Cedar Ridge campus', location: 'Austin, TX', activity: 'construction',
        tier: 'Prospect', commercial_preview: { disposition: 'RESEARCH' } }],
      need_count: 1, event: null, contact: [], contact_people: [], power_summary: null,
      power_amount_class: 'unknown', power_summary_kind: 'unknown', next_action: null,
      updated_at: '2026-10-27T00:00:00Z',
    },
  ],
  total: 2, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'projects-cohort',
  generation: 'generation-1', generation_id: 'generation-1', as_of: '2026-10-27T00:00:00Z',
  valid_until: validUntil, qualification_state: 'current', refresh_state: 'current',
}

const emptyGraph = (companyId: string) => ({
  company: { id: companyId, display_name: companyId === 'company-2' ? 'Northstar Labs' : 'Northstar Compute', identifiers: [], aliases: [] },
  projects: [], relationships: [], evidence: [], limits: { projects: 100, relationships: 100 },
})

async function setup(page: Page, options: { failGraph?: boolean; includeEvidence?: boolean; includeImports?: boolean } = {}) {
  let failed = options.failGraph ?? false
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const url = new URL(route.request().url())
    const path = url.pathname
    if (path === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (path === '/api/opportunities/projects') {
      return route.fulfill({ json: projectPage })
    }
    if (path === '/api/opportunities/needs/need-1') {
      return route.fulfill({ json: opportunity('need-1', 'project-1', 'company-1', 'Northstar Compute') })
    }
    if (path === '/api/opportunities/needs/need-2') {
      return route.fulfill({ json: opportunity('need-2', 'project-2', 'company-2', 'Northstar Labs') })
    }
    if (path === '/api/opportunities/demand-summary') {
      return route.fulfill({ json: {
        sector: 'all', availability: 'unavailable', as_of: null,
        totals: { identified_records: 0, known_mw_records: 0, unknown_records: 0, conflicted_records: 0 },
        classes: { documented: { mw: null, record_count: 0 }, calculated: { mw: null, record_count: 0 }, estimated: { mw: null, record_count: 0 } },
        provenance: { contract: 'test', source_count: 0, latest_evidence_at: null }, limitations: [],
      } })
    }
    if (path.startsWith('/api/companies/') && path.endsWith('/projects')) {
      const companyId = path.split('/').at(-2) ?? 'company-1'
      return route.fulfill({ json: {
        account: { company_identity_id: companyId, name: companyId === 'company-2' ? 'Northstar Labs' : 'Northstar Compute', project_count: 1, need_count: 1 },
        items: [], total: 0, limit: 25, offset: 0,
      } })
    }
    if (path.endsWith('/contacts')) {
      return route.fulfill({ json: {
        company_id: 'company-1', research_required: true, contacts: [],
        imported_unverified: options.includeImports ? [{ import_row_id: 'row-1', batch_id: 'batch-1', sheet: 'Leads', row_number: 7, company: 'Northstar Compute', name: 'Imported Person', title: 'Facilities', email: 'imported@example.invalid', phone: null, profile_url: null, assertion_status: 'imported_unverified', mailbox_verified: false }] : [],
      } })
    }
    if (path.startsWith('/api/companies/') && path.endsWith('/graph')) {
      if (failed) return route.fulfill({ status: 503, json: { detail: 'unavailable' } })
      const companyId = path.split('/').at(-2) ?? 'company-1'
      const payload = options.includeEvidence ? {
        company: {
          ...emptyGraph(companyId).company,
          identifiers: [{ identifier_type: 'domain', value: 'northstar.example', evidence }],
          aliases: [{ identifier_type: 'alias', value: 'Northstar HQ', evidence }],
        },
        projects: [{ id: 'project-1', name: 'Cedar Ridge campus', location: 'Austin, TX', roles: [{ role: 'developer', organization_name: null, state: 'current', evidence }] }],
        relationships: [{ id: 'relationship-1', source_company_id: companyId, target_company_id: 'company-2', relationship_type: 'developer_of', status: 'current', version: 1, support_status: 'operator_assertion_unverified', reason: null, source_quote: 'Northstar may develop this project.', evidence: { ...evidence, url: 'javascript:alert(1)' } }],
        evidence: [{ id: 'ev-1', title: evidence.title, url: evidence.url, source_id: evidence.source_id, content_hash: evidence.content_hash, observed_at: null }],
        limits: { projects: 100, relationships: 100 },
      } : emptyGraph(companyId)
      return route.fulfill({ json: payload })
    }
    if (path.endsWith('/unresolved')) return route.fulfill({ json: { items: [], total: 0, limit: 25, offset: 0 } })
    return route.fulfill({ json: [] })
  })
  return { allowGraph: () => { failed = false } }
}

const auditUrl = (needId = 'need-1') => `/?view=workspace&projectBrowse=1&need=${needId}&section=evidence`

async function openAccountRelationship(page: Page) {
  await expect(page.getByRole('heading', { name: 'Evidence & Sources' })).toBeVisible()
  await page.getByText('Account relationship and contacts', { exact: true }).click()
  return page.getByRole('region', { name: 'Contacts & Buying Chain' })
}

test('company graph shows explicit unknowns and only evidence-backed aliases and safe source links', async ({ page }) => {
  await setup(page)
  await page.goto(auditUrl())
  const panel = await openAccountRelationship(page)
  await expect(panel).toContainText('Identifiers not established.')
  await expect(panel).toContainText('Aliases not established by retained evidence.')
  await expect(panel).toContainText('No linked projects are established.')
  await expect(panel).toContainText('No company relationship assertions are available.')
  await expect(panel.getByText('Northstar', { exact: true })).toHaveCount(0)
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
})

test('company graph failure can be retried from the explicit project audit detail', async ({ page }) => {
  const state = await setup(page, { failGraph: true })
  await page.goto(auditUrl())
  const panel = await openAccountRelationship(page)
  await expect(panel).toContainText('Company context is unavailable.')
  state.allowGraph()
  await panel.getByRole('button', { name: 'Retry context' }).click()
  await expect(panel).toContainText('Identifiers not established.')
})

test('company graph switches identity when the selected project need changes', async ({ page }) => {
  await setup(page)
  await page.goto(auditUrl('need-1'))
  let panel = await openAccountRelationship(page)
  await expect(panel).toContainText('Northstar Compute')
  await page.goto(auditUrl('need-2'))
  panel = await openAccountRelationship(page)
  await expect(panel).toContainText('Northstar Labs')
  await expect(panel).not.toContainText('Northstar Compute')
})

test('company graph displays nested evidence and permits only safe source URLs', async ({ page }) => {
  await setup(page, { includeEvidence: true })
  await page.goto(auditUrl())
  const panel = await openAccountRelationship(page)
  await expect(panel.getByText('Northstar HQ')).toBeVisible()
  await expect(panel).toContainText('domain: northstar.example')
  await expect(panel).toContainText('Unverified operator assertion')
  await expect(panel).toContainText('Ledger state: current')
  await expect(panel).toContainText('Source quote')
  await expect(panel).toContainText('Their ledger state does not independently verify the relationship as fact.')
  await expect(panel).toContainText('Northstar may develop this project.')
  await expect(panel.getByRole('link', { name: 'Open source' }).first()).toHaveAttribute('href', 'https://sources.example/project')
  await expect(panel.locator('a[href^="javascript:"]')).toHaveCount(0)
})

test('imported contact assertions stay visibly unverified and are not clickable routes', async ({ page }) => {
  await setup(page, { includeImports: true })
  await page.goto(auditUrl())
  const panel = await openAccountRelationship(page)
  await expect(panel).toContainText('Imported contacts · unverified')
  await expect(panel).toContainText('Imported assertions have not been verified.')
  await expect(panel.getByText('imported@example.invalid')).toBeVisible()
  await expect(panel.getByRole('link', { name: 'imported@example.invalid' })).toHaveCount(0)
})
