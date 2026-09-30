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
  const cards = projectCards(response.items)
  const signalCard = cards.find((card) => card.members.some((item) => item.evidence.length > 0))
  const signal = signalCard?.members.find((item) => item.evidence.length > 0)
  expect(signal, 'a browseable Signal must retain linked source evidence').toBeTruthy()
  if (!signal) throw new Error('No Signal with retained source evidence exists in the local database')
  if (!signalCard) throw new Error('No project card exists for the selected Signal')

  const title = projectTitle(signal)
  const decision = signalDisplayDecision(signalCard.members)
  if (decision !== 'SHOW') await page.getByRole('button', { name: new RegExp(`^${decision}\\s+\\d+$`) }).click()
  const row = page.locator('.opportunity-row').filter({ hasText: title }).first()
  await expect(row).toBeVisible()
  await page.getByRole('textbox', { name: 'Search projects' }).fill(title)
  await expect(row).toBeVisible()
  await openCardMember(page, signalCard, signal.id)
  await expect(page.getByRole('heading', { level: 1, name: title })).toBeVisible()
  await expect(page.getByText(signal.evidence[0].source_id, { exact: false }).first()).toBeVisible()
  await page.getByRole('button', { name: /Back to Signals/ }).click()
  await expect(page.getByRole('textbox', { name: 'Search projects' })).toHaveValue(title)
  await expect(page.locator(`[data-opportunity-id="${signal.id}"]`).first()).toBeFocused()

  await openCardMember(page, signalCard, signal.id)
  await expect(page.getByRole('heading', { level: 1, name: title })).toBeVisible()
  await page.goBack()
  await expect(page.locator(`[data-opportunity-id="${signal.id}"]`).first()).toBeFocused()
})

test('mobile health, ingestion inbox, watch, and browser history show actual local data states', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await signIn(page)

  const inbox = await page.evaluate(async () => {
    const result = await fetch('/api/ingestion?limit=1&offset=0&watch_only=false')
    return { status: result.status, page: await result.json() as { items: { title: string }[]; total: number } }
  })
  expect(inbox.status).toBe(200)
  expect(inbox.page.total, 'local retained evidence must populate the ingestion inbox').toBeGreaterThan(0)
  await page.getByRole('button', { name: 'Ingestion' }).click()
  await expect(page.getByRole('heading', { name: 'Ingestion inbox' })).toBeVisible()
  await expect(page.locator('.ingestion-card').first()).toContainText(inbox.page.items[0].title)

  await page.getByRole('button', { name: 'Cannabis watch' }).click()
  await expect(page.getByRole('heading', { name: 'Cannabis business news watch' })).toBeVisible()
  const watch = await page.evaluate(async () => {
    const result = await fetch('/api/ingestion?limit=1&offset=0&watch_only=true&vertical=cannabis')
    return { status: result.status, page: await result.json() as { items: { title: string }[]; total: number } }
  })
  expect(watch.status).toBe(200)
  if (watch.page.total > 0) {
    await expect(page.locator('.ingestion-card').first()).toContainText(watch.page.items[0].title)
  } else {
    await expect(page.getByRole('heading', { name: 'No topic matches in this snapshot' })).toBeVisible()
  }
  await page.goBack()
  await expect(page.getByRole('heading', { name: 'Ingestion inbox' })).toBeVisible()

  await page.getByRole('button', { name: 'Source health' }).click()
  await expect(page.getByRole('heading', { name: 'Source health' })).toBeVisible()
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
