import { expect, test } from '@playwright/test'
import { mockDemandSummary } from './mock-demand-summary'

const companyId = '123e4567-e89b-12d3-a456-426614174000'
const project = {
  id: 'project-red-oak',
  project_id: 'project-red-oak',
  project_ids: ['project-red-oak'],
  customer_identity_id: companyId,
  name: 'Red Oak Campus',
  company: 'DataBank',
  location: 'Red Oak, TX',
  sector: 'data_centers',
  asset_type: 'data_center',
  priority_score: null,
  representative_need_id: 'need-red-oak',
  need_count: 1,
  need_ids: ['need-red-oak'],
  needs: [{ id: 'need-red-oak', project_id: 'project-red-oak', name: 'Red Oak Campus', tier: 'Prospect' }],
  event: null,
  contact: [],
  contact_people: [],
  power_summary: null,
  power_summary_kind: 'unknown',
  next_action: null,
  updated_at: null,
}

test('company page labels methodless roster roles as company-only', async ({ page }) => {
  await page.clock.install({ time: new Date('2026-11-13T12:00:00Z') })
  await page.clock.pauseAt(new Date('2026-11-13T12:00:00Z'))
  await mockDemandSummary(page)
  await page.route(url => new URL(url).pathname.startsWith('/api/') && !new URL(url).pathname.includes('demand-summary'), route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (url.pathname === '/api/opportunities/groups') return route.fulfill({ json: {
      items: [{ id: 'cg_databank', name: 'DataBank', role: 'customer', group_kind: 'resolved_identity', company_identity_id: companyId, project_count: 1, total_known_project_count: 1, relevant_project_count: 1, need_count: 1, priority_score: null, sectors: ['data_centers'] }],
      total: 1, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'groups-v1', generation: 'gen-v1',
    } })
    if (url.pathname === '/api/opportunities/projects') return route.fulfill({ json: { items: [project], total: 1, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'projects-v1', generation: 'gen-v1' } })
    if (url.pathname === '/api/opportunities/groups/cg_databank/open') return route.fulfill({ json: {
      group: { id: 'cg_databank', name: 'DataBank', role: 'customer', group_kind: 'resolved_identity', company_identity_id: companyId, project_count: 1, total_known_project_count: 1, relevant_project_count: 1, need_count: 1, sectors: ['data_centers'], featured_project: project },
      parent_cohort_token: 'groups-v1', generation: 'gen-v1', valid_until: '2099-01-01T00:00:00Z',
      projects: { items: [project], total: 1, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'projects-v1', generation: 'gen-v1', valid_until: '2099-01-01T00:00:00Z' },
    } })
    if (url.pathname === `/api/customer-accounts/${companyId}/contacts`) return route.fulfill({ json: {
      company_id: companyId, research_required: true, imported_unverified: [], contacts: [],
      published_company_roles: [{
        company_identity_id: companyId, name: 'Joe Minarik', title: 'Chief Operating Officer',
        role: 'owner_construction', responsibility: 'Published company role; project involvement unverified',
        person_project_relationship: 'UNKNOWN',
        source_url: 'https://www.databank.com/about-databank/leadership-team/', source_title: 'Leadership Team - DataBank',
        source_quote: 'Joe Minarik\n\nChief Operating Officer', source_hash: 'a'.repeat(64),
        observed_at: '2026-11-13T12:00:00Z', valid_until: '2026-11-13T12:00:05Z', published_at: null,
        methods: [], project_ids: [], verification_status: 'Published company role; current employment and project involvement unverified',
      }],
    } })
    if (url.pathname === '/api/commercial-pursuits') return route.fulfill({ json: { items: [], counts: { total: 0, active: 0, needs_attention: 0 }, total_matching: 0, has_more: false, next_offset: null } })
    return route.fulfill({ json: [] })
  })

  await page.goto('/?view=workspace&panel=companies')
  await page.getByRole('button', { name: 'Open DataBank' }).click()
  const roles = page.getByRole('region', { name: 'Published company roles' })
  await expect(roles).toContainText('Joe Minarik')
  await expect(roles).toContainText('Chief Operating Officer')
  await expect(roles).toContainText('Current employment and project involvement are unverified.')
  await expect(roles).toContainText('No personal email or phone is verified.')
  await expect(roles).toContainText('Published company role; project involvement unverified')
  await expect(roles.locator('a')).toHaveAttribute('href', 'https://www.databank.com/about-databank/leadership-team/')
  await expect(roles).not.toContainText('Verified project responsibility')
  await expect(roles.locator('a[href^="mailto:"]')).toHaveCount(0)
  await page.clock.fastForward(5000)
  await expect(roles).toHaveCount(0)
})
