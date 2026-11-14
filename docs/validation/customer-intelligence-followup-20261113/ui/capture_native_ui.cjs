const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const root = process.env.GRIDLENS_SOURCE_ROOT || path.resolve(__dirname, '../../../..');
const { chromium, expect } = require(path.join(root, 'web/node_modules/@playwright/test'));
const manifest = JSON.parse(fs.readFileSync(process.env.GRID_UI_RUN_MANIFEST, 'utf8'));
const output = process.env.GRID_UI_RUN_OUTPUT;
const mode = process.env.GRID_UI_MODE;
const digest = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const cleanAccount = account => ({
  name: account.name,
  group_kind: account.group_kind,
  capacity_totals: account.capacity_totals,
  power_amount_class: account.power_amount_class,
  permitted_contact_route_count: account.permitted_contact_route_count,
  recent_developments: (account.recent_developments ?? []).map(item => ({
    summary: item.summary ?? item.title ?? item.label ?? null,
    source_date: item.source_date ?? null,
  })),
});
let liveBrowser;
let livePage;
const phase = { value: 'initial' };
const pageErrors = [];
const externalRequests = [];
const groupResponses = [];

(async () => {
  if (!['before', 'after'].includes(mode)) throw new Error('Capture mode must be before or after');
  if (!manifest.database_name?.startsWith(`gl3_ui_followup_${mode}_`) || !manifest.database_name.endsWith('_test')) {
    throw new Error('Capture manifest must identify this mode’s disposable gl3_ui_followup *_test database');
  }
  const browser = await chromium.launch({ headless: true });
  liveBrowser = browser;
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'en-US', timezoneId: 'UTC' });
  await context.route('**/*', route => {
    const url = new URL(route.request().url());
    if (['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)) return route.continue();
    externalRequests.push(`${url.origin}${url.pathname}`);
    return route.abort();
  });
  const page = await context.newPage();
  livePage = page;
  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('response', async response => {
    const url = new URL(response.url());
    if (url.pathname !== '/api/opportunities/groups') return;
    const body = await response.json();
    groupResponses.push({
      status: response.status(),
      query: Object.fromEntries(url.searchParams.entries()),
      total: body.total,
      generation_id: body.generation_id,
      items: (body.items ?? []).map(group => cleanAccount({
        ...group,
        power_amount_class: group.featured_project?.commercial_brief?.power_need?.amount_class ?? 'unknown',
        permitted_contact_route_count: group.account_contact_project?.contact?.length ?? 0,
        recent_developments: (group.commercial_intelligence?.recent_developments ?? []).map(item => ({
          summary: item.summary ?? item.title ?? item.label ?? null,
          source_date: item.source_date ?? null,
        })),
        capacity_totals: group.commercial_intelligence?.capacity?.totals ?? [],
      })),
    });
  });
  phase.value = 'login';
  await page.goto(process.env.GRIDLENS_UI_URL || 'http://127.0.0.1:15443/');
  await page.getByLabel('Password', { exact: true }).fill(process.env.GRID_TEST_PASSWORD);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Customers', exact: true })).toBeVisible();
  phase.value = 'native-customer-list';
  const groups = page.locator('.customer-group');
  await expect(groups).toHaveCount(2);
  await expect(page.getByRole('navigation', { name: 'Opportunity scope' }).getByRole('button', { name: 'All customers', exact: true })).toHaveAttribute('aria-pressed', 'true');
  const dataBank = page.getByRole('region', { name: 'DataBank customer group' });
  const cyrusOne = page.getByRole('region', { name: 'CyrusOne customer group' });
  await expect(dataBank).toContainText('DataBank');
  await expect(cyrusOne).toContainText('CyrusOne');
  const dataBankFixture = manifest.accounts.find(account => account.name === 'DataBank');
  const cyrusFixture = manifest.accounts.find(account => account.name === 'CyrusOne');
  if (!dataBankFixture || !cyrusFixture) throw new Error('Native manifest must include DataBank and CyrusOne');
  await expect(dataBank).not.toContainText(/(?<!\d)0\s*MW\b/);
  await expect(dataBank).not.toContainText(/priority score/i);
  await expect(dataBank).not.toContainText(/0\.56|0\.91/);
  if (dataBankFixture.power_amount_class !== 'unknown') throw new Error('The native fixture should not assert a supported customer power need');
  if (dataBankFixture.permitted_contact_route_count === 0) {
    await expect(dataBank.getByRole('link', { name: /Call|Email/ })).toHaveCount(0);
  }
  if (mode === 'before') {
    const historicalAccount = manifest.accounts.find(account => account.recent_developments.length > 0);
    if (!historicalAccount) throw new Error('Pre-PR202 native control must contain a historical first-fact revision label');
    const historicalCard = page.getByRole('region', { name: `${historicalAccount.name} customer group` });
    const staleEvent = historicalAccount.recent_developments[0];
    if (!staleEvent.source_date) throw new Error('The pre-PR202 control must retain the source date on its false recent label');
    await expect(historicalCard.getByText('Recent development', { exact: true })).toBeVisible();
    await expect(historicalCard).toContainText(staleEvent.summary);
    await expect(historicalCard).toContainText(`Source date ${staleEvent.source_date}`);
  } else {
    for (const account of [dataBank, cyrusOne]) await expect(account.getByText('Recent development', { exact: true })).toHaveCount(0);
  }
  await page.evaluate(async () => { await document.fonts.ready; });
  await page.screenshot({ path: path.join(output, `${mode}-customers-desktop.png`), fullPage: true });

  phase.value = 'native-account-detail';
  await dataBank.getByRole('button', { name: /DataBank/ }).click();
  const detail = page.getByRole('region', { name: 'Company DataBank' });
  await expect(detail.getByRole('heading', { name: 'DataBank', exact: true })).toBeVisible();
  await expect(detail.getByRole('region', { name: 'Account projects' })).toBeVisible();
  await expect(detail.getByText('Commercial analysis', { exact: true })).toBeVisible();
  await expect(detail.locator('.cmp-commercial-analysis')).not.toHaveAttribute('open', '');
  if (dataBankFixture.permitted_contact_route_count === 0) {
    await expect(detail.getByText(/No verified business contact|Professional contact details unavailable/)).toBeVisible();
    await expect(detail.getByRole('link', { name: /Call|Email/ })).toHaveCount(0);
  }
  await page.evaluate(async () => { await document.fonts.ready; });
  await page.screenshot({ path: path.join(output, `${mode}-databank-detail-desktop.png`), fullPage: true });
  const analysis = detail.locator('.cmp-commercial-analysis');
  await analysis.locator('summary').first().click();
  await expect(analysis).toHaveAttribute('open', '');
  await expect(analysis.getByRole('heading', { name: 'Build capacity', exact: true })).toBeVisible();
  await expect(analysis).toContainText('Up to 480 MW · IT load');
  await expect(analysis.getByRole('heading', { name: 'Timing', exact: true })).toBeVisible();
  await expect(analysis).toContainText('No supported timeline is available.');
  const sourceLinks = await analysis.locator('a').count();
  if (sourceLinks > 0) {
    await expect(analysis.getByRole('heading', { name: 'Sources', exact: true })).toBeVisible();
    await expect(analysis.getByRole('link', { name: 'Evidence source', exact: true }).first()).toBeVisible();
    await expect(analysis).not.toContainText(/(?:^|\s)[0-9a-f]{8}-[0-9a-f-]{27,}(?:\s|$)/i);
  }
  await page.screenshot({ path: path.join(output, `${mode}-databank-detail-commercial-open-desktop.png`), fullPage: true });

  if (mode === 'after') {
    phase.value = 'native-mobile-list';
    await page.goto(process.env.GRIDLENS_UI_URL || 'http://127.0.0.1:15443/');
    await expect(page.getByRole('heading', { name: 'Customers', exact: true })).toBeVisible();
    await expect(page.locator('.project-results')).toHaveAttribute('aria-busy', 'false');
    await expect(page.locator('.customer-group')).toHaveCount(2);
    await expect(page.getByRole('region', { name: 'DataBank customer group' })).toBeVisible();
    await expect(page.getByRole('region', { name: 'CyrusOne customer group' })).toBeVisible();
    await page.setViewportSize({ width: 390, height: 844 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    await page.screenshot({ path: path.join(output, 'after-customers-mobile.png'), fullPage: true });
  }

  const expectedModes = groupResponses.filter(item => item.status === 200);
  expect(expectedModes.length).toBeGreaterThan(0);
  expect(expectedModes.every(item => item.query.canonical_only === 'true' && item.query.shortlist === 'false')).toBeTruthy();
  expect(new Set(expectedModes.map(item => item.generation_id)).size).toBe(1);
  expect(pageErrors).toEqual([]);
  expect(externalRequests).toEqual([]);
  await browser.close();
  liveBrowser = null;
  const screenshots = Object.fromEntries(
    fs.readdirSync(output).filter(file => file.startsWith(`${mode}-`) && file.endsWith('.png')).map(file => [file, digest(path.join(output, file))]),
  );
  if (mode === 'after') screenshots['after-customers-mobile.png'] = digest(path.join(output, 'after-customers-mobile.png'));
  fs.writeFileSync(path.join(output, `${mode}-capture.json`), JSON.stringify({
    mode,
    database: manifest.database_name,
    api_mocking: false,
    retained_native_sources: manifest.source_selection,
    source_artifact_sha256: manifest.source_artifact_sha256,
    saved_browse_generation: manifest.generation_id,
    accounts: manifest.accounts.map(account => ({
      name: account.name,
      group_kind: account.group_kind,
      capacity_totals: account.capacity_totals,
      power_amount_class: account.power_amount_class,
      permitted_contact_route_count: account.permitted_contact_route_count,
      recent_developments: account.recent_developments,
    })),
    group_responses: groupResponses,
    expanded_account_detail: mode === 'after' ? {
      account: 'DataBank',
      build_capacity: 'Up to 480 MW · IT load',
      supported_timeline: false,
      source_link_count: sourceLinks,
    } : null,
    page_errors: pageErrors,
    external_requests: externalRequests,
    screenshots,
  }, null, 2));
  console.log(`PASS: ${mode} native source UI captured; account list loaded; no external requests or page errors.`);
})().catch(async error => {
  console.error(JSON.stringify({ phase: phase.value, url: livePage?.url(), pageErrors, externalRequests, body: await livePage?.locator('body').innerText().catch(() => ''), error: error.message }));
  await liveBrowser?.close();
  process.exitCode = 1;
});
