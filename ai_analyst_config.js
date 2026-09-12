/* Public endpoint only. NEVER put an API key here. Set after deploying backend/ to Vercel. */
window.NPB_AI_ANALYST_CONFIG = Object.freeze({
  endpoint: ['localhost', '127.0.0.1'].includes(location.hostname)
    ? 'http://127.0.0.1:3000/api/analyze-atbat'
    : 'https://npb-ai-analyst.vercel.app/api/analyze-atbat'
});
