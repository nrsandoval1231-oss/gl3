import { mockDemandSummary } from './mock-demand-summary'
import { expect, test, type Page } from '@playwright/test'

// SYNTHETIC UI TEST FIXTURE ONLY — fabricated names, contacts and values.
const src = { reference: 'fx:1', title: 'Synthetic notice', url: 'https://sources.example.test/n', source_date: '2026-10-20', retained_evidence_id: 'e1', content_hash: 'c'.repeat(64), passage: 'x', extraction_method: 'Official notice', verification_status: 'Current retained support' }
const person = (methods: object[]) => ({ claim_id: 'c1', company: 'Layout Holdings (fixture)', name: 'Pat Fixture', title: 'Director of Power', role: 'owner', responsibility: null, purchasing_authority: null, methods, sources: [src] })
function build(methods: object[], withEquipment = true) {
  const card = {
    policy_version: 'v1', need_id: 'need-l', project_id: 'project-l', input_fingerprint: 'd'.repeat(64), qualification: 'Prospect', disposition: 'RESEARCH',
    fields: [], contacts: [person(methods)], next_action: 'Synthetic action', research_gaps: [], completeness: { supported: 0, total: 1, percent: 0, basis: 'x' },
    equipment_demand: withEquipment ? { status: 'PARTIAL', classification: 'UNKNOWN', scope: 'equipment_schedule', as_of: '2026-10-15', lifecycle: ['proposed'], expected_start: [], demand: { connected_kw: '100', coincident_kw: null, incremental_kw: null } } : undefined,
    power_gap: { remaining_mw: 'Not established', status: 'unknown' }, evidence: [src], research_enabled: true,
  }
  return { id: 'need-l', project_id: 'project-l', name: 'Layout Campus Fixture', browse_title: 'Layout Campus Fixture', location: 'Tulsa, OK', tier: 'Prospect', workflow_status: 'New', activity: 'data center construction', rationale: 'r', signal_evidence_state: 'active_evidence', required_mw: null, start_window: null, duration: null, supply: 'Unknown', next_action: 'Synthetic action', conflict_state: 'Not assessed', title_company: 'Layout Holdings (fixture)', commercial_organization: 'Layout Holdings (fixture)', commercial_reason: 'SYNTHETIC: Phased power may be needed. More text follows.', evidence: [], missing_facts: [], intelligence_card: card }
}
async function open(page: Page, methods: object[], width = 1280, height = 800) {
  await page.setViewportSize({ width, height })
  const opp = build(methods)
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (path === '/api/opportunities/needs/need-l') return route.fulfill({ json: opp })
    if (path === '/api/opportunities/projects') return route.fulfill({ json: { items: [], total: 0, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 't', generation: 'g' } })
    if (path === '/api/commercial/pursuits') return route.fulfill({ json: { items: [] } })
    return route.fulfill({ json: [] })
  })
  await mockDemandSummary(page)
  await page.goto('/?view=workspace&projectBrowse=1&need=need-l')
  await expect(page.locator('.cod-panel h2')).toBeVisible()
}
const usable = [
  { kind: 'phone', value: '+1 206 555 0184', verified_at: '2026-10-20T10:00:00Z' },
  { kind: 'email', value: 'pat@example.test', verified_at: '2026-10-20T10:00:00Z' },
]

test('Call and Email buttons appear only for usable values; no Confidence text; metrics honest', async ({ page }) => {
  await open(page, usable)
  await expect(page.getByRole('link', { name: 'Call +1 206 555 0184' })).toHaveAttribute('href', 'tel:+12065550184')
  await expect(page.getByRole('link', { name: 'Email pat@example.test' })).toHaveAttribute('href', 'mailto:pat@example.test')
  await expect(page.locator('.cod-panel')).not.toContainText(/confidence/i)
  await expect(page.locator('.cod-metrics')).toContainText('Power Need')
  await expect(page.locator('.cod-metrics')).toContainText('Power timing')
  await expect(page.locator('.cod-metrics')).toContainText('Power Gap')
  await expect(page.locator('.cod-metrics')).not.toContainText('Energization')
  await expect(page.locator('.cod-why')).toContainText('SYNTHETIC: Phased power may be needed.')
  await expect(page.locator('.cod-tier')).toHaveText('Prospect')
})

test('only phone is shown as a button when email is unusable (unverified, no source)', async ({ page }) => {
  await open(page, [usable[0], { kind: 'email', value: 'bad@example.test' }])
  await expect(page.getByRole('link', { name: /^Call / })).toHaveCount(1)
  await expect(page.getByRole('link', { name: /^Email / })).toHaveCount(0)
})

test('missing-contact state shows explicit message and contact evidence disclosure', async ({ page }) => {
  await open(page, [{ kind: 'phone', value: '123' }])
  await expect(page.getByRole('link', { name: /^(Call|Email) / })).toHaveCount(0)
  await expect(page.locator('.cod-contact-missing')).toContainText('No verified phone or email')
  await page.getByText('Inspect contact evidence').click()
  await expect(page.locator('.cod-contacts')).toContainText('Phone unavailable in retained contact evidence.')
  await expect(page.locator('.cod-contacts')).toContainText('Contact source: Synthetic notice')
})

test('action row order and equipment disclosure collapsed by default', async ({ page }) => {
  await open(page, usable)
  const actions = page.getByRole('group', { name: 'Opportunity actions' })
  const names = await actions.locator('button, a').allInnerTexts()
  expect(names.map(n => n.trim())).toEqual(['Add to Pursuit', 'View Full Details'])
  await expect(page.locator('.cod-equipment-demand')).not.toHaveAttribute('open', '')
  await expect(page.getByRole('region', { name: 'Equipment schedule demand' })).toHaveCount(0)
  await page.locator('.cod-equipment-demand > summary').click()
  await expect(page.getByRole('region', { name: 'Equipment schedule demand' })).toContainText('not a site or portfolio total')
  const after = await page.evaluate(() => !!(document.querySelector('.cod-contacts')!.compareDocumentPosition(document.querySelector('.cod-actions')!) & Node.DOCUMENT_POSITION_FOLLOWING))
  expect(after).toBe(true)
  await expect(page.locator('.cod-more-details')).not.toHaveAttribute('open', '')
})

test('390px has no horizontal overflow', async ({ page }) => {
  await open(page, usable, 390, 844)
  await expect(page.getByRole('link', { name: 'Call +1 206 555 0184' })).toBeVisible()
  await page.locator('.cod-equipment-demand > summary').click()
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  await expect.poll(() => page.evaluate(() => { const p = document.querySelector('.cod-panel')!; return p.scrollWidth <= p.clientWidth })).toBeTruthy()
})

for (const [width, height] of [[1648, 928], [1440, 900], [1280, 800], [390, 844]]) {
  test(`action buttons are fully inside the viewport at ${width}x${height}`, async ({ page }) => {
    await open(page, usable, width, height)
    for (const name of ['Add to Pursuit', 'View Full Details']) {
      const box = await page.getByRole('group', { name: 'Opportunity actions' }).getByText(name).boundingBox()
      expect(box, name).not.toBeNull()
      expect(box!.x).toBeGreaterThanOrEqual(0)
      expect(box!.y).toBeGreaterThanOrEqual(0)
      expect(box!.x + box!.width).toBeLessThanOrEqual(width)
      expect(box!.y + box!.height).toBeLessThanOrEqual(height)
    }
  })
}
