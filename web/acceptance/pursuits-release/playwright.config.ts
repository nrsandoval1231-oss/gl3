import { defineConfig } from '@playwright/test'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const configDir = fileURLToPath(new URL('.', import.meta.url))

if (process.env.PURSUITS_RELEASE_REAL !== '1') {
  throw new Error('Set PURSUITS_RELEASE_REAL=1 to opt into the isolated real-backend pursuits lane.')
}
const origin = process.env.PURSUITS_RELEASE_WEB_ORIGIN
if (!origin) throw new Error('Set PURSUITS_RELEASE_WEB_ORIGIN to the disposable loopback web origin.')
const parsedOrigin = new URL(origin)
if (!['127.0.0.1', 'localhost', '[::1]'].includes(parsedOrigin.hostname)) {
  throw new Error('PURSUITS_RELEASE_WEB_ORIGIN must use loopback.')
}
const outputDir = process.env.PURSUITS_RELEASE_REAL_OUTPUT_DIR
if (!outputDir) throw new Error('Set PURSUITS_RELEASE_REAL_OUTPUT_DIR to a private artifact directory.')
const startStack = process.env.PURSUITS_RELEASE_REAL_START_STACK === '1'
if (!startStack && process.env.PURSUITS_RELEASE_REAL_START_STACK !== '0') {
  throw new Error('Set PURSUITS_RELEASE_REAL_START_STACK to 1 or use a caller-started loopback stack.')
}
const apiPort = Number(process.env.GRIDLENS_API_PORT ?? '18191')
const webPort = Number(parsedOrigin.port)
if (![apiPort, webPort].every(port => Number.isInteger(port) && port > 0 && port < 65536)) {
  throw new Error('The isolated lane requires explicit valid loopback ports.')
}

const webServer = startStack
  ? [
      {
        command: `uv run --offline uvicorn gridlens.api.app:app --host 127.0.0.1 --port ${apiPort} --no-proxy-headers`,
        cwd: resolve(configDir, '../../../backend'),
        port: apiPort,
        reuseExistingServer: false,
        timeout: 30_000,
      },
      {
        command: `npm run dev -- --host 127.0.0.1 --port ${webPort}`,
        cwd: resolve(configDir, '../..'),
        port: webPort,
        reuseExistingServer: false,
        timeout: 30_000,
      },
    ]
  : undefined

export default defineConfig({
  outputDir: resolve(outputDir),
  testDir: '.',
  testMatch: 'pursuits-real.spec.ts',
  workers: 1,
  retries: 0,
  maxFailures: 1,
  reporter: 'list',
  timeout: 180_000,
  expect: { timeout: 15_000 },
  ...(webServer ? { webServer } : {}),
  use: {
    baseURL: origin,
    viewport: { width: 1440, height: 900 },
    locale: 'en-US',
    timezoneId: 'UTC',
    trace: 'retain-on-failure',
  },
})
