import { expect, test } from '@playwright/test'

const need = {
  id: 'need-a', project_id: 'project-a', name: 'Test data center', location: 'Austin, TX', tier: 'Signal', workflow_status: 'New', activity: 'construction',
  rationale: 'A retained project filing supports investigation.', signal_evidence_state: 'active', conflict_state: 'Not assessed', required_mw: null, supply: 'Unknown', start_window: null, duration: null,
  evidence: [{ source_id: 'city-permit', document_number: 'P-1', title: 'Permit filing', url: 'https://example.test/permit', published_at: null, retrieved_at: '2026-10-18T10:00:00Z', event_date: null, event_date_label: 'Event date', source_origin: 'City permits', extraction_location: 'Page 1', abstract: 'Construction filing.' }],
  missing_facts: ['Activity-specific load', 'Suitable utility supply'], project_identity_key: 'test', commercial_disposition: 'RESEARCH', commercial_reason: 'Load and supply remain unknown.', commercial_next_question: 'Who owns the electrical scope?', commercial_next_action: 'Research the project contractor.', commercial_organization: null,
} as any
const response = (items = [need]) => ({ items, total: items.length, counts: { action_now: 0, research: items.length, watch: 0, reject: 0 }, offset: 0, limit: 25, next_offset: null, cohort_token: 'cohort-a', count_unit: 'power needs', changes_available: false })
const emptyChanges = { items: [], counts: { discovered: 0, changed: 0, promoted: 0, closed: 0, review_exception: 0 }, total_unreviewed: 0, offset: 0, limit: 50, next_offset: null, evaluated_at: '2026-10-20T12:00:00Z', baseline_identity: '00000000-0000-4000-8000-000000000001', baseline_reviewed_at: null, first_use: true, token: 'a'.repeat(64), source_health_exceptions: [] }

test.beforeEach(async ({ page }) => {
  await page.route('**/api/opportunities/workspace/changes*', route => route.fulfill({ json: emptyChanges }))
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: { items: [], total: 0, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'empty-projects', generation: 1 } }))
})



test('default workspace shows project results and opens existing need detail without the legacy list API', async ({ page }) => {
  const workspaceRequests: URL[] = []
  const project = { id: 'project-a', project_id: 'project-a', name: 'Test data center', company: 'Example operator', location: 'Austin, TX', sector: 'data_centers', asset_type: 'data_center', priority_score: null, representative_need_id: 'need-a', needs: [{ id: 'need-a', project_id: 'project-a', activity: 'construction', browse_title: 'Test data center', location: 'Austin, TX' }], need_count: 1, event: { kind: 'permit_issued', label: 'Permit issued', date: '2026-10-18', source: 'Synthetic fixture', evidence_refs: [] }, contact: [], power_summary: 'Power need remains unconfirmed.', next_action: 'Review the source-backed project evidence.', updated_at: '2026-10-20T00:00:00Z' }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: { items: [{ id: 'group-project-a', name: 'Example operator', role: 'operator', project_count: 1, need_count: 1, sectors: ['data_centers'] }], total: 1, count_unit: 'operators and customers', limit: 25, offset: 0, cohort_token: 'group-cohort', generation: 1 } }))
  await page.route('**/api/opportunities/groups/group-project-a/projects?*', route => route.fulfill({ json: { items: [project], total: 1, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'project-cohort', generation: 1 } }))
  await page.route('**/api/opportunities/projects?need_id=*', route => route.fulfill({ json: { items: [project], total: 1, count_unit: 'projects', limit: 1, offset: 0, cohort_token: 'exact-project-cohort', generation: 1 } }))
  await page.route('**/api/opportunities/workspace?*', route => { workspaceRequests.push(new URL(route.request().url())); return route.fulfill({ json: response() }) })
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: need }))
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Search opportunities' })).toBeVisible()
  await expect(page.getByText('1 operator/customer group')).toBeVisible()
  await page.getByRole('button', { name: /Example operator/ }).click()
  await expect(page.getByText('Permit issued · 2026-10-18')).toBeVisible()
  await page.getByRole('button', { name: 'View project details' }).click()
  await expect(page).toHaveURL(/need=need-a/)
  await expect(page.locator('.wh-detail h2')).toHaveText('Test data center')
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  await expect(page.getByRole('link', { name: 'Permit filing' })).toBeVisible()
  await page.getByRole('button', { name: /Back to power needs/ }).click()
  await expect(page.locator('.project-card')).toBeVisible()
  expect(workspaceRequests).toEqual([])
})

test('browser Back re-reads the same selected need after identity is cleared', async ({ page }) => {
  let detailReads = 0
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response() }))
  await page.route('**/api/opportunities/workspace/changes?*', route => {
    const offset = Number(new URL(route.request().url()).searchParams.get('offset') ?? 0)
    const items = Array.from({ length: 50 }, (_, index) => ({
      event_key: `change:${offset + index + 1}`, category: 'changed', title: `Change ${offset + index + 1}`,
      detail: 'Synthetic retained change', created_at: '2026-10-20T12:00:00Z', source_date: null,
      project_id: null, before_state: null, after_state: null, needs: [], sources: [],
    }))
    return route.fulfill({ json: { ...emptyChanges, items, total_unreviewed: 100, offset, next_offset: offset === 0 ? 50 : null } })
  })
  await page.route('**/api/opportunities/needs/need-a*', route => {
    detailReads += 1
    return route.fulfill({ json: need })
  })
  await page.goto('/?view=workspace&accountBrowse=1')
  const panel = page.locator('.wh-changes')
  await page.locator('.wh-tools > summary').click()
  await page.locator('.wh-change-disclosure > summary').click()
  await panel.locator(':scope > details > summary').click()
  await panel.getByRole('button', { name: 'Next changes' }).click()
  await expect(panel.getByRole('heading', { name: 'Change 51', exact: true })).toBeVisible()
  await expect(panel.getByText('Showing 51–100 of 100 changes')).toBeVisible()
  await page.locator('[data-need-row="need-a"]').click()
  await expect(page.getByRole('heading', { name: 'Test data center' })).toBeVisible()
  await page.locator('[data-need-row="need-a"]').click()
  await expect.poll(() => new URL(page.url()).searchParams.get('need')).toBe('need-a')
  const readsBeforeBack = detailReads
  await page.goBack()
  await expect.poll(() => detailReads).toBeGreaterThan(readsBeforeBack)
  await expect(page.getByRole('heading', { name: 'Test data center' })).toBeVisible()
  await expect(page.getByText('Loading current need detail.')).toHaveCount(0)
  await expect(panel.getByRole('heading', { name: 'Change 51', exact: true })).toBeVisible()
  await expect(panel.getByText('Showing 51–100 of 100 changes')).toBeVisible()
})

test('table uses its source-backed browse title and settled detail recomputes from current evidence', async ({ page }) => {
  const row = { ...need, name: 'Austin permit 2026-127192 EP', browse_title: 'JLC Electrical Contractor corp · contractor' }
  const detail = {
    ...row,
    browse_title: undefined,
    title_company: undefined,
    title_company_role: undefined,
    evidence: [{ ...need.evidence[0], assessment_current: true, abstract: 'contractor_company_name: Current project electrician' }],
  }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response([row]) }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: detail }))
  await page.goto('/?view=workspace&accountBrowse=1')
  const rowButton = page.locator('[data-need-row="need-a"]')
  await expect(rowButton.locator('strong')).toHaveText('JLC Electrical Contractor corp · contractor')
  await rowButton.click()
  await expect(page.getByRole('heading', { name: 'Current project electrician · contractor' })).toBeVisible()
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  await page.locator('.wh-source-context summary').click()
  await expect(page.locator('.wh-source-context')).toContainText('Source record: Austin permit 2026-127192 EP')
  await expect(page.locator('.wh-source-context')).not.toContainText('JLC Electrical Contractor corp · contractor')
})

test('Signal ACTION NOW reads as a discovery call while Prospect and Lead dispositions stay unchanged', async ({ page }) => {
  const rows = [
    { ...need, id: 'signal-action-now', name: 'Signal discovery project', tier: 'Signal', commercial_disposition: 'ACTION NOW' },
    { ...need, id: 'prospect-action-now', name: 'Prospect action project', tier: 'Prospect', commercial_disposition: 'ACTION NOW' },
    { ...need, id: 'lead-action-now', name: 'Lead action project', tier: 'Lead', commercial_disposition: 'ACTION NOW' },
    { ...need, id: 'signal-research', name: 'Signal research project', tier: 'Signal', commercial_disposition: 'RESEARCH' },
  ]
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: {
    ...response(rows), counts: { action_now: 3, research: 1, watch: 0, reject: 0 },
  } }))
  await page.goto('/?view=workspace&accountBrowse=1')

  const rowFor = (id: string) => page.locator('tr').filter({ has: page.locator(`[data-need-row="${id}"]`) })
  await expect(rowFor('signal-action-now').locator('.opportunity-status')).toHaveText('Discovery call · Power need unconfirmed')
  await expect(rowFor('signal-action-now').locator('.wh-queue-meta > span').nth(1)).toHaveText('Signal')
  await expect(rowFor('prospect-action-now').locator('.opportunity-status')).toHaveText('ACTION NOW')
  await expect(rowFor('lead-action-now').locator('.opportunity-status')).toHaveText('ACTION NOW')
  await expect(rowFor('signal-research').locator('.opportunity-status')).toHaveText('RESEARCH')

  await page.setViewportSize({ width: 390, height: 844 })
  await expect(rowFor('signal-action-now')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
})

test('off-page detail reload ignores historical company evidence and keeps the source name visible', async ({ page }) => {
  const detail = {
    ...need,
    name: 'Austin permit 2026-127192 EP',
    browse_title: undefined,
    title_company: undefined,
    title_company_role: undefined,
    activity: 'temporary-power',
    supported_action: 'New',
    evidence: [{ ...need.evidence[0], source_id: 'austin-building-permits', assessment_current: false, abstract: 'owner_company_name: Historical Owner LLC' }],
  }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response([]) }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: detail }))
  await page.goto('/?view=workspace&accountBrowse=1&need=need-a')
  await expect(page.getByRole('heading', { name: 'Temporary power · Austin, TX' })).toBeVisible()
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  await page.locator('.wh-source-context summary').click()
  await expect(page.locator('.wh-source-context')).toContainText('Source record: Austin permit 2026-127192 EP')
  await expect(page.locator('.wh-source-context')).not.toContainText('Historical Owner LLC')
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Temporary power · Austin, TX' })).toBeVisible()
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  await page.locator('.wh-source-context summary').click()
  await expect(page.locator('.wh-source-context')).toContainText('Source record: Austin permit 2026-127192 EP')
})

test('workspace gives an honest retry state when the current cohort is unavailable', async ({ page }) => {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/groups?*', route => route.fulfill({ status: 503, json: { detail: 'stale cohort' } }))
  await page.goto('/?groupBrowse=1')
  await expect(page.getByRole('alert')).toContainText('Could not load operator/customer groups')
  await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible()
})

test('workspace selection switches to a full detail view on mobile and has a clear return', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response() }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: need }))
  await page.goto('/?view=workspace&accountBrowse=1')
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await page.getByRole('button', { name: /Test data center/ }).click()
  await expect(page.getByRole('button', { name: /Back to power needs/ })).toBeVisible()
  await page.getByRole('button', { name: /Back to power needs/ }).click()
  await expect(page.getByRole('heading', { name: 'Opportunities', exact: true })).toBeVisible()
})



test('mobile history Back keeps the selected shell through delayed readback and focuses Back', async ({ page }) => {
  const needA = { ...need, id: 'need-a', project_id: 'project-a', name: 'ACS project' }
  const needB = { ...need, id: 'need-b', project_id: 'project-b', name: 'JLC project' }
  let bReads = 0
  let releaseSecondB!: () => void
  let signalSecondB!: () => void
  const secondBStarted = new Promise<void>(resolve => { signalSecondB = resolve })
  const secondBResponse = new Promise<void>(resolve => { releaseSecondB = resolve })
  await page.setViewportSize({ width: 1280, height: 844 })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response([needA, needB]) }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: needA }))
  await page.route('**/api/opportunities/needs/need-b*', async route => {
    bReads += 1
    if (bReads === 2) { signalSecondB(); await secondBResponse }
    await route.fulfill({ json: needB })
  })
  await page.goto('/?view=workspace&accountBrowse=1')
  await page.locator('[data-need-row="need-b"]').click()
  await expect(page.getByRole('heading', { name: 'JLC project' })).toBeVisible()
  await page.locator('[data-need-row="need-a"]').click()
  await expect(page.getByRole('heading', { name: 'ACS project' })).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: /Back to power needs/ }).click()
  await secondBStarted
  await expect(page).toHaveURL(/need=need-b/)
  await expect(page.locator('.wh-detail-loading')).toBeVisible()
  await expect(page.locator('.wh-list')).toBeHidden()
  const pendingBack = page.getByRole('button', { name: /Back to power needs/ })
  await expect(pendingBack).toBeVisible()
  await expect(pendingBack).toBeEnabled()
  releaseSecondB()
  await expect(page.getByRole('heading', { name: 'JLC project' })).toBeVisible()
  await expect(page.getByRole('button', { name: /Back to power needs/ })).toBeFocused()
})

test('desktop history readback does not steal Search focus after resizing to phone', async ({ page }) => {
  const needA = { ...need, id: 'need-a', name: 'ACS project' }
  const needB = { ...need, id: 'need-b', project_id: 'project-b', name: 'JLC project' }
  await page.setViewportSize({ width: 1280, height: 844 })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response([needA, needB]) }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: needA }))
  await page.route('**/api/opportunities/needs/need-b*', route => route.fulfill({ json: needB }))
  await page.goto('/?view=workspace&accountBrowse=1')
  await page.locator('[data-need-row="need-b"]').click()
  await expect(page.getByRole('heading', { name: 'JLC project' })).toBeVisible()
  await page.locator('[data-need-row="need-a"]').click()
  await expect(page.getByRole('heading', { name: 'ACS project' })).toBeVisible()
  await page.goBack()
  await expect(page.getByRole('heading', { name: 'JLC project' })).toBeVisible()
  const more = page.locator('.wh-account summary')
  await more.focus()
  await expect(more).toBeFocused()
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(more).toBeFocused()
  await expect(page.locator('.wh-list')).toBeHidden()
})

test('mobile Back can leave a held history readback and late response cannot restore it', async ({ page }) => {
  const needA = { ...need, id: 'need-a', project_id: 'project-a', name: 'ACS project' }
  const needB = { ...need, id: 'need-b', project_id: 'project-b', name: 'JLC project' }
  let bReads = 0
  let releaseSecondB!: () => void
  let signalSecondB!: () => void
  let finishSecondB!: () => void
  const secondBStarted = new Promise<void>(resolve => { signalSecondB = resolve })
  const secondBResponse = new Promise<void>(resolve => { releaseSecondB = resolve })
  const secondBFinished = new Promise<void>(resolve => { finishSecondB = resolve })
  await page.setViewportSize({ width: 1280, height: 844 })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response([needA, needB]) }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: needA }))
  await page.route('**/api/opportunities/needs/need-b*', async route => {
    bReads += 1
    if (bReads === 2) {
      signalSecondB()
      await secondBResponse
      try { await route.fulfill({ json: needB }) } catch { /* The selected-detail request is expected to be aborted by Back. */ }
      finishSecondB()
      return
    }
    await route.fulfill({ json: needB })
  })
  await page.goto('/?view=workspace&accountBrowse=1')
  await page.locator('[data-need-row="need-b"]').click()
  await expect(page.getByRole('heading', { name: 'JLC project' })).toBeVisible()
  await page.locator('[data-need-row="need-a"]').click()
  await expect(page.getByRole('heading', { name: 'ACS project' })).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: /Back to power needs/ }).click()
  await secondBStarted
  const pendingBack = page.getByRole('button', { name: /Back to power needs/ })
  await expect(pendingBack).toBeVisible()
  await expect(pendingBack).toBeEnabled()
  await pendingBack.click()
  await expect(page).toHaveURL(/view=workspace/)
  await expect(page).not.toHaveURL(/need=need-b/)
  await expect(page.locator('.wh-list')).toBeVisible()
  releaseSecondB()
  await secondBFinished
  await expect(page).not.toHaveURL(/need=need-b/)
  await expect(page.getByRole('heading', { name: 'JLC project' })).toHaveCount(0)
  await expect(page.locator('.wh-list')).toBeVisible()
})

test('mobile failed history readback keeps Retry and Back available', async ({ page }) => {
  const needA = { ...need, id: 'need-a', project_id: 'project-a', name: 'ACS project' }
  const needB = { ...need, id: 'need-b', project_id: 'project-b', name: 'JLC project' }
  let bReads = 0
  await page.setViewportSize({ width: 1280, height: 844 })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response([needA, needB]) }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: needA }))
  await page.route('**/api/opportunities/needs/need-b*', route => {
    bReads += 1
    return bReads === 2
      ? route.fulfill({ status: 503, json: { detail: 'selected detail temporarily unavailable' } })
      : route.fulfill({ json: needB })
  })
  await page.goto('/?view=workspace&accountBrowse=1')
  await page.locator('[data-need-row="need-b"]').click()
  await expect(page.getByRole('heading', { name: 'JLC project' })).toBeVisible()
  await page.locator('[data-need-row="need-a"]').click()
  await expect(page.getByRole('heading', { name: 'ACS project' })).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: /Back to power needs/ }).click()
  await expect(page.getByRole('alert')).toContainText('could not complete this request (503)')
  await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible()
  const errorBack = page.getByRole('button', { name: /Back to power needs/ })
  await expect(errorBack).toBeVisible()
  await expect(errorBack).toBeEnabled()
  await errorBack.click()
  await expect(page).not.toHaveURL(/need=need-b/)
  await expect(page.locator('.wh-list')).toBeVisible()
})

test('mobile selected detail keeps the compact header and clear return', async ({ page }) => {
  const realistic = {
    ...need,
    name: 'North Austin Advanced Manufacturing and Logistics Campus Phase Two',
    location: 'North Austin, Texas · approximate site location',
    required_mw: 'Unknown',
    commercial_next_action: 'Confirm the electrical package owner and expected utility service date.',
    commercial_reason: 'A retained source supports construction activity, but does not establish the facility-specific load or available supply.',
    missing_facts: ['Activity-specific load', 'Utility service timing', 'Suitable supply availability'],
  }
  await page.setViewportSize({ width: 390, height: 844 })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response([realistic]) }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: realistic }))
  await page.goto('/?view=workspace&accountBrowse=1')
  await page.locator('[data-need-row="need-a"]').click()
  const action = page.locator('.wh-record-actions')
  await expect(action).toBeInViewport()
  await expect(action.getByRole('button', { name: 'Research' })).toHaveCount(1)
  await expect(page.locator('.wh-title-row')).toBeHidden()
  await expect(page.locator('.wh-briefing')).toHaveCount(0)
  await expect(page.locator('.canonical-header .global-search label > span')).toBeHidden()
  expect(await page.locator('.canonical-header__brand').evaluate(node => getComputedStyle(node).width)).toBe('143px')
  await expect(page.getByRole('button', { name: /Back to power needs/ })).toBeVisible()
})





test('switching selected needs does not invoke title enrichment', async ({ page }) => {
  const second = { ...need, id: 'need-b', project_id: 'project-b', name: 'Second project' }
  const titleRequests: string[] = []
  page.on('request', request => { if (request.url().includes('/title')) titleRequests.push(request.url()) })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response([need, second]) }))
  await page.route('**/api/opportunities/needs/*', route => route.fulfill({ json: route.request().url().includes('need-b') ? second : need }))
  await page.goto('/?view=workspace&accountBrowse=1')
  await page.locator('[data-need-row="need-a"]').click()
  await page.locator('[data-need-row="need-b"]').click()
  await expect(page.getByRole('heading', { name: 'Second project' })).toBeVisible()
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  await expect(page.getByRole('button', { name: /enrich title/i })).toHaveCount(0)
  expect(titleRequests).toEqual([])
})

test('selected opportunity uses its returned project title without enrichment requests', async ({ page }) => {
  const first = { ...need, id: 'need-a', name: 'Permit filing A', browse_title: 'Cedar Ridge campus', commercial_organization: null }
  const second = { ...need, id: 'need-b', project_id: 'project-b', name: 'Permit filing B', browse_title: 'West Texas buildout', commercial_organization: null }
  const titleRequests: string[] = []
  page.on('request', request => { if (request.url().includes('/title')) titleRequests.push(request.url()) })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response([first, second]) }))
  await page.route('**/api/opportunities/needs/*', route => route.fulfill({ json: route.request().url().includes('need-b') ? second : first }))
  await page.goto('/?view=workspace&accountBrowse=1')
  await page.locator('[data-need-row="need-a"]').click()
  await expect(page.getByRole('heading', { name: 'Cedar Ridge campus' })).toBeVisible()
  await page.locator('[data-need-row="need-b"]').click()
  await expect(page.getByRole('heading', { name: 'West Texas buildout' })).toBeVisible()
  expect(titleRequests).toEqual([])
})

test('Signal tier deep links stay on workspace and a changed cohort resets pagination', async ({ page }) => {
  let pages = 0
  const requested: URL[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', async route => {
    const url = new URL(route.request().url()); requested.push(url); pages += 1
    if (pages === 1) return route.fulfill({ status: 409, json: { detail: 'cohort changed' } })
    return route.fulfill({ json: response() })
  })
  await page.goto('/?view=workspace&accountBrowse=1&tier=Signal&offset=25&cohort_token=old')
  await expect(page.getByRole('heading', { name: 'Opportunities', exact: true })).toBeVisible()
  await expect.poll(() => requested.length).toBeGreaterThan(1)
  expect(requested[0].searchParams.get('tier')).toBe('Signal')
  expect(requested[0].searchParams.get('cohort_token')).toBe('old')
  expect(requested.some(url => url.searchParams.get('offset') === '0' && !url.searchParams.has('cohort_token'))).toBe(true)
})

test('stale list responses cannot replace a newer filter result', async ({ page }) => {
  let resolveOld!: () => void
  const oldResponse = new Promise<void>(resolve => { resolveOld = resolve })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', async route => {
    const geo = new URL(route.request().url()).searchParams.get('geography')
    if (geo === 'Old') { await oldResponse; return route.fulfill({ json: response([{ ...need, id: 'old', name: 'Stale result' }]) }) }
    if (geo === 'New') return route.fulfill({ json: response([{ ...need, id: 'new', name: 'Current result' }]) })
    return route.fulfill({ json: response() })
  })
  await page.goto('/?view=workspace&accountBrowse=1')
  await page.locator('.wh-tools > summary').click()
  await page.locator('.wh-filter-disclosure summary').click()
  await page.getByLabel('Geography (exact match)').fill('Old')
  await page.getByLabel('Geography (exact match)').fill('New')
  await expect(page.getByRole('button', { name: /Current result/ })).toBeVisible()
  resolveOld()
  await expect(page.getByRole('button', { name: /Stale result/ })).toHaveCount(0)
})

test('a failed workspace filter hides rows, counts, and pagination from the prior cohort', async ({ page }) => {
  const oldCohortAction = 'Austin cohort only action'
  const selectedRow = { ...need, name: 'Austin retained row', commercial_next_action: oldCohortAction }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => {
    const geography = new URL(route.request().url()).searchParams.get('geography')
    if (geography === 'Houston') return route.fulfill({ status: 503, json: { detail: 'workspace unavailable' } })
    return route.fulfill({ json: response([selectedRow]) })
  })
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: { ...need, name: 'Fresh canonical detail' } }))
  await page.goto('/?view=workspace&accountBrowse=1&geography=Austin')
  await expect(page.getByRole('button', { name: /Austin retained row/ })).toBeVisible()
  await page.locator('[data-need-row="need-a"]').click()
  await expect(page.getByRole('heading', { name: 'Fresh canonical detail' })).toBeVisible()
  await expect(page.getByText(oldCohortAction)).toBeVisible()
  await page.locator('.wh-tools > summary').click()
  await page.locator('.wh-filter-disclosure summary').click()
  await page.getByLabel('Geography (exact match)').fill('Houston')
  await expect(page.locator('.wh-error[role="alert"]')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Fresh canonical detail' })).toBeVisible()
  await expect(page.getByText(oldCohortAction)).toHaveCount(0)
  await expect(page.getByRole('button', { name: /Austin retained row/ })).toHaveCount(0)
  await expect(page.locator('.wh-queue-heading')).toContainText('Opportunity results unavailable')
  await expect(page.locator('.wh-paging')).toContainText('Results unavailable')
})

test('canonical priority score and reasons are explained separately from disposition', async ({ page }) => {
  const ranked = { ...need, rank_score: 8, rank_reasons: ['Near-term start', 'Supported project scale'], rank_version: 'rank-v1' }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response([ranked]) }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: ranked }))
  await page.goto('/?view=workspace&accountBrowse=1')
  await page.locator('[data-need-row="need-a"]').click()
  await page.getByRole('button', { name: 'Overview' }).click()
  const priority = page.getByRole('region', { name: 'Priority explanation' })
  await expect(priority).toContainText('Canonical rank score: 8 · rank-v1')
  await expect(priority).toContainText('Near-term start')
  await expect(priority).toContainText('separate from qualification and commercial disposition')
})









test('active change links use canonical workspace readback instead of historical stored tier', async ({ page }) => {
  await page.unrouteAll()
  const activeChange = {
    ...emptyChanges,
    items: [{
      event_key: 'fact:33333333-3333-4333-8333-333333333333', category: 'changed',
      title: 'Call fact accepted: demand', detail: 'Synthetic fixture',
      created_at: '2026-10-20T11:00:00Z', source_date: null, project_id: 'project-a',
      before_state: null, after_state: { fact_type: 'demand', value: { mw: '12' } },
      needs: [{ id: 'need-a', name: 'Synthetic Facility', location: 'Austin, TX', active: true, tier: 'Lead' }],
      sources: [], fact_version_id: '44444444-4444-4444-8444-444444444444', fact_type: 'demand',
      decision: 'accepted', reason: 'Confirmed', actor: 'Operator', confirmed_at: '2026-10-20T10:00:00Z', source_reference: null,
    }],
    total_unreviewed: 1, counts: { ...emptyChanges.counts, changed: 1 },
  }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response([]) }))
  await page.route('**/api/opportunities/workspace/changes*', route => route.fulfill({ json: activeChange }))
  await page.route('**/api/opportunities/needs/need-a?*', route => route.fulfill({ json: { ...need, tier: 'Signal' } }))
  let historicalReads = 0
  await page.route('**/api/opportunities/needs/need-a/history', route => { historicalReads += 1; return route.fulfill({ json: { ...need, active: true, tier: 'Lead' } }) })
  await page.goto('/?view=workspace&accountBrowse=1')
  const panel = page.locator('.wh-changes')
  await page.locator('.wh-tools > summary').click()
  await page.locator('.wh-change-disclosure > summary').click()
  await panel.locator(':scope > details > summary').click()
  const link = panel.getByRole('button', { name: /Synthetic Facility · Austin, TX · demand/ })
  await link.click()
  await expect(page.getByRole('heading', { name: 'Test data center' })).toBeVisible()
  await expect(page.locator('.wh-tier-badge')).toContainText('Signal')
  expect(historicalReads).toBe(0)
})

test('active change link hides a previously stored Lead while canonical readback is pending or fails', async ({ page }) => {
  await page.unrouteAll()
  const activeChange = {
    ...emptyChanges,
    items: [{
      event_key: 'fact:55555555-5555-4555-8555-555555555555', category: 'changed',
      title: 'Call fact accepted: demand', detail: 'Synthetic fixture',
      created_at: '2026-10-20T11:00:00Z', source_date: null, project_id: 'project-a',
      before_state: null, after_state: { fact_type: 'demand', value: { mw: '12' } },
      needs: [{ id: 'need-a', name: 'Synthetic Facility', location: 'Austin, TX', active: true, tier: 'Lead' }],
      sources: [], fact_version_id: '66666666-6666-4666-8666-666666666666', fact_type: 'demand',
      decision: 'accepted', reason: 'Confirmed', actor: 'Operator', confirmed_at: '2026-10-20T10:00:00Z', source_reference: null,
    }],
    total_unreviewed: 1, counts: { ...emptyChanges.counts, changed: 1 },
  }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response([]) }))
  await page.route('**/api/opportunities/workspace/changes*', route => route.fulfill({ json: activeChange }))
  await page.route('**/api/opportunities/needs/need-a?*', route => route.fulfill({ status: 503, json: { detail: 'Fresh qualification unavailable' } }))
  let historicalReads = 0
  await page.route('**/api/opportunities/needs/need-a/history', route => { historicalReads += 1; return route.fulfill({ json: { ...need, active: true, tier: 'Lead' } }) })
  await page.goto('/?view=workspace&accountBrowse=1')
  const panel = page.locator('.wh-changes')
  await page.locator('.wh-tools > summary').click()
  await page.locator('.wh-change-disclosure > summary').click()
  await panel.locator(':scope > details > summary').click()
  await panel.getByRole('button', { name: /Synthetic Facility · Austin, TX · demand/ }).click()
  await expect(page.getByRole('alert')).toContainText('GridLens could not complete this request (503)')
  await expect(page.locator('.wh-detail')).not.toContainText('Lead')
  expect(historicalReads).toBe(0)
})

test('tablet workspace has no horizontal overflow and retains readable layout', async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 900 })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response() }))
  await page.goto('/?view=workspace&accountBrowse=1')
  await expect(page.getByRole('heading', { name: 'Opportunities', exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(900)
})

test('tablet direct selection keeps detail and header reachable and restores the queue', async ({ page }) => {
  await page.setViewportSize({ width: 768, height: 1024 })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response() }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: need }))
  await page.goto('/?view=workspace&accountBrowse=1&need=need-a')
  const identity = page.getByRole('heading', { name: 'Test data center' })
  await expect(identity).toBeVisible()
  const bounds = await identity.boundingBox()
  expect(bounds!.y).toBeGreaterThanOrEqual(0)
  expect(bounds!.y + bounds!.height).toBeLessThan(1024)
  for (const control of [page.locator('.canonical-header__brand'), page.getByRole('navigation', { name: 'Primary navigation' }), page.locator('.wh-account > summary')]) {
    const box = await control.boundingBox()
    expect(box).not.toBeNull()
    expect(box!.x).toBeGreaterThanOrEqual(0)
    expect(box!.x + box!.width).toBeLessThanOrEqual(768)
  }
  await page.getByRole('button', { name: 'Back to power needs' }).click()
  const row = page.locator('[data-need-row="need-a"]')
  await expect(row).toBeVisible()
  await row.click()
  await expect(identity).toBeVisible()
})

test('legacy flat project results remain available explicitly and keep routine research queues out of the workspace', async ({ page }) => {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: { items: [], total: 0, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'default-flat', generation: 'synthetic' } }))
  await page.goto('/?view=workspace&projectBrowse=1')
  await expect(page.getByRole('heading', { name: 'Opportunities', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Notifications' })).toHaveCount(0)
  await expect(page.locator('.wh-tools')).toHaveCount(0)
  await expect(page.locator('.brand-kpi')).toHaveCount(0)
  await expect(page.getByRole('navigation', { name: 'Primary navigation' }).getByRole('button')).toHaveText(['Opportunities', 'Intelligence', 'Developers', 'Power Supply', 'Reports'])
  for (const width of [768, 390]) {
    await page.setViewportSize({ width, height: 900 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
  }
})

test('industrial group filters canonical asset types, carries URL cohorts, and resets exact filters', async ({ page }) => {
  const assets = [
    ...Array.from({ length: 10 }, (_, index) => ({ ...need, id: `gas-${index}`, name: `Gas plant ${index}`, asset_type: 'gas_processing_plant', industry: 'gas_processing_plant' })),
    ...Array.from({ length: 10 }, (_, index) => ({ ...need, id: `compressor-${index}`, name: `Compressor ${index}`, asset_type: 'compressor_station', industry: 'compressor_station' })),
    ...Array.from({ length: 10 }, (_, index) => ({ ...need, id: `well-${index}`, name: `Upstream well ${index}`, asset_type: 'upstream_well', industry: 'upstream_well' })),
    { ...need, id: 'data-center', name: 'Data center', asset_type: 'data_center', industry: 'data_center' },
    { ...need, id: 'unknown-asset', name: 'Unclassified asset', asset_type: 'unknown', industry: 'unknown' },
  ]
  const requests: URL[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', async route => {
    const url = new URL(route.request().url())
    requests.push(url)
    const group = url.searchParams.get('industry_group')
    const exact = url.searchParams.get('industry')
    const selected = group === 'industrial'
      ? assets.filter(item => ['gas_processing_plant', 'compressor_station', 'upstream_well'].includes(item.asset_type))
      : exact ? assets.filter(item => item.asset_type === exact) : assets
    const offset = Number(url.searchParams.get('offset') ?? 0)
    const items = selected.slice(offset, offset + 25)
    const cohort = group === 'industrial' ? 'industrial-cohort' : exact ? 'exact-cohort' : 'all-cohort'
    await route.fulfill({ json: { ...response(items), total: selected.length, offset, next_offset: offset + items.length < selected.length ? offset + items.length : null, cohort_token: cohort } })
  })
  await page.goto('/?view=workspace&accountBrowse=1&industry=gas_processing_plant')
  await expect(page.getByLabel('Industry (exact match)')).toHaveValue('gas_processing_plant')
  await expect.poll(() => requests.at(-1)?.searchParams.get('industry')).toBe('gas_processing_plant')
  await page.locator('.wh-tools > summary').click()
  await page.locator('.wh-filter-disclosure summary').click()
  await page.getByLabel('Industry (exact match)').fill('compressor_station')
  await expect.poll(() => requests.at(-1)?.searchParams.get('industry')).toBe('compressor_station')
  await page.getByRole('button', { name: 'Industrial', exact: true }).click()
  await expect.poll(() => requests.at(-1)?.searchParams.get('industry_group')).toBe('industrial')
  await expect(page.getByLabel('Industry (exact match)')).toHaveValue('')
  await expect(page).toHaveURL(/industry_group=industrial/)
  await expect(page).not.toHaveURL(/industry=gas_processing_plant|industry=compressor_station/)
  await expect(page.locator('.wh-queue-heading')).toContainText('30 opportunities')
  await expect(page.locator('[data-need-row]')).toHaveCount(25)
  await expect(page.locator('[data-need-row="data-center"]')).toHaveCount(0)
  await expect(page.locator('[data-need-row="unknown-asset"]')).toHaveCount(0)
  await expect(page.locator('.wh-paging')).toContainText('of 30')
  await page.locator('.wh-paging').getByRole('button', { name: 'Next' }).click()
  await expect.poll(() => requests.at(-1)?.searchParams.get('offset')).toBe('25')
  await expect.poll(() => requests.at(-1)?.searchParams.get('cohort_token')).toBe('industrial-cohort')
  await page.getByRole('button', { name: 'Data centers', exact: true }).click()
  await expect.poll(() => requests.at(-1)?.searchParams.get('industry')).toBe('data_center')
  await expect.poll(() => requests.at(-1)?.searchParams.get('offset')).toBe('0')
  await expect(requests.at(-1)?.searchParams.has('industry_group')).toBe(false)
  await expect(requests.at(-1)?.searchParams.has('cohort_token')).toBe(false)
  await page.goBack()
  await expect(page).toHaveURL(/industry_group=industrial.*offset=25.*cohort_token=industrial-cohort/)
  await expect.poll(() => requests.at(-1)?.searchParams.get('industry_group')).toBe('industrial')
  await expect.poll(() => requests.at(-1)?.searchParams.get('offset')).toBe('25')
  await page.reload()
  await expect.poll(() => requests.at(-1)?.searchParams.get('cohort_token')).toBe('industrial-cohort')
})

test('Power gap shows only backend-qualified ranges and keeps null or conflicted gaps unknown', async ({ page }) => {
  const qualified = { ...need, id: 'need-qualified', name: 'Qualified power need', tier: 'Lead', required_mw: '4–6 MW', supply: '2–3 MW', qualified_remaining_gap: { required_mw_min: '4', required_mw_max: '6', available_mw_min: '2', available_mw_max: '3', remaining_mw_min: '1', remaining_mw_max: '4', start_window: 'Q2 2027', duration: '90–120 days', basis_quote: 'Service letter states 2–3 MW available.', value_kind: 'Derived', calculation: 'range intersection from supported demand and supply', version: 'qual-v1' }, qualification_version: 'qual-v1' }
  const unknown = { ...need, id: 'need-unknown', name: 'Unknown power need', qualified_remaining_gap: null, qualification_version: null }
  const conflict = { ...need, id: 'need-conflict', name: 'Conflicted power need', conflict_state: 'CONFLICT', qualified_remaining_gap: null, qualification_version: null }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response([qualified, unknown, conflict]) }))
  await page.route('**/api/opportunities/needs/*', route => {
    const id = new URL(route.request().url()).pathname.split('/').pop()
    return route.fulfill({ json: [qualified, unknown, conflict].find(value => value.id === id) ?? need })
  })
  await page.goto('/?view=workspace&accountBrowse=1')
  await page.getByRole('button', { name: /Qualified power need/ }).click()
  await page.getByRole('button', { name: 'Power Analysis' }).click()
  await expect(page.getByText(/Qualified remaining gap: 1–4 MW/)).toBeVisible()
  await page.getByRole('button', { name: /Back to power needs/ }).click()
  await page.getByRole('button', { name: /Unknown power need/ }).click()
  await page.getByRole('button', { name: 'Power Analysis' }).click()
  await expect(page.getByText('Supply unknown or no supported remaining gap is available for this need.')).toBeVisible()
  await page.getByRole('button', { name: /Back to power needs/ }).click()
  await page.getByRole('button', { name: /Conflicted power need/ }).click()
  await page.getByRole('button', { name: 'Power Analysis' }).click()
  await expect(page.getByText('Supply unknown or no supported remaining gap is available for this need.')).toBeVisible()
  await expect(page.locator('.wh-detail-head [role="status"]')).toHaveCount(1)
})

test('utility service status stays distinct from an energization date and facility demand stays separate from activity size', async ({ page }) => {
  const card = {
    policy_version: 'opportunity-intelligence-v1', need_id: need.id, project_id: need.project_id,
    input_fingerprint: 'a'.repeat(64), qualification: 'Signal', disposition: 'RESEARCH', fields: [
      { key: 'facility_demand', label: 'Facility Demand', section: 'power', value: null, status: 'Not publicly available', basis: 'No facility-wide demand evidence.' },
      { key: 'energization', label: 'Utility service status', section: 'power', value: 'Utility service application filed', status: 'Verified', basis: 'Public utility filing; no date stated.' },
    ], contacts: [], next_contact_path: 'Unknown', next_action: 'Verify utility timing.', research_gaps: [],
    completeness: { supported: 1, total: 2, percent: 50 }, last_intelligence_update: null, power_gap: null, evidence: [], research_enabled: false,
  }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response([{ ...need, required_mw: '18 MW' }]) }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: { ...need, required_mw: '18 MW', intelligence_card: card } }))
  await page.goto('/?view=workspace&accountBrowse=1')
  await page.locator('[data-need-row="need-a"]').click()
  await page.getByRole('button', { name: 'Power Analysis' }).click()
  const metrics = page.getByRole('region', { name: 'Power need metrics' })
  await expect(metrics).toContainText('Facility DemandNot established')
  await expect(metrics).not.toContainText('18 MW')
  await expect(metrics).toContainText('Utility EnergizationUtility service application filed')
  await expect(metrics).toContainText('Public utility filing; no date stated.')
  await expect(metrics).not.toContainText('date not established')
})

for (const width of [1280, 390]) {
  test(`unified intelligence card preserves evidence, verified actions and research at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    const source = { reference: 'evidence:test', title: 'Official project notice', url: 'https://example.test/project', source_date: '2026-10-20', assessed_at: '2026-10-22T10:00:00Z', retained_evidence_id: 'test', content_hash: 'a'.repeat(64), passage: 'Example Owner is developing the site.', extraction_method: 'Official notice', verification_status: 'Current retained support' }
    const card = {
      policy_version: 'opportunity-intelligence-v1', need_id: need.id, project_id: need.project_id,
      input_fingerprint: 'a'.repeat(64), qualification: 'Signal', disposition: 'RESEARCH',
      fields: [{ key: 'customer', label: 'Customer / end user', section: 'identity', value: 'Example Owner', status: 'Evidence-supported', basis: 'Current owner relationship.', sources: [source] }],
      contacts: [
        { claim_id: 'party', company: 'Example Owner', name: null, title: null, role: 'owner developer', responsibility: 'General company contact path', purchasing_authority: 'Requires confirmation for this power package', methods: [{ kind: 'phone', value: '+1 512 555 0100', href: 'tel:+15125550100', source_url: source.url, verified_at: '2026-10-20T10:00:00Z' }, { kind: 'phone', value: '+1 512 555 0101', href: 'tel:+15125550101', source_url: source.url, verified_at: '2026-10-25T10:00:00Z' }], sources: [source] },
        { claim_id: 'party-source-only', company: 'Example Owner', name: null, title: null, role: 'procurement', responsibility: 'Inferred likely role', purchasing_authority: 'Requires confirmation for this power package', methods: [], sources: [source] },
        { claim_id: 'unknown-date', company: 'Example Owner', name: 'Taylor Unknown', title: 'Operations Director', role: 'operations', responsibility: 'Organizational role', purchasing_authority: 'Requires confirmation for this power package', methods: [{ kind: 'email', value: 'unknown@example.test', href: 'mailto:unknown@example.test', verified_at: 'invalid-date' }], sources: [] },
      ],
      next_contact_path: 'Confirm power procurement with the company office.', next_action: 'Verify the activity-specific power window.',
      research_gaps: [{ key: 'start', label: 'Power needed', section: 'power', value: null, status: 'Research in progress', basis: 'No supported date yet.', research_category: 'timing', research_status: 'NOT_SCHEDULED', sources: [] }],
      completeness: { supported: 1, total: 2, percent: 50, basis: 'Independent of qualification' },
      last_intelligence_update: '2026-10-20T10:00:00Z', power_gap: null, evidence: [source], research_enabled: true,
      power_schedule: {
        status: 'UNRESOLVED', basis: 'Operator-reported phased work plan',
        fact_refs: [{ fact_version_id: 'schedule-v1', content_hash: 'b'.repeat(64), authority: 'User-confirmed', source_reference: 'utility-letter-1', confirmed_at: '2026-10-20T10:00:00Z', reporter_name: 'A. Operator', reporter_organization: 'Example Owner', reporter_role: 'Project Engineer', source_quote: 'January commissioning schedule.' }],
        supplies: [
          { supply_id: 'utility-service', start_date: '2027-01-15', end_date: '2027-02-01', mw_min: '4', mw_max: '5', state: 'committed', suitability: 'suitable', source_kind: 'utility_grid', service_ready_date: '2027-01-15', date_basis: 'Utility service letter', basis: 'Committed service', source_reference: 'utility-letter-1' },
          { supply_id: 'future-grid-option', start_date: '2027-03-01', end_date: '2027-04-01', mw_min: '4', mw_max: '5', state: 'proposed', suitability: 'suitable', source_kind: 'utility_grid', service_ready_date: '2027-03-15', date_basis: 'Draft utility schedule', basis: 'Proposed service', source_reference: null },
        ],
        segments: [
          { phase_id: 'commissioning', start_date: '2027-01-01', end_date: '2027-02-01', demand_min_mw: '10', demand_max_mw: '12', demand_basis: 'Owner-described package', supply_min_mw: null, supply_max_mw: null, residual_min_mw: null, residual_max_mw: null, supply_ids: [], unresolved_supply_ids: [], supply_basis: [], unresolved_reason: 'Other supply is unknown', scenario: 'base' },
          { phase_id: 'future phase', start_date: '2027-03-01', end_date: '2027-03-15', demand_min_mw: '10', demand_max_mw: '12', demand_basis: 'Owner-described package', supply_min_mw: '0', supply_max_mw: '0', residual_min_mw: '10', residual_max_mw: '12', supply_ids: [], unresolved_supply_ids: [], supply_basis: [], unresolved_reason: null, scenario: 'base' },
          { phase_id: 'future phase', start_date: '2027-03-15', end_date: '2027-04-01', demand_min_mw: '10', demand_max_mw: '12', demand_basis: 'Owner-described package', supply_min_mw: '0', supply_max_mw: '0', residual_min_mw: '10', residual_max_mw: '12', supply_ids: [], unresolved_supply_ids: [], supply_basis: [], unresolved_reason: null, scenario: 'base' },
          { phase_id: 'future phase', start_date: '2027-03-15', end_date: '2027-04-01', demand_min_mw: '10', demand_max_mw: '12', demand_basis: 'Owner-described package', supply_min_mw: '4', supply_max_mw: '5', residual_min_mw: '5', residual_max_mw: '8', supply_ids: ['future-grid-option'], unresolved_supply_ids: [], supply_basis: ['future-grid-option: Proposed service (Draft utility schedule)'], unresolved_reason: null, scenario: 'alternative' },
        ],
      },
    }
    await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
    await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response() }))
    await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: {
      ...need, asset_type: 'gas_processing_plant', lifecycle_state: 'operation',
      expected_next_milestone: 'Integrity inspection', expected_power_event: 'Compression upgrade',
      time_to_power_window: 'Within 90 days', estimate_version: 'lifecycle-v2',
      estimate_basis: { confidence: 'medium' },
      lifecycle_timeline: [{ event_type: 'permit', date: '2026-10-20', state: 'permit', evidence_url: source.url, value_kind: 'reported', current: true, published_at: '2026-10-20' }],
      monitoring_requirements: ['Monitor compressor replacement schedule'], lifecycle_open_questions: ['Confirm the power package owner'],
      rank_score: 8, rank_version: 'rank-v1', rank_reasons: ['Near-term power event', 'Known industrial asset'],
      intelligence_card: card,
    } }))
    const researchWrites: string[] = []
    page.on('request', request => { if (request.url().includes('/autonomous-research') && request.method() !== 'GET') researchWrites.push(request.method()) })
    await page.route('**/api/commercial/triage/need-a/autonomous-research', route => route.fulfill({ json: { items: [] } }))
    await page.goto('/?view=workspace&accountBrowse=1&need=need-a')
    const panel = page.getByRole('region', { name: 'Commercial intelligence card', exact: true })
    await expect(panel).toBeVisible()
    await page.getByRole('button', { name: 'Overview', exact: true }).click()
    await panel.locator('.ic-supported-fields > summary').click()
    await expect(panel.locator('.ic-supported-fields')).toContainText('Evidence-supported')
    const contactDetails = panel.locator('.ic-contact details').first()
    await contactDetails.locator('summary').click()
    const latestMethodDate = new Date('2026-10-25T10:00:00Z').toLocaleDateString()
    await expect(contactDetails).toContainText(`Published method source checked ${latestMethodDate}`)
    const sourceOnlyDetails = panel.locator('.ic-contact details').nth(1)
    await sourceOnlyDetails.locator('summary').click()
    const latestSourceDate = new Date('2026-10-22T10:00:00Z').toLocaleDateString()
    await expect(sourceOnlyDetails).toContainText(`Role/source checked ${latestSourceDate}`)
    await page.locator('.wh-provenance-disclosure summary').click()
    await expect(page.locator('.wh-provenance-disclosure')).toContainText('Integrity inspection')
    await expect(page.locator('.wh-provenance-disclosure')).toContainText('Confirm the power package owner')
    const priority = page.getByRole('region', { name: 'Priority explanation' })
    await expect(priority).toContainText('Canonical rank score: 8 · rank-v1')
    await expect(priority).toContainText('Known industrial asset')
    await expect(panel.getByText('Example Owner', { exact: true }).first()).toBeVisible()
    await expect(panel.getByRole('link', { name: 'Call Example Owner owner company route · +1 512 555 0100' })).toHaveAttribute('href', 'tel:+15125550100')
    await expect(panel.locator('a[href^="mailto:"]')).toHaveAttribute('href', 'mailto:unknown@example.test')
    const unknownDateDetails = panel.locator('.ic-contact details').nth(2)
    await unknownDateDetails.locator('summary').click()
    await expect(unknownDateDetails).not.toContainText('Published method source checked')
    await expect(unknownDateDetails).not.toContainText('Role/source checked')
    await expect(unknownDateDetails).not.toContainText('Invalid Date')
    await expect(page.locator('.wh-completeness')).toContainText('1/2')
    await panel.getByRole('button', { name: 'View automated research' }).click()
    await expect(page.getByRole('heading', { name: 'Automated research' })).toBeVisible()
    await expect(page.getByText('No autonomous research questions recorded.')).toBeVisible()
    expect(researchWrites).toEqual([])
    await page.getByRole('button', { name: 'Power Analysis' }).click()
    const schedule = page.getByRole('region', { name: 'Reported phased power schedule' })
    await expect(schedule.getByText('Reported grid energization: 2027-01-15')).toBeVisible()
    await expect(schedule.getByText(/scenario date, not committed service/)).toBeVisible()
    await expect(schedule.getByRole('row').filter({ hasText: '2027-03-01 to 2027-03-15' }).filter({ hasText: 'current reported' })).toContainText('10–12 MW scenario')
    await expect(schedule.getByRole('row').filter({ hasText: '2027-03-15 to 2027-04-01' }).filter({ hasText: 'proposed / hypothetical' })).toContainText('5–8 MW scenario')
    await schedule.getByText('Schedule attribution and source').click()
    await expect(schedule.getByText(/reported by A. Operator, Example Owner · Project Engineer/)).toBeVisible()
    await page.getByRole('button', { name: 'Evidence', exact: true }).click()
    await expect(page.getByRole('region', { name: 'Intelligence card sources' })).toContainText('evidence:test')
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    await page.screenshot({ path: testInfo.outputPath(`intelligence-card-${width}.png`), fullPage: true })
    await page.getByRole('button', { name: /Back to power needs/ }).click()
    await expect(page.getByRole('heading', { name: 'Opportunities', exact: true })).toBeVisible()
  })
}
