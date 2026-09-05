/* Static-page / Node shared model. Source JSON is never mutated. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.PitchReplay = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const DISCLAIMER = '実際の投球軌道を完全再現したものではなく、収集データをもとにした簡易再現です';
  // Same chart reference as index.html's CH. These are approximate diagram bounds, not tracking measurements.
  const CHART = Object.freeze({ size: 63, top: 10, bottom: 58, left: 5, right: 50 });
  const number = v => typeof v === 'number' && Number.isFinite(v) ? v : null;
  const text = v => typeof v === 'string' && v.trim() ? v : null;
  function playerKey(player) {
    if (!player) return null;
    const id = String(player.player_id || '').trim().replace(/\.0$/, '');
    return id ? 'p' + id : player.name ? 'name:' + player.name.replace(/[\s　]/g, '') : null;
  }
  function hand(value, role) {
    return value === '右' + role ? 1 : value === '左' + role ? -1 : 0;
  }
  function pitchFamily(type) {
    if (/カット/.test(type || '')) return 'cutter';
    if (/カーブ|スラーブ/.test(type || '')) return 'curve';
    if (/フォーク|スプリット/.test(type || '')) return 'splitter';
    if (/チェンジアップ|パーム/.test(type || '')) return 'changeup';
    if (/ツーシーム|ワンシーム|シュート|シンカー|スクリュー/.test(type || '')) return 'sinker';
    if (/縦スライダー/.test(type || '')) return 'verticalSlider';
    if (/スライダー|スイーパー/.test(type || '')) return 'slider';
    if (/ストレート/.test(type || '')) return 'fastball';
    return 'neutral';
  }
  const COLORS = Object.freeze({ fastball: '#2465b5', slider: '#71649b', verticalSlider: '#686597',
    cutter: '#526ca0', curve: '#377e89', splitter: '#9a7447', changeup: '#56846b', sinker: '#477c9a', neutral: '#68758a' });
  function coursePosition(course) {
    if (!course) return null;
    const left = number(course.left_px), top = number(course.top_px);
    if (left !== null && top !== null) return { x: 1 - left / CHART.size, y: top / CHART.size, source: 'chart_pixels' };
    const row = number(course.grid_row), col = number(course.grid_col);
    if ([row, col].every(v => Number.isInteger(v) && v >= 0 && v <= 4)) {
      return { x: 1 - (col + .5) / 5, y: (row + .5) / 5, source: 'grid_cell_center_model' };
    }
    return null;
  }
  function locationLabel(course, batterHand) {
    const pos = coursePosition(course);
    if (!pos) return null;
    const row = Math.max(0, Math.min(4, Math.floor(pos.y * 5)));
    const col = Math.max(0, Math.min(4, Math.floor(pos.x * 5)));
    const height = ['高め', '高め', '真ん中', '低め', '低め'][row];
    const side = hand(batterHand, '打');
    // A right-handed batter stands on the catcher's left; source labels are NOT handedness-aware.
    const horizontal = col === 2 ? '真ん中' : !side ? (col < 2 ? '捕手視点の左' : '捕手視点の右')
      : ((col < 2) === (side === 1) ? '内角' : '外角');
    return height + '・' + horizontal;
  }
  function countAfter(before, pitch) {
    if (!before) return null;
    let { balls, strikes } = before;
    const r = text(pitch.result);
    if (!r) return null; // A missing event must never silently count as an in-play pitch.
    if (/四球/.test(r)) balls = 4;
    else if (/三振|スリーバント失敗/.test(r)) strikes = 3;
    else if (/ボール/.test(r)) balls = Math.min(4, balls + 1);
    else if (/ファウル|ファール/.test(r)) strikes = Math.min(2, strikes + 1);
    else if (/見逃し|空振り|ストライク/.test(r)) strikes = Math.min(3, strikes + 1);
    else if (!/安打|本塁打|ゴロ|フライ|飛|ライナー|直|犠|併殺|死球|失策|出塁|野選|内野安打/.test(r)
      && !['hit', 'out', 'bunt'].includes(pitch.kind)) return null;
    return { balls, strikes };
  }
  function normalizePlateAppearance(game, atbat, arrayIndex, sourceFile) {
    const ab = atbat || {}, raw = Array.isArray(ab.pitches) ? ab.pitches.filter(p => p && typeof p === 'object') : [];
    const ordered = raw.every(p => Number.isInteger(p.no) && p.no > 0) && new Set(raw.map(p => p.no)).size === raw.length;
    const pitches = ordered ? raw.slice().sort((a, b) => a.no - b.no) : raw.slice();
    let count = { balls: 0, strikes: 0 };
    const normalized = pitches.map((p, i) => {
      if (!ordered || p.no !== i + 1 || (count && (count.balls >= 4 || count.strikes >= 3))) count = null;
      const before = count && { ...count };
      count = countAfter(before, p);
      return { ordinal: i + 1, number: number(p.no), type: text(p.type), speed: number(p.speed_kmh),
        result: text(p.result), kind: text(p.kind), course: p.course ? { ...p.course } : null,
        location: locationLabel(p.course, ab.batter && ab.batter.hand), position: coursePosition(p.course),
        family: pitchFamily(p.type), countBefore: before, countAfter: count && { ...count } };
    });
    return { gameId: text(String(game.game_id || '')), sourceFile: sourceFile || null,
      id: String(game.game_id || '') + ':' + (text(ab.index) || 'array-' + arrayIndex),
      index: text(ab.index), arrayIndex, date: text(game.game_date), inning: number(ab.inning), half: text(ab.top_bottom),
      pitcher: ab.pitcher ? { ...ab.pitcher, key: playerKey(ab.pitcher) } : null,
      batter: ab.batter ? { ...ab.batter, key: playerKey(ab.batter) } : null,
      recordedCount: ab.count ? { ...ab.count } : null, result: text(ab.result_summary), pitches: normalized };
  }
  function duration(speed) {
    return number(speed) !== null && speed > 0 ? Math.max(800, Math.min(2100, 1400 * Math.pow(140 / speed, 2))) : 1400;
  }
  function trajectory(pitch, pitcherHand, t) {
    if (!pitch.position) return null;
    t = Math.max(0, Math.min(1, t));
    const arm = hand(pitcherHand, '投');
    const start = { x: .5 - .10 * arm, y: -.13 };
    const end = pitch.position;
    // All coefficients below are visual models only. Endpoints ALWAYS preserve the recorded course.
    let bendX = 0, bendY = 0;
    const arc = Math.sin(Math.PI * t), late = t * t * (1 - t) * 4;
    switch (pitch.family) {
      case 'slider': bendX = -.25 * arm * arc; break;
      case 'verticalSlider': bendX = -.06 * arm * arc; bendY = -.20 * late; break;
      case 'cutter': bendX = -.10 * arm * arc; break;
      case 'sinker': bendX = .12 * arm * arc; bendY = -.12 * late; break;
      case 'curve': bendX = -.10 * arm * arc; bendY = -.32 * arc; break;
      case 'splitter': bendY = -.38 * late; break;
      case 'changeup': bendX = .07 * arm * arc; bendY = -.18 * late; break;
    }
    return { x: start.x + (end.x - start.x) * t + bendX, y: start.y + (end.y - start.y) * t + bendY,
      radius: 3 + 10 * t * t };
  }
  function getPlateAppearanceSummary(pa) {
    if (!pa) return null;
    // No animation coefficients or invented intent are included as observations.
    return { schemaVersion: 1, plateAppearanceId: pa.id,
      source: { file: pa.sourceFile, gameId: pa.gameId, index: pa.index, arrayIndex: pa.arrayIndex },
      pitcher: pa.pitcher, batter: pa.batter, date: pa.date, inning: pa.inning, topBottom: pa.half,
      recordedCount: pa.recordedCount, result: pa.result,
      pitches: pa.pitches.map(p => ({ number: p.number, displayOrder: p.ordinal, type: p.type, speed: p.speed,
        course: p.course, location: p.location, result: p.result,
        derived: { countBefore: p.countBefore, countAfter: p.countAfter, locationBasis: 'chart + batter handedness' } })),
      provenance: { recorded: 'Source JSON values; null means unavailable. recordedCount is a snapshot; timing/provenance is not preserved by the collector.',
        derived: 'B/S recomputed from a complete pitch sequence. Missing/ambiguous events or numbering gaps produce null. O is not reconstructed.',
        visualization: '取得できないため簡易モデルで補完: 軌道・リリース位置・変化量・飛行時間。グリッドのみの場合はセル中心。',
        coordinateConvention: 'Existing site labels source chart as pitcher view; horizontally mirrored for catcher view. Approximate zone bounds.',
        disclaimer: DISCLAIMER },
      aiInterpretation: null };
  }
  class Playback {
    constructor(pitches = []) { this.pitches = pitches; this.speed = 1; this.mode = 'single'; this.reset(); }
    reset() { this.index = 0; this.progress = 0; this.hold = 0; this.phase = 'ready'; this.playing = false; }
    select(index) {
      this.index = Math.max(0, Math.min(this.pitches.length - 1, index));
      this.progress = 0; this.hold = 0; this.phase = 'ready'; this.playing = false;
    }
    play() {
      if (!this.pitches.length) return;
      if (this.phase === 'landed') this.select(this.index < this.pitches.length - 1 ? this.index + 1 : 0);
      this.phase = 'flight'; this.playing = true;
    }
    pause() { this.playing = false; }
    advance(ms) {
      if (!this.playing || !this.pitches.length) return;
      if (this.phase === 'landed') {
        this.hold += ms * this.speed;
        if (this.hold >= 650) {
          this.select(this.index + 1); this.play();
        }
        return;
      }
      this.progress = Math.min(1, this.progress + ms * this.speed / duration(this.pitches[this.index].speed));
      if (this.progress >= 1) {
        this.phase = 'landed'; this.hold = 0;
        if (this.mode === 'single' || this.index === this.pitches.length - 1) this.playing = false;
      }
    }
  }
  return { DISCLAIMER, CHART, COLORS, playerKey, hand, pitchFamily, coursePosition, locationLabel,
    countAfter, normalizePlateAppearance, duration, trajectory, getPlateAppearanceSummary, Playback };
});
