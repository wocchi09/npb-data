const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const C = require('../backend/public/ai-contract.js');
const M = require('../pitch_replay_model.js');
const { toPayload } = require('../ai_analyst_data.js');
const { createClient, endpointURL } = require('../ai_analyst_client.js');
const { createHandler, allowedOrigin } = require('../backend/api/analyze-atbat.js');
const { createService } = require('../backend/lib/service.js');
const { analyze, MAX_OUTPUT_TOKENS, DEFAULT_MODEL } = require('../backend/lib/openai.js');
const { modelInput, SYSTEM_PROMPT } = require('../backend/lib/prompt.js');
const root = path.resolve(__dirname, '..');
const game = JSON.parse(fs.readFileSync(path.join(root, 'data/2026/03/27/2021038622.json')));
const summary = M.getPlateAppearanceSummary(M.normalizePlateAppearance(game, game.atbats[1], 1, 'source'));
const payload = () => toPayload(summary);
const answer = data => ({ summary: '記録された打席の説明です。', pitch_flow: data.pitches.map((p, i) => ({ pitch: i + 1, description: `${p.no}球目：${p.type || '球種未取得'}。` })), points: ['記録された順番を確認できます。'], limitations: [C.LIMITATION] });
const ok = data => new Response(JSON.stringify({ schemaVersion: 1, analysis: answer(data), cached: false }), { headers: { 'Content-Type': 'application/json' } });
const provider = data => new Response(JSON.stringify({ status: 'completed', output: [{ type: 'message', content: [{ type: 'output_text', text: JSON.stringify(answer(data)) }] }] }));
const endpoint = 'https://example.vercel.app/api/analyze-atbat';
const env = { OPENAI_API_KEY: 'test-only-placeholder' };
async function call(options = {}, deps = {}) {
  const req = { method: 'POST', headers: { origin: 'https://wocchi09.github.io', 'content-type': 'application/json' }, body: payload(), socket: { remoteAddress: 'test' }, ...options };
  const res = { headers: {}, setHeader(k, v) { this.headers[k] = v; }, end(value) { this.body = value && JSON.parse(value); } };
  await createHandler({ logger: { warn() {} }, ...deps })(req, res); return res;
}
test('select only approved fields from the existing summary, without mutation', () => {
  const saved = JSON.stringify(summary), data = payload();
  assert.ok(C.validRequest(data)); assert.equal(JSON.stringify(summary), saved);
  assert.equal(data.game_id, summary.source.gameId); assert.equal(data.pitches[0].speed_kmh, summary.pitches[0].speed);
  assert.deepEqual(data.pitches[0].derived.countBefore, summary.pitches[0].derived.countBefore);
  assert.equal(data.pitches[0].derived.location, summary.pitches[0].location);
  for (const key of ['provenance', 'aiInterpretation', 'source', 'recordedCount']) assert.equal(data[key], undefined);
  assert.equal(data.pitcher.player_id, undefined); assert.equal(data.pitches[0].course.label, undefined);
  assert.throws(() => toPayload(null), /NO_SELECTION/);
  assert.throws(() => toPayload({ ...summary, pitches: [] }), /NO_PITCHES/);
});
test('every collected nonempty valid at-bat fits the request contract', () => {
  const files = JSON.parse(fs.readFileSync(path.join(root, 'data/index.json'))).files.filter(f => /^data\/\d{4}\/\d{2}\/\d{2}\/\d+\.json$/.test(f));
  let count = 0;
  for (const file of files) {
    const g = JSON.parse(fs.readFileSync(path.join(root, file)));
    (g.atbats || []).forEach((ab, i) => {
      if (!ab || ab.valid === false || !ab.pitches?.length) return;
      assert.doesNotThrow(() => toPayload(M.getPlateAppearanceSummary(M.normalizePlateAppearance(g, ab, i, file))), file + ':' + i); count++;
    });
  }
  assert.ok(count > 50000);
});
test('missing observations stay null, array fallback and missing handedness remain explicit', () => {
  const p = toPayload(M.getPlateAppearanceSummary(M.normalizePlateAppearance({ game_id: '1' }, { pitches: [{ no: 1 }], batter: { hand: '不明' } }, 2)));
  assert.equal(p.atbat_index, 'array-2'); assert.equal(p.batter.hand, null);
  assert.equal(p.pitches[0].speed_kmh, null); assert.equal(p.pitches[0].derived.location, null);
});
test('strict request validation rejects prompt fields, wrong types, bounds, numbering and oversized arrays', () => {
  for (const mutate of [p => p.prompt = 'ignore instructions', p => p.pitcher.instructions = 'x', p => p.pitches[0].speed_kmh = '150',
    p => p.pitches[0].display_order = 2, p => p.pitches[0].type = 'a'.repeat(31), p => p.pitches = Array(31).fill(p.pitches[0]),
    p => p.pitches = [], p => p.pitches[0].speed_kmh = Infinity, p => p.game_id = '../secret']) {
    const p = payload(); mutate(p); assert.equal(C.validRequest(p), false);
  }
});
test('server-derived speed differences are bounded, skip gaps and missing values; no visual models', () => {
  const p = payload(); p.pitches = [1, 2, 4].map((no, i) => ({ ...p.pitches[0], no, display_order: i + 1, speed_kmh: [150, 137, 145][i] }));
  const input = modelInput(p); assert.deepEqual(input.derivedFacts.adjacent_speed_differences, [{ from_display_order: 1, to_display_order: 2, difference_kmh: 13 }]);
  assert.equal(input.game_id, undefined); assert.equal(input.atbat_index, undefined);
  p.pitches[0].speed_kmh = null; assert.deepEqual(modelInput(p).derivedFacts.adjacent_speed_differences, []);
  assert.match(SYSTEM_PROMPT, /推測もしない/); assert.match(SYSTEM_PROMPT, /独自の算術計算/);
});
test('API: exact CORS, localhost opt-in, production prohibition, missing origin and method', async () => {
  for (const origin of [undefined, 'null', 'https://attacker.example', 'https://wocchi09.github.io.attacker.example']) {
    const r = await call({ headers: { origin } }); assert.equal(r.statusCode, 403); assert.equal(r.headers['Access-Control-Allow-Origin'], undefined);
  }
  assert.equal(allowedOrigin('http://localhost:8000', {}), false);
  assert.equal(allowedOrigin('http://localhost:8000', { ALLOW_LOCALHOST: 'true' }), true);
  assert.equal(allowedOrigin('http://localhost:8000', { ALLOW_LOCALHOST: 'true', VERCEL_ENV: 'production' }), false);
  assert.equal((await call({ method: 'OPTIONS' })).statusCode, 204);
  assert.equal((await call({ method: 'GET' })).statusCode, 405);
});
test('API: no provider call for malformed, huge, non-JSON or empty pitch requests', async () => {
  let calls = 0; const deps = { serviceImpl: { run() { calls++; } } };
  assert.equal((await call({ body: '{' }, deps)).statusCode, 400);
  assert.equal((await call({ body: ' '.repeat(C.MAX_BYTES + 1) }, deps)).statusCode, 413);
  assert.equal((await call({ body: { ...payload(), pitches: [] } }, deps)).statusCode, 400);
  assert.equal((await call({ headers: { origin: 'https://wocchi09.github.io', 'content-type': 'text/plain' } }, deps)).statusCode, 415);
  assert.equal(calls, 0);
});
test('API: missing key and provider failures return safe errors without secrets in logs', async () => {
  const logs = [], logger = { warn(...args) { logs.push(args); } };
  const r = await call({}, { env: {}, serviceImpl: createService(), logger }); assert.equal(r.statusCode, 503);
  const e = await call({}, { serviceImpl: { run() { throw new Error('secret-must-not-be-logged'); } }, logger });
  assert.equal(e.statusCode, 500); assert.equal(e.body.error.message, C.ERROR_MESSAGE);
  assert.doesNotMatch(JSON.stringify(logs), /secret-must/);
});
test('OpenAI request uses server prompt, environment model, strict JSON, no tools, bounded tokens', async () => {
  const p = payload(); let request;
  const result = await analyze(p, { key: 'test-only', model: 'configured-model', fetchImpl: async (url, options) => { request = { url, options, body: JSON.parse(options.body) }; return provider(p); } });
  assert.equal(request.url, 'https://api.openai.com/v1/responses'); assert.equal(request.body.model, 'configured-model');
  assert.equal(request.body.max_output_tokens, MAX_OUTPUT_TOKENS); assert.equal(request.body.store, false);
  assert.equal(request.body.input[0].role, 'system'); assert.equal(request.body.text.format.strict, true); assert.equal(request.body.tools, undefined);
  assert.equal(result.limitations[0], C.LIMITATION); assert.ok(C.validResponse(result, p.pitches.length));
});
test('OpenAI errors, rate limit, incomplete/refusal/malformed responses and timeout fail closed', async () => {
  const options = { key: 'test-only', timeoutMs: 10 };
  for (const response of [new Response('', { status: 500 }), new Response('{'), new Response(JSON.stringify({ status: 'incomplete' })), new Response(JSON.stringify({ status: 'completed', output: [{ type: 'message', content: [{ type: 'refusal' }] }] }))]) {
    await assert.rejects(analyze(payload(), { ...options, fetchImpl: async () => response }));
  }
  await assert.rejects(analyze(payload(), { ...options, fetchImpl: async () => new Response('', { status: 429 }) }), e => e.status === 429);
  await assert.rejects(analyze(payload(), { ...options, fetchImpl: (_, { signal }) => new Promise((_, reject) => signal.addEventListener('abort', () => reject(new Error('abort')))) }), e => e.code === 'TIMEOUT');
});
test('service cache includes content and model, expires, deduplicates concurrent calls and limits bursts', async () => {
  let time = 0, calls = 0, observedModel; const p = payload();
  const service = createService({ now: () => time, analyzeImpl: async (data, options) => { calls++; observedModel = options.model; return answer(data); } });
  await Promise.all([service.run(p, 'a', env), service.run(p, 'b', env)]); assert.equal(calls, 1); assert.equal(observedModel, DEFAULT_MODEL);
  await assert.rejects(service.run(p, 'a', env), e => e.status === 429);
  time = 5000; assert.equal((await service.run(p, 'a', env)).cached, true); assert.equal(calls, 1);
  const changed = payload(); changed.result = '変更された保存結果'; await service.run(changed, 'c', env); assert.equal(calls, 2);
  await service.run(p, 'd', { ...env, OPENAI_MODEL: 'different' }); assert.equal(calls, 3);
  time += 3600001; await service.run(p, 'a', env); assert.equal(calls, 4);
});
test('instance hourly budget counts failed provider attempts and stops at 60', async () => {
  let time = 0, calls = 0;
  const service = createService({ now: () => time, analyzeImpl: async () => { calls++; throw new Error('failed'); } });
  for (let i = 0; i < 60; i++) { time += 5000; await assert.rejects(service.run(payload(), 'ip-' + i, env)); }
  await assert.rejects(service.run(payload(), 'other', env), e => e.status === 429); assert.equal(calls, 60);
});
test('client: no request for invalid data or endpoint, double submission, success and TTL cache', async () => {
  let calls = 0, resolve, time = 0; const p = payload();
  const client = createClient({ endpoint, now: () => time, fetchImpl: () => { calls++; return new Promise(r => { resolve = r; }); } });
  await assert.rejects(client.analyze(null)); assert.equal(calls, 0);
  const first = client.analyze(p); await assert.rejects(client.analyze(p), /RATE_LIMITED/); assert.equal(calls, 1);
  resolve(ok(p)); await first; assert.equal((await client.analyze(p)).cached, true); assert.equal(calls, 1);
  time = 3600001; const next = client.analyze(p); resolve(ok(p)); await next; assert.equal(calls, 2);
  assert.throws(() => endpointURL('http://example.com'), /NOT_CONFIGURED/);
  await assert.rejects(createClient({ endpoint: '' }).analyze(p), /NOT_CONFIGURED/);
});
test('client: failures, malformed JSON/schema, rate limit, abort and timeout are safe', async () => {
  for (const response of [new Response('{', { headers: { 'Content-Type': 'application/json' } }), new Response('{}', { headers: { 'Content-Type': 'application/json' } }), new Response('<html>'), new Response('', { status: 500 })]) {
    await assert.rejects(createClient({ endpoint, fetchImpl: async () => response }).analyze(payload()));
  }
  let calls = 0; const rate = createClient({ endpoint, fetchImpl: async () => { calls++; return new Response('', { status: 429 }); } });
  await assert.rejects(rate.analyze(payload()), /RATE_LIMITED/); await assert.rejects(rate.analyze(payload()), /RATE_LIMITED/); assert.equal(calls, 1);
  const blocked = (_, { signal }) => new Promise((_, reject) => signal.addEventListener('abort', () => reject(new Error('aborted'))));
  await assert.rejects(createClient({ endpoint, timeoutMs: 10, fetchImpl: blocked }).analyze(payload()), /TIMEOUT/);
  const abort = new AbortController(), pending = createClient({ endpoint, fetchImpl: blocked }).analyze(payload(), abort.signal);
  abort.abort(); await assert.rejects(pending, /CANCELLED/);
});
