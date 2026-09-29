(function(){
  "use strict";
  const $=id=>document.getElementById(id);
  const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const norm=v=>String(v??"").normalize("NFKC").replace(/\s/g,"").toLowerCase();
  const categories=["自由契約","引退","FA権取得","FA宣言","FA移籍","FA（区分未確認）","トレード","移籍","育成契約関連","来季契約なし","入団","退団","その他"];
  let rows=[],sort="updated_date",direction=-1;
  function sourceUrl(value){try{const u=new URL(value);return u.origin==="https://baseball.yahoo.co.jp"&&u.pathname==="/npb/transfer"?u.href:null}catch{return null}}
  function render(){
    const team=$("movement-team").value,kind=$("movement-category").value,year=$("movement-year").value,q=norm($("movement-query").value);
    const filtered=rows.filter(r=>(!team||r.team===team)&&(!kind||r.category===kind)&&(!year||r.updated_date.startsWith(year))&&(!q||norm([r.name,r.team,r.note,r.destination].join(" ")).includes(q)));
    filtered.sort((a,b)=>direction*String(a[sort]??"").localeCompare(String(b[sort]??""),"ja")||a.name.localeCompare(b.name,"ja"));
    $("movements-count").textContent=`${filtered.length}件 / 掲載${rows.length}件（選手・更新単位）`;
    $("movements-body").innerHTML=filtered.length?filtered.map(r=>{
      const source=sourceUrl(r.source_url);
      return `<tr><td class="date-cell">${esc(r.updated_date)}</td><td>${esc(r.team)}</td><th scope="row">${esc(r.name)}<small>${esc(r.position)}${r.development_player?" · 育成":""}</small></th><td><span class="movement-badge">${esc(r.category)}</span><small>${esc(r.status)}</small></td><td>${esc(r.destination||"記載なし")}</td><td class="movement-note">${esc(r.note||"記載なし")}</td><td>${source?`<a href="${esc(source)}" target="_blank" rel="noopener noreferrer">スポナビ ↗</a>`:"出典未確認"}<small>掲載情報</small></td></tr>`;
    }).join(""):'<tr><td colspan="7">この条件に該当する掲載情報はありません。未掲載・未発表の動きは補完していません。</td></tr>';
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
    $("movement-team").innerHTML='<option value="">全12球団</option>'+data.teams.map(t=>`<option>${esc(t)}</option>`).join("");
    $("movement-category").innerHTML='<option value="">すべて</option>'+categories.map(t=>`<option>${esc(t)}</option>`).join("");
    $("movement-year").innerHTML='<option value="">すべて</option>'+[...new Set(rows.map(r=>r.updated_date.slice(0,4)))].sort().reverse().map(y=>`<option>${esc(y)}</option>`).join("");render();
  }catch(error){$("movements-updated").textContent="取得状況を確認できません";$("movements-body").innerHTML=`<tr><td colspan="7">${esc(error.message)}。<a href="https://baseball.yahoo.co.jp/npb/transfer" target="_blank" rel="noopener noreferrer">スポナビの入退団情報</a>を確認してください。</td></tr>`}}
  init();
})();
