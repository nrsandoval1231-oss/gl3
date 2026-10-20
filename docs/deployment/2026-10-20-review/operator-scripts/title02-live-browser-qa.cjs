// Read-only live product verification. No title/research/provider POST is allowed.
const fs = require('fs'), path = require('path'), {execFileSync} = require('child_process');
process.env.PLAYWRIGHT_BROWSERS_PATH = path.join(__dirname, '.playwright-browsers');
const {chromium, expect} = require('./gl3-pr87-repair/web/node_modules/@playwright/test');
const mode = process.argv[2];
if (!['disabled', 'ready'].includes(mode)) throw new Error('Specify disabled or ready');
const origin = 'https://app.grid-lens.com';
const records = JSON.parse(fs.readFileSync('title02-jev-proposed-scope.json', 'utf8')).records;
const ssh = ['-i', path.join(process.env.USERPROFILE, '.ssh/id_ed25519'), '-o', 'IdentitiesOnly=yes',
  '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
  '-o', 'UserKnownHostsFile=C:/Users/nrsan/Documents/Codex/2026-10-15/task-3/gridlens-known-hosts', 'root@24.199.84.57'];
function session(action, value) {
  return JSON.parse(execFileSync('ssh', [...ssh, 'docker', 'exec', '-i', 'gridlens-api-1', 'uv', 'run',
    'python', '/tmp/gl3-transient-browser-session.py', action], {
    encoding: 'utf8', input: value ? JSON.stringify(value) : undefined, timeout: 30000, windowsHide: true,
  }));
}
const report = {checked_at: new Date().toISOString(), revision: '802cbb4055c515699ce998445f77f98ab96d65b1',
  live: true, mode, passed: false, blocked_writes: [], javascript_errors: [], api_errors: [],
  normal_password_login_tested: false, records: []};
let auth, browser;
(async () => { try {
  browser = await chromium.launch({headless: true});
  const context = await browser.newContext({baseURL: origin, viewport: {width: 1440, height: 1000}});
  expect((await context.request.get('/api/opportunities/workspace?limit=1')).status()).toBe(401);
  auth = session('issue');
  await context.addCookies([{name: 'gridlens_session', value: auth.token, domain: 'app.grid-lens.com', path: '/',
    secure: true, httpOnly: true, sameSite: 'Lax', expires: auth.expires}]);
  await context.route('**/api/**', route => {
    const request = route.request(), endpoint = new URL(request.url()).pathname;
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method()) && endpoint !== '/api/auth/logout') {
      report.blocked_writes.push(endpoint); return route.abort();
    }
    return route.continue();
  });
  const page = await context.newPage(); page.setDefaultTimeout(45000);
  page.on('pageerror', error => report.javascript_errors.push(error.message));
  page.on('response', response => { const url = new URL(response.url());
    if (url.origin === origin && url.pathname.startsWith('/api/') && response.status() >= 400)
      report.api_errors.push({path: url.pathname, status: response.status()});
  });
  for (const [index, record] of records.entries()) {
    const titleReply = await context.request.get(`/api/power-needs/${record.need_id}/title`);
    expect(titleReply.status()).toBe(200);
    const title = await titleReply.json(); expect(title.status).toBe(mode);
    if (mode === 'ready') { expect(title.result.title.length).toBeGreaterThan(10); expect(title.citations.length).toBeGreaterThan(0); expect(title.model).toBe('gpt-6-luna'); }
    const search = record.project.match(/\d{4}-\d+/)[0];
    const workspaceReply = await context.request.get(`/api/opportunities/workspace?limit=25&search=${search}`);
    expect(workspaceReply.status()).toBe(200);
    const rowData = (await workspaceReply.json()).items.find(item => item.id === record.need_id);
    expect(rowData).toBeTruthy();
    if (mode === 'ready') expect(rowData.browse_title).toBe(title.result.title);
    await page.setViewportSize({width: 1440, height: 1000});
    await page.goto(origin + '/?' + new URLSearchParams({view: 'workspace', q: search, need: record.need_id}));
    const detail = page.getByRole('complementary', {name: 'Opportunity detail'});
    const enrichment = page.getByRole('region', {name: 'Evidence-grounded title'});
    await expect(detail).toBeVisible();
    await expect(page.getByText(/^Loading verified detail/)).toHaveCount(0);
    const heading = detail.getByRole('heading', {level: 2});
    await expect(heading).not.toHaveText('');
    if (mode === 'ready') {
      await expect(heading).toHaveText(title.result.title);
      await expect(enrichment.getByRole('button', {name: 'Refresh title', exact: true})).toBeEnabled();
      await expect(enrichment).toContainText('Evidence-grounded title');
      for (const citation of title.citations) await expect(enrichment.locator('a').filter({hasText: citation.title})).toHaveAttribute('href', citation.url);
    } else {
      await expect(enrichment.getByRole('button', {name: 'Enrich title', exact: true})).toBeDisabled();
      await expect(enrichment).toContainText('Title enrichment is disabled');
    }
    const beforeReload = await heading.innerText();
    if (beforeReload !== rowData.name) await expect(detail).toContainText(`Source record: ${rowData.name}`);
    await expect(page.locator(`[data-need-row="${record.need_id}"] strong`)).toHaveText(beforeReload);
    await page.screenshot({path: `title02-${mode}-${index + 1}-desktop.png`, fullPage: true});
    await page.reload();
    await expect(detail).toBeVisible(); await expect(page.getByText(/^Loading verified detail/)).toHaveCount(0);
    await expect(heading).toHaveText(beforeReload);
    await page.setViewportSize({width: 390, height: 844});
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    await page.screenshot({path: `title02-${mode}-${index + 1}-mobile.png`, fullPage: true});
    report.records.push({need_id: record.need_id, title: beforeReload, title_status: title.status,
      raw_source_name: rowData.name, raw_source_preserved: true,
      reload_preserved: true, mobile_width: 390, horizontal_overflow: false});
  }
  await page.getByRole('button', {name: 'Sign out', exact: true}).click();
  await expect(page.getByRole('heading', {name: 'Sign in', exact: true})).toBeVisible();
  expect((await context.request.get('/api/opportunities/workspace?limit=1')).status()).toBe(401);
  expect(report.blocked_writes).toEqual([]); expect(report.javascript_errors).toEqual([]); expect(report.api_errors).toEqual([]);
  report.passed = true;
} catch (error) { report.failure = {name: error.name, message: error.message.slice(0, 1800)}; process.exitCode = 1; }
finally {
  if (browser) await browser.close();
  if (auth) { try { report.session_revoked = session('revoke', {token: auth.token}).revoked; }
    catch { report.session_revoked = false; process.exitCode = 1; } }
  fs.writeFileSync(`title02-live-browser-${mode}.json`, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report));
}})();
