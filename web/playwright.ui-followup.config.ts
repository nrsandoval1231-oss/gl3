import { defineConfig } from '@playwright/test'

const webPort = process.env.GRIDLENS_UI_FOLLOWUP_PORT ?? '15443'

export default defineConfig({
  testDir: './tests',
  testMatch: [
    '**/customer_commercial_acceptance.spec.ts',
    '**/customer_intelligence.spec.ts',
    '**/project_results.spec.ts',
    '**/customer-accounts.spec.ts',
  ],
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: `http://127.0.0.1:${webPort}`,
    viewport: { width: 1280, height: 900 },
    locale: 'en-US',
    timezoneId: 'UTC',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: `npm run dev -- --host 127.0.0.1 --port ${webPort} --strictPort`,
    port: Number(webPort),
    reuseExistingServer: !process.env.CI,
  },
})
