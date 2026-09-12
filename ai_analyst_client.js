(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(require('./backend/public/ai-contract.js'));
  else root.AIAnalystClient = factory(root.AIAnalystContract);
})(typeof globalThis !== 'undefined' ? globalThis : this, function (C) {
  'use strict';
  function endpointURL(endpoint) {
    const url = new URL(endpoint);
    const local = ['localhost', '127.0.0.1'].includes(url.hostname);
    if ((url.protocol !== 'https:' && !(local && url.protocol === 'http:')) || url.username || url.password || url.search || url.hash) throw new Error('NOT_CONFIGURED');
    return url.href;
  }
  function createClient({ endpoint, fetchImpl = fetch, now = Date.now, timeoutMs = 28000, cooldownMs = 5000 } = {}) {
    const cache = new Map(); let busy = false, nextAllowed = 0;
    async function analyze(payload, signal) {
      if (!C.validRequest(payload)) throw new Error('INVALID_REQUEST');
      const key = JSON.stringify(payload), time = now();
      for (const [k, v] of cache) if (v.expires <= time) cache.delete(k);
      if (signal?.aborted) throw new Error('CANCELLED');
      if (cache.has(key)) return { analysis: cache.get(key).analysis, cached: true };
      if (busy || time < nextAllowed) throw new Error('RATE_LIMITED');
      let url;
      try { url = endpointURL(endpoint); } catch { throw new Error('NOT_CONFIGURED'); }
      busy = true; nextAllowed = time + cooldownMs;
      const controller = new AbortController(), cancel = () => controller.abort();
      signal?.addEventListener('abort', cancel, { once: true });
      const timer = setTimeout(cancel, timeoutMs);
      try {
        const response = await fetchImpl(url, { method: 'POST', signal: controller.signal, credentials: 'omit',
          headers: { 'Content-Type': 'application/json' }, body: key });
        if (!response.ok) {
          if (response.status === 429) nextAllowed = Math.max(nextAllowed, now() + 60000);
          throw new Error(response.status === 429 ? 'RATE_LIMITED' : 'API_FAILURE');
        }
        if (!/application\/json/i.test(response.headers.get('content-type') || '')) throw new Error('INVALID_RESPONSE');
        const reader = response.body.getReader(), decoder = new TextDecoder(); let raw = '', bytes = 0;
        try {
          while (true) {
            const { done, value } = await reader.read(); if (done) break;
            bytes += value.byteLength;
            if (bytes > 65536) { await reader.cancel(); throw new Error('INVALID_RESPONSE'); }
            raw += decoder.decode(value, { stream: true });
          }
          raw += decoder.decode();
        } finally { reader.releaseLock(); }
        const result = JSON.parse(raw);
        if (result.schemaVersion !== 1 || !C.validResponse(result.analysis, payload.pitches.length)) throw new Error('INVALID_RESPONSE');
        if (controller.signal.aborted) throw new Error('CANCELLED');
        cache.set(key, { analysis: result.analysis, expires: now() + 3600000 });
        if (cache.size > 64) cache.delete(cache.keys().next().value);
        return { analysis: result.analysis, cached: !!result.cached };
      } catch (error) {
        if (controller.signal.aborted) throw new Error(signal?.aborted ? 'CANCELLED' : 'TIMEOUT');
        if (error instanceof SyntaxError) throw new Error('INVALID_RESPONSE');
        // Never surface arbitrary response bodies or remote error text.
        const codes = ['RATE_LIMITED', 'API_FAILURE', 'INVALID_RESPONSE'];
        throw new Error(codes.includes(error.message) ? error.message : 'NETWORK_FAILURE');
      } finally {
        clearTimeout(timer); signal?.removeEventListener('abort', cancel); busy = false;
      }
    }
    return { analyze };
  }
  return { createClient, endpointURL };
});
