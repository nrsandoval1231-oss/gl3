import { defineConfig } from '@playwright/test'

const webPort = process.env.GRIDLENS_LOGIN_WEB_PORT ?? '5174'

export default defineConfig({
  testDir: './tests',
  testMatch: '**/login.spec.ts',
  workers: 1,
  reporter: 'list',
  use: { baseURL: `http://127.0.0.1:${webPort}`, viewport: { width: 1280, height: 900 }, channel: 'chrome' },
  webServer: { command: `npm run dev -- --host 127.0.0.1 --port ${webPort}`, port: Number(webPort), reuseExistingServer: !process.env.CI },
})
