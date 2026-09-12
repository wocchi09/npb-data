'use strict';
const C = require('../public/ai-contract.js');
const { SYSTEM_PROMPT, modelInput } = require('./prompt.js');
const DEFAULT_MODEL = 'gpt-4.1-mini-2025-04-14';
const MAX_OUTPUT_TOKENS = 3500, TIMEOUT_MS = 25000;
class AnalystError extends Error {
  constructor(code, status = 502) { super(code); this.code = code; this.status = status; }
}
async function analyze(data, { key, model = DEFAULT_MODEL, fetchImpl = fetch, timeoutMs = TIMEOUT_MS }) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetchImpl('https://api.openai.com/v1/responses', {
      method: 'POST', signal: controller.signal,
      headers: { Authorization: 'Bearer ' + key, 'Content-Type': 'application/json' },
      body: JSON.stringify({ model, store: false, max_output_tokens: MAX_OUTPUT_TOKENS,
        input: [{ role: 'system', content: SYSTEM_PROMPT }, { role: 'user', content: JSON.stringify(modelInput(data)) }],
        text: { format: { type: 'json_schema', name: 'atbat_analysis', strict: true, schema: C.responseSchema } } })
    });
    if (!response.ok) throw new AnalystError(response.status === 429 ? 'RATE_LIMITED' : 'OPENAI_ERROR', response.status === 429 ? 429 : 502);
    // Bound the provider response too; include body reading in the same timeout.
    const reader = response.body.getReader(), chunks = []; let size = 0;
    try {
      while (true) {
        const { done, value } = await reader.read(); if (done) break;
        size += value.byteLength;
        if (size > 131072) { await reader.cancel(); throw new AnalystError('INVALID_RESPONSE'); }
        chunks.push(Buffer.from(value));
      }
    } finally { reader.releaseLock(); }
    const body = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    if (body.status !== 'completed') throw new AnalystError('INCOMPLETE_RESPONSE');
    const contents = (body.output || []).filter(x => x.type === 'message').flatMap(x => x.content || []);
    if (contents.some(x => x.type === 'refusal')) throw new AnalystError('REFUSED_RESPONSE');
    const result = JSON.parse(contents.filter(x => x.type === 'output_text').map(x => x.text).join(''));
    if (!C.validResponse(result, data.pitches.length)) throw new AnalystError('INVALID_RESPONSE');
    // Always enforce the limitation even if the generated text omits it.
    result.limitations = [C.LIMITATION, ...result.limitations.filter(x => x !== C.LIMITATION)].slice(0, 6);
    return result;
  } catch (error) {
    if (controller.signal.aborted) throw new AnalystError('TIMEOUT', 504);
    if (error instanceof AnalystError) throw error;
    throw new AnalystError(error instanceof SyntaxError ? 'INVALID_RESPONSE' : 'UPSTREAM_FAILURE');
  } finally { clearTimeout(timer); }
}
module.exports = { analyze, AnalystError, DEFAULT_MODEL, MAX_OUTPUT_TOKENS };
