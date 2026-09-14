const {test}=require('node:test');
const assert=require('node:assert/strict');
const M=require('../workbench_model.js');
const state={a0:'2026-04-01',a1:'2026-04-30',b0:'2026-05-01',b1:'2026-05-31'};
const ab=(id,date,extra={})=>({date,game_id:'123',atbat_index:id,batter:'打者',pitcher:'投手',bat_hand:'左打',pit_hand:'右投',risp:false,ab:1,hit:1,single:1,double:0,triple:0,hr:0,bb:0,hbp:0,sf:0,...extra});
const pitch=(id,no,extra={})=>({date:'2026-04-02',game_id:'123',atbat_index:id,pitch_no:no,pitch_type:'ストレート',zone_label:'高め・外',speed_kmh:150,is_swing:true,is_miss:false,in_zone:false,...extra});
test('date validation disallows overlaps, reversed windows and impossible dates',()=>{
  assert.equal(M.validate(state),'');
  for(const changes of [{b0:'2026-04-30'},{a0:'2026-05-01'},{a0:'2026-02-30'}])assert.notEqual(M.validate({...state,...changes}),'');
});
test('OPS is per PA and pitch-filtered cohort includes only matching atbats',()=>{
  const data={player:{role:'pitcher'},atbats:[ab('1','2026-04-02'),ab('2','2026-04-02',{hit:0,single:0})],pitches:[pitch('1',1),pitch('1',2),pitch('2',1,{pitch_type:'フォーク'})]};
  const all=M.compare(data,state);assert.equal(all.sa.pa,2);assert.equal(all.sa.ops,1);
  const filtered=M.compare(data,{...state,type:'ストレート'});assert.equal(filtered.sa.pa,1);assert.equal(filtered.sa.ops,2);assert.equal(filtered.sa.pitches,2);assert.equal(filtered.sb.ops,null);
});
test('missing speeds, classifications and PA components never turn into zeros',()=>{
  const s=M.summarize({atbats:[ab('1','2026-04-02',{sf:null})],pitches:[pitch('1',1,{speed_kmh:null,is_swing:null,is_miss:null,in_zone:null}),pitch('1',2,{speed_kmh:0,is_swing:false,is_miss:false})]});
  assert.equal(s.speed,null);assert.equal(s.whiff,null);assert.equal(s.ops,null);assert.equal(s.complete_pa,0);assert.equal(s.quality.result,1);assert.equal(s.chase,0);
});
test('Wilson interval supports zero successes and zero sample without fabricating certainty',()=>{
  assert.equal(M.wilson(0,0),null);const ci=M.wilson(0,10);assert.ok(ci[0]>=0&&ci[1]>.25);assert.ok(M.wilson(5,10)[0]<.5&&M.wilson(5,10)[1]>.5);
});
test('sequences keep actual predecessor, never bridge missing pitches or different PAs',()=>{
  const ps=[pitch('1',1),pitch('1',2,{pitch_type:'フォーク',is_miss:true}),pitch('1',4,{pitch_type:'フォーク'}),pitch('2',1,{pitch_type:'フォーク'})];
  const data={player:{role:'pitcher'},atbats:[ab('1','2026-04-02'),ab('2','2026-04-02')],pitches:ps};
  const r=M.compare(data,{...state,type:'フォーク'});assert.equal(r.seqA.length,1);assert.match(r.seqA[0].label,/ストレート.*フォーク/);assert.equal(r.seqA[0].n,1);assert.equal(r.seqA[0].whiff,1);assert.equal(r.seqA[0].refs.length,1);
});
test('hand and RISP filters preserve unknown states as unknown',()=>{
  const data={player:{role:'pitcher'},atbats:[ab('1','2026-04-02'),ab('2','2026-04-02',{risp:null}),ab('3','2026-04-02',{bat_hand:'右打'})],pitches:[]};
  assert.equal(M.compare(data,{...state,hand:'左打',risp:'no'}).sa.pa,1);
});
test('deep links identify the exact source PA with no array-index substitution',()=>{
  const link=M.replay(ab('0110200','2026-04-02'));const url=new URL(link,'https://example.test/npb/');assert.equal(url.searchParams.get('atbat'),'0110200');assert.equal(url.searchParams.get('game'),'data/2026/04/02/123.json');assert.equal(M.replay(ab('../bad','2026-04-02')),null);
});
test('published change candidates reproduce from the evidence used by the UI',()=>{
  const fs=require('node:fs'),path=require('node:path');
  const base=path.join(__dirname,'../data/2026/dataset/workbench');
  const index=JSON.parse(fs.readFileSync(path.join(base,'index.json')));
  const s=Object.fromEntries(['a0','a1','b0','b1'].map((k,i)=>[k,index.periods[i]]));
  for(const alert of index.alerts){
    const data=M.decode(JSON.parse(fs.readFileSync(path.join(base,alert.player+'.json'))));
    const result=M.compare(data,s);
    let values;
    if(alert.metric==='直球平均球速')values=[result.sa.speed,result.sb.speed];
    else if(alert.metric==='空振り率')values=[result.sa.whiff,result.sb.whiff];
    else {const type=alert.metric.split('：')[1];values=[result.sa,result.sb].map(x=>(x.types[type]||0)/Object.values(x.types).reduce((n,v)=>n+v,0));}
    assert.ok(Math.abs(values[0]-alert.before)<1e-10,alert.name+' before');
    assert.ok(Math.abs(values[1]-alert.after)<1e-10,alert.name+' after');
  }
});
test('all published PA evidence references resolve to an existing original atbat',()=>{
  const fs=require('node:fs'),path=require('node:path'),root=path.resolve(__dirname,'..');
  const base=path.join(root,'data/2026/dataset/workbench');
  const index=JSON.parse(fs.readFileSync(path.join(base,'index.json'))),cache=new Map();
  for(const player of index.players){
    const payload=JSON.parse(fs.readFileSync(path.join(base,player.id+'.json')));
    for(const row of payload.atbats){
      const [date,game,id]=row,file=path.join(root,'data',date.replace(/-/g,'/'),game+'.json');
      if(!cache.has(file))cache.set(file,new Set(JSON.parse(fs.readFileSync(file)).atbats.filter(a=>a.valid!==false).map(a=>a.index)));
      assert.ok(cache.get(file).has(id),player.name+' '+date+' '+game+' '+id);
    }
  }
});
