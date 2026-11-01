import type { Page } from '@playwright/test'

// Companion contract for tests that already replace authentication and browse data.
// Real-authentication and real-backend acceptance tests do not install this mock.
export async function mockDemandSummary(page: Page) {
  await page.route('**/api/opportunities/demand-summary?*', route => route.fulfill({ json: {
    availability: 'unavailable', counts_complete: false,
    sector: new URL(route.request().url()).searchParams.get('sector') ?? 'all',
    as_of: '2026-11-01T00:00:00Z',
    totals: { identified_records: 0, known_mw_records: 0, unknown_records: 0, conflicted_records: 0 },
    classes: { documented: { mw: null, record_count: 0 }, calculated: { mw: null, record_count: 0 }, estimated: { mw: null, record_count: 0 } },
    provenance: { contract: 'equipment-demand-v1', source_count: 0, latest_evidence_at: null },
    limitations: ['Synthetic browse fixture does not include equipment demand.'],
  } }))
}
