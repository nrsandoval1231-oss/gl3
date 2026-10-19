import { expect, test, type Route } from '@playwright/test'
import type { Opportunity } from '../src/api/client'
import { projectCards, projectTitle, serverProjectCards, signalDecisionCards, signalDisplayDecision } from '../src/features/opportunities/projectCards'

const apiRoute = `http://127.0.0.1:${process.env.GRIDLENS_WEB_PORT ?? '5173'}/api/**`

function emptyExactNeedAuxiliary(path: string) {
  const facts = path.match(/^\/api\/needs\/([^/]+)\/facts$/)
  if (facts) {
    return {
      items: [], total: 0, limit: 50, offset: 0, next_offset: null, current_fact_version: 0,
      current_reported_timing_correction_target: {
        available: false, unavailable_reason: 'no_current_admitted_lead', need_id: facts[1],
        project_id: null, project_identity_key: null, activity_key: null, facility_identity: null,
        source_semantic_hash: null, source_evidence_hash: null, retained_evidence_id: null,
        source_id: null, earliest_possible_start: null, latest_possible_start: null,
        minimum_duration_days: null, maximum_duration_days: null, current_fact_version: 0,
      },
    }
  }
  if (/^\/api\/needs\/[^/]+\/workflow-status$/.test(path)) {
    return { status: 'UNKNOWN', version: 0, events: [] }
  }
  return undefined
}

const zilkerDescription = '2026/10/02 - 2026/10/04 - Weekend 1 | 2026/10/09 - 2026/10/11 - Weekend 2 | (2026/09/14) | Music stages food vendors art vendors & hospitality programs. October 2-4 & 9-11 2026 in Zilker Park.'

function serverOpportunityPage(records: Opportunity[], selectedDecision = 'ALL', search = '') {
  const groups = new Map<string, Opportunity[]>()
  for (const item of records) {
    const key = item.group_id ?? (item.project_id ? `project:${item.tier}:${item.project_id}` : `record:${item.id}`)
    groups.set(key, [...(groups.get(key) ?? []), item])
  }
  const allGroups = [...groups.entries()].map(([id, members]) => ({
    id,
    members,
    decision: signalDisplayDecision(members),
  }))
  const normalizedSearch = search.normalize('NFKC').replace(/\s+/gu, ' ').trim().toLocaleLowerCase('en-US')
  const matches = (item: Opportunity) => !normalizedSearch || [item.id, item.name, item.location, item.activity, item.rationale, item.assessment_reason, item.supported_subject, item.supported_action, ...item.evidence.flatMap((evidence) => [evidence.title, evidence.abstract, evidence.url, evidence.document_number])]
    .some((value) => value?.normalize('NFKC').replace(/\s+/gu, ' ').trim().toLocaleLowerCase('en-US').includes(normalizedSearch))
  const searchedGroups = allGroups.filter((group) => group.members.some(matches))
  const selectedGroups = (selectedDecision === 'ALL' ? searchedGroups : searchedGroups.filter((group) => group.decision === selectedDecision))
  const decisionCounts = Object.fromEntries(['SHOW', 'REVIEW', 'HOLD'].map((decision) => [decision, searchedGroups.filter((group) => group.decision === decision).length]))
  const items = selectedGroups.flatMap((group) => {
    const titleRecord = group.members.find((item) => item.signal_display_decision === group.decision) ?? group.members[0]
    return group.members.map((item) => ({
      ...item,
      group_id: group.id,
      group_title: item.group_title ?? projectTitle(titleRecord),
      group_total_filtered: group.members.length,
      group_loaded_on_page: group.members.length,
      group_complete_on_page: true,
      matched_search: matches(item),
    }))
  })
  const headers = {
    'X-Total-Count': String(items.length),
    'X-Group-Total-Count': String(selectedGroups.length),
    'X-Page-Record-Count': String(items.length),
    'X-Page-Group-Count': String(selectedGroups.length),
    'X-Limit': '50',
    'X-Offset': '0',
    'X-Cohort-Token': 'fixture-server-cohort',
    'X-Decision-Counts': JSON.stringify(decisionCounts),
  }
  return { items, headers }
}

async function fulfillServerOpportunityPage(route: Route, records: Opportunity[]) {
  const params = new URL(route.request().url()).searchParams
  const selectedDecision = params.get('decision') ?? 'ALL'
  const page = serverOpportunityPage(records, selectedDecision, params.get('search') ?? '')
  await route.fulfill({ status: 200, contentType: 'application/json', headers: page.headers, body: JSON.stringify(page.items) })
}

function partialServerOpportunityPage(records: Opportunity[]) {
  const page = serverOpportunityPage(records)
  page.items = page.items.map((item) => {
    const source = records.find((record) => record.id === item.id)
    return {
      ...item,
      group_total_filtered: source?.group_total_filtered ?? 2,
      group_loaded_on_page: records.filter((record) => record.group_id === item.group_id).length,
      group_complete_on_page: source?.group_complete_on_page ?? false,
    }
  })
  return page
}

function permit(id: string, action: string | null, options: { location?: string; activity?: string; tier?: string; abstract?: string; projectId?: string; decision?: string | null } = {}): Opportunity {
  return {
    id,
    project_id: options.projectId ?? '',
    name: `AUSTIN permit ${id}`,
    location: options.location ?? '2100 BARTON SPRINGS RD, AUSTIN, TX',
    tier: options.tier ?? 'Signal',
    workflow_status: 'UNKNOWN',
    activity: options.activity ?? 'event-power',
    rationale: 'Permit reports a dated powered event activity; temporary rental power is a question to investigate.',
    signal_evidence_state: 'active_evidence',
    brief_status: 'unavailable', brief_stale: false,
    signal_display_decision: options.decision === undefined ? 'SHOW' : options.decision,
    signal_display_decision_state: options.decision === undefined ? 'adjudicated' : options.decision ? 'adjudicated' : 'unadjudicated',
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
      id: `evidence-${id}`,
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
      source_origin: 'Official permit',
      document_number: id,
      assessment_current: true,
      permit_status: 'Issued',
    }],
  }
}

test('stable project IDs consolidate lifecycle records and decision filters default uncertain records to REVIEW', () => {
  const planning = permit('planning', 'Planning approval', { projectId: 'project-atlas', decision: 'SHOW' })
  const electrical = permit('electrical', 'Temporary electrical service', { projectId: 'project-atlas', decision: 'HOLD' })
  const similarTitle = permit('other', 'Planning approval', { projectId: 'different-project', decision: 'REVIEW' })
  const unadjudicated = permit('unknown', 'Permit under review', { decision: null })
  const cards = projectCards([planning, electrical, similarTitle, unadjudicated])

  expect(cards).toHaveLength(3)
  expect(cards[0].members.map((member) => member.id)).toEqual(['planning', 'electrical'])
  expect(signalDisplayDecision(cards[0].members)).toBe('SHOW')
  expect(signalDecisionCards(cards, 'SHOW')).toHaveLength(1)
  expect(signalDecisionCards(cards, 'REVIEW').map((card) => card.members[0].id)).toEqual(['other', 'unknown'])
  expect(signalDecisionCards(cards, 'HOLD')).toHaveLength(0)
})

test('Cannabis Watch is removed and an evidence-supported applicant titles the card and detail', async ({ page }) => {
  const record = permit('cultivation', 'Dated cultivation application at 14 Example Road', {
    location: '14 Example Road, Boston, MA',
    activity: 'facility-expansion',
    abstract: 'applicant_org: Green Valley Cultivation LLC\naddress: 14 Example Road, Boston, MA',
  })
  record.name = 'Houston permit cultivation'
  record.evidence[0].source_id = 'ma-cultivation-applications'
  record.commercial_size_status = 'unknown'
  await page.route(apiRoute, async (route) => {
    const path = new URL(route.request().url()).pathname
    const body = path === '/api/auth/session'
      ? { authenticated: true }
      : path === '/api/opportunities'
        ? [record]
        : path === '/api/health'
          ? { sources: [], backlog: 0, pending_interpretations: 0 }
          : emptyExactNeedAuxiliary(new URL(route.request().url()).pathname) ?? []
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/?tier=Signals')
  await expect(page.getByRole('button', { name: 'Cannabis watch' })).toHaveCount(0)
  const card = page.getByRole('button', { name: /Green Valley Cultivation LLC · applicant/ })
  await expect(card).toBeVisible()
  await expect(card).toContainText('Activity size unknown · retained')
  await card.click()
  await expect(page.getByRole('heading', { level: 1, name: 'Green Valley Cultivation LLC · applicant' })).toBeVisible()
  await expect(page.getByText('Activity size unknown.')).toBeVisible()
  await page.getByRole('button', { name: /Back to Signals/ }).click()
  await page.getByRole('textbox', { name: 'Search projects' }).fill('Green Valley Cultivation')
  await expect(page.getByRole('button', { name: /Green Valley Cultivation LLC · applicant/ })).toBeVisible()
})

test('browse filters travel through the request URL and restore with the selected detail Back state', async ({ page }) => {
  const record = permit('filter-back', 'Dated construction permit for a synthetic campus')
  record.group_id = 'opaque-filter-group'
  record.group_title = 'Synthetic campus'
  record.group_total_filtered = 1
  record.group_loaded_on_page = 1
  record.group_complete_on_page = true
  record.matched_search = true
  const requests: URL[] = []
  await page.route(apiRoute, async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    if (path === '/api/opportunities') requests.push(url)
    const body = path === '/api/auth/session'
      ? { authenticated: true }
      : path === '/api/opportunities'
        ? [record]
        : /^\/api\/needs\/[^/]+\/facts$/.test(path)
          ? { items: [], total: 0, limit: 50, offset: 0, next_offset: null, current_fact_version: 0,
            current_reported_timing_correction_target: {
              available: false, unavailable_reason: 'no_current_admitted_lead', need_id: record.id,
              project_id: record.project_id, project_identity_key: record.group_id ?? record.id, activity_key: record.activity,
              facility_identity: null, source_semantic_hash: null, source_evidence_hash: null, retained_evidence_id: null,
              source_id: null, earliest_possible_start: null, latest_possible_start: null,
              minimum_duration_days: null, maximum_duration_days: null, current_fact_version: 0,
            } }
        : /^\/api\/needs\/[^/]+\/workflow-status$/.test(path)
          ? { status: 'UNKNOWN', version: 0, events: [] }
        : path === '/api/health'
          ? { sources: [], backlog: 0, pending_interpretations: 0 }
          : emptyExactNeedAuxiliary(new URL(route.request().url()).pathname) ?? []
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: path === '/api/opportunities'
        ? { 'X-Total-Count': '1', 'X-Group-Total-Count': '1', 'X-Page-Record-Count': '1', 'X-Page-Group-Count': '1', 'X-Limit': '25', 'X-Offset': url.searchParams.get('offset') ?? '0', 'X-Cohort-Token': 'fixture-cohort', 'X-Decision-Counts': '{"SHOW":1,"REVIEW":0,"HOLD":0}' }
        : undefined,
      body: JSON.stringify(body),
    })
  })
  await page.goto('/?tier=Signals&q=campus&decision=SHOW&offset=25&geography=UNKNOWN&industry=data_center&activity=facility-expansion&timing=UNKNOWN&mw_status=UNKNOWN&mw_min=0.3&priority_segment=8&status=UNKNOWN')
  await expect(page.getByRole('textbox', { name: 'Search projects' })).toHaveValue('campus')
  await expect(page.getByRole('textbox', { name: 'Filter by exact project asset type' })).toHaveValue('data_center')
  await expect(page.getByRole('textbox', { name: 'Filter by exact power activity' })).toHaveValue('facility-expansion')
  await expect(page.getByRole('button', { name: /Back to Signals/ })).toHaveCount(0)
  await expect.poll(() => requests.some((request) => request.searchParams.get('geography') === 'UNKNOWN'
    && request.searchParams.get('industry') === 'data_center'
    && request.searchParams.get('activity') === 'facility-expansion'
    && request.searchParams.get('timing') === 'UNKNOWN'
    && request.searchParams.get('mw_status') === 'UNKNOWN'
    && request.searchParams.get('mw_min') === '0.3'
    && request.searchParams.get('priority_segment') === '8'
    && request.searchParams.get('status') === 'UNKNOWN')).toBe(true)
  const opportunityRequests = requests.filter((request) => request.pathname === '/api/opportunities')
  const laterPageIndex = opportunityRequests.findIndex((request) => request.searchParams.get('offset') === '25')
  expect(laterPageIndex).toBeGreaterThan(0)
  expect(opportunityRequests.slice(0, laterPageIndex).every((request) => (request.searchParams.get('offset') ?? '0') === '0'
    && request.searchParams.get('cohort_token') === null)).toBe(true)
  expect(opportunityRequests[laterPageIndex].searchParams.get('cohort_token')).toBe('fixture-cohort')
  await page.locator('[data-opportunity-id="filter-back"]').first().click()
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await page.getByRole('button', { name: /Back to Signals/ }).click()
  await expect(page.getByRole('textbox', { name: 'Search projects' })).toHaveValue('campus')
  await expect(page.getByRole('textbox', { name: 'Filter by exact project asset type' })).toHaveValue('data_center')
  await expect(page.getByRole('textbox', { name: 'Filter by exact power activity' })).toHaveValue('facility-expansion')
  const restored = new URL(page.url())
  expect(restored.searchParams.get('offset')).toBe('25')
  expect(restored.searchParams.get('geography')).toBe('UNKNOWN')
  expect(restored.searchParams.get('industry')).toBe('data_center')
  expect(restored.searchParams.get('activity')).toBe('facility-expansion')
  expect(restored.searchParams.get('timing')).toBe('UNKNOWN')
  expect(restored.searchParams.get('mw_min')).toBe('0.3')
  expect(restored.searchParams.get('priority_segment')).toBe('8')
  expect(restored.searchParams.get('status')).toBe('UNKNOWN')
  await page.goForward()
  await expect(page.getByRole('heading', { level: 1 })).toContainText(/Synthetic campus/i)
  await page.goBack()
  await expect(page.getByRole('textbox', { name: 'Filter by exact project asset type' })).toHaveValue('data_center')
  expect(new URL(page.url()).searchParams.get('offset')).toBe('25')
})

test('stale later-page cohort restarts at page one without showing the previous cohort', async ({ page }) => {
  const staleRecord = permit('old-cohort-record', 'Old cohort construction filing')
  const currentRecord = permit('current-cohort-record', 'Current cohort construction filing')
  let changed = false
  const requests: URL[] = []
  await page.route(apiRoute, async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/opportunities') {
      requests.push(url)
      const offset = Number(url.searchParams.get('offset') ?? '0')
      if (offset > 0 && url.searchParams.get('cohort_token') === 'old-cohort-token' && !changed) {
        changed = true
        await route.fulfill({ status: 409, json: { detail: 'Opportunity cohort changed; restart pagination' } })
        return
      }
      const record = changed ? currentRecord : staleRecord
      const payload = serverOpportunityPage([record], url.searchParams.get('decision') ?? 'ALL')
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: { ...payload.headers, 'X-Offset': String(offset), 'X-Cohort-Token': changed ? 'current-cohort-token' : 'old-cohort-token', ...(offset === 0 && !changed ? { 'X-Next-Offset': '25' } : {}) },
        body: JSON.stringify(payload.items),
      })
      return
    }
    const body = url.pathname === '/api/auth/session'
      ? { authenticated: true }
      : url.pathname === '/api/health'
        ? { sources: [], backlog: 0, pending_interpretations: 0 }
        : emptyExactNeedAuxiliary(new URL(route.request().url()).pathname) ?? []
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/?tier=Signals')
  const oldCard = page.getByRole('button', { name: /Old cohort construction filing/i })
  await expect(oldCard).toBeVisible()
  await page.getByRole('button', { name: /Next/ }).click()
  const currentCard = page.getByRole('button', { name: /Current cohort construction filing/i })
  await expect(currentCard).toBeVisible()
  await expect(page.getByRole('button', { name: /Old cohort construction filing/i })).toHaveCount(0)
  expect(new URL(page.url()).searchParams.get('offset')).toBeNull()
  const opportunityRequests = requests
  const laterRequest = opportunityRequests.find((request) => request.searchParams.get('offset') === '25')
  expect(laterRequest?.searchParams.get('cohort_token')).toBe('old-cohort-token')
  const restarted = opportunityRequests.find((request, index) => index > opportunityRequests.indexOf(laterRequest!) && (request.searchParams.get('offset') ?? '0') === '0')
  expect(restarted?.searchParams.get('cohort_token')).toBeNull()
})

test('Back restores the exact selected need across tiers and pages with its cohort and focus', async ({ page }) => {
  const firstSignal = permit('signal-first-page', 'First Signal page record')
  const selectedSignal = permit('signal-later-page', 'Exact Signal later-page record')
  selectedSignal.evidence[0].title = 'Citation for the exact later-page Signal'
  const prospect = permit('prospect-first-page', 'Distinct Prospect page record', { tier: 'Prospect' })
  const requests: URL[] = []
  await page.route(apiRoute, async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    if (path === '/api/opportunities') {
      requests.push(url)
      const tier = url.searchParams.get('tier') ?? 'Signal'
      const offset = Number(url.searchParams.get('offset') ?? '0')
      const record = tier === 'Prospect' ? prospect : offset === 0 ? firstSignal : selectedSignal
      const payload = serverOpportunityPage([record], url.searchParams.get('decision') ?? 'ALL', url.searchParams.get('search') ?? '')
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: {
          ...payload.headers,
          'X-Limit': '25',
          'X-Offset': String(offset),
          'X-Cohort-Token': tier === 'Prospect' ? 'prospect-scope-token' : 'signal-scope-token',
          ...(tier === 'Signal' && offset === 0 ? { 'X-Next-Offset': '25' } : {}),
        },
        body: JSON.stringify(payload.items),
      })
      return
    }
    const body = path === '/api/auth/session'
      ? { authenticated: true }
      : path === '/api/health'
        ? { sources: [], backlog: 0, pending_interpretations: 0 }
        : path.startsWith('/api/power-needs/')
          ? { status: 'unavailable', result: null, citations: [] }
          : emptyExactNeedAuxiliary(new URL(route.request().url()).pathname) ?? []
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })

  await page.goto('/?tier=Signals&decision=SHOW&offset=25&activity=event-power')
  const selectedCard = page.locator('[data-opportunity-id="signal-later-page"]')
  await expect(selectedCard).toBeVisible()
  await selectedCard.click()
  await expect(page.getByRole('link', { name: 'Citation for the exact later-page Signal' })).toBeVisible()
  expect(new URL(page.url()).hash).toBe('#signal-later-page')
  await page.getByLabel('Qualification tier').selectOption('Prospects')
  await expect(page.locator('[data-opportunity-id="prospect-first-page"]')).toBeVisible()

  await page.goBack()
  await expect(page.getByRole('link', { name: 'Citation for the exact later-page Signal' })).toBeVisible()
  expect(new URL(page.url()).searchParams.get('tier')).toBe('Signals')
  expect(new URL(page.url()).searchParams.get('offset')).toBe('25')
  expect(new URL(page.url()).searchParams.get('decision')).toBe('SHOW')
  expect(new URL(page.url()).searchParams.get('activity')).toBe('event-power')
  expect(new URL(page.url()).hash).toBe('#signal-later-page')
  const restoreRequests = requests.filter((request) => request.searchParams.get('tier') === 'Signal').slice(-2)
  expect(restoreRequests.map((request) => request.searchParams.get('offset'))).toEqual(['0', '25'])
  expect(restoreRequests[0].searchParams.get('cohort_token')).toBeNull()
  expect(restoreRequests[1].searchParams.get('cohort_token')).toBe('signal-scope-token')

  await page.goBack()
  await expect(page.locator('[data-opportunity-id="signal-later-page"]')).toBeFocused()
  await page.goForward()
  await expect(page.getByRole('link', { name: 'Citation for the exact later-page Signal' })).toBeVisible()
  await page.goForward()
  await expect(page.locator('[data-opportunity-id="prospect-first-page"]')).toBeVisible()
  expect(new URL(page.url()).searchParams.get('tier')).toBe('Prospects')
})

test('direct selected URL reports an exact need outside its filtered cohort without showing another record', async ({ page }) => {
  const visibleRecord = permit('visible-filtered-record', 'Visible record in the selected filter')
  const detailRequests: URL[] = []
  await page.route(apiRoute, async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/opportunities') {
      const payload = serverOpportunityPage([visibleRecord], url.searchParams.get('decision') ?? 'ALL', url.searchParams.get('search') ?? '')
      await route.fulfill({ status: 200, contentType: 'application/json', headers: payload.headers, body: JSON.stringify(payload.items) })
      return
    }
    if (url.pathname === '/api/opportunities/needs/not-in-filtered-cohort') {
      detailRequests.push(url)
      await route.fulfill({ status: 404, json: { detail: 'Opportunity is outside the requested filtered cohort' } })
      return
    }
    const body = url.pathname === '/api/auth/session'
      ? { authenticated: true }
      : url.pathname === '/api/health'
        ? { sources: [], backlog: 0, pending_interpretations: 0 }
        : emptyExactNeedAuxiliary(new URL(route.request().url()).pathname) ?? []
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })

  await page.goto('/?tier=Signals&q=visible&activity=event-power#not-in-filtered-cohort')
  await expect(page.getByRole('alert')).toContainText(/selected opportunity is not available in this filtered cohort/i)
  await expect(page.getByRole('heading', { level: 1, name: 'Signals' })).toBeVisible()
  await expect(page.locator('[data-opportunity-id="visible-filtered-record"]')).toBeVisible()
  await expect(page.getByRole('link', { name: /not-in-filtered-cohort/ })).toHaveCount(0)
  expect(new URL(page.url()).hash).toBe('')
  expect(detailRequests).toHaveLength(1)
  expect(detailRequests[0].searchParams.get('tier')).toBe('Signal')
  expect(detailRequests[0].searchParams.get('search')).toBe('visible')
  expect(detailRequests[0].searchParams.get('activity')).toBe('event-power')
  expect(detailRequests[0].searchParams.get('cohort_token')).toBe('fixture-server-cohort')
})

test('direct selected URL hydrates the exact need with the restored page cohort when it moved off-page', async ({ page }) => {
  const currentPageRecord = permit('current-page-record', 'A separate current page record')
  const selectedRecord = permit('selected-off-page', 'Exact restored off-page record')
  selectedRecord.evidence[0].title = 'Citation for the restored off-page record'
  const detailRequests: URL[] = []
  const opportunityRequests: URL[] = []
  await page.route(apiRoute, async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/opportunities') {
      opportunityRequests.push(url)
      const payload = serverOpportunityPage([currentPageRecord], url.searchParams.get('decision') ?? 'ALL')
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: { ...payload.headers, 'X-Limit': '25', 'X-Offset': url.searchParams.get('offset') ?? '0', 'X-Cohort-Token': 'restored-scope-token' },
        body: JSON.stringify(payload.items),
      })
      return
    }
    if (url.pathname === '/api/opportunities/needs/selected-off-page') {
      detailRequests.push(url)
      await route.fulfill({ status: 200, json: selectedRecord })
      return
    }
    const body = url.pathname === '/api/auth/session'
      ? { authenticated: true }
      : url.pathname === '/api/health'
        ? { sources: [], backlog: 0, pending_interpretations: 0 }
        : emptyExactNeedAuxiliary(new URL(route.request().url()).pathname) ?? []
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })

  await page.goto('/?tier=Signals&offset=25&activity=event-power#selected-off-page')
  await expect(page.getByRole('link', { name: 'Citation for the restored off-page record' })).toBeVisible()
  await expect(page.getByRole('link', { name: /current-page-record/ })).toHaveCount(0)
  expect(opportunityRequests.map((url) => url.searchParams.get('offset'))).toEqual(['0', '25'])
  expect(opportunityRequests[0].searchParams.get('cohort_token')).toBeNull()
  expect(opportunityRequests[1].searchParams.get('cohort_token')).toBe('restored-scope-token')
  expect(detailRequests).toHaveLength(1)
  expect(detailRequests[0].searchParams.get('tier')).toBe('Signal')
  expect(detailRequests[0].searchParams.get('activity')).toBe('event-power')
  expect(detailRequests[0].searchParams.get('cohort_token')).toBe('restored-scope-token')
})

test('late restored-page response cannot replace a newer Back/Forward destination', async ({ page }) => {
  const firstSignal = permit('late-first-signal', 'First Signal page')
  const selectedSignal = permit('late-selected-signal', 'Delayed Signal detail record')
  const prospect = permit('late-prospect', 'Current Prospect destination', { tier: 'Prospect' })
  const requests: URL[] = []
  let restoreSignalPage = false
  let delayedResponseStarted = false
  let releaseDelayedResponse: (() => void) | undefined
  const delayedResponseGate = new Promise<void>((resolve) => { releaseDelayedResponse = resolve })
  await page.route(apiRoute, async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/opportunities') {
      requests.push(url)
      const tier = url.searchParams.get('tier') ?? 'Signal'
      const offset = Number(url.searchParams.get('offset') ?? '0')
      const record = tier === 'Prospect' ? prospect : offset === 0 ? firstSignal : selectedSignal
      const payload = serverOpportunityPage([record], url.searchParams.get('decision') ?? 'ALL', url.searchParams.get('search') ?? '')
      if (restoreSignalPage && tier === 'Signal' && offset === 25 && !delayedResponseStarted) {
        delayedResponseStarted = true
        await delayedResponseGate
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: {
          ...payload.headers,
          'X-Limit': '25',
          'X-Offset': String(offset),
          'X-Cohort-Token': tier === 'Prospect' ? 'prospect-race-token' : 'signal-race-token',
          ...(tier === 'Signal' && offset === 0 ? { 'X-Next-Offset': '25' } : {}),
        },
        body: JSON.stringify(payload.items),
      })
      return
    }
    const body = url.pathname === '/api/auth/session'
      ? { authenticated: true }
      : url.pathname === '/api/health'
        ? { sources: [], backlog: 0, pending_interpretations: 0 }
        : url.pathname.startsWith('/api/power-needs/')
          ? { status: 'unavailable', result: null, citations: [] }
          : emptyExactNeedAuxiliary(new URL(route.request().url()).pathname) ?? []
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })

  try {
    await page.goto('/?tier=Signals&offset=25')
    await page.locator('[data-opportunity-id="late-selected-signal"]').click()
    await page.getByLabel('Qualification tier').selectOption('Prospects')
    await expect(page.locator('[data-opportunity-id="late-prospect"]')).toBeVisible()

    restoreSignalPage = true
    await page.goBack()
    await expect.poll(() => delayedResponseStarted).toBe(true)
    await page.goForward()
    await expect(page.locator('[data-opportunity-id="late-prospect"]')).toBeVisible()
    releaseDelayedResponse?.()
    await expect(page.locator('[data-opportunity-id="late-prospect"]')).toBeVisible()
    await expect(page.getByRole('link', { name: /Delayed Signal detail record/ })).toHaveCount(0)
    expect(new URL(page.url()).searchParams.get('tier')).toBe('Prospects')
    expect(requests.some((request) => request.searchParams.get('tier') === 'Signal' && request.searchParams.get('offset') === '25')).toBe(true)
  } finally {
    releaseDelayedResponse?.()
  }
})

test('active first-page tier click preserves ready metadata and closes its detail without refetching', async ({ page }) => {
  const record = permit('active-tier-ready', 'Campus facility activity')
  const requests: URL[] = []
  await page.route(apiRoute, async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/opportunities') {
      requests.push(url)
      const payload = serverOpportunityPage([record], url.searchParams.get('decision') ?? 'ALL', url.searchParams.get('search') ?? '')
      await route.fulfill({ status: 200, contentType: 'application/json', headers: { ...payload.headers, 'X-Limit': '25', 'X-Offset': '0', 'X-Next-Offset': '25' }, body: JSON.stringify(payload.items) })
      return
    }
    const body = url.pathname === '/api/auth/session'
      ? { authenticated: true }
      : url.pathname === '/api/health'
        ? { sources: [], backlog: 0, pending_interpretations: 0 }
        : url.pathname.startsWith('/api/power-needs/')
          ? { status: 'unavailable', result: null, citations: [] }
          : emptyExactNeedAuxiliary(new URL(route.request().url()).pathname) ?? []
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })

  await page.goto('/?tier=Signals')
  await expect(page.locator('[data-opportunity-id="active-tier-ready"]')).toBeVisible()
  const initialUrl = page.url()
  const csv = page.getByRole('link', { name: 'Download filtered CSV' })
  await expect(csv).toBeVisible()
  await expect(page.locator('.collection-pagination button').nth(1)).toBeEnabled()
  await page.getByRole('button', { name: 'Signals', exact: true }).click()
  await expect(page.getByText('1 filtered records · page 1')).toBeVisible()
  await expect(csv).toBeVisible()
  await expect(page.locator('.collection-pagination button').nth(1)).toBeEnabled()
  expect(page.url()).toBe(initialUrl)
  expect(requests).toHaveLength(1)

  await page.locator('[data-opportunity-id="active-tier-ready"]').click()
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await page.getByRole('button', { name: 'Signals', exact: true }).click()
  await expect(page.locator('[data-opportunity-id="active-tier-ready"]')).toBeVisible()
  await expect(csv).toBeVisible()
  await expect(page.locator('.collection-pagination button').nth(1)).toBeEnabled()
  expect(requests).toHaveLength(1)
})

test('active first-page tier click while loading lets the matching request settle', async ({ page }) => {
  const record = permit('active-tier-pending', 'Pending campus facility activity')
  let requestCount = 0
  let releaseRequest: (() => void) | undefined
  const gate = new Promise<void>((resolve) => { releaseRequest = resolve })
  await page.route(apiRoute, async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/opportunities') {
      requestCount += 1
      await gate
      const payload = serverOpportunityPage([record])
      await route.fulfill({ status: 200, contentType: 'application/json', headers: { ...payload.headers, 'X-Limit': '25', 'X-Offset': '0', 'X-Next-Offset': '25' }, body: JSON.stringify(payload.items) })
      return
    }
    const body = url.pathname === '/api/auth/session'
      ? { authenticated: true }
      : url.pathname === '/api/health'
        ? { sources: [], backlog: 0, pending_interpretations: 0 }
        : emptyExactNeedAuxiliary(new URL(route.request().url()).pathname) ?? []
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  try {
    await page.goto('/?tier=Signals')
    await expect(page.getByRole('button', { name: 'Signals' })).toBeVisible()
    await expect.poll(() => requestCount).toBe(1)
    await expect(page.getByText('Updating this view…')).toBeVisible()
    await page.getByRole('button', { name: 'Signals' }).click()
    releaseRequest?.()
    await expect(page.locator('[data-opportunity-id="active-tier-pending"]')).toBeVisible()
    await expect(page.getByText('Updating this view…')).toHaveCount(0)
    await expect(page.getByRole('link', { name: 'Download filtered CSV' })).toBeVisible()
    await expect(page.locator('.collection-pagination button').nth(1)).toBeEnabled()
    expect(requestCount).toBe(1)
  } finally {
    releaseRequest?.()
  }
})

test('active tier click from a later page fetches first-page data before showing totals', async ({ page }) => {
  const firstPageRecord = permit('active-tier-first-page', 'First-page campus activity')
  const laterPageRecord = permit('active-tier-later-page', 'Later-page campus activity')
  const requests: URL[] = []
  await page.route(apiRoute, async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/opportunities') {
      requests.push(url)
      const offset = Number(url.searchParams.get('offset') ?? '0')
      const record = offset === 0 ? firstPageRecord : laterPageRecord
      const payload = serverOpportunityPage([record], url.searchParams.get('decision') ?? 'ALL')
      await route.fulfill({ status: 200, contentType: 'application/json', headers: { ...payload.headers, 'X-Limit': '25', 'X-Offset': String(offset), 'X-Cohort-Token': 'active-tier-page-token', ...(offset === 0 ? { 'X-Next-Offset': '25' } : {}) }, body: JSON.stringify(payload.items) })
      return
    }
    const body = url.pathname === '/api/auth/session'
      ? { authenticated: true }
      : url.pathname === '/api/health'
        ? { sources: [], backlog: 0, pending_interpretations: 0 }
        : emptyExactNeedAuxiliary(new URL(route.request().url()).pathname) ?? []
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })

  await page.goto('/?tier=Signals&offset=25')
  await expect(page.locator('[data-opportunity-id="active-tier-later-page"]')).toBeVisible()
  await page.getByRole('button', { name: 'Signals', exact: true }).click()
  await expect(page.locator('[data-opportunity-id="active-tier-first-page"]')).toBeVisible()
  await expect(page.locator('[data-opportunity-id="active-tier-later-page"]')).toHaveCount(0)
  await expect(page.getByText('1 filtered records · page 1')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Download filtered CSV' })).toBeVisible()
  expect(new URL(page.url()).searchParams.get('offset')).toBeNull()
  expect(requests.map((url) => url.searchParams.get('offset'))).toEqual(['0', '25', '0'])
  expect(requests[1].searchParams.get('cohort_token')).toBe('active-tier-page-token')
  expect(requests[2].searchParams.get('cohort_token')).toBeNull()
})

test('active Signals decision and unchanged search preserve ready page metadata', async ({ page }) => {
  const record = permit('same-decision-search', 'Campus facility activity')
  const requests: URL[] = []
  await page.route(apiRoute, async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/opportunities') {
      requests.push(url)
      const payload = serverOpportunityPage([record], url.searchParams.get('decision') ?? 'ALL', url.searchParams.get('search') ?? '')
      await route.fulfill({ status: 200, contentType: 'application/json', headers: { ...payload.headers, 'X-Limit': '25', 'X-Offset': '0', 'X-Next-Offset': '25' }, body: JSON.stringify(payload.items) })
      return
    }
    const body = url.pathname === '/api/auth/session'
      ? { authenticated: true }
      : url.pathname === '/api/health'
        ? { sources: [], backlog: 0, pending_interpretations: 0 }
        : emptyExactNeedAuxiliary(new URL(route.request().url()).pathname) ?? []
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/?tier=Signals&q=campus&activity=event-power')
  await expect(page.locator('[data-opportunity-id="same-decision-search"]')).toBeVisible()
  const csv = page.getByRole('link', { name: 'Download filtered CSV' })
  await page.getByRole('group', { name: 'Filter Signals by review decision' }).getByRole('button', { name: /All/ }).click()
  await expect(csv).toBeVisible()
  await expect(page.locator('.collection-pagination button').nth(1)).toBeEnabled()
  await page.getByRole('textbox', { name: 'Search projects' }).fill('campus')
  await expect(csv).toBeVisible()
  await expect(page.locator('.collection-pagination button').nth(1)).toBeEnabled()
  await page.getByRole('textbox', { name: 'Filter by exact power activity' }).fill('event-power')
  await expect(csv).toBeVisible()
  await expect(page.locator('.collection-pagination button').nth(1)).toBeEnabled()
  expect(requests).toHaveLength(1)
})

test('active decision and unchanged activity filter during page load preserve the request', async ({ page }) => {
  const record = permit('same-controls-pending', 'Campus facility activity')
  let requestStarted = false
  let releaseRequest: (() => void) | undefined
  const gate = new Promise<void>((resolve) => { releaseRequest = resolve })
  await page.route(apiRoute, async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/opportunities') {
      requestStarted = true
      await gate
      const payload = serverOpportunityPage([record], url.searchParams.get('decision') ?? 'ALL')
      await route.fulfill({ status: 200, contentType: 'application/json', headers: { ...payload.headers, 'X-Limit': '25', 'X-Offset': '0', 'X-Next-Offset': '25' }, body: JSON.stringify(payload.items) })
      return
    }
    const body = url.pathname === '/api/auth/session'
      ? { authenticated: true }
      : url.pathname === '/api/health'
        ? { sources: [], backlog: 0, pending_interpretations: 0 }
        : emptyExactNeedAuxiliary(new URL(route.request().url()).pathname) ?? []
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  try {
    await page.goto('/?tier=Signals&activity=event-power')
    await expect(page.getByRole('button', { name: 'Signals' })).toBeVisible()
    await expect.poll(() => requestStarted).toBe(true)
    await page.getByRole('group', { name: 'Filter Signals by review decision' }).getByRole('button', { name: /All/ }).click()
    await page.getByRole('textbox', { name: 'Filter by exact power activity' }).fill('event-power')
    releaseRequest?.()
    await expect(page.locator('[data-opportunity-id="same-controls-pending"]')).toBeVisible()
    await expect(page.getByText('Updating this view…')).toHaveCount(0)
    await expect(page.getByRole('link', { name: 'Download filtered CSV' })).toBeVisible()
    await expect(page.locator('.collection-pagination button').nth(1)).toBeEnabled()
  } finally {
    releaseRequest?.()
  }
})

test('unchanged search during page load does not cancel its terminal response', async ({ page }) => {
  const record = permit('same-search-pending', 'Campus facility activity')
  let requestStarted = false
  let releaseRequest: (() => void) | undefined
  const gate = new Promise<void>((resolve) => { releaseRequest = resolve })
  await page.route(apiRoute, async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/opportunities') {
      requestStarted = true
      await gate
      const payload = serverOpportunityPage([record], url.searchParams.get('decision') ?? 'ALL', url.searchParams.get('search') ?? '')
      await route.fulfill({ status: 200, contentType: 'application/json', headers: { ...payload.headers, 'X-Limit': '25', 'X-Offset': '0', 'X-Next-Offset': '25' }, body: JSON.stringify(payload.items) })
      return
    }
    const body = url.pathname === '/api/auth/session'
      ? { authenticated: true }
      : url.pathname === '/api/health'
        ? { sources: [], backlog: 0, pending_interpretations: 0 }
        : emptyExactNeedAuxiliary(new URL(route.request().url()).pathname) ?? []
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  try {
    await page.goto('/?tier=Signals&q=campus')
    await expect(page.getByRole('textbox', { name: 'Search projects' })).toHaveValue('campus')
    await expect.poll(() => requestStarted).toBe(true)
    await page.getByRole('textbox', { name: 'Search projects' }).fill('campus')
    releaseRequest?.()
    await expect(page.locator('[data-opportunity-id="same-search-pending"]')).toBeVisible()
    await expect(page.getByText('Updating this view…')).toHaveCount(0)
    await expect(page.getByRole('link', { name: 'Download filtered CSV' })).toBeVisible()
  } finally {
    releaseRequest?.()
  }
})

test('unchanged activity filter during page load does not cancel or duplicate its request', async ({ page }) => {
  const record = permit('same-filter-pending', 'Campus facility activity')
  const requests: URL[] = []
  let releaseRequest: (() => void) | undefined
  const gate = new Promise<void>((resolve) => { releaseRequest = resolve })
  await page.route(apiRoute, async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/opportunities') {
      requests.push(url)
      await gate
      const payload = serverOpportunityPage([record])
      await route.fulfill({ status: 200, contentType: 'application/json', headers: { ...payload.headers, 'X-Limit': '25', 'X-Offset': '0', 'X-Next-Offset': '25' }, body: JSON.stringify(payload.items) })
      return
    }
    const body = url.pathname === '/api/auth/session'
      ? { authenticated: true }
      : url.pathname === '/api/health'
        ? { sources: [], backlog: 0, pending_interpretations: 0 }
        : emptyExactNeedAuxiliary(new URL(route.request().url()).pathname) ?? []
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  try {
    await page.goto('/?tier=Signals&activity=event-power')
    await expect(page.getByRole('textbox', { name: 'Filter by exact power activity' })).toHaveValue('event-power')
    await expect.poll(() => requests.length).toBe(1)
    await page.getByRole('textbox', { name: 'Filter by exact power activity' }).fill('event-power')
    await page.waitForTimeout(100)
    expect(requests).toHaveLength(1)
    releaseRequest?.()
    await expect(page.locator('[data-opportunity-id="same-filter-pending"]')).toBeVisible()
    await expect(page.getByText('Updating this view…')).toHaveCount(0)
  } finally {
    releaseRequest?.()
  }
})

test('clicking the active Operations view during its request does not strand loading', async ({ page }) => {
  let requestStarted = false
  let releaseRequest: (() => void) | undefined
  const gate = new Promise<void>((resolve) => { releaseRequest = resolve })
  await page.route(apiRoute, async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/ingestion') {
      requestStarted = true
      await gate
      await route.fulfill({ status: 200, json: { items: [], total: 0, limit: 25, offset: 0 } })
      return
    }
    const body = url.pathname === '/api/auth/session'
      ? { authenticated: true }
      : url.pathname === '/api/health'
        ? { sources: [], backlog: 0, pending_interpretations: 0 }
        : emptyExactNeedAuxiliary(new URL(route.request().url()).pathname) ?? []
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  try {
    await page.goto('/?view=ingestion')
    await expect(page.getByRole('button', { name: 'Operations' })).toBeVisible()
    await expect.poll(() => requestStarted).toBe(true)
    await page.getByRole('button', { name: 'Operations' }).click()
    releaseRequest?.()
    await expect(page.getByText('Updating this view…')).toHaveCount(0)
    await expect(page.getByRole('heading', { name: 'No retained source items' })).toBeVisible()
  } finally {
    releaseRequest?.()
  }
})

test('opening a same-cohort record during a pending Back page request does not strand loading', async ({ page }) => {
  const record = permit('open-during-refresh-a', 'First campus facility activity')
  const nextRecord = permit('open-during-refresh-b', 'Second campus facility activity')
  let opportunityRequests = 0
  let secondRequestStarted = false
  let releaseSecondRequest: (() => void) | undefined
  const secondRequestGate = new Promise<void>((resolve) => { releaseSecondRequest = resolve })
  await page.route(apiRoute, async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/opportunities') {
      opportunityRequests += 1
      if (opportunityRequests === 2) {
        secondRequestStarted = true
        await secondRequestGate
      }
      const payload = serverOpportunityPage([record, nextRecord], url.searchParams.get('decision') ?? 'ALL', url.searchParams.get('search') ?? '')
      await route.fulfill({ status: 200, contentType: 'application/json', headers: { ...payload.headers, 'X-Limit': '25', 'X-Offset': '0' }, body: JSON.stringify(payload.items) })
      return
    }
    const body = url.pathname === '/api/auth/session'
      ? { authenticated: true }
      : url.pathname === '/api/health'
        ? { sources: [], backlog: 0, pending_interpretations: 0 }
        : url.pathname.startsWith('/api/power-needs/')
          ? { status: 'unavailable', result: null, citations: [] }
          : emptyExactNeedAuxiliary(new URL(route.request().url()).pathname) ?? []
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  try {
    await page.goto('/?tier=Signals')
    await page.locator('[data-opportunity-id="open-during-refresh-a"]').click()
    await page.getByRole('button', { name: '← Back to Signals' }).click()
    await expect.poll(() => secondRequestStarted).toBe(true)
    await expect(page.locator('[data-opportunity-id="open-during-refresh-a"]')).toBeVisible()
    await page.locator('[data-opportunity-id="open-during-refresh-a"]').click()
    await expect(page.getByRole('button', { name: 'Next →' })).toBeEnabled()
    await page.getByRole('button', { name: 'Next →' }).click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Second Campus Facility Activity')
    releaseSecondRequest?.()
    await expect(page.getByText('Updating this view…')).toHaveCount(0)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Second Campus Facility Activity')
  } finally {
    releaseSecondRequest?.()
  }
})

test('late group expansion pages cannot restore members from a superseded browse filter', async ({ page }) => {
  const oldFirst = permit('scope-a-first', 'Activity A first record', { activity: 'activity-a' })
  const oldLast = permit('scope-a-last', 'Activity A later record', { activity: 'activity-a' })
  const current = permit('scope-b-current', 'Activity B current record', { activity: 'activity-b' })
  const partial = (record: Opportunity, groupId: string, total: number) => {
    record.group_id = groupId
    record.group_title = 'Stable event group'
    record.group_total_filtered = total
    record.group_loaded_on_page = 1
    record.group_complete_on_page = false
    return record
  }
  partial(oldFirst, 'stable-group', 51)
  partial(oldLast, 'stable-group', 51)
  partial(current, 'stable-group', 2)
  let releaseOldLaterPage: (() => void) | undefined
  const oldLaterPage = new Promise<void>((resolve) => { releaseOldLaterPage = resolve })
  let oldLaterPageStarted = false
  const groupRequests: URL[] = []
  await page.route(apiRoute, async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    if (path === '/api/opportunities') {
      const activity = url.searchParams.get('activity')
      const record = activity === 'activity-a' ? oldFirst : current
      const payload = partialServerOpportunityPage([record])
      await route.fulfill({ status: 200, contentType: 'application/json', headers: { ...payload.headers, 'X-Limit': '25', 'X-Offset': url.searchParams.get('offset') ?? '0' }, body: JSON.stringify(payload.items) })
      return
    }
    if (path === '/api/opportunity-groups/stable-group') {
      groupRequests.push(url)
      const activity = url.searchParams.get('activity')
      const groupOffset = Number(url.searchParams.get('offset'))
      if (activity === 'activity-a' && groupOffset === 50) {
        oldLaterPageStarted = true
        await oldLaterPage
        await route.fulfill({ status: 200, json: { items: [oldLast], total: 51, limit: 50, offset: 50, next_offset: null, cohort_token: 'fixture-server-cohort' } })
        return
      }
      await route.fulfill({ status: 200, json: { items: [activity === 'activity-a' ? oldFirst : current], total: activity === 'activity-a' ? 51 : 1, limit: 50, offset: groupOffset, next_offset: activity === 'activity-a' ? 50 : null, cohort_token: 'fixture-server-cohort' } })
      return
    }
    const body = path === '/api/auth/session'
      ? { authenticated: true }
      : path === '/api/health'
        ? { sources: [], backlog: 0, pending_interpretations: 0 }
        : emptyExactNeedAuxiliary(new URL(route.request().url()).pathname) ?? []
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  try {
    await page.goto('/?tier=Signals&activity=activity-a')
    const group = page.locator('[data-opportunity-id="scope-a-first"]')
    await expect(group).toBeVisible()
    await group.click()
    await expect.poll(() => oldLaterPageStarted).toBe(true)
    await page.getByRole('textbox', { name: 'Filter by exact power activity' }).fill('activity-b')
    await expect(page.locator('[data-opportunity-id="scope-b-current"]')).toBeVisible()
    releaseOldLaterPage?.()
    await expect(page.locator('.project-members')).toHaveCount(0)
    await expect(page.locator('[data-opportunity-id="scope-a-last"]')).toHaveCount(0)
    expect(groupRequests.every((request) => request.searchParams.get('cohort_token') === 'fixture-server-cohort')).toBe(true)
    expect(groupRequests.some((request) => request.searchParams.get('activity') === 'activity-a' && request.searchParams.get('offset') === '50')).toBe(true)
    await page.locator('[data-opportunity-id="scope-b-current"]').click()
    await expect(page.locator('.project-members [data-opportunity-id="scope-b-current"]')).toBeVisible()
    await expect(page.locator('.project-members [data-opportunity-id="scope-a-last"]')).toHaveCount(0)
  } finally {
    releaseOldLaterPage?.()
  }
})

test('Back refresh with a rotated cohort token supersedes a pending group expansion', async ({ page }) => {
  const record = permit('token-rotation-member', 'Token rotation group member')
  record.group_id = 'token-rotation-group'
  record.group_title = 'Token rotation group'
  record.group_total_filtered = 2
  record.group_loaded_on_page = 1
  record.group_complete_on_page = false
  let pageRequests = 0
  let releaseGroup: (() => void) | undefined
  const groupGate = new Promise<void>((resolve) => { releaseGroup = resolve })
  let groupStarted = false
  let groupFinished = false
  const groupRequests: URL[] = []
  const pageTokens: string[] = []
  await page.route(apiRoute, async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/opportunities') {
      pageRequests += 1
      const payload = partialServerOpportunityPage([record])
      const token = pageRequests === 1 ? 'token-before-back' : 'token-after-back'
      pageTokens.push(token)
      await route.fulfill({ status: 200, contentType: 'application/json', headers: { ...payload.headers, 'X-Cohort-Token': token, 'X-Limit': '25', 'X-Offset': '0' }, body: JSON.stringify(payload.items) })
      return
    }
    if (url.pathname === '/api/opportunity-groups/token-rotation-group') {
      groupStarted = true
      groupRequests.push(url)
      await groupGate
      await route.fulfill({ status: 200, json: { items: [record], total: 2, limit: 50, offset: 0, next_offset: null, cohort_token: 'token-before-back' } })
      groupFinished = true
      return
    }
    const body = url.pathname === '/api/auth/session'
      ? { authenticated: true }
      : url.pathname === '/api/health'
        ? { sources: [], backlog: 0, pending_interpretations: 0 }
        : emptyExactNeedAuxiliary(new URL(route.request().url()).pathname) ?? []
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  try {
    await page.goto('/?tier=Signals')
    await page.locator('[data-opportunity-id="token-rotation-member"]').click()
    await expect.poll(() => groupStarted).toBe(true)
    expect(groupRequests[0]?.searchParams.get('cohort_token')).toBe('token-before-back')
    await page.evaluate(() => {
      history.pushState(history.state, '', location.href)
      history.back()
    })
    await expect.poll(() => pageRequests).toBe(2)
    expect(pageTokens).toEqual(['token-before-back', 'token-after-back'])
    await expect(page.locator('[data-opportunity-id="token-rotation-member"]')).toBeVisible()
    releaseGroup?.()
    await expect.poll(() => groupFinished).toBe(true)
    await expect(page.locator('.project-members')).toHaveCount(0)
  } finally {
    releaseGroup?.()
  }
})

test('only the latest group expansion intent may open a card or surface its failure', async ({ page }) => {
  const first = permit('intent-first', 'First exact group member')
  const second = permit('intent-second', 'Second exact group member')
  for (const [record, groupId] of [[first, 'intent-group-a'], [second, 'intent-group-b']] as const) {
    record.group_id = groupId
    record.group_title = groupId
    record.group_total_filtered = 2
    record.group_loaded_on_page = 1
    record.group_complete_on_page = false
  }
  let releaseFirst: (() => void) | undefined
  const firstGate = new Promise<void>((resolve) => { releaseFirst = resolve })
  let firstStarted = false
  let failSecond = false
  await page.route(apiRoute, async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/opportunities') {
      const payload = partialServerOpportunityPage([first, second])
      await route.fulfill({ status: 200, contentType: 'application/json', headers: { ...payload.headers, 'X-Limit': '25', 'X-Offset': '0' }, body: JSON.stringify(payload.items) })
      return
    }
    if (url.pathname.startsWith('/api/opportunity-groups/')) {
      if (url.pathname.endsWith('intent-group-a')) {
        firstStarted = true
        await firstGate
        await route.fulfill({ status: 503, json: { detail: 'synthetic stale group failure' } })
        return
      }
      if (failSecond) {
        await route.fulfill({ status: 503, json: { detail: 'synthetic current group failure' } })
        return
      }
      await route.fulfill({ status: 200, json: { items: [second], total: 2, limit: 50, offset: 0, next_offset: null, cohort_token: 'fixture-server-cohort' } })
      return
    }
    const body = url.pathname === '/api/auth/session'
      ? { authenticated: true }
      : url.pathname === '/api/health'
        ? { sources: [], backlog: 0, pending_interpretations: 0 }
        : emptyExactNeedAuxiliary(new URL(route.request().url()).pathname) ?? []
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  try {
    await page.goto('/?tier=Signals')
    await page.locator('[data-opportunity-id="intent-first"]').click()
    await expect.poll(() => firstStarted).toBe(true)
    await page.locator('.opportunity-row[data-opportunity-id="intent-second"]').click()
    await expect(page.locator('.project-members [data-opportunity-id="intent-second"]')).toBeVisible()
    releaseFirst?.()
    await expect(page.locator('.project-members [data-opportunity-id="intent-second"]')).toBeVisible()
    await expect(page.locator('.project-members [data-opportunity-id="intent-first"]')).toHaveCount(0)
    await expect(page.getByRole('alert')).toHaveCount(0)

    await page.locator('.opportunity-row[data-opportunity-id="intent-second"]').click()
    await expect(page.locator('.project-members')).toHaveCount(0)
    failSecond = true
    await page.locator('[data-opportunity-id="intent-second"]').click()
    await expect(page.getByRole('alert')).toContainText('503')
    await expect(page.locator('.project-members')).toHaveCount(0)
  } finally {
    releaseFirst?.()
  }
})

test('reclicking a pending group cancels its expansion and selected-record navigation supersedes it', async ({ page }) => {
  const grouped = permit('pending-group-member', 'Pending group member')
  grouped.group_id = 'pending-group'
  grouped.group_title = 'Pending group'
  grouped.group_total_filtered = 2
  grouped.group_loaded_on_page = 1
  grouped.group_complete_on_page = false
  const selected = permit('pending-selection', 'Selected standalone record')
  selected.group_total_filtered = 1
  selected.group_loaded_on_page = 1
  selected.group_complete_on_page = true
  const groupReleases: (() => void)[] = []
  let groupRequests = 0
  await page.route(apiRoute, async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/opportunities') {
      const payload = partialServerOpportunityPage([grouped, selected])
      await route.fulfill({ status: 200, contentType: 'application/json', headers: { ...payload.headers, 'X-Limit': '25', 'X-Offset': '0' }, body: JSON.stringify(payload.items) })
      return
    }
    if (url.pathname === '/api/opportunity-groups/pending-group') {
      groupRequests += 1
      await new Promise<void>((resolve) => { groupReleases.push(resolve) })
      await route.fulfill({ status: 200, json: { items: [grouped], total: 2, limit: 50, offset: 0, next_offset: null, cohort_token: 'fixture-server-cohort' } })
      return
    }
    const body = url.pathname === '/api/auth/session'
      ? { authenticated: true }
      : url.pathname === '/api/health'
        ? { sources: [], backlog: 0, pending_interpretations: 0 }
        : url.pathname.startsWith('/api/opportunities/needs/')
          ? selected
          : emptyExactNeedAuxiliary(new URL(route.request().url()).pathname) ?? []
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  try {
    await page.goto('/?tier=Signals')
    const group = page.locator('[data-opportunity-id="pending-group-member"]')
    await group.click()
    await expect.poll(() => groupRequests).toBe(1)
    await group.click()
    groupReleases[0]?.()
    await expect(page.locator('.project-members')).toHaveCount(0)
    await group.click()
    await expect.poll(() => groupRequests).toBe(2)
    await page.locator('[data-opportunity-id="pending-selection"]').click()
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Selected Standalone Record')
    groupReleases[1]?.()
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Selected Standalone Record')
    await expect(page.locator('.project-members')).toHaveCount(0)
  } finally {
    for (const release of groupReleases) release()
  }
})

test('group expansion intent is invalidated by tier, search, Signal decision, page, and view transitions', async ({ page }) => {
  const scenarios = [
    { name: 'tier', initialId: 'scope-signal', nextId: 'scope-prospect' },
    { name: 'search', initialId: 'scope-signal', nextId: 'scope-search' },
    { name: 'decision', initialId: 'scope-show', nextId: 'scope-review' },
    { name: 'page', initialId: 'scope-page-first', nextId: 'scope-page-next' },
    { name: 'view', initialId: 'scope-signal', nextId: '' },
  ] as const
  const records = new Map<string, Opportunity>()
  for (const [id, action, options] of [
    ['scope-signal', 'Signal scope activity', {}],
    ['scope-prospect', 'Prospect scope activity', { tier: 'Prospect' }],
    ['scope-search', 'newterm scope activity', {}],
    ['scope-show', 'SHOW scope activity', { decision: 'SHOW' }],
    ['scope-review', 'REVIEW scope activity', { decision: 'REVIEW' }],
    ['scope-page-first', 'First page scope activity', {}],
    ['scope-page-next', 'Next page scope activity', {}],
  ] as const) {
    const record = permit(id, action, options)
    record.group_id = `group-${id}`
    record.group_title = `Group ${id}`
    record.group_total_filtered = 2
    record.group_loaded_on_page = 1
    record.group_complete_on_page = false
    records.set(id, record)
  }
  let activeScenario: typeof scenarios[number] = scenarios[0]
  let releaseGroup: (() => void) | undefined
  let groupGate = Promise.resolve()
  let groupStarted = false
  let groupFinished = false
  await page.route(apiRoute, async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    if (path === '/api/opportunities') {
      const tier = url.searchParams.get('tier')
      const search = url.searchParams.get('search') ?? ''
      const decision = url.searchParams.get('decision') ?? 'ALL'
      const offset = Number(url.searchParams.get('offset') ?? 0)
      const chosenId = tier?.toLowerCase() === 'prospect' ? 'scope-prospect'
        : search ? 'scope-search'
          : decision === 'REVIEW' ? 'scope-review'
            : offset > 0 ? 'scope-page-next'
              : activeScenario.name === 'decision' ? 'scope-show'
                : activeScenario.name === 'page' ? 'scope-page-first' : 'scope-signal'
      const record = records.get(chosenId)!
      const payload = partialServerOpportunityPage([record])
      const headers: Record<string, string> = { ...payload.headers, 'X-Limit': '25', 'X-Offset': String(offset) }
      if (activeScenario.name === 'page' && offset === 0) headers['X-Next-Offset'] = '25'
      await route.fulfill({ status: 200, contentType: 'application/json', headers, body: JSON.stringify(payload.items) })
      return
    }
    if (path.startsWith('/api/opportunity-groups/')) {
      groupStarted = true
      await groupGate
      const groupId = path.split('/').at(-1) ?? ''
      const record = [...records.values()].find((candidate) => candidate.group_id === groupId)!
      await route.fulfill({ status: 200, json: { items: [record], total: 2, limit: 50, offset: 0, next_offset: null, cohort_token: 'fixture-server-cohort' } })
      groupFinished = true
      return
    }
    const body = path === '/api/auth/session'
      ? { authenticated: true }
      : path === '/api/health'
        ? { sources: [], backlog: 0, pending_interpretations: 0 }
        : emptyExactNeedAuxiliary(new URL(route.request().url()).pathname) ?? []
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  try {
  for (const scenario of scenarios) {
    activeScenario = scenario
    groupStarted = false
    groupFinished = false
    groupGate = new Promise<void>((resolve) => { releaseGroup = resolve })
    await page.goto('/?tier=Signals')
    await page.locator(`[data-opportunity-id="${scenario.initialId}"]`).click()
    await expect.poll(() => groupStarted).toBe(true)
    if (scenario.name === 'tier') {
      await page.getByLabel('Qualification tier').selectOption('Prospects')
      await expect(page.locator('[data-opportunity-id="scope-prospect"]')).toBeVisible()
    } else if (scenario.name === 'search') {
      await page.getByRole('textbox', { name: 'Search projects' }).fill('newterm')
      await expect(page.locator('[data-opportunity-id="scope-search"]')).toBeVisible()
    } else if (scenario.name === 'decision') {
      await page.getByRole('button', { name: /^REVIEW/ }).click()
      await expect(page.locator('[data-opportunity-id="scope-review"]')).toBeVisible()
    } else if (scenario.name === 'page') {
      await page.getByRole('button', { name: 'Next →' }).click()
      await expect(page.locator('[data-opportunity-id="scope-page-next"]')).toBeVisible()
    } else {
      await page.getByRole('button', { name: 'Operations' }).click()
      await expect.poll(() => new URL(page.url()).searchParams.get('view')).toBe('ingestion')
    }
    releaseGroup?.()
    await expect.poll(() => groupFinished).toBe(true)
    await expect(page.locator('.project-members')).toHaveCount(0)
    if (scenario.nextId) await expect(page.locator(`[data-opportunity-id="${scenario.nextId}"]`)).toBeVisible()
  }
  } finally {
    releaseGroup?.()
    await page.unroute(apiRoute)
  }
})

test('Previous hides later-page rows and metadata until the first-page request settles', async ({ page }) => {
  const firstPageRecord = permit('transition-first-page', 'First page transition fixture')
  const laterPageRecord = permit('transition-later-page', 'Later page transition fixture')
  let pageZeroRequests = 0
  let releasePrevious: (() => void) | undefined
  let previousStarted = false
  const previousGate = new Promise<void>((resolve) => { releasePrevious = resolve })
  await page.route(apiRoute, async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/opportunities') {
      const offset = Number(url.searchParams.get('offset') ?? '0')
      if (offset === 0) {
        pageZeroRequests += 1
        if (pageZeroRequests > 1) {
          previousStarted = true
          await previousGate
        }
      }
      const payload = serverOpportunityPage([offset === 0 ? firstPageRecord : laterPageRecord])
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: { ...payload.headers, 'X-Limit': '25', 'X-Offset': String(offset), 'X-Cohort-Token': 'transition-token', ...(offset === 0 ? { 'X-Next-Offset': '25' } : {}) },
        body: JSON.stringify(payload.items),
      })
      return
    }
    const path = url.pathname
    const body = path === '/api/auth/session'
      ? { authenticated: true }
      : path === '/api/health'
        ? { sources: [], backlog: 0, pending_interpretations: 0 }
        : emptyExactNeedAuxiliary(new URL(route.request().url()).pathname) ?? []
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  try {
    await page.goto('/?tier=Signals&offset=25')
    await expect(page.locator('[data-opportunity-id="transition-later-page"]')).toBeVisible()
    await page.getByRole('button', { name: '← Previous' }).click()
    await expect.poll(() => previousStarted).toBe(true)
    await expect(page.getByText('Updating this view…')).toBeVisible()
    await expect(page.locator('[data-opportunity-id="transition-later-page"]')).toHaveCount(0)
    await expect(page.getByRole('link', { name: 'Download filtered CSV' })).toHaveCount(0)
    await expect(page.getByRole('heading', { name: 'No Signals yet' })).toHaveCount(0)
    await expect(page.getByText('1 filtered records · page 1')).toHaveCount(0)
    expect(new URL(page.url()).searchParams.get('offset')).toBeNull()
    expect(new URL(page.url()).hash).toBe('')
    releasePrevious?.()
    await expect(page.locator('[data-opportunity-id="transition-first-page"]')).toBeVisible()
    await expect(page.getByRole('link', { name: 'Download filtered CSV' })).toBeVisible()
    await expect(page.getByText('1 filtered records · page 1')).toBeVisible()
  } finally {
    releasePrevious?.()
  }
})

test('Next hides first-page rows and metadata until the later-page request settles', async ({ page }) => {
  const firstPageRecord = permit('transition-next-first-page', 'First page Next fixture')
  const laterPageRecord = permit('transition-next-later-page', 'Later page Next fixture')
  let releaseNext: (() => void) | undefined
  let nextStarted = false
  const nextGate = new Promise<void>((resolve) => { releaseNext = resolve })
  await page.route(apiRoute, async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/opportunities') {
      const offset = Number(url.searchParams.get('offset') ?? '0')
      if (offset > 0) {
        nextStarted = true
        await nextGate
      }
      const payload = serverOpportunityPage([offset === 0 ? firstPageRecord : laterPageRecord])
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: { ...payload.headers, 'X-Limit': '25', 'X-Offset': String(offset), 'X-Cohort-Token': 'transition-next-token', ...(offset === 0 ? { 'X-Next-Offset': '25' } : {}) },
        body: JSON.stringify(payload.items),
      })
      return
    }
    const path = url.pathname
    const body = path === '/api/auth/session'
      ? { authenticated: true }
      : path === '/api/health'
        ? { sources: [], backlog: 0, pending_interpretations: 0 }
        : emptyExactNeedAuxiliary(new URL(route.request().url()).pathname) ?? []
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  try {
    await page.goto('/?tier=Signals')
    await expect(page.locator('[data-opportunity-id="transition-next-first-page"]')).toBeVisible()
    await page.getByRole('button', { name: 'Next →' }).click()
    await expect.poll(() => nextStarted).toBe(true)
    await expect(page.getByText('Updating this view…')).toBeVisible()
    await expect(page.locator('[data-opportunity-id="transition-next-first-page"]')).toHaveCount(0)
    await expect(page.getByRole('link', { name: 'Download filtered CSV' })).toHaveCount(0)
    await expect(page.getByRole('heading', { name: 'No Signals yet' })).toHaveCount(0)
    await expect(page.getByText('1 filtered records · page 1')).toHaveCount(0)
    expect(new URL(page.url()).searchParams.get('offset')).toBe('25')
    releaseNext?.()
    await expect(page.locator('[data-opportunity-id="transition-next-later-page"]')).toBeVisible()
    await expect(page.getByText('1 filtered records · page 2')).toBeVisible()
  } finally {
    releaseNext?.()
  }
})

test('failed Previous clears the later page and reports unavailable instead of an empty cohort', async ({ page }) => {
  const laterPageRecord = permit('transition-error-later-page', 'Later page error fixture')
  let pageZeroRequests = 0
  await page.route(apiRoute, async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/opportunities') {
      const offset = Number(url.searchParams.get('offset') ?? '0')
      if (offset === 0 && ++pageZeroRequests > 1) {
        await route.fulfill({ status: 503, json: { detail: 'First page unavailable for transition test' } })
        return
      }
      const payload = serverOpportunityPage([laterPageRecord])
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: { ...payload.headers, 'X-Limit': '25', 'X-Offset': String(offset), 'X-Cohort-Token': 'transition-error-token', ...(offset === 0 ? { 'X-Next-Offset': '25' } : {}) },
        body: JSON.stringify(payload.items),
      })
      return
    }
    const path = url.pathname
    const body = path === '/api/auth/session'
      ? { authenticated: true }
      : path === '/api/health'
        ? { sources: [], backlog: 0, pending_interpretations: 0 }
        : emptyExactNeedAuxiliary(new URL(route.request().url()).pathname) ?? []
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/?tier=Signals&offset=25')
  await expect(page.locator('[data-opportunity-id="transition-error-later-page"]')).toBeVisible()
  await page.getByRole('button', { name: '← Previous' }).click()
  await expect(page.getByRole('alert')).toContainText('503')
  await expect(page.locator('[data-opportunity-id="transition-error-later-page"]')).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'Download filtered CSV' })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'No Signals yet' })).toHaveCount(0)
  await expect(page.getByText('1 filtered records · page 1')).toHaveCount(0)
  expect(new URL(page.url()).searchParams.get('offset')).toBeNull()
  expect(new URL(page.url()).hash).toBe('')
})

test('failed Next clears the first page and reports unavailable instead of retaining its cards', async ({ page }) => {
  const firstPageRecord = permit('transition-error-first-page', 'First page error fixture')
  await page.route(apiRoute, async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/opportunities') {
      const offset = Number(url.searchParams.get('offset') ?? '0')
      if (offset > 0) {
        await route.fulfill({ status: 503, json: { detail: 'Later page unavailable for transition test' } })
        return
      }
      const payload = serverOpportunityPage([firstPageRecord])
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: { ...payload.headers, 'X-Limit': '25', 'X-Offset': '0', 'X-Next-Offset': '25', 'X-Cohort-Token': 'transition-next-error-token' },
        body: JSON.stringify(payload.items),
      })
      return
    }
    const path = url.pathname
    const body = path === '/api/auth/session'
      ? { authenticated: true }
      : path === '/api/health'
        ? { sources: [], backlog: 0, pending_interpretations: 0 }
        : emptyExactNeedAuxiliary(new URL(route.request().url()).pathname) ?? []
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/?tier=Signals')
  await expect(page.locator('[data-opportunity-id="transition-error-first-page"]')).toBeVisible()
  await page.getByRole('button', { name: 'Next →' }).click()
  await expect(page.getByRole('alert')).toContainText('503')
  await expect(page.locator('[data-opportunity-id="transition-error-first-page"]')).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'Download filtered CSV' })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'No Signals yet' })).toHaveCount(0)
  await expect(page.getByText('1 filtered records · page 1')).toHaveCount(0)
  expect(new URL(page.url()).searchParams.get('offset')).toBe('25')
})

test('project title prefers a current owner over operator, applicant, and contractor claims', () => {
  const record = permit('roles', 'Facility construction', {
    abstract: 'owner_company_name: Owner Company\noperator_company_name: Operating Company\napplicant_org: Applicant Company\ncontractor_company_name: Builder Company',
  })
  expect(projectTitle(record)).toBe('Owner Company · owner')
  record.evidence[0].assessment_current = false
  expect(projectTitle(record)).not.toContain('Owner Company')
})

test('city permit company title shows source role and does not infer ownership', () => {
  const dallas = permit('dallas-1', 'Warehouse construction', {
    abstract: 'lp_business_name: TRICORE BUILDERS INC\ncontact_name: Example Person',
  })
  dallas.evidence[0].source_id = 'dallas-monthly-permits'
  expect(projectTitle(dallas)).toBe('TRICORE BUILDERS INC · LP Business Name · role unverified')

  const houston = permit('houston-1', 'Commercial facility construction')
  houston.title_company = '*MERICHEM TECHNOLOGIES LLC'
  houston.title_company_role = 'permit-listed owner / occupant'
  expect(projectTitle(houston)).toBe('*MERICHEM TECHNOLOGIES LLC · permit-listed owner / occupant')
})

test('city permit organization labels preserve the source role and role uncertainty', () => {
  const dallas = permit('dallas-1', 'Warehouse construction', {
    abstract: 'lp_business_name: TRICORE BUILDERS INC\ncontact_name: Example Person',
  })
  dallas.evidence[0].source_id = 'dallas-monthly-permits'
  expect(projectTitle(dallas)).toBe('TRICORE BUILDERS INC · LP Business Name · role unverified')

  const houston = permit('houston-1', 'Commercial facility construction')
  houston.title_company = '*MERICHEM TECHNOLOGIES LLC'
  houston.title_company_role = 'permit-listed owner / occupant'
  expect(projectTitle(houston)).toBe('*MERICHEM TECHNOLOGIES LLC · permit-listed owner / occupant')
})

test('current official RRC operator labels list and detail titles without buyer authority', () => {
  const record = permit('0917090', 'Drilling permit', {
    abstract: 'row: 0917090\noperator: DE CENTRAL OPERATING, LLC',
  })
  record.evidence[0].source_id = 'texas-rrc-drilling-permits'
  const expected = 'DE CENTRAL OPERATING, LLC · RRC permit-listed operator · buyer authority UNKNOWN'

  expect(projectTitle(record)).toBe(expected)
  record.group_id = 'rrc-group-0917090'
  record.group_title = projectTitle(record)
  expect(serverProjectCards([record])[0].title).toBe(expected)

  record.title_company = 'Verified Buyer'
  record.title_company_role = 'permit-listed owner / occupant'
  expect(projectTitle(record)).toBe('Verified Buyer · permit-listed owner / occupant')
})

test('RRC operator parsing stays on its physical line when the operator is blank', () => {
  const record = permit('rrc-blank-operator', 'Drilling permit', {
    abstract: 'row: 123\noperator: \noperator_number: 456\nlease: TEST',
  })
  record.evidence[0].source_id = 'texas-rrc-drilling-permits'
  expect(projectTitle(record)).not.toContain('RRC permit-listed operator')
  expect(projectTitle(record)).not.toContain('456')
  expect(projectTitle(record)).not.toContain('TEST')

  record.evidence[0].abstract = 'row: 123\noperator:   \nlease:   TEST'
  expect(projectTitle(record)).not.toContain('RRC permit-listed operator')
  expect(projectTitle(record)).not.toContain('TEST')

  record.evidence[0].abstract = 'row: 123\r\noperator: \r\noperator_number: 456\r\nlease: TEST'
  expect(projectTitle(record)).not.toContain('RRC permit-listed operator')
  expect(projectTitle(record)).not.toContain('456')
  expect(projectTitle(record)).not.toContain('TEST')
})

test('RRC operator title requires exact route, current evidence, and one usable name', () => {
  const record = permit('rrc-near-match', 'Drilling permit', {
    abstract: 'operator: Example Operator',
  })
  record.evidence[0].source_id = 'company-news'
  expect(projectTitle(record)).not.toContain('Example Operator')

  record.evidence[0].source_id = 'texas-rrc-drilling-permits'
  record.evidence[0].assessment_current = false
  expect(projectTitle(record)).not.toContain('Example Operator')

  record.evidence[0].assessment_current = true
  record.evidence[0].abstract = 'operator: Unknown'
  expect(projectTitle(record)).not.toContain('buyer authority UNKNOWN')

  record.evidence[0].abstract = 'operator: Example Operator\noperator: Different Operator'
  expect(projectTitle(record)).not.toContain('Example Operator · RRC')
})

test('grouped permit members use company-first titles while retaining each permit record', async ({ page }) => {
  const keeter = permit('COM-NEW-26-000129', 'New data center construction', {
    projectId: 'dallas-campus',
    abstract: 'lp_business_name: KEETER INVESTMENTS LLC\naddress: 2444 FABENS RD, DALLAS, TX',
  })
  const merichem = permit('COM-NEW-26-000130', 'Data center electrical expansion', {
    projectId: 'dallas-campus',
    abstract: 'owner_company_name: MERICHEM TECHNOLOGIES LLC\naddress: 2444 FABENS RD, DALLAS, TX',
  })
  keeter.evidence[0].source_id = 'dallas-monthly-permits'
  merichem.evidence[0].source_id = 'dallas-monthly-permits'
  const records = [keeter, merichem]
  await page.route(apiRoute, async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/opportunities') {
      await fulfillServerOpportunityPage(route, records)
      return
    }
    const body = path === '/api/auth/session'
      ? { authenticated: true }
      : path === '/api/health'
          ? { sources: [], backlog: 0, pending_interpretations: 0 }
          : emptyExactNeedAuxiliary(new URL(route.request().url()).pathname) ?? []
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/?tier=Signals')
  await page.getByRole('button', { name: /KEETER INVESTMENTS LLC · LP Business Name · role unverified/ }).click()
  const keeterMember = page.locator('.project-member[data-opportunity-id="COM-NEW-26-000129"]')
  const merichemMember = page.locator('.project-member[data-opportunity-id="COM-NEW-26-000130"]')
  await expect(keeterMember).toContainText('KEETER INVESTMENTS LLC · LP Business Name · role unverified')
  await expect(merichemMember).toContainText('MERICHEM TECHNOLOGIES LLC · owner')
  await keeterMember.click()
  await expect(page.getByRole('heading', { level: 1, name: 'KEETER INVESTMENTS LLC · LP Business Name · role unverified' })).toBeVisible()
  await expect(page.getByText('COM-NEW-26-000129', { exact: false }).first()).toBeVisible()
})

test('Signals default to All and keep SHOW, REVIEW, and HOLD selectable', async ({ page }) => {
  let records = [
    permit('hold-member', 'Routine hospital maintenance', { projectId: 'shared-project', decision: 'HOLD' }),
    permit('show-member', 'New data center electrical buildout', { projectId: 'shared-project', decision: 'SHOW' }),
    permit('review', 'Possible industrial expansion', { projectId: 'review-project', decision: 'REVIEW' }),
    permit('hold', 'Marathon temporary stage', { projectId: 'hold-project', decision: 'HOLD' }),
    permit('unknown', 'Unadjudicated project', { projectId: 'unknown-project', decision: null }),
  ]
  await page.route(apiRoute, async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/opportunities') {
      await fulfillServerOpportunityPage(route, records)
      return
    }
    const body = path === '/api/auth/session' ? { authenticated: true } : path === '/api/health' ? { sources: [], backlog: 0, pending_interpretations: 0 } : emptyExactNeedAuxiliary(new URL(route.request().url()).pathname) ?? []
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/?tier=Signals')
  await expect(page.getByRole('button', { name: 'All 4' })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('button', { name: /Possible Industrial Expansion/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /Marathon Temporary Stage/ })).toBeVisible()
  await page.getByRole('button', { name: 'SHOW 1' }).click()
  const sharedProject = page.getByRole('button', { name: /New Data Center Electrical Buildout/ })
  await expect(sharedProject).toBeVisible()
  await sharedProject.click()
  const holdMember = page.locator('.project-member[data-opportunity-id="hold-member"]')
  const showMember = page.locator('.project-member[data-opportunity-id="show-member"]')
  await expect(holdMember).toBeVisible()
  await expect(showMember).toBeVisible()
  await expect(holdMember).toContainText(projectTitle(records[0]))
  await expect(showMember).toContainText(projectTitle(records[1]))
  const groupedMemberIds = await page.locator('.project-member').evaluateAll((members) => members.map((member) => member.getAttribute('data-opportunity-id')))
  expect(groupedMemberIds.slice(0, 2)).toEqual(['hold-member', 'show-member'])
  await page.getByRole('button', { name: 'REVIEW 2' }).click()
  await expect(page.getByRole('button', { name: /Possible Industrial Expansion/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /Unadjudicated Project/ })).toBeVisible()
  await page.getByRole('button', { name: 'HOLD 1' }).click()
  await expect(page.getByRole('button', { name: /Marathon Temporary Stage/ })).toBeVisible()
  await page.getByRole('textbox', { name: 'Search projects' }).fill('Marathon')
  await expect(page.getByRole('button', { name: /Marathon Temporary Stage/ })).toBeVisible()
  records = [permit('only-review', 'Unadjudicated campus', { projectId: 'only-review', decision: null })]
  await page.goto('/?tier=Signals')
  await page.getByRole('button', { name: 'SHOW 0' }).click()
  await expect(page.getByRole('heading', { name: 'No SHOW decisions yet' })).toBeVisible()
  await expect(page.getByText('Check REVIEW (1) for uncertain or not-yet-adjudicated projects. An unavailable Jev decision stays visible there.')).toBeVisible()
})

test('only exact dated event evidence groups; titles describe permit work; all records stay openable', async ({ page }) => {
  const currentYear = permit('2026-126812 BP', zilkerDescription)
  const sameEvent = permit('2026-126791 BP', zilkerDescription)
  const nextYear = permit('2027-126791 BP', zilkerDescription.replaceAll('2026', '2027'))
  currentYear.group_id = 'event:zilker:2026-10'
  sameEvent.group_id = 'event:zilker:2026-10'
  nextYear.group_id = 'event:zilker:2027-10'
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
    if (path === '/api/opportunities') {
      await fulfillServerOpportunityPage(route, browseRecords)
      return
    }
    const body = path === '/api/auth/session' ? { authenticated: true } : path === '/api/health' ? { sources: [], backlog: 0, pending_interpretations: 0 } : emptyExactNeedAuxiliary(new URL(route.request().url()).pathname) ?? []
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/?tier=Signals')
  const summaryCard = page.getByRole('button', { name: /New data center construction/ }).first()
  await expect(summaryCard).toContainText('Hampton, Georgia')
  await expect(page.getByRole('button', { name: /New Data Center Campus Construction/ })).toContainText('100 MW campus capacity · 20 MW utility service')
  await expect(summaryCard).not.toContainText('Load unknown')
  await expect(summaryCard).not.toContainText('assessment')
  await expect(summaryCard).not.toContainText('georgia-air-draft-title-v')
  await expect(page.locator('body')).not.toHaveCSS('overflow-x', 'scroll')

  await page.route(apiRoute, async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/opportunities') {
      await fulfillServerOpportunityPage(route, records)
      return
    }
    const body = path === '/api/auth/session'
      ? { authenticated: true }
      : path === '/api/health'
          ? { sources: [], backlog: 0, pending_interpretations: 0 }
          : emptyExactNeedAuxiliary(new URL(route.request().url()).pathname) ?? []
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/?tier=Signals')
  await expect(page.getByRole('heading', { name: /2 filtered project cards · 3 filtered opportunity records/ })).toBeVisible()
  const project = page.getByRole('button', { name: /Zilker Park.*Oct 2026/ })
  await expect(project).toBeVisible()
  await project.click()
  await expect(page.getByText('2 matching · 2 related permit records')).toBeVisible()
  const currentPermitMember = page.locator('.project-member[data-opportunity-id="2026-126812 BP"]')
  await expect(currentPermitMember).toBeVisible()
  await expect(currentPermitMember).toContainText(projectTitle(currentYear))
  await currentPermitMember.click()
  await expect(page.getByRole('heading', { level: 1, name: /Zilker Park.*Oct 2026/ })).toBeVisible()
  await expect(page.getByText('austin-building-permits · 2026-126812 BP')).toBeVisible()
  await page.getByRole('button', { name: /Back to Signals/ }).click()

  await page.getByRole('button', { name: /^SHOW \d+$/ }).click()
  await page.getByRole('textbox', { name: 'Search projects' }).fill('2026-126812 BP')
  await expect(page.getByRole('heading', { name: 'Signals · 1 filtered project cards · 2 filtered opportunity records' })).toBeVisible()
  const searchResult = page.locator('.opportunity-row').filter({ hasText: /Zilker Park.*Oct 2026/ })
  await expect(searchResult).toBeVisible()
  if (!(await page.getByText('1 matching · 2 related permit records').isVisible())) await searchResult.click()
  await expect(page.getByText('1 matching · 2 related permit records')).toBeVisible()
  await expect(currentPermitMember).toBeVisible()
})
