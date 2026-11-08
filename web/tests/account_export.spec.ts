import { test, expect } from '@playwright/test'

test('synthetic export preserves demand scope, actions, permitted contacts and CSV safety', async ({ page }) => {
  await page.goto('/')
  const csv = await page.evaluate(async () => {
    // @ts-expect-error Vite serves the source module to the actual browser.
    const { projectPageCsv } = await import('/src/features/workspace/opportunityExport.ts')
    return projectPageCsv([{ name: '=Synthetic Campus', company: 'Synthetic Owner', location: 'TX', power_summary: '12 MW source-reported activity requirement', power_summary_kind: 'activity_requirement', power_amount_class: 'documented', event: { date: '2026-11-07', label: 'Construction planned' }, shortlist_assessment: { why_now: 'New electrical buildout', next_step: 'Confirm commissioning date', scope: 'construction activity' }, next_action: null, contact: [{ href: 'mailto:business@example.invalid', label: 'Email' }, { href: 'javascript:alert(1)', label: 'Unsafe' }] }])
  })
  expect(csv).toContain('12 MW source-reported activity requirement')
  expect(csv).toContain('activity_requirement')
  expect(csv).toContain('documented')
  expect(csv).toContain('Power statement basis')
  expect(csv).toContain('construction activity')
  expect(csv).toContain('New electrical buildout')
  expect(csv).toContain('Confirm commissioning date')
  expect(csv).toContain('business@example.invalid')
  expect(csv).not.toContain('javascript:')
  expect(csv).toContain("'=Synthetic Campus")
  expect(csv).toContain('Current page')
})
