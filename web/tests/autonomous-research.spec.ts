import { expect, test } from '@playwright/test'

const need = {
  id: 'need-demo', project_id: 'project-demo', name: 'Ridgeview commissioning', browse_title: 'Ridgeview commissioning', title_status: 'unavailable',
  location: 'Austin, TX', tier: 'Prospect', workflow_status: 'UNKNOWN', activity: 'commissioning', rationale: 'Current source-backed project opportunity.',
  signal_evidence_state: 'active_evidence', required_mw: null, qualified_remaining_gap: null, start_window: null, duration: null, supply: 'Unknown',
  next_action: 'Current timing is unknown.', conflict_state: 'clear', missing_facts: ['Temporary demand', 'Power start date'], evidence: [],
  intelligence_card: {
    policy_version: 'test', need_id: 'need-demo', project_id: 'project-demo', input_fingerprint: 'test', qualification: 'Prospect', disposition: 'RESEARCH',
    fields: [{ key: 'project', label: 'Project', section: 'identity', status: 'Verified', value: 'Ridgeview commissioning', basis: 'Publisher filing' }, { key: 'customer', label: 'Company', section: 'identity', status: 'Verified', value: 'Ridgeview Energy', basis: 'Publisher filing' }],
    contacts: [{ claim_id: 'contact-1', company: 'Ridgeview Energy', name: 'Morgan Lee', title: 'Director, Construction', role: 'Project buyer', responsibility: 'Verified project responsibility', purchasing_authority: 'Purchasing authority requires confirmation', methods: [{ kind: 'email', value: 'morgan@example.test', href: 'mailto:morgan@example.test', verified_at: '2026-10-25T00:00:00Z' }], verified_at: '2026-10-25T00:00:00Z', sources: [] }],
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
  const longCompany = `Northstar${'Compute'.repeat(14)}`
  const longEmail = `morgan.${'construction'.repeat(9)}@${'northstar-energy-'.repeat(7)}example.com`
  const longNeed = {
    ...need,
    commercial_organization: longCompany,
    intelligence_card: {
      ...need.intelligence_card,
      fields: need.intelligence_card.fields.map(field => field.key === 'customer' ? { ...field, value: longCompany } : field),
      contacts: need.intelligence_card.contacts.map(contact => ({
        ...contact, company: longCompany,
        methods: contact.methods.map(method => ({ ...method, value: longEmail, href: `mailto:${longEmail}` })),
      })),
    },
  }
  const longThinNeed = { ...longNeed, title_company: longCompany, intelligence_card: undefined }
  await page.route('**/api/opportunities/workspace?**', route => route.fulfill({ json: { ...workspace, items: [longThinNeed] } }))
  await page.route('**/api/opportunities/needs/need-demo**', route => route.fulfill({ json: longNeed }))
  const writes: string[] = []
  await page.route('**/api/**', async route => {
    if (route.request().method() !== 'GET' && !route.request().url().includes('/api/auth/session')) writes.push(`${route.request().method()} ${route.request().url()}`)
    await route.fallback()
  })
  await page.goto('/?view=pursuits')
  await expect(page.getByRole('heading', { name: 'Research', exact: true })).toBeVisible()
  await page.getByRole('button', { name: /Northstar/ }).click()
  await expect(page.getByRole('heading', { name: 'Ridgeview commissioning' })).toBeVisible()
  await expect(page.getByRole('link', { name: longEmail })).toHaveAttribute('href', `mailto:${longEmail}`)
  await expect(page.locator('.research-detail-heading').getByText(longCompany)).toBeVisible()
  await expect(page.getByText('Purchasing authority requires confirmation')).toBeVisible()
  await expect(page.getByText('Confidence', { exact: true })).toBeVisible()
  await expect(page.locator('.research-detail-heading dd').filter({ hasText: 'Not provided' })).toBeVisible()
  await expect(page.getByText(/Temporary demand: Unknown/)).toBeVisible()
  await expect(page.locator('.research-gaps li').filter({ hasText: /^Temporary demand$/ })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Automated research' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Business contacts' })).toBeVisible()
  await expect(page.getByText('Evidence assessed 10/25/2026')).toBeVisible()
  await expect(page.getByRole('button', { name: /call|fact|workflow|enrich|correct|retract|research this question|save/i })).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: test.info().outputPath('mobile-research.png'), fullPage: true })
  expect(writes).toEqual([])
})

test('Research reports contact detail unavailable when the selected need read fails', async ({ page }) => {
  await install(page)
  let detailReads = 0
  await page.route('**/api/opportunities/needs/need-demo**', route => {
    detailReads += 1
    return detailReads === 1
      ? route.fulfill({ status: 503, json: { detail: 'detail unavailable' } })
      : route.fulfill({ json: need })
  })
  await page.goto('/?view=pursuits')
  await page.getByRole('button', { name: /Ridgeview Energy/ }).click()
  const contacts = page.getByRole('region', { name: 'Business contacts' })
  await expect(contacts.getByText(/No conclusion about missing contacts can be drawn/)).toBeVisible()
  await expect(contacts.getByText('No source-backed business contact is currently available.')).toHaveCount(0)
  await expect(contacts.getByText('Morgan Lee')).toHaveCount(0)
  await contacts.getByRole('button', { name: 'Retry contact detail' }).click()
  await expect(contacts.getByRole('link', { name: 'morgan@example.test' })).toHaveAttribute('href', 'mailto:morgan@example.test')
})

test('Research treats a successful detail response without an intelligence card as unavailable', async ({ page }) => {
  await install(page)
  await page.route('**/api/opportunities/needs/need-demo**', route => route.fulfill({ json: { ...need, intelligence_card: null } }))
  await page.goto('/?view=pursuits')
  await page.getByRole('button', { name: /Ridgeview Energy/ }).click()
  const contacts = page.getByRole('region', { name: 'Business contacts' })
  await expect(contacts.getByText(/No conclusion about missing contacts can be drawn/)).toBeVisible()
  await expect(contacts.getByText('No source-backed business contact is currently available.')).toHaveCount(0)
  await expect(contacts.getByRole('button', { name: 'Retry contact detail' })).toBeVisible()
})

test('Research does not show a prior project contact after a rapid selection change', async ({ page }) => {
  await install(page)
  const secondNeed = {
    ...need,
    id: 'need-two', project_id: 'project-two', name: 'Lakeshore commissioning', browse_title: 'Lakeshore commissioning',
    commercial_organization: 'Second Energy',
    intelligence_card: {
      ...need.intelligence_card,
      need_id: 'need-two', project_id: 'project-two',
      fields: need.intelligence_card.fields.map(field => field.key === 'customer' ? { ...field, value: 'Second Energy' } : field.key === 'project' ? { ...field, value: 'Lakeshore commissioning' } : field),
      contacts: [{ ...need.intelligence_card.contacts[0], claim_id: 'contact-two', company: 'Second Energy', name: null, methods: [{ kind: 'phone', value: '+13125550188', href: 'tel:+13125550188' }] }],
    },
  }
  await page.route('**/api/opportunities/workspace?**', route => route.fulfill({ json: { ...workspace, items: [need, secondNeed] } }))
  let releaseFirst: (() => void) | undefined
  let markFirstStarted: (() => void) | undefined
  let markFirstFinished: (() => void) | undefined
  const firstHeld = new Promise<void>(resolve => { releaseFirst = resolve })
  const firstStarted = new Promise<void>(resolve => { markFirstStarted = resolve })
  const firstFinished = new Promise<void>(resolve => { markFirstFinished = resolve })
  await page.route('**/api/opportunities/needs/**', async route => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname.endsWith('/need-demo')) {
      markFirstStarted?.()
      await firstHeld
      try { await route.fulfill({ json: need }) } catch { /* the selected request was aborted */ }
      markFirstFinished?.()
      return
    }
    if (pathname.endsWith('/need-two')) return route.fulfill({ json: secondNeed })
    await route.fallback()
  })
  await page.goto('/?view=pursuits')
  await page.getByRole('button', { name: /Ridgeview Energy/ }).click()
  await firstStarted
  await page.getByRole('button', { name: /Second Energy/ }).click()
  const contacts = page.getByRole('region', { name: 'Business contacts' })
  await expect(contacts.getByRole('link', { name: '+13125550188' })).toHaveAttribute('href', 'tel:+13125550188')
  await expect(contacts.getByText('Morgan Lee')).toHaveCount(0)
  releaseFirst?.()
  await firstFinished
  await expect(contacts.getByRole('link', { name: '+13125550188' })).toBeVisible()
  await expect(contacts.getByText('Morgan Lee')).toHaveCount(0)
})

test('Research hides the previous cohort while a new search loads or fails', async ({ page }) => {
  await install(page)
  let releaseFailure: (() => void) | undefined
  const blocked = new Promise<void>(resolve => { releaseFailure = resolve })
  await page.route('**/api/opportunities/workspace?**', route => {
    const query = new URL(route.request().url()).searchParams.get('search')
    if (query === 'Missing') return blocked.then(() => route.fulfill({ status: 503, json: { detail: 'cohort unavailable' } }))
    return route.fulfill({ json: workspace })
  })
  await page.goto('/?view=pursuits')
  await page.getByRole('button', { name: /Ridgeview Energy/ }).click()
  await expect(page.getByRole('heading', { name: 'Ridgeview commissioning' })).toBeVisible()
  const search = page.getByRole('textbox', { name: 'Search research opportunities' })
  await search.fill('Missing')
  await expect(page.getByText('Loading current opportunities…')).toBeVisible()
  await expect(page.locator('.research-opportunity-list').getByRole('button', { name: /Ridgeview/ })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Ridgeview commissioning' })).toHaveCount(0)
  releaseFailure?.()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByText('No opportunities match this search.')).toHaveCount(0)
})

test('Back to opportunities clears the selected research URL across reloads', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await install(page)
  await page.goto('/?view=pursuits')
  await page.getByRole('button', { name: /Ridgeview Energy/ }).click()
  await expect(page.getByRole('heading', { name: 'Ridgeview commissioning' })).toBeVisible()
  await page.getByRole('button', { name: 'Back to opportunities' }).click()
  expect(new URL(page.url()).searchParams.has('researchNeed')).toBe(false)
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Select an opportunity' })).toBeVisible()
})

test('project search surfaces matching project cards and opens a matching need', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await install(page)
  const longCompany = `Ridgeview${'Energy'.repeat(16)}`
  const longEmail = `morgan.${'project-buyer'.repeat(8)}@${'ridgeview-power-'.repeat(7)}example.com`
  const projectResults = {
    items: [{ id: 'project-demo', project_id: 'project-demo', representative_need_id: 'need-demo', name: 'Ridgeview commissioning', company: longCompany, location: 'Austin, TX', sector: 'oil_gas', asset_type: 'processing_plant', priority_score: 1, needs: [need], need_count: 1, event: null, contact: [{ kind: 'email', label: 'Email Morgan Lee', href: `mailto:${longEmail}`, name: 'Morgan Lee', title: 'Director, Construction', company: longCompany }], power_summary: 'Power need to confirm', next_action: 'Confirm project timing', updated_at: '2026-10-25T00:00:00Z' }], total: 1, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'synthetic', generation: 'synthetic', results_scope: 'discovery'
  }
  const searchNeed = { ...need, intelligence_card: { ...need.intelligence_card, contacts: need.intelligence_card.contacts.map(contact => ({ ...contact, company: longCompany, methods: contact.methods.map(method => ({ ...method, value: longEmail, href: `mailto:${longEmail}` })) })) } }
  await page.route('**/api/opportunities/needs/need-demo**', route => route.fulfill({ json: searchNeed }))
  const projectQueries: string[] = []
  await page.route('**/api/opportunities/projects?**', route => { projectQueries.push(new URL(route.request().url()).searchParams.get('search') ?? ''); return route.fulfill({ json: projectResults }) })
  await page.goto('/?view=workspace&projectBrowse=1')
  const search = page.getByLabel('Search opportunities')
  await search.fill('Morgan')
  await expect.poll(() => projectQueries).toContain('Morgan')
  await expect(page.getByRole('button', { name: 'Ridgeview commissioning', exact: true })).toBeVisible()
  await expect(page.locator('.canonical-flat-results')).toContainText(longCompany)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: test.info().outputPath('mobile-search.png'), fullPage: true })
  await page.getByRole('button', { name: 'Open Ridgeview commissioning', exact: true }).click()
  await expect(page.locator('.cod-panel').getByRole('heading', { name: `${longCompany} — Ridgeview commissioning` })).toBeVisible()
  await expect(page.locator('.cod-contacts a')).toHaveAttribute('href', `mailto:${longEmail}`)
})

test('project search drops prior results after a failed query', async ({ page }) => {
  await install(page)
  const projectResults = { items: [{ id: 'project-demo', project_id: 'project-demo', representative_need_id: 'need-demo', name: 'Ridgeview commissioning', company: 'Ridgeview Energy', location: 'Austin, TX', sector: 'oil_gas', asset_type: 'processing_plant', priority_score: 1, needs: [need], need_count: 1, event: null, contact: [], power_summary: 'Power need to confirm', next_action: 'Confirm project timing', updated_at: null }], total: 1, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'synthetic', generation: 'synthetic', results_scope: 'discovery' }
  const projectQueries: string[] = []
  await page.route('**/api/opportunities/projects?**', route => {
    const query = new URL(route.request().url()).searchParams.get('search') ?? ''
    projectQueries.push(query)
    if (query === 'Failure') return route.fulfill({ status: 503, json: { detail: 'unavailable' } })
    return route.fulfill({ json: projectResults })
  })
  await page.goto('/?view=workspace&projectBrowse=1')
  const search = page.getByLabel('Search opportunities')
  await search.fill('Ridgeview')
  await expect.poll(() => projectQueries).toContain('Ridgeview')
  const hit = page.getByRole('button', { name: 'Open Ridgeview commissioning', exact: true })
  await expect(hit).toBeEnabled()
  await hit.click()
  await expect(page.locator('.cod-panel').getByRole('heading', { name: 'Ridgeview Energy — Ridgeview commissioning' })).toBeVisible()
  await page.goBack()
  await search.fill('Failure')
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.locator('.cfr-table tbody tr')).toHaveCount(0)
})

test('All search explains when no source-backed operator/customer groups match', async ({ page }) => {
  await install(page)
  await page.route('**/api/opportunities/groups?**', route => route.fulfill({ json: { items: [], total: 0, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'synthetic', generation: 'synthetic' } }))
  await page.goto('/?view=workspace&groupBrowse=1')
  await page.getByLabel('Search opportunities').fill('Ridgeview')
  await expect(page.getByText(/No groups match this search/)).toBeVisible()
})
