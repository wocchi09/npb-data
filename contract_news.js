(function(){
  "use strict";
  const $=id=>document.getElementById(id);
  let data=null;
  const esc=value=>String(value??"").replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
  const featuredPublishers=["日刊スポーツ","スポーツ報知","スポニチアネックス","サンケイスポーツ","中日スポーツ","デイリースポーツ"];
  const featuredPublisher=publisher=>featuredPublishers.some(name=>String(publisher||"").normalize("NFKC").includes(name));
  function safeUrl(value){try{const u=new URL(value);return u.protocol==="https:"&&["news.yahoo.co.jp","sports.yahoo.co.jp"].includes(u.hostname)?u.href:null}catch{return null}}
  function render(){
    if(!data)return;
    const team=$("team").value;const query=$("query").value.trim().normalize("NFKC").replace(/\s/g,"").toLowerCase();
    const publisher=$("publisher").value;
    const rows=data.articles.filter(row=>($("kind").value==="all"||!row.is_commentary)&&(!team||(team==="unknown"?!row.teams.length:row.teams.includes(team)))&&(!publisher||(publisher==="featured"?featuredPublisher(row.publisher):row.publisher===publisher))&&(!query||row.title.normalize("NFKC").replace(/\s/g,"").toLowerCase().includes(query)));
    $("count").textContent=`${rows.length}件 / 収集済み${data.articles.length}件`;
    $("news").innerHTML=rows.length?rows.map(row=>{
      const url=safeUrl(row.url);
      const mentions=row.mentioned_players?.length?`<p>見出しに登場：${row.mentioned_players.map(esc).join("、")}</p>`:"";
      return `<article class="news-card"><time datetime="${esc(row.published_at)}">${esc(row.published_at.slice(0,16).replace("T"," "))} JST</time><div class="teams">${(row.teams.length?row.teams:["球団未特定"]).map(t=>`<span class="team-badge">${esc(t)}</span>`).join("")}</div><h3>${esc(row.display_title)}</h3>${mentions}<p class="credit"><span class="outlet-tag ${featuredPublisher(row.publisher)?"featured":""}">${esc(row.outlet_type|| (featuredPublisher(row.publisher)?"主要野球ニュース":"その他の配信元"))}</span>${esc(row.publisher)} / スポナビ掲載</p><p class="context">${esc(row.context)}</p><details><summary>元記事の見出しを確認（媒体の原文）</summary><p>${esc(row.title)}</p></details>${url?`<a class="button primary" href="${esc(url)}" target="_blank" rel="noopener noreferrer">元記事を読む ↗</a>`:""}</article>`;
    }).join(""):'<div class="empty-card">この条件に該当する収集済みニュースはありません。未取得の記事や未発表の情報を補完していません。</div>';
  }
  async function init(){try{
    const response=await fetch("data/contract_news.json",{cache:"no-store"});if(!response.ok)throw new Error("収集データを読み込めませんでした");
    data=await response.json();
    $("updated").textContent=`対象：${data.since}以降 / 最終確認：${data.checked_at.slice(0,16).replace("T"," ")} JST`;
    $("team").innerHTML='<option value="">全12球団・球団未特定</option>'+data.teams.map(t=>`<option value="${esc(t)}">${esc(t)}</option>`).join("")+'<option value="unknown">球団未特定</option>';
    const publishers=[...new Set(data.articles.map(row=>row.publisher).filter(Boolean))].sort((a,b)=>a.localeCompare(b,"ja"));
    $("publisher").innerHTML='<option value="">スポナビ掲載の全媒体</option><option value="featured">主要6媒体を優先</option>'+publishers.map(name=>`<option value="${esc(name)}">${esc(name)}</option>`).join("");
    $("coverage").hidden=false;
    $("coverage").textContent=data.coverage_limited?"一部の検索で取得上限に達しています。掲載件数は全件数ではありません。元のニュース一覧も確認してください。":"公開ニュース一覧で確認できた範囲を掲載しています。本文だけに契約情報がある記事や、検索結果から消えた記事は取得できない場合があります。";
    render();
  }catch(error){$("updated").textContent="取得状況を確認できません";$("news").innerHTML=`<div class="error-card">${esc(error.message)}。上のスポナビへのリンクから確認できます。</div>`}}
  $("team").addEventListener("change",render);$("publisher").addEventListener("change",render);$("kind").addEventListener("change",render);$("query").addEventListener("input",render);init();
})();
