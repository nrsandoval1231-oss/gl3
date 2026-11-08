import { defineConfig } from '@playwright/test'

const apiPort = process.env.GRIDLENS_API_PORT ?? '8152'
const webPort = process.env.GRIDLENS_WEB_PORT ?? '5179'

export default defineConfig({
  testDir: './tests',
  testMatch: '**/phase2_commercial_brief.spec.ts',
  forbidOnly: true,
  workers: 1,
  reporter: 'list',
  timeout: 90_000,
  use: {
    baseURL: `http://127.0.0.1:${webPort}`,
    viewport: { width: 1280, height: 800 },
    locale: 'en-US',
    timezoneId: 'UTC',
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: `uv run uvicorn gridlens.api.app:app --host 127.0.0.1 --port ${apiPort} --no-proxy-headers`,
      cwd: '../backend',
      port: Number(apiPort),
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${webPort}`,
      port: Number(webPort),
      reuseExistingServer: false,
      timeout: 60_000,
      env: { ...process.env, GRIDLENS_API_PORT: apiPort, GRIDLENS_WEB_PORT: webPort },
    },
  ],
})
