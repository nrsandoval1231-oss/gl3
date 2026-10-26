import { expect, test } from '@playwright/test'

const need = {
  id: 'need-a', project_id: 'project-a', name: 'Austin data center', location: 'Austin, TX', tier: 'Signal',
  workflow_status: 'UNKNOWN', activity: 'construction', rationale: 'A retained construction filing supports investigation.',
  signal_display_decision: 'REVIEW', signal_display_decision_state: 'adjudicated', signal_evidence_state: 'active_evidence',
  required_mw: null, supply: 'Unknown', start_window: null, duration: null, conflict_state: 'clear',
  project_identity_key: 'project-a', group_id: 'project-a', group_title: 'Austin data center', group_total_filtered: 2,
  group_loaded_on_page: 1, group_complete_on_page: false,
  evidence: [{ id: 'evidence-a', title: 'Construction filing', url: 'https://example.test/filing', published_at: '2026-10-01',
    retrieved_at: '2026-10-02T00:00:00Z', extraction_location: 'Description', content_hash: 'a'.repeat(64), event_date: null,
    event_date_label: 'Unknown', source_id: 'city-permits', document_number: 'permit-1', source_origin: 'City',
    abstract: 'A construction filing.', assessment_current: true }],
}

async function authenticated(page: import('@playwright/test').Page) {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
}

test('server-filtered SHOW group remains visible when only a REVIEW member is loaded', async ({ page }) => {
  await authenticated(page)
  await page.route('**/api/opportunities?*', route => route.fulfill({
    status: 200, contentType: 'application/json',
    headers: { 'X-Total-Count': '1', 'X-Group-Total-Count': '1', 'X-Page-Record-Count': '1', 'X-Page-Group-Count': '1',
      'X-Limit': '25', 'X-Offset': '0', 'X-Cohort-Token': 'show-cohort', 'X-Decision-Counts': '{"SHOW":1,"REVIEW":0,"HOLD":0}' },
    body: JSON.stringify([need]),
  }))
  await page.goto('/?view=signals&decision=SHOW')
  await expect(page.getByRole('heading', { name: 'Austin data center' })).toBeVisible()
  await expect(page.getByText('Decision: REVIEW')).toBeVisible()
})

test('active Opportunities navigation preserves its selected need and section after reload', async ({ page }) => {
  await authenticated(page)
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: {
    items: [{ ...need, signal_display_decision: 'SHOW', commercial_disposition: 'RESEARCH' }], total: 1,
    counts: { action_now: 0, research: 1, watch: 0, reject: 0 }, offset: 0, limit: 25, next_offset: null,
    cohort_token: 'workspace-cohort', count_unit: 'power needs', changes_available: false,
  } }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: need }))
  await page.goto('/?view=workspace&need=need-a&section=evidence')
  await expect(page.locator('.wh-detail').getByRole('button', { name: 'Evidence', exact: true })).toHaveClass(/active/)
  await page.getByRole('button', { name: 'Opportunities', exact: true }).click()
  await expect(page).toHaveURL(/need=need-a/)
  await expect(page).toHaveURL(/section=evidence/)
  await page.reload()
  await expect(page.locator('.wh-detail').getByRole('heading', { name: 'Austin data center' })).toBeVisible()
  await expect(page.locator('.wh-detail').getByRole('button', { name: 'Evidence', exact: true })).toHaveClass(/active/)
})

test('legacy source-sector aliases canonicalize selection, request, and URL', async ({ page }) => {
  await authenticated(page)
  await page.route('**/api/health', route => route.fulfill({ json: { sources: [], backlog: 0, pending_interpretations: 0 } }))
  const requests: string[] = []
  await page.route('**/api/ingestion*', route => {
    requests.push(new URL(route.request().url()).searchParams.get('vertical') ?? '')
    return route.fulfill({ json: { items: [], total: 0, limit: 25, offset: 0 } })
  })
  const aliases = [
    ['manufacturing', 'industrial-and-manufacturing'],
    ['Industrial%20%26%20manufacturing', 'industrial-and-manufacturing'],
    ['utilities', 'energy-and-utilities'],
    ['Energy%20%26%20utilities', 'energy-and-utilities'],
    ['Construction%20%26%20facilities', 'construction-and-facilities'],
    ['cannabis%20cultivation', 'cannabis'],
  ] as const
  for (const [legacy, canonical] of aliases) {
    await page.goto(`/?view=ingestion&vertical=${legacy}`)
    await expect(page.getByLabel('Filter by source sector', { exact: true })).toHaveValue(canonical)
    await expect(page).toHaveURL(new RegExp(`vertical=${canonical}`))
    await expect.poll(() => requests.at(-1)).toBe(canonical)
  }
})
