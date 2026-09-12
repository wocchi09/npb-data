'use strict';
const { createHash } = require('node:crypto');
const { analyze, AnalystError, DEFAULT_MODEL } = require('./openai.js');
const { PROMPT_VERSION } = require('./prompt.js');
const TTL_MS = 3600000;
function createService({ analyzeImpl = analyze, now = Date.now } = {}) {
  const cache = new Map(), pending = new Map(), clients = new Map();
  let windowStart = now(), calls = 0;
  function rateLimit(ip) {
    const time = now();
    for (const [k, v] of clients) if (time - v.start >= 60000) clients.delete(k);
    const state = clients.get(ip) || { start: time, last: -Infinity, count: 0 };
    if (time - state.last < 5000 || state.count >= 6 || (!clients.has(ip) && clients.size >= 2000)) throw new AnalystError('RATE_LIMITED', 429);
    state.count++; state.last = time; clients.set(ip, state);
  }
  async function run(data, ip, env) {
    rateLimit(ip);
    if (!env.OPENAI_API_KEY?.trim()) throw new AnalystError('NOT_CONFIGURED', 503);
    const model = env.OPENAI_MODEL?.trim() || DEFAULT_MODEL;
    const hash = createHash('sha256').update(PROMPT_VERSION + model + JSON.stringify(data)).digest('hex');
    const key = data.game_id + ':' + data.atbat_index + ':' + hash;
    for (const [k, v] of cache) if (v.expires <= now()) cache.delete(k);
    if (cache.has(key)) return { analysis: cache.get(key).analysis, cached: true };
    if (pending.has(key)) return { analysis: await pending.get(key), cached: true };
    if (now() - windowStart >= TTL_MS) { windowStart = now(); calls = 0; }
    // Per warm instance circuit breaker. See docs for distributed deployment limits.
    if (calls >= 60 || pending.size >= 4) throw new AnalystError('RATE_LIMITED', 429);
    calls++;
    const promise = Promise.resolve().then(() => analyzeImpl(data, { key: env.OPENAI_API_KEY, model }));
    pending.set(key, promise);
    try {
      const analysis = await promise;
      cache.set(key, { analysis, expires: now() + TTL_MS });
      if (cache.size > 256) cache.delete(cache.keys().next().value);
      return { analysis, cached: false };
    } finally { pending.delete(key); }
  }
  return { run };
}
module.exports = { createService };
