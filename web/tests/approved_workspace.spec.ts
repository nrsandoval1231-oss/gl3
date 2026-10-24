import { expect, test } from '@playwright/test'

import { needA, needB } from './fixtures/dashboard'

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
  await expect(page.getByRole('heading', { name: 'A very long customer organization name that should wrap without widening the dashboard' })).toBeVisible()
  await expect(page.getByText('Opportunity Intelligence', { exact: true })).toBeVisible()
  await expect(page.locator('.wh-customer-metrics > div')).toHaveCount(3)
  await expect(page.locator('.wh-customer-metrics')).toContainText('Not established')
  const dashboard = page.getByRole('region', { name: 'Commercial intelligence card' })
  await expect(dashboard.getByText('A very long customer organization name that should wrap without widening the dashboard').first()).toBeVisible()
  await expect(dashboard.getByRole('link', { name: 'Call +1 512 555 0100' })).toHaveAttribute('href', 'tel:+15125550100')
  await expect(dashboard.locator('a[href^="mailto:"]')).toHaveCount(0)
  await page.locator('.wh-more-tabs > summary').click()
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
  const geometry = await page.evaluate(() => ({ header: document.querySelector('.wh-header')!.getBoundingClientRect(), rail: document.querySelector('.wh-list')!.getBoundingClientRect(), metrics: document.querySelector('.wh-customer-metrics')!.getBoundingClientRect(), columns: document.querySelector('.ic-dashboard')!.getBoundingClientRect(), tabs: document.querySelector('.wh-tabs')!.getBoundingClientRect(), table: document.querySelector('.wh-tabs')!.getBoundingClientRect() }))
  expect(geometry.header.height).toBeCloseTo(92, 0)
  // October 23 supersedes the old fixed 25% queue / three-column detail.
  expect(geometry.rail.width).toBeGreaterThan(1648 * .5)
  expect(geometry.rail.width).toBeLessThan(1648 * .71)
  expect(geometry.metrics.top).toBeGreaterThan(geometry.header.bottom)
  expect(geometry.columns.top).toBeGreaterThan(geometry.metrics.top)
  expect(await page.locator('.wh-header').evaluate(el => getComputedStyle(el).backgroundColor)).toBe('rgb(11, 31, 51)')
  await page.evaluate(() => document.fonts.ready)
  expect(await page.evaluate(() => document.fonts.check('14px Inter') && document.fonts.check('22px Sora'))).toBe(true)
  for (const [width, height] of [[1648,928],[1440,900],[1280,800],[768,1024],[390,844]]) {
    await page.setViewportSize({ width, height })
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    await page.screenshot({ path: new URL(`../../docs/design/screenshots/fixture-workspace-${width}x${height}.png`, import.meta.url).pathname, fullPage: false })
  }
  await page.setViewportSize({ width: 1648, height: 928 })
  // Wider action labels model platform font metrics without changing production typography.
  await page.addStyleTag({ content: '.wh-record-actions button { letter-spacing: 3px; }' })
  const actionGeometry = await page.evaluate(() => {
    const rect = (selector: string) => document.querySelector(selector)!.getBoundingClientRect()
    return { actions: rect('.wh-record-actions').toJSON(), toolbar: rect('.wh-identity-toolbar').toJSON(), share: rect('.wh-share').toJSON(), workflow: rect('.wh-primary-action').toJSON(), metrics: rect('.wh-customer-metrics').toJSON() }
  })
  expect(actionGeometry.actions.width).toBeGreaterThan(225)
  expect(actionGeometry.share.top).toBeCloseTo(actionGeometry.workflow.top, 0)
  expect(actionGeometry.share.right).toBeLessThanOrEqual(actionGeometry.workflow.left)
  expect(actionGeometry.workflow.right).toBeLessThanOrEqual(1648)
  expect(actionGeometry.metrics.top).toBeGreaterThan(geometry.header.bottom)
  await page.locator('[data-need-row="need-a"]').click()
  await page.getByRole('button', { name: 'Evidence', exact: true }).click()
  await page.getByText('Source record', { exact: true }).click()
  await expect(page.getByText('P-1 · Event date', { exact: false })).toBeVisible()
  await expect(page).toHaveURL(/need=need-a/)
  await page.locator('[data-need-row="need-b"]').click()
  await expect(page).toHaveURL(/need=need-b/)
  await page.goBack()
  await expect(page).toHaveURL(/need=need-a/)
  await expect(page.getByRole('heading', { name: 'A very long customer organization name that should wrap without widening the dashboard' })).toBeVisible()
  expect(providerPosts).toBe(0)

  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.getByRole('heading', { name: 'A very long customer organization name that should wrap without widening the dashboard' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
})
