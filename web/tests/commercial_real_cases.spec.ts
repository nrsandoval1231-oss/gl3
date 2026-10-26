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
  expected_evidence_id?: string
  expected_need_rationale?: string[]
  expected_browse_view?: 'signals' | 'workspace'
  expected_project_heading?: boolean
  expected_detail_heading?: string
  expected_detail_text?: string[]
  expected_research_project_heading?: string | false
  expected_opportunity_absent?: boolean
  expected_opportunity_text?: string
  expected_tier?: string
  expected_commercial_disposition?: string
  expected_unknown_keys: string[]
  expected_contact_responsibility?: string
  expected_contact_authority?: string
  expected_contact_method_count?: number
  expected_contact_route?: {
    company_name: string
    company_href: string
    company_phone: string
    company_action_label: string
    source_url: string
    source_quote: string
    source_reference: string
    retained_evidence_id: string
    content_hash: string
    representative_name: string
    representative_quote: string
  }
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
      commercial_disposition?: string
      rationale?: string
      qualified_remaining_gap?: unknown
      intelligence_card?: {
        qualification?: string
        disposition?: string
        fields: { key: string; label: string; value: string | null; status: string }[]
        evidence: { url: string | null; content_hash: string | null; retained_evidence_id: string | null }[]
        power_gap?: unknown
        contacts: {
          name?: string | null
          company?: string
          responsibility: string
          purchasing_authority: string
          sources: { reference?: string; retained_evidence_id?: string | null; content_hash?: string | null; url?: string | null; passage?: string | null; title?: string | null }[]
          methods: { kind: string; value: string; href: string; source_url?: string }[]
        }[]
      }
    }
    const card = need.intelligence_card
    expect(need.id).toBe(item.need_id)
    expect(need.project_id).toBe(item.project_id)
    expect(need.name).toContain(item.project_name)
    if (item.expected_tier) expect(need.tier).toBe(item.expected_tier)
    expect(card).toBeTruthy()
    if (item.expected_commercial_disposition) expect(card?.disposition).toBe(item.expected_commercial_disposition)
    expect(card?.evidence.some(source =>
      source.url === item.source_url &&
      source.content_hash === item.source_hash &&
      source.retained_evidence_id &&
      (!item.expected_evidence_id || source.retained_evidence_id === item.expected_evidence_id),
    )).toBe(true)
    for (const fragment of item.expected_need_rationale ?? []) expect(need.rationale ?? '').toContain(fragment)
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
    if (item.expected_contact_route) {
      const expected = item.expected_contact_route
      const companyRoute = card?.contacts.find(contact => contact.company === expected.company_name && contact.methods.some(method => method.href === expected.company_href))
      expect(companyRoute, 'the sourced owner phone belongs to the company contact route').toBeTruthy()
      const method = companyRoute?.methods.find(candidate => candidate.href === expected.company_href)
      expect(method?.kind).toBe('phone')
      expect(method?.value).toBe(expected.company_phone)
      expect(method?.source_url).toBe(expected.source_url)
      expect(expected.company_href).toBe(`tel:${expected.company_phone.replace(/\D/g, '')}`)
      expect(companyRoute?.purchasing_authority).toMatch(/unknown|confirm/i)
      expect(companyRoute?.sources.some(source =>
        source.reference === expected.source_reference &&
        source.retained_evidence_id === expected.retained_evidence_id &&
        source.content_hash === expected.content_hash &&
        source.url === expected.source_url && source.passage?.includes(expected.source_quote),
      )).toBe(true)

      const representative = card?.contacts.find(contact => contact.name === expected.representative_name)
      expect(representative, 'the named owner representative is a separate contact record').toBeTruthy()
      expect(representative?.methods, 'no personal phone or email is inferred for the named person').toHaveLength(0)
      expect(representative?.purchasing_authority).toMatch(/unknown|confirm/i)
      expect(representative?.sources.some(source =>
        source.reference === expected.source_reference &&
        source.retained_evidence_id === expected.retained_evidence_id &&
        source.content_hash === expected.content_hash &&
        source.url === expected.source_url && source.passage?.includes(expected.representative_quote),
      )).toBe(true)
    }
    if (item.no_qualified_gap) {
      expect(need.qualified_remaining_gap).toBeFalsy()
      expect(card?.power_gap).toBeFalsy()
    }

    const browseView = item.expected_browse_view ?? (need.tier === 'Signal' ? 'signals' : 'workspace')
    await page.goto(`/?view=${browseView}&need=${encodeURIComponent(item.need_id)}`)
    const activeNavigation = page.getByRole('navigation', { name: 'Primary navigation' }).getByRole('button', { name: browseView === 'signals' ? 'Signals' : 'Opportunities', exact: true })
    await expect(activeNavigation).toHaveAttribute('aria-current', 'page')
    if (browseView === 'signals') await expect(page.getByRole('heading', { level: 1, name: 'Signals', exact: true })).toBeVisible()
    if (item.expected_signal_text) await expect(page.getByText(item.expected_signal_text, { exact: false })).toBeVisible()
    if (item.expected_project_heading !== false) {
      await expect(page.getByRole('heading', { level: 2, name: item.project_name, exact: true })).toBeVisible()
    }
    const detail = page.getByRole('complementary', { name: 'Opportunity detail' })
    if (item.expected_detail_heading) await expect(detail.getByRole('heading', { level: 2, name: item.expected_detail_heading, exact: false })).toBeVisible()
    for (const text of item.expected_detail_text ?? []) await expect(detail).toContainText(text)
    if (item.company_name) {
      await expect(detail.getByRole('heading', { name: item.company_name, exact: true })).toBeVisible()
      await expect(detail.getByText(/Loading company context/)).toHaveCount(0)
      await expect(detail.getByText(/Checking retained contacts/)).toHaveCount(0)
    }
    if (item.expected_contact_route) {
      const expected = item.expected_contact_route
      const contacts = page.getByRole('region', { name: 'Key contacts and buying chain' })
      const phoneLink = contacts.locator(`article a[href="${expected.company_href}"]`)
      await expect(phoneLink).toHaveCount(1)
      const companyArticle = phoneLink.locator('xpath=ancestor::article[1]')
      await expect(companyArticle.locator('.ic-contact-identity strong')).toHaveText(expected.company_name)
      await expect(phoneLink).toHaveText(expected.company_action_label)
      await companyArticle.locator('details > summary').click()
      await expect(companyArticle).toContainText('Published method source checked')
      await expect(companyArticle.getByRole('link', { name: expected.source_quote, exact: false })).toHaveAttribute('href', expected.source_url)

      const representativeArticle = contacts.locator('article').filter({ hasText: expected.representative_name })
      await expect(representativeArticle).toHaveCount(1)
      await expect(representativeArticle.locator('.ic-contact-actions a')).toHaveCount(0)
      await representativeArticle.locator('details > summary').click()
      await expect(representativeArticle.getByRole('link', { name: expected.representative_quote, exact: false }).first()).toHaveAttribute('href', expected.source_url)

      await page.setViewportSize({ width: 390, height: 844 })
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
      await page.screenshot({ path: testInfo.outputPath(`${item.case_id}-contact-mobile.png`), fullPage: true })
      await page.setViewportSize({ width: 1280, height: 900 })
    }
    await page.screenshot({ path: testInfo.outputPath(`${item.case_id}-${browseView}-desktop.png`), fullPage: true })
    await page.getByRole('button', { name: 'Evidence', exact: true }).click()
    const citations = page.getByRole('region', { name: 'Intelligence card sources' }).locator(`a[href="${item.source_url}"]`)
    await expect(citations.first()).toHaveAttribute('href', item.source_url)
    await page.screenshot({ path: testInfo.outputPath(`${item.case_id}-evidence-desktop.png`), fullPage: true })

    const opportunities = page.getByRole('navigation', { name: 'Primary navigation' }).getByRole('button', { name: 'Opportunities', exact: true })
    await opportunities.click()
    await expect(opportunities).toHaveAttribute('aria-current', 'page')
    const opportunityView = page.getByRole('region', { name: 'Opportunities' })
    await expect(opportunityView).toBeVisible()
    await opportunityView.getByRole('textbox', { name: 'Search workspace' }).fill(item.project_name)
    if (item.expected_opportunity_absent) {
      await expect(opportunityView.getByRole('table', { name: 'Opportunity power needs' })).not.toContainText(item.project_name)
      if (item.expected_opportunity_text) await expect(opportunityView).toContainText(item.expected_opportunity_text)
    } else {
      await expect(opportunityView).toContainText(item.project_name)
    }
    if (item.company_name && !item.expected_opportunity_absent) {
      await opportunityView.getByRole('button', { name: new RegExp(`${item.company_name}.*${item.project_name}`) }).click()
      const selectedOpportunity = page.getByRole('complementary', { name: 'Opportunity detail' })
      await expect(selectedOpportunity.getByRole('heading', { name: item.company_name, exact: true })).toBeVisible()
      await expect(selectedOpportunity.getByText(/Loading company context/)).toHaveCount(0)
      await expect(selectedOpportunity.getByText(/Checking retained contacts/)).toHaveCount(0)
    }
    await page.screenshot({ path: testInfo.outputPath(`${item.case_id}-opportunities-desktop.png`), fullPage: true })
    await page.goto(`/?view=pursuits&researchNeed=${encodeURIComponent(item.need_id)}`)
    await expect(page.getByRole('heading', { level: 1, name: 'Research', exact: true })).toBeVisible()
    if (item.expected_research_project_heading !== false) {
      await expect(page.getByRole('heading', { level: 2, name: item.expected_research_project_heading ?? item.project_name, exact: false })).toBeVisible()
    }
    if (item.expected_contact_route) {
      const expected = item.expected_contact_route
      const researchContacts = page.getByRole('region', { name: 'Business contacts' })
      const researchCompanyLink = researchContacts.locator(`a[href="${expected.company_href}"]`)
      await expect(researchCompanyLink, 'Research hydrates the sourced owner-company route for the selected need').toHaveCount(1)
      const researchCompany = researchCompanyLink.locator('xpath=ancestor::article[1]')
      await expect(researchCompany.locator('strong')).toHaveText(expected.company_name)
      await expect(researchContacts.locator(`a[href="${expected.source_url}"]`).first(), 'Research keeps the contact source citation').toHaveAttribute('href', expected.source_url)
      const researchRepresentative = researchContacts.locator('article').filter({ hasText: expected.representative_name })
      await expect(researchRepresentative).toHaveCount(1)
      await expect(researchRepresentative.locator('a[href^="tel:"]'), 'Research does not infer a personal phone line').toHaveCount(0)
    }
    const researchDetail = page.getByRole('region', { name: 'Selected automated research' })
    for (const text of item.expected_research_text ?? []) await expect(researchDetail).toContainText(text)
    await page.screenshot({ path: testInfo.outputPath(`${item.case_id}-research-desktop.png`), fullPage: true })

    await page.setViewportSize({ width: 390, height: 844 })
    if (item.expected_contact_route) {
      const expected = item.expected_contact_route
      const researchContacts = page.getByRole('region', { name: 'Business contacts' })
      await expect(researchContacts.locator(`a[href="${expected.company_href}"]`), 'the same company method remains present at mobile width').toHaveCount(1)
      await expect(researchContacts.locator(`a[href="${expected.source_url}"]`).first()).toHaveAttribute('href', expected.source_url)
    }
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
