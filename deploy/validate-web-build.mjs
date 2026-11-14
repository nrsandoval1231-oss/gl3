import { readdir, readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'

const productionShaPattern = /^[0-9a-fA-F]{40}$/

function repositoryState(cwd) {
  try {
    const head = execFileSync('git', ['rev-parse', 'HEAD'], { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim()
    const dirty = execFileSync('git', ['status', '--porcelain'], { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim().length > 0
    return { head, dirty }
  } catch {
    return null
  }
}

export async function validate({ phase = 'pre', environment, sha, dist = '/app/dist', cwd = process.cwd() } = {}) {
  if (phase !== 'pre' && phase !== 'post') throw new Error(`Unknown validation phase: ${phase}`)
  if (environment === 'local' || environment === 'development' || environment === 'test' || environment === 'ci') return
  if (environment !== 'production') {
    throw new Error('Set GRIDLENS_DEPLOYMENT_ENVIRONMENT to local, development, test, ci, or production.')
  }
  if (!productionShaPattern.test(sha ?? '')) {
    throw new Error('Production web builds require a 40-character hexadecimal GRIDLENS_BUILD_SHA.')
  }
  if (phase === 'pre') {
    const repository = repositoryState(cwd)
    if (repository?.dirty) throw new Error('Production web builds require a clean Git worktree.')
    if (repository && repository.head.toLowerCase() !== sha.toLowerCase()) {
      throw new Error('Production web build SHA does not match Git HEAD.')
    }
  }
  if (phase === 'pre') return

  const assetsDir = join(dist, 'assets')
  const assets = await readdir(assetsDir, { withFileTypes: true }).catch(() => [])
  const javascript = assets.filter(entry => entry.isFile() && entry.name.endsWith('.js'))
  for (const asset of javascript) {
    const content = await readFile(join(assetsDir, asset.name), 'utf8')
    if (content.includes(JSON.stringify(sha))) return
  }
  throw new Error(`Compiled JavaScript in ${assetsDir} does not contain the explicit build SHA.`)
}

async function main() {
  const [phase = 'pre', dist = '/app/dist'] = process.argv.slice(2)
  await validate({
    phase,
    environment: process.env.VITE_DEPLOYMENT_ENVIRONMENT,
    sha: process.env.VITE_GIT_SHA,
    dist,
  })
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  main().catch(error => {
    process.stderr.write(`${error.message}\n`)
    process.exitCode = 1
  })
}
