import { expect, test } from '@playwright/test'

const need = {
  id: 'need-a', project_id: 'project-a', name: 'Austin data center', location: 'Austin, TX', tier: 'Signal',
  workflow_status: 'UNKNOWN', activity: 'construction', rationale: 'A retained construction filing supports investigation.',
  signal_display_decision: 'SHOW', signal_display_decision_state: 'adjudicated', signal_evidence_state: 'active_evidence',
  required_mw: null, supply: 'Unknown', start_window: null, duration: null, conflict_state: 'clear',
  project_identity_key: 'project-a', group_id: 'project-a', commercial_disposition: 'RESEARCH',
  commercial_reason: 'A retained construction filing supports investigation.', commercial_next_question: 'Who owns the electrical scope?',
  commercial_next_action: 'Confirm the package owner.', evidence: [{ id: 'evidence-a', title: 'Construction filing', url: 'https://example.test/filing',
    published_at: '2026-10-01', retrieved_at: '2026-10-02T00:00:00Z', extraction_location: 'Description', content_hash: 'a'.repeat(64),
    event_date: null, event_date_label: 'Unknown', source_id: 'city-permits', document_number: 'permit-1', source_origin: 'City', abstract: 'A construction filing.', assessment_current: true }],
} as const

const workspaceResponse = (items: readonly unknown[] = [need]) => ({ items, total: items.length, counts: { action_now: 0, research: items.length, watch: 0, reject: 0 }, offset: 0, limit: 25, next_offset: null, cohort_token: 'workspace-token', count_unit: 'power needs', changes_available: false })

async function authenticated(page: import('@playwright/test').Page) {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
}

function opportunityHeaders(token: string, offset: number, nextOffset: number | null) {
  return {
    'X-Total-Count': '1', 'X-Group-Total-Count': '1', 'X-Page-Record-Count': '1', 'X-Page-Group-Count': '1',
    'X-Limit': '25', 'X-Offset': String(offset), 'X-Cohort-Token': token,
    'X-Decision-Counts': JSON.stringify({ SHOW: 1, REVIEW: 0, HOLD: 0 }),
    ...(nextOffset == null ? {} : { 'X-Next-Offset': String(nextOffset) }),
  }
}

test('legacy environment links preserve supported tab, lens, tier, and grouped browse offset', async ({ page }) => {
  await authenticated(page)
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: workspaceResponse() }))
  let detailReads = 0
  await page.route('**/api/opportunities/needs/need-a*', route => { detailReads += 1; return route.fulfill({ json: need }) })
  const browseRequests: URL[] = []
  await page.route('**/api/opportunities?*', route => {
    const url = new URL(route.request().url())
    browseRequests.push(url)
    const offset = Number(url.searchParams.get('offset') ?? 0)
    return route.fulfill({ status: 200, contentType: 'application/json', headers: opportunityHeaders('legacy-page', offset, null), body: JSON.stringify([need]) })
  })

  await page.goto('/environment?view=environment&mode=evidence&need=need-a&lens=data_center&groupBrowse=1')
  await expect.poll(() => {
    const params = new URL(page.url()).searchParams
    return [params.get('view'), params.get('industry'), params.get('section'), params.get('need')]
  }).toEqual(['workspace', 'data_center', 'evidence', 'need-a'])
  await expect.poll(() => detailReads).toBeGreaterThan(0)
  await expect(page.locator('.wh-detail').getByRole('button', { name: 'Evidence', exact: true })).toHaveClass(/active/)
  await expect(page.locator('.wh-evidence-table').getByRole('link', { name: 'Construction filing' })).toBeVisible()
  await page.goto('/environment?view=environment&mode=browse&level=Leads&lens=data_center&records=50')
  await expect(page.getByRole('heading', { name: 'Leads' })).toBeVisible()
  await expect.poll(() => new URL(page.url()).searchParams.get('offset')).toBe('50')
  await expect.poll(() => new URL(page.url()).searchParams.get('industry')).toBe('data_center')
  const browseQueries = browseRequests.map(url => Object.fromEntries(url.searchParams.entries()))
  await expect.poll(() => browseRequests.some(url => url.searchParams.get('offset') === '50' && url.searchParams.get('tier') === 'Lead' && url.searchParams.get('industry') === 'data_center'), { message: JSON.stringify(browseQueries) }).toBe(true)
})

test('secondary technical diagnostics keeps the filtered inbox URL and readback aligned', async ({ page }) => {
  await authenticated(page)
  await page.route('**/api/health', route => route.fulfill({ json: { sources: [{ id: 'city-permits' }], backlog: 0, pending_interpretations: 0 } }))
  const requests: URL[] = []
  await page.route('**/api/ingestion?*', route => {
    requests.push(new URL(route.request().url()))
    return route.fulfill({ json: { items: [], total: 30, limit: 25, offset: Number(new URL(route.request().url()).searchParams.get('offset')) } })
  })
  await page.goto('/?view=ingestion&source=city-permits&vertical=data-centers&offset=25')
  await expect(page.getByLabel('Filter by source', { exact: true })).toHaveValue('city-permits')
  await expect(page.getByLabel('Filter by source sector', { exact: true })).toHaveValue('data-centers')
  const before = new URL(page.url()).search
  await page.locator('.wh-account summary').click()
  await page.getByRole('button', { name: 'Technical diagnostics' }).click()
  expect(new URL(page.url()).search).toBe(before)
  await page.reload()
  await expect(page.getByLabel('Filter by source', { exact: true })).toHaveValue('city-permits')
  await expect(page.getByLabel('Filter by source sector', { exact: true })).toHaveValue('data-centers')
  await expect.poll(() => requests.at(-1)?.searchParams.get('offset')).toBe('25')
})

test('default landing hides the legacy queue and briefing controls', async ({ page }) => {
  await authenticated(page)
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: { items: [], total: 0, count_unit: 'operators and customers', limit: 25, offset: 0, cohort_token: 'empty', generation: 'synthetic' } }))
  await page.goto('/?groupBrowse=1')
  await expect(page.locator('.wh-queue-meta')).toHaveCount(0)
  await expect(page.locator('.wh-briefing-scope')).toHaveCount(0)
  await expect(page.getByText('No operator/customer groups match this search.')).toBeVisible()
})
