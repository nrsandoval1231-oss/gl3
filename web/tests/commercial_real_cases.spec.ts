import { expect, test, type Page } from '@playwright/test'
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

type CommercialCase = {
  case_id: string
  project_id: string
  need_id: string
  project_name: string
  company_name?: string
  source_url: string
  source_hash: string
  expected_unknown_keys: string[]
  expected_contact_responsibility?: string
  expected_contact_authority?: string
  expected_contact_method_count?: number
  expected_signal_text?: string
  expected_research_text?: string[]
  no_qualified_gap?: boolean
}

const credentialPath = resolve(process.cwd(), '../.artifacts/local-auth.txt')
const password = process.env.GRIDLENS_TEST_PASSWORD ?? (existsSync(credentialPath) ? readFileSync(credentialPath, 'utf8').split(/\r?\n/)[1] : undefined)
const manifestPath = process.env.GL3_REAL_CASE_MANIFEST ?? resolve(process.cwd(), '../docs/validation/commercial-release-20261026/real-cases.json')
if (!existsSync(manifestPath)) {
  throw new Error(`Missing persisted real-case manifest at ${manifestPath}; synthetic fixtures are not accepted by this project`)
}
const cases = JSON.parse(readFileSync(manifestPath, 'utf8')) as CommercialCase[]
if (!Array.isArray(cases) || cases.length === 0) throw new Error('Real-case manifest must contain at least one persisted case')

async function signIn(page: Page) {
  if (!password) throw new Error('Set GRIDLENS_TEST_PASSWORD or provide ../.artifacts/local-auth.txt for the isolated browser API')
  await page.goto('/?view=workspace')
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await expect(page.getByRole('navigation', { name: 'Primary navigation' })).toBeVisible()
}

for (const item of cases) {
  test(`persisted real case ${item.case_id} retains citations and unknowns across commercial views`, async ({ page }, testInfo) => {
    const writes: string[] = []
    page.on('request', request => {
      const url = new URL(request.url())
      if (url.pathname.startsWith('/api/') && request.method() !== 'GET' && url.pathname !== '/api/auth/login') {
        writes.push(`${request.method()} ${url.pathname}`)
      }
    })
    await signIn(page)

    const response = await page.request.get(`/api/opportunities/needs/${encodeURIComponent(item.need_id)}`)
    expect(response.status(), 'the authenticated workspace must resolve this persisted need').toBe(200)
    const need = await response.json() as {
      id: string
      project_id: string
      name: string
      tier: string
      qualified_remaining_gap?: unknown
      intelligence_card?: {
        fields: { key: string; label: string; value: string | null; status: string }[]
        evidence: { url: string | null; content_hash: string | null; retained_evidence_id: string | null }[]
        power_gap?: unknown
        contacts: { responsibility: string; purchasing_authority: string; sources: unknown[]; methods: unknown[] }[]
      }
    }
    const card = need.intelligence_card
    expect(need.id).toBe(item.need_id)
    expect(need.project_id).toBe(item.project_id)
    expect(need.name).toContain(item.project_name)
    expect(card).toBeTruthy()
    expect(card?.evidence.some(source => source.url === item.source_url && source.content_hash === item.source_hash && source.retained_evidence_id)).toBe(true)
    for (const key of item.expected_unknown_keys) {
      expect(card?.fields.find(field => field.key === key), `field ${key} is represented`).toBeTruthy()
      expect(card?.fields.find(field => field.key === key)?.value, `field ${key} remains unknown`).toBeNull()
    }
    if (item.expected_contact_responsibility || item.expected_contact_authority || item.expected_contact_method_count !== undefined) {
      expect(card?.contacts.length).toBeGreaterThan(0)
      for (const contact of card?.contacts ?? []) {
        expect(contact.sources.length, 'contact attribution retains a source').toBeGreaterThan(0)
        if (item.expected_contact_responsibility) expect(contact.responsibility).toBe(item.expected_contact_responsibility)
        if (item.expected_contact_authority) expect(contact.purchasing_authority).toBe(item.expected_contact_authority)
        if (item.expected_contact_method_count !== undefined) expect(contact.methods).toHaveLength(item.expected_contact_method_count)
      }
    }
    if (item.no_qualified_gap) {
      expect(need.qualified_remaining_gap).toBeFalsy()
      expect(card?.power_gap).toBeFalsy()
    }

    const browseView = need.tier === 'Signal' ? 'signals' : 'workspace'
    await page.goto(`/?view=${browseView}&need=${encodeURIComponent(item.need_id)}`)
    const activeNavigation = page.getByRole('navigation', { name: 'Primary navigation' }).getByRole('button', { name: browseView === 'signals' ? 'Signals' : 'Opportunities', exact: true })
    await expect(activeNavigation).toHaveAttribute('aria-current', 'page')
    if (browseView === 'signals') await expect(page.getByRole('heading', { level: 1, name: 'Signals', exact: true })).toBeVisible()
    if (item.expected_signal_text) await expect(page.getByText(item.expected_signal_text, { exact: false })).toBeVisible()
    await expect(page.getByRole('heading', { level: 2, name: item.project_name, exact: true })).toBeVisible()
    const detail = page.getByRole('complementary', { name: 'Opportunity detail' })
    if (item.company_name) {
      await expect(detail.getByRole('heading', { name: item.company_name, exact: true })).toBeVisible()
      await expect(detail.getByText(/Loading company context/)).toHaveCount(0)
      await expect(detail.getByText(/Checking retained contacts/)).toHaveCount(0)
    }
    await page.screenshot({ path: testInfo.outputPath(`${item.case_id}-signals-desktop.png`), fullPage: true })
    await page.getByRole('button', { name: 'Evidence', exact: true }).click()
    const citation = page.getByRole('region', { name: 'Intelligence card sources' }).getByRole('link', { name: 'Open retained source' })
    await expect(citation).toHaveAttribute('href', item.source_url)
    await page.screenshot({ path: testInfo.outputPath(`${item.case_id}-evidence-desktop.png`), fullPage: true })

    const opportunities = page.getByRole('navigation', { name: 'Primary navigation' }).getByRole('button', { name: 'Opportunities', exact: true })
    await opportunities.click()
    await expect(opportunities).toHaveAttribute('aria-current', 'page')
    const opportunityView = page.getByRole('region', { name: 'Opportunities' })
    await expect(opportunityView).toBeVisible()
    await expect(opportunityView).toContainText(item.project_name)
    if (item.company_name) {
      await opportunityView.getByRole('button', { name: new RegExp(`${item.company_name}.*${item.project_name}`) }).click()
      const selectedOpportunity = page.getByRole('complementary', { name: 'Opportunity detail' })
      await expect(selectedOpportunity.getByRole('heading', { name: item.company_name, exact: true })).toBeVisible()
      await expect(selectedOpportunity.getByText(/Loading company context/)).toHaveCount(0)
      await expect(selectedOpportunity.getByText(/Checking retained contacts/)).toHaveCount(0)
    }
    await page.screenshot({ path: testInfo.outputPath(`${item.case_id}-opportunities-desktop.png`), fullPage: true })
    await page.goto(`/?view=pursuits&researchNeed=${encodeURIComponent(item.need_id)}`)
    await expect(page.getByRole('heading', { level: 1, name: 'Research', exact: true })).toBeVisible()
    await expect(page.getByRole('heading', { level: 2, name: item.project_name, exact: true })).toBeVisible()
    const researchDetail = page.getByRole('region', { name: 'Selected automated research' })
    for (const text of item.expected_research_text ?? []) await expect(researchDetail).toContainText(text)
    await page.screenshot({ path: testInfo.outputPath(`${item.case_id}-research-desktop.png`), fullPage: true })

    await page.setViewportSize({ width: 390, height: 844 })
    await page.screenshot({ path: testInfo.outputPath(`${item.case_id}-research-mobile.png`), fullPage: true })
    const globalSearch = page.getByRole('searchbox', { name: 'Search companies, projects, contacts and opportunities' })
    await globalSearch.fill(item.project_name)
    const results = page.getByRole('region', { name: 'Search results', exact: true })
    await expect(results).toContainText(item.project_name)
    await page.screenshot({ path: testInfo.outputPath(`${item.case_id}-search-mobile.png`), fullPage: true })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    expect(writes).toEqual([])
  })
}
