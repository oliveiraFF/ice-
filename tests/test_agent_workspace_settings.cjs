/* Real local ICE UI test for the persisted Agent workspace selector. */
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const {spawn} = require('node:child_process');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE);

const repo = path.resolve(process.argv[2]);
const workspace = path.resolve(process.argv[3]);
const python = process.env.UI_PYTHON;
if (!repo || !workspace || !python) throw new Error('Pass repo/workspace and UI_PYTHON.');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function freePort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => server.once('error', reject).listen(0, '127.0.0.1', resolve));
  const {port} = server.address();
  await new Promise(resolve => server.close(resolve));
  return port;
}
async function hashInputs() {
  const files = [
    'project.manifest.json', 'config/profile/account.profile.json', 'config/profile/audience.profile.json',
    'config/profile/offer.profile.json', 'config/strategy/strategy-brief.json',
    'config/policies/topic-discovery.policy.json', 'data/operations/current/account-snapshot.json',
    'data/feedback/raw/post-metrics.json', 'data/topic-research/current/strategy-assessment.json',
    'presentation/ops-dashboard.json', 'presentation/status.json',
    'work/topics/selections/daily.json', 'work/plans/daily.json',
    'data/benchmarks/current/reference-bank.json', 'data/topic-research/current/pain-bank.json',
    'data/feedback/raw/published-posts.json', 'data/feedback/current/learning.json', 'runs/.gitkeep',
  ];
  const result = {};
  for (const file of files) {
    try {
      result[file] = crypto.createHash('sha256').update(await fs.readFile(path.join(workspace, file))).digest('hex');
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
      result[file] = null;
    }
  }
  return result;
}

(async () => {
  const tempRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'ice-agent-settings-ui-'));
  const dataDir = path.join(tempRoot, 'data');
  await fs.mkdir(dataDir);
  const port = await freePort();
  const origin = `http://127.0.0.1:${port}`;
  const env = {...process.env, SHORT_VIDEO_OPS_WORKSPACE: ''};
  const server = spawn(python, ['app.py', '--port', String(port), '--data-dir', dataDir], {
    cwd: repo, env, windowsHide: true, stdio: 'ignore',
  });
  let browser;
  const results = {statuses: [], widths: [], errors: [], externalRequests: 0};
  try {
    let ready = false;
    for (let attempt = 0; attempt < 100; attempt++) {
      try {
        const response = await fetch(origin + '/api/state?mode=live');
        if (response.ok) { ready = true; break; }
      } catch (_) {}
      await pause(100);
    }
    assert(ready, 'ICE local service failed to start');
    const before = await hashInputs();
    browser = await chromium.launch({
      executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true,
    });
    const context = await browser.newContext({viewport: {width: 1280, height: 900}});
    const page = await context.newPage();
    page.on('pageerror', error => results.errors.push(error.message));
    page.on('request', request => {
      if (new URL(request.url()).origin !== origin) results.externalRequests++;
    });

    await page.goto(origin + '/');
    await page.waitForLoadState('networkidle');
    await page.locator('#siteSettings').click();
    await page.locator('#settingsDialog #agentWorkspaceForm').waitFor({state: 'visible'});
    assert.equal(await page.locator('#settingsDialog #agentWorkspaceForm').count(), 1,
      'the default local-video page must show Agent settings inside its active data-source dialog');
    assert.equal(await page.locator('#siteSettingsDialog #agentWorkspaceForm').count(), 0,
      'Agent settings must not be attached to the inactive duplicate dialog');
    await page.locator('#settingsDialog').evaluate(dialog => dialog.close());

    await page.goto(origin + '/ops-wallboard');
    await page.waitForLoadState('networkidle');
    await page.locator('#siteSettings').click();
    await page.locator('#agentWorkspaceForm').waitFor({state: 'visible'});
    assert.equal(await page.locator('#agentWorkspaceBrowse').isDisabled(), true,
      'browser mode should not pretend to open a native folder picker');
    assert.equal(await page.locator('#siteApiKey').getAttribute('type'), 'password');
    assert.equal(await page.locator('#siteApiKey').inputValue(), '');

    for (const width of [1280, 768, 414, 390, 375, 360, 320]) {
      await page.setViewportSize({width, height: 900});
      await page.waitForTimeout(120);
      const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
      assert(scrollWidth <= width, `settings overflow at ${width}px: ${scrollWidth}`);
      results.widths.push({width, scrollWidth});
      if (width === 1280 || width === 390) {
        await page.screenshot({path: path.join(tempRoot, `settings-${width}.png`), animations: 'disabled'});
      }
    }
    for (const selector of ['#agentWorkspacePath','#agentWorkspaceBrowse','#agentWorkspaceSave','#agentWorkspaceClear']) {
      const height = await page.locator(selector).evaluate(node => node.getBoundingClientRect().height);
      assert(height >= 44, `${selector} touch target must be at least 44px, got ${height}`);
    }

    await page.locator('#agentWorkspacePath').fill(workspace);
    await page.getByRole('button', {name: '校验并保存'}).click();
    await page.locator('#agentWorkspaceStatus').filter({hasText: '路径保存在 ICE 本机数据目录'}).waitFor();
    results.statuses.push('real-workspace-saved');
    await page.locator('#connectionLabel').filter({hasText: '已连接'}).waitFor();
    const viewModel = await page.evaluate(async () => (await fetch('/api/agent/view-model')).json());
    assert.equal(viewModel.workspace.connected, true);
    assert.equal(JSON.stringify(viewModel).includes('1970-01-01'), false,
      'epoch placeholder dates must remain unknown instead of appearing as real freshness');
    assert(viewModel.dashboard.kpis.every(row => row.value === null),
      'missing real KPI values must remain unavailable, not fabricated');
    assert.equal(viewModel.account.state, 'blocked', 'unconfirmed profile and missing post metrics must block account conclusions');
    assert.equal(viewModel.account.assessment.conclusion, null, 'unconfirmed conclusions must not reach the UI model');
    assert(viewModel.account.blockers.some(row => row.id === 'strategy_confirmation'));
    assert(viewModel.workbench.materials.some(row => row.id === 'pain_points'));
    assert.equal(await page.locator('#siteNav a:not(.site-brand)').count(), 11,
      'Agent entry must preserve the existing 11 navigation items');
    await page.locator('#accountSummary').filter({hasText: '只列出缺口'}).waitFor();
    assert.equal(await page.locator('#accountConfirmedProfile').isVisible(), false,
      'unconfirmed profile content must stay hidden');
    for (const width of [1280, 768, 414, 390, 375, 360, 320]) {
      await page.setViewportSize({width, height: 900});
      await page.waitForTimeout(100);
      const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
      assert(scrollWidth <= width, `Agent wallboard overflow at ${width}px: ${scrollWidth}`);
    }
    await page.locator('#closeSiteSettings').click();
    assert.equal(await page.locator('main').innerText().then(text => text.includes(workspace)), false,
      'the dashboard must not expose the selected local path');
    for (const width of [1280, 768, 414, 390, 375, 360, 320]) {
      await page.setViewportSize({width, height: 900});
      await page.waitForTimeout(120);
      const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
      assert(scrollWidth <= width, `connected Agent wallboard overflow at ${width}px: ${scrollWidth}`);
      if (width === 1280 || width === 390) {
        await page.screenshot({path: path.join(tempRoot, `wallboard-${width}.png`), fullPage: true, animations: 'disabled'});
      }
    }

    await page.locator('#siteSettings').click();
    await page.locator('#agentWorkspaceForm').waitFor({state: 'visible'});
    assert.equal(await page.locator('#agentWorkspacePath').inputValue(), workspace,
      'saved path should restore when settings are reopened');
    const invalidWorkspace = path.join(tempRoot, 'not-a-workspace');
    await fs.mkdir(invalidWorkspace);
    await page.locator('#agentWorkspacePath').fill(invalidWorkspace);
    await page.getByRole('button', {name: '校验并保存'}).click();
    await page.locator('#agentWorkspaceStatus').filter({hasText: 'manifest'}).waitFor();
    const retained = await page.evaluate(async () => (await fetch('/api/agent/workspace-config')).json());
    assert.equal(path.resolve(retained.configured_path), workspace,
      'invalid replacement must leave the previous path intact');
    results.statuses.push('invalid-path-rejected-old-path-retained');

    page.once('dialog', dialog => dialog.accept());
    await page.locator('#agentWorkspaceClear').click();
    await page.waitForFunction(() => document.querySelector('#agentWorkspacePath').value === '');
    const cleared = await page.evaluate(async () => (await fetch('/api/agent/workspace-config')).json());
    assert.equal(cleared.configured_path, '');
    results.statuses.push('local-binding-cleared');

    const after = await hashInputs();
    assert.deepEqual(after, before, 'workspace source files changed during read-only configuration');
    assert.equal(results.errors.length, 0, JSON.stringify(results.errors));
    assert.equal(results.externalRequests, 0);
    results.workspaceHashUnchanged = true;
    results.apiKeyNotReturned = !JSON.stringify(viewModel).toLowerCase().includes('api_key');
    assert(results.apiKeyNotReturned);
    await fs.writeFile(path.join(tempRoot, 'acceptance.json'), JSON.stringify(results, null, 2));
    console.log(JSON.stringify({pass: true, widths: results.widths, statuses: results.statuses,
      workspaceHashUnchanged: results.workspaceHashUnchanged, apiKeyNotReturned: results.apiKeyNotReturned,
      externalRequests: results.externalRequests, errors: results.errors.length}));
  } finally {
    if (browser) await browser.close();
    server.kill();
    await new Promise(resolve => server.once('exit', resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
