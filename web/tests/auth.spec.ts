import { expect, test } from '@playwright/test'
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const credentialPath = resolve(process.cwd(), '../.artifacts/local-auth.txt')
const password = process.env.GRIDLENS_TEST_PASSWORD ?? (existsSync(credentialPath) ? readFileSync(credentialPath, 'utf8').split(/\r?\n/)[1] : undefined)

test('real session protects the workspace, survives reload, and ends on sign-out', async ({ page }) => {
  if (!password) throw new Error('Set GRIDLENS_TEST_PASSWORD to the password for the disposable test API')

  expect((await page.request.get('/api/health')).status()).toBe(401)
  await page.goto('/?tier=Signals')
  await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Signals', exact: true })).toBeVisible()
  expect((await page.request.get('/api/health')).status()).toBe(200)

  await page.reload()
  await expect(page.getByRole('heading', { name: 'Signals', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
  expect((await page.request.get('/api/health')).status()).toBe(401)
  expect(await (await page.request.get('/api/auth/session')).json()).toEqual({ authenticated: false })
})
