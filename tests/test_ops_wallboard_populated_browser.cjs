/* Real Chromium run using explicitly labeled data in a disposable template copy. */
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs/promises');
const path = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE);

const origin = process.env.WALLBOARD_ORIGIN || 'http://127.0.0.1:8880';
const fixtureRoot = path.resolve(process.env.WALLBOARD_POPULATED_FIXTURE_WORKSPACE);
const outputDir = path.resolve(process.env.WALLBOARD_ACCEPTANCE_DIR);
const chromePath = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const report = {origin, rows: [], requests: [], errors: []};

async function treeHash(root) {
  const entries = [];
  async function walk(dir) {
    for (const entry of await fs.readdir(dir, {withFileTypes: true})) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) await walk(full);
      else if (entry.isFile()) entries.push([path.relative(root, full).replaceAll(path.sep, '/'), crypto.createHash('sha256').update(await fs.readFile(full)).digest('hex')]);
    }
  }
  await walk(root);
  return crypto.createHash('sha256').update(JSON.stringify(entries.sort((a,b) => a[0].localeCompare(b[0])))).digest('hex');
}

async function main() {
  await fs.mkdir(outputDir, {recursive: true});
  report.fixture_sha256_before = await treeHash(fixtureRoot);
  const browser = await chromium.launch({executablePath: chromePath, headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1920, height: 1080}});
    page.on('pageerror', error => report.errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') report.errors.push(message.text()); });
    page.on('request', request => {
      const url = new URL(request.url());
      if (url.protocol === 'http:' || url.protocol === 'https:') report.requests.push({method: request.method(), host: url.host, path: url.pathname});
    });
    const response = await page.goto(origin + '/ops-wallboard', {waitUntil: 'networkidle'});
    assert.equal(response.status(), 200);
    await page.waitForFunction(() => document.querySelector('[data-kpi="in_progress"]')?.textContent === '3');
    assert.equal(await page.locator('[data-kpi="todo"]').innerText(), '0');
    assert.equal(await page.locator('[data-kpi="review"]').innerText(), '2');
    assert.equal(await page.locator('[data-kpi="blocked"]').innerText(), '0');
    assert.equal(await page.locator('[data-kpi-updated="todo"]').innerText(), '运营指标 · 10/26 08:00');
    const pipeline = await page.locator('#pipelineList strong').allInnerTexts();
    assert.deepEqual(pipeline, ['4','3','2','1','0']);
    assert.match(await page.locator('#alertList').innerText(), /今日无阻塞/);
    assert.match(await page.locator('#recentRows').innerText(), /合成验收记录/);
    assert.match(await page.locator('#workspaceNotice').innerText(), /合成演示数据/);
    assert.doesNotMatch(await page.locator('.wallboard-main').innerText(), /presentation\//);
    report.rows = {kpis: {todo: 0, in_progress: 3, review: 2, blocked: 0}, pipeline, syntheticLabel: true, recent: true, completeAlerts: true};
    await page.screenshot({path: path.join(outputDir, 'wallboard-synthetic-data-1920x1080.png'), animations: 'disabled'});
    assert(report.requests.every(item => item.host === new URL(origin).host));
    assert(report.requests.every(item => item.method === 'GET'));
    assert.equal(report.errors.length, 0, JSON.stringify(report.errors));
    report.fixture_sha256_after = await treeHash(fixtureRoot);
    assert.equal(report.fixture_sha256_after, report.fixture_sha256_before, 'UI read must not change the synthetic fixture');
    report.result = 'PASS';
    await fs.writeFile(path.join(outputDir, 'populated-browser-acceptance.json'), JSON.stringify(report, null, 2), 'utf8');
    console.log(JSON.stringify(report, null, 2));
  } finally {
    await browser.close();
  }
}

main().catch(async error => {
  report.result = 'FAIL';
  report.failure = error.stack || String(error);
  await fs.mkdir(outputDir, {recursive: true});
  await fs.writeFile(path.join(outputDir, 'populated-browser-acceptance.json'), JSON.stringify(report, null, 2), 'utf8');
  console.error(error);
  process.exitCode = 1;
});
