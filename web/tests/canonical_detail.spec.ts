import { expect, test } from '@playwright/test'
import { resolve } from 'node:path'

test.use({ timezoneId: 'America/Chicago' })

// SYNTHETIC UI TEST FIXTURE ONLY — these names, source URLs, contacts, dates, and power values are fabricated test data; they are not factual claims about real companies or sites.

const source = {
  reference: 'fixture:canonical-detail', title: 'Synthetic campus planning notice', url: 'https://sources.example.test/notice',
  source_date: '2026-10-20', retained_evidence_id: 'evidence-canonical', content_hash: 'c'.repeat(64), passage: 'Synthetic source fixture.',
  extraction_method: 'Official notice', verification_status: 'Current retained support',
}
const card = {
  policy_version: 'opportunity-intelligence-v1', need_id: 'need-canonical', project_id: 'project-canonical', input_fingerprint: 'd'.repeat(64),
  qualification: 'Lead', disposition: 'RESEARCH',
  fields: [
    { key: 'facility_demand', label: 'Facility demand', section: 'power', value: 'SYNTHETIC ≤1,200 MW', status: 'Source-reported', basis: 'Test fixture only; generated source record.', sources: [source] },
    { key: 'untrusted-link', label: 'Untrusted citation', section: 'commercial', value: 'Review carefully', status: 'Source-reported', basis: 'Test URL safety.', sources: [{ ...source, reference: 'fixture:unsafe', url: 'javascript:alert(1)' }] },
  ],
  contacts: [{ claim_id: 'contact-canonical', company: 'Example Compute Holdings (test fixture)', name: 'Alex Test Contact', title: 'Synthetic Infrastructure Role', role: 'owner developer', responsibility: 'Fixture-only contact role', purchasing_authority: 'Requires confirmation for this power package', methods: [
    { kind: 'phone', value: '+1 206 555 0184', href: 'tel:+12065550184', verified_at: '2026-10-20T10:00:00Z' },
    { kind: 'email', value: 'unverified@example.test', href: 'mailto:unverified@example.test', source_url: source.url },
  ], sources: [source] }],
  next_contact_path: 'Synthetic test action: confirm the temporary power package with the fixture contact.', next_action: 'Synthetic test action: confirm the fixture power package and schedule.',
  research_gaps: [], completeness: { supported: 1, total: 2, percent: 50, basis: 'Evidence support' },
  equipment_demand: { status: 'PARTIAL', classification: 'UNKNOWN', scope: 'equipment_schedule', as_of: '2026-10-15', lifecycle: ['proposed'], expected_start: ['2027-06-01'], next_action: 'Investigate source-backed equipment procurement timing and the responsible buyer.', demand: { connected_kw: '1250.123456789', coincident_kw: null, incremental_kw: '0' } },
  power_gap: { remaining_mw: 'Not established', status: 'unknown' }, evidence: [source], research_enabled: true,
}
const opportunity = {
  id: 'need-canonical', project_id: 'project-canonical', name: 'Synthetic Phoenix Campus Fixture', browse_title: 'Synthetic Phoenix Campus Fixture', location: 'Phoenix, AZ',
  tier: 'Lead', workflow_status: 'New', activity: 'data center construction', rationale: 'A retained planning notice identifies a campus project.', signal_evidence_state: 'active_evidence',
  required_mw: null, start_window: null, duration: null, supply: 'Unknown', next_action: 'Synthetic test action: confirm the fixture power package and schedule.', conflict_state: 'Not assessed',
  title_company: 'Example Compute Holdings (test fixture)', commercial_organization: 'Example Compute Holdings (test fixture)', commercial_reason: 'SYNTHETIC UI FIXTURE: The campus may require phased temporary power. Current demand and timing need confirmation.',
  evidence: [
    { id: 'source-good', title: 'Synthetic campus planning notice', abstract: 'Fabricated UI fixture record; not an actual source.', url: 'https://sources.example.test/notice', published_at: '2026-10-20T00:00:00Z', retrieved_at: '2026-10-21T00:00:00Z', extraction_location: 'Page 1', content_hash: 'a'.repeat(64), event_date: '2026-10-19', event_date_label: 'Permit issued', source_id: 'synthetic-fixture', document_number: 'TEST-10', source_origin: 'Synthetic fixture', assessment_current: true },
    { id: 'source-unsafe', title: 'Unsafe source', abstract: null, url: 'javascript:alert(1)', published_at: null, retrieved_at: '2026-10-21T00:00:00Z', extraction_location: 'Page 1', content_hash: 'b'.repeat(64), event_date: null, event_date_label: 'Unknown', source_id: 'unsafe', document_number: 'U-1', source_origin: 'Test', assessment_current: true },
  ], missing_facts: ['Temporary power package'], intelligence_card: card,
}
const secondOpportunity = {
  ...opportunity, id: 'need-second', project_id: 'project-second', name: 'Second Synthetic Campus Fixture', browse_title: 'Second Synthetic Campus Fixture',
  title_company: 'Second Synthetic Holdings', commercial_organization: 'Second Synthetic Holdings', evidence: [], intelligence_card: undefined,
}
const project = {
  id: 'project-canonical', project_id: 'project-canonical', name: 'Example Compute Holdings (test fixture) · Synthetic Phoenix Campus Fixture', company: 'Example Compute Holdings (test fixture)', location: 'Phoenix, AZ',
  sector: 'data_centers', asset_type: 'data_center_campus', priority_score: null, representative_need_id: 'need-canonical', need_count: 1,
  needs: [{ id: 'need-canonical', project_id: 'project-canonical', tier: 'Lead', activity: 'data center construction' }],
  event: { kind: 'permit_issued', label: 'Synthetic permit date', date: '2026-10-19', source: 'Synthetic fixture', evidence_refs: [] },
  contact: [
    { kind: 'call', label: 'Call Alex Test Contact', href: 'tel:+12065550184', route_kind: 'company_route', responsibility: 'General company contact path', support: 'Duplicate published route fixture' },
    { kind: 'call', label: 'Call Example Compute Holdings', href: 'tel:+12065550199', route_kind: 'company_route', responsibility: 'General company contact path', support: 'Published company contact route' },
    { kind: 'email', label: 'Email Alex Test Contact', href: 'mailto:unverified@example.test', route_kind: 'company_route', responsibility: 'General company contact path', support: 'Duplicate published route fixture' },
    { kind: 'email', label: 'Email Example Compute Holdings', href: 'mailto:contact@example.test', route_kind: 'company_route', responsibility: 'General company contact path', support: 'Published company contact route' },
    { kind: 'contact', label: 'Company contact page', href: 'https://example.test/contact', route_kind: 'company_route', responsibility: 'General company contact path', support: 'Published company contact route' },
    { kind: 'email', label: 'Email Alex Test Contact', href: 'mailto:alex@example.test', route_kind: 'person_method', responsibility: 'Verified project responsibility' },
  ], contact_people: [], power_summary: null, power_summary_kind: 'unknown', next_action: 'Synthetic test action: confirm fixture details.', updated_at: '2026-10-21T00:00:00Z',
}
const secondProject = {
  ...project, id: 'project-second', project_id: 'project-second', name: 'Second Synthetic Holdings · Second Synthetic Campus Fixture', company: 'Second Synthetic Holdings', representative_need_id: 'need-second',
  needs: [{ id: 'need-second', project_id: 'project-second', tier: 'Lead', activity: 'data center construction' }],
  contact: [{ kind: 'call', label: 'Call Second Synthetic Holdings', href: 'tel:+12065550222', route_kind: 'company_route', responsibility: 'General company contact path' }],
}
const projects = { items: [project, secondProject], total: 2, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'canonical-project', generation: 'synthetic-fixture' }

test('canonical detail tabs update browser history and render only source-backed, correctly attributed contact methods', async ({ page }) => {
  const projectReads: URL[] = []
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (url.pathname === '/api/opportunities/needs/need-canonical') return route.fulfill({ json: opportunity })
    if (url.pathname === '/api/opportunities/needs/need-second') return route.fulfill({ json: secondOpportunity })
    if (url.pathname === '/api/opportunities/projects') {
      projectReads.push(url)
      if (url.searchParams.get('need_id') === 'need-second') {
        await new Promise(resolve => setTimeout(resolve, 300))
        return route.abort('failed')
      }
      return route.fulfill({ json: projects })
    }
    if (url.pathname === '/api/evidence/source-good/content') return route.fulfill({ json: { evidence_id: 'source-good', content_hash: 'a'.repeat(64), source_url: 'https://sources.example.test/notice', offset: 0, total_chars: 28, content: 'SYNTHETIC FULL SOURCE CHUNK', next_offset: null } })
    if (url.pathname === '/api/projects/project-canonical/buying-chain') return route.fulfill({ json: { project_id: 'project-canonical', status: 'unavailable', candidates: [], unresolved: [], runs: [], permit_summaries: [], policy_version: 'buying-chain-v2-permits' } })
    if (url.pathname === '/api/commercial/triage/need-canonical/autonomous-research') return route.fulfill({ json: { items: [] } })
    return route.fulfill({ json: [] })
  })

  await page.goto('/?view=workspace&projectBrowse=1')
  await expect(page.locator('.cfr-table')).toContainText('Synthetic Phoenix Campus Fixture')
  await page.getByRole('button', { name: 'Open Synthetic Phoenix Campus Fixture' }).click()
  await expect(page.getByRole('heading', { name: 'Example Compute Holdings (test fixture) — Synthetic Phoenix Campus Fixture' })).toBeVisible()
  await expect(page.locator('.cod-tier')).toHaveText('Lead')
  await expect(page.locator('.cod-metrics')).toContainText('SYNTHETIC ≤1,200 MW')
  await expect(page.locator('.cod-details')).toContainText('Milestone date2026-10-19')
  await expect(page.locator('.cod-metrics')).not.toContainText('2026-10-19')
  await expect(page.locator('.cod-metrics')).toContainText('—')
  await expect(page.locator('.cod-metrics')).toContainText('Not established')
  await expect(page.getByRole('region', { name: 'Equipment schedule demand' })).toContainText('PARTIAL')
  await expect(page.getByRole('region', { name: 'Equipment schedule demand' })).toContainText('UNKNOWN')
  await expect(page.getByRole('region', { name: 'Equipment schedule demand' })).toContainText('Planned connected capacity1,250.1 kW')
  await expect(page.getByRole('region', { name: 'Equipment schedule demand' })).toContainText('Planned coincident operating capacityUnknown')
  await expect(page.getByRole('region', { name: 'Equipment schedule demand' })).toContainText('Planned incremental capacity0 kW')
  await expect(page.getByRole('region', { name: 'Equipment schedule demand' })).toContainText('Documented expected start6/1/2027')
  await expect(page.getByRole('region', { name: 'Equipment schedule demand' })).toContainText('Schedule as of10/15/2026')
  await expect(page.getByRole('region', { name: 'Equipment schedule demand' })).toContainText('proposed')
  await expect(page.getByRole('region', { name: 'Equipment schedule demand' })).toContainText('not a site or portfolio total')
  await expect(page.getByRole('region', { name: 'Equipment schedule demand' })).toContainText('Investigate source-backed equipment procurement timing and the responsible buyer.')
  await expect(page.getByRole('link', { name: 'Email unverified@example.test' })).toHaveAttribute('href', 'mailto:unverified@example.test')
  await expect(page.locator('.cod-contacts')).toContainText('verification not established')
  await expect(page.locator('.cod-contacts')).toContainText('Company phone')
  await expect(page.getByRole('link', { name: 'Call Example Compute Holdings' })).toHaveAttribute('href', 'tel:+12065550199')
  await expect(page.locator('.cod-contacts')).toContainText('Company email')
  await expect(page.getByRole('link', { name: 'Email Example Compute Holdings' })).toHaveAttribute('href', 'mailto:contact@example.test')
  await expect(page.getByRole('link', { name: 'Company contact page' })).toHaveAttribute('href', 'https://example.test/contact')
  await expect(page.getByRole('link', { name: 'Call Alex Test Contact' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'Email Alex Test Contact' })).toHaveCount(0)
  await expect(page.locator('.cod-verified-method').nth(0)).toContainText('Call +1 206 555 0184')
  await expect(page.locator('.cod-verified-method').nth(1)).toContainText('Email unverified@example.test')
  await expect(page.getByRole('link', { name: 'Email Alex Test Contact' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'Call +1 206 555 0184' })).toHaveAttribute('href', 'tel:+12065550184')
  await expect(page.locator('.cod-verified-method').first()).toContainText('Source checked 10/20/2026')
  await expect(page.getByRole('heading', { name: 'Decision Maker / Contact' })).toBeVisible()
  await expect(page.locator('.cod-contacts')).toContainText('Purchasing authority: Requires confirmation for this power package')
  await expect(page.locator('.cod-evidence-row time').first()).toHaveText('10/19/2026')
  await expect(page.locator('.cod-panel a[href^="javascript:"]')).toHaveCount(0)
  const safeLinks = await page.locator('.cod-panel a[href^="https://"]').evaluateAll(links => links.map(link => (link as HTMLAnchorElement).href))
  expect(safeLinks.length).toBeGreaterThanOrEqual(1)
  expect(safeLinks.every(href => href.startsWith('https://'))).toBe(true)
  await expect.poll(() => projectReads.filter(url => url.searchParams.get('need_id') === 'need-canonical').length).toBe(1)

  for (const viewport of [{ width: 1280, height: 720 }, { width: 1440, height: 900 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport)
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
    const filename = `.artifacts/canonical-pass4-${viewport.width}x${viewport.height}.png`
    await page.screenshot({ path: resolve(process.cwd(), '..', filename), fullPage: false })
  }

  await page.getByRole('button', { name: 'View all evidence' }).click()
  await expect(page).toHaveURL(/section=evidence/)
  await expect(page.getByRole('heading', { name: 'Evidence & Sources' })).toBeVisible()
  await expect(page.locator('.wh-detail-content a[href^="javascript:"]')).toHaveCount(0)
  await page.getByRole('button', { name: 'Load full source' }).click()
  await expect(page.locator('.wh-evidence-raw')).toContainText('SYNTHETIC FULL SOURCE CHUNK')
  await page.goBack()
  await expect(page).not.toHaveURL(/section=evidence/)
  await expect(page.getByRole('navigation', { name: 'Project detail sections' })).toBeVisible()

  card.fields[0].value = 'SYNTHETIC <10 MW'
  card.contacts[0].purchasing_authority = ''
  await page.getByRole('button', { name: '← Opportunities' }).click()
  await page.getByRole('button', { name: 'Open Synthetic Phoenix Campus Fixture' }).click()
  await expect(page.locator('.cod-metrics')).toContainText('SYNTHETIC <10 MW')
  await expect(page.locator('.cod-contacts')).toContainText('Purchasing authority: Authority not established')
  card.contacts[0].sources[0].verification_status = 'Historical support'
  await page.getByRole('button', { name: '← Opportunities' }).click()
  await page.getByRole('button', { name: 'Open Synthetic Phoenix Campus Fixture' }).click()
  await expect(page.getByRole('link', { name: 'Email unverified@example.test' })).toHaveCount(0)
  await expect(page.locator('.cod-contacts')).toContainText('Email unavailable in retained contact evidence.')
  await expect(page.getByRole('link', { name: 'Call +1 206 555 0184' })).toHaveAttribute('href', 'tel:+12065550184')

  const detailTabs = page.getByRole('navigation', { name: 'Project detail sections' })
  await detailTabs.getByRole('button', { name: 'Intelligence' }).click()
  await expect(page).toHaveURL(/section=unknowns/)
  await expect(page.getByRole('heading', { name: 'Commercial intelligence' })).toBeVisible()
  await detailTabs.getByRole('button', { name: 'Timeline' }).click()
  await expect(page).toHaveURL(/section=timeline/)
  await expect(page.getByText('Permit issued', { exact: true }).last()).toBeVisible()
  await detailTabs.getByRole('button', { name: 'Related' }).click()
  await expect(page).toHaveURL(/section=buying-chain/)
  await expect(page.getByRole('heading', { name: 'Buying chain' })).toBeVisible()
  await expect(page.getByText('No supported buying-chain candidates retained yet.')).toBeVisible()
  await expect(page.locator('[role="alert"]')).toHaveCount(0)
  await page.goBack()
  await expect(page).toHaveURL(/section=timeline/)
  await expect(page.getByRole('heading', { name: 'Timeline' })).toBeVisible()
  await detailTabs.getByRole('button', { name: 'Overview' }).click()
  await page.getByRole('button', { name: 'View research' }).click()
  await expect(page).toHaveURL(/section=research/)
  await expect(page.getByRole('heading', { name: 'Automated research' })).toBeVisible()

  await page.goto('/?view=workspace&projectBrowse=1&need=need-canonical&section=power-gap')
  await expect(page.getByText('Supply unknown or no supported remaining gap is available for this need.')).toBeVisible()
  await page.goto('/?view=workspace&projectBrowse=1&need=need-canonical')
  await expect(page.getByRole('link', { name: 'Call Example Compute Holdings' })).toBeVisible()
  await page.evaluate(() => {
    window.history.pushState({}, '', '/?view=workspace&projectBrowse=1&need=need-second')
    window.dispatchEvent(new PopStateEvent('popstate'))
  })
  await expect(page.getByRole('heading', { name: 'Second Synthetic Holdings — Second Synthetic Campus Fixture' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Call Example Compute Holdings' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'Company contact page' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'Call Second Synthetic Holdings' })).toHaveCount(0)
  await expect.poll(() => projectReads.filter(url => url.searchParams.get('need_id') === 'need-second').length).toBe(1)
  await expect(page.locator('.cod-status')).toBeVisible()
  await expect(page.locator('.cod-contacts')).not.toContainText('Example Compute Holdings')
})


test('native equipment proposal preserves historical date and unknown capacity on desktop and mobile', async ({ page }) => {
  const nativeCard = { ...card, qualification: 'Signal', contacts: [], fields: [], equipment_demand: {
    status: 'PARTIAL', classification: 'UNKNOWN', scope: 'identified_equipment_assertion',
    as_of: '2024-06-12', lifecycle: ['proposed'], expected_start: [],
    equipment: [{ quote: 'Install one new electric motor driven compressor unit with a rating of 18,340 hp.' }],
    demand: { connected_kw: null, coincident_kw: null, incremental_kw: null },
    next_action: 'Investigate current plans and missing electrical specifications.',
  } }
  const nativeOpportunity = { ...opportunity, tier: 'Signal', intelligence_card: nativeCard }
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (path === '/api/opportunities/needs/need-canonical') return route.fulfill({ json: nativeOpportunity })
    if (path === '/api/opportunities/projects') return route.fulfill({ json: projects })
    return route.fulfill({ json: [] })
  })
  await page.goto('/?view=workspace&projectBrowse=1&need=need-canonical')
  const proposal = page.getByRole('region', { name: 'Source-reported equipment proposal' })
  for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport)
    await expect(proposal).toBeVisible()
    await expect(proposal).toContainText('Source proposal as of6/12/2024')
    await expect(proposal).toContainText('Current status and site demand remain unverified.')
    await expect(proposal).toContainText('Equipment reported by source: Install one new electric motor driven compressor unit with a rating of 18,340 hp.')
    await expect(proposal).toContainText('Planned connected capacityUnknown')
    await expect(proposal).toContainText('Documented expected startUnknown')
    await expect(proposal).not.toContainText('0 kW')
    await expect(page.getByRole('region', { name: 'Equipment schedule demand' })).toHaveCount(0)
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  }
})
