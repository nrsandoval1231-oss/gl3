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
})

test('retired editorial URL alias falls through to the private pursuit workspace', async ({ page }) => {
  const apiPaths: string[] = []
  page.on('request', request => {
    const path = new URL(request.url()).pathname
    if (path.startsWith('/api/')) apiPaths.push(path)
  })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response() }))
  await page.goto('/?view=editorial')
  await expect(page.getByRole('heading', { name: 'Opportunity Intelligence' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Editorial review' })).toHaveCount(0)
  expect(apiPaths).toContain('/api/opportunities/workspace')
  expect(apiPaths.some(path => path.toLowerCase().includes('editorial'))).toBe(false)
})

test('workspace sends server filters, opens canonical detail, and restores list navigation', async ({ page }) => {
  const requests: URL[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', async route => { const url = new URL(route.request().url()); requests.push(url); await route.fulfill({ json: response(url.searchParams.get('geography') === 'Austin, TX' ? [need] : []) }) })
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: { ...need, required_mw: '3 MW' } }))
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Opportunity Intelligence' })).toBeVisible()
  await page.locator('.wh-tools > summary').click()
  await page.locator('.wh-filter-disclosure summary').click()
  await page.getByLabel('Geography (exact match)').fill('Austin, TX')
  await expect.poll(() => requests.some(url => url.searchParams.get('geography') === 'Austin, TX')).toBeTruthy()
  await expect(page.getByRole('button', { name: /Test data center/ })).toBeVisible()
  await page.getByRole('button', { name: /Test data center/ }).click()
  await expect(page.getByRole('heading', { name: 'Test data center' })).toBeVisible()
  await page.getByRole('button', { name: 'Power Analysis' }).click()
  await expect(page.locator('.wh-metrics')).toContainText('No facility-wide demand is supported by retained evidence.')
  await page.locator('.wh-more-tabs > summary').click()
  await expect(page.locator('.wh-detail-head [role="status"]')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Research Gaps' })).toBeVisible()
  await page.getByRole('button', { name: 'Research Gaps' }).click()
  await expect(page.getByText(/Buying authority: not evaluated in this summary/)).toBeVisible()
  await page.getByRole('button', { name: 'Overview' }).click()
  // The October 23 workspace uses semantic table rows, preserving the same selection button.
  await expect(page.getByRole('table', { name: 'Opportunity power needs' })).toBeVisible()
  expect(await page.locator('.wh-queue-item:first-child').evaluate(el => getComputedStyle(el).display)).toBe('table-row')
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(1280)
  await expect(page.getByText('A numerical gap is unavailable')).toHaveCount(0)
  await page.getByRole('button', { name: 'Evidence' }).click()
  await expect(page.getByRole('link', { name: 'Permit filing' })).toBeVisible()
  await page.locator('.wh-record-actions').getByRole('button', { name: 'Update workflow' }).click()
  await expect(page).toHaveURL(/section=next-steps/)
  await page.getByRole('button', { name: /Back to power needs/ }).click()
  await expect(page.getByRole('heading', { name: 'Opportunity Intelligence' })).toBeVisible()
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
  await page.goto('/?view=workspace')
  const panel = page.locator('.wh-changes')
  await page.getByRole('button', { name: 'Notifications' }).click()
  await panel.locator(':scope > details > summary').click()
  await panel.getByRole('button', { name: 'Next changes' }).click()
  await expect(panel.getByRole('heading', { name: 'Change 51', exact: true })).toBeVisible()
  await expect(panel.getByText('Showing 51–100 of 100 unreviewed')).toBeVisible()
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
  await expect(panel.getByText('Showing 51–100 of 100 unreviewed')).toBeVisible()
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
  await page.goto('/?view=workspace')
  const rowButton = page.locator('[data-need-row="need-a"]')
  await expect(rowButton.locator('strong')).toHaveText('JLC Electrical Contractor corp · contractor')
  await rowButton.click()
  await expect(page.getByRole('heading', { name: 'Current project electrician · contractor' })).toBeVisible()
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  await page.locator('.wh-source-context summary').click()
  await expect(page.locator('.wh-source-context')).toContainText('Source record: Austin permit 2026-127192 EP')
  await expect(page.locator('.wh-source-context')).not.toContainText('JLC Electrical Contractor corp · contractor')
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
  await page.goto('/?view=workspace&need=need-a')
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
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ status: 503, json: { detail: 'stale cohort' } }))
  await page.goto('/')
  await expect(page.getByRole('alert')).toContainText('cohort is unavailable')
  await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible()
})

test('workspace selection switches to a full detail view on mobile and has a clear return', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response() }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: need }))
  await page.goto('/')
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await page.getByRole('button', { name: /Test data center/ }).click()
  await expect(page.getByRole('button', { name: /Back to power needs/ })).toBeVisible()
  await page.getByRole('button', { name: /Back to power needs/ }).click()
  await expect(page.getByRole('heading', { name: 'Opportunity Intelligence' })).toBeVisible()
})

test('mobile Next action opens a visible next step and Back restores the selected row focus', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response() }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: need }))
  await page.goto('/?view=workspace')
  await page.locator('[data-need-row="need-a"]').click()
  const mobileAction = page.locator('.wh-record-actions')
  await expect(mobileAction).toBeInViewport()
  await mobileAction.getByRole('button', { name: 'Update workflow' }).click()
  await expect(page.getByRole('heading', { name: 'Record call facts' })).toBeVisible()
  await page.getByRole('button', { name: /Back to power needs/ }).click()
  await expect(page.getByRole('button', { name: /Test data center/ })).toBeFocused()
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
  await page.goto('/?view=workspace')
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
  await page.goto('/?view=workspace')
  await page.locator('[data-need-row="need-b"]').click()
  await expect(page.getByRole('heading', { name: 'JLC project' })).toBeVisible()
  await page.locator('[data-need-row="need-a"]').click()
  await expect(page.getByRole('heading', { name: 'ACS project' })).toBeVisible()
  await page.goBack()
  await expect(page.getByRole('heading', { name: 'JLC project' })).toBeVisible()
  const search = page.getByRole('textbox', { name: 'Search workspace' })
  await search.focus()
  await expect(search).toBeFocused()
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(search).toBeFocused()
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
  await page.goto('/?view=workspace')
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
  await page.goto('/?view=workspace')
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

test('mobile selected detail starts at the next action with the compact header', async ({ page }) => {
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
  await page.goto('/?view=workspace')
  await page.locator('[data-need-row="need-a"]').click()
  const action = page.locator('.wh-record-actions')
  await expect(action).toBeInViewport()
  await expect(action.getByRole('button', { name: 'Update workflow' })).toBeInViewport()
  await expect(page.locator('.wh-title-row')).toBeHidden()
  await expect(page.locator('.wh-briefing')).toBeHidden()
  await expect(page.locator('.wh-global-search > span')).toBeHidden()
  expect(await page.locator('.wh-header>a img').evaluate(node => getComputedStyle(node).width)).toBe('170px')
  await expect(page.getByRole('button', { name: /Back to power needs/ })).toBeVisible()
})

test('Next steps presents supported organization, retained permit person and phone, dated reason and question before forms', async ({ page }) => {
  const supported = { ...need, name: 'Austin permit 2026-127192 EP', browse_title: '833 1/2 E BRAKER LN · temporary-power', title_company: 'JLC Electrical Contractor corp', title_company_role: 'Electrical Contractor', commercial_organization: 'JLC Electrical Contractor corp', commercial_reason: 'Active temporary-loop permit issued September 29; retrieved October 14.', commercial_next_question: 'Who is handling the temporary power package, and is supply sufficient?', evidence: [{ ...need.evidence[0], title: 'Historical permit version', assessment_current: false }, { ...need.evidence[0], source_id: 'current', title: 'Current assessment permit', assessment_current: true, published_at: '2026-09-29' }] }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response([supported]) }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: supported }))
  await page.route('**/api/projects/project-a/buying-chain', route => route.fulfill({ json: {
    project_id: 'project-a', candidates: [{ id: 'candidate-a', organization: 'JLC Electrical Contractor corp', category: 'electrical_contractor', stale: false, organization_relationship: 'DIRECT', public_contacts: [] }],
    permit_summaries: [{ evidence_id: 'permit-evidence', title: 'Austin Electrical Permit', url: 'https://example.test/permit', facts: [{ label: 'Contractor company name', value: 'Wrongly inferred company' }, { label: 'Permit-listed contractor name', value: 'Jose Rivera-Lopez' }, { label: 'Contractor permit-listed phone (permit field)', value: '512-555-0100' }] }], unresolved: [], runs: [], status: 'complete',
  } }))
  await page.goto('/?view=workspace')
  await page.locator('[data-need-row="need-a"]').click()
  await page.locator('.wh-record-actions').getByRole('button', { name: 'Update workflow' }).click()
  const brief = page.getByRole('region', { name: 'Call preparation' })
  await expect(brief).toContainText('JLC Electrical Contractor corp')
  await expect(brief).toContainText('Electrical Contractor')
  await expect(brief).toContainText('Jose Rivera-Lopez')
  await expect(brief).toContainText('Permit-listed person')
  await expect(brief).toContainText('512-555-0100')
  await expect(brief).not.toContainText('Wrongly inferred company')
  await expect(brief).toContainText('Current assessment permit')
  await expect(brief).toContainText('Active temporary-loop permit issued September 29')
  await expect(brief).toContainText('Who is handling the temporary power package')
  await expect(brief).toContainText('purchasing authority')
  const briefIndex = await brief.evaluate(el => el.compareDocumentPosition([...document.querySelectorAll('.wh-detail-content h3')].find(heading => heading.textContent?.includes('Record call facts'))!) & Node.DOCUMENT_POSITION_FOLLOWING)
  expect(briefIndex).toBeTruthy()
  await expect(page.getByRole('heading', { name: 'Record call facts' })).toBeVisible()
})

test('Research link carries the selected need into the research queue', async ({ page }) => {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response() }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: need }))
  await page.route('**/api/commercial/triage?*', route => route.fulfill({ json: { items: [], total: 0, offset: 0, limit: 50 } }))
  await page.goto('/?view=workspace&need=need-a')
  await page.getByRole('button', { name: 'Research', exact: true }).click()
  await expect(page).toHaveURL(/pursuitNeed=need-a/)
})

for (const resolved of [false, true]) test(`call-prep excludes prior project contact (already resolved: ${resolved})`, async ({ page }) => {
  const second = { ...need, id: 'need-b', project_id: 'project-b', name: 'Second project' }
  let releaseOld!: () => void
  let oldRequestSeen = false
  const held = new Promise<void>(resolve => { releaseOld = resolve })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response([need, second]) }))
  await page.route('**/api/opportunities/needs/**', route => route.fulfill({ json: route.request().url().includes('need-b') ? second : need }))
  await page.route('**/api/projects/project-a/buying-chain', async route => {
    oldRequestSeen = true
    if (!resolved) await held
    try { await route.fulfill({ json: { project_id: 'project-a', candidates: [{ organization: 'Old project contact', category: 'electrical_contractor', stale: false, organization_relationship: 'DIRECT', public_contacts: [{ value: 'Old project contact', kind: 'phone', source_url: 'https://example.test/old' }] }], permit_summaries: [], unresolved: [], runs: [], status: 'complete' } }) } catch { /* Request was correctly aborted on selection change. */ }
  })
  await page.route('**/api/projects/project-b/buying-chain', route => route.fulfill({ json: { project_id: 'project-b', candidates: [], permit_summaries: [], unresolved: [], runs: [], status: 'complete' } }))
  await page.goto('/?view=workspace')
  await page.locator('[data-need-row="need-a"]').click()
  await page.locator('.wh-record-actions').getByRole('button', { name: 'Update workflow' }).click()
  await expect.poll(() => oldRequestSeen).toBeTruthy()
  if (resolved) await expect(page.getByRole('region', { name: 'Call preparation' })).toContainText('Old project contact')
  await page.locator('[data-need-row="need-b"]').click()
  await page.locator('.wh-record-actions').getByRole('button', { name: 'Update workflow' }).click()
  await expect(page.getByRole('heading', { name: 'Second project' })).toBeVisible()
  releaseOld()
  await expect(page.getByRole('region', { name: 'Call preparation' })).not.toContainText('Old project contact')
})

test('a deep-link detail uses the current workspace disposition instead of stale detail metadata', async ({ page }) => {
  const current = { ...need, commercial_disposition: 'ACTION NOW', commercial_reason: 'Current reviewed evidence supports immediate investigation.' }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response([current]) }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: { ...need, commercial_disposition: 'RESEARCH', commercial_reason: 'Stale disposition from an older snapshot.' } }))
  await page.goto('/?view=workspace&need=need-a')
  await expect(page.getByRole('heading', { name: 'Test data center' })).toBeVisible()
  await expect(page.locator('.wh-record-metadata')).toContainText('ACTION NOW')
  await expect(page.locator('.wh-record-metadata')).not.toContainText('Stale disposition')
})

test('refreshing to a new cohort clears selected commercial preview when its row is absent', async ({ page }) => {
  const current = { ...need, commercial_disposition: 'ACTION NOW', commercial_reason: 'Current evidence supports immediate investigation.' }
  const requests: URL[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', async route => {
    const url = new URL(route.request().url())
    requests.push(url)
    const excluded = url.searchParams.get('search') === 'new generation'
    await route.fulfill({ json: { ...response(excluded ? [] : [current]), cohort_token: excluded ? 'cohort-b' : 'cohort-a' } })
  })
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: need }))
  await page.goto('/?view=workspace')
  await page.getByRole('button', { name: /Test data center/ }).click()
  await expect(page.locator('.wh-record-metadata')).toContainText('ACTION NOW')
  await page.getByRole('textbox', { name: 'Search workspace' }).fill('new generation')
  await expect.poll(() => requests.some(url => url.searchParams.get('search') === 'new generation')).toBeTruthy()
  await expect(page.getByRole('heading', { name: 'Test data center' })).toBeVisible()
  await expect(page.locator('.wh-record-metadata')).toContainText('Disposition unavailable')
  await expect(page.locator('.wh-record-metadata')).not.toContainText('ACTION NOW')
})

test('global search sends a server query and displays the matching cohort result', async ({ page }) => {
  const match = { ...need, id: 'need-search', name: 'Searchable Austin project' }
  const requests: string[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', async route => {
    const query = new URL(route.request().url()).searchParams.get('search') ?? ''
    requests.push(query)
    await route.fulfill({ json: response(query === 'Searchable Austin project' ? [match] : []) })
  })
  await page.goto('/?view=workspace')
  await page.getByRole('textbox', { name: 'Search workspace' }).fill('Searchable Austin project')
  await expect.poll(() => requests.includes('Searchable Austin project')).toBeTruthy()
  await expect(page.getByRole('button', { name: /Searchable Austin project/ })).toBeVisible()
})

test('workspace delays protected list requests until login succeeds, then loads the list', async ({ page }) => {
  let loggedIn = false
  let listRequests = 0
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: loggedIn } }))
  await page.route('**/api/auth/login', async route => { loggedIn = true; await route.fulfill({ json: { authenticated: true } }) })
  await page.route('**/api/opportunities/workspace?*', async route => { listRequests += 1; await route.fulfill({ json: response() }) })
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: need }))
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  expect(listRequests).toBe(0)
  await page.getByLabel('Password', { exact: true }).fill('test-password')
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByRole('button', { name: /Test data center/ })).toBeVisible()
  expect(listRequests).toBeGreaterThan(0)
})

test('workspace selection is restored through Back, Forward, and a deep-link refresh', async ({ page }) => {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response() }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: need }))
  await page.goto('/')
  await page.getByRole('button', { name: /Test data center/ }).click()
  await expect(page.getByRole('heading', { name: 'Test data center' })).toBeVisible()
  await page.goBack()
  await expect(page.getByRole('heading', { name: 'Opportunity Intelligence' })).toBeVisible()
  await page.goForward()
  await expect(page.getByRole('heading', { name: 'Test data center' })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Test data center' })).toBeVisible()
})

test('title enrichment is explicit, polls pending work, refreshes the saved list, and shows citations', async ({ page }) => {
  let queued = false
  let ready = false
  let statusReads = 0
  const enrichedTitle = 'Cobalt Data Center expansion — Cobalt Energy — asset operator — Activity: Building substations.'
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response([{ ...need, browse_title: ready ? enrichedTitle : undefined }]) }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: need }))
  await page.route('**/api/power-needs/need-a/title', async route => {
    if (route.request().method() === 'POST') {
      queued = true
      await route.fulfill({ json: { status: 'pending', job_id: 'job-a', result: null, citations: [], generated_at: null, model: 'gpt-test' } })
      return
    }
    statusReads += 1
    if (!queued) {
      await route.fulfill({ json: { status: 'unavailable', result: null, citations: [], generated_at: null, model: null } })
      return
    }
    if (statusReads >= 3) {
      ready = true
      await route.fulfill({ json: { status: 'ready', result: { title: enrichedTitle }, citations: [{ evidence_id: 'ev-a', title: 'Current permit', url: 'https://example.test/current', publisher: 'City permits', quote: 'Activity: Building substations.' }], generated_at: '2026-10-19T10:00:00Z', model: 'gpt-test' } })
      return
    }
    await route.fulfill({ json: { status: 'pending', result: null, citations: [], generated_at: null, model: 'gpt-test' } })
  })
  await page.goto('/?view=workspace')
  await page.locator('[data-need-row="need-a"]').click()
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Enrich title' })).toBeVisible()
  await expect.poll(() => statusReads).toBe(1)
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  await page.getByRole('button', { name: 'Enrich title' }).click()
  await expect(page.getByRole('heading', { name: enrichedTitle })).toBeVisible({ timeout: 8000 })
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  const titleRegion = page.getByRole('region', { name: 'Evidence-grounded title' })
  await expect(titleRegion.getByRole('link', { name: 'Current permit' })).toBeVisible()
  await expect(titleRegion).toContainText('source activity')
  await expect(titleRegion).toContainText('"Activity: Building substations."')
  await expect(page.locator('[data-need-row="need-a"] strong')).toHaveText(enrichedTitle)
})

test('switching selected needs clears the prior title and ignores late title status', async ({ page }) => {
  const second = { ...need, id: 'need-b', project_id: 'project-b', name: 'Second project' }
  let releaseFirst: (() => void) | undefined
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response([need, second]) }))
  await page.route('**/api/opportunities/needs/*', route => route.fulfill({ json: route.request().url().includes('need-b') ? second : need }))
  await page.route('**/api/power-needs/*/title', async route => {
    if (route.request().url().includes('need-a')) await new Promise<void>(resolve => { releaseFirst = resolve })
    await route.fulfill({ json: { status: 'unavailable', result: null, citations: [], generated_at: null, model: null } })
  })
  await page.goto('/?view=workspace')
  await page.locator('[data-need-row="need-a"]').click()
  await page.locator('[data-need-row="need-b"]').click()
  await expect(page.getByRole('heading', { name: 'Second project' })).toBeVisible()
  releaseFirst?.()
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Enrich title' })).toBeVisible()
  await expect(page.locator('.wh-title-enrichment')).not.toContainText('Cobalt Data Center expansion')
})

test('switching needs during a title POST does not leave the new selection busy', async ({ page }) => {
  const second = { ...need, id: 'need-b', project_id: 'project-b', name: 'Second project' }
  let releasePost: (() => void) | undefined
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response([need, second]) }))
  await page.route('**/api/opportunities/needs/*', route => route.fulfill({ json: route.request().url().includes('need-b') ? second : need }))
  await page.route('**/api/power-needs/*/title', async route => {
    if (route.request().method() === 'POST' && route.request().url().includes('need-a')) {
      await new Promise<void>(resolve => { releasePost = resolve })
      await route.fulfill({ json: { status: 'pending', job_id: 'job-a', result: null, citations: [], generated_at: null, model: 'gpt-test' } })
      return
    }
    await route.fulfill({ json: { status: 'unavailable', result: null, citations: [], generated_at: null, model: null } })
  })
  await page.goto('/?view=workspace')
  await page.locator('[data-need-row="need-a"]').click()
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  await page.getByRole('button', { name: 'Enrich title' }).click()
  await expect.poll(() => Boolean(releasePost)).toBeTruthy()
  await page.locator('[data-need-row="need-b"]').click()
  await expect(page.getByRole('heading', { name: 'Second project' })).toBeVisible()
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Enrich title' })).toBeEnabled()
  releasePost?.()
})

test('a failed pending-title status check is visible and retryable', async ({ page }) => {
  let posts = 0
  let statusReads = 0
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response() }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: need }))
  await page.route('**/api/power-needs/need-a/title', async route => {
    if (route.request().method() === 'POST') {
      posts += 1
      await route.fulfill({ json: { status: 'pending', job_id: `job-${posts}`, result: null, citations: [], generated_at: null, model: 'gpt-test' } })
      return
    }
    statusReads += 1
    if (statusReads === 1) await route.fulfill({ json: { status: 'unavailable', result: null, citations: [], generated_at: null, model: null } })
    else if (statusReads === 2) await route.fulfill({ status: 503, json: { detail: 'temporarily unavailable' } })
    else await route.fulfill({ json: { status: 'pending', job_id: `job-${posts}`, result: null, citations: [], generated_at: null, model: 'gpt-test' } })
  })
  await page.goto('/?view=workspace')
  await page.locator('[data-need-row="need-a"]').click()
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  await page.getByRole('button', { name: 'Enrich title' }).click()
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  const titleRegion = page.getByRole('region', { name: 'Evidence-grounded title' })
  await expect(titleRegion).toContainText('Title status could not be checked', { timeout: 8000 })
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Enrich title' })).toBeDisabled()
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  await page.getByRole('button', { name: 'Retry status' }).click()
  await expect.poll(() => statusReads).toBeGreaterThan(2)
  await expect.poll(() => posts).toBe(1)
  await expect(titleRegion).toContainText('Title request pending.')
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Enrich title' })).toBeEnabled()
})

test('a delayed status retry for a prior selection cannot leave that need busy', async ({ page }) => {
  const second = { ...need, id: 'need-b', project_id: 'project-b', name: 'Second project' }
  let aStatusReads = 0
  let releaseRetry: (() => void) | undefined
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response([need, second]) }))
  await page.route('**/api/opportunities/needs/*', route => route.fulfill({ json: route.request().url().includes('need-b') ? second : need }))
  await page.route('**/api/power-needs/*/title', async route => {
    if (route.request().url().includes('need-b')) {
      await route.fulfill({ json: { status: 'unavailable', result: null, citations: [], generated_at: null, model: null } })
      return
    }
    if (route.request().method() === 'POST') {
      await route.fulfill({ json: { status: 'unavailable', result: null, citations: [], generated_at: null, model: null } })
      return
    }
    aStatusReads += 1
    if (aStatusReads === 2) await new Promise<void>(resolve => { releaseRetry = resolve })
    if (aStatusReads === 1 || aStatusReads === 3) {
      await route.fulfill({ status: 503, json: { detail: 'temporarily unavailable' } })
    } else {
      await route.fulfill({ json: { status: 'unavailable', result: null, citations: [], generated_at: null, model: null } })
    }
  })
  await page.goto('/?view=workspace')
  await page.locator('[data-need-row="need-a"]').click()
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Retry status' })).toBeVisible()
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  await page.getByRole('button', { name: 'Retry status' }).click()
  await expect.poll(() => Boolean(releaseRetry)).toBeTruthy()
  await page.locator('[data-need-row="need-b"]').click()
  await expect(page.getByRole('heading', { name: 'Second project' })).toBeVisible()
  await page.locator('[data-need-row="need-a"]').click()
  await expect(page.getByRole('heading', { name: 'Test data center' })).toBeVisible()
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Retry status' })).toBeEnabled()
  releaseRetry?.()
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  await page.getByRole('button', { name: 'Retry status' }).click()
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Enrich title' })).toBeEnabled()
})

test('an initial title status failure replaces last-known enriched detail with deterministic fallback', async ({ page }) => {
  const lastKnown = 'Old enriched project title - owner operator'
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response([{ ...need, browse_title: lastKnown, title_status: 'ready' }]) }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: { ...need, browse_title: lastKnown, title_status: 'ready' } }))
  let titleReads = 0
  let titlePosts = 0
  await page.route('**/api/power-needs/need-a/title', route => {
    if (route.request().method() === 'POST') titlePosts += 1
    titleReads += 1
    if (titleReads === 1) return route.fulfill({ status: 503, json: { detail: 'temporarily unavailable' } })
    return route.fulfill({ json: { status: 'unavailable', result: null, citations: [], generated_at: null, model: null } })
  })
  await page.goto('/?view=workspace')
  await page.locator('[data-need-row="need-a"]').click()
  await expect(page.getByRole('heading', { name: 'Test data center' })).toBeVisible()
  await expect(page.getByRole('heading', { name: lastKnown })).toHaveCount(0)
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  const titleRegion = page.getByRole('region', { name: 'Evidence-grounded title' })
  await expect(titleRegion).toContainText('status could not be checked')
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Enrich title' })).toBeDisabled()
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  await page.getByRole('button', { name: 'Retry status' }).click()
  await expect.poll(() => titleReads).toBe(2)
  await expect.poll(() => titlePosts).toBe(0)
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Enrich title' })).toBeEnabled()
  await expect(titleRegion).toContainText('Showing source-backed title fallback.')
})

test('cached ready POST refreshes the saved list and a newly stale item falls back', async ({ page }) => {
  let listReads = 0
  let detailReads = 0
  const oldTitle = 'Old generated title - source role - Activity: Old activity.'
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => {
    listReads += 1
    const row = listReads === 1
      ? { ...need, browse_title: oldTitle, title_status: 'ready' }
      : { ...need, browse_title: 'Temporary power - Austin, TX', title_status: 'stale' }
    return route.fulfill({ json: response([row]) })
  })
  await page.route('**/api/opportunities/needs/need-a*', route => {
    detailReads += 1
    return route.fulfill({ json: { ...need, title_status: detailReads === 1 ? 'ready' : 'stale', browse_title: detailReads === 1 ? oldTitle : 'Temporary power - Austin, TX' } })
  })
  let titleStatusReads = 0
  await page.route('**/api/power-needs/need-a/title', async route => {
    if (route.request().method() === 'POST') {
      await route.fulfill({ json: { status: 'ready', result: { title: oldTitle }, citations: [{ evidence_id: 'ev-a', title: 'Old permit', url: 'https://example.test/old', publisher: 'City', quote: 'Old activity.' }], generated_at: '2026-10-19T10:00:00Z', model: 'gpt-test' } })
      return
    }
    titleStatusReads += 1
    if (titleStatusReads === 1) {
      await route.fulfill({ json: { status: 'ready', result: { title: oldTitle }, citations: [{ evidence_id: 'ev-a', title: 'Old permit', url: 'https://example.test/old', publisher: 'City', quote: 'Old activity.' }], generated_at: '2026-10-19T10:00:00Z', model: 'gpt-test' } })
      return
    }
    await route.fulfill({ json: { status: 'stale', result: null, citations: [], generated_at: null, model: 'gpt-test' } })
  })
  await page.goto('/?view=workspace')
  await page.locator('[data-need-row="need-a"]').click()
  await expect(page.getByRole('heading', { name: 'Old generated title' })).toBeVisible()
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  await page.getByRole('button', { name: 'Refresh title' }).click()
  await expect.poll(() => listReads).toBeGreaterThan(1)
  await expect(page.getByRole('heading', { name: 'Temporary power - Austin, TX' })).toBeVisible()
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  const titleRegion = page.getByRole('region', { name: 'Evidence-grounded title' })
  await expect(titleRegion).toContainText('Saved title is stale')
  await expect(titleRegion).not.toContainText('Old permit')
})

test('the selected title response wins over stale browse metadata in either direction', async ({ page }) => {
  const staleNeed = {
    ...need,
    id: 'need-a',
    title_status: 'ready',
    browse_title: 'Old enriched browse title - owner operator',
  }
  const refreshedNeed = {
    ...need,
    id: 'need-b',
    project_id: 'project-b',
    name: 'Second project',
    title_status: 'stale',
    browse_title: 'Old stale title - contractor',
  }
  const freshTitle = 'Second project - Synthetic Owner LLC - asset operator - Activity: Site expansion.'
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response([staleNeed, refreshedNeed]) }))
  await page.route('**/api/opportunities/needs/*', route => {
    const id = route.request().url().includes('need-b') ? 'need-b' : 'need-a'
    return route.fulfill({ json: id === 'need-b' ? refreshedNeed : staleNeed })
  })
  await page.route('**/api/power-needs/*/title', route => {
    const id = route.request().url().includes('need-b') ? 'need-b' : 'need-a'
    return route.fulfill({ json: id === 'need-a'
      ? { status: 'stale', result: null, citations: [], generated_at: null, model: 'gpt-test' }
      : { status: 'ready', result: { title: freshTitle }, citations: [{ evidence_id: 'ev-b', title: 'Current filing', url: 'https://example.test/current', publisher: 'City', quote: 'Activity: Site expansion.' }], generated_at: '2026-10-19T10:00:00Z', model: 'gpt-test' },
    })
  })
  await page.goto('/?view=workspace')
  await page.locator('[data-need-row="need-a"]').click()
  await expect(page.getByRole('heading', { name: 'Test data center' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Old enriched browse title - owner operator' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Evidence-grounded title' })).toContainText('Saved title is stale')
  await page.locator('[data-need-row="need-b"]').click()
  await expect(page.getByRole('heading', { name: freshTitle })).toBeVisible()
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Evidence-grounded title' })).toContainText('Evidence-grounded title')
  await expect(page.getByRole('heading', { name: 'Old stale title - contractor' })).toHaveCount(0)
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
  await page.goto('/?view=workspace&tier=Signal&offset=25&cohort_token=old')
  await expect(page.getByRole('heading', { name: 'Opportunity Intelligence' })).toBeVisible()
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
  await page.goto('/')
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
  await page.route('**/api/power-needs/need-a/title', route => route.fulfill({ json: { status: 'disabled', result: null, citations: [] } }))
  await page.route('**/api/needs/need-a/facts*', route => route.fulfill({ json: { items: [], total: 0, limit: 50, offset: 0, next_offset: null, current_fact_version: 0 } }))
  await page.route('**/api/needs/need-a/workflow-status', route => route.fulfill({ json: { need_id: 'need-a', status: 'New', version: 0, events: [] } }))
  await page.goto('/?view=workspace&geography=Austin')
  await expect(page.getByRole('button', { name: /Austin retained row/ })).toBeVisible()
  await page.locator('[data-need-row="need-a"]').click()
  await expect(page.getByRole('heading', { name: 'Fresh canonical detail' })).toBeVisible()
  await page.getByRole('button', { name: 'Notes', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Call preparation' }).getByText(oldCohortAction)).toBeVisible()
  await page.locator('.wh-tools > summary').click()
  await page.locator('.wh-filter-disclosure summary').click()
  await page.getByLabel('Geography (exact match)').fill('Houston')
  await expect(page.locator('.wh-error[role="alert"]')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Fresh canonical detail' })).toBeVisible()
  await expect(page.getByText(oldCohortAction)).toHaveCount(0)
  await expect(page.getByRole('button', { name: /Austin retained row/ })).toHaveCount(0)
  await expect(page.locator('.wh-queue-heading')).toContainText('Opportunity results unavailable')
  await expect(page.locator('.wh-paging')).toContainText('of —')
})

test('canonical priority score and reasons are explained separately from disposition', async ({ page }) => {
  const ranked = { ...need, rank_score: 8, rank_reasons: ['Near-term start', 'Supported project scale'], rank_version: 'rank-v1' }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response([ranked]) }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: ranked }))
  await page.goto('/?view=workspace')
  await page.locator('[data-need-row="need-a"]').click()
  await page.getByRole('button', { name: 'Overview' }).click()
  const priority = page.getByRole('region', { name: 'Priority explanation' })
  await expect(priority).toContainText('Canonical rank score: 8 · rank-v1')
  await expect(priority).toContainText('Near-term start')
  await expect(priority).toContainText('separate from qualification and commercial disposition')
})

test('material change review acknowledges only the displayed page and keeps health exceptions visible', async ({ page }) => {
  await page.unrouteAll()
  const change = {
    event_key: 'fact:11111111-1111-4111-8111-111111111111', category: 'changed', title: 'Call fact accepted: demand',
    detail: 'Austin DC · Synthetic Facility', created_at: '2026-10-20T11:00:00Z', source_date: '2026-10-20',
    project_id: 'project-a', before_state: null, after_state: { fact_type: 'demand', value: { mw: '12' } },
    needs: [{ id: 'need-a', name: 'Synthetic Facility', location: 'Austin, TX', active: false, tier: 'Signal' }],
    sources: [], fact_version_id: '22222222-2222-4222-8222-222222222222', fact_type: 'demand', decision: 'accepted',
    reason: 'Confirmed by operator', actor: 'Operator', confirmed_at: '2026-10-20T10:00:00Z', source_reference: null,
  }
  let reads = 0
  let reviewed = false
  let reviewBody: Record<string, unknown> | null = null
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response() }))
  await page.route('**/api/opportunities/workspace/changes*', route => {
    reads += 1
    return route.fulfill({ json: reviewed ? { ...emptyChanges, first_use: false, baseline_reviewed_at: '2026-10-20T12:01:00Z', source_health_exceptions: [{ source_id: 'source-a', status: 'Partial', error: 'partial run', parse_failures: 1 }] } : { ...emptyChanges, items: [change], total_unreviewed: 1, counts: { ...emptyChanges.counts, changed: 1 }, source_health_exceptions: [{ source_id: 'source-a', status: 'Partial', error: 'partial run', parse_failures: 1 }] } })
  })
  await page.route('**/api/opportunities/workspace/changes/review', async route => {
    reviewBody = route.request().postDataJSON() as Record<string, unknown>
    reviewed = true
    await route.fulfill({ json: { baseline_identity: emptyChanges.baseline_identity, reviewed_at: '2026-10-20T12:01:00Z', reviewed_count: 1, event_keys: [change.event_key], token: emptyChanges.token, remaining_counts: emptyChanges.counts } })
  })
  await page.route('**/api/opportunities/needs/need-a/history', route => route.fulfill({ json: { id: 'need-a', project_id: 'project-a', name: 'Synthetic Facility', location: 'Austin, TX', activity: 'construction', active: false, tier: 'Signal', rationale: 'Closed historical need', required_mw: null, start_window: null, duration: null, supply: 'Unknown', updated_at: '2026-10-20T10:30:00Z', evidence: [] } }))
  await page.goto('/?view=workspace')
  const panel = page.locator('.wh-changes')
  await page.getByRole('button', { name: 'Notifications' }).click()
  await panel.getByText('Material changes · 1 unreviewed items').click()
  await expect(panel).toContainText('Call fact accepted: demand')
  await expect(panel).toContainText('Source-health exceptions')
  await page.screenshot({ path: 'test-results/audit-workspace-briefing.png', fullPage: true })
  await panel.getByRole('button', { name: /Synthetic Facility · Austin, TX/ }).click()
  await expect(panel).toContainText('Inactive historical need')
  await panel.getByRole('button', { name: 'Close historical detail' }).click()
  await panel.getByRole('button', { name: 'Mark these displayed changes reviewed' }).click()
  await expect.poll(() => reviewBody).toEqual({ baseline_identity: emptyChanges.baseline_identity, token: emptyChanges.token, limit: 50, offset: 0 })
  await expect.poll(() => reads).toBeGreaterThan(1)
  await expect(panel).toContainText('No unreviewed material changes on this page.')
  await expect(panel).toContainText('source-a · Partial · partial run · 1 parse failures')
})

test('reviewing page two resets to the remaining first page without changing its exact token', async ({ page }) => {
  await page.unrouteAll()
  let pageTwoReviewed = false
  let failFirstReview = true
  const reviewBodies: Record<string, unknown>[] = []
  const changes = (offset: number) => {
    const start = pageTwoReviewed ? 1 : offset + 1
    const count = pageTwoReviewed ? 50 : 100 - offset
    const items = Array.from({ length: Math.min(50, count) }, (_, index) => ({
      event_key: `change:${start + index}`,
      category: 'changed',
      title: `Change ${start + index}`,
      detail: 'Synthetic remaining material change',
      created_at: '2026-10-20T12:00:00Z',
      source_date: null, project_id: null, before_state: null, after_state: null,
      needs: [], sources: [],
    }))
    return {
      ...emptyChanges,
      items,
      total_unreviewed: pageTwoReviewed ? 50 : 100,
      offset: pageTwoReviewed ? 0 : offset,
      next_offset: pageTwoReviewed ? null : offset === 0 ? 50 : null,
      token: `token-${pageTwoReviewed ? 'remaining' : offset}`,
    }
  }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response() }))
  await page.route('**/api/opportunities/workspace/changes?*', async route => {
    const offset = Number(new URL(route.request().url()).searchParams.get('offset') ?? 0)
    return route.fulfill({ json: changes(offset) })
  })
  await page.route('**/api/opportunities/workspace/changes/review', async route => {
    reviewBodies.push(route.request().postDataJSON() as Record<string, unknown>)
    if (failFirstReview) {
      failFirstReview = false
      return route.fulfill({ status: 503, json: { detail: 'Synthetic review response failure' } })
    }
    pageTwoReviewed = true
    return route.fulfill({ json: { baseline_identity: emptyChanges.baseline_identity, reviewed_count: 50, token: 'token-50', event_keys: [] } })
  })
  await page.goto('/?view=workspace')
  const panel = page.locator('.wh-changes')
  await page.getByRole('button', { name: 'Notifications' }).click()
  await panel.locator(':scope > details > summary').click()
  await expect(panel.getByRole('heading', { name: 'Change 1', exact: true })).toBeVisible()
  await panel.getByRole('button', { name: 'Next changes' }).click()
  await expect(panel.getByRole('heading', { name: 'Change 51', exact: true })).toBeVisible()
  await panel.getByRole('button', { name: 'Mark these displayed changes reviewed' }).click()
  await expect(panel.getByRole('alert')).toBeVisible()
  await expect(panel.getByRole('heading', { name: 'Change 51', exact: true })).toBeVisible()
  await panel.getByRole('button', { name: 'Mark these displayed changes reviewed' }).click()
  await expect.poll(() => reviewBodies).toHaveLength(2)
  expect(reviewBodies[0]).toEqual({ baseline_identity: emptyChanges.baseline_identity, token: 'token-50', limit: 50, offset: 50 })
  expect(reviewBodies[1]).toEqual(reviewBodies[0])
  await expect(panel.getByRole('heading', { name: 'Change 1', exact: true })).toBeVisible()
  await expect(panel.getByRole('heading', { name: 'Change 50', exact: true })).toBeVisible()
  await expect(panel.getByText('Showing 1–50 of 50 unreviewed')).toBeVisible()
})

test('accepted fact read-back refreshes the material changes count and list', async ({ page }) => {
  await page.unrouteAll()
  let fact: Record<string, any> | null = null
  let currentVersion = 0
  let changeReads = 0
  const emptyFactPage = () => ({ items: fact ? [fact] : [], total: fact ? 1 : 0, limit: 50, offset: 0, next_offset: null, current_fact_version: currentVersion })
  const materialChange = {
    ...emptyChanges,
    items: [{
      event_key: 'fact:accepted-fact', category: 'changed', title: 'Call fact accepted: demand',
      detail: 'Synthetic facility', created_at: '2026-10-20T12:00:00Z', source_date: null,
      project_id: 'project-a', before_state: null,
      after_state: { fact_type: 'demand', value: { mw: '12' }, effective_from: null, effective_until: null },
      needs: [], sources: [], fact_version_id: 'accepted-fact', fact_type: 'demand', decision: 'accepted',
      reason: 'Confirmed by operator', actor: 'Operator', confirmed_at: '2026-10-20T12:00:00Z', source_reference: null,
    }],
    counts: { ...emptyChanges.counts, changed: 1 }, total_unreviewed: 1,
  }
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const method = request.method()
    if (path === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (path === '/api/opportunities/workspace') return route.fulfill({ json: response() })
    if (path === '/api/opportunities/workspace/changes') {
      changeReads += 1
      return route.fulfill({ json: fact?.decision === 'accepted' ? materialChange : emptyChanges })
    }
    if (path === '/api/opportunities/needs/need-a') return route.fulfill({ json: need })
    if (path === '/api/needs/need-a/facts' && method === 'GET') return route.fulfill({ json: emptyFactPage() })
    if (path === '/api/needs/need-a/facts' && method === 'POST') {
      currentVersion = 1
      fact = { id: 'accepted-fact', need_id: 'need-a', project_id: 'project-a', predecessor_id: null, activity_key: 'construction', facility_scope: 'Test data center', fact_type: 'demand', value: { mw: '12', basis: 'Synthetic report' }, reporter_name: 'Synthetic operator', reporter_role: 'Project Engineer', confirmation_channel: 'phone', source_reference: null, source_date: null, confirmed_at: '2026-10-20T12:00:00Z', effective_from: '2026-10-20T12:00:00Z', effective_until: null, content_hash: 'a'.repeat(64), decision: 'draft', decision_version: currentVersion, decision_reason: 'Draft', decision_actor: 'Operator', authority_label: 'Reported / not accepted', recorded_by: 'Operator', created_at: '2026-10-20T12:00:00Z' }
      return route.fulfill({ json: fact })
    }
    if (path === '/api/needs/need-a/facts/accepted-fact/decision' && method === 'POST') {
      currentVersion += 1
      fact = { ...fact!, decision: 'accepted', decision_version: currentVersion, decision_reason: 'Confirmed by operator', decision_actor: 'Operator', authority_label: 'User-confirmed' }
      return route.fulfill({ json: { id: 'decision-accepted', version: currentVersion, decision: 'accepted', fact_version_id: 'accepted-fact', reason: 'Confirmed by operator', actor: 'Operator', created_at: '2026-10-20T12:00:00Z' } })
    }
    if (path === '/api/needs/need-a/workflow-status') return route.fulfill({ json: { need_id: 'need-a', status: 'New', version: 0, events: [] } })
    if (path === '/api/power-needs/need-a/title') return route.fulfill({ json: { status: 'disabled', result: null, citations: [] } })
    if (path === '/api/projects/project-a/buying-chain') return route.fulfill({ json: { project_id: 'project-a', candidates: [], permit_summaries: [], unresolved: [], runs: [], status: 'unavailable' } })
    return route.fulfill({ json: [] })
  })
  await page.goto('/?view=workspace')
  const panel = page.locator('.wh-changes')
  await page.getByRole('button', { name: 'Notifications' }).click()
  const summary = panel.locator(':scope > details > summary')
  await expect(summary).toContainText('0 unreviewed items')
  await summary.click()
  await page.locator('[data-need-row="need-a"]').click()
  await page.getByRole('button', { name: 'Notes', exact: true }).click()
  await page.getByLabel('Reporter name').fill('Synthetic operator')
  await page.getByLabel('Reported demand (MW or bounded range)').fill('12')
  await page.getByRole('button', { name: 'Save fact draft' }).click()
  await expect(page.getByText(/Draft persisted and confirmed/)).toBeVisible()
  await page.getByLabel('Reason for decision').fill('Confirmed by operator')
  await page.getByRole('button', { name: 'Accept fact' }).click()
  await expect(page.getByRole('option', { name: 'v2 · demand · accepted', exact: true })).toHaveCount(1)
  await expect.poll(() => changeReads).toBeGreaterThan(1)
  await expect(summary).toContainText('1 unreviewed items')
  await expect(panel.getByRole('heading', { name: 'Call fact accepted: demand' })).toBeVisible()
})

test('row-based schedule drafts, accepts, corrects and retracts with dated utility metadata', async ({ page }) => {
  await page.unrouteAll()
  let currentVersion = 0
  const facts: Array<Record<string, any>> = []
  const postedValues: Record<string, any>[] = []
  const pageResult = () => ({
    items: [...facts].reverse(), total: facts.length, limit: 50, offset: 0, next_offset: null,
    current_fact_version: currentVersion,
    current_reported_timing_correction_target: {
      available: false, unavailable_reason: 'no_current_admitted_lead', need_id: 'need-a',
      project_id: 'project-a', project_identity_key: null, activity_key: 'construction', facility_identity: null,
      source_semantic_hash: null, source_evidence_hash: null, retained_evidence_id: null, source_id: null,
      earliest_possible_start: null, latest_possible_start: null, minimum_duration_days: null,
      maximum_duration_days: null, current_fact_version: currentVersion,
    },
  })
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const method = request.method()
    if (path === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (path === '/api/opportunities/workspace') return route.fulfill({ json: response() })
    if (path === '/api/opportunities/workspace/changes') return route.fulfill({ json: emptyChanges })
    if (path === '/api/opportunities/needs/need-a') return route.fulfill({ json: need })
    if (path === '/api/needs/need-a/facts' && method === 'GET') return route.fulfill({ json: pageResult() })
    if (path === '/api/needs/need-a/facts' && method === 'POST') {
      currentVersion += 1
      postedValues.push(request.postDataJSON())
      const fact = { ...(postedValues.at(-1) as object), id: `schedule-${facts.length + 1}`, need_id: 'need-a', project_id: 'project-a', decision: 'draft', decision_version: currentVersion, decision_reason: 'Draft', decision_actor: 'Operator', authority_label: 'Reported / not accepted', recorded_by: 'Operator', created_at: '2026-10-20T12:00:00Z', content_hash: 'a'.repeat(64) }
      facts.push(fact)
      return route.fulfill({ json: fact })
    }
    const decisionMatch = path.match(/^\/api\/needs\/need-a\/facts\/([^/]+)\/decision$/)
    if (decisionMatch && method === 'POST') {
      currentVersion += 1
      const body = request.postDataJSON() as { decision: string; reason: string }
      const fact = facts.find(row => row.id === decisionMatch[1])!
      fact.decision = body.decision; fact.decision_version = currentVersion
      fact.decision_reason = body.reason; fact.decision_actor = 'Operator'
      fact.authority_label = body.decision === 'accepted' || body.decision === 'corrected' ? 'User-confirmed' : 'Retracted'
      return route.fulfill({ json: { id: `decision-${currentVersion}`, version: currentVersion, decision: body.decision, fact_version_id: fact.id, reason: body.reason, actor: 'Operator', created_at: '2026-10-20T12:00:00Z' } })
    }
    if (path === '/api/needs/need-a/workflow-status') return route.fulfill({ json: { need_id: 'need-a', status: 'New', version: 0, events: [] } })
    if (path === '/api/power-needs/need-a/title') return route.fulfill({ json: { status: 'disabled', result: null, citations: [] } })
    if (path === '/api/projects/project-a/buying-chain') return route.fulfill({ json: { project_id: 'project-a', candidates: [], permit_summaries: [], unresolved: [], runs: [], status: 'unavailable' } })
    return route.fulfill({ json: [] })
  })
  await page.goto('/?view=workspace')
  await page.locator('[data-need-row="need-a"]').click()
  await page.getByRole('button', { name: 'Notes', exact: true }).click()
  const panel = page.getByRole('region', { name: 'Exact-Need facts and operator status' })
  const enterSchedule = async (correction: boolean) => {
    await panel.getByLabel('Fact type').selectOption('power_schedule')
    await panel.getByLabel('Reporter name').fill('Synthetic operator')
    await panel.getByLabel('Reporter organization').fill('Example Owner')
    await panel.getByLabel('Reporter role').fill('Project Engineer')
    await panel.getByLabel('Phase name').fill(correction ? 'commissioning-revised' : 'commissioning')
    await panel.getByLabel('Start date').fill('2027-01-01')
    await panel.getByLabel('End date').fill('2027-02-01')
    await panel.getByLabel('Demand minimum (MW)').fill(correction ? '11' : '10')
    await panel.getByLabel('Demand maximum (MW)').fill('12')
    await panel.getByLabel('Demand basis').fill('Owner-described commissioning demand')
    await panel.getByLabel('Supply coverage').selectOption('partial')
    await panel.getByLabel('Coverage basis').fill('Utility date remains subject to confirmation')
    const fillPhase = async (ordinal: number, start: string, end: string) => {
      const phase = panel.getByRole('group', { name: `Demand phase ${ordinal}` })
      await phase.getByLabel('Start date').fill(start)
      await phase.getByLabel('End date').fill(end)
      await phase.getByLabel('Demand minimum (MW)').fill('10')
      await phase.getByLabel('Demand maximum (MW)').fill('12')
      await phase.getByLabel('Demand basis').fill('Owner-described phased demand')
      await phase.getByLabel('Supply coverage').selectOption('partial')
      await phase.getByLabel('Coverage basis').fill('Other supply remains unconfirmed')
    }
    await panel.getByRole('button', { name: 'Add demand phase' }).click()
    await panel.getByRole('button', { name: 'Add demand phase' }).click()
    await panel.getByRole('button', { name: 'Add demand phase' }).click()
    await fillPhase(2, '2027-02-01', '2027-03-01')
    await fillPhase(3, '2027-03-01', '2027-04-01')
    await fillPhase(4, '2027-04-01', '2027-05-01')
    await panel.getByRole('group', { name: 'Demand phase 3' }).getByRole('button', { name: 'Remove phase' }).click()
    await panel.getByRole('button', { name: 'Add demand phase' }).click()
    await fillPhase(4, '2027-05-01', '2027-06-01')
    await panel.getByRole('button', { name: 'Add supply entry' }).click()
    const utility = panel.getByRole('group', { name: 'Supply entry 1' })
    await utility.getByLabel('Entry name').fill('utility-service')
    await utility.getByLabel('Start date').fill('2027-01-15')
    await utility.getByLabel('End date').fill('2027-02-01')
    await utility.getByLabel('Supply minimum (MW)').fill('4')
    await utility.getByLabel('Supply maximum (MW)').fill('5')
    await utility.getByLabel('Supply state').selectOption('committed')
    await utility.getByLabel('Suitability').selectOption('suitable')
    await utility.getByLabel('Supply source kind').selectOption('utility_grid')
    await utility.getByLabel('Service-ready / energization date').fill('2027-01-15')
    await utility.getByLabel('Date basis').fill('Utility service letter')
    await utility.getByLabel('Supply basis').fill('Utility committed service')
    await panel.getByRole('button', { name: 'Add supply entry' }).click()
    const proposed = panel.getByRole('group', { name: 'Supply entry 2' })
    await proposed.getByLabel('Entry name').fill('future-utility-option')
    await proposed.getByLabel('Start date').fill('2027-03-01')
    await proposed.getByLabel('End date').fill('2027-04-01')
    await proposed.getByLabel('Supply minimum (MW)').fill('4')
    await proposed.getByLabel('Supply maximum (MW)').fill('5')
    await proposed.getByLabel('Supply state').selectOption('proposed')
    await proposed.getByLabel('Suitability').selectOption('suitable')
    await proposed.getByLabel('Supply source kind').selectOption('utility_grid')
    await proposed.getByLabel('Service-ready / energization date').fill('2027-03-15')
    await proposed.getByLabel('Date basis').fill('Draft utility schedule')
    await proposed.getByLabel('Supply basis').fill('Proposed future grid service')
    await panel.getByRole('button', { name: 'Add supply entry' }).click()
    const generator = panel.getByRole('group', { name: 'Supply entry 3' })
    await generator.getByLabel('Entry name').fill('supply-3')
    await generator.getByLabel('Start date').fill('2027-01-01')
    await generator.getByLabel('End date').fill('2027-02-01')
    await generator.getByLabel('Supply minimum (MW)').fill('1')
    await generator.getByLabel('Supply maximum (MW)').fill('1')
    await generator.getByLabel('Supply state').selectOption('hypothetical')
    await generator.getByLabel('Suitability').selectOption('suitable')
    await generator.getByLabel('Supply source kind').selectOption('onsite')
    await generator.getByLabel('Service-ready / energization date').fill('2027-01-15')
    await generator.getByLabel('Date basis').fill('Hypothetical generator schedule')
    await generator.getByLabel('Supply basis').fill('Hypothetical generation')
    await proposed.getByRole('button', { name: 'Remove supply entry' }).click()
    await panel.getByRole('button', { name: 'Add supply entry' }).click()
    const replacement = panel.getByRole('group', { name: 'Supply entry 3' })
    await replacement.getByLabel('Start date').fill('2027-03-01')
    await replacement.getByLabel('End date').fill('2027-04-01')
    await replacement.getByLabel('Supply minimum (MW)').fill('4')
    await replacement.getByLabel('Supply maximum (MW)').fill('5')
    await replacement.getByLabel('Supply state').selectOption('proposed')
    await replacement.getByLabel('Suitability').selectOption('suitable')
    await replacement.getByLabel('Supply source kind').selectOption('utility_grid')
    await replacement.getByLabel('Service-ready / energization date').fill('2027-03-15')
    await replacement.getByLabel('Date basis').fill('Draft utility schedule')
    await replacement.getByLabel('Supply basis').fill('Proposed future grid service')
    await panel.getByLabel('Basis', { exact: true }).fill('Operator-reported phased work plan')
    await panel.locator('form').getByLabel('Source reference', { exact: true }).last().fill('utility-letter-1')
    if (correction) await panel.getByLabel('Predecessor fact version (for correction)').selectOption({ label: 'v2 · power_schedule · accepted' })
  }
  await enterSchedule(false)
  await panel.getByRole('button', { name: 'Save fact draft' }).click()
  await expect(panel.getByText(/Draft persisted and confirmed/)).toBeVisible()
  const savedSchedule = postedValues.at(-1)?.value
  expect(savedSchedule.phases[0]).toMatchObject({ phase_id: 'commissioning', mw_min: '10' })
  expect(savedSchedule.supplies).toMatchObject([{ supply_id: 'utility-service', source_kind: 'utility_grid', service_ready_date: '2027-01-15' }, { supply_id: 'supply-3', state: 'hypothetical' }, { supply_id: 'supply-1', state: 'proposed', source_kind: 'utility_grid', service_ready_date: '2027-03-15' }])
  expect(new Set(savedSchedule.phases.map((phase: { phase_id: string }) => phase.phase_id)).size).toBe(savedSchedule.phases.length)
  expect(new Set(savedSchedule.supplies.map((supply: { supply_id: string }) => supply.supply_id)).size).toBe(savedSchedule.supplies.length)
  expect(savedSchedule.phases.map((phase: { phase_id: string }) => phase.phase_id)).toContain('phase-3')
  expect(savedSchedule.supplies.map((supply: { supply_id: string }) => supply.supply_id)).toContain('supply-3')
  expect(savedSchedule.supplies.map((supply: { supply_id: string }) => supply.supply_id)).toContain('supply-1')
  await panel.getByLabel('Reason for decision').fill('Schedule confirmed for test')
  await panel.getByRole('button', { name: 'Accept fact' }).click()
  await expect(panel.getByText('power_schedule · accepted · User-confirmed')).toBeVisible()

  await enterSchedule(true)
  await panel.getByRole('button', { name: 'Save fact draft' }).click()
  await expect(panel.getByText(/Draft persisted and confirmed/)).toBeVisible()
  await panel.getByLabel('Reason for decision').fill('Corrected commissioning estimate')
  await panel.getByRole('button', { name: 'Record correction' }).click()
  await expect(panel.getByText('power_schedule · corrected · User-confirmed')).toBeVisible()
  await panel.getByLabel('Reason for retraction').fill('Source schedule withdrawn')
  const corrected = panel.locator('article').filter({ hasText: 'power_schedule · corrected · User-confirmed' })
  await corrected.getByRole('button', { name: 'Retract this accepted version' }).click()
  await expect(panel.getByText('power_schedule · retracted · Retracted')).toBeVisible()
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
  await page.goto('/?view=workspace')
  const panel = page.locator('.wh-changes')
  await page.getByRole('button', { name: 'Notifications' }).click()
  await panel.locator(':scope > details > summary').click()
  const link = panel.getByRole('button', { name: /Synthetic Facility · Austin, TX · demand/ })
  await link.click()
  await expect(page.getByRole('heading', { name: 'Test data center' })).toBeVisible()
  await expect(page.getByText(/Signal/).first()).toBeVisible()
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
  await page.goto('/?view=workspace')
  const panel = page.locator('.wh-changes')
  await page.getByRole('button', { name: 'Notifications' }).click()
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
  await page.goto('/?view=workspace')
  await expect(page.getByRole('heading', { name: 'Opportunity Intelligence' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(900)
})

test('tablet direct selection keeps detail and header reachable and restores the queue', async ({ page }) => {
  await page.setViewportSize({ width: 768, height: 1024 })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response() }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: need }))
  await page.goto('/?view=workspace&need=need-a')
  const identity = page.getByRole('heading', { name: 'Test data center' })
  await expect(identity).toBeVisible()
  const bounds = await identity.boundingBox()
  expect(bounds!.y).toBeGreaterThanOrEqual(0)
  expect(bounds!.y + bounds!.height).toBeLessThan(1024)
  for (const control of [page.getByRole('link', { name: 'GridLens home' }), page.getByRole('navigation', { name: 'Primary navigation' }), page.getByRole('textbox', { name: 'Search workspace' }), page.getByRole('button', { name: 'Notifications' }), page.locator('.wh-account > summary')]) {
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

for (const width of [768, 390]) {
  test(`Notifications reveals queue after repeated selection and preserves Back at ${width}px`, async ({ page }) => {
    const secondNeed = { ...need, id: 'need-b', project_id: 'project-b', name: 'Second data center' }
    const change = {
      event_key: `compact-change-${width}`, category: 'changed', title: 'Source changed',
      detail: 'Permit text was updated and needs review.', created_at: '2026-10-20T12:00:00Z',
      source_date: null, project_id: 'project-a', before_state: null, after_state: null,
      needs: [], sources: [],
    }
    await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
    await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response([need, secondNeed]) }))
    await page.route('**/api/opportunities/workspace/changes*', route => route.fulfill({ json: { ...emptyChanges, items: [change], total_unreviewed: 1, counts: { ...emptyChanges.counts, changed: 1 } } }))
    await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: need }))
    await page.route('**/api/opportunities/needs/need-b*', route => route.fulfill({ json: secondNeed }))
    await page.goto('/?view=workspace')
    await page.locator('[data-need-row="need-a"]').click()
    await expect(page.getByRole('heading', { name: 'Test data center' })).toBeVisible()
    await page.locator('[data-need-row="need-b"]').click()
    await expect(page.getByRole('heading', { name: 'Second data center' })).toBeVisible()
    await page.setViewportSize({ width, height: 900 })
    await page.getByRole('button', { name: 'Notifications' }).click()
    const list = page.locator('.wh-list')
    await expect(list).toBeVisible()
    const disclosure = page.locator('.wh-change-disclosure')
    await expect(disclosure).toHaveAttribute('open', '')
    await expect(disclosure).toContainText('Permit text was updated and needs review.')
    await expect(disclosure).toBeInViewport()
    await page.goBack()
    await expect(page.getByRole('heading', { name: 'Second data center' })).toBeVisible()
    await page.getByRole('button', { name: 'Notifications' }).click()
    await expect(list).toBeVisible()
    await expect(disclosure).toBeInViewport()
  })
}

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
  await page.goto('/?view=workspace&industry=gas_processing_plant')
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
  await page.goto('/?view=workspace')
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
  await page.goto('/?view=workspace')
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
    const source = { reference: 'evidence:test', title: 'Official project notice', url: 'https://example.test/project', source_date: '2026-10-20', assessed_at: '2026-10-22T12:00:00Z', retained_evidence_id: 'test', content_hash: 'a'.repeat(64), passage: 'Example Owner is developing the site.', extraction_method: 'Official notice', verification_status: 'Current retained support' }
    const card = {
      policy_version: 'opportunity-intelligence-v1', need_id: need.id, project_id: need.project_id,
      input_fingerprint: 'a'.repeat(64), qualification: 'Signal', disposition: 'RESEARCH',
      fields: [{ key: 'customer', label: 'Customer / end user', section: 'identity', value: 'Example Owner', status: 'Verified', basis: 'Current owner relationship.', sources: [source] }],
      contacts: [
        { claim_id: 'party', company: 'Example Owner', name: null, title: null, role: 'owner developer', responsibility: 'General company contact path', purchasing_authority: 'Requires confirmation for this power package', verified_at: '2026-10-24T18:04:00Z', methods: [{ kind: 'phone', value: '+1 512 555 0100', href: 'tel:+15125550100', source_url: source.url, verified_at: '2026-10-25T18:04:00Z' }], sources: [source] },
        { claim_id: 'role-only', company: 'Example Owner', name: 'Jordan Lee', title: 'Facilities Director', role: 'facilities', responsibility: 'Verified organizational responsibility', purchasing_authority: 'Requires confirmation for this power package', verified_at: '2026-10-24T18:04:00Z', methods: [], sources: [source] },
        { claim_id: 'unknown-date', company: 'Example Owner', name: 'Taylor Unknown', title: 'Operations Director', role: 'operations', responsibility: 'Verified organizational responsibility', purchasing_authority: 'Requires confirmation for this power package', verified_at: '2026-10-24T18:04:00Z', methods: [{ kind: 'email', value: 'unknown@example.test', href: 'mailto:unknown@example.test', verified_at: 'invalid-date' }], sources: [] },
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
    await page.route('**/api/power-needs/*/title', route => route.fulfill({ json: { status: 'disabled', result: null, citations: [] } }))
    await page.route('**/api/power-needs/*/brief', route => route.fulfill({ json: { status: 'disabled', result: null, citations: [] } }))
    let researchBody: unknown
    await page.route('**/api/commercial/triage/need-a/autonomous-research', route => { researchBody = route.request().postDataJSON(); return route.fulfill({ json: { items: [{ id: 'queued' }] } }) })
    await page.goto('/?view=workspace&need=need-a')
    const panel = page.getByRole('region', { name: 'Commercial intelligence card', exact: true })
    await expect(panel).toBeVisible()
    await page.getByRole('button', { name: 'Overview', exact: true }).click()
    await page.locator('.wh-provenance-disclosure summary').click()
    await expect(page.locator('.wh-provenance-disclosure')).toContainText('Integrity inspection')
    await expect(page.locator('.wh-provenance-disclosure')).toContainText('Confirm the power package owner')
    const priority = page.getByRole('region', { name: 'Priority explanation' })
    await expect(priority).toContainText('Canonical rank score: 8 · rank-v1')
    await expect(priority).toContainText('Known industrial asset')
    await expect(panel.getByText('Example Owner', { exact: true }).first()).toBeVisible()
    await expect(panel.getByRole('link', { name: 'Call +1 512 555 0100' })).toHaveAttribute('href', 'tel:+15125550100')
    const emailLinks = panel.locator('a[href^="mailto:"]')
    await expect(emailLinks).toHaveCount(1)
    await expect(emailLinks).toHaveAttribute('href', 'mailto:unknown@example.test')
    const methodContact = panel.locator('.ic-contact').first()
    await methodContact.getByText('Responsibility, authority & evidence').click()
    await expect(methodContact).toContainText('Verified 10/25/2026')
    await expect(methodContact).not.toContainText('Verified 10/24/2026')
    await expect(methodContact).toContainText('Requires confirmation for this power package.')
    await expect(methodContact).not.toContainText('Purchasing authority confirmed')
    const roleContact = panel.locator('.ic-contact').nth(1)
    await roleContact.getByText('Responsibility, authority & evidence').click()
    await expect(roleContact).toContainText('Role/source checked 10/22/2026')
    await expect(roleContact).not.toContainText('Verified 10/24/2026')
    const unknownDateContact = panel.locator('.ic-contact').nth(2)
    await unknownDateContact.getByText('Responsibility, authority & evidence').click()
    await expect(unknownDateContact).not.toContainText('Verified 10/24/2026')
    await expect(unknownDateContact).not.toContainText('Role/source checked')
    await expect(page.locator('.wh-completeness')).toContainText('1/2')
    await panel.getByRole('button', { name: 'Research missing information' }).click()
    await expect.poll(() => researchBody).toEqual({ force: false, complete_intelligence: true })
    await expect(panel.getByRole('status')).toContainText('Targeted research queued')
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
    await expect(page.getByRole('heading', { name: 'Opportunity Intelligence' })).toBeVisible()
  })
}
