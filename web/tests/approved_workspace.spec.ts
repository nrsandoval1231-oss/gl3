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
    { key: 'energization', label: 'Utility energization', section: 'power', value: 'North Austin substation energization targeted for Q3 2027 after feeder acceptance', status: 'Reported', basis: `The notice attributes the target to the utility coordination milestone; retained source record ${'TXPUCT2026UTILITYCOORDINATIONREFERENCE'.repeat(3)}.`, sources: [source] },
  ],
  contacts: [{ claim_id: 'contact-a', company: 'A very long customer organization name for a multi-phase advanced manufacturing and industrial infrastructure development company', name: 'Alexandra Longname-Sample', title: 'Director, Infrastructure Programs', role: 'Owner developer', responsibility: 'Source-supported project involvement', purchasing_authority: 'Requires confirmation for this power package', methods: [{ kind: 'phone', value: '+1 512 555 0100', href: 'tel:+15125550100', source_url: source.url }], sources: [source] }],
  next_contact_path: 'Confirm which organization owns temporary power procurement for this specific multi-phase construction and commissioning package.',
  next_action: 'Verify the activity-specific power window and remaining utility capacity with the source-listed organization.',
  research_gaps: [{ key: 'start', label: 'Power needed by', section: 'power', value: null, status: 'Research in progress', basis: 'No supported date is available yet.', research_category: 'timing', research_status: 'NOT_SCHEDULED', sources: [] }],
  completeness: { supported: 3, total: 8, percent: 38, basis: 'Independent of qualification' },
  last_intelligence_update: '2026-10-20T10:00:00Z', power_gap: { remaining_mw: '3.25–6.75 MW of potential residual bridge power during phase-one construction', status: 'reported_with_unresolved_supply_conflict' }, evidence: [source], research_enabled: true,
}
const needA = {
  id: 'need-a', project_id: 'project-a', name: 'North Austin Advanced Manufacturing Campus Construction and Electrical Infrastructure Development Project',
  browse_title: 'North Austin Advanced Manufacturing Campus Construction and Electrical Infrastructure Development Project', location: 'Austin, TX', tier: 'Signal',
  workflow_status: 'New', activity: 'construction', rationale: 'A retained project filing supports investigation.',
  signal_evidence_state: 'active', conflict_state: 'Not assessed', required_mw: '12.75–19.5 MW for the phased temporary construction power package', supply: 'Unknown', start_window: 'Q3 2027 after substation feeder acceptance, followed by staged construction and commissioning', duration: '24–36 months across the staged construction and commissioning sequence',
  evidence: [{ source_id: 'city-permit', document_number: 'P-1', title: 'Retained site development notice', url: source.url, published_at: null, retrieved_at: '2026-10-20T10:00:00Z', event_date: '2026-10-19', event_date_label: 'Event date', source_origin: 'City permits', extraction_location: 'Page 1', abstract: 'The notice identifies a site project and its electrical contractor.', content_hash: 'a'.repeat(64), assessment_current: true }],
  missing_facts: ['Activity-specific load', 'Suitable utility supply'], project_identity_key: 'project-a',
  commercial_disposition: 'RESEARCH', commercial_reason: 'The retained filing supports project investigation while load and suitable supply remain unknown.',
  commercial_next_question: 'Who owns the electrical scope?', commercial_next_action: 'Confirm the power package and expected timing.', commercial_organization: 'A very long customer organization name for a multi-phase advanced manufacturing and industrial infrastructure development company',
  intelligence_card: card,
}
const needB = { ...needA, id: 'need-b', project_id: 'project-b', name: 'Second supported power need', browse_title: 'Second supported power need', required_mw: '', start_window: '', duration: '', intelligence_card: { ...card, need_id: 'need-b', project_id: 'project-b', power_gap: { remaining_mw: '', status: '' }, fields: card.fields.filter(field => !['facility_demand', 'energization'].includes(field.key)).map(field => field.key === 'customer' ? { ...field, value: 'Example Customer' } : field.key === 'project' ? { ...field, value: 'Second supported power need' } : field), contacts: [], evidence: [] }, evidence: needA.evidence }

test('approved intelligence dashboard preserves evidence, verified actions, selection history, and mobile width', async ({ page }) => {
  let providerPosts = 0
  const workspace = (items: typeof needA[], total = items.length) => ({ items, total, counts: { action_now: 0, research: total, watch: 0, reject: 0 }, offset: 0, limit: 25, next_offset: null, cohort_token: 'approved-cohort', count_unit: 'power needs', changes_available: false })
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (request.method() === 'POST') providerPosts += 1
    if (path === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (path === '/api/opportunities/workspace') return route.fulfill({ json: workspace([needA, needB], 1659) })
    if (path === '/api/opportunities/workspace/changes') return route.fulfill({ json: { items: [], counts: { discovered: 0, changed: 0, promoted: 0, closed: 0, review_exception: 0 }, total_unreviewed: 0, offset: 0, limit: 50, next_offset: null, baseline_identity: 'test', token: 'test', source_health_exceptions: [] } })
    if (path === '/api/opportunities/needs/need-a') return route.fulfill({ json: needA })
    if (path === '/api/opportunities/needs/need-b') return route.fulfill({ json: needB })
    if (/\/power-needs\/[^/]+\/(brief|title)$/.test(path)) return route.fulfill({ json: { status: 'disabled', result: null, citations: [] } })
    return route.fulfill({ json: [] })
  })

  await page.setViewportSize({ width: 1280, height: 720 })
  await page.goto('/?view=workspace')
  await expect(page.locator('.wh-list')).toBeVisible()
  // Reserve the scrollbar gutter that Windows Chrome allocates in this list.
  await page.locator('.wh-list').evaluate(element => { element.style.scrollbarGutter = 'stable' })
  await expect(page.locator('.wh-queue-heading > span')).toHaveText('1659 opportunities')
  await expect(page.locator('.wh-sort select')).toHaveValue('priority')
  const assertQueueToolbarFits = async () => {
    const geometry = await page.evaluate(() => {
      const list = document.querySelector<HTMLElement>('.wh-list')!
      const tools = document.querySelector<HTMLElement>('.wh-tools > summary')!
      const rect = tools.getBoundingClientRect()
      const listRect = list.getBoundingClientRect()
      return {
        scrollWidth: list.scrollWidth,
        clientWidth: list.clientWidth,
        toolsRight: rect.right,
        visibleRight: listRect.left + list.clientLeft + list.clientWidth,
      }
    })
    expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.clientWidth)
    expect(geometry.toolsRight).toBeLessThanOrEqual(geometry.visibleRight)
  }
  await assertQueueToolbarFits()
  await page.locator('.wh-tools > summary').click()
  await expect(page.locator('.wh-tool-content')).toBeVisible()
  await page.locator('.wh-filter-disclosure > summary').click()
  await expect(page.getByLabel('Tier')).toBeVisible()
  await assertQueueToolbarFits()
  await page.locator('.wh-tools > summary').click()
  for (const width of [1321, 1330, 1399, 1440]) {
    await page.setViewportSize({ width, height: 720 })
    await assertQueueToolbarFits()
  }
  await page.locator('[data-need-row="need-a"]').click()
  await expect(page.getByRole('heading', { name: 'A very long customer organization name for a multi-phase advanced manufacturing and industrial infrastructure development company' })).toBeVisible()
  await page.setViewportSize({ width: 1280, height: 800 })
  const baselineCss = await page.addStyleTag({ content: '.wh-record-hero>*{min-width:auto!important}.wh-record-identity{flex:0 1 auto!important}.wh-record-qualification{flex:0 1 auto!important}.wh-completeness{flex:0 1 auto!important}.wh-record-qualification>span,.wh-completeness>span{overflow-wrap:normal!important}.wh-metric small{overflow-wrap:normal!important}' })
  await page.screenshot({ path: '../.agent/artifacts/PRODUCTION-M1-UI/baseline-long-values-1280x800.png', fullPage: false })
  const baselineHero = await page.evaluate(() => {
    const hero = document.querySelector<HTMLElement>('.wh-record-hero')!
    const detail = document.querySelector<HTMLElement>('.wh-detail')!.getBoundingClientRect()
    const metricCards = [...document.querySelectorAll<HTMLElement>('.wh-metric')]
    return { scrollWidth: hero.scrollWidth, clientWidth: hero.clientWidth, pageWidth: document.documentElement.scrollWidth, children: [...hero.children].map(child => ({ scrollWidth: (child as HTMLElement).scrollWidth, clientWidth: (child as HTMLElement).clientWidth })), metricCards: metricCards.map(card => { const basis = card.querySelector<HTMLElement>('small')!; return { cardScrollWidth: card.scrollWidth, cardClientWidth: card.clientWidth, basisScrollWidth: basis.scrollWidth, basisClientWidth: basis.clientWidth, left: card.getBoundingClientRect().left, right: card.getBoundingClientRect().right } }), detailLeft: detail.left, detailRight: detail.right }
  })
  console.log(`baseline hero geometry: ${JSON.stringify(baselineHero)}`)
  expect(baselineHero.metricCards.some(card => card.basisScrollWidth > card.basisClientWidth)).toBe(true)
  await baselineCss.evaluate(element => (element as HTMLElement).remove())
  const desktopDetail = await page.evaluate(() => {
    const rect = (selector: string) => document.querySelector<HTMLElement>(selector)!.getBoundingClientRect()
    const detail = document.querySelector<HTMLElement>('.wh-detail')!
    const hero = rect('.wh-record-hero')
    const heroContent = [...document.querySelectorAll<HTMLElement>('.wh-record-hero > *')].map(element => ({ left: element.getBoundingClientRect().left, right: element.getBoundingClientRect().right, top: element.getBoundingClientRect().top, bottom: element.getBoundingClientRect().bottom, height: element.scrollHeight, client: element.clientHeight }))
    const metrics = rect('.wh-metrics')
    const detailRect = detail.getBoundingClientRect()
    const actions = [...document.querySelectorAll<HTMLElement>('.wh-record-actions button')].map(element => element.getBoundingClientRect())
    return { pageWidth: document.documentElement.scrollWidth, detailWidth: detail.clientWidth, detailScrollWidth: detail.scrollWidth, detailRect, hero, heroContent, actions: actions.map(({ left, right }) => ({ left, right })), metrics, metricCount: document.querySelectorAll('.wh-metric').length }
  })
  expect(desktopDetail.pageWidth).toBeLessThanOrEqual(1280)
  expect(desktopDetail.detailScrollWidth).toBeLessThanOrEqual(desktopDetail.detailWidth)
  expect(desktopDetail.metricCount).toBe(5)
  for (const child of desktopDetail.heroContent) {
    expect(child.height).toBeLessThanOrEqual(child.client)
    expect(child.left).toBeGreaterThanOrEqual(desktopDetail.hero.left)
    expect(child.right).toBeLessThanOrEqual(desktopDetail.hero.right)
    expect(child.top).toBeGreaterThanOrEqual(desktopDetail.hero.top)
    expect(child.bottom).toBeLessThanOrEqual(desktopDetail.hero.bottom)
  }
  for (const action of desktopDetail.actions) {
    expect(action.left).toBeGreaterThanOrEqual(desktopDetail.detailRect.left)
    expect(action.right).toBeLessThanOrEqual(desktopDetail.detailRect.right)
  }
  expect(desktopDetail.metrics.left).toBeGreaterThanOrEqual(0)
  expect(desktopDetail.metrics.right).toBeLessThanOrEqual(1280)
  const metricBounds = await page.locator('.wh-metric').evaluateAll(cards => cards.map(card => {
    const rect = card.getBoundingClientRect()
    return { label: card.querySelector<HTMLElement>('.wh-metric-label')!, value: card.querySelector<HTMLElement>('strong')!, basis: card.querySelector<HTMLElement>('small')!, rect: { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom } }
  }).map(({ label, value, basis, rect }) => ({
    cardFits: label.closest<HTMLElement>('.wh-metric')!.scrollWidth <= label.closest<HTMLElement>('.wh-metric')!.clientWidth,
    valueWidth: value.clientWidth,
    labelFits: label.scrollWidth <= label.clientWidth, valueFits: value.scrollWidth <= value.clientWidth, basisFits: basis.scrollWidth <= basis.clientWidth,
    valueFontSize: Number.parseFloat(getComputedStyle(value).fontSize), wordBreak: getComputedStyle(value).wordBreak, overflowWrap: getComputedStyle(value).overflowWrap,
    wordFragmentCounts: (() => { const text = value.firstChild!; const content = value.textContent ?? ''; return [...content.matchAll(/\S+/g)].map(match => { const range = document.createRange(); range.setStart(text, match.index!); range.setEnd(text, match.index! + match[0].length); return range.getClientRects().length }) })(),
    rect, labelRect: label.getBoundingClientRect().toJSON(), valueRect: value.getBoundingClientRect().toJSON(), basisRect: basis.getBoundingClientRect().toJSON(),
  })))
  for (const metric of metricBounds) {
    expect(metric.cardFits && metric.labelFits && metric.valueFits && metric.basisFits).toBe(true)
    expect(metric.valueWidth).toBeGreaterThanOrEqual(110)
    expect(metric.valueFontSize).toBeGreaterThanOrEqual(13)
    expect(metric.wordBreak).toBe('normal')
    expect(metric.overflowWrap).toBe('break-word')
    expect(metric.wordFragmentCounts.every(count => count === 1)).toBe(true)
    expect(metric.rect.left).toBeGreaterThanOrEqual(desktopDetail.detailRect.left)
    expect(metric.rect.right).toBeLessThanOrEqual(desktopDetail.detailRect.right)
    for (const content of [metric.labelRect, metric.valueRect, metric.basisRect]) {
      expect(content.left).toBeGreaterThanOrEqual(metric.rect.left)
      expect(content.right).toBeLessThanOrEqual(metric.rect.right)
    }
  }
  await page.screenshot({ path: '../.agent/artifacts/PRODUCTION-M1-UI/selected-detail-1280x800.png', fullPage: false })
  await expect(page.getByText('Opportunity Intelligence', { exact: true })).toBeVisible()
  await expect(page.locator('.wh-metric')).toHaveCount(5)
  await expect(page.locator('.wh-metrics')).toContainText('184.75 MW across the complete facility buildout')
  const dashboard = page.getByRole('region', { name: 'Commercial intelligence card' })
  await expect(dashboard.getByText('A very long customer organization name for a multi-phase advanced manufacturing and industrial infrastructure development company').first()).toBeVisible()
  await expect(dashboard.getByRole('link', { name: 'Call +1 512 555 0100' })).toHaveAttribute('href', 'tel:+15125550100')
  await expect(dashboard.locator('a[href^="mailto:"]')).toHaveCount(0)
  await page.getByRole('button', { name: 'Research Gaps' }).click()
  await expect(page.getByText(/Buying authority: not evaluated in this summary/)).toBeVisible()
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  await expect(page.locator('.wh-evidence-heading')).toContainText('Retained records: 1 · Intelligence citations: 1.')
  await expect(page.locator('.wh-evidence-heading')).toContainText('Citations may refer to records listed here.')
  const sourceFilter = page.getByRole('combobox', { name: 'Filter evidence sources' })
  await expect(sourceFilter.locator('option')).toHaveText(['All sources', 'City permits', 'evidence:approved-fixture'])
  await sourceFilter.selectOption('evidence:approved-fixture')
  await expect(page.locator('.wh-evidence-table tbody tr')).toHaveCount(0)
  await expect(page.locator('.wh-card-sources article')).toHaveCount(1)
  await sourceFilter.selectOption('City permits')
  await expect(page.locator('.wh-evidence-table tbody tr')).toHaveCount(1)
  await expect(page.locator('.wh-card-sources article')).toHaveCount(0)
  await sourceFilter.selectOption('All sources')
  await expect(page.getByRole('link', { name: 'Retained site development notice' }).first()).toBeVisible()
  await page.locator('[data-need-row="need-b"]').click()
  await expect(page.getByRole('heading', { name: 'Example Customer' })).toBeVisible()
  await page.setViewportSize({ width: 1648, height: 928 })
  await page.locator('.wh-detail').evaluate(el => { el.scrollTop = 0 })
  const geometry = await page.evaluate(() => ({ header: document.querySelector('.wh-header')!.getBoundingClientRect(), rail: document.querySelector('.wh-list')!.getBoundingClientRect(), metrics: document.querySelector('.wh-metrics')!.getBoundingClientRect(), columns: document.querySelector('.ic-dashboard')!.getBoundingClientRect(), tabs: document.querySelector('.wh-tabs')!.getBoundingClientRect(), table: document.querySelector('.wh-evidence-table')!.getBoundingClientRect() }))
  expect(geometry.header.height).toBeCloseTo(58, 0)
  expect(geometry.rail.width).toBeCloseTo(412, 0)
  expect(geometry.metrics.top).toBeGreaterThanOrEqual(241)
  expect(geometry.metrics.top).toBeLessThanOrEqual(261)
  expect(geometry.columns.top).toBeGreaterThanOrEqual(367)
  expect(geometry.columns.top).toBeLessThanOrEqual(387)
  expect(geometry.columns.height).toBeGreaterThanOrEqual(374)
  expect(geometry.columns.height).toBeLessThanOrEqual(390)
  expect(geometry.tabs.top).toBeGreaterThanOrEqual(751)
  expect(geometry.tabs.top).toBeLessThanOrEqual(781)
  expect(geometry.table.top).toBeLessThanOrEqual(875)
  // Wider action labels model platform font metrics without changing production typography.
  const wideActionLabels = await page.addStyleTag({ content: '.wh-record-actions button { letter-spacing: 3px; }' })
  const actionGeometry = await page.evaluate(() => {
    const rect = (selector: string) => document.querySelector(selector)!.getBoundingClientRect()
    return { actions: rect('.wh-record-actions').toJSON(), toolbar: rect('.wh-identity-toolbar').toJSON(), share: rect('.wh-share').toJSON(), workflow: rect('.wh-primary-action').toJSON(), metrics: rect('.wh-metrics').toJSON() }
  })
  expect(actionGeometry.actions.width).toBeGreaterThan(225)
  expect(actionGeometry.share.top).toBeCloseTo(actionGeometry.workflow.top, 0)
  expect(actionGeometry.share.right).toBeLessThanOrEqual(actionGeometry.workflow.left)
  expect(actionGeometry.workflow.right).toBeLessThanOrEqual(1648)
  expect(actionGeometry.metrics.top).toBeLessThanOrEqual(261)
  await wideActionLabels.evaluate(element => (element as HTMLElement).remove())
  await page.locator('[data-need-row="need-a"]').click()
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  await page.getByText('Source record', { exact: true }).click()
  await expect(page.getByText('P-1 · Event date', { exact: false })).toBeVisible()
  await expect(page).toHaveURL(/need=need-a/)
  await page.locator('[data-need-row="need-b"]').click()
  await expect(page).toHaveURL(/need=need-b/)
  await page.goBack()
  await expect(page).toHaveURL(/need=need-a/)
  await expect(page.getByRole('heading', { name: 'A very long customer organization name for a multi-phase advanced manufacturing and industrial infrastructure development company' })).toBeVisible()
  expect(providerPosts).toBe(0)

  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.getByRole('heading', { name: 'A very long customer organization name for a multi-phase advanced manufacturing and industrial infrastructure development company' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await page.screenshot({ path: '../.agent/artifacts/PRODUCTION-M1-UI/selected-detail-390x844.png', fullPage: false })
})
