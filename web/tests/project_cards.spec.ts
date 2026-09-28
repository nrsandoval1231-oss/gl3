import { expect, test } from '@playwright/test'
import type { Opportunity } from '../src/api/client'
import { projectCards, projectTitle } from '../src/features/opportunities/projectCards'

const apiRoute = `http://127.0.0.1:${process.env.GRIDLENS_WEB_PORT ?? '5173'}/api/**`

const zilkerDescription = '2026/10/02 - 2026/10/04 - Weekend 1 | 2026/10/09 - 2026/10/11 - Weekend 2 | (2026/09/14) | Music stages food vendors art vendors & hospitality programs. October 2-4 & 9-11 2026 in Zilker Park.'

function permit(id: string, action: string | null, options: { location?: string; activity?: string; tier?: string; abstract?: string } = {}): Opportunity {
  return {
    id,
    name: `AUSTIN permit ${id}`,
    location: options.location ?? '2100 BARTON SPRINGS RD, AUSTIN, TX',
    tier: options.tier ?? 'Signal',
    activity: options.activity ?? 'event-power',
    rationale: 'Permit reports a dated powered event activity; temporary rental power is a question to investigate.',
    required_mw: null,
    start_window: null,
    duration: null,
    supply: 'Unknown',
    next_action: 'Confirm activity power needs, timing, duration, and service plan.',
    conflict_state: 'Not assessed',
    assessment_reason: 'Permit reports a dated powered event activity; temporary rental power is a question to investigate.',
    supported_subject: `AUSTIN permit ${id}`,
    supported_action: action,
    demand_quote: null,
    supply_quote: null,
    missing_facts: ['activity-specific power requirement'],
    evidence: [{
      title: `Austin building permit ${id}`,
      abstract: options.abstract ?? action,
      url: `https://example.invalid/${id}`,
      published_at: '2026-09-14',
      retrieved_at: '2026-09-27T12:00:00Z',
      extraction_location: 'description',
      content_hash: `hash-${id}`,
      event_date: null,
      event_date_label: 'Unknown',
      source_id: 'austin-building-permits',
      document_number: id,
      assessment_current: true,
      permit_status: 'Issued',
    }],
  }
}

test('only exact dated event evidence groups; titles describe permit work; all records stay openable', async ({ page }) => {
  const currentYear = permit('2026-126812 BP', zilkerDescription)
  const sameEvent = permit('2026-126791 BP', zilkerDescription)
  const nextYear = permit('2027-126791 BP', zilkerDescription.replaceAll('2026', '2027'))
  const records = [currentYear, sameEvent, nextYear]
  const groups = projectCards(records)
  expect(groups.map((group) => group.members.length)).toEqual([2, 1])
  expect(groups[0].title).toMatch(/Zilker Park.*Oct 2026/)
  expect(projectTitle(permit('2026-097374 BP', 'Generator replacement. Existing natural gas NG generator and its pad will be removed; a new ATS will be installed.'))).toBe('Generator Replacement')
  expect(projectTitle(permit('3460046', 'PERMIT EXPIRES ON 11/09/2026 ERECTION STARTS: 9/26/2026, ERECTION ENDS: 9/27/2026. 2019 CBC. REINSTATEMENT OF 2025 PERMIT 101074048 FOR THE 2026 HYDE PARK JAZZ FEST STAGES AT THE MUSEUM.'))).toMatch(/Hyde Park Jazz Fest Stages/i)
  expect(projectTitle(permit('3460191', '2026 INTL. FESTIVAL OF LIFE JERK SEAFOOD AND VEGAN FEST STAGE ON SEPT. 25-27, 2026.'))).toMatch(/International Festival of Life.*September/i)
  expect(projectTitle(permit('3460022', '2026 ST. ALPHONSUS OKTOBERFEST STAGE ON SEPT. 25-27, 2026.'))).toMatch(/St Alphonsus Oktoberfest/i)
  expect(projectTitle(permit('2026-118574 BP', 'CBC 2019.', { activity: 'backup-power', location: '919 E 32ND ST, AUSTIN, TX' }))).toBe('Backup power · 919 E 32ND ST, AUSTIN, TX')
  expect(projectTitle(permit('2026-118573 BP', null, {
    activity: 'backup-power',
    location: '919 E 32ND ST, AUSTIN, TX',
    abstract: 'row: 2026-118573 BP\ndate: 2026-09-14\ndescription: Remodel hospital surgery area with associated above and below ceiling work',
  }))).toBe('Remodel Hospital Surgery Area With Associated Above And Below Ceiling Work')
  expect(projectTitle(permit('2026-000001 BP', null, {
    activity: 'facility-expansion',
    location: '100 MAIN ST, AUSTIN, TX',
    abstract: 'row: 2026-000001 BP\ndate: 2026-09-14\nstatus: Issued',
  }))).toBe('Facility expansion · 100 MAIN ST, AUSTIN, TX')
  expect(projectTitle(permit('2026-000002 BP', null, {
    activity: 'facility-expansion',
    location: '200 MAIN ST, AUSTIN, TX',
    abstract: 'row: 2026-000002 BP\ndate: 2026-09-14\nwork: New\ntype: Building Permit',
  }))).toBe('Facility expansion · 200 MAIN ST, AUSTIN, TX')
  const georgia = (action: string, abstract: string, activity = 'facility-expansion', id = 'GA-1') => ({
    ...permit(id, action, { activity, location: 'Hampton, Georgia', abstract }),
    evidence: [{ ...permit(id, action).evidence[0], source_id: 'georgia-air-draft-title-v' }],
  })
  expect(projectTitle(georgia('construct a data center facility', 'Historical excerpt: equipment inventory.', 'facility-expansion'))).toBe('New data center construction')
  expect(projectTitle(georgia('The operations will be powered with four Tier 4 certified diesel fired generator sets for the first two years after startup or until grid power is available, whichever is earlier.', 'Historical excerpt: unrelated text.', 'temporary-power'))).toBe('Generators until grid power is available')
  expect(projectTitle(georgia('Application proposes installation of additional emergency generators for the campus.', 'Historical excerpt: unrelated text.', 'backup-power'))).toBe('Backup power · Hampton, Georgia')
  expect(projectTitle(georgia('construction and operation of a landfill gas-to-renewable natural gas processing facility.', 'Historical excerpt: unrelated text.', 'facility-expansion'))).toBe('Renewable natural gas facility construction')
  expect(projectTitle(georgia('construction and operation of an additional 337 emergency generators and nine fire pumps.', 'Historical excerpt: unrelated text.', 'backup-power'))).toBe('Additional emergency generators')
  expect(projectTitle(georgia('replacing the existing permitted drum dryer and baghouse with like-kind equipment.', 'Historical excerpt: unrelated text.', 'facility-expansion'))).toBe('Asphalt plant equipment replacement')
  expect(projectTitle(georgia('increasing the permitted production capacity at this quarry.', 'Historical excerpt: unrelated text.', 'facility-expansion'))).toBe('Quarry production capacity increase')
  expect(projectTitle(georgia('modification and operation of this existing quarry and stone processing facility.', 'Historical excerpt: unrelated text.', 'facility-expansion'))).toBe('Quarry processing equipment modification')
  expect(projectTitle(georgia('', 'Application purpose details are unavailable.', 'backup-power'))).toBe('Backup power · Hampton, Georgia')
  const liveGeorgia = [
    ['Walker County Quarry', 'Page 1 current application purpose: for increasing the permitted production (crushing) capacity of the facility. Page 1 background prospective activity: Construction of the Facility is planned to begin in Q2 2026.'],
    ['Vulcan Construction Materials, LLC – Siloam Quarry', 'for the modification and operation of this existing quarry and associated stone processing facility. According to Application No. 29927, the proposed facility modification involves: adding a 475 ton-per-hour portable stone processing plant.'],
    ['TADG – ATL02 / Ellenwood', 'for the construction and operation of diesel-fired emergency generators to provide backup power at a new data center located in Ellenwood, Georgia.'],
    ['South Atlanta Asphalt Plant', 'for replacing the existing permitted drum dryer and baghouse with a like-kind new drum dryer and baghouse.'],
    ['QTS Fayetteville I, LLC', 'for the construction and operation of an additional 337 emergency generators and nine fire pumps.'],
    ['QTS ATL3', 'for the construction and operation of a greenfield data center with 224 diesel-fired critical emergency generators.'],
    ['Grady Road Renewable Energy, LLC', 'for the construction and operation of a landfill gas (LFG)-to-renewable natural gas (RNG) processing facility adjacent to the landfill.'],
    ['Azalea Quarry', 'The operations will be powered with four Tier 4 certified diesel fired generator sets for the first two years after startup or until grid power is available, whichever is earlier.'],
    ['Apex Site Solutions LLC', 'for the construction and operation of diesel emergency generators and diesel supporting emergency engines at a data processing facility.'],
  ] as const
  for (const [name, action] of liveGeorgia) {
    const record = georgia(action, 'Historical evidence should not supply the current title.', 'facility-expansion', name)
    expect(projectTitle(record), name).not.toBe(name)
    expect(projectTitle(record).length).toBeLessThan(65)
  }
  const cityRecord = permit('100MW', 'New data center campus construction', { activity: 'facility-expansion' })
  cityRecord.reported_power_facts = ['100 MW campus capacity', '20 MW utility service']
  const browseRecords = [cityRecord, georgia('construct a data center facility', 'A new data center facility is proposed.', 'facility-expansion')]
  await page.unroute(apiRoute)
  await page.route(apiRoute, async (route) => {
    const path = new URL(route.request().url()).pathname
    const body = path === '/api/auth/session' ? { authenticated: true } : path === '/api/opportunities' ? browseRecords : path === '/api/health' ? { sources: [], backlog: 0, pending_interpretations: 0 } : []
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/')
  const summaryCard = page.getByRole('button', { name: /New data center construction/ }).first()
  await expect(summaryCard).toContainText('Hampton, Georgia')
  await expect(page.getByRole('button', { name: /New Data Center Campus Construction/ })).toContainText('100 MW campus capacity · 20 MW utility service')
  await expect(summaryCard).not.toContainText('Load unknown')
  await expect(summaryCard).not.toContainText('assessment')
  await expect(summaryCard).not.toContainText('georgia-air-draft-title-v')
  await expect(page.locator('body')).not.toHaveCSS('overflow-x', 'scroll')

  await page.route(apiRoute, async (route) => {
    const path = new URL(route.request().url()).pathname
    const body = path === '/api/auth/session'
      ? { authenticated: true }
      : path === '/api/opportunities'
        ? records
        : path === '/api/health'
          ? { sources: [], backlog: 0, pending_interpretations: 0 }
          : []
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: /2 project cards · 3 opportunity records/ })).toBeVisible()
  const project = page.getByRole('button', { name: /Zilker Park.*Oct 2026/ })
  await expect(project).toBeVisible()
  await project.click()
  await expect(page.getByText('2 individual permit records')).toBeVisible()
  await page.getByRole('button', { name: /Permit 2026-126812 BP/ }).click()
  await expect(page.getByRole('heading', { level: 1, name: /Zilker Park.*Oct 2026/ })).toBeVisible()
  await expect(page.getByText('austin-building-permits · 2026-126812 BP')).toBeVisible()
  await page.getByRole('button', { name: /Back to Signals/ }).click()

  await page.getByRole('textbox', { name: 'Search projects' }).fill('2026-126812 BP')
  await expect(page.getByText('1 matching project cards · 1 matching records · 3 underlying records.')).toBeVisible()
  const searchResult = page.getByRole('button', { name: /Zilker Park.*Oct 2026/ })
  await expect(searchResult).toBeVisible()
  if (!(await page.getByText('1 matching record · 2 related permit records').isVisible())) await searchResult.click()
  await expect(page.getByText('1 matching record · 2 related permit records')).toBeVisible()
  await expect(page.getByRole('button', { name: /Permit 2026-126812 BP/ })).toBeVisible()
})
