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
            : []
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/?tier=Signals')
  await expect(page.getByText(/Status review needed: a retained filing/)).toBeVisible()
  await expect(page.getByText(/outcome is unknown/)).toBeVisible()
})

test('a grouped card shows the review flag when any member left its listing', async ({ page }) => {
  const sibling = { ...absent, id: 'listed', name: 'Test filing', group_id: 'test-group', group_title: 'Test filing', group_total_filtered: 2, group_loaded_on_page: 2, group_complete_on_page: true, signal_evidence_state: 'active_evidence' } as unknown as Opportunity
  const absentMember = { ...absent, group_id: 'test-group', group_title: 'Test filing', group_total_filtered: 2, group_loaded_on_page: 2, group_complete_on_page: true } as unknown as Opportunity
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (!path.startsWith('/api/')) return route.continue()
    const body = path === '/api/auth/session' ? { authenticated: true }
      : path === '/api/opportunities' ? [sibling, absentMember]
        : path === '/api/health' ? { sources: [], backlog: 0, pending_interpretations: 0 }
          : []
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/?tier=Signals')
  await expect(page.getByText(/Status review needed: a retained filing/)).toBeVisible()
  await expect(page.getByText(/outcome is unknown/)).toBeVisible()
  await page.locator('[data-opportunity-id="listed"]').click()
  await expect(page.locator('.project-member[data-opportunity-id="absent"]')).toContainText("Status review needed: no longer in the source's current listing; outcome unknown.")
  await expect(page.locator('.project-member[data-opportunity-id="listed"]')).not.toContainText('Status review needed')
})
