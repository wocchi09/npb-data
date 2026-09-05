/* Optional browser suite: npm install --no-save --package-lock=false playwright
 * REPLAY_BROWSER_CHANNEL=chrome node --test tests/pitch_replay_browser.test.cjs
 * Set REPLAY_QA_DIR to retain desktop/mobile screenshots outside the repository. */
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
let server, browser, base;
const realFile = 'data/2026/03/27/2021038622.json';
const fixtureFile = 'data/2026/01/01/1.json';
const fixture = pitches => ({ game_id: '1', game_date: '2026-01-01', atbats: [{ index: '0110100', inning: 1,
  top_bottom: '表', pitcher: { name: 'テスト投手', player_id: '1', hand: '右投' },
  batter: { name: 'テスト打者', hand: '左打' }, count: { ball: 0, strike: 2, out: 1 }, result_summary: '空振り三振', pitches }] });
const pitch = (i, changes = {}) => ({ no: i, type: 'スライダー', speed_kmh: 140, result: 'ファウル',
  course: { left_px: 30, top_px: 32, label: '真ん中・真ん中' }, ...changes });
const waitText = (page, id, value) => page.waitForFunction(({ id, value }) => document.getElementById(id)?.textContent.includes(value), { id: 'replay-' + id, value });
async function openPage() {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(10000);
  await page.route('**/*', route => route.request().url().startsWith(base) ? route.continue() : route.abort());
  return page;
}
async function loadFixture(page, game = fixture([pitch(1)])) {
  await page.route('**/data/index.json', route => route.fulfill({ json: { files: [fixtureFile] } }));
  await page.route('**/' + fixtureFile, route => route.fulfill({ json: game }));
  await page.goto(base + 'pitch_replay.html');
  await waitText(page, 'status', game.atbats?.length ? '読み込みました' : '打席データはありません');
}
before(async () => {
  server = http.createServer((request, response) => {
    const name = decodeURIComponent(new URL(request.url, 'http://localhost').pathname).replace(/^\/npb-data\//, '');
    const file = path.resolve(root, name || 'index.html');
    if (!file.startsWith(root + path.sep)) { response.writeHead(403).end(); return; }
    fs.readFile(file, (error, contents) => {
      if (error) { response.writeHead(404).end(); return; }
      const mime = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json' }[path.extname(file)] || 'application/octet-stream';
      response.writeHead(200, { 'Content-Type': mime + '; charset=utf-8' }); response.end(contents);
    });
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  base = 'http://127.0.0.1:' + server.address().port + '/npb-data/';
  browser = await chromium.launch({ headless: true, ...(process.env.REPLAY_BROWSER_CHANNEL ? { channel: process.env.REPLAY_BROWSER_CHANNEL } : {}) });
});
after(async () => { await browser?.close(); await new Promise(resolve => server?.close(resolve)); });

test('real game / Pages subpath: desktop, mobile, exact deep link, raw JSON export', async () => {
  const page = await openPage(), errors = [], requests = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => requests.push(request.url()));
  await page.goto(base + 'pitch_replay.html?game=' + encodeURIComponent(realFile) + '&atbat=0110200');
  await page.locator('#replay-content').waitFor({ state: 'visible' });
  assert.match(await page.locator('#replay-batter').innerText(), /中野/);
  assert.match(await page.locator('#replay-pitcher').innerText(), /竹丸/);
  assert.match(await page.locator('#replay-batter-side').textContent(), /左打者/);
  assert.equal(await page.locator('#replay-pitches tr').count(), 4);
  const stage = await page.locator('.replay-stage-card').boundingBox(), info = await page.locator('.replay-info').boundingBox();
  assert.ok(stage.x < info.x && Math.abs(stage.y - info.y) < 3);
  await page.locator('#replay-pitches [data-pitch="2"]').click();
  assert.equal(await page.locator('#replay-marks > g').count(), 2);
  await page.locator('#replay-play').click(); await page.waitForTimeout(450); await page.locator('#replay-pause').click();
  assert.equal(await page.locator('#replay-ball').isVisible(), true);
  if (process.env.REPLAY_QA_DIR) {
    fs.mkdirSync(process.env.REPLAY_QA_DIR, { recursive: true });
    await page.screenshot({ path: path.join(process.env.REPLAY_QA_DIR, 'replay-desktop.png'), fullPage: true });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  const mobileStage = await page.locator('.replay-stage-card').boundingBox(), mobileInfo = await page.locator('.replay-info').boundingBox();
  assert.ok(mobileInfo.y >= mobileStage.y + mobileStage.height);
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  if (process.env.REPLAY_QA_DIR) await page.screenshot({ path: path.join(process.env.REPLAY_QA_DIR, 'replay-mobile.png'), fullPage: true });
  await page.locator('.replay-provenance summary').click();
  const downloaded = page.waitForEvent('download'); await page.locator('#replay-export').click();
  const download = await downloaded, summary = JSON.parse(fs.readFileSync(await download.path()));
  assert.equal(summary.pitches[0].speed, 142); assert.equal(summary.source.index, '0110200');
  assert.equal(summary.recordedCount.out, 2); assert.equal(summary.aiInterpretation, null);
  assert.ok(requests.filter(url => /\/\d+\.json$/.test(url)).length <= 1);
  assert.deepEqual(errors, []); await page.close();
});
test('play/pause/resume, speed, previous/next, restart and active row', async () => {
  const page = await openPage(); await loadFixture(page, fixture([pitch(1), pitch(2), pitch(3, { result: '空振り三振' })]));
  await page.locator('#replay-play').click(); await page.waitForTimeout(250); await page.locator('#replay-pause').click();
  const position = await page.locator('#replay-ball').getAttribute('cx');
  await page.waitForTimeout(180); assert.equal(await page.locator('#replay-ball').getAttribute('cx'), position);
  assert.match(await page.locator('#replay-progress').innerText(), /一時停止/);
  for (const value of ['0.5', '1', '1.5', '2']) { await page.locator('#replay-speed').selectOption(value); assert.equal(await page.locator('#replay-speed').inputValue(), value); }
  await page.locator('#replay-play').click(); await waitText(page, 'progress', '1球の再生が完了');
  assert.equal(await page.locator('#replay-marks > g').count(), 1);
  await page.locator('#replay-next').click(); assert.equal(await page.locator('#replay-number').innerText(), '2 / 3');
  assert.equal(await page.locator('#replay-pitches tr[aria-current="true"] [data-pitch]').getAttribute('data-pitch'), '1');
  await page.locator('#replay-prev').click(); assert.equal(await page.locator('#replay-number').innerText(), '1 / 3');
  await page.locator('#replay-restart').click(); await waitText(page, 'progress', '再生中');
  assert.equal(await page.locator('#replay-marks > g').count(), 0);
  await page.close();
});
test('continuous 12-pitch at-bat, collision labels and complete result', async () => {
  const page = await openPage(); await loadFixture(page, fixture(Array.from({ length: 12 }, (_, i) => pitch(i + 1, i === 11 ? { result: '空振り三振' } : {}))));
  await page.locator('#replay-mode').selectOption('continuous'); await page.locator('#replay-speed').selectOption('2');
  await page.locator('#replay-play').click();
  await page.waitForFunction(() => document.getElementById('replay-progress').textContent.includes('打席の再生が完了'), null, { timeout: 20000 });
  assert.equal(await page.locator('#replay-marks > g').count(), 12);
  const labels = await page.locator('#replay-marks text').evaluateAll(nodes => nodes.map(n => n.getAttribute('x') + ',' + n.getAttribute('y')));
  assert.equal(new Set(labels).size, 12);
  assert.match(await page.locator('#replay-result').innerText(), /空振り三振/);
  assert.equal(await page.locator('#replay-bs').innerText(), '0 / 3');
  await page.close();
});
test('missing type/speed/course, one pitch, and empty at-bat preserve absence', async () => {
  const page = await openPage(); await loadFixture(page, fixture([{ no: 1 }]));
  assert.match(await page.locator('#replay-current').innerText(), /球速未取得/);
  assert.equal(await page.locator('#replay-missing-course').isVisible(), true);
  await page.locator('#replay-speed').selectOption('2'); await page.locator('#replay-play').click();
  await waitText(page, 'progress', '打席の再生が完了');
  assert.equal(await page.locator('#replay-marks > g').count(), 0);
  assert.equal(await page.locator('#replay-ball').isVisible(), false);
  assert.equal(await page.locator('#replay-bs').innerText(), '未取得 / 未取得');
  await page.route('**/' + fixtureFile, route => route.fulfill({ json: fixture([]) }));
  await page.reload(); await waitText(page, 'status', '投球データはありません');
  assert.equal(await page.locator('#replay-play').isDisabled(), true);
  assert.equal(await page.locator('#replay-number').innerText(), '0 / 0'); await page.close();
});
test('empty index, fetch failure, retry and invalid deep link are explicit', async () => {
  const page = await openPage();
  await page.route('**/data/index.json', route => route.fulfill({ json: { files: [] } }));
  await page.goto(base + 'pitch_replay.html'); await waitText(page, 'status', '試合データはありません');
  assert.equal(await page.locator('#replay-content').isVisible(), false);
  await page.route('**/data/index.json', route => route.fulfill({ status: 500, body: '' }));
  await page.reload(); await page.locator('#replay-retry').waitFor({ state: 'visible' });
  await page.route('**/data/index.json', route => route.fulfill({ json: { files: [realFile] } }));
  await page.locator('#replay-retry').click(); await page.locator('#replay-content').waitFor({ state: 'visible' });
  await page.goto(base + 'pitch_replay.html?game=../../secret.json'); await waitText(page, 'status', '指定された試合');
  assert.equal(await page.locator('#replay-content').isVisible(), false); await page.close();
});
test('late responses cannot replace a newly selected game; summary is optional', async () => {
  const page = await openPage(), other = fixtureFile.replace('/1.json', '/2.json');
  await page.route('**/data/index.json', route => route.fulfill({ json: { files: [fixtureFile, other] } }));
  await page.route('**/' + fixtureFile, async route => { await new Promise(resolve => setTimeout(resolve, 400)); await route.fulfill({ json: fixture([pitch(1)]) }).catch(() => {}); });
  const second = fixture([pitch(1)]); second.game_id = '2'; second.atbats[0].batter.name = '選択した打者';
  await page.route('**/' + other, route => route.fulfill({ json: second }));
  await page.goto(base + 'pitch_replay.html'); await page.locator('#replay-game').selectOption(other);
  await waitText(page, 'batter', '選択した打者'); await page.waitForTimeout(500);
  assert.match(await page.locator('#replay-batter').innerText(), /選択した打者/); await page.close();
});
test('reduced motion and keyboard controls remain usable', async () => {
  const page = await openPage(); await page.emulateMedia({ reducedMotion: 'reduce' }); await loadFixture(page);
  await page.locator('#replay-speed').selectOption('2');
  await page.locator('#replay-play').focus(); await page.keyboard.press('Enter');
  assert.equal(await page.locator('#replay-ball').isVisible(), false);
  await waitText(page, 'progress', '打席の再生が完了');
  assert.equal(await page.locator('#replay-marks > g').count(), 1); await page.close();
});
test('ANALYST LAB pitch filter and existing scoreboard link resolve to the correct data', async () => {
  const page = await openPage(); await page.goto(base + 'analyst_lab.html');
  await page.locator('[data-tab="sequences"]').click();
  const link = page.locator('a[href^="pitch_replay.html?"]'); await link.waitFor();
  const href = await link.getAttribute('href'); assert.match(href, /pitcher=/);
  await link.click(); await page.locator('#replay-content').waitFor({ state: 'visible' });
  const key = new URL(page.url()).searchParams.get('pitcher');
  assert.equal(await page.evaluate(() => getPlateAppearanceSummary().pitcher.key), key);
  await page.locator('#replay-filter button').click(); await page.waitForFunction(() => !new URL(location.href).searchParams.has('pitcher'));
  await page.goto(base + 'index.html');
  // Reuse the existing game's loader/rendering; run against actual stored JSON.
  await page.evaluate(async file => { const response = await fetch(file); curGame = await response.json(); dp.value = curGame.game_date; }, realFile);
  await page.evaluate(() => { const host = document.createElement('div'); host.id = 'tabbody'; document.body.append(host); renderPitches(); });
  const replayLink = page.locator('#tabbody a[href^="pitch_replay.html?"]').first();
  await replayLink.waitFor(); const url = new URL(await replayLink.getAttribute('href'), base);
  assert.equal(url.searchParams.get('game'), realFile); assert.equal(url.searchParams.get('atbat'), '0110100');
  await page.goto(url.href); await page.locator('#replay-content').waitFor({ state: 'visible' });
  assert.equal(await page.evaluate(() => getPlateAppearanceSummary().source.index), '0110100');
  await page.close();
});
