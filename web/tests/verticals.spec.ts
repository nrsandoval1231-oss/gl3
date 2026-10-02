import { expect, test } from '@playwright/test'
import type { Opportunity } from '../src/api/client'

function record(id: string, name: string, decision: 'SHOW' | 'REVIEW' | 'HOLD', projectId = ''): Opportunity {
  return {
    id,
    project_id: projectId,
    name,
    tier: 'Signal',
    activity: 'construction',
    location: 'Boston, MA',
    signal_display_decision: decision,
    signal_display_decision_state: 'adjudicated',
    signal_evidence_state: 'active_evidence',
    evidence: [],
  } as unknown as Opportunity
}

test('source-sector groups preserve the oil and gas URL alias and send canonical filter values', async ({ page }) => {
  const filters: Array<string | null> = []
  await page.route('**/api/auth/session', (route) => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/health', (route) => route.fulfill({ json: { sources: [], backlog: 0, pending_interpretations: 0 } }))
  await page.route('**/api/opportunities**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/changes', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/ingestion**', async (route) => {
    filters.push(new URL(route.request().url()).searchParams.get('vertical'))
    await route.fulfill({ json: { items: [], total: 0 } })
  })

  await page.goto('/?view=ingestion&vertical=oil%20and%20gas')
  const selector = page.getByRole('combobox', { name: 'Filter by source sector' })
  await expect(selector).toHaveValue('oil-and-gas')
  await expect(page).toHaveURL(/vertical=oil-and-gas/)
  await expect.poll(() => filters).toContain('oil-and-gas')
  await expect(selector.locator('option')).toContainText(['Energy & utilities', 'Oil & gas', 'Construction & facilities'])

  await selector.selectOption('energy-and-utilities')
  await expect.poll(() => filters.at(-1)).toBe('energy-and-utilities')
  await expect(selector).toHaveValue('energy-and-utilities')
})

test('source filters list authenticated health sources and send their actual source IDs', async ({ page }) => {
  const selectedSources: Array<string | null> = []
  await page.route('**/api/auth/session', (route) => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/health', (route) => route.fulfill({ json: {
    sources: [
      { id: 'texas-rrc-drilling-permits', status: 'Checked', family: 'oil-and-gas', geography: 'Texas', enabled: true },
      { id: 'boston-building-permits', status: 'Checked', family: 'construction-permits', geography: 'Boston', enabled: true },
    ],
    backlog: 0,
    pending_interpretations: 0,
  } }))
  await page.route('**/api/opportunities**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/changes', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/ingestion**', async (route) => {
    selectedSources.push(new URL(route.request().url()).searchParams.get('source_id'))
    await route.fulfill({ json: { items: [], total: 0 } })
  })

  await page.goto('/?view=ingestion')
  const selector = page.getByRole('combobox', { name: 'Filter by source', exact: true })
  await expect(selector.locator('option')).toContainText(['Texas RRC Drilling Permits', 'Boston Building Permits'])
  await selector.selectOption('texas-rrc-drilling-permits')
  await expect.poll(() => selectedSources.at(-1)).toBe('texas-rrc-drilling-permits')
  await selector.selectOption('boston-building-permits')
  await expect.poll(() => selectedSources.at(-1)).toBe('boston-building-permits')
})

test('All Signals labels cards and every member of a mixed decision group', async ({ page }) => {
  const records = [
    record('show-member', 'Shared project', 'SHOW', 'shared-project'),
    record('hold-member', 'Shared project', 'HOLD', 'shared-project'),
    record('review-card', 'Review project', 'REVIEW'),
    record('hold-card', 'Held project', 'HOLD'),
  ]
  await page.route('**/api/auth/session', (route) => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/health', (route) => route.fulfill({ json: { sources: [], backlog: 0, pending_interpretations: 0 } }))
  await page.route('**/api/changes', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/opportunities**', (route) => route.fulfill({ json: records }))

  await page.goto('/')
  await expect(page.getByRole('button', { name: 'All 3' })).toHaveAttribute('aria-pressed', 'true')
  const cardBadges = page.locator('.opportunity-row [data-review-decision]')
  await expect(cardBadges).toHaveCount(3)
  await expect(cardBadges).toHaveText(['Decision: SHOW', 'Decision: REVIEW', 'Decision: HOLD'])

  const mixedCard = page.locator('.project-card').filter({ hasText: 'Shared project' }).first()
  await mixedCard.locator('.opportunity-row').click()
  await expect(mixedCard.locator('.project-member[data-opportunity-id="show-member"] [data-review-decision]')).toHaveText('Decision: SHOW')
  await expect(mixedCard.locator('.project-member[data-opportunity-id="hold-member"] [data-review-decision]')).toHaveText('Decision: HOLD')

  await page.getByRole('button', { name: 'SHOW 1' }).click()
  await expect(page.locator('.opportunity-row [data-review-decision]')).toHaveText(['Decision: SHOW'])
  await page.getByRole('button', { name: 'REVIEW 1' }).click()
  await expect(page.locator('.opportunity-row [data-review-decision]')).toHaveText(['Decision: REVIEW'])
  await page.getByRole('button', { name: 'HOLD 1' }).click()
  await expect(page.locator('.opportunity-row [data-review-decision]')).toHaveText(['Decision: HOLD'])
})
