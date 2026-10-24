import { defineConfig } from '@playwright/test'
process.env.GRIDLENS_WEB_PORT = '5175'
// Mocked API regression suite: never starts providers or writes production records.
export default defineConfig({
  testDir: './tests',
  testIgnore: ['**/first_path.spec.ts', '**/pursuits.spec.ts', '**/auth.spec.ts'],
  workers: 2,
  reporter: 'list',
  use: { launchOptions: { executablePath: process.env.GRIDLENS_BROWSER_PATH ?? '/usr/bin/chromium', args: ['--no-sandbox'] }, baseURL: 'http://127.0.0.1:5175', viewport: { width: 1280, height: 900 } },
  webServer: { command: 'npm run dev -- --host 127.0.0.1 --port 5175', port: 5175, reuseExistingServer: false },
})
