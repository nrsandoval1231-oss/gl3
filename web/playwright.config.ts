import { defineConfig } from '@playwright/test'

const apiPort = process.env.GRIDLENS_API_PORT ?? '8000'
const webPort = process.env.GRIDLENS_WEB_PORT ?? '5173'
const liveAcceptance = ['**/first_path.spec.ts']
const commercialRealCases = ['**/commercial_real_cases.spec.ts']

export default defineConfig({
  testDir: './tests',
  forbidOnly: !!process.env.CI,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI ? [['line'], ['html', { open: 'never' }]] : 'list',
  use: { baseURL: `http://127.0.0.1:${webPort}`, viewport: { width: 1280, height: 900 }, locale: 'en-US', timezoneId: 'UTC', trace: 'retain-on-failure' },
  projects: [
    { name: 'regression', testIgnore: [...liveAcceptance, ...commercialRealCases] },
    // These checks require retained real-source records and an active worker.
    { name: 'live-acceptance', testMatch: liveAcceptance },
    // Read-only checks for persisted source-backed commercial case manifests.
    { name: 'commercial-real', testMatch: commercialRealCases },
  ],
  webServer: [
    { command: `uv run uvicorn gridlens.api.app:app --host 127.0.0.1 --port ${apiPort} --no-proxy-headers`, cwd: '../backend', port: Number(apiPort), reuseExistingServer: !process.env.CI },
    { command: `npm run dev -- --host 127.0.0.1 --port ${webPort}`, port: Number(webPort), reuseExistingServer: !process.env.CI },
  ],
})
