import { expect, test } from '@playwright/test'
import { mockDemandSummary } from './mock-demand-summary'

const accountId = 'cg_synthetic-page-restore'
const company = 'Synthetic Page Restore Operator'
const project = (index: number) => ({
  id: `project-${index}`, project_id: `project-${index}`, customer_identity_id: accountId,
  name: `Synthetic Project ${index}`, company, location: 'Synthetic, TX', sector: 'oil_gas', asset_type: 'compressor_station',
  priority_score: null, representative_need_id: `need-${index}`, eligible_need_ids: [`need-${index}`], need_count: 1,
  needs: [{ id: `need-${index}`, project_id: `project-${index}`, name: `Synthetic Project ${index}`, browse_title: `Synthetic Project ${index}`, activity: 'compressor expansion', tier: 'Lead' }],
  event: null, contact: index === 1 ? [{ kind: 'call', label: 'Call Synthetic Page Restore Operator', href: 'tel:+15555550101', route_kind: 'company_route' }] : [],
  contact_people: [], power_summary: null, power_summary_kind: 'unknown', next_action: 'Synthetic fixture only.',
  shortlist_assessment: { eligible: true, reasons: [], evidence_refs: [], why_now: 'Synthetic fixture only.', next_step: 'Confirm scope.' }, updated_at: null,
})
const firstPage = Array.from({ length: 25 }, (_, index) => project(index + 1))
const secondPage = Array.from({ length: 23 }, (_, index) => project(index + 26))
const group = { id: accountId, name: company, role: 'operator', group_kind: 'resolved_identity', project_count: 48, need_count: 48, total_known_project_count: 48, relevant_project_count: 48, eligible_need_count: 48, sectors: ['oil_gas'], featured_project: firstPage[0] }
const freshGroup = { ...group, featured_project: { ...firstPage[0], contact: [] } }
const validUntil = '2099-01-01T00:00:00Z'
const page = (items: typeof firstPage, offset: number, cohort = 'synthetic-stable-cohort') => ({ items, total: 48, count_unit: 'projects', limit: 25, offset, cohort_token: cohort, generation: 'synthetic-generation', valid_until: validUntil })

test('loaded account pages survive pending account verification, reload, and Back from a second-page project', async ({ page: browser }) => {
  let resolveAssociation!: () => void
  let associationStarted!: () => void
  const associationGate = new Promise<void>(resolve => { resolveAssociation = resolve })
  const associationRequest = new Promise<void>(resolve => { associationStarted = resolve })
  let currentCohort = 'synthetic-stable-cohort'
  let pageTwoUnavailable = false
  let pageTwoConflict = false
  let currentGroup = group
  let freshOpenReads = 0
  await browser.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(browser)
  await browser.route('**/api/opportunities/groups?*', route => route.fulfill({ json: { items: [group], total: 1, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'synthetic-group-cohort', generation: 'synthetic-generation', valid_until: validUntil, facets: { regions: [], stages: [] } } }))
  await browser.route(`**/api/opportunities/groups/${accountId}/open?*`, route => {
    if (currentGroup === freshGroup) freshOpenReads += 1
    return route.fulfill({ json: { group: currentGroup, projects: page(firstPage, 0, currentCohort), parent_cohort_token: 'synthetic-group-cohort', generation: 'synthetic-generation', valid_until: validUntil } })
  })
  await browser.route(`**/api/opportunities/groups/${accountId}/projects?*`, route => {
    const offset = Number(new URL(route.request().url()).searchParams.get('offset') ?? 0)
    if (offset === 25 && pageTwoUnavailable) return route.fulfill({ status: 404, json: { detail: 'Synthetic account snapshot is unavailable.' } })
    if (offset === 25 && pageTwoConflict) {
      pageTwoConflict = false
      currentGroup = freshGroup
      currentCohort = 'synthetic-conflict-fresh-cohort'
      return route.fulfill({ status: 409, json: { detail: 'Synthetic child cohort changed.' } })
    }
    return route.fulfill({ json: page(offset === 25 ? secondPage : firstPage, offset, currentCohort) })
  })
  await browser.route('**/api/opportunities/projects?*', route => {
    const url = new URL(route.request().url()), id = url.searchParams.get('need_id') === 'need-26' ? 26 : 1
    return route.fulfill({ json: { ...page([project(id)], 0), total: 1, limit: 1 } })
  })
  await browser.route('**/api/opportunities/needs/need-26*', route => route.fulfill({ json: {
    id: 'need-26', project_id: 'project-26', name: 'Synthetic Project 26', browse_title: 'Synthetic Project 26',
    location: 'Synthetic, TX', tier: 'Lead', activity: 'compressor expansion', supply: 'Unknown', required_mw: null,
    start_window: null, duration: null, evidence: [], missing_facts: [], rationale: 'Synthetic fixture only.',
    associated_account: { company_identity_id: accountId, name: company, support_status: 'current' },
  } }))
  await browser.route('**/api/projects/project-26/account', async route => {
    associationStarted()
    await associationGate
    await route.fulfill({ json: { id: accountId, name: company, group_kind: 'resolved_identity', project_id: 'project-26' } })
  })
  await browser.route('**/api/commercial-pursuits*', route => route.fulfill({ json: { items: [], counts: { total: 0, active: 0, needs_attention: 0 }, total_matching: 0, has_more: false, next_offset: null } }))

  await browser.goto(`/?groupBrowse=1&shortlist=1&account=${accountId}`)
  const account = browser.getByRole('region', { name: `Company ${company}` })
  await expect(account.getByRole('heading', { name: 'Projects' })).toBeVisible()
  await account.getByRole('button', { name: 'Load more projects' }).click()
  await expect(account.getByRole('region', { name: 'Account projects' }).getByRole('listitem')).toHaveCount(48)
  await account.getByRole('button', { name: 'Open project detail Synthetic Project 26' }).click()
  await associationRequest
  await expect(browser.getByRole('region', { name: 'Account context verification' })).toBeVisible()
  await expect(browser.getByRole('link', { name: 'Call company' })).toHaveCount(0)
  resolveAssociation()
  await expect(browser.getByRole('complementary', { name: 'Opportunity detail' }).getByRole('heading', { name: 'Synthetic Project 26' })).toBeVisible()

  await browser.reload()
  await expect(browser.getByRole('complementary', { name: 'Opportunity detail' }).getByRole('heading', { name: 'Synthetic Project 26' })).toBeVisible()
  await browser.getByRole('button', { name: '← Back to account' }).click()
  const restored = browser.getByRole('region', { name: `Company ${company}` })
  await expect(restored.getByRole('region', { name: 'Account projects' }).getByRole('listitem')).toHaveCount(48)
  await expect(restored.getByRole('button', { name: 'Open project detail Synthetic Project 26' })).toBeVisible()

  await restored.getByRole('button', { name: 'Open project detail Synthetic Project 26' }).click()
  await expect(browser.getByRole('complementary', { name: 'Opportunity detail' }).getByRole('heading', { name: 'Synthetic Project 26' })).toBeVisible()
  pageTwoConflict = true
  await browser.reload()
  await expect(browser.getByRole('complementary', { name: 'Opportunity detail' }).getByRole('heading', { name: 'Synthetic Project 26' })).toBeVisible()
  await browser.getByRole('button', { name: '← Back to account' }).click()
  const conflictRefreshed = browser.getByRole('region', { name: `Company ${company}` })
  await expect.poll(() => freshOpenReads).toBeGreaterThan(0)
  await expect(conflictRefreshed.getByRole('region', { name: 'Account projects' }).getByRole('listitem')).toHaveCount(25)
  await expect(conflictRefreshed.getByRole('status')).toContainText('The account project list changed')
  await expect(conflictRefreshed.getByRole('link', { name: 'Call company' })).toHaveCount(0)

  currentGroup = group
  await conflictRefreshed.getByRole('button', { name: 'Load more projects' }).click()
  await expect(conflictRefreshed.getByRole('region', { name: 'Account projects' }).getByRole('listitem')).toHaveCount(48)
  await conflictRefreshed.getByRole('button', { name: 'Open project detail Synthetic Project 26' }).click()
  await expect(browser.getByRole('complementary', { name: 'Opportunity detail' }).getByRole('heading', { name: 'Synthetic Project 26' })).toBeVisible()
  currentCohort = 'synthetic-changed-cohort'
  await browser.reload()
  await expect(browser.getByRole('complementary', { name: 'Opportunity detail' }).getByRole('heading', { name: 'Synthetic Project 26' })).toBeVisible()
  await browser.getByRole('button', { name: '← Back to account' }).click()
  const refreshed = browser.getByRole('region', { name: `Company ${company}` })
  await expect(refreshed.getByRole('region', { name: 'Account projects' }).getByRole('listitem')).toHaveCount(25)
  await expect(refreshed.getByRole('status')).toContainText('The account project list changed')

  await refreshed.getByRole('button', { name: 'Load more projects' }).click()
  await expect(refreshed.getByRole('region', { name: 'Account projects' }).getByRole('listitem')).toHaveCount(48)
  await refreshed.getByRole('button', { name: 'Open project detail Synthetic Project 26' }).click()
  await expect(browser.getByRole('complementary', { name: 'Opportunity detail' }).getByRole('heading', { name: 'Synthetic Project 26' })).toBeVisible()
  pageTwoUnavailable = true
  await browser.reload()
  await expect(browser.getByRole('complementary', { name: 'Opportunity detail' }).getByRole('heading', { name: 'Synthetic Project 26' })).toBeVisible()
  await browser.getByRole('button', { name: '← Back to account' }).click()
  const unavailable = browser.getByRole('region', { name: `Company ${company}` })
  await expect(unavailable.getByRole('alert')).toContainText('no longer available')
  await expect(unavailable.getByRole('region', { name: 'Account projects' }).getByRole('listitem')).toHaveCount(0)
  await expect(unavailable.getByRole('link', { name: 'Call company' })).toHaveCount(0)
})
