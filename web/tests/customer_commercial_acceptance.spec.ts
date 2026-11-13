import { expect, test } from '@playwright/test'
import { mockDemandSummary } from './mock-demand-summary'

// Synthetic browser fixtures exercise presentation and navigation only; they are not customer evidence.
test('synthetic account card puts scoped commercial context first and offers one next action', async ({ page }) => {
  const account = {
    id: 'cg_fixture', name: 'Synthetic Grid Campus', role: 'customer', group_kind: 'resolved_identity',
    project_count: 1, total_known_project_count: 1, relevant_project_count: 1, need_count: 1,
    sectors: ['data_centers'],
    commercial_intelligence: {
      capacity: { status: 'supported', totals: [{ basis: 'it_load', value_mw: '20', status: 'upper_bound', qualifier: 'up_to', complete: true }], coverage: { projects_with_capacity: 1, projects_total: 1 }, conflicts: [] },
      timelines: { construction_start: { label: 'Q2 2027', precision: 'quarter' }, expected_energization: null, conflicts: [] },
      commissioning: { status: 'insufficient_data', base_mw: null, low_mw: null, high_mw: null, limitations: [], input_evidence: [] },
      recent_developments: [{ summary: 'Synthetic site plan update.', url: 'https://example.invalid/update' }],
      recommended_next_action: 'Confirm phase timing from the cited schedule.',
    },
    featured_project: {
      id: 'project_fixture', project_id: 'project_fixture', customer_identity_id: 'company_fixture',
      name: 'Synthetic East Campus', company: 'Synthetic Grid Campus', location: 'Austin, TX',
      sector: 'data_centers', asset_type: 'data_center', priority_score: null,
      representative_need_id: 'need_fixture', need_count: 1,
      needs: [{ id: 'need_fixture', name: 'Synthetic East Campus', project_id: 'project_fixture', tier: 'Prospect' }],
      eligible_need_ids: ['need_fixture'], event: null, contact: [], power_summary: null,
      power_summary_kind: 'unknown', next_action: null, updated_at: null,
      commercial_brief: {
        version: 'synthetic-v1', why_now: { text: 'A synthetic schedule update needs review.', source_date: null, scope: null, sources: [] },
        power_need: { amount_class: 'unknown', scope: null, value: null, unit: null, status: 'unknown', limitations: [] },
        best_contact: null,
        next_action: { text: 'Confirm phase timing from the cited schedule.', kind: 'confirm_need', source: null },
        freshness: { as_of: null, status: 'unknown', source_date: null }, limitations: [], sources: [],
      },
    },
  }
  await mockDemandSummary(page)
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?**', route => route.fulfill({ json: { items: [account], total: 1, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'synthetic', generation: 'synthetic', valid_until: '2099-01-01T00:00:00Z' } }))
  await page.route('**/api/opportunities/projects?**', route => route.fulfill({ json: { items: [], total: 0, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'synthetic', generation: 'synthetic', valid_until: '2099-01-01T00:00:00Z' } }))
  await page.route('**/api/commercial-pursuits**', route => route.fulfill({ json: { items: [], counts: { total: 0, active: 0, needs_attention: 0 } } }))

  await page.goto('/?view=workspace&groupBrowse=1')
  const card = page.getByRole('region', { name: 'Synthetic Grid Campus customer group' })
  await expect(card).toContainText('Synthetic East Campus')
  await expect(card).toContainText('Up to 20 MW IT load')
  await expect(card).toContainText('Q2 2027')
  await expect(card).toContainText('Synthetic site plan update.')
  await expect(card.getByText('Next action', { exact: true })).toHaveCount(1)
  await expect(card).toContainText('Confirm phase timing from the cited schedule.')
  await expect(card).not.toContainText('unknown is zero')
  await expect(card.locator('details.customer-brief-sources')).toBeVisible()
  await expect(card.locator('details.customer-brief-sources')).not.toHaveAttribute('open', '')
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  for (const amountClass of ['estimated', 'inferred']) {
    const forecast = {
      ...account,
      commercial_intelligence: {
        ...account.commercial_intelligence,
        timelines: { construction_start: null, expected_energization: null, reported_target: { event_type: 'operational_target', label: 'By Q4 2026' } },
      },
      featured_project: {
        ...account.featured_project,
        commercial_brief: {
          ...account.featured_project.commercial_brief,
          power_need: { amount_class: amountClass, scope: 'Bridge power', value: '90', unit: 'MW', status: 'supported', limitations: ['Upstream forecast; customer demand is unverified.'] },
        },
      },
    }
    await page.route('**/api/opportunities/groups?**', route => route.fulfill({ json: { items: [forecast], total: 1, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'synthetic', generation: 'synthetic', valid_until: '2099-01-01T00:00:00Z' } }))
    await page.reload()
    const refreshed = page.getByRole('region', { name: 'Synthetic Grid Campus customer group' })
    await expect(refreshed).toContainText('Up to 20 MW IT load')
    await expect(refreshed).not.toContainText('90 MW')
    await expect(refreshed.getByText('Power need', { exact: true })).toHaveCount(0)
    await expect(refreshed.getByText('Operational target', { exact: true })).toBeVisible()
    await expect(refreshed).toContainText('By Q4 2026')
    await expect(refreshed).toContainText('source-reported; energization unverified')
    await expect(refreshed.getByText('Expected energization', { exact: true }).locator('..')).toContainText('Not established')
  }
})
