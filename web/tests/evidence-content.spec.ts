import { expect, test } from '@playwright/test'

test('raw source content loads only on request and uses bounded chunks', async ({ page }) => {
  const needId = '11111111-1111-4111-8111-111111111111'
  const evidenceId = '22222222-2222-4222-8222-222222222222'
  const rawRequests: URL[] = []
  const opportunity = {
    id: needId, project_id: '33333333-3333-4333-8333-333333333333', name: 'Pecos County Data Center',
    location: 'Fort Stockton, TX', tier: 'Signal', workflow_status: 'UNKNOWN', activity: 'construction',
    rationale: 'A retained TDLR registration supports investigation.', signal_evidence_state: 'active_evidence',
    required_mw: null, start_window: null, duration: null, supply: 'Unknown', next_action: 'Confirm the activity scope.',
    conflict_state: 'Not assessed', commercial_disposition: 'RESEARCH', commercial_reason: 'Power details are unknown.',
    evidence: [{ id: evidenceId, title: 'Pecos County Data Center registration', abstract: 'Project: Pecos County Data Center. Scope: New data center building.',
      url: 'https://example.test/tdlr', published_at: null, retrieved_at: '2026-10-24T12:00:00Z', extraction_location: 'TDLR project page',
      content_hash: 'a'.repeat(64), event_date: null, event_date_label: 'TDLR registration', source_id: 'texas-tdlr-tabs-data-centers',
      document_number: 'TABS-1', source_origin: 'Official TDLR record', assessment_current: true, permit_status: null }],
  }
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url())
    const path = url.pathname
    if (!path.startsWith('/api/')) return route.continue()
    if (path === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (path === '/api/opportunities/workspace/changes' || path === '/api/changes') return route.fulfill({ json: { items: [], counts: {}, total_unreviewed: 0, offset: 0, limit: 50, next_offset: null, source_health_exceptions: [] } })
    if (path === '/api/opportunities/workspace') return route.fulfill({ json: { items: [opportunity], total: 1, counts: { action_now: 0, research: 1, watch: 0, reject: 0 }, offset: 0, limit: 25, next_offset: null, cohort_token: 'evidence-test', count_unit: 'power needs', changes_available: false } })
    if (path === `/api/opportunities/needs/${needId}`) return route.fulfill({ json: opportunity })
    if (path === '/api/health') return route.fulfill({ json: { sources: [], backlog: 0, pending_interpretations: 0 } })
    if (path === `/api/evidence/${evidenceId}/content`) {
      rawRequests.push(url)
      const first = url.searchParams.get('offset') === '0'
      return route.fulfill({ json: { evidence_id: evidenceId, content_hash: 'a'.repeat(64), source_url: 'https://example.test/tdlr', offset: first ? 0 : 8, total_chars: 16, content: first ? 'raw part' : ' 2 data', next_offset: first ? 8 : null } })
    }
    return route.fulfill({ status: 404, json: { detail: 'Not found' } })
  })

  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Opportunity Intelligence' })).toBeVisible()
  await page.locator(`[data-need-row="${needId}"]`).click()
  await page.getByRole('button', { name: 'Evidence' }).click()
  await expect(page.getByText(/Project: Pecos County Data Center/)).toBeVisible()
  expect(rawRequests).toHaveLength(0)

  await page.getByRole('button', { name: 'Load full source' }).click()
  await expect(page.getByText('raw part')).toBeVisible()
  expect(rawRequests).toHaveLength(1)
  expect(rawRequests[0].searchParams.get('limit')).toBe('4096')
  await page.getByRole('button', { name: 'Load next section' }).click()
  await expect(page.getByText('raw part 2 data')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Full source loaded' })).toBeVisible()
  expect(rawRequests).toHaveLength(2)
})
