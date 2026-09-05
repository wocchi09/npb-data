const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const M = require('../pitch_replay_model.js');
// Synthetic fixtures are test-only. The production UI never loads sample or invented pitches.
const rawPitch = (no, result = 'ファウル') => ({ no, result, type: 'ストレート', speed_kmh: 140,
  course: { left_px: 20, top_px: 30, label: '真ん中・外', grid_row: 2, grid_col: 1 } });
const normalize = pitches => M.normalizePlateAppearance({ game_id: 'test' }, { index: '0110100', pitches,
  pitcher: { player_id: '123', hand: '右投' }, batter: { hand: '左打' } }, 0, 'test-only');

test('empty, missing fields and unknown pitch names preserve missing values', () => {
  assert.deepEqual(normalize([]).pitches, []);
  const p = normalize([{ no: 1 }]).pitches[0];
  for (const key of ['type', 'speed', 'course', 'position', 'location', 'result', 'countAfter']) assert.equal(p[key], null);
  assert.equal(M.pitchFamily('未知球種'), 'neutral');
  assert.equal(M.coursePosition({ left_px: '', top_px: null }), null);
  assert.equal(M.trajectory(p, '右投', .5), null);
});
test('identifiers reuse existing player key format; index fallback is explicit', () => {
  assert.equal(M.playerKey({ player_id: '123' }), 'p123');
  assert.equal(M.playerKey({ name: 'テスト　選手' }), 'name:テスト選手');
  assert.equal(M.playerKey(null), null);
  assert.equal(M.normalizePlateAppearance({ game_id: 'test' }, {}, 7).id, 'test:array-7');
});
test('sorting is non-mutating; missing/duplicate numbers make counts unknown', () => {
  const source = [rawPitch(2, '見逃し'), rawPitch(1, 'ボール')], saved = JSON.stringify(source);
  const pa = normalize(source);
  assert.deepEqual(pa.pitches.map(p => p.number), [1, 2]);
  assert.deepEqual(pa.pitches[1].countAfter, { balls: 1, strikes: 1 });
  assert.equal(JSON.stringify(source), saved);
  assert.equal(normalize([rawPitch(1), rawPitch(3)]).pitches[1].countBefore, null);
  assert.equal(normalize([rawPitch(1), rawPitch(1)]).pitches[0].countBefore, null);
});
test('count derivation handles long at-bats, fouls, walk, strikeout and missing events', () => {
  const long = normalize(Array.from({ length: 12 }, (_, i) => rawPitch(i + 1)));
  assert.equal(long.pitches[11].countAfter.strikes, 2);
  const walk = normalize(Array.from({ length: 4 }, (_, i) => rawPitch(i + 1, 'ボール')));
  assert.equal(walk.pitches[3].countAfter.balls, 4);
  assert.equal(normalize([rawPitch(1, '見逃し'), rawPitch(2, '空振り'), rawPitch(3, '空振り三振')]).pitches[2].countAfter.strikes, 3);
  assert.equal(normalize([rawPitch(1, ''), rawPitch(2)]).pitches[1].countBefore, null);
  assert.equal(M.countAfter({ balls: 1, strikes: 2 }, { result: 'スリーバント失敗' }).strikes, 3);
  assert.equal(normalize([rawPitch(1, '不明')]).pitches[0].countAfter, null);
});
test('catcher coordinates are mirrored once; right and left batter labels reverse', () => {
  const course = { left_px: 0, top_px: 0 };
  assert.deepEqual(M.coursePosition(course), { x: 1, y: 0, source: 'chart_pixels' });
  assert.equal(M.locationLabel(course, '右打'), '高め・外角');
  assert.equal(M.locationLabel(course, '左打'), '高め・内角');
  assert.equal(M.locationLabel(course, null), '高め・捕手視点の右');
  assert.ok(M.coursePosition({ left_px: 80, top_px: 90 }).x < 0); // no invented strike-zone clamping
});
test('grid-only data is explicitly modeled and labels alone do not invent coordinates', () => {
  assert.equal(M.coursePosition({ grid_row: 1, grid_col: 4 }).source, 'grid_cell_center_model');
  assert.equal(M.coursePosition({ grid_row: 5, grid_col: 0 }), null);
  assert.equal(M.coursePosition({ label: '低め・外' }), null);
});
test('pitch families cover the collected variants with a neutral fallback', () => {
  for (const [type, family] of Object.entries({ ストレート: 'fastball', カットボール: 'cutter', ナックルカーブ: 'curve',
    スローカーブ: 'curve', パワーカーブ: 'curve', フォーク: 'splitter', スプリット: 'splitter', スイーパー: 'slider',
    縦スライダー: 'verticalSlider', ツーシーム: 'sinker', シュート: 'sinker', スクリュー: 'sinker', チェンジアップ: 'changeup' })) {
    assert.equal(M.pitchFamily(type), family);
  }
});
test('all visual models land on the recorded course, with mirrored handedness', () => {
  const position = { x: .5, y: .5 };
  for (const family of Object.keys(M.COLORS)) {
    const p = { family, position };
    for (const arm of ['右投', '左投', null]) {
      const endpoint = M.trajectory(p, arm, 1);
      assert.ok(Math.abs(endpoint.x - .5) < 1e-12);
      assert.ok(Math.abs(endpoint.y - .5) < 1e-12);
    }
    const right = M.trajectory(p, '右投', .5), left = M.trajectory(p, '左投', .5);
    assert.ok(Math.abs(right.x + left.x - 1) < 1e-12);
    assert.equal(M.trajectory(p, null, .5).x, .5);
  }
  assert.ok(M.trajectory({ family: 'curve', position }, '右投', .5).y < M.trajectory({ family: 'fastball', position }, '右投', .5).y);
});
test('speed affects a bounded, readable duration without a fabricated missing speed', () => {
  assert.ok(M.duration(150) < M.duration(140)); assert.ok(M.duration(140) < M.duration(120));
  assert.equal(M.duration(null), 1400); assert.equal(M.duration(0), 1400);
  assert.equal(M.duration(999), 800); assert.equal(M.duration(1), 2100);
});
test('single-pitch play, pause, resume, restart and bounds', () => {
  const c = new M.Playback(normalize([rawPitch(1)]).pitches);
  c.play(); c.advance(350); assert.equal(c.progress, .25);
  c.pause(); c.advance(500); assert.equal(c.progress, .25);
  c.play(); c.advance(1050); assert.equal(c.phase, 'landed'); assert.equal(c.playing, false);
  c.play(); assert.equal(c.index, 0); assert.equal(c.progress, 0);
  c.select(99); assert.equal(c.index, 0); c.reset(); assert.equal(c.playing, false);
  const empty = new M.Playback(); empty.play(); empty.advance(500); assert.equal(empty.playing, false);
});
test('continuous play retains every pitch, allows speed changes and navigation', () => {
  const c = new M.Playback(normalize(Array.from({ length: 12 }, (_, i) => rawPitch(i + 1))).pitches);
  c.mode = 'continuous'; c.play();
  c.advance(350); c.speed = 2; c.advance(525); assert.equal(c.phase, 'landed');
  c.pause(); c.advance(10000); assert.equal(c.index, 0); c.play(); assert.equal(c.index, 1);
  const visited = [0];
  for (let i = 1; i < 12; i++) {
    assert.equal(c.index, i); visited.push(c.index); c.advance(700);
    if (i < 11) c.advance(325);
  }
  assert.equal(visited.length, 12); assert.equal(c.playing, false); assert.equal(c.index, 11);
  c.select(3); assert.equal(c.index, 3); assert.equal(c.progress, 0); assert.equal(c.playing, false);
});
test('AI export separates recorded, derived, model and interpretation fields', () => {
  const summary = M.getPlateAppearanceSummary(normalize([rawPitch(1)]));
  assert.equal(summary.pitches[0].speed, 140);
  assert.equal(summary.pitches[0].course.left_px, 20);
  assert.equal(summary.aiInterpretation, null);
  assert.ok(summary.provenance.disclaimer.includes('簡易再現'));
  assert.equal('trajectory' in summary.pitches[0], false);
  assert.equal(M.getPlateAppearanceSummary(null), null);
});
test('every committed game normalizes without mutating source or inventing pitches', () => {
  const root = path.resolve(__dirname, '..');
  const files = JSON.parse(fs.readFileSync(path.join(root, 'data/index.json'))).files.filter(f => /\/\d+\.json$/.test(f));
  let count = 0;
  for (const file of files) {
    const game = JSON.parse(fs.readFileSync(path.join(root, file))), original = JSON.stringify(game);
    (game.atbats || []).forEach((ab, i) => {
      const pa = M.normalizePlateAppearance(game, ab, i, file);
      assert.equal(pa.pitches.length, (ab.pitches || []).length);
      for (const p of pa.pitches) {
        if (p.position) { const end = M.trajectory(p, pa.pitcher?.hand, 1); assert.ok(Math.abs(end.x - p.position.x) < 1e-10); assert.ok(Math.abs(end.y - p.position.y) < 1e-10); }
        count++;
      }
    });
    assert.equal(JSON.stringify(game), original);
  }
  assert.ok(count > 200000);
});
