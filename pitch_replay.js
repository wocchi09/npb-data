(function () {
  'use strict';
  const M = window.PitchReplay, $ = id => document.getElementById('replay-' + id);
  const escape = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const shown = v => v == null || v === '' ? '未取得' : String(v);
  const params = new URLSearchParams(location.search), cache = new Map();
  let files = [], game = null, pa = null, appearances = [], player = new M.Playback(), frame = 0, lastTime = 0;
  let request = 0, abort = null, metaKey = '', project = null;
  let pitcherFilter = params.get('pitcher') || '';
  const pathDate = path => path.split('/').slice(1, 4).join('-');
  const pitcherName = p => p ? shown(p.name) + '（' + shown(p.hand) + '）' : '未取得';

  async function json(path, signal) {
    if (cache.has(path)) return cache.get(path);
    const response = await fetch(path, { signal });
    if (!response.ok) throw new Error('HTTP ' + response.status);
    const result = await response.json();
    cache.set(path, result);
    if (cache.size > 8) cache.delete(cache.keys().next().value);
    return result;
  }
  function options(node, items, selected) {
    node.replaceChildren(...items.map(item => new Option(item.label, item.value)));
    if (items.some(item => item.value === selected)) node.value = selected;
    node.disabled = !items.length;
  }
  function stop() { player.pause(); cancelAnimationFrame(frame); frame = 0; lastTime = 0; }
  function loading(message) {
    stop(); pa = null; $('content').hidden = true; $('status').textContent = message; $('retry').hidden = true;
    $('atbat').disabled = true;
  }
  function failed(message) { $('status').textContent = message; $('retry').hidden = false; }
  function startRequest() {
    if (abort) abort.abort();
    abort = new AbortController();
    return { token: ++request, signal: abort.signal };
  }
  async function loadDate(preferredFile, preferredAtbat, preferredArray) {
    const { token, signal } = startRequest();
    loading('この日の試合を確認しています…');
    const date = $('date').value;
    const matches = files.filter(file => pathDate(file) === date).sort();
    options($('game'), matches.map(file => ({ value: file, label: '試合 ' + file.split('/').pop().replace('.json', '') })), preferredFile);
    if (!matches.length) { $('status').textContent = 'この日の収集データはありません。'; return; }
    // Day summaries are only for labels. Full game JSON remains the source of every pitch.
    try {
      const summary = await json(matches[0].replace(/\d+\.json$/, '_summary.json'), signal);
      if (token !== request) return;
      const names = new Map((summary.games || []).map(g => [String(g.game_id), g.card || [g.away, g.home].filter(Boolean).join(' vs ')]));
      Array.from($('game').options).forEach(option => {
        const id = option.value.split('/').pop().replace('.json', '');
        if (names.get(id)) option.textContent = names.get(id) + ' / ' + id;
      });
    } catch (error) { if (error.name === 'AbortError') return; /* Missing summary must not block raw game data. */ }
    if (token === request) await loadGame(preferredAtbat, preferredArray);
  }
  async function loadGame(preferredAtbat, preferredArray) {
    const { token, signal } = startRequest();
    loading('打席データを読み込んでいます…');
    const file = $('game').value;
    if (!files.includes(file)) { failed('収集済みの試合を選んでください。'); return; }
    try {
      const payload = await json(file, signal);
      if (token !== request) return;
      game = payload;
      appearances = (Array.isArray(game.atbats) ? game.atbats : []).map((ab, index) => ({ ab, index }))
        .filter(({ ab }) => ab && ab.valid !== false && (!pitcherFilter || M.playerKey(ab.pitcher) === pitcherFilter));
      const items = appearances.map(({ ab, index }) => ({ value: String(index), label: [
        (ab.inning == null ? '回未取得' : ab.inning + '回') + (ab.top_bottom || ''),
        shown(ab.pitcher && ab.pitcher.name) + ' → ' + shown(ab.batter && ab.batter.name),
        (ab.pitches || []).length + '球'
      ].join(' / ') }));
      const desired = appearances.find(({ ab, index }) => preferredAtbat ? ab.index === preferredAtbat : preferredArray != null && String(index) === preferredArray);
      options($('atbat'), items, desired ? String(desired.index) : undefined);
      if (!items.length) {
        $('status').textContent = pitcherFilter ? 'この試合には選択中の投手の打席がありません。日付・試合を変更するか、投手の絞り込みを解除してください。' : 'この試合に打席データはありません。';
        return;
      }
      selectAppearance();
      if ((preferredAtbat || preferredArray != null) && !desired) $('status').textContent = '指定の打席は見つかりません。打席一覧の先頭を表示しています。';
    } catch (error) {
      if (token === request && error.name !== 'AbortError') failed('試合データを読み込めません。再読み込みするか別の試合を選んでください。');
    }
  }
  function selectAppearance() {
    stop();
    const entry = appearances.find(item => String(item.index) === $('atbat').value);
    if (!entry) return;
    pa = M.normalizePlateAppearance(game, entry.ab, entry.index, $('game').value);
    player = new M.Playback(pa.pitches); player.mode = $('mode').value; player.speed = Number($('speed').value);
    $('content').hidden = false;
    $('status').textContent = pa.pitches.length ? '実データ ' + pa.pitches.length + '球を読み込みました。再生ボタンで開始します。' : 'この打席の投球データはありません。';
    $('pitcher').textContent = pitcherName(pa.pitcher); $('batter').textContent = pitcherName(pa.batter);
    $('inning').textContent = shown(pa.inning) + '回' + (pa.half || '');
    $('outs').textContent = shown(pa.recordedCount && pa.recordedCount.out);
    const side = M.hand(pa.batter && pa.batter.hand, '打');
    $('batter-side').textContent = side === 1 ? '右打者：画面左側' : side === -1 ? '左打者：画面右側' : '打者の左右：未取得（内外角は判定しません）';
    $('pitches').innerHTML = pa.pitches.map((p, i) => '<tr><td><button data-pitch="' + i + '" aria-label="' + (i + 1) + '番目の投球を選択">' + escape(p.number == null ? '?' : p.number) + '</button></td><td><span style="color:' + M.COLORS[p.family] + '">●</span> ' + escape(shown(p.type)) + '</td><td>' + escape(p.speed == null ? '未取得' : p.speed + ' km/h') + '</td><td>' + escape(shown(p.location)) + '</td><td>' + escape(shown(p.result)) + '</td></tr>').join('');
    const types = new Map(pa.pitches.map(p => [p.type || '球種未取得', p.family]));
    $('legend').innerHTML = Array.from(types, ([type, family]) => '<span><i style="background:' + M.COLORS[family] + '"></i>' + escape(type) + '</span>').join('');
    buildZone(); metaKey = ''; render();
    const query = new URLSearchParams(); query.set('game', $('game').value);
    if (pa.index) query.set('atbat', pa.index); else query.set('ab', String(pa.arrayIndex));
    if (pitcherFilter) query.set('pitcher', pitcherFilter);
    history.replaceState(null, '', location.pathname + '?' + query.toString());
  }
  function buildZone() {
    // Fit out-of-chart recorded points without clamping them into the strike zone.
    const positions = pa.pitches.map(p => p.position).filter(Boolean);
    const minX = Math.min(-.16, ...positions.map(p => p.x)), maxX = Math.max(1.16, ...positions.map(p => p.x));
    const minY = Math.min(-.35, ...positions.map(p => p.y)), maxY = Math.max(1.14, ...positions.map(p => p.y));
    project = p => ({ x: 35 + (p.x - minX) / (maxX - minX) * 430, y: 52 + (p.y - minY) / (maxY - minY) * 320 });
    const c = M.CHART, a = project({ x: 1 - c.right / c.size, y: c.top / c.size }), b = project({ x: 1 - c.left / c.size, y: c.bottom / c.size });
    let svg = '<rect x="' + a.x + '" y="' + a.y + '" width="' + (b.x - a.x) + '" height="' + (b.y - a.y) + '" fill="#e4edf9" stroke="#7395c4" stroke-width="2"/>';
    for (let i = 1; i < 3; i++) {
      const x = a.x + (b.x - a.x) * i / 3, y = a.y + (b.y - a.y) * i / 3;
      svg += '<path d="M' + x + ' ' + a.y + 'V' + b.y + ' M' + a.x + ' ' + y + 'H' + b.x + '" stroke="#a7bbd6" stroke-dasharray="4 4"/>';
    }
    $('zone').innerHTML = svg;
  }
  function drawMarks() {
    const completed = player.index + (player.phase === 'landed' ? 1 : 0), labels = [];
    $('marks').innerHTML = pa.pitches.slice(0, completed).map(p => {
      if (!p.position) return '';
      const actual = project(p.position); let label = { ...actual };
      // Move only the numbered label, preserving the recorded point and a connector.
      for (let attempt = 0; attempt < 96 && labels.some(q => Math.hypot(q.x - label.x, q.y - label.y) < 27); attempt++) {
        const angle = attempt * 2.4, radius = 28 + Math.floor(attempt / 8) * 13;
        label = { x: Math.max(18, Math.min(482, actual.x + Math.cos(angle) * radius)), y: Math.max(43, Math.min(385, actual.y + Math.sin(angle) * radius)) };
      }
      labels.push(label);
      return '<g><title>' + escape(shown(p.number) + '球目 / ' + shown(p.type) + ' / ' + shown(p.location)) + '</title><path d="M' + actual.x + ' ' + actual.y + 'L' + label.x + ' ' + label.y + '" stroke="' + M.COLORS[p.family] + '"/><circle cx="' + actual.x + '" cy="' + actual.y + '" r="3" fill="' + M.COLORS[p.family] + '"/><circle cx="' + label.x + '" cy="' + label.y + '" r="12" fill="' + M.COLORS[p.family] + '"/><text x="' + label.x + '" y="' + (label.y + 4) + '" text-anchor="middle" font-size="12" font-weight="700" fill="white">' + escape(p.number == null ? '?' : p.number) + '</text></g>';
    }).join('');
  }
  function render() {
    if (!pa) return;
    const p = pa.pitches[player.index], landed = player.phase === 'landed';
    const key = [player.index, player.phase, player.playing].join(':');
    if (key !== metaKey) {
      metaKey = key; drawMarks();
      const count = p && (landed ? p.countAfter : p.countBefore);
      $('bs').textContent = count ? count.balls + ' / ' + count.strikes : '未取得 / 未取得';
      $('count-label').textContent = 'B / S（投球' + (landed ? '後' : '前') + '・再計算）';
      $('number').textContent = p ? (player.index + 1) + ' / ' + pa.pitches.length : '0 / 0';
      $('current').innerHTML = p ? '<h3>' + escape(shown(p.type)) + ' <span>' + escape(p.speed == null ? '球速未取得' : p.speed + ' km/h') + '</span></h3><p>' + escape(shown(p.location)) + ' · ' + escape(shown(p.result)) + '</p><small>保存コース: ' + escape(shown(p.course && p.course.label)) + ' / ' + (p.position ? (p.position.source === 'chart_pixels' ? '図上座標を使用' : 'セル中心で簡易補完') : 'コース未取得') + (p.speed == null || p.speed <= 0 ? ' / 再生時間は共通設定' : '') + '</small>' : '<p>この打席の投球データはありません。</p>';
      $('play').disabled = !p || player.playing; $('pause').disabled = !player.playing;
      $('restart').disabled = !p; $('prev').disabled = !p || player.index === 0; $('next').disabled = !p || player.index >= pa.pitches.length - 1;
      $('progress').textContent = !p ? '投球データなし' : player.playing ? (landed ? '着弾・次の球へ' : '再生中') : landed ? (player.index === pa.pitches.length - 1 ? '打席の再生が完了しました' : '1球の再生が完了しました') : player.phase === 'flight' ? '一時停止中' : '再生待ち';
      const ended = !p || landed && player.index === pa.pitches.length - 1;
      $('result').hidden = !ended;
      $('result').textContent = '打席結果（保存値）：' + shown(pa.result);
      $('pitches').querySelectorAll('tr').forEach((row, i) => row.setAttribute('aria-current', String(i === player.index)));
    }
    $('missing-course').toggleAttribute('hidden', !p || !!p.position);
    const animated = p && p.position && player.phase !== 'ready';
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    $('ball').toggleAttribute('hidden', !animated || landed || reduce);
    if (!animated || reduce) { $('trail').setAttribute('d', ''); return; }
    const hand = pa.pitcher && pa.pitcher.hand, points = [];
    for (let i = 0; i <= 32; i++) {
      const point = project(M.trajectory(p, hand, player.progress * i / 32)); points.push(point.x + ' ' + point.y);
    }
    $('trail').setAttribute('d', 'M' + points.join(' L')); $('trail').setAttribute('stroke', M.COLORS[p.family]);
    const raw = M.trajectory(p, hand, player.progress), point = project(raw);
    $('ball').setAttribute('cx', point.x); $('ball').setAttribute('cy', point.y);
    $('ball').setAttribute('r', raw.radius); $('ball').setAttribute('stroke', M.COLORS[p.family]);
  }
  function tick(time) {
    if (!player.playing) return;
    if (lastTime) player.advance(Math.max(0, time - lastTime));
    lastTime = time; render();
    frame = player.playing ? requestAnimationFrame(tick) : 0;
  }
  function play() { cancelAnimationFrame(frame); lastTime = 0; player.play(); render(); if (player.playing) frame = requestAnimationFrame(tick); }
  $('play').onclick = play;
  $('pause').onclick = () => { stop(); render(); };
  $('restart').onclick = () => { stop(); player.reset(); play(); };
  $('prev').onclick = () => { stop(); player.select(player.index - 1); render(); };
  $('next').onclick = () => { stop(); player.select(player.index + 1); render(); };
  $('pitches').onclick = event => {
    const button = event.target.closest('[data-pitch]');
    if (button) { stop(); player.select(Number(button.dataset.pitch)); render(); }
  };
  $('speed').onchange = () => { player.speed = Number($('speed').value); };
  $('mode').onchange = () => { player.mode = $('mode').value; if (player.mode === 'single' && player.phase === 'landed') { stop(); render(); } };
  $('date').onchange = () => loadDate(); $('game').onchange = () => loadGame(); $('atbat').onchange = selectAppearance;
  $('retry').onclick = () => files.length ? loadDate() : initialize();
  document.addEventListener('visibilitychange', () => { if (document.hidden) { stop(); render(); } });
  window.addEventListener('pagehide', stop);
  window.getPlateAppearanceSummary = () => M.getPlateAppearanceSummary(pa);
  $('export').onclick = () => {
    const summary = window.getPlateAppearanceSummary();
    if (!summary) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(summary, null, 2)], { type: 'application/json;charset=utf-8' }));
    const link = document.createElement('a'); link.href = url; link.download = 'plate-appearance-' + pa.gameId + '-' + (pa.index || pa.arrayIndex) + '.json';
    link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  function renderFilter() {
    $('filter').hidden = !pitcherFilter;
    $('filter').replaceChildren(document.createTextNode('ANALYST LABで選んだ投手で絞り込み中 '));
    const clear = document.createElement('button'); clear.textContent = '絞り込み解除';
    clear.onclick = () => { pitcherFilter = ''; renderFilter(); loadGame(); }; $('filter').append(clear);
  }
  async function initialize() {
    loading('収集済み試合を確認しています…'); renderFilter();
    try {
      const index = await json('data/index.json');
      files = Array.from(new Set((index.files || []).filter(file => typeof file === 'string' && /^data\/\d{4}\/\d{2}\/\d{2}\/\d+\.json$/.test(file))));
      const preferred = params.get('game'), dates = Array.from(new Set(files.map(pathDate))).sort().reverse();
      options($('date'), dates.map(date => ({ value: date, label: date })), preferred && files.includes(preferred) ? pathDate(preferred) : undefined);
      if (!dates.length) { $('status').textContent = '収集済みの試合データはありません。'; return; }
      if (preferred && !files.includes(preferred)) {
        $('status').textContent = '指定された試合は収集済み一覧にありません。日付を選び直してください。';
        options($('date'), [{ value: '', label: '日付を選択' }, ...dates.map(date => ({ value: date, label: date }))]);
        return;
      }
      await loadDate(preferred, params.get('atbat'), params.get('ab'));
    } catch (error) { failed('試合一覧を読み込めません。再読み込みしてください。'); }
  }
  initialize();
})();
