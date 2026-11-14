import assert from 'node:assert/strict'
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { execFileSync } from 'node:child_process'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'
import { validate } from './validate-web-build.mjs'

const sha = 'a'.repeat(40)

test('local builds keep the npm and Compose development fallback', async () => {
  await validate({ environment: 'local' })
  await validate({ environment: 'ci' })
})

test('production preflight requires an explicit environment and full revision', async () => {
  await assert.rejects(validate({ environment: undefined, sha }), /Set GRIDLENS_DEPLOYMENT_ENVIRONMENT/)
  await assert.rejects(validate({ environment: 'production', sha: '' }), /40-character hexadecimal/)
  await assert.rejects(validate({ environment: 'production', sha: 'z'.repeat(40) }), /40-character hexadecimal/)
  await assert.rejects(validate({ environment: 'production', sha: 'a'.repeat(39) }), /40-character hexadecimal/)
  const repo = await mkdtemp(join(tmpdir(), 'gl3-web-build-git-'))
  try {
    execFileSync('git', ['init', '-q'], { cwd: repo })
    execFileSync('git', ['config', 'user.email', 'test@example.invalid'], { cwd: repo })
    execFileSync('git', ['config', 'user.name', 'UI build identity test'], { cwd: repo })
    await writeFile(join(repo, 'tracked.txt'), 'clean tree')
    execFileSync('git', ['add', 'tracked.txt'], { cwd: repo })
    execFileSync('git', ['commit', '-q', '-m', 'fixture'], { cwd: repo })
    const head = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repo, encoding: 'utf8' }).trim()
    await validate({ environment: 'production', sha: head, cwd: repo })
    await assert.rejects(validate({ environment: 'production', sha, cwd: repo }), /does not match Git HEAD/)
    await writeFile(join(repo, 'tracked.txt'), 'dirty tree')
    await assert.rejects(validate({ environment: 'production', sha: head, cwd: repo }), /clean Git worktree/)
  } finally {
    await rm(repo, { recursive: true, force: true })
  }
  // A Docker build context without .git trusts the explicitly declared SHA as
  // metadata; the postflight still checks the compiled artifact contains it.
  const noGit = await mkdtemp(join(tmpdir(), 'gl3-web-build-nogit-'))
  try {
    await assert.rejects(validate({ environment: 'production', sha: '', cwd: noGit }), /40-character hexadecimal/)
    await validate({ environment: 'production', sha, cwd: noGit })
  } finally {
    await rm(noGit, { recursive: true, force: true })
  }
})

test('production postflight accepts only a compiled JavaScript asset with the explicit revision', async () => {
  const root = await mkdtemp(join(tmpdir(), 'gl3-web-build-identity-'))
  const assets = join(root, 'dist', 'assets')
  try {
    await mkdir(assets, { recursive: true })
    await writeFile(join(assets, 'index.js'), `const build = "${sha}";`)
    await validate({ phase: 'post', environment: 'production', sha, dist: join(root, 'dist') })
    await writeFile(join(assets, 'index.js'), `const build = "${sha}-dirty";`)
    await assert.rejects(
      validate({ phase: 'post', environment: 'production', sha, dist: join(root, 'dist') }),
      /does not contain the explicit build SHA/,
    )
    await writeFile(join(assets, 'index.js'), 'const build = "another-revision";')
    await assert.rejects(
      validate({ phase: 'post', environment: 'production', sha, dist: join(root, 'dist') }),
      /does not contain the explicit build SHA/,
    )
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})

test('Docker and Compose wire identity through the production build and retain local defaults', async () => {
  const root = new URL('../', import.meta.url)
  const docker = await readFile(new URL('deploy/Dockerfile.web', root), 'utf8')
  const localCompose = await readFile(new URL('compose.yaml', root), 'utf8')
  const productionCompose = await readFile(new URL('deploy/digitalocean/compose.prod.yaml', root), 'utf8')
  assert.match(docker, /ARG GRIDLENS_BUILD_SHA/)
  assert.match(docker, /ARG GRIDLENS_DEPLOYMENT_ENVIRONMENT/)
  assert.match(docker, /validate-web-build\.sh pre && npm run build && sh \/usr\/local\/bin\/validate-web-build\.sh post \/app\/dist/)
  assert.match(localCompose, /GRIDLENS_DEPLOYMENT_ENVIRONMENT: \$\{GRIDLENS_DEPLOYMENT_ENVIRONMENT:-local\}/)
  assert.match(productionCompose, /GRIDLENS_BUILD_SHA: \$\{GRIDLENS_BUILD_SHA:-\}/)
  assert.match(productionCompose, /GRIDLENS_DEPLOYMENT_ENVIRONMENT: production/)
})
