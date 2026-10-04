import { expect, test } from '@playwright/test'

test('detail explicitly requests a brief, polls pending state, and resolves source links', async ({ page }) => {
  const id = '11111111-1111-4111-8111-111111111111'
  let getCount = 0
  let posted = false
  const citation = {
    evidence_id: 'evidence-a', title: 'Official city permit', url: 'https://city.example/permit',
    publisher: 'City', excerpt: 'Construction at the north campus.',
  }
  const ready = {
    status: 'ready', stale: false, generated_at: '2026-10-01T12:00:00Z',
    result: {
      event_summary: [{ text: 'A city permit describes construction work.', evidence_id: 'evidence-a' }],
      commercial_hypothesis: { text: 'Investigation hypothesis: the activity merits verification.', evidence_id: 'evidence-a' },
      unknowns: ['Activity-specific power remains unknown.'],
      next_step: 'Ask when site electrical work is expected to begin.',
    },
    citations: [citation], error: null, input_tokens: 300, output_tokens: 90,
  }
  await page.route('**/api/auth/session', (route) => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities**', (route) => route.fulfill({ json: [{
    id, project_id: '22222222-2222-4222-8222-222222222222', name: 'North Campus', location: 'Austin, TX',
    tier: 'Signal', activity: 'construction', rationale: 'Public construction evidence merits investigation.',
    signal_display_decision: 'SHOW', signal_display_decision_state: 'adjudicated',
    signal_evidence_state: 'active_evidence', required_mw: null, start_window: null, duration: null,
    supply: 'Unknown', next_action: 'Confirm the activity power requirement.', conflict_state: 'Not assessed',
    evidence: [{ title: 'North Campus permit', abstract: 'Construction at the north campus.', url: citation.url,
      published_at: null, retrieved_at: '2026-10-01T10:00:00Z', extraction_location: 'permit description',
      content_hash: 'a'.repeat(64), event_date: null, event_date_label: 'Unknown', source_id: 'austin-building-permits',
      document_number: 'permit-1', source_origin: 'Official permit', assessment_current: true, permit_status: null }],
  }] }))
  await page.route('**/api/changes', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/health', (route) => route.fulfill({ json: { sources: [], backlog: 0, pending_interpretations: 0 } }))
  await page.route('**/api/projects/*/buying-chain', (route) => route.fulfill({ json: { candidates: [], permit_summaries: [], unresolved: [], runs: [], status: 'not_researched', policy_version: 'test' } }))
  await page.route(`**/api/power-needs/${id}/brief`, async (route) => {
    if (route.request().method() === 'POST') {
      posted = true
      return route.fulfill({ json: { ...ready, status: 'pending', result: null, citations: [], job_id: '33333333-3333-4333-8333-333333333333' } })
    }
    getCount += 1
    return route.fulfill({ json: posted && getCount > 1 ? ready : { status: 'unavailable', stale: false, result: null, citations: [] } })
  })

  await page.goto('/?tier=Signals')
  await expect(page.getByRole('heading', { name: 'Signals', exact: true })).toBeVisible()
  await page.locator(`[data-opportunity-id="${id}"]`).click()
  await expect(page.getByRole('heading', { name: 'Concise evidence brief' })).toBeVisible()
  await expect(page.getByText('Not generated')).toBeVisible()
  await page.getByRole('button', { name: 'Generate or retry brief' }).click()
  await expect(page.getByText('A city permit describes construction work.')).toBeVisible()
  const citationLinks = page.getByRole('link', { name: '[Official city permit]' })
  await expect(citationLinks).toHaveCount(2)
  await expect(citationLinks.nth(0)).toHaveAttribute('href', citation.url)
  await expect(citationLinks.nth(1)).toHaveAttribute('href', citation.url)
  expect(getCount).toBeLessThanOrEqual(3)
})
