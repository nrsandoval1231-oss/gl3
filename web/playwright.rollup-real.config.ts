import { defineConfig } from '@playwright/test'

// This lane only targets a caller-started disposable stack. Requiring an
// explicit switch and loopback URL keeps it out of the ordinary 184-test run.
if (process.env.CUSTOMER_ROLLUP_REAL !== '1') {
  throw new Error('Set CUSTOMER_ROLLUP_REAL=1 to opt into the isolated real-backend customer-rollup lane.')
}

const origin = process.env.CUSTOMER_ROLLUP_REAL_WEB_ORIGIN
if (!origin) throw new Error('Set CUSTOMER_ROLLUP_REAL_WEB_ORIGIN to the loopback web origin for the disposable stack.')
const parsedOrigin = new URL(origin)
if (!['127.0.0.1', 'localhost', '[::1]'].includes(parsedOrigin.hostname)) {
  throw new Error('CUSTOMER_ROLLUP_REAL_WEB_ORIGIN must use a loopback host.')
}
const startStack = process.env.CUSTOMER_ROLLUP_REAL_START_STACK === '1'
const apiPort = Number(process.env.GRIDLENS_API_PORT ?? '18191')
const webPort = Number(parsedOrigin.port)
if (startStack && (!Number.isInteger(apiPort) || apiPort < 1 || apiPort > 65535 || !Number.isInteger(webPort) || webPort < 1 || webPort > 65535)) {
  throw new Error('Stack startup requires valid explicit loopback API and web ports.')
}
const webServer = startStack ? [
  {
    command: `uv run --offline uvicorn gridlens.api.app:app --host 127.0.0.1 --port ${apiPort} --no-proxy-headers`,
    cwd: '../backend',
    port: apiPort,
    reuseExistingServer: false,
    timeout: 30_000,
  },
  {
    command: `npm run dev -- --host 127.0.0.1 --port ${webPort}`,
    port: webPort,
    reuseExistingServer: false,
    timeout: 30_000,
  },
] : undefined

export default defineConfig({
  testDir: './acceptance/rollup-scale',
  testMatch: '**/customer-rollup-real.spec.ts',
  workers: 1,
  retries: 0,
  maxFailures: 1,
  reporter: 'list',
  timeout: 180_000,
  expect: { timeout: Number(process.env.CUSTOMER_ROLLUP_UI_READY_MS ?? 15_000) },
  ...(webServer ? { webServer } : {}),
  use: {
    baseURL: origin,
    viewport: { width: 1440, height: 900 },
    locale: 'en-US',
    timezoneId: 'UTC',
    actionTimeout: Number(process.env.CUSTOMER_ROLLUP_UI_READY_MS ?? 15_000),
    navigationTimeout: Number(process.env.CUSTOMER_ROLLUP_UI_READY_MS ?? 15_000),
    trace: 'retain-on-failure',
  },
})
