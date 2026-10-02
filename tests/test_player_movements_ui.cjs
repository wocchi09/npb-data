// No browser/network dependencies: exercise the real renderer using DOM stubs.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {value:'',innerHTML:'',textContent:'',listeners:{},addEventListener(k,fn){this.listeners[k]=fn;}});
  return elements.get(id);
}
const row = {
  name:'試験 太郎',team:'楽天',category:'自由契約',categories:['自由契約','育成契約関連'],
  updated_date:'2026-09-30', note:'育成再契約を打診',
  salary:{amount_man_yen:8000,season:'2026',source_url:'https://www.daily.co.jp/baseball/koukai/tb0000000419.shtml'},
  stats:{season:'2026',yearly:[],career:[{kind:'batting',games:1,plate_appearances:0,batting_average:0,on_base_percentage:0,slugging_percentage:0},{kind:'pitching',games:1,innings:'0',era:0}],source_url:'https://npb.jp/bis/players/123.html'},
  observations:[{source:'日刊スポーツ',name:'試験太郎',updated_date:'2026-09-30',note:'<script>unsafe</script>',source_url:'javascript:alert(1)',date_kind:'記事全体の更新日'}]
};
const data={checked_at:'2026-09-30T12:00:00+09:00',teams:['楽天'],movements:[row],sources:{nikkan:{stale:true}}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../player_movements.js'),'utf8'),{
  document:{getElementById:element,querySelectorAll:()=>[]}, URL,
  fetch:async()=>({ok:true,json:async()=>data})
});
setImmediate(()=>{
  const html=element('movements-body').innerHTML;
  assert.match(html,/8,000万円/);
  assert.match(html,/2026年度・推定/);
  assert.match(html,/打席なし/);
  assert.match(html,/防御率 —/);
  assert.match(html,/0試合とは限りません/);
  assert.match(html,/&lt;script&gt;/);
  assert.doesNotMatch(html,/href="javascript:/);
  assert.match(element('movement-source-status').textContent,/日刊スポーツ：未取得/);
  assert.match(element('movement-cards').innerHTML,/movement-card/);
  assert.match(element('movement-cards').innerHTML,/team-eagles/);
  assert.match(element('movement-cards').innerHTML,/team-pill/);
  assert.match(element('movement-cards').innerHTML,/推定年俸/);
  assert.match(element('movement-cards').innerHTML,/今季・通算成績/);
  element('movement-category').value='育成契約関連';
  element('movement-category').listeners.change();
  assert.match(element('movements-count').textContent,/1人/);
  element('movement-query').value='該当なし';
  element('movement-query').listeners.input();
  assert.match(element('movements-body').innerHTML,/colspan="9"/);
  console.log('PASS: salary, provenance, zero denominators, escaping, filters, empty state');
});
