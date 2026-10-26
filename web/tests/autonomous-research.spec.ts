import { expect, test } from '@playwright/test'

const need = {
  id: 'need-demo', project_id: 'project-demo', name: 'Ridgeview commissioning', browse_title: 'Ridgeview commissioning', title_status: 'unavailable',
  location: 'Austin, TX', tier: 'Prospect', workflow_status: 'UNKNOWN', activity: 'commissioning', rationale: 'Current source-backed project opportunity.',
  signal_evidence_state: 'active_evidence', required_mw: null, qualified_remaining_gap: null, start_window: null, duration: null, supply: 'Unknown',
  next_action: 'Current timing is unknown.', conflict_state: 'clear', missing_facts: ['Temporary demand', 'Power start date'], evidence: [],
  intelligence_card: {
    policy_version: 'test', need_id: 'need-demo', project_id: 'project-demo', input_fingerprint: 'test', qualification: 'Prospect', disposition: 'RESEARCH',
    fields: [{ key: 'project', label: 'Project', section: 'identity', status: 'Verified', value: 'Ridgeview commissioning', basis: 'Publisher filing' }, { key: 'customer', label: 'Company', section: 'identity', status: 'Verified', value: 'Ridgeview Energy', basis: 'Publisher filing' }],
    contacts: [{ claim_id: 'contact-1', company: 'Ridgeview Energy', name: 'Morgan Lee', title: 'Director, Construction', role: 'Project buyer', responsibility: 'Verified project responsibility', purchasing_authority: 'Purchasing authority requires confirmation', methods: [{ kind: 'email', value: 'morgan@example.test', href: 'mailto:morgan@example.test' }], verified_at: '2026-10-25T00:00:00Z', sources: [] }],
    next_contact_path: 'Verified business email available', next_action: 'Review current gap evidence', research_gaps: [{ key: 'demand', label: 'Temporary demand', section: 'power', status: 'Not publicly available', value: null, basis: 'No current source supports activity demand.' }],
    completeness: { supported: 2, total: 5 }, last_intelligence_update: '2026-10-25T00:00:00Z', power_gap: null, evidence: [], research_enabled: true,
  },
} as const

const workspace = { items: [need], total: 1, offset: 0, limit: 25, next_offset: null, cohort_token: 'cohort', count_unit: 'power needs', counts: {} }

async function install(page: import('@playwright/test').Page) {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?**', route => route.fulfill({ json: workspace }))
  await page.route('**/api/opportunities/needs/need-demo**', route => route.fulfill({ json: need }))
  await page.route('**/api/commercial/triage/need-demo/autonomous-research', route => route.fulfill({ json: { items: [] } }))
}

test('Research shows source-backed contacts, separate priority and confidence, explicit unknowns, and read-only history on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await install(page)
  const writes: string[] = []
  await page.route('**/api/**', async route => {
    if (route.request().method() !== 'GET' && !route.request().url().includes('/api/auth/session')) writes.push(`${route.request().method()} ${route.request().url()}`)
    await route.fallback()
  })
  await page.goto('/?view=pursuits')
  await expect(page.getByRole('heading', { name: 'Research', exact: true })).toBeVisible()
  await page.getByRole('button', { name: /Ridgeview Energy/ }).click()
  await expect(page.getByRole('heading', { name: 'Ridgeview commissioning' })).toBeVisible()
  await expect(page.getByText('morgan@example.test')).toBeVisible()
  await expect(page.getByText('Purchasing authority requires confirmation')).toBeVisible()
  await expect(page.getByText('Confidence', { exact: true })).toBeVisible()
  await expect(page.locator('.research-detail-heading dd').filter({ hasText: 'Not provided' })).toBeVisible()
  await expect(page.getByText(/Temporary demand: Unknown/)).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Automated research' })).toBeVisible()
  await expect(page.getByRole('button', { name: /call|fact|workflow|enrich|correct|retract|research this question|save/i })).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: test.info().outputPath('mobile-research.png'), fullPage: true })
  expect(writes).toEqual([])
})

test('global search groups projects, companies and verified contacts and opens a matching need', async ({ page }) => {
  await install(page)
  await page.route('**/api/search?**', route => route.fulfill({ json: {
    query: 'Morgan', projects: [{ project_id: 'project-demo', need_id: 'need-demo', name: 'Ridgeview commissioning', location: 'Austin, TX', region_state: 'TX', tier: 'Prospect', updated_at: '2026-10-25T00:00:00Z' }],
    companies: [{ company_identity_id: 'company-demo', name: 'Ridgeview Energy', project_count: 1 }],
    contacts: [{ company_identity_id: 'company-demo', project_id: 'project-demo', need_id: 'need-demo', name: 'Morgan Lee', title: 'Director, Construction', organization: 'Ridgeview Energy', methods: [{ kind: 'email', value: 'morgan@example.test' }], sources: [], verification_status: 'verified' }], opportunities: [],
  } }))
  await page.goto('/?view=workspace')
  const search = page.getByRole('searchbox', { name: 'Search companies, projects, contacts and opportunities' })
  await search.fill('Morgan')
  await expect(page.getByRole('heading', { name: 'Contacts' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: test.info().outputPath('mobile-search.png'), fullPage: true })
  await page.getByRole('button', { name: /Morgan Lee/ }).click()
  await expect(page.getByRole('heading', { name: 'Ridgeview Energy' })).toBeVisible()
  await expect(page.getByText('Current timing is unknown.')).toBeVisible()
})

test('global search opens compact opportunity hits and drops prior results after a failed query', async ({ page }) => {
  await install(page)
  await page.route('**/api/search?**', route => {
    const query = new URL(route.request().url()).searchParams.get('q')
    if (query === 'Failure') return route.fulfill({ status: 503, json: { detail: 'unavailable' } })
    return route.fulfill({ json: {
      query, projects: [], companies: [], contacts: [],
      opportunities: [{ id: 'need-demo', project_id: 'project-demo', name: 'Ridgeview commissioning', location: 'Austin, TX', tier: 'Prospect', activity: 'commissioning', rank_score: 82, sources: [] }],
    } })
  })
  await page.goto('/?view=workspace')
  const search = page.getByRole('searchbox', { name: 'Search companies, projects, contacts and opportunities' })
  await search.fill('Ridgeview')
  await expect(page.getByRole('button', { name: /Ridgeview commissioning/ })).toBeEnabled()
  await page.getByRole('button', { name: /Ridgeview commissioning/ }).click()
  await expect(page.getByRole('heading', { name: 'Ridgeview Energy' })).toBeVisible()
  await page.goBack()
  await search.fill('Failure')
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.locator('.global-search-results').getByRole('button', { name: /Ridgeview commissioning/ })).toHaveCount(0)
})

test('global search reports qualification pending without claiming there are no matches', async ({ page }) => {
  await install(page)
  await page.route('**/api/search?**', route => route.fulfill({ json: {
    query: 'Ridgeview', companies_status: 'qualification_pending', opportunities_status: 'qualification_pending',
    projects: [], companies: [], contacts: [], opportunities: [],
  } }))
  await page.goto('/?view=workspace')
  await page.getByRole('searchbox', { name: 'Search companies, projects, contacts and opportunities' }).fill('Ridgeview')
  await expect(page.getByText(/waiting for the current opportunity qualification snapshot/)).toBeVisible()
  await expect(page.getByText('No current companies, projects, contacts or opportunities match this search.')).toHaveCount(0)
})
