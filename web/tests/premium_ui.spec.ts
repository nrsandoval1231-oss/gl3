import { mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'
import { mockDemandSummary } from './mock-demand-summary'

const screenshotDir = resolve(dirname(fileURLToPath(import.meta.url)), '../../docs/validation/premium-ui-20261111')
const refreshCaptures = process.env.GRIDLENS_REFRESH_UI_CAPTURES === '1'
const capturePath = (name: string) => refreshCaptures ? resolve(screenshotDir, name) : test.info().outputPath(name)

// Every response in this test is synthetic and visibly identified as such.
async function installSyntheticApi(page: import('@playwright/test').Page, event: { kind: string; label: string; date: string } | null = null) {
  const searchQueries: string[] = []
  await mockDemandSummary(page)
  await page.route(url => new URL(url).pathname.startsWith('/api/'), route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/session') return route.fulfill({ json: { authenticated: true } })
    if (url.pathname === '/api/opportunities/groups') {
      const source = { title: 'Synthetic acceptance source', url: 'https://example.invalid/synthetic-source', evidence_id: 'synthetic-source-1', date: '2026-11-04' }
      const brief = (kind: 'estimated' | 'documented' | 'unknown', name: string) => ({
        version: 'synthetic-v1',
        why_now: { text: `Synthetic source indicates a ${name.toLowerCase()} planning milestone.`, source_date: '2026-11-04', scope: 'Synthetic project', sources: [source] },
        power_need: kind === 'estimated'
          ? { amount_class: 'estimated' as const, scope: 'Synthetic temporary package', value: '4.5', unit: 'MW', status: 'estimated from source scope', limitations: ['Estimate; confirm the package boundary.'] }
          : kind === 'documented'
            ? { amount_class: 'documented' as const, scope: 'Synthetic phase one', value: '2', unit: 'MW', status: 'documented in source', limitations: [] }
            : { amount_class: 'unknown' as const, scope: 'Synthetic project scope', value: null, unit: null, status: 'unknown', limitations: ['Activity-specific power need is unknown; unknown is not zero.'] },
        best_contact: kind === 'estimated'
          ? { contact: 'Synthetic test contact', href: 'mailto:buyer@synthetic.invalid', kind: 'email' as const, route_kind: 'person_method' as const, authority: 'Synthetic test fixture; confirm for this need.', deliverability: 'Synthetic test route; not verified for delivery.', sources: [] }
          : kind === 'documented'
            ? { contact: 'Synthetic test operator', href: 'tel:+15555550101', kind: 'call' as const, route_kind: 'person_method' as const, authority: 'Synthetic test fixture; confirm for this need.', deliverability: 'Synthetic test route; not verified for delivery.', sources: [] }
            : null,
        next_action: { text: `Review the synthetic ${kind} scope before follow-up.`, kind: 'review_source', source },
        freshness: { as_of: '2026-11-04T00:00:00Z', status: 'current_source', source_date: '2026-11-04' },
        limitations: ['Synthetic fixture only; it makes no claim about a real company or project.'], sources: [source],
      })
      const group = (index: number, name: string, kind: 'estimated' | 'documented' | 'unknown') => {
        const projectId = `synthetic-project-${index}`
        const needId = `synthetic-need-${index}`
        return {
          id: `cg_synthetic_acceptance_${index}`, name, role: 'customer', group_kind: 'resolved_identity',
          project_count: 1, total_known_project_count: 1, relevant_project_count: 1, need_count: 1, eligible_need_count: 1, sectors: ['data_centers'],
          featured_project: {
            id: projectId, project_id: projectId, name: `${name} campus phase`, company: name,
            customer_identity_id: `synthetic-company-${index}`, location: 'Synthetic, TX', sector: 'data_centers', asset_type: 'data_center', priority_score: null,
            representative_need_id: needId, need_count: 1,
            needs: [{ id: needId, project_id: projectId, name: `${name} campus phase`, activity: 'construction', tier: 'Prospect', commercial_brief: brief(kind, name) }],
            eligible_need_ids: [needId], event,
            contact: [], commercial_brief: brief(kind, name), power_summary: null, power_summary_kind: kind === 'unknown' ? 'unknown' : 'activity_requirement', next_action: null,
            shortlist_assessment: { eligible: true, reasons: [], evidence_refs: [], why_now: 'Synthetic fixture for browser acceptance.', next_step: 'Review synthetic source.' }, updated_at: null,
          },
        }
      }
      return route.fulfill({ json: {
        items: [
          group(1, 'Synthetic Estimated Operator', 'estimated'),
          group(2, 'Synthetic Documented Operator', 'documented'),
          group(3, 'Synthetic Unknown Scope Operator', 'unknown'),
        ], total: 3, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'synthetic-group-cohort', generation: 'synthetic',
        facets: { regions: ['Synthetic, TX'], stages: ['Construction'] },
      } })
    }
    if (url.pathname === '/api/opportunities/projects') return route.fulfill({ json: { items: [], total: 0, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'synthetic-project-cohort', generation: 'synthetic' } })
    if (url.pathname === '/api/search') return route.fulfill({ json: {
      query: url.searchParams.get('q') ?? '', companies: [{ company_identity_id: 'synthetic-company-1', name: 'Synthetic Estimated Operator' }],
      projects: [], contacts: [], opportunities: [], companies_status: 'available', opportunities_status: 'available',
    } })
    if (url.pathname === '/api/opportunities/workspace/changes') return route.fulfill({ json: { items: [], counts: { discovered: 0, changed: 0, promoted: 0, closed: 0, review_exception: 0 }, total_unreviewed: 0, offset: 0, limit: 50, next_offset: null, baseline_identity: 'synthetic', token: 'synthetic', source_health_exceptions: [] } })
    if (url.pathname.startsWith('/api/opportunities/groups/')) return route.fulfill({ json: { group: null, projects: { items: [], total: 0, count_unit: 'projects', limit: 25, offset: 0, cohort_token: 'synthetic-child-cohort', generation: 'synthetic' } } })
    if (url.pathname.startsWith('/api/opportunities/needs/')) return route.fulfill({ json: {} })
    if (url.pathname === '/api/commercial-pursuits') return route.fulfill({ json: { items: [], counts: { total: 0, active: 0, needs_attention: 0 }, total_matching: 0, has_more: false, next_offset: null } })
    return route.fulfill({ json: [] })
  })
  // Keep the existing search request observable while the rest of the synthetic
  // API fixture remains a compact catch-all for the page's ordinary reads.
  await page.route('**/api/search?**', route => {
    const url = new URL(route.request().url())
    searchQueries.push(url.searchParams.get('q') ?? '')
    return route.fulfill({ json: {
      query: url.searchParams.get('q') ?? '', companies: [{ company_identity_id: 'synthetic-company-1', name: 'Synthetic Estimated Operator' }],
      projects: [], contacts: [], opportunities: [], companies_status: 'available', opportunities_status: 'available',
    } })
  })
  return searchQueries
}

test('premium shell holds its desktop and phone layout and keeps search and account controls usable', async ({ page }) => {
  if (refreshCaptures) mkdirSync(screenshotDir, { recursive: true })
  const searchQueries = await installSyntheticApi(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/?view=workspace&groupBrowse=1&shortlist=1')

  const header = page.locator('.canonical-header')
  const masthead = page.locator('.canonical-header__masthead')
  const nav = page.getByRole('navigation', { name: 'Primary navigation' })
  const brandArt = page.locator('.canonical-header__brand-art')
  const estimatedCard = page.getByRole('region', { name: 'Synthetic Estimated Operator customer group' })
  const documentedCard = page.getByRole('region', { name: 'Synthetic Documented Operator customer group' })
  const unknownCard = page.getByRole('region', { name: 'Synthetic Unknown Scope Operator customer group' })
  await expect(estimatedCard).toBeVisible()
  await expect(documentedCard).toBeVisible()
  await expect(unknownCard).toBeVisible()
  await expect(page.getByRole('button', { name: 'Shortlist', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('.premium-metrics strong').first()).toHaveText('3')
  await expect(nav.getByRole('button')).toHaveText(['Opportunities', 'Companies', 'Pursuits', 'Reports'])
  expect(await masthead.evaluate(el => Math.round(el.getBoundingClientRect().height))).toBe(110)
  expect(await nav.evaluate(el => Math.round(el.getBoundingClientRect().height))).toBe(58)
  await expect(brandArt).toHaveAttribute('src', '/ui/canonical/canonical-header-brand.png')
  expect(await brandArt.evaluate(el => getComputedStyle(el).objectFit)).toBe('contain')
  await expect(estimatedCard).toContainText('Synthetic source indicates a synthetic estimated operator planning milestone.')
  await expect(estimatedCard).toContainText('4.5 MW')
  await expect(estimatedCard.getByRole('link', { name: 'Email Synthetic test contact' })).toHaveAttribute('href', 'mailto:buyer@synthetic.invalid')
  await expect(estimatedCard).toContainText('Review the synthetic estimated scope before follow-up.')
  await expect(documentedCard).toContainText('2 MW')
  await expect(documentedCard).toContainText('Documented')
  await expect(documentedCard.getByRole('link', { name: 'Call Synthetic test operator' })).toHaveAttribute('href', 'tel:+15555550101')
  await expect(unknownCard).toContainText('unknown')

  await page.getByRole('button', { name: 'Account menu' }).click()
  const accountOptions = page.getByRole('region', { name: 'Account options' }).or(page.locator('.workspace-account__menu'))
  await expect(accountOptions).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(accountOptions).toBeHidden()
  await expect(page.getByRole('button', { name: 'Account menu' })).toBeFocused()
  await page.getByRole('button', { name: 'Account menu' }).click()
  await expect(accountOptions).toContainText('Build SHA')
  const sha = (await accountOptions.locator('dd').nth(2).innerText()).trim()
  expect(sha).toMatch(/^[0-9a-f]{40}$/i)
  await expect(accountOptions.locator('dd').nth(0)).toHaveText('Local build')
  await accountOptions.getByRole('button', { name: 'Profile' }).click()
  const dialog = page.getByRole('dialog', { name: 'Profile' })
  await expect(dialog).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(page.getByRole('button', { name: 'Account menu' })).toBeFocused()
  await page.getByRole('button', { name: 'Account menu' }).click()
  await page.locator('.workspace-account__menu').getByRole('button', { name: 'Settings' }).click()
  const settings = page.getByRole('dialog', { name: 'Settings' })
  await settings.getByRole('checkbox', { name: 'Reduce motion' }).check()
  await expect.poll(() => page.evaluate(() => localStorage.getItem('gl3.reduceMotion'))).toBe('true')
  await expect.poll(() => page.locator('html').evaluate(el => el.classList.contains('gl3-reduce-motion'))).toBe(true)
  await page.keyboard.press('Escape')
  await page.reload()
  await expect.poll(() => page.evaluate(() => localStorage.getItem('gl3.reduceMotion'))).toBe('true')
  await page.getByRole('button', { name: 'Account menu' }).click()
  await page.locator('.workspace-account__menu').getByRole('button', { name: 'Settings' }).click()
  await expect(page.getByRole('dialog', { name: 'Settings' }).getByRole('checkbox', { name: 'Reduce motion' })).toBeChecked()
  await page.keyboard.press('Escape')

  // Exercise the retained four destination handlers, then restore Opportunities.
  await nav.getByRole('button', { name: 'Companies', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Companies', exact: true })).toBeVisible()
  await nav.getByRole('button', { name: 'Reports', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Reports', exact: true })).toBeVisible()
  await nav.getByRole('button', { name: 'Pursuits', exact: true }).click()
  await expect(nav.getByRole('button', { name: 'Pursuits', exact: true })).toHaveAttribute('aria-current', 'page')
  await nav.getByRole('button', { name: 'Opportunities', exact: true }).click()
  await expect(page.locator('.premium-account-card')).toHaveCount(3)

  // Capture the desktop surface with the synthetic fixture name visible.
  await page.screenshot({ path: capturePath('desktop-1440x900.png') })

  for (const size of [{ width: 1648, height: 928 }, { width: 1280, height: 800 }, { width: 768, height: 1024 }]) {
    await page.setViewportSize(size)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
    await page.screenshot({ path: capturePath(`desktop-${size.width}x${size.height}.png`), fullPage: true })
  }

  for (const width of [390, 375]) {
    await page.setViewportSize({ width, height: 844 })
    await expect(page.locator('.canonical-header__masthead')).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
    const primaryAction = await page.getByRole('button', { name: 'Add to Pursuit', exact: true }).first().boundingBox()
    expect(primaryAction).not.toBeNull()
    expect(primaryAction!.y + primaryAction!.height).toBeLessThanOrEqual(844)
    if (width === 390) {
      await page.screenshot({ path: capturePath('mobile-390x844.png') })
      await page.screenshot({ path: capturePath('mobile-full.png'), fullPage: true })
    }
  }

  await page.setViewportSize({ width: 390, height: 844 })
  const openSearch = page.getByRole('button', { name: 'Open search' })
  await openSearch.click()
  const search = page.getByRole('searchbox', { name: 'Search companies, projects, contacts and opportunities' })
  await expect(search).toBeFocused()
  await search.fill('synthetic')
  await expect.poll(() => searchQueries).toContain('synthetic')
  await expect(page.getByRole('region', { name: 'Search results' }).getByRole('button', { name: /Synthetic Estimated Operator/ })).toBeVisible()
  await page.getByRole('button', { name: 'Close search' }).click()
  await expect(search).toBeHidden()
  await expect(page.getByRole('region', { name: 'Search results' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Open search' }).click()
  await expect(search).toBeFocused()
  await expect(page.getByRole('region', { name: 'Search results' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: 'Open search' })).toBeFocused()
  await expect(search).toBeHidden()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  expect(await header.evaluate(el => el.getBoundingClientRect().width <= window.innerWidth)).toBeTruthy()
})

for (const event of [
  { kind: 'commissioning_planned', label: 'Commissioning expected', date: '2027-06-01', supported: true },
  { kind: 'decommissioning', label: 'Site decommissioning scheduled', date: '2027-06-01', supported: false },
  { kind: 'permit_issued', label: 'Railroad Commission permit issued', date: '2027-06-01', supported: false },
  { kind: 'planning', label: 'Application mentions energization and commissioning', date: '2027-06-01', supported: false },
]) {
  test(`energization requires a supported lifecycle type: ${event.kind}`, async ({ page }) => {
    await installSyntheticApi(page, event)
    await page.goto('/?view=workspace&groupBrowse=1')
    await expect(page.locator('.premium-account-card')).toHaveCount(3)
    const timing = page.locator('.premium-account-card').first().locator('.premium-energization')
    if (event.supported) {
      await expect(timing).toContainText('Commissioning expected')
      await expect(timing).toContainText('2027-06-01')
    } else await expect(timing).toHaveCount(0)
  })
}

test('account actions remain reachable in a short landscape viewport', async ({ page }) => {
  await installSyntheticApi(page)
  await page.setViewportSize({ width: 844, height: 390 })
  await page.goto('/?view=workspace&groupBrowse=1')
  await page.getByRole('button', { name: 'Account menu' }).click()
  const menu = page.locator('.workspace-account__menu')
  const signOut = menu.getByRole('button', { name: 'Sign out', exact: true })
  await signOut.scrollIntoViewIfNeeded()
  const bounds = await signOut.boundingBox()
  expect(bounds).not.toBeNull()
  expect(bounds!.y).toBeGreaterThanOrEqual(0)
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(390)
})

for (const kind of ['source_context', undefined, 'supported_gap', 'activity_requirement', 'facility_demand']) {
  test(`legacy power summary preserves claim scope: ${kind ?? 'missing kind'}`, async ({ page }) => {
    await installSyntheticApi(page)
    await page.route('**/api/opportunities/groups?*', route => route.fulfill({ json: {
      items: [{ id: 'cg_power_scope', name: 'Synthetic power scope account', group_kind: 'resolved_identity', role: 'customer', project_count: 1, need_count: 1, sectors: ['data_centers'], featured_project: {
        id: 'project_power_scope', project_id: 'project_power_scope', name: 'Synthetic power scope project', company: 'Synthetic power scope account', location: 'Synthetic, TX', sector: 'data_centers', asset_type: 'data_center', priority_score: null,
        representative_need_id: 'need_power_scope', needs: [{ id: 'need_power_scope', project_id: 'project_power_scope', name: 'Synthetic power scope project' }], need_count: 1, event: null, contact: [],
        power_summary: '12 MW synthetic source statement; confirm package scope.', power_summary_kind: kind, power_amount_class: 'estimated', next_action: null,
      } }], total: 1, count_unit: 'groups', limit: 25, offset: 0, cohort_token: 'power-scope', generation: 'synthetic',
    } }))
    await page.goto('/?view=workspace&groupBrowse=1')
    const card = page.locator('.premium-account-card')
    await expect(card).toHaveCount(1)
    const power = card.locator('.premium-power')
    await expect(power).toHaveCount(1)
    if (kind === 'activity_requirement' || kind === 'facility_demand') {
      await expect(power).toContainText('12 MW synthetic source statement; confirm package scope.')
      await expect(power).toContainText('Estimated')
      await expect(power.locator('strong')).toHaveText(kind === 'facility_demand' ? 'Facility demand' : 'Power need')
    } else {
      await expect(power).toContainText('Unknown')
      await expect(card).not.toContainText('12 MW')
    }
  })
}
