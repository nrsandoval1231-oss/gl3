import { expect, test } from '@playwright/test'
import { mockDemandSummary } from './mock-demand-summary'

const accountId = 'cg_synthetic-search-account'
const company = 'Synthetic Search Operator'
const targetProject = {
  id: 'project-synthetic-26', project_id: 'project-synthetic-26', customer_identity_id: accountId,
  name: 'Synthetic Project 26', company, location: 'Permian Basin, TX', sector: 'oil_gas', asset_type: 'compressor_station',
  priority_score: null, representative_need_id: 'need-synthetic-26', eligible_need_ids: ['need-synthetic-26'], need_count: 1,
  needs: [{ id: 'need-synthetic-26', project_id: 'project-synthetic-26', name: 'Synthetic Project 26', browse_title: 'Synthetic Project 26', activity: 'compressor expansion', tier: 'Lead' }],
  event: null, contact: [], contact_people: [], power_summary: null, power_summary_kind: 'unknown', next_action: 'Review retained project evidence.',
  shortlist_assessment: { eligible: true, reasons: [], evidence_refs: [], why_now: 'Synthetic fixture only.', next_step: 'Confirm scope.' }, updated_at: null,
}
const firstPage = Array.from({ length: 25 }, (_, index) => ({
  ...targetProject, id: `project-synthetic-${index + 1}`, project_id: `project-synthetic-${index + 1}`,
  name: `Synthetic Project ${index + 1}`, representative_need_id: `need-synthetic-${index + 1}`,
  needs: [{ id: `need-synthetic-${index + 1}`, project_id: `project-synthetic-${index + 1}`, name: `Synthetic Project ${index + 1}`, browse_title: `Synthetic Project ${index + 1}`, activity: 'compressor expansion', tier: 'Lead' }],
}))
const group = {
  id: accountId, name: company, role: 'operator', group_kind: 'resolved_identity', project_count: 26,
  total_known_project_count: 26, relevant_project_count: 26, eligible_need_count: 26, need_count: 26,
  priority_score: null, sectors: ['oil_gas'], featured_project: firstPage[0],
  matched_project_id: targetProject.project_id, matched_need_id: targetProject.representative_need_id,
}
const groupPage = { items: [group], total: 1, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'account-search-cohort', generation: 'synthetic-account-search', valid_until: '2099-01-01T00:00:00Z', facets: { regions: [], stages: [] } }
const currentProjectPage = { items: firstPage, total: 26, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'child-search-cohort', generation: 'synthetic-account-search', valid_until: '2099-01-01T00:00:00Z' }

test('project-specific account search opens its exact matched opportunity beyond page one with account scope', async ({ page }) => {
  const groupOpens: string[] = []
  const exactReads: URL[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: groupPage }))
  await page.route('**/api/opportunities/groups/*/open?*', route => { groupOpens.push(route.request().url()); return route.fulfill({ json: { group, projects: currentProjectPage, parent_cohort_token: 'account-search-cohort', valid_until: '2099-01-01T00:00:00Z' } }) })
  await page.route('**/api/opportunities/projects?*', route => {
    const url = new URL(route.request().url())
    exactReads.push(url)
    return route.fulfill({ json: { ...currentProjectPage, items: [targetProject], total: 1, limit: 1, offset: 0 } })
  })
  await page.route('**/api/projects/project-synthetic-26/account', route => route.fulfill({ json: { id: accountId, name: company, group_kind: 'resolved_identity', project_id: targetProject.project_id } }))
  await page.route('**/api/opportunities/needs/need-synthetic-26*', route => route.fulfill({ json: {
    id: 'need-synthetic-26', project_id: targetProject.project_id, name: targetProject.name, browse_title: targetProject.name,
    location: targetProject.location, tier: 'Lead', activity: 'compressor expansion', supply: 'Unknown', required_mw: null,
    start_window: null, duration: null, evidence: [], missing_facts: [], rationale: 'Synthetic fixture, not a commercial finding.',
    associated_account: { company_identity_id: accountId, name: company, support_status: 'current' },
  } }))
  await page.route('**/api/commercial-pursuits*', route => route.fulfill({ json: { items: [], counts: { total: 0, active: 0, needs_attention: 0 }, total_matching: 0, has_more: false, next_offset: null } }))

  await page.goto('/?groupBrowse=1&shortlist=1&q=Synthetic+Project+26')
  const card = page.getByRole('region', { name: `${company} customer group` })
  await expect(card).toContainText(company)
  await expect(card.getByRole('button', { name: 'View account with matching opportunity' })).toBeVisible()
  await card.getByRole('button', { name: 'View account with matching opportunity' }).click()
  await page.getByRole('region', { name: `Company ${company}` }).getByRole('button', { name: 'Open matching opportunity' }).click()

  const detail = page.getByRole('complementary', { name: 'Opportunity detail' })
  await expect(detail.getByRole('heading', { name: 'Synthetic Project 26' })).toBeVisible()
  await expect(page).toHaveURL(/account=cg_synthetic-search-account/)
  await expect(page).toHaveURL(/project=project-synthetic-26/)
  await expect(page).toHaveURL(/need=need-synthetic-26/)
  expect(exactReads.some(url => url.searchParams.get('need_id') === 'need-synthetic-26')).toBe(true)
  expect(groupOpens.every(url => Number(new URL(url).searchParams.get('offset') ?? 0) === 0)).toBe(true)
  expect(exactReads.some(url => Number(url.searchParams.get('offset') ?? 0) > 0)).toBe(false)
  await page.getByRole('button', { name: '← Back to account' }).click()
  await expect(page.getByRole('region', { name: 'Company Synthetic Search Operator' }).getByRole('heading', { name: 'Projects' })).toBeVisible()
  await expect(new URL(page.url()).searchParams.get('account')).toBe(accountId)
  await expect(new URL(page.url()).searchParams.get('need')).toBeNull()
  await expect(new URL(page.url()).searchParams.get('q')).toBe('Synthetic Project 26')
})

test('account-name-only search keeps the account overview as its primary action', async ({ page }) => {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: { ...groupPage, items: [{ ...group, name: 'Northstar Energy' }] } }))
  await page.route('**/api/opportunities/groups/*/open?*', route => route.fulfill({ json: { group: { ...group, name: 'Northstar Energy' }, projects: currentProjectPage, parent_cohort_token: 'account-search-cohort', valid_until: '2099-01-01T00:00:00Z' } }))
  await page.goto('/?groupBrowse=1&shortlist=1&q=Northstar')
  const card = page.getByRole('region', { name: 'Northstar Energy customer group' })
  await expect(card.getByRole('button', { name: 'Open matching opportunity' })).toHaveCount(0)
  await card.getByRole('button', { name: 'Choose opportunity' }).click()
  await expect(page.getByRole('region', { name: 'Company Northstar Energy' }).getByRole('heading', { name: 'Projects' })).toBeVisible()
})

test('same-name contacts in conflicting roles do not share contact methods', async ({ page }) => {
  const project = {
    ...firstPage[0],
    contact: [
      { kind: 'call', label: 'Call John Smith', href: 'tel:+15555550111', name: 'John Smith', title: 'Project Manager', role: 'site_development', company: 'Synthetic Search Operator', route_kind: 'named_contact' },
      { kind: 'email', label: 'Email John Smith', href: 'mailto:procurement@example.test', name: 'John Smith', title: 'Project Manager', role: 'energy_procurement', company: 'Synthetic Search Operator', route_kind: 'named_contact' },
    ],
  }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: { ...groupPage, items: [{ ...group, featured_project: project, matched_project_id: null, matched_need_id: null }] } }))
  await page.goto('/?groupBrowse=1&shortlist=1')
  const card = page.getByRole('region', { name: `${company} customer group` })
  await expect(card.getByRole('link', { name: 'Call John Smith' })).toHaveAttribute('href', 'tel:+15555550111')
  await expect(card.getByRole('link', { name: 'Email John Smith' })).toHaveCount(0)
})
