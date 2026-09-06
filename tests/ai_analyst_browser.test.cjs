/* Real browser + HTTP API integration. Only OpenAI is mocked; no paid calls. */
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const { createHandler } = require('../backend/api/analyze-atbat.js');
const { createService } = require('../backend/lib/service.js');
const { analyze } = require('../backend/lib/openai.js');
const C = require('../backend/public/ai-contract.js');
const root = path.resolve(__dirname, '..');
const realFile = 'data/2026/03/27/2021038622.json';
let server, browser, base, handler, providerCalls = 0, sent;
function answer(data) {
  return { summary: '保存された球種・球速・結果から、この打席の流れを確認できます。',
    pitch_flow: data.pitches.map(p => ({ pitch: p.display_order,
      description: `${p.no ?? '表示順' + p.display_order}球目：${p.speed_kmh === null ? '球速未取得' : p.speed_kmh + 'km/h'} ${p.type || '球種未取得'}。配球図上では${p.derived.location || 'コース未取得'} → ${p.result || '結果未取得'}` })),
    points: ['球種の切り替わりは投球一覧でも確認できます。'], limitations: [C.LIMITATION, 'コースは配球図からの変換値です。'] };
}
function api(mode = 'ok') {
  providerCalls = 0;
  const service = createService({ analyzeImpl: data => analyze(data, { key: 'test-only-placeholder', fetchImpl: async (_, options) => {
    providerCalls++; sent = JSON.parse(options.body);
    if (mode === 'slow') await new Promise(r => setTimeout(r, 700));
    if (mode === 'error') return new Response('', { status: 500 });
    if (mode === 'rate') return new Response('', { status: 429 });
    if (mode === 'invalid') return new Response('{');
    return new Response(JSON.stringify({ status: 'completed', output: [{ type: 'message', content: [{ type: 'output_text', text: JSON.stringify(answer(data)) }] }] }));
  } }) });
  handler = createHandler({ serviceImpl: service, env: { OPENAI_API_KEY: 'test-only-placeholder', ALLOW_LOCALHOST: 'true' }, logger: { warn() {} } });
}
before(async () => {
  api();
  server = http.createServer((req, res) => {
    if (req.url.startsWith('/api/analyze-atbat')) { handler(req, res); return; }
    const name = decodeURIComponent(new URL(req.url, 'http://localhost').pathname).replace(/^\/npb-data\//, '');
    const file = path.resolve(root, name || 'index.html');
    if (!file.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
    fs.readFile(file, (error, contents) => {
      if (error) { res.writeHead(404).end(); return; }
      res.writeHead(200, { 'Content-Type': ({ '.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json', '.css': 'text/css', '.webp': 'image/webp' }[path.extname(file)] || 'application/octet-stream') + '; charset=utf-8' }); res.end(contents);
    });
  });
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  base = 'http://127.0.0.1:' + server.address().port;
  browser = await chromium.launch({ headless: true, ...(process.env.REPLAY_BROWSER_CHANNEL ? { channel: process.env.REPLAY_BROWSER_CHANNEL } : {}) });
});
after(async () => { await browser?.close(); await new Promise(r => server?.close(r)); });
async function pageFor(width = 1440) {
  const page = await browser.newPage({ viewport: { width, height: 1000 } }); page.setDefaultTimeout(8000);
  await page.route('**/*', route => route.request().url().startsWith(base) ? route.continue() : route.abort());
  await page.route('**/ai_analyst_config.js*', route => route.fulfill({ contentType: 'text/javascript', body: `window.NPB_AI_ANALYST_CONFIG={endpoint:${JSON.stringify(base + '/api/analyze-atbat')}};` }));
  return page;
}
async function load(page) {
  await page.goto(base + '/npb-data/pitch_replay.html?game=' + encodeURIComponent(realFile) + '&atbat=0110200');
  await page.waitForFunction(() => !document.getElementById('ai-analyze').disabled);
}
async function waitStatus(page, text) { await page.waitForFunction(text => document.getElementById('ai-status').textContent.includes(text), text); }
test('PC and 390px: replay → API → structured card, keyboard, cache, no overflow or secret', async () => {
  for (const width of [1440, 390]) {
    api('slow'); const page = await pageFor(width), errors = [], requests = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('request', r => { if (r.method() === 'POST') requests.push(r); });
    await load(page);
    await page.locator('#replay-play').click(); await page.locator('#replay-pause').click();
    await page.locator('#ai-analyze').focus(); await page.keyboard.press('Enter');
    await waitStatus(page, 'AIが配球を分析しています');
    assert.equal(await page.locator('#ai-analyze').isDisabled(), true);
    assert.equal(await page.locator('#ai-result').getAttribute('aria-busy'), 'true');
    assert.equal(await page.locator('#ai-spinner').isVisible(), true);
    await waitStatus(page, '表示しました');
    assert.equal(await page.locator('#ai-result section').count(), 4);
    assert.equal(await page.locator('#ai-result .ai-pitch-flow li').count(), 4);
    assert.match(await page.locator('#ai-result').innerText(), /心理/);
    assert.match(await page.locator('.replay-disclaimer').innerText(), /実際の投球軌道を完全再現/);
    assert.equal(requests.length, 1); assert.equal(providerCalls, 1);
    const body = requests[0].postDataJSON(); assert.equal(body.pitches.length, 4);
    assert.equal(body.game_id, '2021038622'); assert.equal(body.atbat_index, '0110200');
    assert.equal(requests[0].headers().authorization, undefined);
    assert.ok(Buffer.byteLength(requests[0].postData()) < C.MAX_BYTES);
    assert.equal(JSON.parse(sent.input[1].content).game_id, undefined);
    await page.locator('#ai-analyze').click(); await waitStatus(page, '保存済み');
    assert.equal(requests.length, 1); assert.equal(providerCalls, 1);
    assert.deepEqual(errors, []);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    assert.ok(await page.locator('#ai-card').evaluate(el => el.scrollWidth <= el.clientWidth));
    assert.equal(await page.locator('#ai-status').getAttribute('aria-live'), 'polite');
    await page.locator('#ai-analyze').focus(); await page.keyboard.press('Tab'); await page.keyboard.press('Shift+Tab');
    assert.notEqual(await page.locator('#ai-analyze').evaluate(el => getComputedStyle(el).outlineStyle), 'none');
    if (process.env.AI_QA_DIR) {
      fs.mkdirSync(process.env.AI_QA_DIR, { recursive: true });
      await page.screenshot({ path: path.join(process.env.AI_QA_DIR, `ai-page-${width}.png`), fullPage: true });
      await page.locator('#ai-card').screenshot({ path: path.join(process.env.AI_QA_DIR, `ai-card-${width}.png`) });
    }
    await page.close();
  }
});
test('unselected and no pitches never call API, including a programmatic click', async () => {
  api();
  for (const empty of [true, false]) {
    const page = await pageFor();
    await page.route('**/data/index.json', route => route.fulfill({ json: { files: empty ? [] : [realFile] } }));
    if (!empty) await page.route('**/' + realFile, route => route.fulfill({ json: { game_id: '2021038622', atbats: [{ index: '1', pitches: [] }] } }));
    await page.goto(base + '/npb-data/pitch_replay.html');
    await page.waitForFunction(() => window.getPlateAppearanceSummary && !document.getElementById('replay-status').textContent.includes('読み込んで'));
    await page.locator('#ai-analyze').evaluate(el => el.dispatchEvent(new MouseEvent('click')));
    await waitStatus(page, empty ? '打席を選択' : '投球データはありません');
    assert.equal(providerCalls, 0); assert.equal(await page.locator('#ai-analyze').isDisabled(), true);
    await page.close();
  }
});
test('provider failure/rate limit/invalid JSON and transport failure show recoverable errors', async () => {
  for (const mode of ['error', 'rate', 'invalid', 'transport', 'badjson']) {
    api(mode); const page = await pageFor();
    if (mode === 'transport') await page.route('**/api/analyze-atbat', route => route.abort());
    if (mode === 'badjson') await page.route('**/api/analyze-atbat', route => route.fulfill({ contentType: 'application/json', body: '{' }));
    await load(page); await page.locator('#ai-analyze').click();
    await waitStatus(page, mode === 'rate' ? '上限' : '取得できませんでした');
    assert.equal(await page.locator('#ai-analyze').isEnabled(), true); assert.equal(await page.locator('#ai-spinner').isVisible(), false);
    assert.equal(await page.locator('#ai-result section').count(), 0); await page.close();
  }
});
test('double submission and switching at-bats never display an old result', async () => {
  api('slow'); const page = await pageFor(); await load(page);
  await page.locator('#ai-analyze').evaluate(el => { el.click(); el.dispatchEvent(new MouseEvent('click')); });
  await waitStatus(page, '分析しています');
  await page.locator('#replay-atbat').selectOption('2'); await waitStatus(page, '選択した1打席');
  await page.waitForTimeout(900);
  assert.equal(providerCalls, 1); assert.equal(await page.locator('#ai-result section').count(), 0);
  assert.equal(await page.locator('#ai-analyze').isEnabled(), true); await page.close();
});
test('AI markup is literal text, never an HTML element or executable event', async () => {
  api(); const page = await pageFor(390);
  await page.route('**/api/analyze-atbat', route => {
    const data = route.request().postDataJSON(), result = answer(data);
    result.summary = '<img src=x onerror="window.aiXSS=true">'; result.points = ['<script>window.aiXSS=true</script>', 'a'.repeat(280)];
    return route.fulfill({ json: { schemaVersion: 1, analysis: result, cached: false } });
  });
  await load(page); await page.locator('#ai-analyze').click(); await waitStatus(page, '表示しました');
  assert.match(await page.locator('#ai-result').textContent(), /<img/);
  assert.equal(await page.locator('#ai-result img, #ai-result script').count(), 0);
  assert.equal(await page.evaluate(() => window.aiXSS), undefined);
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)); await page.close();
});
