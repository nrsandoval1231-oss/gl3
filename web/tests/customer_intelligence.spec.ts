import { expect, test } from '@playwright/test'
import { mockDemandSummary } from './mock-demand-summary'
import { selectAccountContactProject } from '../src/features/companies/CompanyView'
import type { OpportunityGroup, ProjectResult } from '../src/api/client'

test('customer workspace uses customer-first branding and hides raw priority scores', async ({ page }) => {
  const sampleGroup = {
    id: 'cg_synthetic', name: 'Synthetic Northstar Compute', role: 'customer', group_kind: 'resolved_identity', project_count: 2, relevant_project_count: 2, total_known_project_count: 2, need_count: 1, sectors: ['data_centers'],
    commercial_intelligence: { version: 'synthetic-v1', capacity: { status: 'supported', totals: [{ basis: 'it_load', value_mw: '20', status: 'upper_bound', qualifier: 'up_to', complete: false }], coverage: { projects_with_capacity: 1, projects_total: 2 }, claims: [{ fact_id: 'cf-cap-1', value_mw: '5', basis: 'utility_service', scope_id: 'p-synthetic:phase:1', qualifier: 'exact', quote: 'Phase 1 utility service is 5 MW.', source: { title: 'Capacity source A', url: 'https://example.invalid/capacity-a', evidence_id: 'e-cap-a' } }, { fact_id: 'cf-cap-2', value_mw: '8', basis: 'utility_service', scope_id: 'p-synthetic:phase:1', qualifier: 'exact', quote: 'Phase 1 utility service is 8 MW.', source: { title: 'Capacity source B', url: 'https://example.invalid/capacity-b', evidence_id: 'e-cap-b' } }], conflicts: [{ basis: 'utility_service', scope_id: 'p-synthetic:phase:1', claim_ids: ['cf-cap-1', 'cf-cap-2'], reason: 'Equal-authority capacity claims disagree.' }] }, timelines: { construction_start: { label: 'Q2 2027', precision: 'quarter' }, expected_energization: null, claims: [{ fact_id: 'tf-energy-1', event_type: 'phase_energization', display_label: 'Q3 2027', label: 'Q3 2027', precision: 'quarter', scope_id: 'p-synthetic:phase:2', status: 'expected', quote: 'Phase 2 expected first energization in Q3 2027.', source: { title: 'Schedule source A', url: 'https://example.invalid/schedule-a' } }, { fact_id: 'tf-energy-2', event_type: 'phase_energization', display_label: 'Q4 2027', label: 'Q4 2027', precision: 'quarter', scope_id: 'p-synthetic:phase:2', status: 'expected', quote: 'Phase 2 expected first energization in Q4 2027.', source: { title: 'Schedule source B', url: 'https://example.invalid/schedule-b' } }], conflicts: [{ event_type: 'phase_energization', scope_id: 'p-synthetic:phase:2', claim_ids: ['tf-energy-1', 'tf-energy-2'] }] }, commissioning: { status: 'estimated', base_mw: '12.5', low_mw: null, high_mw: null, calculation_version: 'commissioning-v1', assumptions: ['Synthetic project-specific test sequence.'], input_evidence: [{ project_id: 'p-synthetic', quote: 'Rated electrical input 25 MW; test at 50 percent.', url: 'https://example.invalid/commissioning', evidence_id: 'e-commissioning' }], limitations: ['Engineering scenario, not verified customer demand.'] }, recent_developments: [{ summary: 'Synthetic announcement for layout review.', url: 'https://example.invalid/synthetic' }], priority: { potential: 0.6, confidence: 0.4, score: 0.24, components: { supported_capacity: 0.2, timeline: 0.1 }, version: 'synthetic-v1' }, recommended_next_action: 'Review the source details.', sources: [{ title: 'Synthetic source record', url: 'https://example.invalid/synthetic' }], limitations: [] },
    featured_project: { id: 'p-synthetic', project_id: 'p-synthetic', customer_identity_id: 'company-synthetic', name: 'Mesa campus', company: 'Synthetic Northstar Compute', location: 'Austin, TX', sector: 'data_centers', asset_type: 'data_center', priority_score: null, representative_need_id: 'need-synthetic', need_count: 1, commercial_brief: { version: 'synthetic-v1', why_now: { text: 'Synthetic schedule evidence is unresolved.', source_date: null, scope: null, sources: [] }, power_need: { amount_class: 'unknown', scope: null, value: null, unit: null, status: 'unknown', limitations: [] }, best_contact: null, next_action: { text: 'Review the source details.', kind: 'review', source: null }, freshness: { as_of: null, status: 'unknown', source_date: null }, limitations: [], sources: [] }, needs: [{ id: 'need-synthetic', name: 'Mesa campus', project_id: 'p-synthetic', tier: 'Prospect' }], eligible_need_ids: ['need-synthetic'], contact: [], contact_people: [{ company_identity_id: 'company-synthetic', person_identity_id: 'person-synthetic', name: 'Avery Example', title: 'Facilities Director', responsibility: 'Verified project responsibility', source_url: 'https://example.invalid/person' }, { company_identity_id: 'other-company', person_identity_id: 'person-unsupported', name: 'Unsupported Example', title: 'Buyer', responsibility: 'Verified organizational responsibility', source_url: 'https://example.invalid/unsupported' }], event: null, power_summary: null, power_summary_kind: 'unknown', next_action: null, updated_at: null },
  }
  const secondProject = { ...sampleGroup.featured_project, id: 'p-synthetic-2', project_id: 'p-synthetic-2', name: 'Synthetic Northstar East campus', representative_need_id: null, need_count: 0, needs: [], eligible_need_ids: [], contact: [], contact_people: [] }
  const unfeaturedGroup = { ...sampleGroup, id: 'cg_cedar', name: 'Synthetic Cedar Infrastructure', project_count: 1, relevant_project_count: 1, total_known_project_count: 1, need_count: 0, featured_project: null, commercial_intelligence: { ...sampleGroup.commercial_intelligence, capacity: { status: 'insufficient_data', totals: [], claims: [], conflicts: [], coverage: { projects_with_capacity: 0, projects_total: 1 } }, timelines: { construction_start: null, expected_energization: null, claims: [], conflicts: [] }, commissioning: { status: 'insufficient_data', base_mw: null, low_mw: null, high_mw: null, limitations: ['No Cedar project test evidence.'], input_evidence: [] }, recent_developments: [], priority: { potential: 0, confidence: 0, score: 0, components: {}, version: 'synthetic-v1' }, recommended_next_action: 'Research supported project and timing evidence.', sources: [], limitations: ['No supported capacity or timeline claims.'] } }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/search?**', route => route.fulfill({ json: { query: 'Mesa', companies: [], projects: [], contacts: [], opportunities: [{ id: 'need-mesa', name: 'Mesa campus', organization: 'Northstar', rank_score: 93 }] } }))
  await page.route('**/api/opportunities/groups?**', route => route.fulfill({ json: { items: [sampleGroup, unfeaturedGroup], total: 2, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'ci', generation: 'ci', valid_until: '2099-01-01T00:00:00Z' } }))
  await page.route('**/api/opportunities/groups/cg_synthetic/open**', route => route.fulfill({ json: { group: sampleGroup, parent_cohort_token: 'ci-parent', generation: 'ci', valid_until: '2099-01-01T00:00:00Z', projects: { items: [sampleGroup.featured_project, secondProject], total: 2, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'ci-projects', generation: 'ci', valid_until: '2099-01-01T00:00:00Z' } } }))
  await page.route('**/api/opportunities/projects?**', route => route.fulfill({ json: { items: [], total: 0, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'ci', generation: 'ci', valid_until: '2099-01-01T00:00:00Z' } }))
  await page.route('**/api/commercial-pursuits**', route => route.fulfill({ json: { items: [], counts: { total: 0, active: 0, needs_attention: 0 } } }))
  await page.goto('/?view=workspace&groupBrowse=1')
  await expect(page.getByRole('heading', { level: 1, name: 'Customers' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'GridLens — Real projects. Real power.' })).toBeVisible()
  const primaryGroup = page.getByRole('region', { name: 'Synthetic Northstar Compute customer group' })
  await expect(primaryGroup.getByText('2 projects', { exact: true })).toBeVisible()
  await expect(primaryGroup.getByText('Up to 20 MW IT load · partial coverage')).toBeVisible()
  await expect(primaryGroup.getByText('1 of 2 projects with supported capacity')).toBeVisible()
  await expect(primaryGroup.getByText('Conflicting capacity claims require review.')).toBeVisible()
  await expect(primaryGroup.getByText('Conflicting timeline claims require review.')).toBeVisible()
  await expect(primaryGroup.getByText('Construction start')).toBeVisible()
  await expect(primaryGroup.getByText(/Expected energization · Not established/)).toBeVisible()
  await expect(primaryGroup.getByText(/Q2 2027 · quarter/)).toBeVisible()
  await expect(primaryGroup.getByText('Avery Example')).toBeVisible()
  await expect(primaryGroup.getByText('Unsupported Example')).toHaveCount(0)
  await expect(primaryGroup.getByRole('link', { name: 'Email Avery Example' })).toHaveCount(0)
  const unfeatured = page.getByRole('region', { name: 'Synthetic Cedar Infrastructure customer group' })
  await expect(unfeatured.getByText('1 project', { exact: true })).toBeVisible()
  await expect(unfeatured.getByText('Build capacity')).toBeVisible()
  await expect(unfeatured.getByText('Not available from supported evidence')).toBeVisible()
  await expect(primaryGroup.getByText('Recent development')).toBeVisible()
  await expect(primaryGroup.getByText('Review the source details.', { exact: true })).toBeVisible()
  await expect(primaryGroup.getByText('12.5 MW base engineering scenario')).toBeVisible()
  const captures = [
    { name: 'desktop-wide', width: 1440, height: 1000 },
    { name: 'desktop-compact', width: 1280, height: 800 },
    { name: 'tablet-landscape', width: 1024, height: 768 },
    { name: 'tablet-portrait', width: 768, height: 1024 },
    { name: 'mobile', width: 390, height: 844 },
  ]
  for (const viewport of captures) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
    await page.screenshot({ path: `../docs/validation/customer-intelligence-20261112/after-${viewport.name}.png`, fullPage: true })
  }
  const search = page.getByRole('searchbox', { name: 'Search companies, projects, contacts and opportunities' })
  await search.fill('Mesa')
  const results = page.getByRole('region', { name: 'Search results' })
  await expect(results.getByRole('button', { name: /Mesa campus/ })).toBeVisible()
  await expect(results).not.toContainText('93')
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.getByRole('button', { name: 'View account details' }).click()
  await page.getByText('Commercial analysis').click()
  await expect(page.getByText('Priority rationale')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Synthetic source record' })).toHaveAttribute('href', 'https://example.invalid/synthetic')
  await page.getByText('Conflicting capacity claims (1)').click()
  await expect(page.getByText('Equal-authority capacity claims disagree.')).toBeVisible()
  await page.getByText('Source evidence').first().click()
  await expect(page.getByRole('link', { name: 'Capacity source A' })).toHaveAttribute('href', 'https://example.invalid/capacity-a')
  await page.getByText('Conflicting timeline claims (1)').click()
  const timelineConflict = page.locator('.cmp-commercial-analysis > details').filter({ hasText: 'Conflicting timeline claims (1)' })
  await expect(timelineConflict.getByText('Phase energization').first()).toBeVisible()
  await expect(timelineConflict.getByText('Phase 2').first()).toBeVisible()
  await expect(timelineConflict.getByText('Q3 2027').first()).toBeVisible()
  await expect(page.locator('.cmp-commercial-analysis')).not.toContainText(/(?:cf-cap-|tf-energy-|p-synthetic:)/)
  await expect(page.locator('.cmp-commercial-analysis').getByText('0', { exact: true })).toHaveCount(0)
  await timelineConflict.getByText('Source evidence').first().click()
  await expect(timelineConflict.getByRole('link', { name: 'Schedule source A' })).toHaveAttribute('href', 'https://example.invalid/schedule-a')
  await page.getByText('Engineering scenario inputs and calculation').click()
  await expect(page.getByRole('link', { name: 'Open cited source' })).toHaveAttribute('href', 'https://example.invalid/commissioning')
  await expect(page.getByText(/Partial supported amounts/)).toHaveCount(0)
  await page.screenshot({ path: '../docs/validation/customer-intelligence-20261112/after-account-detail.png', fullPage: true })
  await page.locator('.wh-account > summary').click()
  await expect(page.getByText('Build identity')).toBeVisible()
  await expect(page.locator('.wh-build-identity small').filter({ hasText: /^Source / })).toBeVisible()
})

test('an explicit null authoritative account contact selection does not fall back to a project contact', () => {
  const account = { id: 'cg_synthetic', name: 'Synthetic account', role: 'customer', project_count: 1, need_count: 0, sectors: [], account_contact_project: null } as unknown as OpportunityGroup
  const fallback = { id: 'p-synthetic', project_id: 'p-synthetic', name: 'Synthetic project', company: 'Synthetic account', location: null, sector: null, asset_type: null, priority_score: null, representative_need_id: null, needs: [], need_count: 0, event: null, contact: [], contact_people: [{ company_identity_id: 'company-synthetic', person_identity_id: 'person-synthetic', name: 'Avery Example', responsibility: 'Verified project responsibility', source_url: 'https://example.invalid/person' }], power_summary: null, next_action: null, updated_at: null } as unknown as ProjectResult
  expect(selectAccountContactProject(account, fallback)).toBeNull()
})
