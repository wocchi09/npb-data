(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.AIAnalystView = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  function render(container, analysis) {
    const doc = container.ownerDocument;
    const node = (tag, text) => { const el = doc.createElement(tag); el.textContent = text; return el; };
    const sections = [];
    function section(title, content) {
      const el = doc.createElement('section'); el.append(node('h4', title), content); sections.push(el);
    }
    section('この打席の要約', node('p', analysis.summary));
    const flow = doc.createElement('ol'); flow.className = 'ai-pitch-flow';
    for (const item of analysis.pitch_flow) flow.append(node('li', item.description));
    section('配球の流れ', flow);
    for (const [title, items] of [['ポイント', analysis.points], ['データ上わからないこと', analysis.limitations]]) {
      const list = doc.createElement('ul'); for (const text of items) list.append(node('li', text)); section(title, list);
    }
    container.replaceChildren(...sections);
  }
  return { render };
});
