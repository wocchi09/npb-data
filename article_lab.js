(function(root){
  "use strict";

  const state={data:null,template:"",scope:"hawksPriority",type:"all",activeText:"",activeFile:"article-brief.md"};
  const esc=value=>String(value??"").replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
  const list=(items)=>items?.length?items.map(x=>`* ${x}`).join("\n"):"* データ不足";
  const dateJP=value=>{const m=String(value||"").match(/^(\d{4})-(\d{2})-(\d{2})$/);return m?`${Number(m[2])}月${Number(m[3])}日`:"日付不明"};
  const safeFileName=value=>String(value||"article").normalize("NFKC").replace(/[\\/:*?"<>|\s]+/g,"-").replace(/^-+|-+$/g,"").slice(0,80)||"article";

  function sourceLine(src){
    if(!src)return "データ不足";
    const parts=[src.dataset,src.date,src.game_id?`game_id=${src.game_id}`:""].filter(Boolean);
    return parts.join(" / ");
  }
  function buildBrief(idea,dataDate){
    const facts=(idea.facts||[]).map(x=>`* ${x.label}: ${x.value}\n  source: ${sourceLine(x.source)}`).join("\n")||"* データ不足";
    return [
      "Article Brief","",`date: ${dataDate||"データ不足"}`,`type: ${idea.type||"unknown"}`,`team: ${idea.team||"データ不足"}`,"",
      "## Theme","",idea.theme||idea.title||"データ不足","","## Facts","",facts,"","## Angles","",list(idea.angles),"","## Cautions","",list(idea.cautions),"","## Source References","",
      (idea.source_refs||[]).map(x=>`* ${sourceLine(x)}`).join("\n")||"* データ不足"
    ].join("\n");
  }
  function fillPrompt(template,idea,dataDate){
    const values={
      THEME:idea.theme||"データ不足",TITLE:idea.title||"データ不足",REASON:idea.reason||"データ不足",
      FACTS:(idea.facts||[]).map(x=>`* **${x.label}**: ${x.value}  \n  出典: ${sourceLine(x.source)}`).join("\n")||"* データ不足",
      ANGLES:list(idea.angles),CAUTIONS:list(idea.cautions),
      SOURCES:(idea.source_refs||[]).map(x=>`* ${sourceLine(x)}`).join("\n")||"* データ不足",
      ARTICLE_BRIEF:buildBrief(idea,dataDate)
    };
    return String(template||"").replace(/\{\{([A-Z_]+)\}\}/g,(all,key)=>Object.prototype.hasOwnProperty.call(values,key)?values[key]:all);
  }
  function filterIdeas(ideas,scope,type){
    return (ideas||[]).filter(idea=>{
      const scopeOK=scope==="hawksPriority"||scope==="all"||(scope==="pacific"&&idea.league==="パ");
      return scopeOK&&(type==="all"||idea.type===type);
    }).sort((a,b)=>{
      if(scope!=="hawksPriority")return (a.rank||99)-(b.rank||99);
      return (a.team==="ソフトバンク"?0:1)-(b.team==="ソフトバンク"?0:1)||(a.rank||99)-(b.rank||99);
    });
  }
  root.ArticleLab={buildBrief,fillPrompt,filterIdeas,safeFileName};
  if(typeof module!=="undefined"&&module.exports)module.exports=root.ArticleLab;
  if(typeof document==="undefined")return;

  const $=id=>document.getElementById(id);
  function renderSources(items){
    return (items||[]).map(src=>`<li>${esc(sourceLine(src))}${src.fields?.length?`<br><small>fields: ${esc(src.fields.join(", "))}</small>`:""}</li>`).join("");
  }
  function renderCard(idea){
    const facts=(idea.facts||[]).map(item=>`<div class="fact"><span>${esc(item.label)}</span><b>${esc(item.value)}</b></div>`).join("");
    const angles=(idea.angles||[]).map(x=>`<li>${esc(x)}</li>`).join("");
    const cautions=(idea.cautions||[]).map(x=>`<li>${esc(x)}</li>`).join("");
    return `<article class="idea-card">
      <div class="idea-rank"><small>IDEA</small><b>${esc(idea.rank)}</b></div>
      <div class="idea-body">
        <div class="idea-meta"><span class="type-badge">${esc(idea.type_label)}</span><span class="team-badge">${esc(idea.team)}</span></div>
        <h3>${esc(idea.title)}</h3>
        <p class="why"><b>なぜ面白い？</b><br>${esc(idea.reason)}</p>
        <div class="content-grid">
          <section class="block"><h4>注目データ</h4><div class="fact-grid">${facts}</div></section>
          <section class="block"><h4>記事で掘るポイント</h4><ol class="editor-list">${angles}</ol></section>
        </div>
        <details class="cautions"><summary>注意事項</summary><ul>${cautions}</ul></details>
        <details class="sources"><summary>数字の出典を確認</summary><ul>${renderSources(idea.source_refs)}</ul></details>
        <div class="card-actions">
          <button class="button primary" type="button" data-prompt="${esc(idea.id)}">Claude用プロンプトを生成</button>
          <button class="button" type="button" data-brief="${esc(idea.id)}">Article Brief</button>
        </div>
      </div>
    </article>`;
  }
  function render(){
    const rows=filterIdeas(state.data?.ideas,state.scope,state.type);
    $("ideas").innerHTML=rows.length?rows.map(renderCard).join(""):'<div class="empty-card">この条件に合う記事候補はありません。データ不足を推測で補完していないため、別の条件を選んでください。</div>';
  }
  function findIdea(id){return state.data?.ideas?.find(x=>x.id===id)}
  function openWorkspace(kind,idea){
    if(!idea)return;
    const isPrompt=kind==="prompt";
    if(isPrompt&&!state.template){alert("マスタープロンプトを読み込めませんでした。再読み込みしてください。");return}
    state.activeText=isPrompt?fillPrompt(state.template,idea,state.data.data_date):buildBrief(idea,state.data.data_date);
    state.activeFile=`${state.data.data_date||"data"}-${safeFileName(idea.title)}-${isPrompt?"claude-prompt":"brief"}.md`;
    $("workspaceKicker").textContent=isPrompt?"CLAUDE HANDOFF":"ARTICLE BRIEF";
    $("workspaceTitle").textContent=isPrompt?"Claude用プロンプト":"Article Brief";
    $("workspaceText").value=state.activeText;$("actionStatus").textContent="";$("workspace").hidden=false;document.body.style.overflow="hidden";
  }
  function closeWorkspace(){$("workspace").hidden=true;document.body.style.overflow=""}
  async function copyText(){
    let copied=false;
    try{if(navigator.clipboard&&window.isSecureContext){await navigator.clipboard.writeText(state.activeText);copied=true}}catch(_){/* use selection fallback */}
    if(!copied){const ta=$("workspaceText");ta.focus();ta.select();try{copied=document.execCommand("copy")}catch(_){copied=false}}
    $("actionStatus").textContent=copied?"コピーしました":"全文を選択しました。端末のコピー操作を使ってください";
  }
  function download(){
    const url=URL.createObjectURL(new Blob([state.activeText],{type:"text/markdown;charset=utf-8"}));
    const a=document.createElement("a");a.href=url;a.download=state.activeFile;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);$("actionStatus").textContent="ダウンロードしました";
  }
  async function fetchIdeas(){
    const param=new URLSearchParams(location.search).get("season");const year=new Date().getFullYear();
    const candidates=[param,String(year),String(year-1)].filter((x,i,a)=>x&&a.indexOf(x)===i);
    for(const season of candidates){
      try{const response=await fetch(`data/${season}/_article_ideas.json`,{cache:"no-store"});if(response.ok)return await response.json()}catch(_){/* try previous season */}
    }
    throw new Error("ARTICLE LAB用の集計JSONが見つかりません。");
  }
  async function init(){
    try{
      const [data,templateResponse]=await Promise.all([fetchIdeas(),fetch("prompts/article_writer.md",{cache:"no-store"})]);
      state.data=data;if(templateResponse.ok)state.template=await templateResponse.text();
      $("statusBadge").textContent=data.data_date?`${data.data_date} 時点`:"データなし";
      $("dataDateText").textContent=data.data_date?`${dateJP(data.data_date)}データから記事ネタを生成。PCの日付ではなく、収集済みの最新試合日を基準にしています。`:(data.message||"記事候補を生成できる試合データがありません。");
      $("selectionNote").textContent=data.selection_note||"実在する収集データだけを使います。";render();
    }catch(error){$("statusBadge").textContent="error";$("ideas").innerHTML=`<div class="error-card">${esc(error.message)}<br>Daily workflowで build_article_ideas.py を実行してください。</div>`}
  }
  $("scopeFilter").addEventListener("change",e=>{state.scope=e.target.value;render()});
  $("typeFilter").addEventListener("change",e=>{state.type=e.target.value;render()});
  $("ideas").addEventListener("click",e=>{const prompt=e.target.closest("[data-prompt]");const brief=e.target.closest("[data-brief]");if(prompt)openWorkspace("prompt",findIdea(prompt.dataset.prompt));if(brief)openWorkspace("brief",findIdea(brief.dataset.brief))});
  document.querySelectorAll("[data-close]").forEach(x=>x.addEventListener("click",closeWorkspace));
  $("copyButton").addEventListener("click",copyText);$("downloadButton").addEventListener("click",download);
  document.addEventListener("keydown",e=>{if(e.key==="Escape"&&!$("workspace").hidden)closeWorkspace()});
  init();
})(typeof globalThis!=="undefined"?globalThis:this);
