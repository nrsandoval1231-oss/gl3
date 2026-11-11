import type { Page } from '@playwright/test'

/** Open the Opportunities filter disclosure without closing it when already open. */
export async function openProjectFilters(page: Page) {
  const filters = page.locator('details.premium-filters')
  const route = new URL(page.url()).searchParams
  if (route.get('projectBrowse') === '1' || route.get('accountBrowse') === '1') return
  await filters.waitFor({ state: 'visible' })
  if (!(await filters.evaluate(element => (element as HTMLDetailsElement).open))) {
    await filters.locator('summary').click()
  }
}

/** Fill the project/account search, which is inside the collapsed Filters disclosure. */
export async function fillAccountSearch(page: Page, value: string) {
  await openProjectFilters(page)
  await page.getByRole('textbox', { name: 'Search accounts and projects' }).fill(value)
}

/** Select a ProjectResults sector from its Project type select. */
export async function selectProjectType(page: Page, value: 'all' | 'oil_gas' | 'data_centers') {
  await openProjectFilters(page)
  await page.getByRole('combobox', { name: 'Project type' }).selectOption(value)
}

/** Ensure the workspace account menu has the requested disclosure state. */
export async function setAccountMenuOpen(page: Page, open = true) {
  const trigger = page.getByRole('button', { name: 'Account menu' })
  if ((await trigger.getAttribute('aria-expanded')) !== String(open)) await trigger.click()
}
