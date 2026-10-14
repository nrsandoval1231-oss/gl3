import { expect, test } from '@playwright/test'
import type { Opportunity } from '../src/api/client'

// Test-only fixture: one record whose filing left its source's current listing.
const absent = {
  id: 'absent', project_id: 'absent', name: 'Test filing', location: 'Atlanta, Georgia', tier: 'Signal',
  workflow_status: 'UNKNOWN', activity: 'facility-expansion', rationale: 'Test rationale.',
  brief_status: 'unavailable', brief_stale: false, required_mw: null, start_window: null, duration: null,
  supply: 'Unknown', next_action: 'Status review: this filing is no longer in the source\'s current listing.',
  conflict_state: 'Not assessed', signal_display_decision: 'SHOW', signal_display_decision_state: 'adjudicated',
  signal_evidence_state: 'source_listing_absent', evidence: [],
} as unknown as Opportunity

test('a filing that left its source listing is flagged for status review, not hidden', async ({ page }) => {
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (!path.startsWith('/api/')) return route.continue()
    const body = path === '/api/auth/session' ? { authenticated: true }
      : path === '/api/opportunities' ? [absent]
        : path === '/api/health' ? { sources: [], backlog: 0, pending_interpretations: 0 }
          : path.endsWith('/workflow-status') ? { status: 'UNKNOWN', version: 0, events: [] }
            : []
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/?tier=Signals')
  await expect(page.getByText('Signal · status review: no longer listed')).toBeVisible()
})

test('a grouped card shows the review flag when any member left its listing', async ({ page }) => {
  const sibling = { ...absent, id: 'listed', name: 'Test filing', signal_evidence_state: 'active_evidence' } as unknown as Opportunity
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (!path.startsWith('/api/')) return route.continue()
    const body = path === '/api/auth/session' ? { authenticated: true }
      : path === '/api/opportunities' ? [sibling, absent]
        : path === '/api/health' ? { sources: [], backlog: 0, pending_interpretations: 0 }
          : []
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/?tier=Signals')
  await expect(page.getByText('Signal · status review: no longer listed')).toBeVisible()
})
