import { expect, test } from '@playwright/test'

const need = {
  id: 'need-a', project_id: 'project-a', name: 'Test data center', location: 'Austin, TX', tier: 'Signal', workflow_status: 'New', activity: 'construction',
  rationale: 'A retained project filing supports investigation.', signal_evidence_state: 'active', conflict_state: 'Not assessed', required_mw: null, supply: 'Unknown', start_window: null, duration: null,
  evidence: [{ source_id: 'city-permit', document_number: 'P-1', title: 'Permit filing', url: 'https://example.test/permit', published_at: null, retrieved_at: '2026-10-18T10:00:00Z', event_date: null, event_date_label: 'Event date', source_origin: 'City permits', extraction_location: 'Page 1', abstract: 'Construction filing.' }],
  missing_facts: ['Activity-specific load', 'Suitable utility supply'], project_identity_key: 'test', commercial_disposition: 'RESEARCH', commercial_reason: 'Load and supply remain unknown.', commercial_next_question: 'Who owns the electrical scope?', commercial_next_action: 'Research the project contractor.', commercial_organization: null,
} as any
const response = (items = [need]) => ({ items, total: items.length, counts: { action_now: 0, research: items.length, watch: 0, reject: 0 }, offset: 0, limit: 25, next_offset: null, cohort_token: 'cohort-a', count_unit: 'power needs', changes_available: false })

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
