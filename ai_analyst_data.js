(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(require('./backend/public/ai-contract.js'));
  else root.AIAnalystData = factory(root.AIAnalystContract);
})(typeof globalThis !== 'undefined' ? globalThis : this, function (C) {
  'use strict';
  const text = v => typeof v === 'string' && v.trim() ? v : null;
  const number = v => typeof v === 'number' && Number.isFinite(v) ? v : null;
  const person = (p, role) => p ? { name: text(p.name), hand: ['右', '左', '両'].map(h => h + role).includes(p.hand) ? p.hand : null } : null;
  const count = c => c ? { balls: number(c.balls), strikes: number(c.strikes) } : null;
  function toPayload(summary) {
    if (!summary) throw new Error('NO_SELECTION');
    if (!Array.isArray(summary.pitches) || !summary.pitches.length) throw new Error('NO_PITCHES');
    if (summary.pitches.length > C.MAX_PITCHES) throw new Error('INVALID_REQUEST');
    // Only select fields from the existing summary. No replay normalization or coordinate math here.
    const payload = { schemaVersion: 1, game_id: summary.source?.gameId,
      atbat_index: summary.source?.index || 'array-' + summary.source?.arrayIndex,
      pitcher: person(summary.pitcher, '投'), batter: person(summary.batter, '打'), inning: number(summary.inning),
      topBottom: text(summary.topBottom), result: text(summary.result),
      pitches: summary.pitches.map(p => ({ no: number(p.number), display_order: p.displayOrder,
        type: text(p.type), speed_kmh: number(p.speed), result: text(p.result),
        course: p.course ? { top_px: number(p.course.top_px), left_px: number(p.course.left_px),
          grid_row: number(p.course.grid_row), grid_col: number(p.course.grid_col) } : null,
        derived: { location: text(p.location), countBefore: count(p.derived?.countBefore), countAfter: count(p.derived?.countAfter) }
      })) };
    if (!C.validRequest(payload)) throw new Error('INVALID_REQUEST');
    return payload;
  }
  return { toPayload };
});
