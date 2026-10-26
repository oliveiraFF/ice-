/* Real Chromium acceptance for the read-only operations wallboard. */
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs/promises');
const path = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE);

const origin = process.env.WALLBOARD_ORIGIN || 'http://127.0.0.1:8879';
const fixtureRoot = path.resolve(process.env.WALLBOARD_FIXTURE_WORKSPACE);
const templateRoot = process.env.WALLBOARD_TEMPLATE_SOURCE ? path.resolve(process.env.WALLBOARD_TEMPLATE_SOURCE) : null;
const outputDir = path.resolve(process.env.WALLBOARD_ACCEPTANCE_DIR);
const chromePath = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const report = {origin, viewports: [], navigation: [], states: [], requests: [], navigation_requests: [], errors: [], hashes: {}};

async function treeHash(root) {
  const entries = [];
  async function walk(dir) {
    for (const entry of await fs.readdir(dir, {withFileTypes: true})) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) await walk(full);
      else if (entry.isFile()) {
        const bytes = await fs.readFile(full);
        entries.push([path.relative(root, full).replaceAll(path.sep, '/'), crypto.createHash('sha256').update(bytes).digest('hex')]);
      }
    }
  }
  await walk(root);
  return crypto.createHash('sha256').update(JSON.stringify(entries.sort((a,b) => a[0].localeCompare(b[0])))).digest('hex');
}

async function main() {
  await fs.mkdir(outputDir, {recursive: true});
  report.hashes.fixture_before = await treeHash(fixtureRoot);
  if (templateRoot) report.hashes.template_before = await treeHash(templateRoot);
  const browser = await chromium.launch({executablePath: chromePath, headless: true});
  try {
    const context = await browser.newContext({viewport: {width: 1920, height: 1080}, deviceScaleFactor: 1});
    const page = await context.newPage();
    await page.addInitScript(() => {
      const setIntervalOriginal = window.setInterval.bind(window);
      window.__scheduledIntervals = [];
      window.setInterval = (callback, delay, ...args) => {
        window.__scheduledIntervals.push(delay);
        return setIntervalOriginal(callback, delay, ...args);
      };
    });
    page.on('pageerror', error => report.errors.push(error.message));
    page.on('console', message => {
      if (message.type() === 'error' && !message.text().includes('Failed to load resource: net::ERR_FAILED')) {
        report.errors.push('console: ' + message.text());
      }
    });
    page.on('request', request => {
      const url = new URL(request.url());
      if (url.protocol === 'http:' || url.protocol === 'https:') {
        report.requests.push({method: request.method(), host: url.host, path: url.pathname});
      }
    });
    const configResponse = await fetch(origin + '/api/ai/config', {method: 'GET'});
    assert.equal(configResponse.status, 200, 'isolated model config check must be local and successful');
    const config = await configResponse.json();
    const modelConfig = {connected: config.connected, endpointConfigured: Boolean(config.endpoint), modelConfigured: Boolean(config.model)};
    assert.equal(modelConfig.connected, false, 'isolated app data must have no in-memory model key');
    assert.equal(modelConfig.endpointConfigured, false);
    assert.equal(modelConfig.modelConfigured, false);
    report.model_config = modelConfig;
    report.verification_requests = [{method: 'GET', host: new URL(origin).host, path: '/api/ai/config'}];

    const viewports = [
      {width: 1920, height: 1080}, {width: 2560, height: 1440},
      {width: 320, height: 844}, {width: 375, height: 844},
      {width: 390, height: 844}, {width: 414, height: 844},
      {width: 768, height: 900}, {width: 1280, height: 900}
    ];
    for (const viewport of viewports) {
      await page.setViewportSize(viewport);
      const response = await page.goto(origin + '/ops-wallboard', {waitUntil: 'networkidle'});
      assert.equal(response.status(), 200, 'wallboard HTML must load');
      await page.locator('#connectionLabel').waitFor({state: 'visible'});
      await page.waitForFunction(() => document.querySelector('#connectionLabel')?.textContent === '已连接');
      const measurements = await page.evaluate(() => ({
        width: innerWidth,
        height: innerHeight,
        documentWidth: document.documentElement.scrollWidth,
        bodyWidth: document.body.scrollWidth,
        navItems: document.querySelectorAll('#siteNav a:not(.site-brand)').length,
        kpis: document.querySelectorAll('.wallboard-kpi').length,
        pipeline: document.querySelectorAll('#pipelineList > li').length,
        controlHeights: [...document.querySelectorAll('.wallboard-controls button')].map(button => ({
          height: Math.round(button.getBoundingClientRect().height),
          minHeight: getComputedStyle(button).minHeight,
          cssHeight: getComputedStyle(button).height,
        })),
        boardBackground: getComputedStyle(document.querySelector('.wallboard-main')).backgroundColor,
      }));
      assert(measurements.documentWidth <= viewport.width, 'document horizontal overflow at ' + viewport.width);
      assert(measurements.bodyWidth <= viewport.width, 'body horizontal overflow at ' + viewport.width);
      assert.equal(measurements.navItems, 11, 'the existing 11 navigation items remain');
      assert.equal(measurements.kpis, 4);
      assert.equal(measurements.pipeline, 5);
      assert(measurements.controlHeights.every(item => item.height >= 44), 'touch controls meet 44px minimum at ' + viewport.width + ': ' + JSON.stringify(measurements.controlHeights));
      assert.equal(await page.locator('.wallboard-kpi strong').first().innerText(), '待接入', 'missing metrics must not be shown as zero');
      assert.doesNotMatch(await page.locator('.wallboard-kpis').innerText(), /presentation\//);
      assert.doesNotMatch(await page.locator('.wallboard-main').innerText(), /Agent workspace|workspace/);
      if (viewport.width === 390) {
        assert.equal(await page.locator('[data-kpi-updated="todo"]').innerText(), '运营指标 · 时间未记录');
        assert(await page.evaluate(() => window.__scheduledIntervals.includes(60000)), 'automatic refresh must be scheduled every 60 seconds');
      }
      report.viewports.push(measurements);
      if ([390, 1920, 2560].includes(viewport.width)) {
        await page.screenshot({path: path.join(outputDir, `wallboard-${viewport.width}x${viewport.height}.png`), animations: 'disabled'});
      }
      if (viewport.width === 1920) {
        assert.equal(await page.locator('.wallboard-alert-item').count(), 1, 'template fixture should truthfully show the missing dashboard source');
        assert.match(await page.locator('.wallboard-recent-panel').innerText(), /暂无动态记录/);
        assert.match(await page.locator('#workspaceNotice').innerText(), /合成演示数据/);
        assert(await page.locator('#pipelineList a[href="/research"]').count() === 1, 'a valid view link is exposed');
        await page.locator('#pipelineList a[href="/research"]').click();
        await page.waitForURL('**/research');
        report.pipeline_navigation = {source: 'pipeline stage', href: '/research', result: new URL(page.url()).pathname};
        await page.goto(origin + '/ops-wallboard', {waitUntil: 'networkidle'});
      }
    }

    const navItems = await page.locator('#siteNav a:not(.site-brand)').evaluateAll(links => links.map(link => ({
      label: link.innerText.trim(), href: link.getAttribute('href')
    })));
    assert.equal(navItems.length, 11, 'the existing navigation remains exactly 11 items');
    const navPage = await context.newPage();
    navPage.on('request', request => {
      const url = new URL(request.url());
      if (url.protocol === 'http:' || url.protocol === 'https:') report.navigation_requests.push({method: request.method(), host: url.host, path: url.pathname});
    });
    for (let index = 0; index < navItems.length; index += 1) {
      await navPage.goto(origin + '/ops-wallboard', {waitUntil: 'networkidle'});
      const navigation = navPage.waitForNavigation({waitUntil: 'networkidle'});
      await navPage.locator('#siteNav a:not(.site-brand)').nth(index).click();
      const response = await navigation;
      const result = new URL(navPage.url()).pathname;
      assert.equal(response.status(), 200, 'navigation item loads: ' + navItems[index].href);
      assert.equal(result, navItems[index].href, 'navigation target matches its href');
      report.navigation.push({label: navItems[index].label, href: navItems[index].href, status: response.status()});
    }
    await navPage.close();

    // A failed refresh after a successful read must preserve the last view model.
    await page.setViewportSize({width: 1920, height: 1080});
    await page.goto(origin + '/ops-wallboard', {waitUntil: 'networkidle'});
    const previousAlert = await page.locator('#alertList').innerText();
    await page.route('**/api/agent/view-model', route => route.abort('failed'));
    await page.locator('#refreshButton').click();
    await page.getByText('刷新失败，仍显示上次成功读取的数据；当前内容可能不是最新。', {exact: true}).waitFor();
    assert.equal(await page.locator('#alertList').innerText(), previousAlert, 'failed refresh must retain previous data');
    assert.equal(await page.locator('#connectionLabel').innerText(), '离线 · 显示上次数据');
    report.states.push({name: 'refresh failure', result: 'old view model retained; stale notice shown'});
    await page.screenshot({path: path.join(outputDir, 'wallboard-refresh-failure.png'), animations: 'disabled'});
    await page.unroute('**/api/agent/view-model');

    // Separate first-load offline state, where no cached data exists.
    const offline = await context.newPage();
    offline.on('pageerror', error => report.errors.push(error.message));
    await offline.route('**/api/agent/view-model', route => route.abort('failed'));
    await offline.goto(origin + '/ops-wallboard', {waitUntil: 'networkidle'});
    await offline.getByText('尚未读取到数据；请检查本机服务后重试。', {exact: true}).waitFor();
    assert.equal(await offline.locator('#connectionLabel').innerText(), '离线');
    report.states.push({name: 'first-load offline', result: 'offline state shown without claiming data'});
    await offline.screenshot({path: path.join(outputDir, 'wallboard-first-load-offline.png'), animations: 'disabled'});
    await offline.close();

    // Only this local app's GET routes should be touched; no content mutations or paid services.
    assert(report.requests.every(request => request.host === new URL(origin).host), 'browser must not call outside this local app');
    assert(report.requests.every(request => request.method === 'GET'), 'wallboard must issue read-only GET requests');
    assert(report.requests.some(request => request.path === '/api/agent/view-model'));
    assert(report.navigation_requests.every(request => request.host === new URL(origin).host), 'navigation regression must not call outside this local app');
    const existingPreview = report.navigation_requests.filter(request => request.method !== 'GET');
    assert(existingPreview.every(request => request.method === 'POST' && request.path === '/api/ai/cache'), 'only the existing local preview request may be non-GET');
    report.navigation_existing_side_effect = existingPreview;
    assert.equal(report.errors.length, 0, JSON.stringify(report.errors));
    report.hashes.fixture_after = await treeHash(fixtureRoot);
    assert.equal(report.hashes.fixture_after, report.hashes.fixture_before, 'read-only bridge/UI must not change template fixture files');
    if (templateRoot) {
      report.hashes.template_after = await treeHash(templateRoot);
      assert.equal(report.hashes.template_after, report.hashes.template_before, 'read-only bridge/UI must not change the source template');
    }
    report.result = 'PASS';
    await fs.writeFile(path.join(outputDir, 'browser-acceptance.json'), JSON.stringify(report, null, 2), 'utf8');
    console.log(JSON.stringify(report, null, 2));
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  report.result = 'FAIL';
  report.failure = error.stack || String(error);
  fs.mkdir(outputDir, {recursive: true})
    .then(() => fs.writeFile(path.join(outputDir, 'browser-acceptance.json'), JSON.stringify(report, null, 2), 'utf8'))
    .finally(() => { console.error(error); process.exitCode = 1; });
});
