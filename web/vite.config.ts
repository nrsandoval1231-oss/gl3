import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'

const apiPort = process.env.GRIDLENS_API_PORT ?? '8000'
const appVersion = process.env.VITE_APP_VERSION || JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')).version
const gitSha = process.env.VITE_GIT_SHA || (() => { try { return execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim() } catch { return '' } })()
const sourceDirty = (() => { try { return execFileSync('git', ['status', '--porcelain'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim().length > 0 } catch { return true } })()

export default defineConfig({
  plugins: [react()],
  define: {
    'import.meta.env.VITE_DEPLOYMENT_ENVIRONMENT': JSON.stringify(process.env.VITE_DEPLOYMENT_ENVIRONMENT || 'Local build'),
    'import.meta.env.VITE_APP_VERSION': JSON.stringify(appVersion),
    'import.meta.env.VITE_GIT_SHA': JSON.stringify(gitSha ? `${gitSha}${sourceDirty ? '-dirty' : ''}` : ''),
    'import.meta.env.VITE_DEPLOYED_AT': JSON.stringify(process.env.VITE_DEPLOYED_AT || ''),
  },
  server: { proxy: { '/api': `http://127.0.0.1:${apiPort}` } },
})
