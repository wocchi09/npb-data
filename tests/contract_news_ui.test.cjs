const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {value:'', innerHTML:'', textContent:'', className:'', listeners:{},
    classList:{toggle(){}}, addEventListener(name, fn){this.listeners[name]=fn;}, setAttribute(){}});
  return elements.get(id);
}
const buttons = ['cards', 'list'].map(view => ({dataset:{newsView:view}, classList:{toggle(){}}, setAttribute(){}, addEventListener(name, fn){this.listener=fn;}}));
const data = {since:'2026-09-28', checked_at:'2026-10-02T12:00:00+09:00', coverage_limited:false, teams:['阪神'], articles:[{
  title:'【阪神】来季契約を結ばないと発表', display_title:'来季契約・契約終了に関する記事', teams:['阪神'],
  published_at:'2026-10-02T10:30+09:00', publisher:'スポーツ報知', url:'https://news.yahoo.co.jp/articles/test', context:'関連報道・本文確認が必要', is_commentary:false
}]};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../contract_news.js'), 'utf8'), {
  document:{getElementById:element, querySelectorAll(selector){return selector === '[data-news-view]' ? buttons : [];}}, URL,
  fetch:async()=>({ok:true,json:async()=>data})
});
setImmediate(()=>{
  assert.match(element('news').innerHTML, /news-card/);
  assert.match(element('publisher').innerHTML, /主要6媒体を優先/);
  buttons[1].listener();
  assert.equal(element('news').className, 'news-list news-list-compact');
  assert.match(element('news').innerHTML, /news-row/);
  assert.match(element('news').innerHTML, /【阪神】来季契約を結ばないと発表/);
  console.log('PASS: news cards, outlet filter, compact list view');
});
