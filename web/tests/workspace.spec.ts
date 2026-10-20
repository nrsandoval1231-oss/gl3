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
  await expect(page.getByRole('heading', { name: 'Power needs' })).toBeVisible()
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
  await expect(page.getByRole('heading', { name: 'Power needs' })).toBeVisible()
  await page.getByLabel('Geography (exact match)').fill('Austin, TX')
  await expect.poll(() => requests.some(url => url.searchParams.get('geography') === 'Austin, TX')).toBeTruthy()
  await expect(page.getByRole('button', { name: /Test data center/ })).toBeVisible()
  await page.getByRole('button', { name: /Test data center/ }).click()
  await expect(page.getByRole('heading', { name: 'Test data center' })).toBeVisible()
  await expect(page.locator('.wh-facts')).toContainText('Evidence status unavailable')
  await expect(page.locator('.wh-detail-head [role="status"]')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Unknowns' })).toBeVisible()
  await page.getByRole('button', { name: 'Unknowns' }).click()
  await expect(page.getByText(/Buying authority: not evaluated in this summary/)).toBeVisible()
  await page.getByRole('button', { name: 'Overview' }).click()
  expect(await page.locator('.wh-table tbody tr:first-child td:nth-child(2)').evaluate(el => getComputedStyle(el).whiteSpace)).toBe('nowrap')
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(1280)
  await expect(page.getByText('A numerical gap is unavailable')).toHaveCount(0)
  await page.getByRole('button', { name: 'Evidence' }).click()
  await expect(page.getByRole('link', { name: 'Permit filing' })).toBeVisible()
  await page.getByRole('button', { name: /Research the project contractor/ }).click()
  await expect(page).toHaveURL(/section=next-steps/)
  await page.getByRole('button', { name: /Back to power needs/ }).click()
  await expect(page.getByRole('heading', { name: 'Power needs' })).toBeVisible()
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
  await expect(rowButton).toContainText('Source record: Austin permit 2026-127192 EP')
  await rowButton.click()
  await expect(page.getByRole('heading', { name: 'Current project electrician · contractor' })).toBeVisible()
  await expect(page.locator('.wh-detail-head')).toContainText('Source record: Austin permit 2026-127192 EP')
  await expect(page.locator('.wh-detail-head')).not.toContainText('JLC Electrical Contractor corp · contractor')
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
  await expect(page.locator('.wh-detail-head')).toContainText('Source record: Austin permit 2026-127192 EP')
  await expect(page.locator('.wh-detail-head')).not.toContainText('Historical Owner LLC')
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Temporary power · Austin, TX' })).toBeVisible()
  await expect(page.locator('.wh-detail-head')).toContainText('Source record: Austin permit 2026-127192 EP')
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
  await expect(page.getByRole('heading', { name: 'Power needs' })).toBeVisible()
})

test('mobile Next action opens detail and Back restores the selected row focus', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response() }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: need }))
  await page.goto('/?view=workspace')
  await page.getByRole('button', { name: 'Research the project contractor.' }).click()
  await expect(page.getByRole('button', { name: 'Next steps', exact: true })).toBeInViewport()
  await expect(page.getByRole('heading', { name: 'Record call facts' })).toBeVisible()
  await page.getByRole('button', { name: /Back to power needs/ }).click()
  await expect(page.getByRole('button', { name: /Test data center/ })).toBeFocused()
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
  await page.getByRole('button', { name: /Austin permit 2026-127192/ }).click()
  await page.getByRole('button', { name: /Research the project contractor/ }).click()
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
  const briefIndex = await brief.evaluate(el => el.compareDocumentPosition(document.querySelector('.wh-detail-content h3')!) & Node.DOCUMENT_POSITION_FOLLOWING)
  expect(briefIndex).toBeTruthy()
  await expect(page.getByRole('heading', { name: 'Record call facts' })).toBeVisible()
})

test('Research link carries the selected need into the research queue', async ({ page }) => {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response() }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: need }))
  await page.route('**/api/commercial/triage?*', route => route.fulfill({ json: { items: [], total: 0, offset: 0, limit: 50 } }))
  await page.goto('/?view=workspace&need=need-a')
  await page.getByRole('link', { name: 'Research' }).click()
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
  await page.locator('.wh-action').nth(0).click()
  await expect.poll(() => oldRequestSeen).toBeTruthy()
  if (resolved) await expect(page.getByRole('region', { name: 'Call preparation' })).toContainText('Old project contact')
  await page.locator('.wh-action').nth(1).click()
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
  await expect(page.locator('.wh-detail-head')).toContainText('ACTION NOW')
  await expect(page.locator('.wh-detail-head')).not.toContainText('Stale disposition')
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
  await expect(page.locator('.wh-detail-head')).toContainText('ACTION NOW')
  await page.getByRole('textbox', { name: 'Search opportunities' }).fill('new generation')
  await expect.poll(() => requests.some(url => url.searchParams.get('search') === 'new generation')).toBeTruthy()
  await expect(page.getByRole('heading', { name: 'Test data center' })).toBeVisible()
  await expect(page.locator('.wh-detail-head')).toContainText('Disposition unavailable')
  await expect(page.locator('.wh-detail-head')).not.toContainText('ACTION NOW')
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
  await page.getByRole('textbox', { name: 'Search opportunities' }).fill('Searchable Austin project')
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
  await expect(page.getByRole('heading', { name: 'Power needs' })).toBeVisible()
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
  await expect(page.getByRole('button', { name: 'Enrich title' })).toBeVisible()
  await expect.poll(() => statusReads).toBe(1)
  await page.getByRole('button', { name: 'Enrich title' }).click()
  await expect(page.getByRole('heading', { name: enrichedTitle })).toBeVisible({ timeout: 8000 })
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
  await page.getByRole('button', { name: 'Enrich title' }).click()
  await expect.poll(() => Boolean(releasePost)).toBeTruthy()
  await page.locator('[data-need-row="need-b"]').click()
  await expect(page.getByRole('heading', { name: 'Second project' })).toBeVisible()
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
  await page.getByRole('button', { name: 'Enrich title' }).click()
  const titleRegion = page.getByRole('region', { name: 'Evidence-grounded title' })
  await expect(titleRegion).toContainText('Title status could not be checked', { timeout: 8000 })
  await expect(page.getByRole('button', { name: 'Enrich title' })).toBeDisabled()
  await page.getByRole('button', { name: 'Retry status' }).click()
  await expect.poll(() => statusReads).toBeGreaterThan(2)
  await expect.poll(() => posts).toBe(1)
  await expect(titleRegion).toContainText('Title request pending.')
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
  await expect(page.getByRole('button', { name: 'Retry status' })).toBeVisible()
  await page.getByRole('button', { name: 'Retry status' }).click()
  await expect.poll(() => Boolean(releaseRetry)).toBeTruthy()
  await page.locator('[data-need-row="need-b"]').click()
  await expect(page.getByRole('heading', { name: 'Second project' })).toBeVisible()
  await page.locator('[data-need-row="need-a"]').click()
  await expect(page.getByRole('heading', { name: 'Test data center' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Retry status' })).toBeEnabled()
  releaseRetry?.()
  await page.getByRole('button', { name: 'Retry status' }).click()
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
  const titleRegion = page.getByRole('region', { name: 'Evidence-grounded title' })
  await expect(titleRegion).toContainText('status could not be checked')
  await expect(page.getByRole('button', { name: 'Enrich title' })).toBeDisabled()
  await page.getByRole('button', { name: 'Retry status' }).click()
  await expect.poll(() => titleReads).toBe(2)
  await expect.poll(() => titlePosts).toBe(0)
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
  await page.getByRole('button', { name: 'Refresh title' }).click()
  await expect.poll(() => listReads).toBeGreaterThan(1)
  await expect(page.getByRole('heading', { name: 'Temporary power - Austin, TX' })).toBeVisible()
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
  await expect(page.getByRole('region', { name: 'Evidence-grounded title' })).toContainText('Saved title is stale')
  await page.locator('[data-need-row="need-b"]').click()
  await expect(page.getByRole('heading', { name: freshTitle })).toBeVisible()
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
  await expect(page.getByRole('heading', { name: 'Power needs' })).toBeVisible()
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
  await page.getByLabel('Geography (exact match)').fill('Old')
  await page.getByLabel('Geography (exact match)').fill('New')
  await expect(page.getByRole('button', { name: /Current result/ })).toBeVisible()
  resolveOld()
  await expect(page.getByRole('button', { name: /Stale result/ })).toHaveCount(0)
})

test('a failed workspace filter hides rows, counts, and pagination from the prior cohort', async ({ page }) => {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => {
    const geography = new URL(route.request().url()).searchParams.get('geography')
    if (geography === 'Houston') return route.fulfill({ status: 503, json: { detail: 'workspace unavailable' } })
    return route.fulfill({ json: response([{ ...need, name: 'Austin retained row' }]) })
  })
  await page.goto('/?view=workspace&geography=Austin')
  await expect(page.getByRole('button', { name: /Austin retained row/ })).toBeVisible()
  await page.getByLabel('Geography (exact match)').fill('Houston')
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByRole('button', { name: /Austin retained row/ })).toHaveCount(0)
  await expect(page.locator('.wh-briefbar')).toContainText('Current results unavailable')
  await expect(page.locator('.wh-briefbar')).toContainText('—')
  await expect(page.locator('.wh-paging')).toContainText('of —')
})

test('canonical priority score and reasons are explained separately from disposition', async ({ page }) => {
  const ranked = { ...need, rank_score: 8, rank_reasons: ['Near-term start', 'Supported project scale'], rank_version: 'rank-v1' }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response([ranked]) }))
  await page.route('**/api/opportunities/needs/need-a*', route => route.fulfill({ json: ranked }))
  await page.goto('/?view=workspace')
  await expect(page.locator('[data-need-row="need-a"]')).toContainText('Priority 8 · Near-term start; Supported project scale')
  await page.locator('[data-need-row="need-a"]').click()
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
  const panel = page.getByRole('region', { name: 'Material changes' })
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
  const panel = page.getByRole('region', { name: 'Material changes' })
  await panel.locator('summary').click()
  const link = panel.getByRole('button', { name: /Synthetic Facility · Austin, TX · Lead/ })
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
  const panel = page.getByRole('region', { name: 'Material changes' })
  await panel.locator('summary').click()
  await panel.getByRole('button', { name: /Synthetic Facility · Austin, TX · Lead/ }).click()
  await expect(page.getByRole('alert')).toContainText('GridLens could not complete this request (503)')
  await expect(page.locator('.wh-detail')).not.toContainText('Lead')
  expect(historicalReads).toBe(0)
})

test('tablet workspace has no horizontal overflow and retains readable layout', async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 900 })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: response() }))
  await page.goto('/?view=workspace')
  await expect(page.getByRole('heading', { name: 'Power needs' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(900)
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
  await page.getByRole('button', { name: 'Power gap' }).click()
  await expect(page.getByText(/Qualified remaining gap: 1–4 MW/)).toBeVisible()
  await page.getByRole('button', { name: /Back to power needs/ }).click()
  await page.getByRole('button', { name: /Unknown power need/ }).click()
  await page.getByRole('button', { name: 'Power gap' }).click()
  await expect(page.getByText('Supply unknown or no supported remaining gap is available for this need.')).toBeVisible()
  await page.getByRole('button', { name: /Back to power needs/ }).click()
  await page.getByRole('button', { name: /Conflicted power need/ }).click()
  await page.getByRole('button', { name: 'Power gap' }).click()
  await expect(page.getByText('Supply unknown or no supported remaining gap is available for this need.')).toBeVisible()
  await expect(page.locator('.wh-detail-head [role="status"]')).toHaveCount(1)
})
