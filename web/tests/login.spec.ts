import { expect, test, type Page, type Route } from '@playwright/test'

type LoginResponse = (route: Route) => Promise<void>

async function mockApi(page: Page, loginResponse: LoginResponse) {
  await page.route('**/*', async (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (!pathname.startsWith('/api/')) return route.continue()
    if (pathname === '/api/auth/session') return route.fulfill({ json: { authenticated: false } })
    if (pathname === '/api/auth/login') return loginResponse(route)
    return route.fulfill({ json: [] })
  })
}

for (const [label, path] of [['workspace', '/?tier=Signals'], ['environment', '/?view=environment']] as const) {
  test(`${label} login responds at desktop and phone sizes, then retries after a rejected password`, async ({ page }, testInfo) => {
    let loginCount = 0
    await mockApi(page, async (route) => {
      loginCount += 1
      if (loginCount === 1) return route.fulfill({ status: 401, json: { detail: 'private auth provider text' } })
      return route.fulfill({ json: { authenticated: true } })
    })
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto(path)
    await expect(page.getByRole('heading', { name: 'Sign in to GridLens' })).toBeVisible()
    await expect(page.getByRole('img', { name: 'GridLens' })).toBeVisible()
    await expect(page.getByLabel('Password', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)

    if (label === 'workspace') await page.screenshot({ path: testInfo.outputPath('login-1440x900.png') })
    await page.setViewportSize({ width: 390, height: 844 })
    const password = page.getByLabel('Password', { exact: true })
    await expect(password).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    expect(await password.evaluate(el => el.parentElement!.getBoundingClientRect().right <= document.querySelector('.login-panel-inner')!.getBoundingClientRect().right)).toBe(true)
    if (label === 'workspace') await page.screenshot({ path: testInfo.outputPath('login-390x844.png') })
    await expect(password).toHaveAttribute('type', 'password')
    await expect(password).toHaveAttribute('autocomplete', 'current-password')
    await password.fill('synthetic-password')
    await password.press('Enter')
    await expect(page.getByRole('alert')).toHaveText('That password was not accepted. Check it and try again.')
    await expect(password).toBeFocused()
    await expect(password).toHaveAttribute('aria-invalid', 'true')
    await expect(password).toHaveAttribute('type', 'password')
    expect(await page.evaluate(() => location.href.includes('synthetic-password'))).toBe(false)
    expect(await page.evaluate(() => [...Object.keys(localStorage), ...Object.keys(sessionStorage)].some((key) => `${key}:${localStorage.getItem(key) ?? sessionStorage.getItem(key)}`.includes('synthetic-password')))).toBe(false)

    await password.press('Enter')
    await expect(page.getByRole('heading', { name: 'Sign in to GridLens' })).toHaveCount(0)
    expect(loginCount).toBe(2)
  })

  test(`${label} login validates required input and suppresses repeated submissions while pending`, async ({ page }) => {
    let loginCount = 0
    let releaseLogin!: () => void
    const deferredLogin = new Promise<void>((resolve) => { releaseLogin = resolve })
    await mockApi(page, async (route) => {
      loginCount += 1
      await deferredLogin
      return route.fulfill({ json: { authenticated: true } })
    })
    await page.goto(path)
    const password = page.getByLabel('Password', { exact: true })
    expect(await password.evaluate((el: HTMLInputElement) => el.checkValidity())).toBe(false)
    await password.fill('synthetic-password')
    await password.focus()
    await password.press('Enter')
    await expect(page.getByRole('status')).toHaveText('Signing in to your private workspace.')
    await expect(page.locator('.login-form')).toHaveAttribute('aria-busy', 'true')
    await expect(page.getByRole('button', { name: 'Signing in' })).toBeDisabled()
    await expect.poll(() => loginCount).toBe(1)

    await page.locator('.login-form').evaluate((form: HTMLFormElement) => { form.requestSubmit(); form.requestSubmit() })
    await password.press('Enter')
    expect(loginCount).toBe(1)
    await page.emulateMedia({ reducedMotion: 'reduce' })
    expect(await page.locator('.login-submit').evaluate((el) => getComputedStyle(el).transitionDuration)).toBe('0s')
    releaseLogin()
    await expect(page.getByRole('heading', { name: 'Sign in to GridLens' })).toHaveCount(0)
    expect(loginCount).toBe(1)
  })

  test(`${label} login gives safe rate-limit guidance`, async ({ page }) => {
    await mockApi(page, (route) => route.fulfill({ status: 429, json: { detail: 'sensitive provider response' } }))
    await page.goto(path)
    await page.getByLabel('Password', { exact: true }).fill('synthetic-password')
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page.getByRole('alert')).toHaveText('Too many sign-in attempts. Wait a moment, then try again.')
  })

  test(`${label} login gives safe network guidance`, async ({ page }) => {
    await mockApi(page, (route) => route.abort('failed'))
    await page.goto(path)
    await page.getByLabel('Password', { exact: true }).fill('synthetic-password')
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page.getByRole('alert')).toHaveText('GridLens could not be reached. Check your connection and try again.')
  })
}

for (const [width, height] of [[1280, 853], [1440, 900], [768, 1024], [390, 844], [320, 568]]) {
  test(`approved sign-in composition at ${width}x${height}`, async ({ page }, testInfo) => {
    await mockApi(page, (route) => route.fulfill({ status: 401, json: { detail: 'Invalid credentials' } }))
    await page.setViewportSize({ width, height })
    await page.goto('/?tier=Signals')
    await expect(page.getByRole('heading', { name: 'Sign in to GridLens' })).toBeVisible()
    await expect(page.getByText('Real projects. Real power.')).toBeVisible()
    await expect(page.getByRole('textbox', { name: /email/i })).toHaveCount(0)
    await expect(page.getByRole('button', { name: /Google|Microsoft|Sign up/ })).toHaveCount(0)
    await expect(page.getByText('Contact your workspace administrator')).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    const password = page.getByLabel('Password', { exact: true })
    await password.fill('synthetic-password')
    await page.getByRole('button', { name: 'Show password' }).click()
    await expect(password).toHaveAttribute('type', 'text')
    await page.getByRole('button', { name: 'Hide password' }).click()
    await expect(password).toHaveAttribute('type', 'password')
    await password.fill('')
    await page.evaluate(async () => { await document.fonts.ready; (document.activeElement as HTMLElement)?.blur() })
    await page.screenshot({ path: testInfo.outputPath(`sign-in-${width}x${height}.png`), fullPage: true })
  })
}

test('sign-in keyboard order and mobile imagery stay focused on access', async ({ page }) => {
  const imageRequests: string[] = []
  page.on('request', request => { if (request.url().includes('/ui/sign-in/')) imageRequests.push(request.url()) })
  await page.setViewportSize({ width: 390, height: 844 })
  await mockApi(page, route => route.fulfill({ status: 401, json: { detail: 'Invalid credentials' } }))
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Sign in to GridLens' })).toBeVisible()
  await page.keyboard.press('Tab')
  await expect(page.getByLabel('Password', { exact: true })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'Show password' })).toBeFocused()
  await page.keyboard.press('Space')
  await expect(page.getByLabel('Password', { exact: true })).toHaveAttribute('type', 'text')
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeFocused()
  expect(imageRequests).toEqual([])
})
