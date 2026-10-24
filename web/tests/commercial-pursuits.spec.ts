import { expect, test } from '@playwright/test'
import type { CommercialTriage, CommercialTriageCard } from '../src/api/client'

const emptyMapWindow = {
  items: [], total_count: 0, loaded_count: 0, is_subset: false, window_limit: 200,
  group_total_count: 0, cohort_token: 'fixture-map-window',
  decision_counts: { SHOW: 0, REVIEW: 0, HOLD: 0 },
}

const base: CommercialTriage = {
  evaluated_at: '2026-10-03T14:00:00Z', policy_version: 'v1', total: 2,
  cohort_counts: { action_now: 1, research: 1, watch: 0, reject: 0 },
  daily: { evaluated: 2, surfaced: 1, contacted: 0, reached_buyer: null, qualified: null, promoted_prospects: 0, promoted_leads: 0, supported_mw: null, metric_scope: ['Counts reflect current UTC day.'], unavailable_metrics: ['Buyer authority remains unverified.'] },
  items: [
    { id: 'need-a', project_id: 'project-a', related_project_ids: ['project-a', 'project-a-related'], lifecycle_timeline: [{ state: 'Under construction', event_type: 'construction_start', date: '2026-09-28', value_kind: 'project_milestone', evidence_url: 'https://example.test/timeline', current: true, published_at: '2026-09-29', event_date_label: null }, { state: 'Planned', event_type: 'prior_plan', date: null, value_kind: 'project_milestone', evidence_url: 'https://example.test/timeline-old', current: false, published_at: null, event_date_label: null }], related_need_ids: ['need-a', 'need-a-sibling', 'need-a-closed'], related_need_states: [{ need_id: 'need-a', project_id: 'project-a', disposition: 'ACTION NOW', reason: 'Active campus construction is retained.', held: false, conflict_state: 'clear', closed: false }, { need_id: 'need-a-sibling', project_id: 'project-a', disposition: 'RESEARCH', reason: 'Sibling evidence conflicts on project stage.', held: true, conflict_state: 'conflict', closed: false }, { need_id: 'need-a-closed', project_id: 'project-a', disposition: 'WATCH', reason: 'Earlier need was closed.', held: false, conflict_state: 'clear', closed: true }], pursuit_id: 'pursuit-a', name: 'Northstar Campus', location: 'Ohio · location approximate', tier: 'Signal', activity: 'electrical-construction', industry: 'data_center', disposition: 'ACTION NOW', reason: 'A retained filing describes active campus construction.', required_mw: null, start_window: null, duration: null, supply: 'Unknown', stage: { stage: 'project_construction', date: '2026-09-28', source_url: 'https://example.test/stage', evidence_id: 'ev-stage' }, organization: 'Northstar', organization_role: 'Unknown', contacts: [], facts: [{ text: 'Construction filing accepted.', evidence_id: 'ev-1', url: 'https://example.test/fact', hash: 'abcdef1234567890', date: '2026-09-28' }], hypothesis: 'Temporary power may be needed during construction.', unknowns: ['Activity-specific load', 'Utility service timing'], blockers: ['No activity-specific MW'], next_question: 'What is the electrical load and energization window for this construction phase?', next_action: 'Verify scope and electrical package owner.', watch: null, sources: [{ text: 'Filing status: accepted.', evidence_id: 'ev-1', url: 'https://example.test/fact', hash: 'abcdef1234567890', date: '2026-09-28' }], conflict_state: 'clear', input_hash: 'hash-a', notes: [] },
    { id: 'need-b', project_id: 'project-b', related_need_ids: ['need-b'], pursuit_id: null, name: 'South Ridge Works', location: null, tier: 'Signal', activity: 'industrial expansion', industry: 'Industrial', disposition: 'RESEARCH', reason: 'An expansion announcement lacks a confirmed construction date.', required_mw: null, start_window: null, duration: null, supply: 'Unknown', stage: { stage: 'Announced', date: null, source_url: null, evidence_id: null }, organization: null, organization_role: null, contacts: [], facts: [], hypothesis: null, unknowns: ['Site address', 'Project stage'], blockers: [], next_question: 'What is the project site address and current construction stage?', next_action: 'Verify the site address and project stage.', watch: null, sources: [], conflict_state: 'clear', input_hash: 'hash-b', notes: [] },
  ],
}

async function contrastRatio(locator: import('@playwright/test').Locator) {
  return locator.evaluate((node) => {
    const channels = (value: string) => value.match(/[\d.]+/g)?.map(Number) ?? []
    const luminance = (value: string) => {
      const [red, green, blue] = channels(value).slice(0, 3).map((channel) => {
        const linear = channel / 255
        return linear <= 0.04045 ? linear / 12.92 : ((linear + 0.055) / 1.055) ** 2.4
      })
      return 0.2126 * red + 0.7152 * green + 0.0722 * blue
    }
    const foreground = getComputedStyle(node).color
    let backgroundNode: Element | null = node
    let background = 'rgb(255, 255, 255)'
    while (backgroundNode) {
      const value = getComputedStyle(backgroundNode).backgroundColor
      const components = channels(value)
      if (components.length === 3 || components[3] === 1) { background = value; break }
      backgroundNode = backgroundNode.parentElement
    }
    const [light, dark] = [luminance(foreground), luminance(background)].sort((a, b) => b - a)
    if (Number.isNaN(light) || Number.isNaN(dark)) throw new Error(`Cannot calculate contrast: foreground=${foreground}; background=${background}`)
    return (light + 0.05) / (dark + 0.05)
  })
}

async function useCommercialFixture(page: import('@playwright/test').Page, researchStatus = 200, failFirstNote = false, m4Scenario: 'completed' | 'unknown' | 'invalid_citation' | 'unvalidated_legacy' | null = null) {
  let savedNote: NonNullable<CommercialTriageCard['notes']>[number] | null = null
  let receivedQuestion = ''
  let statusQuestion = ''
  let researchCalls = 0
  let statusCalls = 0
  let evaluationCalls = 0
  let intelligenceFeedback: Record<string, unknown> | null = null
  const intelligenceNeedRequests: string[] = []
  const intelligenceHistoryQueries: { needId: string; limit: string | null; taskType: string | null }[] = []
  const noteIds: string[] = []
  await page.route('**/api/auth/session', (route) => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/health', (route) => route.fulfill({ json: {} }))
  await page.route(/\/api\/opportunities\?/, (route) => route.fulfill({ json: [] }))
  await page.route('**/api/changes', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/commercial/triage/*/autonomous-research', (route) => route.fulfill({ json: { items: [] } }))
  await page.route('**/api/intelligence/tasks', (route) => route.fulfill({ json: {
    items: [{ task_type: 'GROUNDED_DOSSIER', question_id: 'TEMP_LOAD_MW', eligible: false, reason: 'INTELLIGENCE_DISABLED', provider: null, pinned_model: null }],
    mode: 'disabled', enabled: false, provider_configuration: { openai_key_present: false, typesafe_key_present: false }, note: 'Configuration metadata only.',
  } }))
  await page.route(url => /^\/api\/intelligence\/needs\/[^/]+\/history$/.test(url.pathname), async (route) => {
    const requestUrl = new URL(route.request().url())
    const needId = requestUrl.pathname.split('/')[4]
    const limit = requestUrl.searchParams.get('limit')
    const taskType = requestUrl.searchParams.get('task_type')
    expect(limit).toBe('20')
    if (taskType !== null) expect(taskType).toBe('COMMERCIAL_ASSESSMENT_V1')
    intelligenceHistoryQueries.push({ needId, limit, taskType })
    intelligenceNeedRequests.push(needId)
    if (needId === 'need-a') await new Promise((resolve) => setTimeout(resolve, 250))
    const candidate = {
      field: 'temporary_load_mw', value: '2.0', unit: 'MW', evidence_id: 'ev-intel', evidence_hash: 'a'.repeat(64),
      quote: 'Synthetic filing states an activity-specific 2.0 MW load.', section: 'abstract', page: null,
      span_start: 0, span_end: 'Synthetic filing states an activity-specific 2.0 MW load.'.length,
      publisher: 'Synthetic utility filing', published_date: '2026-10-10', support: 'direct', status: 'candidate',
      source_url: 'https://example.test/intelligence-evidence', source_id: 'utility-filings',
    }
    const m4Job = m4Scenario ? {
      job_id: `job-m4-${m4Scenario}`, task_type: 'COMMERCIAL_ASSESSMENT_V1', need_id: needId,
      status: m4Scenario === 'unknown' ? 'unknown' : 'completed', validation_outcome: ['unknown', 'unvalidated_legacy'].includes(m4Scenario) ? 'UNKNOWN' : 'VALIDATED',
      result_status: 'validated', validation_reason: null,
      result: m4Scenario === 'unknown' ? null : { disposition: 'UNRESOLVED', reason_code: 'EXCERPT_INSUFFICIENT', next_question: 'What load is required?', next_action: 'Verify the load with the project team.', unknown_fields: ['REQUIRED_MW'], selected_fact_ids: ['f-m4'], actual_model: 'gpt-6.1-sol' },
      commercial_assessment_support: m4Scenario === 'invalid_citation'
        ? { status: 'saved', document_coverage: 'RECORD_EXCERPT', source_collection_status: 'PARTIAL', selected_facts: [{ fact_id: 'f-m4', support_status: 'unavailable', unavailable_reason: 'SAVED_CITATION_FAILED_VALIDATION', citation: null }] }
        : { status: 'saved', document_coverage: 'RECORD_EXCERPT', source_collection_status: 'PARTIAL', selected_facts: [{ fact_id: 'f-m4', field: 'application_stage', value: 'Permit application', label: 'REPORTED', support_status: 'saved', citation: { evidence_id: 'ev-m4', evidence_hash: 'b'.repeat(64), source_url: 'https://example.test/m4', excerpt: 'Application stage: Permit application', field: 'abstract', start: 18, end: 36 } }] },
      error: m4Scenario === 'unknown' ? 'ProviderResponseError' : null, evidence_ids: ['ev-m4'], logical_call_id: 'call-m4',
      usage: { input_tokens: 10, output_tokens: 8, cost_usd: null }, reserved: true, uncertain: m4Scenario === 'unknown', created_at: '2026-10-10T12:00:00Z', completed_at: null,
    } : null
    await route.fulfill({ json: { items: needId === 'need-a' ? [{
      job_id: 'job-intel-a', task_type: 'GROUNDED_DOSSIER', need_id: needId, status: 'completed',
      result: { candidates: [candidate], hypotheses: ['Potential temporary need'], contradictions: [], unresolved_questions: ['Utility service date'], candidate_orgs: [], proposed_queries: [], suggested_pursuit: null },
      error: null, evidence_ids: ['ev-intel'], logical_call_id: 'call-intel-a', usage: { input_tokens: 18, output_tokens: 24, cost_usd: null },
      reserved: true, uncertain: false, created_at: '2026-10-10T12:00:00Z', completed_at: '2026-10-10T12:00:01Z',
    }, ...(m4Job ? [m4Job] : [])] : [] } })
  })
  await page.route('**/api/intelligence/needs/need-a/feedback', async (route) => {
    intelligenceFeedback = route.request().postDataJSON() as Record<string, unknown>
    await route.fulfill({ json: { id: 'review-note-a', client_id: (intelligenceFeedback as { client_id: string }).client_id, metadata: { review_state: 'pending_independent_review' }, note: 'Owner review saved', created_at: '2026-10-10T12:01:00Z' } })
  })
  await page.route('**/api/projects/*/buying-chain', (route) => {
    const projectId = new URL(route.request().url()).pathname.split('/')[3]
    return route.fulfill({ json: {
      project_id: projectId, status: 'available', policy_version: 'buying-chain-v2-permits', unresolved: [], runs: [], permit_summaries: [],
      candidates: projectId === 'project-a' ? [{ id: 'buyer-a', organization: 'Northstar Electric', person_name: 'Avery Chen', title: 'Project Engineer', category: 'ELECTRICAL_CONTRACTOR', organization_relationship: 'DIRECT', person_organization_relationship: 'CURRENT', person_project_relationship: 'UNKNOWN', evidence_strength: 'SUPPORTED', reason: 'A project filing names the electrical contractor.', observed_at: '2026-10-03T14:00:00Z', verified_at: null, history_count: 1, stale: false, public_contacts: [], evidence: [{ id: 'claim-a', url: 'https://example.test/buyer', quote: 'Northstar Electric is listed.', supports: 'CONTRACTOR_ROLE', extraction_location: 'Applicant section', published_at: null, observed_at: '2026-10-03T14:00:00Z', content_hash: 'hash-buyer' }] }] : [],
    } })
  })
  await page.route(/\/api\/commercial\/triage\?limit=50$/, (route) => {
    const current = structuredClone(base)
    if (savedNote) current.items[0].notes = [savedNote]
    return route.fulfill({ json: current })
  })
  await page.route('**/api/commercial/triage/evaluate', async (route) => {
    evaluationCalls += 1
    await route.fulfill({ json: base })
  })
  await page.route('**/api/pursuits/pursuit-a/notes', async (route) => {
    const body = route.request().postDataJSON() as { client_id: string; note: string; outcome: string; next_action: string }
    noteIds.push(body.client_id)
    if (failFirstNote && noteIds.length === 1) return route.fulfill({ status: 503, json: { detail: 'Temporary note response failure.' } })
    savedNote = { ...body, id: 'note-a', owner: 'Operator', created_at: '2026-10-03T14:06:00Z', follow_up: null } as NonNullable<CommercialTriageCard['notes']>[number]
    await route.fulfill({ status: 200, json: savedNote })
  })
  await page.route('**/api/commercial/triage/need-a/research', async (route) => {
    researchCalls += 1
    const body = route.request().postDataJSON() as { question: string }
    receivedQuestion = body.question
    await route.fulfill(researchStatus === 200
      ? { json: { status: 'pending', stale: false, generated_at: null, result: null, citations: [], error: null, input_tokens: 0, output_tokens: 0, job_id: 'job-a' } }
      : { status: researchStatus, json: { detail: 'Research worker unavailable.' } })
  })
  await page.route('**/api/commercial/triage/need-a/research?*', async (route) => {
    statusCalls += 1
    statusQuestion = new URL(route.request().url()).searchParams.get('question') ?? ''
    await route.fulfill({ json: statusCalls === 1
      ? { status: 'pending', job_id: 'job-a', input_hash: 'fingerprint-a', generated_at: null, result: null, citations: [], error: null }
      : { status: 'ready', job_id: 'job-a', input_hash: 'fingerprint-a', generated_at: '2026-10-03T14:05:00Z', result: { event_summary: [{ text: 'Source review confirms the filing stage.', evidence_id: 'ev-1' }], commercial_hypothesis: { text: 'Timing needs confirmation.', evidence_id: 'ev-1' }, unknowns: ['Need-specific MW remains unknown.'], next_step: 'Confirm the activity load schedule.' }, citations: [{ evidence_id: 'ev-1', url: 'https://example.test/fact', title: 'Retained filing' }], error: null } })
  })
  await page.goto('/?view=pursuits')
  return { get savedNote() { return savedNote }, get receivedQuestion() { return receivedQuestion }, get statusQuestion() { return statusQuestion }, get researchCalls() { return researchCalls }, get statusCalls() { return statusCalls }, get evaluationCalls() { return evaluationCalls }, get intelligenceFeedback() { return intelligenceFeedback }, intelligenceNeedRequests, intelligenceHistoryQueries, noteIds }
}

type M6Scenario = 'completed' | 'unknown' | 'invalid_citation' | 'unvalidated_legacy' | 'missing_estimate'
const m6Need = (id: string, name: string, projectId: string) => ({
  id, project_id: projectId, name, location: 'Austin, TX', tier: 'Signal', workflow_status: 'New', activity: 'construction',
  rationale: 'A retained project filing supports investigation.', signal_evidence_state: 'active', conflict_state: 'Not assessed',
  required_mw: null, supply: 'Unknown', start_window: null, duration: null,
  evidence: [{ id: `ev-${id}`, source_id: 'city-permit', document_number: 'P-1', title: 'Permit filing', url: 'https://example.test/m4', published_at: null, retrieved_at: '2026-10-18T10:00:00Z', event_date: null, event_date_label: 'Event date', source_origin: 'City permits', extraction_location: 'Page 1', abstract: 'Construction filing.' }],
  missing_facts: ['Activity-specific load', 'Suitable utility supply'], project_identity_key: name, commercial_disposition: 'RESEARCH',
  commercial_reason: 'Load and supply remain unknown.', commercial_next_question: 'Who owns the electrical scope?', commercial_next_action: 'Research the project contractor.',
  commercial_organization: null, qualified_remaining_gap: null,
} as any)

async function useM6WorkspaceFixture(page: import('@playwright/test').Page, scenario: M6Scenario, includeSecond = false) {
  const needs = [m6Need('need-a', 'Northstar Campus', 'project-a')]
  const historyRequests: { needId: string; taskType: string | null; limit: string | null }[] = []
  if (includeSecond) needs.push(m6Need('need-b', 'South Ridge Works', 'project-b'))
  const result = {
    disposition: 'UNRESOLVED', reason_code: 'EXCERPT_INSUFFICIENT', next_question: 'What load is required?',
    next_action: 'Verify the load with the project team.', unknown_fields: ['REQUIRED_MW'], selected_fact_ids: ['f-m4'],
    actual_model: 'gpt-6.1-sol',
  }
  const completed = scenario !== 'unknown'
  const validated = !['unknown', 'unvalidated_legacy'].includes(scenario)
  const support = scenario === 'unknown' ? { status: 'unavailable', reason: 'ASSESSMENT_SUPPORT_UNAVAILABLE', selected_facts: [] }
    : { status: 'saved', document_coverage: 'RECORD_EXCERPT', source_collection_status: 'PARTIAL', selected_facts: [{
      fact_id: 'f-m4', field: 'application_stage', value: 'Permit application', label: 'REPORTED',
      support_status: scenario === 'invalid_citation' ? 'unavailable' : 'saved',
      unavailable_reason: scenario === 'invalid_citation' ? 'SAVED_CITATION_FAILED_VALIDATION' : null,
      citation: scenario === 'invalid_citation' ? null : { evidence_id: 'ev-need-a', evidence_hash: 'b'.repeat(64), source_url: 'https://example.test/m4', excerpt: 'Permit application', field: 'abstract', start: 19, end: 37 },
    }] }
  const usage = { input_tokens: 10, output_tokens: 8, ...(scenario === 'completed' ? { estimated_cost_usd: '0.0057725', cost_basis: 'conservative_usage_estimate_not_invoice' } : {}) }
  const job = {
    job_id: `job-m4-${scenario}`, task_type: 'COMMERCIAL_ASSESSMENT_V1', need_id: 'need-a',
    status: completed ? 'completed' : 'unknown', validation_outcome: validated ? 'VALIDATED' : 'UNKNOWN',
    result_status: 'validated', validation_reason: scenario === 'unvalidated_legacy' ? 'UNKNOWN' : null,
    result: completed ? result : null, commercial_assessment_support: support,
    error: scenario === 'unknown' ? 'ProviderResponseError' : null, evidence_ids: ['ev-need-a'],
    logical_call_id: 'call-m4', usage, reserved: true, uncertain: scenario === 'unknown',
    created_at: '2026-10-10T12:00:00Z', completed_at: completed ? '2026-10-10T12:00:01Z' : null,
  }
  await page.route('**/api/auth/session', route => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/health', route => route.fulfill({ json: {} }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: {
    items: needs, total: needs.length, counts: { action_now: 0, research: needs.length, watch: 0, reject: 0 },
    offset: 0, limit: 25, next_offset: null, cohort_token: 'm6-fixture', count_unit: 'power needs', changes_available: false,
  } }))
  await page.route('**/api/opportunities/workspace/changes*', route => route.fulfill({ json: {
    items: [], counts: { discovered: 0, changed: 0, promoted: 0, closed: 0, review_exception: 0 },
    total_unreviewed: 0, offset: 0, limit: 50, next_offset: null, evaluated_at: null,
    baseline_identity: null, baseline_reviewed_at: null, first_use: true, token: 'm6-fixture', source_health_exceptions: [],
  } }))
  await page.route(url => /^\/api\/opportunities\/needs\/need-[ab]$/.test(url.pathname), route => {
    const id = new URL(route.request().url()).pathname.split('/').at(-1)!
    return route.fulfill({ json: needs.find(item => item.id === id) ?? needs[0] })
  })
  await page.route('**/api/power-needs/need-*/title', route => route.fulfill({ json: { status: 'disabled', result: null, citations: [], generated_at: null, model: null, error: null } }))
  await page.route(url => /^\/api\/intelligence\/needs\/[^/]+\/history$/.test(url.pathname), route => {
    const requestUrl = new URL(route.request().url())
    const needId = requestUrl.pathname.split('/')[4]
    const taskType = requestUrl.searchParams.get('task_type')
    const limit = requestUrl.searchParams.get('limit')
    historyRequests.push({ needId, taskType, limit })
    return route.fulfill({ json: { items: needId === 'need-a' ? [job] : [] } })
  })
  await page.goto('/?view=workspace')
  return { historyRequests }
}

test('advisory candidates cite the exact source, preserve UNKNOWNs, and save pending owner review', async ({ page }) => {
  const captured = await useCommercialFixture(page)
  await page.locator('.commercial-list .commercial-card-heading').click()
  const research = page.getByRole('region', { name: 'Advisory intelligence research' })
  await expect(research).toContainText('Unaccepted source candidates')
  await expect(research).toContainText('Synthetic filing states an activity-specific 2.0 MW load.')
  await expect(research.getByRole('link', { name: 'open source' })).toHaveAttribute('href', 'https://example.test/intelligence-evidence')
  await expect(research).toContainText('Utility service date')
  await expect(research.getByRole('button', { name: 'Research retained evidence' })).toBeDisabled()
  await research.getByLabel('Owner review').selectOption('CONFLICT')
  await research.getByLabel('Review note').fill('The quoted load is not confirmed for this activity.')
  await research.getByRole('button', { name: 'Save attributed review' }).click()
  await expect(research).toContainText('pending-review material')
  const review = captured.intelligenceFeedback as { decision: string; logical_call_id: string; candidate: { evidence_hash: string; source_url: string }; evidence_refs: { evidence_id: string }[] }
  expect(review.decision).toBe('CONFLICT')
  expect(review.logical_call_id).toBe('call-intel-a')
  expect(review.candidate.evidence_hash).toBe('a'.repeat(64))
  expect(review.candidate.source_url).toBe('https://example.test/intelligence-evidence')
  expect(review.evidence_refs[0].evidence_id).toBe('ev-intel')
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(research.getByLabel('Review note')).toBeVisible()
  await research.getByLabel('Review note').focus()
  await expect(research.getByLabel('Review note')).toBeFocused()
})

test('all ineligible intelligence tasks retain a real selection and explain why requests are unavailable', async ({ page }) => {
  await useCommercialFixture(page)
  await page.locator('.commercial-list .commercial-card-heading').click()
  const research = page.getByRole('region', { name: 'Advisory intelligence research' })
  const task = research.getByLabel('Research task')
  await expect(task).toHaveValue('GROUNDED_DOSSIER|TEMP_LOAD_MW')
  await expect(task.locator('option:checked')).toHaveText('Temporary electrical load')
  await expect(research.getByRole('button', { name: 'Research retained evidence' })).toBeDisabled()
  await expect(research.getByRole('status')).toContainText('Research is unavailable for Temporary electrical load: INTELLIGENCE_DISABLED.')
})

test('switching exact need aborts stale intelligence history and clears prior candidates', async ({ page }) => {
  const captured = await useM6WorkspaceFixture(page, 'completed', true)
  await page.locator('[data-need-row="need-a"]').click()
  await page.getByRole('button', { name: 'Power Analysis' }).click()
  const assessment = page.getByRole('region', { name: 'Saved commercial assessment' })
  await expect(assessment).toContainText('UNRESOLVED')
  await page.locator('[data-need-row="need-b"]').click()
  await page.getByRole('button', { name: 'Power Analysis' }).click()
  await expect(page.getByRole('region', { name: 'Saved commercial assessment' })).toContainText('No saved commercial assessment is available for this need.')
  await expect(page.getByRole('region', { name: 'Saved commercial assessment' })).not.toContainText('UNRESOLVED')
  expect(captured.historyRequests).toContainEqual({ needId: 'need-a', taskType: 'COMMERCIAL_ASSESSMENT_V1', limit: '20' })
  expect(captured.historyRequests).toContainEqual({ needId: 'need-b', taskType: 'COMMERCIAL_ASSESSMENT_V1', limit: '20' })
})

test('commercial assessment renders verified facts, fail-closed citations, UNKNOWN, and mobile layout', async ({ page }, testInfo) => {
  const captured = await useM6WorkspaceFixture(page, 'completed')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.locator('[data-need-row="need-a"]').click()
  await page.getByRole('button', { name: 'Power Analysis' }).click()
  const assessment = page.getByRole('region', { name: 'Saved commercial assessment' })
  await expect(assessment).toContainText('UNRESOLVED')
  await expect(assessment).toContainText('Still unknown')
  await expect(assessment).toContainText('Saved historical support')
  await expect(assessment.getByRole('link', { name: 'Open cited source' })).toHaveAttribute('href', 'https://example.test/m4')
  expect(captured.historyRequests).toContainEqual({ needId: 'need-a', taskType: 'COMMERCIAL_ASSESSMENT_V1', limit: '20' })
  await assessment.getByText('Assessment details', { exact: true }).click()
  await expect(assessment).toContainText('Returned model: gpt-6.1-sol')
  await expect(assessment).toContainText('Recorded estimate: $0.0057725 USD · Estimate basis: conservative usage estimate (not an invoice) · Invoice: UNKNOWN')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('m6-assessment-completed-390.png'), fullPage: true })
})

test('invalid commercial-assessment citation is shown without an actionable source link', async ({ page }) => {
  const captured = await useM6WorkspaceFixture(page, 'invalid_citation')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.locator('[data-need-row="need-a"]').click()
  await page.getByRole('button', { name: 'Power Analysis' }).click()
  const assessment = page.getByRole('region', { name: 'Saved commercial assessment' })
  await expect(assessment).toContainText('Selected source support unavailable')
  await expect(assessment.getByRole('link', { name: 'Open cited source' })).toHaveCount(0)
  expect(captured.historyRequests).toContainEqual({ needId: 'need-a', taskType: 'COMMERCIAL_ASSESSMENT_V1', limit: '20' })
})

test('legacy result_status cannot substitute for an explicit VALIDATED outcome', async ({ page }) => {
  const captured = await useM6WorkspaceFixture(page, 'unvalidated_legacy')
  await page.locator('[data-need-row="need-a"]').click()
  await page.getByRole('button', { name: 'Power Analysis' }).click()
  const assessment = page.getByRole('region', { name: 'Saved commercial assessment' })
  await expect(assessment).toContainText('Assessment COMPLETED: UNKNOWN')
  await expect(assessment).not.toContainText('UNRESOLVED')
  expect(captured.historyRequests).toContainEqual({ needId: 'need-a', taskType: 'COMMERCIAL_ASSESSMENT_V1', limit: '20' })
})

test('UNKNOWN commercial assessment keeps retry blocked visible on mobile', async ({ page }, testInfo) => {
  const captured = await useM6WorkspaceFixture(page, 'unknown')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.locator('[data-need-row="need-a"]').click()
  await page.getByRole('button', { name: 'Power Analysis' }).click()
  const assessment = page.getByRole('region', { name: 'Saved commercial assessment' })
  await expect(assessment).toContainText('ProviderResponseError')
  await expect(assessment).toContainText('Provider outcome UNKNOWN; retry is blocked until reconciled.')
  await expect(assessment).not.toContainText('UNRESOLVED')
  expect(captured.historyRequests).toContainEqual({ needId: 'need-a', taskType: 'COMMERCIAL_ASSESSMENT_V1', limit: '20' })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('m6-assessment-unknown-390.png'), fullPage: true })
})

test('commercial assessment reports UNKNOWN when no recorded estimate is present', async ({ page }) => {
  const captured = await useM6WorkspaceFixture(page, 'missing_estimate')
  await page.locator('[data-need-row="need-a"]').click()
  await page.getByRole('button', { name: 'Power Analysis' }).click()
  const assessment = page.getByRole('region', { name: 'Saved commercial assessment' })
  await assessment.getByText('Assessment details', { exact: true }).click()
  await expect(assessment).toContainText('Estimate: UNKNOWN · Estimate basis: UNKNOWN · Invoice: UNKNOWN')
  expect(captured.historyRequests).toContainEqual({ needId: 'need-a', taskType: 'COMMERCIAL_ASSESSMENT_V1', limit: '20' })
})

test('commercial queue filters backend states, exposes UNKNOWN, and saves targeted research and linked notes', async ({ page }) => {
  const captured = await useCommercialFixture(page, 200, true)
  await expect(page.getByRole('heading', { name: 'What should we work today?' })).toBeVisible()
  await expect(page.getByRole('button', { name: /ACTION NOW 1/ })).toBeVisible()
  await page.getByText('Queue details and research updates').click()
  await page.getByRole('button', { name: 'Evaluate Signals' }).click()
  await expect(page.getByRole('button', { name: 'Evaluate Signals' })).toBeEnabled()
  expect(captured.evaluationCalls).toBe(1)
  await expect(page.locator('.commercial-list .commercial-card')).toHaveCount(1)
  await page.locator('.commercial-list .commercial-card-heading').click()
  await expect(page.locator('.commercial-card-facts')).toContainText('Power Unknown')
  await expect(page.locator('.commercial-list .commercial-card-heading')).toContainText('Data center · Electrical construction')
  await expect(page.locator('.commercial-card-facts')).toContainText('Stage Project construction')
  await expect(page.locator('.commercial-detail')).toContainText('Activity-specific load')
  await expect(page.locator('.commercial-detail')).toContainText('Construction filing accepted.')
  await expect(page.locator('.commercial-detail')).toContainText('Related need states')
  await expect(page.locator('.commercial-related-needs')).toContainText('RESEARCH · need-a-sibling · held · conflict: Conflict')
  await expect(page.locator('.commercial-related-needs')).toContainText('WATCH · need-a-closed · closed')
  await expect(page.locator('.commercial-detail')).toContainText('Group review question: What is the electrical load and energization window for this construction phase?')
  expect(await contrastRatio(page.locator('.commercial-toolbar h2'))).toBeGreaterThanOrEqual(4.5)
  expect(await contrastRatio(page.locator('.buying-chain h3').first())).toBeGreaterThanOrEqual(4.5)
  expect(await contrastRatio(page.locator('.buying-chain-note').first())).toBeGreaterThanOrEqual(4.5)
  expect(await contrastRatio(page.locator('.buying-chain a').last())).toBeGreaterThanOrEqual(4.5)
  await expect(page.getByRole('heading', { name: 'Buying Chain' }).first()).toBeVisible()
  await expect(page.locator('.buying-chain')).toContainText('Avery Chen')
  await expect(page.locator('.buying-chain')).toContainText('Person → project')
  await expect(page.locator('.buying-chain')).toContainText('Project relationship unknown')
  await expect(page.locator('.commercial-project-chain')).toHaveCount(1)
  await page.getByRole('button', { name: 'Project 2 · related record' }).click()
  await expect(page.locator('.commercial-project-chain-label')).toContainText('related project record')
  await page.getByRole('button', { name: 'Project 1 · primary record' }).click()
  await expect(page.locator('.commercial-timeline')).toContainText('Under construction')
  await expect(page.locator('.commercial-timeline')).toContainText('2026-09-28')
  await expect(page.locator('.commercial-timeline')).toContainText('superseded source state')
  await expect(page.locator('.commercial-history-note')).toContainText('do not establish a verified power start window')
  await expect(page.locator('.commercial-timeline a').first()).toHaveAttribute('href', 'https://example.test/timeline')
  const question = 'What is the electrical load and energization window for this construction phase?'
  await page.getByLabel('Exact missing-fact question').fill(question)
  await page.locator('.commercial-list .commercial-card-heading').click()
  await page.locator('.commercial-list .commercial-card-heading').click()
  await expect(page.getByLabel('Exact missing-fact question')).toHaveValue(question)
  await page.locator('.commercial-filters button').nth(1).click()
  await expect(page.locator('.commercial-list .commercial-card-heading')).toContainText('South Ridge Works')
  await page.locator('.commercial-filters button').first().click()
  await page.getByRole('button', { name: 'Signals', exact: true }).click()
  await page.goBack()
  await expect(page.getByLabel('Exact missing-fact question')).toHaveValue(question)
  await page.getByRole('button', { name: 'Research this question' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Research result' })).toBeVisible()
  await expect(page.locator('.commercial-research-result')).toContainText('Source review confirms the filing stage.')
  await expect(page.locator('.commercial-research-result a').first()).toHaveAttribute('href', 'https://example.test/fact')
  expect(captured.receivedQuestion).toBe(question)
  expect(captured.statusQuestion).toBe(question)
  expect(captured.statusCalls).toBeGreaterThanOrEqual(2)
  expect(captured.researchCalls).toBe(1)
  const noteText = 'Operator reported a follow-up is needed.'
  await page.locator('.commercial-action textarea').nth(1).fill(noteText)
  await page.getByLabel('Reported outcome').selectOption('Reached buying organization')
  await page.locator('.commercial-list .commercial-card-heading').click()
  await page.locator('.commercial-list .commercial-card-heading').click()
  await expect(page.locator('.commercial-action textarea').nth(1)).toHaveValue(noteText)
  await page.getByLabel('Reported outcome').selectOption('Reached buying organization')
  await page.getByRole('button', { name: 'Save note' }).click()
  await expect(page.getByRole('status').filter({ hasText: '503' })).toBeVisible()
  await page.getByRole('button', { name: 'Save note' }).click()
  await expect(page.getByText('Note saved to this pursuit. Evidence tier unchanged.')).toBeVisible()
  expect(captured.savedNote?.note).toBe(noteText)
  expect(captured.noteIds).toHaveLength(2)
  expect(captured.noteIds[0]).toBe(captured.noteIds[1])
  await expect(page.locator('.commercial-note').filter({ hasText: noteText })).toHaveCount(1)
  await page.reload()
  const restoredCard = page.locator('.commercial-list .commercial-card-heading')
  if (await restoredCard.getAttribute('aria-expanded') !== 'true') await restoredCard.click()
  await expect(page.locator('.commercial-note').filter({ hasText: noteText })).toHaveCount(1)
  await page.locator('.commercial-filters button').nth(1).click()
  await expect(page.locator('.commercial-list .commercial-card')).toHaveCount(1)
  await expect(page.locator('.commercial-list .commercial-card-heading')).toContainText('South Ridge Works')
  await page.getByRole('button', { name: 'Signals', exact: true }).click()
  await page.goBack()
  await expect(page.locator('.commercial-filters button').nth(1)).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('.commercial-list .commercial-card-heading')).toContainText('South Ridge Works')
  await page.locator('.commercial-filters button').first().click()
  await expect(page.locator('.commercial-list .commercial-card-heading')).toContainText('Northstar Campus')
})

test('source health operations disclosure keeps readable contrast in the commercial workspace', async ({ page }) => {
  await useCommercialFixture(page)
  await page.route('**/api/health', (route) => route.fulfill({ json: { sources: [], backlog: 0, pending_interpretations: 0 } }))
  await page.route('**/api/ingestion?*', (route) => route.fulfill({ json: { items: [], total: 0, limit: 25, offset: 0 } }))
  await page.route('**/api/intelligence/operations', (route) => route.fulfill({ json: {
    sources: [],
    queue: { by_kind_status: {}, oldest_queued_at: null, retried_jobs_30d: 0, failed_after_three_attempts_30d: 0 },
    providers: {
      utc_day: { date: '2026-10-21', timezone: 'UTC', calls: 0, known_cost_usd: null, reserved_cost_usd: null, reserved_known_subtotal_usd: 0, unknown_cost_calls: 0, daily_budget_status: 'UNKNOWN', daily_budget_rows: [], daily_budget_limits_usd: { global: 0 }, daily_budget_limits_calls: { global: 0 } },
      configured: {}, enabled: {}, by_provider: [], reserved_cost_usd: null, reserved_known_subtotal_usd: 0, known_cost_usd: null, known_cost_calls: 0, unknown_cost_calls_all_time: 0, total_cost_status: 'UNKNOWN', detail_rows_30d: 0, detail_truncated: false, outstanding_uncertain_calls_all_time: 0, uncertain_calls: 0, accepted: null, accepted_reason: 'No measured calls.',
    },
    questions: { outcomes_30d: {} }, material_changes_30d: null, reviewed_signals: null, independent_leads: null, backup: 'UNKNOWN', restore: 'UNKNOWN', last_verified_restore_at: null, last_reported_restore_at: null, operational_receipt: {},
    commercial_review_receipt: { status: 'UNKNOWN', reported_case_count: null, decision_counts: null, reviewer: null, reviewed_at: null, sample_sha256: null, context_sha256: null, cases: [], independent_labels: 'UNKNOWN', quality_verification: 'UNKNOWN', acceptance: 'UNKNOWN' },
    owner_review_notes_30d: 0,
  } }))
  await page.goto('/?view=ingestion')

  const panel = page.locator('.wh-panel').filter({ has: page.getByRole('heading', { name: 'Source health' }) })
  await expect(panel.getByRole('heading', { name: 'Source health' })).toBeVisible()
  const operations = panel.locator('.intelligence-operations')
  await expect(operations.locator('summary')).toBeVisible()
  await expect(operations.locator('p').first()).toContainText('Read-only status for saved jobs')
  expect(await contrastRatio(operations.locator('summary'))).toBeGreaterThanOrEqual(4.5)
  expect(await contrastRatio(operations.locator('p').first())).toBeGreaterThanOrEqual(4.5)
  await operations.locator('summary').click()
  await expect(operations.getByText('No queue rows were found in the bounded window.', { exact: true })).toBeVisible()
  expect(await contrastRatio(operations.locator('summary'))).toBeGreaterThanOrEqual(4.5)
  expect(await contrastRatio(operations.locator('p').first())).toBeGreaterThanOrEqual(4.5)
})

test('commercial pages report all-group totals and preserve note drafts while traversing', async ({ page }) => {
  await useCommercialFixture(page)
  const firstPage: CommercialTriage = {
    ...base,
    total: 1,
    limit: 50,
    offset: 0,
    grouped_total: 51,
    next_offset: 50,
    cohort_counts: { action_now: 1, research: 0, watch: 0, reject: 0 },
    items: [base.items[0]],
  }
  const secondPage: CommercialTriage = {
    ...base,
    total: 1,
    limit: 50,
    offset: 50,
    grouped_total: 51,
    next_offset: null,
    cohort_counts: { action_now: 0, research: 1, watch: 0, reject: 0 },
    items: [base.items[1]],
  }
  await page.route(/\/api\/commercial\/triage\?/, (route) => {
    const offset = Number(new URL(route.request().url()).searchParams.get('offset') ?? 0)
    return route.fulfill({ json: offset ? secondPage : firstPage })
  })
  await page.goto('/?view=pursuits')
  await page.getByText('Queue details and research updates').click()
  await expect(page.getByText('All eligible groups').locator('..')).toContainText('51')
  await expect(page.getByText(/eligible groups overall/).first()).toContainText('51')
  await page.locator('.commercial-list .commercial-card-heading').first().click()
  const noteDraft = 'Keep this unsaved operator note across pages.'
  await page.locator('.commercial-action textarea').nth(1).fill(noteDraft)
  const pager = page.getByRole('navigation', { name: 'Commercial pursuit pages' })
  await pager.getByRole('button', { name: 'Next page' }).click()
  await expect(page.getByText(/Matching pursuits on this loaded page · 51 eligible groups overall/)).toBeVisible()
  await expect(page.getByRole('heading', { name: 'No action now pursuits' })).toBeVisible()
  await expect(page.locator('.pursuit-position')).toHaveCount(0)
  await page.getByRole('button', { name: /RESEARCH 1/ }).click()
  await expect(page.locator('.commercial-list .commercial-card-heading')).toContainText('South Ridge Works')
  await expect(page.locator('.pursuit-position')).toHaveText('51')
  await pager.getByRole('button', { name: 'Previous page' }).click()
  await expect(page.getByText(/Matching pursuits on this loaded page · 51 eligible groups overall/)).toBeVisible()
  await page.getByRole('button', { name: /ACTION NOW 1/ }).click()
  await expect(page.locator('.commercial-list .commercial-card-heading')).toContainText('Northstar Campus')
  await page.locator('.commercial-list .commercial-card-heading').first().click()
  await expect(page.locator('.commercial-action textarea').nth(1)).toHaveValue(noteDraft)
})

test('commercial targeted research reports unavailable response', async ({ page }) => {
  const captured = await useCommercialFixture(page, 503)
  await page.locator('.commercial-list .commercial-card-heading').click()
  await page.getByRole('button', { name: 'Research this question' }).click()
  await expect(page.getByRole('alert').filter({ hasText: '503' })).toBeVisible()
  expect(captured.receivedQuestion).toContain('energization window')
})

test('targeted research polling resumes after detail collapse without posting the question again', async ({ page }) => {
  const captured = await useCommercialFixture(page)
  await page.locator('.commercial-list .commercial-card-heading').click()
  await page.getByRole('button', { name: 'Research this question' }).click()
  await expect.poll(() => captured.statusCalls).toBeGreaterThan(0)
  await page.locator('.commercial-list .commercial-card-heading').click()
  const callsAtCollapse = captured.statusCalls
  await page.waitForTimeout(1750)
  expect(captured.statusCalls).toBe(callsAtCollapse)
  await page.locator('.commercial-list .commercial-card-heading').click()
  await expect(page.locator('.commercial-research-result')).toContainText('Source review confirms the filing stage.')
  expect(captured.researchCalls).toBe(1)
  expect(captured.statusQuestion).toContain('energization window')
})

test('explicit Signals entry does not request or mount hidden commercial triage', async ({ page }) => {
  let triageRequests = 0
  await page.route('**/api/auth/session', (route) => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/health', (route) => route.fulfill({ json: { sources: [], backlog: 0, pending_interpretations: 0 } }))
  await page.route('**/api/changes', (route) => route.fulfill({ json: [] }))
  await page.route(/\/api\/opportunities\/map-window(?:\?|$)/, (route) => route.fulfill({ json: emptyMapWindow }))
  await page.route(/\/api\/opportunities\?/, (route) => route.fulfill({ json: [] }))
  await page.route('**/api/commercial/triage*', async (route) => {
    triageRequests += 1
    await route.fulfill({ json: [] })
  })
  await page.goto('/?tier=Signals')
  await expect(page.getByRole('heading', { name: 'Signals', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'All 0' })).toBeVisible()
  await page.waitForLoadState('networkidle')
  expect(triageRequests).toBe(0)
})

test('legacy environment reveals commercial preview on demand with an explicit full queue path', async ({ page }) => {
  await page.route('**/api/auth/session', (route) => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/health', (route) => route.fulfill({ json: { sources: [], backlog: 0, pending_interpretations: 0 } }))
  await page.route('**/api/changes', (route) => route.fulfill({ json: [] }))
  await page.route(/\/api\/opportunities\/map-window(?:\?|$)/, (route) => route.fulfill({ json: emptyMapWindow }))
  await page.route(/\/api\/opportunities\?/, (route) => route.fulfill({ json: [] }))
  await page.route('**/api/commercial/triage?limit=50', (route) => route.fulfill({ json: base }))
  let requests = 0
  page.on('request', request => { if (new URL(request.url()).pathname === '/api/commercial/triage') requests++ })
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: { items: [], total: 0, counts: { action_now: 0, research: 0, watch: 0, reject: 0 }, offset: 0, limit: 25, next_offset: null, cohort_token: 'test' } }))
  await page.goto('/environment')
  await page.waitForLoadState('networkidle')
  expect(requests).toBe(0)
  await page.getByRole('button', { name: 'Research', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'What should we work today?' })).toBeVisible()
  await expect(page.locator('.commercial-list')).toContainText('Northstar Campus')
  await page.locator('.commercial-list .commercial-card-heading').first().click()
  await expect(page.locator('.commercial-card-facts')).toContainText('Power Unknown')
  expect(requests).toBeGreaterThan(0)
})
test('legacy environment watch-only cohort is not described as empty or actionable', async ({ page }) => {
  const watchOnly = structuredClone(base)
  watchOnly.items = [{ ...watchOnly.items[0], disposition: 'WATCH', watch: { event: 'Utility service plan filing', date: '2026-11-01', source_url: 'https://example.test/watch' } }]
  watchOnly.total = 1
  watchOnly.cohort_counts = { action_now: 0, research: 0, watch: 1, reject: 0 }
  await page.route('**/api/auth/session', (route) => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/health', (route) => route.fulfill({ json: { sources: [], backlog: 0, pending_interpretations: 0 } }))
  await page.route('**/api/changes', (route) => route.fulfill({ json: [] }))
  await page.route(/\/api\/opportunities\/map-window(?:\?|$)/, (route) => route.fulfill({ json: emptyMapWindow }))
  await page.route(/\/api\/opportunities\?/, (route) => route.fulfill({ json: [] }))
  await page.route('**/api/commercial/triage?limit=50', (route) => route.fulfill({ json: watchOnly }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: { items: [], total: 0, counts: { action_now: 0, research: 0, watch: 0, reject: 0 }, offset: 0, limit: 25, next_offset: null, cohort_token: 'test' } }))
  await page.goto('/environment')
  await page.getByRole('button', { name: 'Research', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'No action now pursuits' })).toBeVisible()
  await page.getByRole('button', { name: /WATCH 1/ }).click()
  await expect(page.locator('.commercial-list')).toContainText('Northstar Campus')
  await page.locator('.commercial-list .commercial-card-heading').click()
  await expect(page.locator('.commercial-detail')).toContainText('Utility service plan filing')
})
test('legacy environment malformed commercial preview fails visibly without a false empty cohort', async ({ page }) => {
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  await page.route('**/api/auth/session', (route) => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/health', (route) => route.fulfill({ json: { sources: [], backlog: 0, pending_interpretations: 0 } }))
  await page.route('**/api/changes', (route) => route.fulfill({ json: [] }))
  await page.route(/\/api\/opportunities\/map-window(?:\?|$)/, (route) => route.fulfill({ json: emptyMapWindow }))
  await page.route(/\/api\/opportunities\?/, (route) => route.fulfill({ json: [] }))
  await page.route('**/api/commercial/triage?limit=50', (route) => route.fulfill({ json: {} }))
  await page.route('**/api/opportunities/workspace?*', route => route.fulfill({ json: { items: [], total: 0, counts: { action_now: 0, research: 0, watch: 0, reject: 0 }, offset: 0, limit: 25, next_offset: null, cohort_token: 'test' } }))
  await page.goto('/environment')
  await page.getByRole('button', { name: 'Research', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Commercial pursuits are unavailable' })).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('incomplete data')
  await expect(page.locator('.commercial-summary')).toHaveCount(0)
  await expect(page.locator('.commercial-filters')).toHaveCount(0)
  expect(pageErrors).toEqual([])
})
test('commercial queue stays behind sign-in until the authenticated session is established', async ({ page }) => {
  await page.route('**/api/auth/session', (route) => route.fulfill({ status: 401, json: { detail: 'Not authenticated' } }))
  await page.route('**/api/auth/login', (route) => route.fulfill({ json: { authenticated: true } }))
  await page.route('**/api/health', (route) => route.fulfill({ json: {} }))
  await page.route(/\/api\/opportunities\?/, (route) => route.fulfill({ json: [] }))
  await page.route('**/api/changes', (route) => route.fulfill({ json: [] }))
  await page.route(/\/api\/commercial\/triage\?limit=50$/, (route) => route.fulfill({ json: base }))
  await page.goto('/?view=pursuits')
  await expect(page.getByLabel('Password', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'What should we work today?' })).toHaveCount(0)
  await page.getByLabel('Password', { exact: true }).fill('test-session')
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByRole('heading', { name: 'What should we work today?' })).toBeVisible()
})

test('saved evaluation history keeps as-of card and notes searchable after cohort departure', async ({ page }) => {
  const captured = await useCommercialFixture(page)
  const current = structuredClone(base)
  current.items = [current.items[1]]
  current.total = 1
  current.cohort_counts = { action_now: 0, research: 1, watch: 0, reject: 0 }
  current.daily.evaluated = 1
  await page.route('**/api/commercial/triage?limit=50', (route) => route.fulfill({ json: current }))
  const recordedCard = { ...base.items[0], operator_fact_refs: [{ need_id: 'need-a', fact_version_id: 'fact-version-a', content_hash: 'f'.repeat(64), authority: 'User-confirmed' as const }] }
  const recordedEmptyCard = { ...base.items[0], id: 'need-empty', name: 'Empty saved facts', facts: [], sources: [], operator_fact_refs: [] }
  const historyItems = [
    { pursuit_id: 'pursuit-a', need_id: 'need-a', project_id: 'project-a', related_project_ids: ['project-a-related'], disposition: 'ACTION NOW', evaluated_at: '2026-10-02T14:00:00Z', evaluated_on: '2026-10-02', input_hash: 'persisted-hash-a', snapshot_status: 'saved_as_of', live_status: 'not_rechecked', saved_card: recordedCard, versions: [{ version: 1, disposition: 'ACTION NOW', evaluated_at: '2026-10-02T14:00:00Z', evaluated_on: '2026-10-02', input_hash: 'persisted-hash-a', operator_fact_provenance: 'recorded', snapshot_status: 'saved_as_of', live_status: 'not_rechecked', saved_card: recordedCard }], notes: [{ id: 'saved-note-a', client_id: 'client-a', owner: 'Operator', created_at: '2026-10-02T14:10:00Z', note: 'Persisted operator note after displacement.', outcome: 'Reached buying organization', next_action: 'Confirm the project load.', follow_up: null }] },
    { pursuit_id: 'pursuit-empty', need_id: 'need-empty', project_id: 'project-a', disposition: 'RESEARCH', evaluated_at: '2026-10-02T15:00:00Z', evaluated_on: '2026-10-02', input_hash: 'persisted-empty-a', snapshot_status: 'saved_as_of', live_status: 'not_rechecked', saved_card: recordedEmptyCard, versions: [{ version: 1, disposition: 'RESEARCH', evaluated_at: '2026-10-02T15:00:00Z', evaluated_on: '2026-10-02', input_hash: 'persisted-empty-a', operator_fact_provenance: 'recorded', snapshot_status: 'saved_as_of', live_status: 'not_rechecked', saved_card: recordedEmptyCard }], notes: [] },
    { pursuit_id: 'pursuit-old', need_id: 'need-old', project_id: 'project-old', disposition: 'REJECT', evaluated_at: null, evaluated_on: null, input_hash: null, snapshot_status: 'metadata_only', live_status: 'not_rechecked', saved_card: null, notes: [] },
  ]
  await page.route('**/api/commercial/triage/history', (route) => route.fulfill({ json: { items: historyItems, total: 2, limit: 50, offset: 0, next_offset: null } }))
  await page.route('**/api/commercial/triage/history/*', (route) => {
    const pursuitId = new URL(route.request().url()).pathname.split('/').at(-1)
    const item = historyItems.find((candidate) => candidate.pursuit_id === pursuitId)
    return route.fulfill(item ? { json: item } : { status: 404, json: { detail: 'Not found' } })
  })
  const researchReads: string[] = []
  await page.route(/\/api\/commercial\/triage\/[^/]+\/autonomous-research/, (route) => {
    const needId = new URL(route.request().url()).pathname.split('/').at(-2) ?? ''
    researchReads.push(needId)
    if (needId === 'need-old' && researchReads.filter((value) => value === needId).length === 1) {
      return route.fulfill({ status: 503, json: { detail: 'Retained research history is temporarily unavailable.' } })
    }
    return route.fulfill({ json: { items: [] } })
  })
  const currentFactReads: string[] = []
  await page.route(/\/api\/needs\/[^/]+\/facts/, (route) => {
    currentFactReads.push(new URL(route.request().url()).pathname)
    return route.fulfill({ json: { items: [], total: 0, limit: 50, offset: 0, next_offset: null, current_fact_version: 0 } })
  })
  await page.goto('/?view=pursuits')
  await page.locator('.commercial-filters button').nth(1).click()
  await expect(page.locator('.commercial-list .commercial-card-heading')).toContainText('South Ridge Works')
  await expect(page.locator('.commercial-list .commercial-card-heading')).not.toContainText('Northstar Campus')
  const history = page.locator('details.commercial-history')
  await history.locator('summary').click()
  await expect(history.getByRole('button', { name: /Northstar Campus/ })).toBeVisible()
  await history.getByLabel('Search saved evaluations').fill('Persisted operator note')
  await expect(history.getByRole('button', { name: /Northstar Campus/ })).toBeVisible()
  await history.getByRole('button', { name: /Northstar Campus/ }).click()
  await expect(history.locator('.commercial-history-asof')).toContainText('Saved version 1: ACTION NOW')
  await expect(history.locator('.commercial-history-asof')).toContainText('current status not rechecked')
  await expect(history.locator('.commercial-history-detail')).toContainText('User-confirmed fact references saved with this evaluation')
  await expect(history.locator('.commercial-history-detail')).toContainText('content reference ffffffffffff')
  await expect(history.locator('.commercial-history-detail')).toContainText('Construction filing accepted.')
  await expect(history.locator('.commercial-history-detail')).toContainText('Required power: Unknown')
  await expect(history.locator('.commercial-history-detail .commercial-note')).toContainText('Persisted operator note after displacement.')
  expect(researchReads).toEqual([])
  expect(captured.evaluationCalls).toBe(0)
  expect(currentFactReads).toEqual([])
  await history.getByRole('button', { name: 'Inspect later research attempts' }).click()
  await expect(history.getByText(/Research attempt history loaded now/)).toBeVisible()
  expect(researchReads).toEqual(['need-a'])
  await history.getByLabel('Search saved evaluations').fill('need-old')
  await expect(history.getByRole('button', { name: /Saved work · need-old/ })).toBeVisible()
  await history.getByRole('button', { name: /Saved work · need-old/ }).click()
  await expect(history.locator('.commercial-history-detail')).toContainText('Only its saved disposition and operator notes are available; facts are not reconstructed.')
  await expect(history.locator('.commercial-history-detail')).toContainText('Saved version 1: REJECT')
  await expect(history.locator('.commercial-history-detail')).not.toContainText('Construction filing accepted.')
  await expect(history.locator('.commercial-history-detail')).toContainText('Unknown · this legacy evaluation did not record its operator fact basis.')
  await expect(history.getByRole('region', { name: 'Autonomous pursuit research' })).toHaveCount(0)
  await history.getByRole('button', { name: 'Inspect later research attempts' }).click()
  await expect(history.locator('.commercial-history-detail')).toContainText('Later research attempt history is unavailable; status is UNKNOWN.')
  expect(researchReads).toEqual(['need-a', 'need-old'])
  await history.getByRole('button', { name: /Saved work · need-old/ }).click()
  await history.getByRole('button', { name: /Saved work · need-old/ }).click()
  await history.getByRole('button', { name: 'Inspect later research attempts' }).click()
  await expect(history.locator('.commercial-history-detail')).toContainText('No autonomous research questions recorded.')
  expect(researchReads).toEqual(['need-a', 'need-old', 'need-old'])
  await history.getByLabel('Search saved evaluations').fill('Empty saved facts')
  await expect(history.getByRole('button', { name: /Empty saved facts/ })).toBeVisible()
  await history.getByRole('button', { name: /Empty saved facts/ }).click()
  await expect(history.locator('.commercial-history-detail')).toContainText('Recorded empty · no accepted operator facts were included in this evaluation.')
  await expect(history.locator('.commercial-history-detail')).toContainText('Recorded empty · this saved evaluation contains no supported source facts.')
  expect(currentFactReads).toEqual([])
})

test('saved evaluation history traverses more than one bounded page', async ({ page }) => {
  await useCommercialFixture(page)
  const historyItem = (pursuitId: string, needId: string) => ({
    pursuit_id: pursuitId,
    need_id: needId,
    project_id: `project-${needId}`,
    disposition: 'REJECT',
    evaluated_at: null,
    evaluated_on: null,
    input_hash: null,
    snapshot_status: 'metadata_only' as const,
    live_status: 'not_rechecked' as const,
    saved_card: null,
    notes: [],
  })
  await page.route((url) => url.pathname === '/api/commercial/triage/history', (route) => {
    const offset = Number(new URL(route.request().url()).searchParams.get('offset') ?? 0)
    return route.fulfill({ json: {
      items: [offset ? historyItem('pursuit-last', 'historic-last') : historyItem('pursuit-first', 'historic-first')],
      total: 51,
      limit: 50,
      offset,
      next_offset: offset ? null : 50,
    } })
  })
  await page.goto('/?view=pursuits')
  const history = page.locator('details.commercial-history')
  await history.locator('summary').click()
  await expect(history).toContainText('Showing 1–1 of 51 saved workspaces')
  await expect(history.getByRole('button', { name: /Saved work · historic/ })).toBeVisible()
  await history.getByRole('navigation', { name: 'Saved evaluation history pages' }).getByRole('button', { name: 'Next page' }).click()
  await expect(history).toContainText('Showing 51–51 of 51 saved workspaces')
  await expect(history.getByRole('button', { name: /Saved work · historic/ })).toBeVisible()
})

test('prior saved versions remain visible when the need is still in the current cohort', async ({ page }) => {
  await useCommercialFixture(page)
  const card = structuredClone(base.items[0])
  const olderCard = { ...card, reason: 'Earlier evidence cited an announced project stage.' }
  const historyItem = {
    pursuit_id: 'pursuit-a', need_id: 'need-a', project_id: 'project-a', disposition: 'ACTION NOW', evaluated_at: '2026-10-03T14:00:00Z', evaluated_on: '2026-10-03', input_hash: 'hash-new', snapshot_status: 'saved_as_of', live_status: 'not_rechecked', saved_card: card, notes: [], versions: [
      { version: 1, disposition: 'RESEARCH', evaluated_at: '2026-10-02T14:00:00Z', evaluated_on: '2026-10-02', input_hash: 'hash-older', snapshot_status: 'saved_as_of', live_status: 'not_rechecked', saved_card: olderCard },
      { version: 2, disposition: 'ACTION NOW', evaluated_at: '2026-10-03T14:00:00Z', evaluated_on: '2026-10-03', input_hash: 'hash-new', snapshot_status: 'saved_as_of', live_status: 'not_rechecked', saved_card: card },
    ],
  }
  await page.route('**/api/commercial/triage/history', (route) => route.fulfill({ json: { items: [historyItem], total: 1, limit: 50, offset: 0, next_offset: null } }))
  await page.route('**/api/commercial/triage/history/*', (route) => route.fulfill({ json: historyItem }))
  await page.locator('.commercial-list .commercial-card-heading').waitFor()
  const history = page.locator('details.commercial-history')
  await history.locator('summary').click()
  await history.getByLabel('Search saved evaluations').fill('hash-older')
  const previous = history.getByRole('button', { name: /Version 1 · RESEARCH/ })
  await expect(previous).toBeVisible()
  await expect(history.getByRole('button', { name: /Version 2 · ACTION NOW/ })).toHaveCount(0)
  await previous.click()
  await expect(history.locator('.commercial-history-asof')).toContainText('Saved version 1: RESEARCH')
  await expect(history.locator('.commercial-history-detail')).toContainText('Earlier evidence cited an announced project stage.')
})
