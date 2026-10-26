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
  if (!card.members.some((item) => item.id === opportunityId)) {
    throw new Error('Selected Signal does not belong to its project card')
  }
  const cardButton = page.locator(
    `.signals-group header button[data-opportunity-id="${opportunityId}"]`,
  )
  if (await cardButton.getAttribute('aria-expanded') !== null) {
    const groupButton = cardButton
    if (await groupButton.getAttribute('aria-expanded') !== 'true') await groupButton.click()
    await page.locator(`.project-member[data-opportunity-id="${opportunityId}"]`).click()
    return
  }
  await cardButton.click()
}

async function signIn(page: import('@playwright/test').Page) {
  await page.goto('/?tier=Signals')
  await page.getByLabel('Password', { exact: true }).fill(requirePassword())
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByRole('heading', { name: 'Signals', exact: true })).toBeVisible()
}

test('authenticated desktop browse, detail, back, and search use a live Signal', async ({ page }) => {
  await expect((await page.request.get('/api/health')).status()).toBe(401)
  await signIn(page)

  const response = await page.evaluate(async () => {
    const result = await fetch('/api/opportunities?tier=Signal&decision=ALL&sort=rank&limit=25&offset=0')
    return { status: result.status, items: await result.json() as Opportunity[] }
  })
  expect(response.status).toBe(200)
  expect(response.items.length, 'authenticated local API must contain at least one real Signal').toBeGreaterThan(0)
  expect(response.items.every((item) => ['Official permit', 'Official utility filing', 'Temporary-power solicitation', 'Official cultivation application'].includes(item.signal_admission_origin ?? ''))).toBe(true)
  const cards = projectCards(response.items)
  const signal = await page.evaluate(async (items) => {
    for (const item of items) {
      const detailResponse = await fetch(`/api/opportunities/needs/${encodeURIComponent(item.id)}`)
      if (!detailResponse.ok) continue
      const detail = await detailResponse.json() as Opportunity
      if (detail.evidence.length > 0) return detail
    }
    return null
  }, response.items)
  expect(signal, 'a browseable Signal must retain linked source evidence').toBeTruthy()
  if (!signal) throw new Error('No Signal with retained source evidence exists in the local database')
  const signalCard = cards.find((card) => card.members.some((item) => item.id === signal.id))
  if (!signalCard) throw new Error('No project card exists for the selected Signal')

  const title = projectTitle(signal)
  const decision = signalDisplayDecision(signalCard.members)
  await page.getByRole('button', { name: new RegExp(`^${decision}\\s+\\d+$`) }).click()
  const row = page.locator(`[data-opportunity-id="${signal.id}"]`).first()
  await expect(row).toBeVisible()
  await page.getByRole('textbox', { name: 'Search projects' }).fill(title)
  await expect(row).toBeVisible()
  await openCardMember(page, signalCard, signal.id)
  await expect(page.getByRole('heading', { level: 2, name: title })).toBeVisible()
  await page.getByRole('navigation', { name: 'Opportunity detail' }).getByRole('button', { name: 'Evidence', exact: true }).click()
  await expect(page.getByText(signal.evidence[0].source_id, { exact: false }).first()).toBeVisible()
  await expect(page.getByRole('complementary', { name: 'Opportunity detail' }).getByRole('cell', { name: signal.signal_admission_origin ?? '', exact: true })).toBeVisible()
  await page.screenshot({ path: test.info().outputPath('live-desktop.png'), fullPage: true })
  await page.getByRole('button', { name: /Back to power needs/ }).click()
  await expect(page.getByRole('textbox', { name: 'Search projects' })).toHaveValue(title)
  await expect(page.locator(`[data-opportunity-id="${signal.id}"]`).first()).toBeFocused()

  await openCardMember(page, signalCard, signal.id)
  await expect(page.getByRole('heading', { level: 2, name: title })).toBeVisible()
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
  await expect(page.getByRole('navigation', { name: 'Primary navigation' }).getByRole('button')).toHaveCount(3)
  await page.locator('.wh-account summary').click()
  await page.getByRole('button', { name: 'Technical diagnostics' }).click()
  await expect(page.getByRole('heading', { name: 'Ingestion inbox' })).toBeVisible()
  await expect(page.locator('.wh-ingestion-row').first()).toContainText(inbox.page.items[0].title)

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
  await expect(page.locator('.wh-ingestion-row').first()).toContainText('City of El Paso')
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
  await expect(page.locator('.wh-ingestion-row').first()).toContainText(inbox.page.items[0].title)
  await sourceFilter.selectOption('el-paso-new-commercial-permits')
  await page.getByRole('navigation', { name: 'Primary navigation' }).getByRole('button', { name: 'Research' }).click()
  await expect(page.getByRole('heading', { name: 'Research', exact: true })).toBeVisible()
  await expect(page.getByText(/Source-backed research progress/)).toBeVisible()
  await page.goBack()
  await expect(page.getByRole('heading', { name: 'Ingestion inbox' })).toBeVisible()
  await expect(page.locator('.wh-ingestion-row').first()).toBeVisible()
  await expect(sourceFilter).toHaveValue('el-paso-new-commercial-permits')

  await expect(page.getByRole('heading', { name: 'Source health' })).toBeVisible()
  await page.screenshot({ path: test.info().outputPath('live-mobile-health.png') })
  const rows = page.locator('.wh-source-row')
  await expect(rows.first()).toBeVisible()
  const rowCount = await rows.count()
  expect(rowCount, 'the populated local database must expose configured source health').toBeGreaterThan(0)
  const panel = await page.locator('.operations-view .wh-panel').first().boundingBox()
  expect(panel).toBeTruthy()
  for (let index = 0; index < rowCount; index += 1) {
    const row = rows.nth(index)
    const bounds = await row.boundingBox()
    expect(bounds && panel && bounds.x >= panel.x && bounds.x + bounds.width <= panel.x + panel.width).toBeTruthy()
    await expect(row.locator('span').first()).toBeVisible()
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


test('retained out-of-region permits remain inspectable without active Signals', async ({ page }) => {
  await signIn(page)
  const retained = await page.evaluate(async () => {
    const sources = ['georgia-air-draft-title-v', 'chicago-building-permits']
    const observations = await Promise.all(sources.map(async (source_id) => {
      const response = await fetch(`/api/ingestion?source_id=${encodeURIComponent(source_id)}&limit=100`)
      return { source_id, ...(await response.json()) as { items: { title: string; citation_url: string; reported_power_facts: string[] }[] } }
    }))
    const health = await fetch('/api/health').then(response => response.json()) as { sources: { id: string; enabled: boolean; status: string }[] }
    const signals: Opportunity[] = []
    let offset = 0
    let cohort = ''
    do {
      const params = new URLSearchParams({ tier: 'Signal', decision: 'ALL', sort: 'rank', limit: '50', offset: String(offset) })
      if (cohort) params.set('cohort_token', cohort)
      const response = await fetch(`/api/opportunities?${params}`)
      signals.push(...await response.json() as Opportunity[])
      cohort = response.headers.get('X-Cohort-Token') ?? cohort
      const next = response.headers.get('X-Next-Offset')
      if (!next) break
      offset = Number(next)
    } while (true)
    return { observations, health, signals }
  })
  const georgia = retained.observations.find(item => item.source_id === 'georgia-air-draft-title-v')
  const chicago = retained.observations.find(item => item.source_id === 'chicago-building-permits')
  expect(georgia?.items.length, 'Georgia air evidence must remain in retained ingestion').toBeGreaterThan(0)
  expect(chicago?.items.length, 'Chicago permit evidence must remain in retained ingestion').toBeGreaterThan(0)
  const powerRecord = georgia?.items.find(item => item.reported_power_facts.length > 0)
  expect(powerRecord, 'source equipment claims must remain preserved as source facts').toBeTruthy()
  for (const sourceId of ['georgia-air-draft-title-v', 'chicago-building-permits']) {
    const source = retained.health.sources.find(item => item.id === sourceId)
    expect(source?.enabled, `${sourceId} must remain disabled outside the active region`).toBe(false)
    expect(source?.status).toBe('Disabled')
  }
  expect(retained.signals.some(item => /(?:,\s*(?:GA|IL)\b|Georgia|Illinois)/i.test(item.location ?? ''))).toBe(false)

  await page.locator('.wh-account summary').click()
  await page.getByRole('button', { name: 'Technical diagnostics' }).click()
  await expect(page.getByRole('heading', { name: 'Ingestion inbox' })).toBeVisible()
  const sourceFilter = page.getByLabel('Filter by source', { exact: true })
  await sourceFilter.selectOption('georgia-air-draft-title-v')
  await expect(page.locator('.wh-ingestion-row').first()).toBeVisible()
  const row = page.locator('.wh-ingestion-row').filter({
    has: page.getByRole('link', { name: powerRecord!.title, exact: true }),
  }).first()
  const inboxPaging = page.locator('.wh-paging')
  const nextInboxPage = inboxPaging.getByRole('button', { name: 'Next' })
  while (await row.count() === 0 && await nextInboxPage.isEnabled()) {
    const priorPage = await inboxPaging.locator('span').innerText()
    await nextInboxPage.click()
    await expect(inboxPaging.locator('span')).not.toHaveText(priorPage)
  }
  await expect(row).toBeVisible()
  await row.getByText('Reported power figures', { exact: true }).click()
  await expect(row).toContainText(powerRecord!.reported_power_facts[0])
  await expect(row.locator('a').first()).toHaveAttribute('href', powerRecord!.citation_url)
  await sourceFilter.selectOption('chicago-building-permits')
  await expect(page.locator('.wh-ingestion-row').first()).toBeVisible()
  await expect(page.locator('.wh-ingestion-row').first()).toContainText(chicago!.items[0].title)
  await expect(page.locator('.wh-source-row').filter({ hasText: 'georgia-air-draft-title-v' })).toContainText('Disabled')
  await expect(page.locator('.wh-source-row').filter({ hasText: 'chicago-building-permits' })).toContainText('Disabled')

  await page.getByRole('button', { name: 'Signals', exact: true }).click()
  await page.getByText('Geography, industry, activity, timing, size and priority filters').click()
  await page.getByLabel('Geography', { exact: true }).fill('Georgia')
  await expect(page.locator('.wh-empty')).toContainText('No Signals match these filters.')
})

test('retained Texas data-center permits preserve organization attribution and unknown buyer authority', async ({ page }) => {
  await signIn(page)
  const proof = await page.evaluate(async () => {
    const response = await fetch('/api/opportunities?tier=Signal&decision=ALL&sort=rank&search=data%20center&limit=50&offset=0')
    const items = await response.json() as Opportunity[]
    for (const item of items) {
      if (!/\bTX\b/i.test(item.location ?? '')) continue
      const detailResponse = await fetch(`/api/opportunities/needs/${encodeURIComponent(item.id)}`)
      if (!detailResponse.ok) continue
      const detail = await detailResponse.json() as Opportunity
      const chainResponse = await fetch(`/api/projects/${encodeURIComponent(item.project_id)}/buying-chain`)
      if (!chainResponse.ok) continue
      const chain = await chainResponse.json() as import('../src/api/client').BuyingChainResult
      const candidate = chain.candidates?.find(value => value.organization_relationship === 'DIRECT' && value.person_project_relationship === 'UNKNOWN' && value.person_name === null)
      if (candidate && chain.permit_summaries?.length && detail.evidence?.length) return { items, item, detail, chain, candidate }
    }
    return null
  })
  expect(proof, 'retained Texas permit and organization claims must preserve unknown person-to-project authority').toBeTruthy()
  if (!proof) throw new Error('No retained Texas permit with attributed organization and unknown buyer authority is available')
  expect(proof.chain.permit_summaries?.length).toBeGreaterThan(0)
  expect(proof.candidate.organization_relationship).toBe('DIRECT')
  expect(proof.candidate.person_name).toBeNull()
  expect(proof.candidate.person_project_relationship).toBe('UNKNOWN')
  expect(proof.candidate.evidence?.length).toBeGreaterThan(0)
  expect(proof.candidate.evidence?.some(evidence => /^https:\/\//.test(evidence.url))).toBe(true)

  await page.goto('/?view=signals&tier=Signals&decision=ALL&q=data%20center')
  const card = projectCards(proof.items).find(candidate => candidate.members.some(item => item.id === proof.item.id))
  if (!card) throw new Error('The retained Texas permit is absent from its live Signal card')
  const decision = signalDisplayDecision(card.members)
  await page.getByRole('button', { name: new RegExp(`^${decision}\\s+\\d+$`) }).click()
  await openCardMember(page, card, proof.item.id)
  const detailNavigation = page.getByRole('navigation', { name: 'Opportunity detail' })
  await detailNavigation.getByRole('button', { name: 'Buying Chain', exact: true }).click()
  const section = page.getByRole('region', { name: 'Buying Chain', exact: true })
  await expect(section.getByRole('heading', { name: 'Retained permit facts' })).toBeVisible()
  const retainedCandidate = section.locator(`[data-context-owner="${proof.candidate.id}"]`)
  await expect(retainedCandidate.getByRole('heading', { name: proof.candidate.organization, exact: true })).toBeVisible()
  await expect(retainedCandidate).toContainText('Person → project')
  await expect(retainedCandidate).toContainText('Project relationship unknown')
  await expect(section.getByRole('link', { name: 'Inspect retained claim history' }))
    .toHaveAttribute('href', /\/buying-chain\?history=true$/)
})
