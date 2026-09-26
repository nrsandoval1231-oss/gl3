import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  use: { baseURL: 'http://127.0.0.1:5173', viewport: { width: 1280, height: 900 } },
  webServer: [
    { command: 'uv run uvicorn gridlens.api.app:app --app-dir src --host 127.0.0.1 --port 8000', cwd: '../backend', port: 8000, reuseExistingServer: !process.env.CI },
    { command: 'npm run dev -- --host 127.0.0.1', port: 5173, reuseExistingServer: !process.env.CI },
  ],
})
