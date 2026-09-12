'use strict';
const C = require('../public/ai-contract.js');
const { createService } = require('../lib/service.js');
const { AnalystError } = require('../lib/openai.js');
const service = createService();
const ORIGIN = 'https://wocchi09.github.io';
function allowedOrigin(origin, env) {
  return origin === ORIGIN || (env.ALLOW_LOCALHOST === 'true' && env.VERCEL_ENV !== 'production'
    && /^http:\/\/(localhost|127\.0\.0\.1)(:\d{1,5})?$/.test(origin || ''));
}
async function readBody(req) {
  if (Number(req.headers['content-length']) > C.MAX_BYTES) throw new AnalystError('PAYLOAD_TOO_LARGE', 413);
  // Vercel supplies a parsed body; the local server uses a bounded stream.
  if (req.body !== undefined) {
    const raw = typeof req.body === 'string' ? req.body : JSON.stringify(req.body);
    if (Buffer.byteLength(raw) > C.MAX_BYTES) throw new AnalystError('PAYLOAD_TOO_LARGE', 413);
    return typeof req.body === 'string' ? JSON.parse(raw) : req.body;
  }
  const chunks = []; let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > C.MAX_BYTES) throw new AnalystError('PAYLOAD_TOO_LARGE', 413);
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}
function createHandler({ serviceImpl = service, env = process.env, logger = console } = {}) {
  return async (req, res) => {
    const send = (status, body) => { res.statusCode = status; res.end(JSON.stringify(body)); };
    res.setHeader('Content-Type', 'application/json; charset=utf-8');
    res.setHeader('Cache-Control', 'no-store'); res.setHeader('Vary', 'Origin');
    res.setHeader('X-Content-Type-Options', 'nosniff');
    if (!allowedOrigin(req.headers.origin, env)) return send(403, { error: { code: 'ORIGIN_DENIED', message: C.ERROR_MESSAGE } });
    res.setHeader('Access-Control-Allow-Origin', req.headers.origin);
    res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
    if (req.method === 'OPTIONS') { res.statusCode = 204; res.end(); return; }
    if (req.method !== 'POST') { res.setHeader('Allow', 'POST, OPTIONS'); return send(405, { error: { code: 'METHOD_NOT_ALLOWED', message: C.ERROR_MESSAGE } }); }
    try {
      if (!/^application\/json(?:\s*;|$)/i.test(req.headers['content-type'] || '')) throw new AnalystError('UNSUPPORTED_MEDIA_TYPE', 415);
      let data;
      try { data = await readBody(req); } catch (error) { throw error instanceof AnalystError ? error : new AnalystError('INVALID_REQUEST', 400); }
      if (!C.validRequest(data)) throw new AnalystError('INVALID_REQUEST', 400);
      // Vercel overwrites x-forwarded-for at its trusted proxy; never accept client IP headers in the local server.
      const ip = env.VERCEL === '1' ? String(req.headers['x-forwarded-for'] || 'unknown').split(',')[0].trim() : req.socket?.remoteAddress || 'local';
      const result = await serviceImpl.run(data, ip, env);
      return send(200, { schemaVersion: 1, ...result });
    } catch (error) {
      const known = error instanceof AnalystError;
      const status = known ? error.status : 500, code = known ? error.code : 'INTERNAL_ERROR';
      // Do not log request contents, raw provider errors, headers, or environment values.
      logger.warn('[AI ANALYST]', { code, status });
      if (status === 429) res.setHeader('Retry-After', '60');
      return send(status, { error: { code, message: C.ERROR_MESSAGE } });
    }
  };
}
module.exports = createHandler();
module.exports.createHandler = createHandler;
module.exports.allowedOrigin = allowedOrigin;
