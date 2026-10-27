/* Real browser contract for the user-supplied ICE full-flow design. */
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const {spawn} = require('node:child_process');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE);

const repo = path.resolve(process.argv[2] || process.cwd());
const python = process.env.UI_PYTHON;
const chromePath = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const outputDir = process.env.UI_ACCEPTANCE_DIR ? path.resolve(process.env.UI_ACCEPTANCE_DIR) : null;
const widths = [320, 375, 390, 414, 768, 1280];
let server, browser;
const report = {viewports: [], navigation: [], requests: [], errors: []};

async function freePort() {
  const probe = net.createServer();
  await new Promise((resolve, reject) => probe.once('error', reject).listen(0, '127.0.0.1', resolve));
  const {port} = probe.address();
  await new Promise(resolve => probe.close(resolve));
  return port;
}

async function startServer(port, dataDir) {
  server = spawn(python, ['app.py', '--port', String(port), '--data-dir', dataDir], {
    cwd: repo,
    windowsHide: true,
    stdio: 'ignore',
    env: {...process.env, TIKHUB_API_KEY: '', LLM_ALLOW_PAID: '0'}
  });
  const origin = `http://127.0.0.1:${port}`;
  for (let i = 0; i < 100; i++) {
    try { if ((await fetch(origin + '/api/agent/tasks')).ok) return origin; } catch {}
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error('local ICE service did not start');
}

function stopServer() {
  if (!server) return Promise.resolve();
  const child = server;
  server = null;
  return new Promise(resolve => {
    child.once('exit', resolve);
    child.kill();
    setTimeout(resolve, 2000).unref();
  });
}

async function open(page, origin, route) {
  await page.goto(origin + route);
  await page.waitForLoadState('networkidle');
}

async function screenshot(page, name) {
  if (!outputDir) return;
  await fs.mkdir(outputDir, {recursive: true});
  await page.screenshot({path: path.join(outputDir, name + '.png'), fullPage: false, animations: 'disabled'});
}

function luminance(rgb) {
  const channels = rgb.match(/[\d.]+/g)?.slice(0, 3).map(Number) || [];
  return channels.length === 3 ? channels.reduce((sum, value) => sum + value, 0) / 3 : 255;
}

(async () => {
  const dataRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'ice-ui-fullflow-v2-'));
  try {
    const port = await freePort();
    const origin = await startServer(port, path.join(dataRoot, 'data'));
    browser = await chromium.launch({executablePath: chromePath, headless: true});
    const page = await browser.newPage({viewport: {width: 1280, height: 900}});
    page.on('pageerror', error => report.errors.push(error.message));
    page.on('request', request => {
      const url = new URL(request.url());
      if (url.protocol === 'http:' || url.protocol === 'https:') {
        report.requests.push({host: url.host, path: url.pathname, method: request.method()});
      }
    });

    for (const width of widths) {
      await page.setViewportSize({width, height: 900});
      for (const route of ['/dashboard', '/creative']) {
        await open(page, origin, route);
        const metrics = await page.evaluate(() => ({
          viewport: innerWidth,
          document: document.documentElement.scrollWidth,
          body: document.body.scrollWidth,
          nav: document.querySelectorAll('#siteNav a:not(.site-brand)').length
        }));
        assert(metrics.document <= width && metrics.body <= width, `${route} overflows at ${width}px`);
        assert.equal(metrics.nav, 11, 'all 11 navigation items remain present');
        report.viewports.push({route, ...metrics});

        if (width === 1280 && route === '/dashboard') {
          const palette = await page.evaluate(() => ({
            page: getComputedStyle(document.body).backgroundColor,
            rail: getComputedStyle(document.querySelector('.site-nav')).backgroundColor,
            brand: getComputedStyle(document.querySelector('.site-brand>span:last-child')).color,
            panel: getComputedStyle(document.querySelector('#workbench .wb-panel')).backgroundColor,
            focus: getComputedStyle(document.querySelector('#workbench .wb-kpi')).backgroundImage,
            account: getComputedStyle(document.querySelector('.ice-home-grid .ice-card')).backgroundColor,
            artifact: getComputedStyle(document.querySelector('#workbench .ice-card:not(.ice-home-grid .ice-card)')).backgroundColor,
            dataPanel: getComputedStyle(document.querySelector('.screen-grid .screen-panel')).backgroundColor
          }));
          assert(luminance(palette.page) < 64, `dashboard should use the reference's dark overview, got ${palette.page}`);
          assert(luminance(palette.rail) < 64, `shared navigation should use the reference's dark rail, got ${palette.rail}`);
          assert(luminance(palette.brand) > 100, `sidebar brand text should remain readable, got ${palette.brand}`);
          assert(luminance(palette.panel) < 64, `real workbench panels should use the dark palette, got ${palette.panel}`);
          assert(luminance(palette.account) < 64, `the live account summary should use the dark palette, got ${palette.account}`);
          assert(luminance(palette.artifact) < 64, `recent creative results should use the dark palette, got ${palette.artifact}`);
          assert(luminance(palette.dataPanel) < 64, `expanded data panels should use the dark palette, got ${palette.dataPanel}`);
          assert(palette.focus.includes('linear-gradient'), `the first real KPI should use the warm focus accent, got ${palette.focus}`);
          assert.equal(await page.locator('#workbench .wb-kpi').count(), 5, 'dashboard uses the five real workbench indicators');
          report.dashboardPalette = palette;
          await screenshot(page, 'dashboard-1280');
        }

        if (width === 1280 && route === '/creative') {
          const layout = await page.evaluate(() => {
            const box = selector => {
              const {x, y, width, height, right} = document.querySelector(selector).getBoundingClientRect();
              return {x, y, width, height, right};
            };
            return {
              columns: getComputedStyle(document.querySelector('.ice-task-layout')).gridTemplateColumns,
              stages: box('.ice-task-layout > aside:first-child'),
              workflow: box('.ice-task-center'),
              trace: box('#iceTrace'),
              optionalFieldsCollapsed: !document.querySelector('#creativeMore').open,
              optionalFields: document.querySelector('#creativeOutputOptions').closest('details')?.id
            };
          });
          assert(layout.workflow.x < layout.trace.x, 'trace panel stays beside the workflow on desktop');
          assert(layout.stages.x === layout.workflow.x, 'stage overview aligns with the workflow content');
          assert(layout.stages.width > layout.workflow.width, 'stage overview spans the workflow and trace columns');
          assert(layout.optionalFieldsCollapsed, 'optional choices start collapsed');
          assert.equal(layout.optionalFields, 'creativeMore', 'output and goal choices are inside optional details');
          report.workflowLayout = layout;
          await screenshot(page, 'creative-1280');
          await page.locator('[data-ice-step="iceTranscriptTitle"]').click();
          assert.equal(await page.locator('[data-ice-step="iceTranscriptTitle"]').getAttribute('aria-current'), 'step');
          assert.equal(await page.locator('[data-ice-step="sourceTitle"]').getAttribute('aria-current'), null);
          await page.locator('#creativeMore').evaluate(node => node.open = true);
          assert.equal(await page.locator('#creativeMore').getAttribute('open'), '');
        }

        if (width === 390 && route === '/creative') {
          await screenshot(page, 'creative-390');
          const actionWidths = await page.locator('.creative-task-actions button').evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().width));
          assert(actionWidths.every(width => width >= 120), `mobile task actions should remain usable, got ${actionWidths}`);
        }
      }
    }

    await page.setViewportSize({width: 1280, height: 900});
    await open(page, origin, '/dashboard');
    const links = await page.locator('#siteNav a:not(.site-brand)').evaluateAll(nodes =>
      nodes.map(node => ({name: node.innerText.trim(), href: node.getAttribute('href')})));
    for (const item of links) {
      await page.locator('#siteNav').getByRole('link', {name: item.name, exact: true}).click();
      await page.waitForLoadState('networkidle');
      assert.equal(new URL(page.url()).pathname, item.href, `navigation opens ${item.name}`);
      report.navigation.push(item);
    }

    assert.equal(report.errors.length, 0, JSON.stringify(report.errors));
    assert(report.requests.every(request => request.host === new URL(origin).host), 'browser stays on localhost');
    assert(!report.requests.some(request => /agent\/task\/generate|video\/generate|transcrib/.test(request.path)),
      'visual acceptance must not make paid requests');
    if (outputDir) await fs.writeFile(path.join(outputDir, 'browser-results.json'), JSON.stringify(report, null, 2));
    console.log('PASS local ICE browser contract: 6 widths, dark overview, 2-column workflow, 11 navigation items, no paid/external requests');
  } finally {
    if (browser) await browser.close();
    await stopServer();
    await fs.rm(dataRoot, {recursive: true, force: true});
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
