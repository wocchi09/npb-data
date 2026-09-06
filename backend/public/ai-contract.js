/* Public, dependency-free request/response contract. No secrets or prompts. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.AIAnalystContract = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const MAX_BYTES = 24576, MAX_PITCHES = 30;
  const ERROR_MESSAGE = 'AI分析を取得できませんでした。少し時間を置いて再度お試しください。';
  const LIMITATION = '投手・捕手・打者の心理や、この配球を選択した意図は、このデータだけでは判断できません。';
  const str = max => ({ type: 'string', minLength: 1, maxLength: max });
  const num = (min, max, integer = false) => ({ type: integer ? 'integer' : 'number', minimum: min, maximum: max });
  const nullable = schema => ({ anyOf: [schema, { type: 'null' }] });
  const obj = properties => ({ type: 'object', properties, required: Object.keys(properties), additionalProperties: false });
  const arr = (items, min, max) => ({ type: 'array', items, minItems: min, maxItems: max });
  const count = nullable(obj({ balls: num(0, 4, true), strikes: num(0, 3, true) }));
  const person = role => nullable(obj({ name: nullable(str(60)), hand: { enum: [null, '右' + role, '左' + role, '両' + role] } }));
  const requestSchema = obj({
    schemaVersion: { enum: [1] }, game_id: { ...str(20), pattern: '^\\d+$' },
    atbat_index: { ...str(40), pattern: '^(\\d+|array-\\d+)$' },
    pitcher: person('投'), batter: person('打'), inning: nullable(num(1, 30, true)),
    topBottom: { enum: [null, '表', '裏'] }, result: nullable(str(120)),
    pitches: arr(obj({
      no: nullable(num(1, 100, true)), display_order: num(1, MAX_PITCHES, true),
      type: nullable(str(30)), speed_kmh: nullable(num(1, 200)), result: nullable(str(120)),
      course: nullable(obj({ top_px: nullable(num(-200, 300)), left_px: nullable(num(-200, 300)),
        grid_row: nullable(num(0, 4, true)), grid_col: nullable(num(0, 4, true)) })),
      derived: obj({ location: nullable(str(40)), countBefore: count, countAfter: count })
    }), 1, MAX_PITCHES)
  });
  const responseSchema = obj({ summary: str(600),
    pitch_flow: arr(obj({ pitch: num(1, MAX_PITCHES, true), description: str(300) }), 1, MAX_PITCHES),
    points: arr(str(300), 1, 6), limitations: arr(str(300), 1, 6) });
  function matches(value, schema) {
    if (schema.anyOf) return schema.anyOf.some(s => matches(value, s));
    if (schema.enum) return schema.enum.includes(value);
    if (schema.type === 'null') return value === null;
    if (schema.type === 'object') return value !== null && typeof value === 'object' && !Array.isArray(value)
      && Object.keys(value).length === schema.required.length
      && schema.required.every(k => Object.prototype.hasOwnProperty.call(value, k) && matches(value[k], schema.properties[k]));
    if (schema.type === 'array') return Array.isArray(value) && value.length >= schema.minItems && value.length <= schema.maxItems && value.every(v => matches(v, schema.items));
    if (schema.type === 'string') return typeof value === 'string' && value.trim().length >= schema.minLength && value.length <= schema.maxLength
      && (!schema.pattern || new RegExp(schema.pattern).test(value)) && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(value);
    return typeof value === 'number' && Number.isFinite(value) && value >= schema.minimum && value <= schema.maximum && (schema.type !== 'integer' || Number.isInteger(value));
  }
  function validRequest(value) {
    return matches(value, requestSchema) && value.pitches.every((p, i) => p.display_order === i + 1)
      && new TextEncoder().encode(JSON.stringify(value)).length <= MAX_BYTES;
  }
  function validResponse(value, pitchCount) {
    return matches(value, responseSchema) && value.pitch_flow.length === pitchCount
      && value.pitch_flow.every((p, i) => p.pitch === i + 1);
  }
  return { MAX_BYTES, MAX_PITCHES, ERROR_MESSAGE, LIMITATION, requestSchema, responseSchema, validRequest, validResponse };
});
