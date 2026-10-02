import { expect, test } from '@playwright/test'
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import type { Opportunity } from '../src/api/client'
import { projectCards, projectTitle, signalDisplayDecision } from '../src/features/opportunities/projectCards'

const credentialPath = resolve(process.cwd(), '../.artifacts/local-auth.txt')
const password = process.env.GRIDLENS_TEST_PASSWORD ?? (existsSync(credentialPath) ? readFileSync(credentialPath, 'utf8').split(/\r?\n/)[1] : undefined)

function requirePassword() {
  if (!password) throw new Error('Authenticated browser proof requires GRIDLENS_TEST_PASSWORD or ../.artifacts/local-auth.txt')
  return password
}

async function openCardMember(
  page: import('@playwright/test').Page,
  card: ReturnType<typeof projectCards>[number],
  opportunityId: string,
) {
  if (card.grouped) {
    const group = page.locator('.opportunity-row').filter({ hasText: projectTitle(card.members[0]) }).first()
    if (await group.getAttribute('aria-expanded') !== 'true') await group.click()
    await page.locator(`.project-member[data-opportunity-id="${opportunityId}"]`).click()
    return
  }
  await page.locator(`.opportunity-row[data-opportunity-id="${opportunityId}"]`).click()
}

async function signIn(page: import('@playwright/test').Page) {
  await page.goto('/')
  await page.getByLabel('Password').fill(requirePassword())
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByRole('heading', { name: 'Signals', exact: true })).toBeVisible()
}

test('authenticated desktop browse, detail, back, and search use a live Signal', async ({ page }) => {
  await expect((await page.request.get('/api/health')).status()).toBe(401)
  await signIn(page)

  const response = await page.evaluate(async () => {
    const result = await fetch('/api/opportunities?tier=Signal')
    return { status: result.status, items: await result.json() as Opportunity[] }
  })
  expect(response.status).toBe(200)
  expect(response.items.length, 'authenticated local API must contain at least one real Signal').toBeGreaterThan(0)
  expect(response.items.every((item) => ['Official permit', 'Official utility filing', 'Temporary-power solicitation', 'Official cultivation application'].includes(item.signal_admission_origin ?? ''))).toBe(true)
  const cards = projectCards(response.items)
  const signalCard = cards.find((card) => card.members.some((item) => item.evidence.length > 0))
  const signal = signalCard?.members.find((item) => item.evidence.length > 0)
  expect(signal, 'a browseable Signal must retain linked source evidence').toBeTruthy()
  if (!signal) throw new Error('No Signal with retained source evidence exists in the local database')
  if (!signalCard) throw new Error('No project card exists for the selected Signal')

  const title = projectTitle(signal)
  const decision = signalDisplayDecision(signalCard.members)
  await page.getByRole('button', { name: new RegExp(`^${decision}\\s+\\d+$`) }).click()
  const row = page.locator('.opportunity-row').filter({ hasText: title }).first()
  await expect(row).toBeVisible()
  await page.getByRole('textbox', { name: 'Search projects' }).fill(title)
  await expect(row).toBeVisible()
  await openCardMember(page, signalCard, signal.id)
  await expect(page.getByRole('heading', { level: 1, name: title })).toBeVisible()
  await expect(page.getByText(signal.evidence[0].source_id, { exact: false }).first()).toBeVisible()
  await expect(page.getByText(signal.signal_admission_origin ?? '', { exact: true })).toBeVisible()
  await page.screenshot({ path: test.info().outputPath('live-desktop.png'), fullPage: true })
  await page.getByRole('button', { name: /Back to Signals/ }).click()
  await expect(page.getByRole('textbox', { name: 'Search projects' })).toHaveValue(title)
  await expect(page.locator(`[data-opportunity-id="${signal.id}"]`).first()).toBeFocused()

  await openCardMember(page, signalCard, signal.id)
  await expect(page.getByRole('heading', { level: 1, name: title })).toBeVisible()
  await page.goBack()
  await expect(page.locator(`[data-opportunity-id="${signal.id}"]`).first()).toBeFocused()
})

test('mobile health, ordinary news inbox, and browser history show actual local data states', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await signIn(page)

  const inbox = await page.evaluate(async () => {
    const result = await fetch('/api/ingestion?limit=1&offset=0')
    return { status: result.status, page: await result.json() as { items: { title: string }[]; total: number } }
  })
  expect(inbox.status).toBe(200)
  expect(inbox.page.total, 'local retained evidence must populate the ingestion inbox').toBeGreaterThan(0)
  await page.getByRole('button', { name: 'Ingestion' }).click()
  await expect(page.getByRole('heading', { name: 'Ingestion inbox' })).toBeVisible()
  await expect(page.locator('.ingestion-card').first()).toContainText(inbox.page.items[0].title)

  const sourceFilter = page.getByRole('combobox', { name: 'Filter by source', exact: true })
  await sourceFilter.selectOption('el-paso-new-commercial-permits')
  const elPaso = await page.evaluate(async () => {
    const result = await fetch('/api/ingestion?source_id=el-paso-new-commercial-permits&limit=5&offset=0')
    return { status: result.status, page: await result.json() as { items: { source_id: string; event_date_label: string | null; citation_url: string }[]; total: number } }
  })
  expect(elPaso.status).toBe(200)
  expect(elPaso.page.total).toBeGreaterThan(0)
  expect(elPaso.page.items.every((item) => item.source_id === 'el-paso-new-commercial-permits')).toBe(true)
  expect(elPaso.page.items.every((item) => item.event_date_label?.startsWith('ISSUEDATE'))).toBe(true)
  expect(elPaso.page.items.every((item) => item.citation_url.startsWith('https://gis.elpasotexas.gov/arcgis/'))).toBe(true)
  await expect(sourceFilter.locator('option')).toContainText([
    'Dallas Monthly Permits',
    'El Paso New Commercial Permits',
    'Houston Weekly Permits',
  ])
  await expect(page.locator('.ingestion-card').first()).toContainText('City of El Paso')
  await sourceFilter.selectOption('')

  await expect(page.getByRole('navigation', { name: 'Workspace views' }).getByRole('button', { name: 'Cannabis watch' })).toHaveCount(0)
  await expect(sourceFilter.locator('option')).toContainText([
    'Construction Dive News',
    'DCD News',
    'Manufacturing Dive News',
    'MJBizDaily News',
    'OGJ Exploration News',
    'Utility Dive News',
  ])
  await expect(page.locator('.ingestion-card').first()).toContainText(inbox.page.items[0].title)
  await sourceFilter.selectOption('el-paso-new-commercial-permits')
  await page.getByRole('button', { name: 'Today’s pursuits' }).click()
  await expect(page.getByRole('heading', { name: "Today's Power Pursuits" })).toBeVisible()
  await page.goBack()
  await expect(page.getByRole('heading', { name: 'Ingestion inbox' })).toBeVisible()
  await expect(sourceFilter).toHaveValue('el-paso-new-commercial-permits')

  await page.getByRole('button', { name: 'Source health' }).click()
  await expect(page.getByRole('heading', { name: 'Source health' })).toBeVisible()
  await page.screenshot({ path: test.info().outputPath('live-mobile-health.png') })
  const rows = page.locator('.health-row')
  const rowCount = await rows.count()
  expect(rowCount, 'the populated local database must expose configured source health').toBeGreaterThan(0)
  const panel = await page.locator('.health-panel').boundingBox()
  expect(panel).toBeTruthy()
  for (let index = 0; index < rowCount; index += 1) {
    const row = rows.nth(index)
    const bounds = await row.boundingBox()
    expect(bounds && panel && bounds.x >= panel.x && bounds.x + bounds.width <= panel.x + panel.width).toBeTruthy()
    await expect(row.locator('.status')).toBeVisible()
    await expect(row).toContainText(/\d+ new · \d+ changed · \d+ parse failures/)
  }
  const widths = await page.evaluate(() => {
    const viewport = document.documentElement.clientWidth
    const overflowing = [...document.querySelectorAll<HTMLElement>('body *')]
      .map((element) => ({ element, bounds: element.getBoundingClientRect() }))
      .filter(({ element, bounds }) => bounds.right > viewport + 1 || element.scrollWidth > element.clientWidth + 1)
      .map(({ element, bounds }) => ({
        tag: element.tagName,
        className: typeof element.className === 'string' ? element.className : '',
        right: Math.round(bounds.right),
        width: Math.round(bounds.width),
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
        text: element.innerText.slice(0, 100),
      }))
    return { page: document.documentElement.scrollWidth, viewport, overflowing }
  })
  expect(widths.page, JSON.stringify(widths.overflowing)).toBeLessThanOrEqual(widths.viewport)
})


test('live air documents retain equipment context without creating rental MW', async ({ page }) => {
  await signIn(page)
  const items = await page.evaluate(async () => (await fetch('/api/opportunities?tier=Signal')).json() as Promise<Opportunity[]>)
  const air = items.find((item) => item.evidence.some((e) => e.source_id === 'georgia-air-draft-title-v') && Boolean(item.reported_power_facts?.length))
  expect(air, 'ordinary-worker Georgia acceptance must retain source power context').toBeTruthy()
  if (!air) throw new Error('No live air-permit power context is available')
  expect(air.required_mw).toBeNull()
  expect(air.supply).toBe('Unknown')
  const card = projectCards(items).find((candidate) => candidate.members.some((item) => item.id === air.id))
  if (!card) throw new Error('Missing live project card')
  const decision = signalDisplayDecision(card.members)
  await page.getByRole('button', { name: new RegExp(`^${decision}\\s+\\d+$`) }).click()
  await openCardMember(page, card, air.id)
  await expect(page.getByText('Reported power figures (source claims; not rental requirements)')).toBeVisible()
  await expect(page.getByText('Power need is not established. A Signal does not imply a power gap.')).toBeVisible()
  const links = page.locator('.evidence a')
  expect(await links.count()).toBeGreaterThan(1)
  await expect(links.filter({ hasText: 'Georgia EPD narrative' }).first()).toHaveAttribute('href', /^https:\/\/epd\.georgia\.gov\/document\/document\//)
  await page.locator('.detail-section').filter({ hasText: 'Reported power figures (source claims; not rental requirements)' }).screenshot({ path: test.info().outputPath('live-air-detail.png') })
})

test('live data-center permit enrichment exposes attributed fields and organizations', async ({ page }) => {
  await signIn(page)
  const items = await page.evaluate(async () => (await fetch('/api/opportunities?tier=Signal')).json() as Promise<Opportunity[]>)
  const examples = [
    items.find((item) => item.evidence.some((e) => e.source_id === 'chicago-building-permits' && /data center/i.test(e.abstract ?? ''))),
    items.find((item) => item.evidence.some((e) => e.source_id === 'georgia-air-draft-title-v' && /QTS ATL3/.test(e.title))),
  ]
  for (const [index, opportunity] of examples.entries()) {
    expect(opportunity, 'live acceptance requires Chicago and Georgia data-center examples').toBeTruthy()
    if (!opportunity) throw new Error('Missing data-center acceptance example')
    await page.goto('/')
    const card = projectCards(items).find((candidate) => candidate.members.some((item) => item.id === opportunity.id))
    if (!card) throw new Error('Missing data-center card')
    const decision = signalDisplayDecision(card.members)
    await page.getByRole('button', { name: new RegExp(`^${decision}\\s+\\d+$`) }).click()
    await openCardMember(page, card, opportunity.id)
    const section = page.getByRole('region', { name: 'Buying chain' })
    await expect(section.getByRole('heading', { name: 'Retained permit facts' })).toBeVisible()
    const response = page.waitForResponse((r) => r.url().endsWith('/buying-chain/enrich') && r.request().method() === 'POST')
    await section.getByRole('button', { name: 'Enrich buying chain' }).click()
    const enriched = await response
    expect(enriched.ok()).toBe(true)
    const result = await enriched.json() as import('../src/api/client').BuyingChainResult
    expect(result.permit_summaries?.length).toBeGreaterThan(0)
    expect(result.candidates?.length).toBeGreaterThan(0)
    for (const candidate of result.candidates ?? []) {
      expect(candidate.organization_relationship).toBe('DIRECT')
      expect(candidate.person_name).toBeNull()
      expect(candidate.person_project_relationship).toBe('UNKNOWN')
      expect(candidate.public_contacts).toEqual([])
      await expect(section.getByRole('heading', { name: candidate.organization, exact: true })).toBeVisible()
    }
    await section.locator('.permit-summary').screenshot({ path: test.info().outputPath(`live-dc-permit-${index}.png`) })
  }
})
