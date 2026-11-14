import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'

const apiPort = process.env.GRIDLENS_API_PORT ?? '8000'
const appVersion = process.env.VITE_APP_VERSION || JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')).version
const explicitGitSha = process.env.VITE_GIT_SHA
const gitSha = explicitGitSha || (() => { try { return execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim() } catch { return '' } })()
const sourceDirty = (() => { try { return execFileSync('git', ['status', '--porcelain'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim().length > 0 } catch { return null } })()

export default defineConfig({
  plugins: [react()],
  define: {
    'import.meta.env.VITE_DEPLOYMENT_ENVIRONMENT': JSON.stringify(process.env.VITE_DEPLOYMENT_ENVIRONMENT || 'Local build'),
    'import.meta.env.VITE_APP_VERSION': JSON.stringify(appVersion),
    // An explicit image-build revision is authoritative. Preserve the dirty
    // suffix only for local fallback builds where Vite discovers Git itself.
    'import.meta.env.VITE_GIT_SHA': JSON.stringify(gitSha ? `${gitSha}${sourceDirty === true || (!explicitGitSha && sourceDirty === null) ? '-dirty' : ''}` : ''),
    'import.meta.env.VITE_DEPLOYED_AT': JSON.stringify(process.env.VITE_DEPLOYED_AT || ''),
  },
  server: { proxy: { '/api': `http://127.0.0.1:${apiPort}` } },
})
