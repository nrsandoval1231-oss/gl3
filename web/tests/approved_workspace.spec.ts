import { expect, test } from '@playwright/test'

const source = {
  reference: 'evidence:approved-fixture', title: 'Retained site development notice', url: 'https://example.test/notice',
  source_date: '2026-10-20', retained_evidence_id: 'retained-a', content_hash: 'a'.repeat(64),
  passage: 'Synthetic approved fixture: the notice identifies the North Austin site, reports 184.75 MW of full facility buildout demand, a 12.75–19.5 MW phased construction package with a 3.25–6.75 MW potential bridge gap, Q3 2027 utility energization, and 24–36 months of staged construction and commissioning.', extraction_method: 'Official notice',
  verification_status: 'Current retained support',
}
const card = {
  policy_version: 'opportunity-intelligence-v1', need_id: 'need-a', project_id: 'project-a',
  input_fingerprint: 'b'.repeat(64), qualification: 'Signal', disposition: 'RESEARCH',
  fields: [
    { key: 'customer', label: 'Customer / end user', section: 'identity', value: 'A very long customer organization name for a multi-phase advanced manufacturing and industrial infrastructure development company', status: 'Reported', basis: 'Identified in retained source.', sources: [source] },
    { key: 'project', label: 'Project', section: 'identity', value: 'North Austin Advanced Manufacturing Campus Construction and Electrical Infrastructure Development Project', status: 'Reported', basis: 'Source title.', sources: [source] },
    { key: 'power', label: 'Power activity', section: 'power', value: 'Construction', status: 'Reported', basis: 'Permit scope.', sources: [source] },
    { key: 'facility_demand', label: 'Facility demand', section: 'power', value: '184.75 MW across the complete facility buildout; it does not represent the temporary construction load', status: 'Reported', basis: 'The notice reports aggregate facility buildout demand and distinguishes it from the activity-specific construction package.', sources: [source] },
    { key: 'energization', label: 'Utility energization', section: 'power', value: 'North Austin substation energization targeted for Q3 2027 after substation feeder acceptance', status: 'Reported', basis: `The notice attributes the target to the utility coordination milestone; retained source record ${'TXPUCT2026UTILITYCOORDINATIONREFERENCE'.repeat(3)}.`, sources: [source] },
  ],
  contacts: [{ claim_id: 'contact-a', company: 'A very long customer organization name for a multi-phase advanced manufacturing and industrial infrastructure development company', name: 'Alexandra Longname-Sample', title: 'Director, Infrastructure Programs', role: 'Owner developer', responsibility: 'Source-supported project involvement', purchasing_authority: 'Requires confirmation for this power package', methods: [{ kind: 'phone', value: '+1 512 555 0100', href: 'tel:+15125550100', source_url: source.url }], sources: [source] }],
  next_contact_path: 'Confirm which organization owns temporary power procurement for this specific multi-phase construction and commissioning package.',
  next_action: 'Verify the activity-specific power window and remaining utility capacity with the source-listed organization.',
  research_gaps: [{ key: 'start', label: 'Power needed by', section: 'power', value: null, status: 'Research in progress', basis: 'No supported date is available yet.', research_category: 'timing', research_status: 'NOT_SCHEDULED', sources: [] }],
  completeness: { supported: 3, total: 8, percent: 38, basis: 'Independent of qualification' },
  last_intelligence_update: '2026-10-20T10:00:00Z', power_gap: { remaining_mw: '3.25–6.75 MW of potential residual bridge power during phase one construction', status: 'reported_with_unresolved_supply_conflict' }, evidence: [source], research_enabled: true,
}
const needA = {
  id: 'need-a', project_id: 'project-a', name: 'North Austin Advanced Manufacturing Campus Construction and Electrical Infrastructure Development Project',
  browse_title: 'North Austin Advanced Manufacturing Campus Construction and Electrical Infrastructure Development Project', location: 'Austin, TX', tier: 'Signal',
  workflow_status: 'New', activity: 'construction', rationale: 'A retained project filing supports investigation.',
  signal_evidence_state: 'active', conflict_state: 'Not assessed', required_mw: '12.75–19.5 MW for the phased temporary construction power package', supply: 'Unknown', start_window: 'Q3 2027 after substation feeder acceptance, followed by staged construction and commissioning', duration: '24–36 months across the staged construction and commissioning sequence',
  evidence: [{ source_id: 'city-permit', document_number: 'P-1', title: 'Retained site development notice', url: source.url, published_at: null, retrieved_at: '2026-10-20T10:00:00Z', event_date: '2026-10-19', event_date_label: 'Event date', source_origin: 'City permits', extraction_location: 'Page 1', abstract: source.passage, content_hash: 'a'.repeat(64), assessment_current: true }],
  missing_facts: ['Activity-specific load', 'Suitable utility supply'], project_identity_key: 'project-a',
  commercial_disposition: 'RESEARCH', commercial_reason: 'The 12.75–19.5 MW temporary construction package is activity-specific; 184.75 MW is the complete facility buildout.',
  commercial_next_question: 'Who owns the electrical scope?', commercial_next_action: 'Confirm the power package and expected timing.', commercial_organization: 'A very long customer organization name for a multi-phase advanced manufacturing and industrial infrastructure development company',
  intelligence_card: card,
}
const needB = { ...needA, id: 'need-b', project_id: 'project-b', name: 'Second supported power need', browse_title: 'Second supported power need', required_mw: '', start_window: '', duration: '', intelligence_card: { ...card, need_id: 'need-b', project_id: 'project-b', power_gap: { remaining_mw: '', status: '' }, fields: card.fields.filter(field => !['facility_demand', 'energization'].includes(field.key)).map(field => field.key === 'customer' ? { ...field, value: 'Example Customer' } : field.key === 'project' ? { ...field, value: 'Second supported power need' } : field), contacts: [], evidence: [] }, evidence: needA.evidence }

test('account-first workspace keeps scoped project evidence, contacts, history, and responsive access', async ({ page }, testInfo) => {
  let providerPosts = 0
  const projectA = {
    id: 'project-a', project_id: 'project-a', name: needA.name, company: card.fields[0].value, location: 'Austin, TX', sector: 'data_centers', asset_type: 'data_center', priority_score: 8,
    representative_need_id: 'need-a', needs: [{ id: 'need-a', project_id: 'project-a', name: needA.name, activity: 'construction', tier: 'Signal' }], need_count: 1,
    event: { kind: 'permit_issued', label: 'Construction permit issued', date: '2026-10-19', source: source.url, evidence_refs: [source.reference] },
    contact: [{ kind: 'phone', label: 'Call Alexandra Longname-Sample', href: 'tel:+15125550100', name: 'Alexandra Longname-Sample', title: 'Director, Infrastructure Programs', company: card.fields[0].value, source_url: source.url }],
    contact_people: [], power_summary: '12.75–19.5 MW temporary construction package', power_amount_class: 'documented', power_summary_kind: 'activity_requirement',
    next_action: 'Verify the activity-specific power window and remaining utility capacity.', shortlist_assessment: { why_now: 'A current permit supports review of the construction package.', next_step: 'Confirm activity-specific power timing.', evidence_refs: [source.reference] }, updated_at: '2026-10-20T10:00:00Z',
  }
  const projectB = { ...projectA, id: 'project-b', project_id: 'project-b', name: needB.name, representative_need_id: 'need-b', needs: [{ id: 'need-b', project_id: 'project-b', name: needB.name, activity: 'construction', tier: 'Signal' }] }
  const projects = [projectA, projectB]
  const projectPage = { items: projects, total: 2, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'project-page', generation: 'synthetic', valid_until: '2099-01-01T00:00:00Z' }
  const group = { id: 'cg_approved_fixture', name: card.fields[0].value, role: 'operator', group_kind: 'resolved_identity', project_count: 2, total_known_project_count: 2, relevant_project_count: 2, eligible_need_count: 2, eligible_need_ids: ['need-a', 'need-b'], pursued_eligible_need_count: 0, need_count: 2, sectors: ['data_centers'], featured_project: projectA }
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    if (request.method() === 'POST') providerPosts += 1
    if (path === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (path === '/api/opportunities/groups') return route.fulfill({ json: { items: [group], totals: { accounts: 1, projects: 2, needs: 2 }, total: 1, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'group-page', generation: 'synthetic', valid_until: '2099-01-01T00:00:00Z' } })
    if (path === `/api/opportunities/groups/${group.id}/open`) return route.fulfill({ json: { group, projects: projectPage, parent_cohort_token: 'group-page', generation: 'synthetic', valid_until: '2099-01-01T00:00:00Z' } })
    if (path === `/api/opportunities/groups/${group.id}/projects`) return route.fulfill({ json: projectPage })
    if (path === '/api/projects/project-a/account' || path === '/api/projects/project-b/account') return route.fulfill({ json: { id: group.id, name: group.name, group_kind: group.group_kind, project_id: path.includes('project-a') ? 'project-a' : 'project-b' } })
    if (path === '/api/opportunities/projects') return route.fulfill({ json: { ...projectPage, items: url.searchParams.get('need_id') === 'need-b' ? [projectB] : [projectA] } })
    if (path === '/api/opportunities/needs/need-a') return route.fulfill({ json: needA })
    if (path === '/api/opportunities/needs/need-b') return route.fulfill({ json: needB })
    if (path === '/api/commercial-pursuits') return route.fulfill({ json: { items: [], counts: { total: 0, active: 0, needs_attention: 0 } } })
    if (path === '/api/opportunities/workspace/changes') return route.fulfill({ json: { items: [], counts: { discovered: 0, changed: 0, promoted: 0, closed: 0, review_exception: 0 }, total_unreviewed: 0, offset: 0, limit: 50, next_offset: null, baseline_identity: 'test', token: 'test', source_health_exceptions: [] } })
    return route.fulfill({ json: [] })
  })

  await page.setViewportSize({ width: 1280, height: 720 })
  await page.goto('/?view=workspace&groupBrowse=1&shortlist=1')
  await expect(page.getByRole('heading', { name: 'Commercial intelligence for constrained power.' })).toBeVisible()
  const account = page.locator('.workspace-account')
  const accountSummary = account.getByRole('button', { name: 'Account menu' })
  const signOut = page.getByRole('button', { name: 'Sign out' })
  await accountSummary.focus()
  await page.keyboard.press('Enter')
  await expect(accountSummary).toHaveAttribute('aria-expanded', 'true')
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'Research progress' })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'Signals' })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'Technical diagnostics' })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(signOut).toBeFocused()
  await accountSummary.press('Enter')
  await expect(accountSummary).toHaveAttribute('aria-expanded', 'false')
  await expect(page.locator('.customer-group')).toContainText('A current permit supports review of the construction package.')
  await expect(page.getByRole('link', { name: 'Call Alexandra Longname-Sample' })).toHaveAttribute('href', 'tel:+15125550100')
  await expect(page.getByRole('button', { name: /Choose opportunity/ })).toBeVisible()
  await page.getByRole('button', { name: /Choose opportunity/ }).click()
  await expect(page.getByRole('region', { name: `Company ${group.name}` })).toBeVisible()
  await page.goBack()
  await expect(page.locator('.customer-group')).toBeVisible()
  await page.goForward()
  await expect(page.getByRole('region', { name: `Company ${group.name}` })).toBeVisible()
  await page.setViewportSize({ width: 1280, height: 800 })
  await expect(page.locator('.cmp-company')).toContainText('A current permit supports review of the construction package.')
  await page.getByRole('button', { name: /Open project detail .*North Austin Advanced Manufacturing/ }).click()
  await expect(page).toHaveURL(/need=need-a/)
  await expect(page.locator('.cod-panel')).toContainText('Activity-specific power need')
  await expect(page.locator('.cod-panel')).toContainText('12.75–19.5 MW for the phased temporary construction power package')
  await expect(page.locator('.cod-panel')).toContainText('The 12.75–19.5 MW temporary construction package is activity-specific; 184.75 MW is the complete facility buildout.')
  await expect(page.locator('.cod-panel')).toContainText('Alexandra Longname-Sample')
  await expect(page.getByRole('link', { name: 'Call +1 512 555 0100' })).toHaveAttribute('href', 'tel:+15125550100')
  const sources = page.locator('.cod-account-sources')
  await expect(sources).not.toHaveAttribute('open', '')
  await sources.locator('summary').click()
  await expect(sources.getByRole('link', { name: 'Retained site development notice' })).toHaveAttribute('href', source.url)
  await expect(sources).toContainText('North Austin site')
  await expect(sources).toContainText('184.75 MW of full facility buildout demand')
  await page.getByRole('button', { name: '← Back to account' }).click()
  await expect(page.getByRole('region', { name: `Company ${group.name}` })).toBeVisible()
  await page.getByRole('button', { name: /Open project detail .*Second supported power need/ }).click()
  await expect(page).toHaveURL(/need=need-b/)
  await page.goBack()
  await expect(page).not.toHaveURL(/need=need-b/)
  await expect(page.getByRole('region', { name: `Company ${group.name}` })).toBeVisible()
  await page.goForward()
  await expect(page).toHaveURL(/need=need-b/)
  await expect(page.getByRole('heading', { name: 'Second supported power need' })).toBeVisible()
  expect(providerPosts).toBe(0)

  for (const [width, height] of [[1648, 928], [1440, 900], [1280, 800], [768, 1024], [390, 844]]) {
    await page.setViewportSize({ width, height })
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    await page.screenshot({ path: testInfo.outputPath(`account-detail-${width}x${height}.png`), fullPage: false })
  }
  expect(providerPosts).toBe(0)
})
