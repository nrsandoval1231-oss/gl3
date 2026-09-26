import { expect, test } from '@playwright/test'
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const credentialPath = resolve(process.cwd(), '../.artifacts/local-auth.txt')
const password = process.env.GRIDLENS_TEST_PASSWORD ?? (existsSync(credentialPath) ? readFileSync(credentialPath, 'utf8').split(/\r?\n/)[1] : undefined)

test('private browse/detail keeps context and source health fits a phone', async ({ page, request }) => {
  test.skip(!password, 'Set GRIDLENS_TEST_PASSWORD and provide a populated local database to run the authenticated browser proof')
  const activePassword = password ?? ''
  expect((await request.get('/api/health')).status()).toBe(401)
  await page.goto('/')
  await page.getByLabel('Password').fill(activePassword)
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByRole('heading', { name: 'Signals', exact: true })).toBeVisible()

  const search = page.getByRole('textbox', { name: 'Search projects' })
  await search.fill('Roca Honda')
  const signal = page.getByRole('button', { name: /Roca Honda Mine Project/i })
  await expect(signal).toBeVisible()
  await signal.click()
  await expect(page.getByRole('heading', { level: 1, name: /Roca Honda Mine Project/i })).toBeVisible()
  await expect(page.getByText('2026-09-14').first()).toBeVisible()
  const unknownEvents = page.getByText('Described event: Unknown', { exact: true })
  const unknownEventCount = await unknownEvents.count()
  expect(unknownEventCount).toBeGreaterThan(0)
  for (let index = 0; index < unknownEventCount; index += 1) {
    await expect(unknownEvents.nth(index)).toBeVisible()
  }
  await page.getByRole('button', { name: /Back to Signals/ }).click()
  await expect(page.getByRole('textbox', { name: 'Search projects' })).toHaveValue('Roca Honda')
  await expect(page.getByRole('button', { name: /Roca Honda Mine Project/i })).toBeFocused()

  await page.getByRole('button', { name: /Roca Honda Mine Project/i }).click()
  await page.goBack()
  await expect(page.getByRole('button', { name: /Roca Honda Mine Project/i })).toBeFocused()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: 'Source health' }).click()
  await expect(page.getByRole('heading', { name: 'Source health' })).toBeVisible()
  const rows = page.locator('.health-row')
  const rowCount = await rows.count()
  expect(rowCount).toBeGreaterThan(0)
  const panel = await page.locator('.health-panel').boundingBox()
  expect(panel).toBeTruthy()
  for (let index = 0; index < rowCount; index += 1) {
    const row = rows.nth(index)
    const bounds = await row.boundingBox()
    expect(bounds && panel && bounds.x >= panel.x && bounds.x + bounds.width <= panel.x + panel.width).toBeTruthy()
    await expect(row.locator('.status')).toBeVisible()
    await expect(row).toContainText(/Latest publication (?:\d{4}-\d{2}-\d{2}|unknown)/i)
    await expect(row).toContainText(/\d+ new · \d+ changed · \d+ parse failures/)
  }
  const widths = await page.evaluate(() => ({ page: document.documentElement.scrollWidth, viewport: document.documentElement.clientWidth }))
  expect(widths.page).toBeLessThanOrEqual(widths.viewport)
})
