import { expect, test } from '@playwright/test'
import { mockDemandSummary } from './mock-demand-summary'

const accountId = 'cg_synthetic-snapshot-label'
const company = 'Synthetic Snapshot Label Operator'
const item = {
  id: 'project-1', project_id: 'project-1', customer_identity_id: accountId, name: 'Synthetic Project 1', company,
  location: 'Synthetic, TX', sector: 'oil_gas', asset_type: 'compressor_station', priority_score: null,
  representative_need_id: 'need-1', eligible_need_ids: ['need-1'], need_count: 1,
  needs: [{ id: 'need-1', project_id: 'project-1', name: 'Synthetic Project 1', browse_title: 'Synthetic Project 1', activity: 'compressor expansion', tier: 'Lead' }],
  event: null, contact: [], contact_people: [], power_summary: null, power_summary_kind: 'unknown', next_action: 'Synthetic fixture only.',
  shortlist_assessment: { eligible: true, reasons: [], evidence_refs: [], why_now: 'Synthetic fixture only.', next_step: 'Confirm scope.' }, updated_at: null,
}
const group = {
  id: accountId, name: company, role: 'operator', group_kind: 'resolved_identity', project_count: 1, need_count: 1,
  total_known_project_count: 1, relevant_project_count: 1, eligible_need_count: 1, pursued_eligible_need_count: 0,
  priority_score: null, sectors: ['oil_gas'], matched_project_id: null, matched_need_id: null, identity_count: 1,
}
const projects = (refreshState: string) => ({
  items: [item], total: 1, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'synthetic-cohort', generation: 'synthetic-generation',
  as_of: '2026-10-29T15:00:00Z', valid_until: '2099-01-01T00:00:00Z', qualification_state: 'current', refresh_state: refreshState,
})

for (const [state, expected] of [['updating', true], ['current', false]] as const) {
  test(`account detail ${expected ? 'labels' : 'does not label'} a ${state} snapshot`, async ({ page }) => {
    await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
    await mockDemandSummary(page)
    await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: { items: [group], total: 1, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'synthetic-group-cohort', generation: 'synthetic-generation', as_of: '2026-10-29T15:00:00Z', valid_until: '2099-01-01T00:00:00Z', qualification_state: 'current', refresh_state: state } }))
    await page.route(`**/api/opportunities/groups/${accountId}/open?*`, route => route.fulfill({ json: { group, projects: projects(state), parent_cohort_token: 'synthetic-group-cohort', generation: 'synthetic-generation', valid_until: '2099-01-01T00:00:00Z', qualification_state: 'current', refresh_state: state } }))
    await page.route('**/api/commercial-pursuits*', route => route.fulfill({ json: { items: [], counts: { total: 0, active: 0, needs_attention: 0 }, total_matching: 0, has_more: false, next_offset: null } }))
    await page.goto(`/?groupBrowse=1&shortlist=1&account=${accountId}`)
    const account = page.getByRole('region', { name: `Company ${company}` })
    await expect(account.getByRole('heading', { name: 'Projects' })).toBeVisible()
    await expect(account.getByRole('listitem').filter({ hasText: 'Synthetic Project 1' }).first()).toBeVisible()
    const label = account.getByRole('status').filter({ hasText: 'Showing results as of' })
    await expect(label).toHaveCount(expected ? 1 : 0)
  })
}
