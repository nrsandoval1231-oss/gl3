import { mockDemandSummary } from './mock-demand-summary'
import { expect, test } from '@playwright/test'
import type { BuyingChainResult } from '../src/api/client'

const pageFixture = {
  items: [
    { id: 'p1', project_id: 'p1', name: 'Northstar Energy · Mesa Compressor', company: 'Northstar Energy', location: 'Midland, TX', sector: 'oil_gas', asset_type: 'Compressor station', priority_score: 42, representative_need_id: 'n1', need_count: 2, needs: [{ id: 'n1', tier: 'Signal', activity: 'compression' }, { id: 'n2', tier: 'Prospect', activity: 'construction power' }], event: { kind: 'permit_issued', label: 'Permit issued', date: '2026-10-10' }, contact: [], power_summary: null, power_summary_kind: 'unknown', next_action: null, shortlist_assessment: { eligible: true, reasons: [], evidence_refs: ['source-1'], why_now: 'Permit issued for Mesa Compressor on October 10, 2026.', next_step: 'Confirm the project owner and power timing.', source_subject: 'Mesa Compressor' }, updated_at: '2026-10-28T00:00:00Z' },
    { id: 'p2', project_id: 'p2', name: 'Copperline Data · Mesa Campus', company: 'Copperline Data', location: 'Phoenix, AZ', sector: 'data_centers', asset_type: 'Campus', priority_score: null, representative_need_id: 'n3', need_count: 1, needs: [{ id: 'n3', tier: 'Lead' }], event: null, contact: [], power_summary: '420 MW supported residual gap', power_summary_kind: 'supported_gap', next_action: null, shortlist_assessment: { eligible: true, reasons: [], evidence_refs: [], why_now: null, next_step: null, source_subject: 'Mesa Campus' }, updated_at: '2026-10-28T00:00:00Z' },
  ], total: 2, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'synthetic-flat', generation: 'synthetic', results_scope: 'discovery',
}
const buyingChainFixture = { project_id: 'p1', status: 'complete', candidates: [], unresolved: [], runs: [], policy_version: 'buying-chain-v2-permits' } satisfies BuyingChainResult

test('synthetic flat results render company/project rows, honest KPIs, filters, selection and full-cohort server search', async ({ page }) => {
  const requests: URL[] = []
  const demandRequests: URL[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/commercial-pursuits**', route => route.fulfill({ json: { items: [], counts: { total: 0, active: 0, needs_attention: 0 }, total_matching: 0, has_more: false, next_offset: null } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/demand-summary?*', route => { demandRequests.push(new URL(route.request().url())); return route.fulfill({ json: { availability: 'available', sector: new URL(route.request().url()).searchParams.get('sector'), as_of: '2026-10-31T00:00:00Z', totals: { identified_records: 5, known_mw_records: 3, unknown_records: 2, conflicted_records: 1 }, classes: { documented: { mw: 8, record_count: 2 }, calculated: { mw: 4.5, record_count: 1 }, estimated: { mw: 6, record_count: 1 } }, provenance: { contract: 'equipment-demand-v1', source_count: 3, latest_evidence_at: '2026-10-30T00:00:00Z' }, limitations: [] } }) })
  await page.route('**/api/opportunities/projects?*', route => { const url = new URL(route.request().url()); requests.push(url); const response = url.searchParams.get('shortlist') === 'false' ? { ...pageFixture, items: pageFixture.items.map(({ shortlist_assessment: _assessment, ...item }) => item) } : pageFixture; return route.fulfill({ json: response }) })
  await page.route('**/api/opportunities/needs/n1*', route => route.fulfill({ json: { id: 'n1', project_id: 'p1', name: 'Northstar Mesa Compressor', browse_title: 'Mesa Compressor', location: 'Midland, TX', tier: 'Signal', activity: 'compression', required_mw: null, start_window: null, duration: null, supply: 'Unknown', rationale: 'Source fixture', workflow_status: 'New', evidence: [], missing_facts: [] } }))
  await page.goto('/?view=workspace&projectBrowse=1')

  await expect(page.getByRole('heading', { name: 'Opportunities' })).toBeVisible()
  await expect.poll(() => requests[0]?.searchParams.get('include_signals')).toBe('true')
  await expect.poll(() => requests[0]?.searchParams.get('shortlist')).toBe('true')
  await expect(page.locator('.cfr-table tbody tr')).toHaveCount(2)
  await expect(page.locator('.cfr-kpis article')).toHaveCount(3)
  const demandKpi = page.locator('.cfr-kpis article').first()
  await expect(demandKpi).toContainText('Identified Power Demand (MW)')
  await expect.poll(() => demandKpi.locator('strong').textContent()).toBe('8 MW')
  await expect(demandKpi.locator('strong')).toHaveAttribute('aria-label', '8 MW documented')
  await expect(demandKpi).toContainText('Documented 8 MW (2)')
  await expect(demandKpi).toContainText('Calculated 4.5 MW (1)')
  await expect(demandKpi).toContainText('Estimated 6 MW (1)')
  await expect(demandKpi).toContainText('2 unknown')
  await expect(demandKpi).toContainText('Additional equipment only')
  await expect(demandKpi).toContainText('not total portfolio demand')
  await expect(demandKpi).not.toContainText('equipment-demand-v1')
  await demandKpi.getByText('Coverage and limitations').click()
  await expect(demandKpi).toContainText('3 contributing sources')
  await expect.poll(() => demandRequests.at(-1)?.searchParams.get('sector')).toBe('all')
  await expect(page.locator('.cfr-heading')).toContainText('Shortlist')
  await expect(page.locator('.cfr-kpis')).toContainText('Priority classification unavailable')
  await expect(page.locator('.cfr-kpis')).toContainText('Creation date unavailable')
  await expect(page.locator('.cfr-table')).toContainText('Northstar Energy')
  await expect(page.locator('.cfr-table')).toContainText('Mesa Compressor')
  await expect(page.locator('.cfr-table')).toContainText('Permit issued for Mesa Compressor on October 10, 2026.')
  await expect(page.locator('.cfr-table')).toContainText('Confirm the project owner and power timing.')
  await expect(page.locator('.cfr-table')).toContainText('Activity MW not established')
  await expect(page.locator('.cfr-table')).not.toContainText('Qualification: Signal')
  await expect(page.locator('.cfr-table')).toContainText('Supported gap · 420 MW supported residual gap')

  await page.getByRole('combobox', { name: 'Region' }).selectOption({ label: 'Midland, TX' })
  await expect(page.locator('.cfr-table tbody tr')).toHaveCount(1)
  await page.getByRole('combobox', { name: 'Region' }).selectOption('')
  await page.getByRole('combobox', { name: 'Project type' }).selectOption('oil_gas')
  await expect.poll(() => demandRequests.at(-1)?.searchParams.get('sector')).toBe('oil_gas')
  await page.getByRole('combobox', { name: 'Project type' }).selectOption('all')
  await expect(page.locator('.cfr-table')).not.toContainText('No contact on file')
  await page.getByRole('button', { name: 'All Projects' }).click()
  await expect.poll(() => requests.at(-1)?.searchParams.get('shortlist')).toBe('false')
  await expect(page.locator('.cfr-heading')).toContainText('Signals included')
  await expect(page.locator('[data-label="Why now"]').first()).toContainText('Permit issued · 2026-10-10')
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.locator('[data-need-row="n1"]').first().click()
  await expect(page).toHaveURL(/shortlist=0/)
  await expect(page.locator('.cod-panel')).toBeVisible()
  await page.goBack()
  await expect(page).toHaveURL(/shortlist=0/)
  await expect(page.locator('.cfr-view-switch button[aria-pressed="true"]')).toHaveText('All Projects')

  await page.getByRole('textbox', { name: 'Search opportunities' }).fill('alternate source alias')
  await expect.poll(() => requests.some(url => url.searchParams.get('search') === 'alternate source alias')).toBeTruthy()
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.locator('.cfr-kpis article')).toHaveCount(3)
  await expect(demandKpi.locator('strong')).toHaveText('8 MW')
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
})

test('canonical KPI captions stay within their cards and above the opportunities heading', async ({ page }) => {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: pageFixture }))
  await page.route('**/api/opportunities/needs/**', route => route.fulfill({ json: { id: 'n1', project_id: 'p1', name: 'Northstar Mesa Compressor', browse_title: 'Northstar Mesa Compressor', location: 'Midland, TX', tier: 'Signal', activity: 'compression', priority_score: 42, required_mw: null, start_window: null, duration: null, supply: 'Unknown', rationale: 'Synthetic fixture', workflow_status: 'New' } }))
  await page.goto('/?view=workspace&projectBrowse=1')

  const kpis = page.locator('.cfr-kpis')
  const heading = page.getByRole('heading', { name: 'Opportunities' })
  await expect(kpis.locator('article')).toHaveCount(3)
  for (const width of [1440, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 900 })
    await expect.poll(async () => page.evaluate(() => {
      const cards = [...document.querySelectorAll<HTMLElement>('.cfr-kpis article')]
      const heading = document.querySelector<HTMLElement>('.cfr-heading h1')
      const results = document.querySelector<HTMLElement>('.canonical-flat-results')
      if (cards.length !== 3 || !heading || !results) return false
      const cardContainsText = cards.every(card => {
        const box = card.getBoundingClientRect()
        return [...card.querySelectorAll<HTMLElement>('strong, span, small')].every(text => {
          const range = document.createRange()
          range.selectNodeContents(text)
          return [...range.getClientRects()].every(rect => rect.top >= box.top && rect.bottom <= box.bottom && rect.left >= box.left && rect.right <= box.right)
        })
      })
      const kpiBottom = document.querySelector('.cfr-kpis')!.getBoundingClientRect().bottom
      const resultsTop = results.getBoundingClientRect().top
      return cardContainsText && kpiBottom < heading.getBoundingClientRect().top && resultsTop - kpiBottom >= 0 && resultsTop - kpiBottom <= 24
    })).toBe(true)
    await page.screenshot({ path: `../.artifacts/kpi-layout-fix-20261030/kpi-${width}.png`, fullPage: true })
  }
  await expect(heading).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: 'Mesa Compressor', exact: true }).click()
  await expect(page.locator('.cfr-kpis')).toBeHidden()
  await page.locator('.cod-back').click()
  await expect(page.locator('.cfr-kpis')).toBeVisible()
  await page.screenshot({ path: '../.artifacts/kpi-layout-fix-20261030/kpi-mobile-back.png', fullPage: true })
})

test('shortlist cards keep their actions and browse controls inside the results panel at desktop and phone widths', async ({ page }) => {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/commercial-pursuits**', route => route.fulfill({ json: { items: [], counts: { total: 0, active: 0, needs_attention: 0 }, total_matching: 0, has_more: false, next_offset: null } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: pageFixture }))
  await page.route('**/api/opportunities/needs/n1*', route => route.fulfill({ json: { id: 'n1', project_id: 'p1', name: 'Northstar Mesa Compressor', browse_title: 'Mesa Compressor', location: 'Midland, TX', tier: 'Signal', activity: 'compression', required_mw: null, start_window: null, duration: null, supply: 'Unknown', rationale: 'Synthetic source fixture.', workflow_status: 'New', evidence: [], missing_facts: [] } }))
  await page.goto('/?view=workspace')
  const card = page.locator('.cfr-table tbody tr').first()
  await expect(card).toBeVisible()
  const assertWithinBounds = async () => page.evaluate(() => {
    const card = document.querySelector<HTMLElement>('.cfr-table tbody tr')
    const action = card?.querySelector<HTMLElement>('.cfr-card-action')
    const results = document.querySelector<HTMLElement>('.canonical-flat-results')
    if (!card || !action || !results) return false
    const cardRect = card.getBoundingClientRect(), actionRect = action.getBoundingClientRect(), resultsRect = results.getBoundingClientRect()
    const controlsReadable = [...document.querySelectorAll<HTMLElement>('.cfr-filters input,.cfr-filters select')].filter(el => el.getClientRects().length).every(el => el.getBoundingClientRect().width >= 80)
    const labelCells = [...document.querySelectorAll<HTMLElement>('.cfr-table tbody tr:first-child td[data-label]')]
    const luminance = (color: string) => {
      const channels = color.match(/[\d.]+/g)?.slice(0, 3).map(Number)
      if (!channels || channels.length !== 3) return NaN
      const linear = channels.map(channel => { const value = channel / 255; return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4 })
      return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    }
    const labelContrast = labelCells.length === 4 && labelCells.every(cell => {
      const ratio = 1.05 / (luminance(getComputedStyle(cell, '::before').color) + 0.05)
      return ratio >= 4.5
    })
    return controlsReadable && labelContrast && actionRect.left >= cardRect.left && actionRect.right <= cardRect.right && cardRect.right <= resultsRect.right && document.documentElement.scrollWidth <= window.innerWidth
  })
  const viewports = [{ width: 1648, height: 928 }, { width: 1440, height: 900 }, { width: 1280, height: 800 }, { width: 768, height: 1024 }, { width: 390, height: 844 }]
  for (const size of viewports) {
    await page.setViewportSize(size)
    await expect.poll(assertWithinBounds).toBe(true)
  }
  await page.setViewportSize({ width: 1280, height: 800 })
  const add = card.getByRole('button', { name: 'Add to Pursuit' })
  await expect(add).toHaveCSS('color', 'rgb(255, 255, 255)')
  await page.getByRole('button', { name: 'Mesa Compressor', exact: true }).click()
  await expect(page.locator('.cod-panel')).toBeVisible()
  for (const size of viewports) {
    await page.setViewportSize(size)
    await expect.poll(assertWithinBounds).toBe(true)
  }
})

test('synthetic repeated cohort conflict stops after one reset and presents a retry', async ({ page }) => {
  let reads = 0
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => { reads += 1; return route.fulfill({ status: 409, json: { detail: 'cohort changed' } }) })
  await page.goto('/?view=workspace&projectBrowse=1')
  await expect(page.getByRole('alert')).toContainText('Results changed again')
  expect(reads).toBeLessThanOrEqual(3)
})

test('demand KPI keeps loading, unavailable, and unknown MW distinct from zero', async ({ page }) => {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: pageFixture }))
  await page.route('**/api/opportunities/demand-summary?*', route => route.fulfill({ status: 503, json: { detail: 'unavailable' } }))
  await page.goto('/?view=workspace&projectBrowse=1')
  const kpi = page.locator('.cfr-kpis article').first()
  await expect(kpi).toContainText('Demand summary unavailable.')
  await expect(kpi.locator('strong')).toHaveText('—')
  await page.route('**/api/opportunities/demand-summary?*', route => route.fulfill({ json: { availability: 'available', sector: 'all', as_of: null, totals: { identified_records: 2, known_mw_records: 0, unknown_records: 2, conflicted_records: 0 }, classes: { documented: { mw: null, record_count: 0 }, calculated: { mw: null, record_count: 0 }, estimated: { mw: null, record_count: 0 } }, provenance: { contract: 'equipment-demand-v1', source_count: 1, latest_evidence_at: null }, limitations: [] } }))
  await kpi.getByRole('button', { name: 'Retry' }).click()
  await expect(kpi).toContainText('2 identified records')
  await expect(kpi).toContainText('2 unknown')
  await expect(kpi.locator('strong')).toHaveText('—')
  await expect(kpi.locator('strong')).toHaveAttribute('aria-label', 'Unavailable')
})

test('malformed demand summary fails closed while opportunity results remain available', async ({ page }) => {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: pageFixture }))
  await page.route('**/api/opportunities/demand-summary?*', route => route.fulfill({ json: [] }))
  await page.goto('/?view=workspace&projectBrowse=1')
  await expect(page.locator('.cfr-table tbody tr')).toHaveCount(2)
  const kpi = page.locator('.cfr-kpis article').first()
  await expect(kpi).toContainText('Demand summary unavailable.')
  await expect(kpi.locator('strong')).toHaveText('—')
})

test('demand KPI aborts a pending private summary when continuity is cleared', async ({ page }) => {
  let release: (() => void) | undefined
  let started: (() => void) | undefined
  const requestStarted = new Promise<void>(resolve => { started = resolve })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: pageFixture }))
  await page.route('**/api/opportunities/demand-summary?*', async route => {
    started?.()
    await new Promise<void>(resolve => { release = resolve })
    await route.fulfill({ json: { availability: 'available', sector: 'all', as_of: null, totals: { identified_records: 1, known_mw_records: 1, unknown_records: 0, conflicted_records: 0 }, classes: { documented: { mw: 99, record_count: 1 }, calculated: { mw: null, record_count: 0 }, estimated: { mw: null, record_count: 0 } }, provenance: { contract: 'equipment-demand-v1', source_count: 1, latest_evidence_at: null }, limitations: [] } })
  })
  await page.goto('/?view=workspace&projectBrowse=1')
  await requestStarted
  await page.evaluate(() => window.dispatchEvent(new Event('gl3-clear-continuity')))
  const kpi = page.locator('.cfr-kpis article').first()
  await expect(kpi.locator('strong')).toHaveText('—')
  release?.()
  await page.waitForTimeout(100)
  await expect(kpi.locator('strong')).toHaveText('—')
  await expect(kpi).not.toContainText('99 MW')
})

test('demand KPI follows sector changes in the opportunity view and requests the matching scope', async ({ page }) => {
  const scopes: string[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: pageFixture }))
  await page.route('**/api/opportunities/demand-summary?*', route => {
    const sector = new URL(route.request().url()).searchParams.get('sector') ?? 'all'
    scopes.push(sector)
    return route.fulfill({ json: { availability: 'available', sector, as_of: null, totals: { identified_records: 1, known_mw_records: 1, unknown_records: 0, conflicted_records: 0 }, classes: { documented: { mw: sector === 'oil_gas' ? 2 : 7, record_count: 1 }, calculated: { mw: null, record_count: 0 }, estimated: { mw: null, record_count: 0 } }, provenance: { contract: 'equipment-demand-v1', source_count: 1, latest_evidence_at: null }, limitations: [] } })
  })
  await page.goto('/?view=workspace&projectBrowse=1')
  const kpi = page.locator('.cfr-kpis article').first()
  await expect(kpi.locator('strong')).toHaveText('7 MW')
  await page.getByRole('combobox', { name: 'Project type' }).selectOption('oil_gas')
  await expect.poll(() => scopes.at(-1)).toBe('oil_gas')
  await expect(kpi.locator('strong')).toHaveText('2 MW')
})

test('demand KPI refreshes after its bounded 60 second freshness window', async ({ page }) => {
  let reads = 0
  let currentMw = 1
  await page.clock.install()
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: pageFixture }))
  await page.route('**/api/opportunities/demand-summary?*', route => {
    reads += 1
    return route.fulfill({ json: { availability: 'available', sector: 'all', as_of: '2026-10-20T00:00:00Z', totals: { identified_records: 1, known_mw_records: 1, unknown_records: 0, conflicted_records: 0 }, classes: { documented: { mw: currentMw, record_count: 1 }, calculated: { mw: null, record_count: 0 }, estimated: { mw: null, record_count: 0 } }, provenance: { contract: 'equipment-demand-v1', source_count: 1, latest_evidence_at: '2026-10-20T00:00:00Z' }, limitations: [] } })
  })
  await page.goto('/?view=workspace&projectBrowse=1')
  const value = page.locator('.cfr-kpis article').first().locator('strong')
  await expect(value).toHaveText('1 MW')
  const baselineReads = reads
  currentMw = 2
  await page.clock.fastForward(60_000)
  await expect.poll(() => reads).toBeGreaterThan(baselineReads)
  await expect(value).toHaveText('2 MW')
})

test('unknown-only unavailable summary keeps its record counts visible', async ({ page }) => {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: pageFixture }))
  await page.route('**/api/opportunities/demand-summary?*', route => route.fulfill({ json: { availability: 'unavailable', sector: 'all', as_of: null, totals: { identified_records: 2, known_mw_records: 0, unknown_records: 2, conflicted_records: 0 }, classes: { documented: { mw: null, record_count: 0 }, calculated: { mw: null, record_count: 0 }, estimated: { mw: null, record_count: 0 } }, provenance: { contract: 'equipment-demand-v1', source_count: 1, latest_evidence_at: null }, limitations: ['MW unknown'] } }))
  await page.goto('/?view=workspace&projectBrowse=1')
  const kpi = page.locator('.cfr-kpis article').first()
  await expect(kpi.locator('strong')).toHaveText('—')
  await expect(kpi).toContainText('2 identified records')
  await expect(kpi).toContainText('2 unknown')
})

test('incomplete over-budget counts never display zero while complete zero counts do', async ({ page }) => {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: pageFixture }))
  await page.route('**/api/opportunities/demand-summary?*', route => {
    const sector = new URL(route.request().url()).searchParams.get('sector')
    const complete = sector === 'oil_gas'
    return route.fulfill({ json: { counts_complete: complete, availability: 'unavailable', sector, as_of: null, totals: { identified_records: 0, known_mw_records: 0, unknown_records: 0, conflicted_records: 0 }, classes: { documented: { mw: null, record_count: 0 }, calculated: { mw: null, record_count: 0 }, estimated: { mw: null, record_count: 0 } }, provenance: { contract: 'equipment-demand-v1', source_count: 0, latest_evidence_at: null }, limitations: [complete ? 'No safely aggregatable records.' : 'Candidate cohort exceeds the supported summary bound; counts not computed.'] } })
  })
  await page.goto('/?view=workspace&projectBrowse=1')
  const kpi = page.locator('.cfr-kpis article').first()
  await expect(kpi).toContainText('Record counts unavailable.')
  await expect(kpi).not.toContainText('0 identified')
  await kpi.getByText('Coverage and limitations').click()
  await expect(kpi).toContainText('Candidate cohort exceeds the supported summary bound')
  await page.getByRole('combobox', { name: 'Project type' }).selectOption('oil_gas')
  await expect(kpi).toContainText('0 identified')
})

test('synthetic logout while a request is pending cannot repopulate rows or cache', async ({ page }) => {
  let release: (() => void) | undefined
  let requestStarted: (() => void) | undefined
  let routeSettled: (() => void) | undefined
  const projectRequestStarted = new Promise<void>(resolve => { requestStarted = resolve })
  const projectRouteSettled = new Promise<void>(resolve => { routeSettled = resolve })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', async route => {
    requestStarted?.()
    await new Promise<void>(resolve => { release = resolve })
    try { await route.fulfill({ json: pageFixture }) } finally { routeSettled?.() }
  })
  await page.goto('/?view=workspace&projectBrowse=1')
  await projectRequestStarted
  await page.evaluate(() => window.dispatchEvent(new Event('gl3-clear-continuity')))
  await expect(page.getByRole('alert')).toContainText('session ended')
  release?.()
  await projectRouteSettled
  await page.waitForTimeout(150)
  await expect(page.locator('.cfr-table tbody tr')).toHaveCount(0)
})

test('detail loads the active shortlist source group and opens a sibling source record', async ({ page }) => {
  const projectQueries: URL[] = []
  const apiErrors: string[] = []
  const pageErrors: string[] = []
  page.on('pageerror', error => pageErrors.push(error.stack ?? error.message))
  page.on('response', response => { if (response.url().includes('/api/') && response.status() >= 400) apiErrors.push(`${response.status()} ${response.url()}`) })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/needs/n1*', route => route.fulfill({ json: { id: 'n1', project_id: 'p1', name: 'Northstar Mesa Compressor', browse_title: 'Mesa Compressor', location: 'Midland, TX', tier: 'Signal', activity: 'compression', required_mw: null, start_window: null, duration: null, supply: 'Unknown', rationale: 'Source fixture', workflow_status: 'New', evidence: [], missing_facts: [] } }))
  await page.route('**/api/opportunities/needs/n2*', route => route.fulfill({ json: { id: 'n2', project_id: 'p1', name: 'Northstar construction power', browse_title: 'Construction power', location: 'Midland, TX', tier: 'Prospect', activity: 'construction power', required_mw: null, start_window: null, duration: null, supply: 'Unknown', rationale: 'Source fixture', workflow_status: 'New', evidence: [], missing_facts: [] } }))
  await page.route('**/api/commercial-pursuits**', route => route.fulfill({ json: { items: [], counts: { total: 0, active: 0, needs_attention: 0 }, total_matching: 0, has_more: false, next_offset: null } }))
  await mockDemandSummary(page)
  await page.route('**/api/projects/p1/buying-chain*', route => route.fulfill({ json: buyingChainFixture }))
  await page.route('**/api/opportunities/projects?*', route => {
    const url = new URL(route.request().url())
    projectQueries.push(url)
    return route.fulfill({ json: pageFixture })
  })
  await page.goto('/?view=workspace&projectBrowse=1')
  await expect(page.locator('.cfr-table tbody tr')).toHaveCount(2)
  await page.locator('[data-need-row="n1"]').first().click()
  await expect(page).toHaveURL(/need=n1/)
  // Wait for the grouped detail response before opening Related, so the source group is present.
  await expect(page.locator('.cod-location')).toContainText('Permit issued')
  await page.getByRole('button', { name: 'Related' }).click()
  await expect(page.getByRole('region', { name: 'Other source-backed records' })).toContainText('construction power')
  expect(projectQueries.some(url => url.searchParams.get('need_id') === 'n1' && url.searchParams.get('shortlist') === 'true' && url.searchParams.get('include_signals') === 'true')).toBeTruthy()
  await expect(page.locator('.buying-chain[data-context-loading="false"]')).toBeVisible()
  await page.getByRole('button', { name: /construction power/ }).click()
  await expect(page).toHaveURL(/need=n2/)
  await expect(page.locator('.cod-panel')).toContainText('Prospect')
  await expect(page.locator('.cod-location')).toContainText('Permit issued')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: 'Related' }).click()
  await expect(page.locator('.buying-chain[data-context-loading="false"]')).toBeVisible()
  const sibling = page.getByRole('button', { name: /compression/ })
  await expect(sibling).toBeVisible()
  await sibling.click()
  await expect(page).toHaveURL(/need=n1/)
  await expect(page.locator('.cod-panel')).toContainText('Signal')
  expect(apiErrors).toEqual([])
  expect(pageErrors).toEqual([])
})

test('empty shortlist gives an evidence-rule explanation and a direct All Projects path', async ({ page }) => {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: { ...pageFixture, items: [], total: 0 } }))
  await page.goto('/?view=workspace&projectBrowse=1&sector=oil_gas')
  await expect(page.getByRole('status')).toContainText('No projects meet the shortlist evidence rules for this search')
  await page.getByRole('button', { name: 'Explore All Projects for unresolved records' }).click()
  await expect(page.getByRole('button', { name: 'All Projects' })).toHaveAttribute('aria-pressed', 'true')
})

test('bookmarked needs outside the shortlist use the bounded All Projects detail fallback', async ({ page }) => {
  const detailScopes: string[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/opportunities/needs/n1*', route => route.fulfill({ json: { id: 'n1', project_id: 'p1', name: 'Northstar Mesa Compressor', browse_title: 'Mesa Compressor', location: 'Midland, TX', tier: 'Signal', activity: 'compression', required_mw: null, start_window: null, duration: null, supply: 'Unknown', rationale: 'Source fixture', workflow_status: 'New', evidence: [], missing_facts: [] } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => {
    const url = new URL(route.request().url())
    const needId = url.searchParams.get('need_id')
    if (needId) {
      detailScopes.push(url.searchParams.get('shortlist') ?? '')
      return route.fulfill({ json: needId === 'n1' && url.searchParams.get('shortlist') === 'false' ? pageFixture : { ...pageFixture, items: [], total: 0 } })
    }
    return route.fulfill({ json: pageFixture })
  })
  await page.goto('/?view=workspace&projectBrowse=1')
  await page.locator('[data-need-row="n1"]').first().click()
  await expect.poll(() => detailScopes).toEqual(['true', 'false'])
  await expect(page.locator('.cod-status')).toHaveCount(0)
  await expect(page.locator('.cod-panel')).toContainText('Mesa Compressor')
})

test('synthetic logout while results are unmounted clears module cache before returning', async ({ page }) => {
  let projectReads = 0
  let holdNext = false
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', async route => {
    projectReads += 1
    if (holdNext) return new Promise<void>(() => {})
    return route.fulfill({ json: pageFixture })
  })
  await page.goto('/?view=workspace&projectBrowse=1')
  await expect(page.locator('.cfr-table tbody tr')).toHaveCount(2)
  await page.getByRole('button', { name: 'Pursuits' }).click()
  await page.evaluate(() => window.dispatchEvent(new Event('gl3-clear-continuity')))
  holdNext = true
  await page.getByRole('button', { name: 'Opportunities' }).click()
  await expect(page.getByRole('status')).toContainText('Loading current opportunities')
  await expect(page.locator('.cfr-table tbody tr')).toHaveCount(0)
  expect(projectReads).toBeGreaterThanOrEqual(2)
})

test('synthetic empty and error states do not produce repeated React update errors', async ({ page }) => {
  const consoleErrors: string[] = []
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ status: 503, json: { detail: 'unavailable' } }))
  await page.goto('/?view=workspace&projectBrowse=1')
  await expect(page.getByRole('alert')).toContainText('Could not load projects')
  await expect.poll(() => consoleErrors.filter(error => /maximum update depth|too many re-renders/i.test(error)).length).toBe(0)
})

test('synthetic project selection restores focus to its exact need control', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: pageFixture }))
  await page.route('**/api/opportunities/needs/**', route => route.fulfill({ json: { id: 'n2', project_id: 'p1', name: 'Synthetic related need', browse_title: 'Synthetic related need', location: 'Midland, TX', tier: 'Prospect', activity: 'construction power', priority_score: 42, required_mw: null, start_window: null, duration: null, supply: 'Unknown', rationale: 'Synthetic fixture', workflow_status: 'New' } }))
  await page.goto('/?view=workspace&projectBrowse=1')
  await expect(page.locator('.cfr-table tbody tr')).toHaveCount(2)
  const primaryNeed = page.locator('[data-need-row="n1"]')
  await expect(primaryNeed).toBeEnabled()
  await primaryNeed.click()
  await expect(page).toHaveURL(/need=n1/)
  await page.locator('.cod-back').click()
  await expect(page.locator('[data-need-row="n1"]')).toBeFocused()
})

test('synthetic unavailable browse response stays visible for explicit retry', async ({ page }) => {
  let reads = 0
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => { reads += 1; return route.fulfill({ status: 503, headers: { 'X-Qualification-State': 'pending', 'retry-after': '0' }, json: { detail: 'browse pending' } }) })
  await page.goto('/?view=workspace&projectBrowse=1')
  await expect(page.getByRole('alert')).toContainText('Could not load projects (503)')
  expect(reads).toBeLessThanOrEqual(2)
})

test('malformed browse payload fails safely while an exact selected need remains available', async ({ page }) => {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await mockDemandSummary(page)
  await page.route('**/api/opportunities/projects?*', route => route.fulfill({ json: [] }))
  await page.route('**/api/opportunities/needs/n2*', route => route.fulfill({ json: {
    id: 'n2', project_id: 'p1', name: 'Exact selected need', browse_title: 'Exact selected need',
    location: 'Midland, TX', tier: 'Prospect', activity: 'construction power', priority_score: 42,
    required_mw: null, start_window: null, duration: null, supply: 'Unknown', rationale: 'Synthetic fixture', workflow_status: 'New',
  } }))

  await page.goto('/?view=workspace&projectBrowse=1&need=n2')
  await expect(page.getByRole('heading', { name: 'Exact selected need' })).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('Current project results could not be confirmed')
})
