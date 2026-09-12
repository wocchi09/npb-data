(function () {
  'use strict';
  const C = window.AIAnalystContract, $ = id => document.getElementById('ai-' + id);
  const client = window.AIAnalystClient.createClient(window.NPB_AI_ANALYST_CONFIG);
  let selection = 0, request = null, busy = false;
  function status(message, loading = false) {
    $('status').textContent = message; $('spinner').hidden = !loading;
    // Keep the live status outside the busy region so loading is announced immediately.
    $('result').setAttribute('aria-busy', String(loading));
    $('analyze').setAttribute('aria-busy', String(loading));
  }
  function refresh() {
    selection++;
    request?.abort(); request = null; busy = false;
    $('result').replaceChildren();
    const summary = window.getPlateAppearanceSummary?.();
    $('analyze').disabled = !summary?.pitches?.length;
    status(!summary ? '分析する打席を選択してください。' : !summary.pitches.length ? 'この打席の投球データはありません。' : '選択した1打席のデータをAIへ送信して解説します。');
  }
  $('analyze').addEventListener('click', async () => {
    if (busy) return;
    let payload;
    try { payload = window.AIAnalystData.toPayload(window.getPlateAppearanceSummary?.()); }
    catch (error) {
      status(error.message === 'NO_SELECTION' ? '分析する打席を選択してください。' : error.message === 'NO_PITCHES' ? 'この打席の投球データはありません。' : C.ERROR_MESSAGE); return;
    }
    const token = selection;
    busy = true; $('analyze').disabled = true; $('result').replaceChildren();
    request = new AbortController();
    status('AIが配球を分析しています…', true);
    try {
      const result = await client.analyze(payload, request.signal);
      if (token !== selection) return;
      window.AIAnalystView.render($('result'), result.analysis);
      status(result.cached ? 'この打席の保存済み分析を表示しました。' : 'この打席のAI分析を表示しました。');
    } catch (error) {
      if (token !== selection || error.message === 'CANCELLED') return;
      const messages = { RATE_LIMITED: '短時間の利用回数の上限に達しました。1分ほど待って再度お試しください。',
        NOT_CONFIGURED: 'AI分析は準備中です。時間を置いて再度お試しください。' };
      status(messages[error.message] || C.ERROR_MESSAGE);
      console.warn('[AI ANALYST]', { code: error.message });
    } finally {
      if (token === selection) { busy = false; request = null; $('analyze').disabled = false; $('spinner').hidden = true; $('result').setAttribute('aria-busy', 'false'); $('analyze').setAttribute('aria-busy', 'false'); }
    }
  });
  window.addEventListener('pitchreplay:selectionchange', refresh);
  window.addEventListener('pagehide', () => request?.abort());
  refresh();
})();
