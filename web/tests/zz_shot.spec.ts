import { test } from '@playwright/test'
import { mockDemandSummary } from './mock-demand-summary'
const dir = '/tmp/claude-0/-home-user-gl3/38bc2319-6e47-532f-9cf3-1a18c02a54a5/scratchpad/ui5/'
const proj = { id: 'project-1', project_id: 'project-1', name: 'Example Energy · Example Compressor Station', company: 'Example Energy', location: 'Permian Basin, TX', sector: 'oil_gas', asset_type: 'compressor_station', priority_score: null, representative_need_id: 'need-1', need_count: 1, needs: [{ id: 'need-1', project_id: 'project-1', tier: 'Lead' }], event: null, contact: [], contact_people: [], power_summary: null, power_summary_kind: 'unknown', next_action: 'Confirm fixture details.', updated_at: null }
const need = { id: 'need-1', project_id: 'project-1', name: 'Example Compressor Station', browse_title: 'Example Compressor Station', location: 'Permian Basin, TX', tier: 'Lead', workflow_status: 'New', activity: 'drilling', rationale: 'Synthetic.', signal_evidence_state: 'active_evidence', required_mw: null, start_window: null, duration: null, supply: 'Unknown', conflict_state: 'Not assessed', title_company: 'Example Energy', commercial_organization: 'Example Energy', evidence: [], missing_facts: [] }
for (const [w, h] of [[1648, 928], [390, 844]]) test(`shot ${w}`, async ({ page }) => {
  await page.setViewportSize({ width: w, height: h })
  await mockDemandSummary(page)
  await page.route(u => u.pathname.startsWith('/api/') && !u.pathname.includes('demand-summary'), route => {
    const p = new URL(route.request().url()).pathname
    if (p === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (p === '/api/opportunities/groups') return route.fulfill({ json: { items: [{ id: 'g', name: 'Example Energy', role: 'operator', project_count: 1, need_count: 1, priority_score: null, sectors: ['oil_gas'] }], total: 1, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'g', generation: 'g' } })
    if (p.endsWith('/projects') || p === '/api/opportunities/projects') return route.fulfill({ json: { items: [proj], total: 1, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'p', parent_cohort_token: 'g', generation: 'g' } })
    if (p === '/api/opportunities/needs/need-1') return route.fulfill({ json: need })
    if (p === '/api/commercial-pursuits') return route.fulfill({ json: { items: [], counts: { total: 0, active: 0, needs_attention: 0 } } })
    return route.fulfill({ json: [] })
  })
  await page.goto('/?view=workspace&need=need-1')
  await page.waitForSelector('.wh-pursuit-action button')
  await page.screenshot({ path: `${dir}default-detail-${w}.png` })
  await page.locator('.wh-pursuit-action button').click().catch(() => {})
})
