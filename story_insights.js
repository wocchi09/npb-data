(function(){
  "use strict";

  const TEAM_COLORS={"ソフトバンク":"#f7b500","日本ハム":"#1e88e5","オリックス":"#6b1d5c","楽天":"#a71930","西武":"#143d73","ロッテ":"#111827","阪神":"#f5c400","DeNA":"#0b79bf","巨人":"#f97316","中日":"#2563eb","広島":"#d71920","ヤクルト":"#159447"};
  const state={data:null,tab:"wins",pitcherKey:"",pitchTeam:"すべて",trendTeam:"ソフトバンク"};
  const esc=v=>String(v==null?"":v).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const pct=v=>v==null?"-":(Number(v)*100).toFixed(1)+"%";
  const num=(v,d=3)=>v==null||!Number.isFinite(Number(v))?"-":Number(v).toFixed(d).replace(/^0\./,".");
  const signed=(v,d=3)=>v==null?"-":(Number(v)>0?"+":"")+Number(v).toFixed(d);
  const teamColor=t=>TEAM_COLORS[t]||"#6b7280";

  async function load(){
    const year=new URLSearchParams(location.search).get("year")||String(new Date().getFullYear());
    try{
      const res=await fetch(`data/${encodeURIComponent(year)}/_story_insights.json?t=${Date.now()}`);
      if(!res.ok)throw new Error(`${res.status} ${res.statusText}`);
      state.data=await res.json();
      const pitchers=state.data.two_strike_pitchers||[];
      state.pitcherKey=(pitchers.find(p=>p.team==="ソフトバンク")||pitchers[0]||{}).key||"";
      if(!(state.data.team_trends||[]).some(x=>x.team===state.trendTeam))state.trendTeam=(state.data.team_trends||[])[0]?.team||"";
      document.getElementById("statusBadge").textContent=`${state.data.season} / ${String(state.data.generated_at||"").slice(0,16).replace("T"," ")}`;
      document.querySelectorAll(".tab").forEach(btn=>btn.addEventListener("click",()=>{state.tab=btn.dataset.tab;document.querySelectorAll(".tab").forEach(x=>x.classList.toggle("on",x===btn));render();}));
      render();
    }catch(err){
      console.error(err);
      document.getElementById("statusBadge").textContent="data unavailable";
      document.getElementById("app").innerHTML=`<div class="error-card"><b>分析データを読み込めませんでした。</b><br><small>${esc(err.message)}</small><div class="note">GitHub Actions で story insights を生成してください。</div></div>`;
    }
  }

  function render(){if(!state.data)return;if(state.tab==="wins")renderWins();else if(state.tab==="twoStrike")renderTwoStrike();else renderTrend();}

  function renderWins(){
    const block=state.data.latest_games||{},games=block.games||[];
    let h=`<div class="hero-card"><h2>${esc((block.date||"-").replace(/-/g,"/"))} 今日なぜ勝った？</h2><p>勝ったチームのボックススコアから、目立った勝利要素を整理。因果を断定せず「数字で見える材料」として読む。</p></div>`;
    if(!games.length)h+=`<div class="empty card">対象日の試合がありません。</div>`;
    games.forEach(g=>{
      const awayWin=g.winner===g.away,homeWin=g.winner===g.home;
      const away=`<span class="${awayWin?"winner":""}">${esc(g.away)} ${g.away_score}</span>`;
      const home=`<span class="${homeWin?"winner":""}">${g.home_score} ${esc(g.home)}</span>`;
      if(!g.winner){h+=`<article class="card"><div class="game-head"><div class="score">${away} － ${home}</div><div class="venue">${esc(g.stadium||"")}</div></div><div class="note">${esc(g.note||"")}</div></article>`;return;}
      const b=g.top_batter||{},s=g.starter||{},bp=g.bullpen||{};
      h+=`<article class="card" style="border-top:4px solid ${teamColor(g.winner)}"><div class="game-head"><div class="score">${away} － ${home}</div><div class="venue">${esc(g.stadium||"")}<br>${esc(g.winner)} 勝利</div></div><p class="headline">${esc(g.headline||"")}</p><div class="tags">${(g.tags||[]).map(x=>`<span class="tag">${esc(x)}</span>`).join("")}</div><div class="factor-grid"><div class="factor"><span>打撃の中心</span><b>${esc(b.name||"-")}</b><small>${b.hits||0}安打 / ${b.hr||0}本塁打 / ${b.rbi||0}打点</small></div><div class="factor"><span>先発</span><b>${esc(s.name||"-")}</b><small>${esc(s.innings||"-")}回 / 自責${s.earned_runs??"-"} / ${s.so??"-"}奪三振</small></div><div class="factor"><span>救援陣</span><b>${esc(bp.innings||"-")}回 自責${bp.earned_runs??"-"}</b><small>${bp.so??0}奪三振 / WHIP ${num(bp.whip,2)}</small></div></div><div class="note">${esc(g.note||"")}</div></article>`;
    });
    document.getElementById("app").innerHTML=h;
  }

  function renderTwoStrike(){
    const pitchers=state.data.two_strike_pitchers||[],teams=[...new Set(pitchers.map(p=>p.team))].sort();
    let filtered=state.pitchTeam==="すべて"?pitchers:pitchers.filter(p=>p.team===state.pitchTeam);
    if(!filtered.some(p=>p.key===state.pitcherKey))state.pitcherKey=filtered[0]?.key||"";
    const p=filtered.find(x=>x.key===state.pitcherKey)||filtered[0];
    let h=`<div class="hero-card"><h2>追い込んでから何を投げる？</h2><p>2ストライク後の球種選択・三振決着球率・左右打者への使い分けを投手別に見る。</p></div><section class="card"><div class="controls"><div class="field"><label>球団</label><select id="pitchTeam"><option>すべて</option>${teams.map(t=>`<option${t===state.pitchTeam?" selected":""}>${esc(t)}</option>`).join("")}</select></div><div class="field"><label>投手</label><select id="pitcher">${filtered.map(x=>`<option value="${esc(x.key)}"${x.key===state.pitcherKey?" selected":""}>${esc(x.team)} / ${esc(x.name)}</option>`).join("")}</select></div></div></section>`;
    if(!p){document.getElementById("app").innerHTML=h+`<div class="empty card">条件に合う投手がいません。</div>`;bindPitch();return;}
    const fin=p.best_finisher||{};
    h+=`<section class="card" style="border-top:4px solid ${teamColor(p.team)}"><div class="team-title"><span class="team-dot" style="--team:${teamColor(p.team)}"></span><h3>${esc(p.name)} <small>${esc(p.team)} / ${esc(p.hand||"-")}</small></h3></div><div class="kpis"><div class="kpi"><b>${p.pitches}</b><span>2ストライク後の投球</span></div><div class="kpi"><b>${pct(p.k_finish_rate)}</b><span>三振決着球率</span></div><div class="kpi"><b>${pct(p.whiff_rate)}</b><span>空振り三振決着率</span></div><div class="kpi"><b>${esc(fin.pitch_type||"-")}</b><span>高決着率の球種</span></div></div><div class="note">${esc(state.data.notes?.two_strike||"")}</div></section><div class="split-grid"><section class="card"><h3>球種配分</h3><table class="pitch-table"><thead><tr><th>球種</th><th>割合</th><th>三振決着</th><th>空振り三振決着</th><th>平均球速</th></tr></thead><tbody>${(p.pitch_types||[]).map(x=>`<tr><td><b>${esc(x.pitch_type)}</b><br><small>${esc(x.top_zone||"")}</small></td><td>${pct(x.share)}</td><td>${pct(x.k_finish_rate)}</td><td>${pct(x.whiff_rate)}</td><td>${x.avg_speed==null?"-":num(x.avg_speed,1)+"km/h"}</td></tr>`).join("")}</tbody></table></section><section class="card"><h3>左右打者への使い分け</h3>${splitBlock("右打者",p.vs_right)}${splitBlock("左打者",p.vs_left)}<h3 style="margin-top:20px">球種シェア</h3>${(p.pitch_types||[]).slice(0,5).map(x=>`<div class="bar-row"><b>${esc(x.pitch_type)}</b><div class="track"><div class="fill" style="width:${Math.max(2,(x.share||0)*100)}%"></div></div><span>${pct(x.share)}</span></div>`).join("")}</section></div>`;
    document.getElementById("app").innerHTML=h;bindPitch();
  }

  function splitBlock(label,x){x=x||{};return `<div class="factor" style="margin-bottom:9px"><span>${label}</span><b>${esc(x.top_pitch||"-")} ${x.top_pitch_share==null?"":pct(x.top_pitch_share)}</b><small>${x.pitches||0}球 / 三振決着球率 ${pct(x.k_finish_rate)}</small></div>`;}
  function bindPitch(){const team=document.getElementById("pitchTeam"),pitcher=document.getElementById("pitcher");if(team)team.onchange=()=>{state.pitchTeam=team.value;renderTwoStrike();};if(pitcher)pitcher.onchange=()=>{state.pitcherKey=pitcher.value;renderTwoStrike();};}

  function renderTrend(){
    const rows=state.data.team_trends||[],row=rows.find(x=>x.team===state.trendTeam)||rows[0];
    let h=`<div class="hero-card"><h2>直近10試合で何が変わった？</h2><p>シーズン全体を基準線にして、最近10試合の打撃・投球・得失点がどちらへ動いたかを見る。</p></div><section class="card"><div class="controls"><div class="field"><label>球団</label><select id="trendTeam">${rows.map(x=>`<option${x.team===state.trendTeam?" selected":""}>${esc(x.team)}</option>`).join("")}</select></div></div></section>`;
    if(!row){document.getElementById("app").innerHTML=h+`<div class="empty card">球団データがありません。</div>`;return;}
    const rr=row.recent.record||{},sr=row.season.record||{},rb=row.recent.batting||{},sb=row.season.batting||{},rp=row.recent.pitching||{},sp=row.season.pitching||{},d=row.delta||{};
    h+=`<section class="card" style="border-top:4px solid ${teamColor(row.team)}"><div class="team-title"><span class="team-dot" style="--team:${teamColor(row.team)}"></span><h3>${esc(row.team)}</h3><span class="record">直近 ${rr.wins||0}-${rr.losses||0}${rr.ties?`-${rr.ties}`:""}</span></div><div class="tags">${(row.changes||[]).map(x=>`<span class="tag">${esc(x)}</span>`).join("")}</div><div class="metric-grid">${metric("OPS",rb.ops,sb.ops,d.ops,true,3)}${metric("得点 / 試合",rr.runs_per_game,sr.runs_per_game,d.runs_per_game,true,2)}${metric("防御率",rp.era,sp.era,d.era,false,2)}${metric("失点 / 試合",rr.allowed_per_game,sr.allowed_per_game,d.allowed_per_game,false,2)}${metric("K/9",rp.k9,sp.k9,rp.k9==null||sp.k9==null?null:rp.k9-sp.k9,true,2)}${metric("本塁打",rb.hr,sb.hr,null,true,0,"直近合計 / シーズン合計")}</div><div class="note">${esc(state.data.notes?.team_trends||"")}</div></section>`;
    document.getElementById("app").innerHTML=h;const sel=document.getElementById("trendTeam");if(sel)sel.onchange=()=>{state.trendTeam=sel.value;renderTrend();};
  }

  function metric(label,recent,season,delta,higherBetter,digits,sub){const n=delta==null?null:Number(delta);let cls="flat",word="差分なし";if(n!=null&&Math.abs(n)>.0001){const good=higherBetter?n>0:n<0;cls=good?"good":"bad";word=signed(n,digits);}return `<div class="metric"><div class="label">${esc(label)}</div><div class="values"><span class="recent">${num(recent,digits)}</span><span class="season">シーズン ${num(season,digits)}</span></div><div class="delta ${cls}">${esc(sub||word)}</div></div>`;}
  load();
})();
