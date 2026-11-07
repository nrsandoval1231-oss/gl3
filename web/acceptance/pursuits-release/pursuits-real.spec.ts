import { expect, test, type Page } from '@playwright/test'
import { readFile } from 'node:fs/promises'

type Manifest = {
  synthetic_fixture: true
  migration_revision: '0050_commercial_pursuits'
  target_need_id: string
  target_group_id: string
  target_name: string
  target_group_name: string
}
type ApiResponse = { path: string; method: string; status: number }
type TaskBody = { description: string; due_date: string | null; client_id: string }

const manifestPath = process.env.PURSUITS_RELEASE_REAL_MANIFEST
const password = process.env.PURSUITS_RELEASE_REAL_PASSWORD
if (!manifestPath) throw new Error('Set PURSUITS_RELEASE_REAL_MANIFEST to the sanitized local seed manifest.')
if (!password) throw new Error('Set PURSUITS_RELEASE_REAL_PASSWORD for the disposable API only.')
const manifestPromise = readFile(manifestPath, 'utf8').then(raw => JSON.parse(raw) as Manifest)

function isLoopback(url: URL) {
  return ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)
}

async function signIn(page: Page) {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
  await page.getByLabel('Password', { exact: true }).fill(password!)
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Opportunities' })).toBeVisible()
  const health = await page.request.get('/api/health')
  expect(health.status()).toBe(200)
}

test('real API persists one pursuit, task retry, and serves normal navigation reads', async ({ page }) => {
  const manifest = await manifestPromise
  expect(manifest.synthetic_fixture).toBe(true)
  expect(manifest.migration_revision).toBe('0050_commercial_pursuits')
  const external = new Set<string>()
  const responses: ApiResponse[] = []
  const taskBodies: TaskBody[] = []
  let firstTaskReplyDropped = false

  await page.context().route('**/*', async route => {
    const url = new URL(route.request().url())
    if (!['http:', 'https:'].includes(url.protocol) || !isLoopback(url)) {
      external.add(`${route.request().method()} ${url.origin}${url.pathname}`)
      return route.abort()
    }
    return route.continue()
  })
  page.on('response', response => {
    const url = new URL(response.url())
    if (url.pathname.startsWith('/api/')) {
      responses.push({ path: url.pathname, method: response.request().method(), status: response.status() })
    }
  })
  await page.route('**/api/commercial-pursuits/*/tasks', async route => {
    if (route.request().method() !== 'POST' || new URL(route.request().url()).pathname.split('/').at(-1) !== 'tasks') {
      return route.continue()
    }
    const body = route.request().postDataJSON() as TaskBody
    taskBodies.push(body)
    const stored = await route.fetch()
    expect([200, 201]).toContain(stored.status())
    if (!firstTaskReplyDropped) {
      firstTaskReplyDropped = true
      // The real backend commits the task; only the browser's first response is lost.
      return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'simulated lost response' }) })
    }
    return route.fulfill({ response: stored })
  })

  await signIn(page)
  const needUrl = `/?view=workspace&need=${encodeURIComponent(manifest.target_need_id)}`
  const needResponse = page.waitForResponse(response => {
    const url = new URL(response.url())
    return url.pathname === `/api/opportunities/needs/${manifest.target_need_id}`
  })
  await page.goto(needUrl)
  expect((await needResponse).status()).toBe(200)
  const detail = page.locator('.cod-panel')
  await expect(detail).toBeVisible()
  await expect(detail).toContainText(manifest.target_name)
  const add = detail.getByRole('button', { name: 'Add to Pursuit' })
  await expect(add).toBeEnabled()
  await expect(page.getByTestId('nav-badge-pursuits')).toHaveCount(0)

  const createResponse = page.waitForResponse(response =>
    response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/commercial-pursuits',
  )
  await add.dblclick()
  const created = await createResponse
  expect(created.status()).toBe(201)
  const createdPursuit = await created.json() as { id: string; need_id: string }
  expect(createdPursuit.need_id).toBe(manifest.target_need_id)
  await expect(detail.getByRole('link', { name: 'In Pursuits' })).toHaveAttribute('href', `/?view=pursuits&pursuit=${createdPursuit.id}`)
  await expect(page.getByTestId('nav-badge-pursuits')).toHaveText('1')
  const duplicate = await page.evaluate(async needId => {
    const response = await fetch('/api/commercial-pursuits', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ need_id: needId }),
    })
    return { status: response.status, body: await response.json() as { id: string; need_id: string } }
  }, manifest.target_need_id)
  expect(duplicate.status).toBe(200)
  expect(duplicate.body.id).toBe(createdPursuit.id)
  const persisted = await page.request.get(`/api/commercial-pursuits?need_id=${encodeURIComponent(manifest.target_need_id)}`)
  expect(persisted.status()).toBe(200)
  const persistedBody = await persisted.json() as { items: Array<{ id: string; need_id: string }>; total_matching: number }
  expect(persistedBody.items).toHaveLength(1)
  expect(persistedBody.items[0].id).toBe(createdPursuit.id)

  await page.goto(`/?view=pursuits&pursuit=${createdPursuit.id}`)
  await expect(page.getByRole('heading', { name: manifest.target_name })).toBeVisible()
  const taskInput = page.getByRole('textbox', { name: 'Follow-up description' })
  await taskInput.fill('Confirm project follow-up')
  const taskButton = page.getByRole('button', { name: 'Add follow-up' })
  await taskButton.click()
  await expect(page.getByRole('alert')).toContainText(/503|simulated lost response/i)
  await expect(taskInput).toHaveValue('Confirm project follow-up')
  await taskButton.click()
  await expect(page.getByText('Confirm project follow-up', { exact: true })).toBeVisible()
  expect(taskBodies).toHaveLength(2)
  expect(taskBodies[0].client_id).toMatch(/^[0-9a-f-]{36}$/i)
  expect(taskBodies[1].client_id).toBe(taskBodies[0].client_id)
  const afterRetry = await page.request.get(`/api/commercial-pursuits/${createdPursuit.id}`)
  const detailAfterRetry = await afterRetry.json() as { tasks: Array<{ id: string; description: string }> }
  expect(detailAfterRetry.tasks.filter(task => task.description === 'Confirm project follow-up')).toHaveLength(1)
  expect(detailAfterRetry.tasks.find(task => task.description === 'Confirm project follow-up')?.id).toBe(taskBodies[0].client_id)

  // Group browse must resolve the same persisted opportunity and show the existing pursuit.
  const groupResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/opportunities/groups')
  await page.goto(`/?view=workspace&groupBrowse=1&need=${encodeURIComponent(manifest.target_need_id)}`)
  const groups = await groupResponse
  expect(groups.status(), await groups.text()).toBe(200)
  await expect(page.locator('.wh-detail')).toBeVisible()
  await expect(page.locator('.wh-detail').getByRole('link', { name: 'In Pursuits' })).toHaveAttribute('href', `/?view=pursuits&pursuit=${createdPursuit.id}`)
  await expect(page.getByTestId('nav-badge-pursuits')).toHaveText('1')

  await page.getByRole('button', { name: 'Companies' }).click()
  await expect(page.getByRole('heading', { name: 'Companies', exact: true })).toBeVisible()
  await expect.poll(() => responses.some(item => item.path === '/api/opportunities/groups' && item.status === 200)).toBe(true)

  await page.getByRole('button', { name: 'Reports' }).click()
  await expect(page.getByRole('heading', { name: 'Reports', exact: true })).toBeVisible()
  await expect.poll(() => responses.some(item => item.path === '/api/opportunities/projects' && item.status === 200)).toBe(true)
  await expect.poll(() => responses.some(item => item.path === '/api/opportunities/demand-summary' && item.status === 200)).toBe(true)

  await page.goto('/?view=research')
  await expect(page.getByRole('heading', { name: 'Research', exact: true })).toBeVisible()
  await expect.poll(() => responses.some(item => item.path === '/api/opportunities/workspace' && item.status === 200)).toBe(true)
  expect([...external]).toEqual([])
  const failedUnexpectedApi = responses.filter(item => item.status >= 500 && !(item.method === 'POST' && item.path.endsWith('/tasks') && item.status === 503))
  expect(failedUnexpectedApi).toEqual([])
})
