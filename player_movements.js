(function(){
  "use strict";
  const $=id=>document.getElementById(id);
  const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const norm=v=>String(v??"").normalize("NFKC").replace(/\s/g,"").toLowerCase();
  const categories=["自由契約","引退","引退（意向）","FA権取得","FA宣言","FA移籍","FA（区分未確認）","トレード","移籍","育成契約関連","契約解除","来季契約なし","入団","退団","その他"];
  const teamClasses={"ソフトバンク":"hawks","日本ハム":"fighters","ロッテ":"marines","楽天":"eagles","西武":"lions","オリックス":"buffaloes","阪神":"tigers","広島":"carp","DeNA":"baystars","横浜DeNA":"baystars","巨人":"giants","ヤクルト":"swallows","中日":"dragons"};
  let rows=[],sort="updated_date",direction=-1;
  const teamClass=team=>teamClasses[team]||"neutral";
  function sourceUrl(value){try{const u=new URL(value);return u.protocol==="https:"&&(
    (u.hostname==="baseball.yahoo.co.jp"&&u.pathname==="/npb/transfer")||
    (u.hostname==="www.nikkansports.com"&&/^\/baseball\/news\/\d+\.html$/.test(u.pathname))||
    (u.hostname==="www.daily.co.jp"&&/^\/baseball\/koukai\/tb\d+\.shtml$/.test(u.pathname))||
    (u.hostname==="npb.jp"&&/^\/bis\/players\/\d+\.html$/.test(u.pathname)))?u.href:null}catch{return null}}
  const stamp=v=>v?esc(String(v).slice(0,16).replace("T"," ")):"未取得";
  function link(url,label){const safe=sourceUrl(url);return safe?`<a href="${esc(safe)}" target="_blank" rel="noopener noreferrer">${esc(label)} ↗</a>`:esc(label)}
  function salaryView(s){return s?`<strong>${Number(s.amount_man_yen).toLocaleString("ja-JP")}万円</strong><small>${esc(s.season)}年度・推定${s.stale?" / 更新待ち":""}</small><small>${link(s.source_url,"デイリースポーツ")}</small><small>取得 ${stamp(s.as_of)}</small>`:"<small>確認できる年俸なし<br>未掲載・氏名照合できない場合は補完しません</small>"}
  function statLine(s){
    const v=(key,decimals)=>s[key]==null?"—":decimals==null?esc(s[key]):Number(s[key]).toFixed(decimals);
    if(s.kind==="pitching")return `${v("games")}登板 / ${v("innings")}回<br>${v("wins")}勝 ${v("losses")}敗 ${v("saves")}S ${v("holds")}H<br>防御率 ${Number(s.innings)>0?v("era",2):"—"} / ${v("strikeouts")}奪三振`;
    if(s.plate_appearances===0)return `${v("games")}試合 / 0打席<br>打席なし（打率・OPSは算出しません）`;
    const ops=s.plate_appearances>0&&s.at_bats>0&&s.on_base_percentage!=null&&s.slugging_percentage!=null?(s.on_base_percentage+s.slugging_percentage).toFixed(3):"—";
    return `${v("games")}試合 / ${v("plate_appearances")}打席<br>打率 ${s.at_bats>0?v("batting_average",3):"—"} / OPS ${ops}<br>${v("hits")}安打 ${v("home_runs")}本 ${v("runs_batted_in")}打点 ${v("stolen_bases")}盗塁`;
  }
  function statsView(s){if(!s)return '<small>選手を一意に照合できないため成績未取得</small>';
    const section=(title,items)=>`<h4>${esc(title)}</h4>${items.length?items.map(x=>`<p>${x.team?`<small>${esc(x.team)}</small>`:""}${statLine(x)}</p>`).join(""):"<p>成績データなし（0試合とは限りません）</p>"}`;
    return `<details class="movement-stats"><summary>${esc(s.season)}年・通算を見る</summary>${section(s.season+"年（一軍）",s.yearly)}${section("NPB通算（一軍）",s.career)}<small>${link(s.source_url,"NPB公式")}</small><small>取得 ${stamp(s.as_of)}${s.stale?" / 更新待ち":""}</small><small>OPSは掲載出塁率＋長打率（丸め誤差あり）。投球回の小数はアウト数です。</small></details>`;
  }
  function observationsView(r){const entries=r.observations||[r];return `<details><summary>${entries.length}件の掲載情報</summary>`+entries.map(o=>`<p>${link(o.source_url,o.source||"掲載元")}<small>${esc(o.name)}</small><small>${esc(o.date_kind||"掲載元の選手更新日")}：${esc(o.updated_date)}</small><small>${esc(o.note||o.status)}${o.stale?"（更新待ち・前回取得分）":""}</small></p>`).join("")+"</details>"}
  function teamPill(team){return `<span class="team-pill team-${teamClass(team)}">${esc(team)}</span>`}
  function cardsView(items){return items.length?items.map(r=>`<article class="movement-card team-${teamClass(r.team)}"><header><div><p class="movement-card-meta">${esc(r.updated_date)} · ${esc(r.date_kind||"掲載元の選手更新日")}</p><h3>${esc(r.name)} ${teamPill(r.team)}</h3><p class="movement-position">${esc(r.position)}${r.development_player?" · 育成":""}</p></div><div class="movement-card-badges">${(r.categories||[r.category]).map(c=>`<span class="movement-badge">${esc(c)}</span>`).join("")}</div></header><p class="movement-card-note">${esc(r.note||"掲載内容なし")}</p>${r.destination?`<p class="movement-destination"><b>移籍・入団先</b>${esc(r.destination)}</p>`:""}<div class="movement-card-details"><details><summary>推定年俸</summary>${salaryView(r.salary)}</details><details><summary>今季・通算成績</summary>${statsView(r.stats)}</details><details><summary>出典・掲載内容</summary>${observationsView(r)}</details></div></article>`).join(""):'<p class="movement-card-empty">この条件に該当する掲載情報はありません。未掲載・未発表の動きは補完していません。</p>'}
  function render(){
    const team=$("movement-team").value,kind=$("movement-category").value,year=$("movement-year").value,q=norm($("movement-query").value);
    const filtered=rows.filter(r=>(!team||r.team===team)&&(!kind||(r.categories||[r.category]).includes(kind))&&(!year||r.updated_date.startsWith(year))&&(!q||norm([r.name,r.team,r.note,r.destination].join(" ")).includes(q)));
    filtered.sort((a,b)=>direction*String(a[sort]??"").localeCompare(String(b[sort]??""),"ja")||a.name.localeCompare(b.name,"ja"));
    $("movements-count").textContent=`${filtered.length}人 / 掲載${rows.length}人（同球団の同一選手は統合）`;
    $("movement-cards").innerHTML=cardsView(filtered);
    $("movements-body").innerHTML=filtered.length?filtered.map(r=>{
      return `<tr class="team-${teamClass(r.team)}"><td class="date-cell">${esc(r.updated_date)}<small>${esc(r.date_kind||"掲載元の選手更新日")}</small></td><td>${teamPill(r.team)}</td><th scope="row">${esc(r.name)}<small>${esc(r.position)}${r.development_player?" · 育成":""}</small></th><td>${(r.categories||[r.category]).map(c=>`<span class="movement-badge">${esc(c)}</span>`).join(" ")}</td><td>${esc(r.destination||"記載なし")}</td><td class="movement-note">${esc(r.note||"記載なし")}</td><td class="movement-salary">${salaryView(r.salary)}</td><td>${statsView(r.stats)}</td><td class="movement-sources">${observationsView(r)}</td></tr>`;
    }).join(""):'<tr><td colspan="9">この条件に該当する掲載情報はありません。未掲載・未発表の動きは補完していません。</td></tr>';
  }
  document.querySelectorAll("[data-movement-sort]").forEach(button=>{
    const label=button.textContent.replace(/ [↓↑]$/,"");
    button.dataset.label=label;
    button.addEventListener("click",()=>{
      const key=button.dataset.movementSort;
      direction=key===sort?-direction:(key==="updated_date"?-1:1);sort=key;
      document.querySelectorAll("[data-movement-sort]").forEach(b=>{b.textContent=b.dataset.label+(b===button?(direction===1?" ↑":" ↓"):"");b.parentElement.setAttribute("aria-sort",b===button?(direction===1?"ascending":"descending"):"none")});render();
    });
  });
  ["movement-team","movement-category","movement-year"].forEach(id=>$(id).addEventListener("change",render));
  $("movement-query").addEventListener("input",render);
  async function init(){try{
    const response=await fetch("data/player_movements.json",{cache:"no-store"});
    if(!response.ok)throw new Error("入退団データを読み込めませんでした");
    const data=await response.json();
    if(!Array.isArray(data.movements))throw new Error("入退団データの形式を確認できませんでした");
    rows=data.movements;
    $("movements-updated").textContent=`最終取得：${data.checked_at.slice(0,16).replace("T"," ")} JST`;
    const sources=Object.entries(data.sources||{});
    const failedSalary=Object.entries(data.salary_sources||{}).filter(([,s])=>s.stale).map(([team])=>team);
    $("movement-source-status").textContent=sources.map(([key,s])=>`${key==="nikkan"?"日刊スポーツ":"スポナビ"}：${s.stale?(s.last_success_at?"更新待ち（前回取得分）":"未取得"):"取得済み"} / 最終成功 ${s.last_success_at?.slice(0,16).replace("T"," ")||"未取得"}`).join(" ｜ ")+(failedSalary.length?` ｜ 年俸更新待ち：${failedSalary.join("・")}`:"");
    $("movement-team").innerHTML='<option value="">全12球団</option>'+data.teams.map(t=>`<option>${esc(t)}</option>`).join("");
    $("movement-category").innerHTML='<option value="">すべて</option>'+categories.map(t=>`<option>${esc(t)}</option>`).join("");
    $("movement-year").innerHTML='<option value="">すべて</option>'+[...new Set(rows.map(r=>r.updated_date.slice(0,4)))].sort().reverse().map(y=>`<option>${esc(y)}</option>`).join("");render();
  }catch(error){$("movements-updated").textContent="取得状況を確認できません";$("movements-body").innerHTML=`<tr><td colspan="9">${esc(error.message)}。<a href="https://baseball.yahoo.co.jp/npb/transfer" target="_blank" rel="noopener noreferrer">スポナビの入退団情報</a>を確認してください。</td></tr>`}}
  init();
})();
