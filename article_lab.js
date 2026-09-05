(function(root){
  "use strict";

  const state={data:null,template:"",scope:"hawksPriority",type:"all",activeText:"",activeFile:"article-brief.md",customIdea:null,playerLabels:new Map()};
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
      const selectedTeam=String(scope||"").startsWith("team:")?String(scope).slice(5):"";
      const scopeOK=scope==="hawksPriority"||scope==="all"||(scope==="pacific"&&idea.league==="パ")||(scope==="central"&&idea.league==="セ")||(selectedTeam&&idea.team===selectedTeam);
      return scopeOK&&(type==="all"||idea.type===type);
    }).sort((a,b)=>{
      if(scope!=="hawksPriority")return (a.rank||99)-(b.rank||99);
      return (a.team==="ソフトバンク"?0:1)-(b.team==="ソフトバンク"?0:1)||(a.rank||99)-(b.rank||99);
    });
  }

  const periodLabels={latest:"直近1試合",recent5:"直近5試合",recent10:"直近10試合",season:"シーズン"};
  const teamAliases={ホークス:"ソフトバンク",鷹:"ソフトバンク",ファイターズ:"日本ハム",バファローズ:"オリックス",イーグルス:"楽天",ライオンズ:"西武",マリーンズ:"ロッテ",タイガース:"阪神",ベイスターズ:"DeNA",ジャイアンツ:"巨人",ドラゴンズ:"中日",カープ:"広島",スワローズ:"ヤクルト"};
  const normalize=value=>String(value||"").normalize("NFKC").replace(/[\s・･]/g,"").toLowerCase();
  const rate=(value,digits=3)=>value==null?null:Number(value).toFixed(digits).replace(/^0/,"");
  const percent=value=>value==null?null:`${(Number(value)*100).toFixed(1)}%`;
  const valueText=(value,digits=2)=>value==null?null:Number(value).toFixed(digits);
  const periodDate=period=>period?.date_start&&period?.date_end?(period.date_start===period.date_end?period.date_start:`${period.date_start}〜${period.date_end}`):null;
  const dataFact=(label,value,metric,source)=>value==null?null:{label,value:String(value),metric,raw_value:value,source};
  const addFact=(facts,item)=>{if(item)facts.push(item)};
  function inferPeriod(theme,selected){
    if(selected&&selected!=="auto")return selected;
    if(/直近\s*5|最近\s*5|5試合/.test(theme))return "recent5";
    if(/直近\s*10|最近\s*10|10試合/.test(theme))return "recent10";
    if(/今日|昨日|前回|最新|この試合|1試合/.test(theme))return "latest";
    if(/最近|好調|不調|変化|調子/.test(theme))return "recent10";
    return "season";
  }
  function inferFocus(theme,selected,player){
    if(selected&&selected!=="auto")return selected;
    if(/球種|配球|ストレート|直球|フォーク|スライダー|カーブ|チェンジアップ|空振り|ゾーン/.test(theme))return "pitch";
    if(/woba|wrc\+?|fip|セイバー|babip|iso|指標/i.test(theme))return "advanced";
    if(/防御率|era|whip|奪三振|投球|先発|救援|リリーフ|四死球/.test(theme))return "pitching";
    if(/勝敗|勝率|得点|失点|順位|チーム|球団/.test(theme))return "record";
    if(/打率|ops|本塁打|長打|安打|打点|四球|三振|打撃/.test(theme))return "batting";
    return player?.kind==="pitcher"?"pitching":player?.kind==="batter"?"batting":"record";
  }
  function detectTeam(theme,context,selected){
    if(selected)return selected;
    const normalized=normalize(theme);
    const teams=(context?.teams||[]).map(x=>x.team).sort((a,b)=>b.length-a.length);
    const exact=teams.find(team=>normalized.includes(normalize(team)));
    if(exact)return exact;
    return Object.entries(teamAliases).find(([alias])=>normalized.includes(normalize(alias)))?.[1]||"";
  }
  function detectPlayer(theme,context,selectedId){
    const players=context?.players||[];
    if(selectedId)return players.find(player=>player.id===selectedId)||null;
    const normalized=normalize(theme);
    const wantsPitcher=/防御率|era|whip|奪三振|投球|投手|先発|救援|リリーフ|球種|配球/.test(theme);
    const wantsBatter=/打率|ops|本塁打|長打|安打|打点|打撃|打者/.test(theme);
    return players.filter(player=>normalize(player.name).length>=3&&normalized.includes(normalize(player.name))).sort((a,b)=>
      normalize(b.name).length-normalize(a.name).length+
      ((wantsPitcher&&a.kind==="pitcher")||(wantsBatter&&a.kind==="batter")?-100:0)+
      ((wantsPitcher&&b.kind==="pitcher")||(wantsBatter&&b.kind==="batter")?100:0)
    )[0]||null;
  }
  function pitchMixText(profile){
    return (profile?.pitch_mix||[]).slice(0,4).map(row=>`${row.pitch_type} ${row.pitches}球（${percent(row.share)}）`).join("、")||null;
  }
  function sourceRef(dataset,period,fields){
    const src={dataset,date:periodDate(period)};
    if(period?.games===1&&period.latest_game_id)src.game_id=period.latest_game_id;
    if(fields?.length)src.fields=fields;
    return src;
  }
  function buildCustomIdea(config,context,dataDate){
    const theme=String(config?.theme||"").trim();
    if(!theme)return {error:"書きたいテーマ・疑問を入力してください。"};
    const player=detectPlayer(`${theme} ${config?.playerText||""}`,context,config?.playerId);
    let team=player?.team||detectTeam(theme,context,config?.team);
    const requestedType=config?.target||"auto";
    const type=requestedType!=="auto"?requestedType:(player?"player":/この試合|今日の試合|昨日の試合|最新試合|対戦結果|スコア/.test(theme)?"game":"team");
    const periodKey=inferPeriod(theme,config?.period);
    const focus=inferFocus(theme,config?.focus,player);
    const facts=[];const cautions=[];const refs=[];
    let subject=player?.name||team||"対象未指定";
    let outputType=type==="player"?"player":type==="game"?"game":"trend";
    let game=null;
    if(type==="game"){
      game=(context?.games||[]).find(row=>config?.gameId&&row.game_id===config.gameId)||
        (context?.games||[]).find(row=>!team||team===row.home||team===row.away)||null;
      if(game){
        subject=`${game.away}－${game.home}`;team=team||game.home;
        const gameSrc={dataset:"games.csv",date:game.date,game_id:game.game_id,fields:["home","away","home_score","away_score","winner","stadium"]};
        addFact(facts,dataFact("試合結果",`${game.away} ${game.away_score}－${game.home_score} ${game.home}`,"score",gameSrc));
        addFact(facts,dataFact("勝利球団",game.winner||"引き分け","winner",gameSrc));
        addFact(facts,dataFact("球場",game.stadium,"stadium",gameSrc));refs.push(gameSrc);
      }else cautions.push("条件に合う収集済み試合を特定できないため、試合固有の数字は付けていません");
    }else if(type==="player"){
      if(!player){
        cautions.push("選手を一意に特定できません。選手欄から選ぶと根拠データを追加できます");
      }else{
        const period=player.periods?.[periodKey];const stats=period?.stats||{};
        const dataset=player.kind==="batter"?"batting_lines.csv":"pitching_lines.csv";
        const src=sourceRef(dataset,period,player.kind==="batter"?["games","pa","ab","hits","hr","rbi","bb","so","avg","ops"]:["games","innings","earned_runs","so","bb","hits_allowed","era","whip","k9"]);
        if(player.kind==="batter"){
          addFact(facts,dataFact("標本",`${period?.games||0}試合 ${stats.pa||0}打席`,"sample",src));
          addFact(facts,dataFact("打率・OPS",stats.avg==null||stats.ops==null?null:`打率${rate(stats.avg)} / OPS ${rate(stats.ops)}`,"avg_ops",src));
          addFact(facts,dataFact("安打・本塁打・打点",`${stats.hits||0}安打 / ${stats.hr||0}本塁打 / ${stats.rbi||0}打点`,"production",src));
          addFact(facts,dataFact("四球・三振",`${stats.bb||0}四球 / ${stats.so||0}三振`,"discipline",src));
        }else{
          addFact(facts,dataFact("標本",`${period?.games||0}登板 ${stats.innings||"0.0"}回`,"sample",src));
          addFact(facts,dataFact("防御率・WHIP",stats.era==null||stats.whip==null?null:`防御率${valueText(stats.era)} / WHIP ${valueText(stats.whip)}`,"era_whip",src));
          addFact(facts,dataFact("奪三振・与四球",`${stats.so||0}奪三振 / ${stats.bb||0}与四球`,"k_bb",src));
          addFact(facts,dataFact("K/9",valueText(stats.k9),"k9",src));
        }
        refs.push(src);
        if(focus==="advanced"){
          const adv=player.advanced||{};const advSrc={dataset:player.kind==="batter"?"season_batting.csv":"season_pitching.csv",date:dataDate};
          if(player.kind==="batter"){
            addFact(facts,dataFact("wOBA・wRC+",adv.woba_est==null&&adv.wrc_plus_est==null?null:`wOBA ${rate(adv.woba_est)} / wRC+ ${valueText(adv.wrc_plus_est,1)}`,"advanced_batting",advSrc));
            addFact(facts,dataFact("ISO・BsR",adv.iso==null&&adv.bsr_est==null?null:`ISO ${rate(adv.iso)} / BsR ${valueText(adv.bsr_est,1)}`,"secondary_value",advSrc));
          }else{
            addFact(facts,dataFact("FIP・K/9・BB/9",adv.fip==null?null:`FIP ${valueText(adv.fip)} / K/9 ${valueText(adv.k9)} / BB/9 ${valueText(adv.bb9)}`,"advanced_pitching",advSrc));
          }
          refs.push(advSrc);cautions.push("セイバー指標は収集済みシーズン全体の集計値です");
        }
        if(focus==="pitch"){
          const profile=player.pitch_profile;const pitchSrc={dataset:"pitches.csv",date:profile?.date_start===profile?.date_end?profile?.date_start:(profile?.date_start&&profile?.date_end?`${profile.date_start}〜${profile.date_end}`:dataDate)};
          addFact(facts,dataFact(player.kind==="pitcher"?"球種構成":"対戦球種",pitchMixText(profile),"pitch_mix",pitchSrc));
          if(player.kind==="pitcher"){
            addFact(facts,dataFact("ストレート球速",profile?.fastball?.avg_speed_kmh==null?null:`平均${valueText(profile.fastball.avg_speed_kmh,1)}km/h / 最速${valueText(profile.fastball.max_speed_kmh,1)}km/h`,"fastball_velocity",pitchSrc));
            addFact(facts,dataFact("ゾーン内割合",percent(profile?.in_zone_rate),"zone_rate",pitchSrc));
          }else addFact(facts,dataFact("空振り率",percent(profile?.whiff_rate),"whiff_rate",pitchSrc));
          refs.push(pitchSrc);cautions.push("球種・配球データは選択期間ではなく収集済みシーズン全体の集計です");
        }
        if((period?.games||0)<5)cautions.push(`${periodLabels[periodKey]}は${period?.games||0}試合の小標本です`);
        if((player.team_history||[]).length>1)cautions.push(`所属履歴に${player.team_history.join("・")}を含みます`);
      }
    }else{
      const teamRow=(context?.teams||[]).find(row=>row.team===team);
      if(!teamRow){
        cautions.push("球団を特定できません。球団欄から選ぶと根拠データを追加できます");
      }else{
        const period=teamRow.periods?.[periodKey];const record=period?.record||{};const bat=period?.batting||{};const pit=period?.pitching||{};
        const gameSrc=sourceRef("games.csv",period,["wins","losses","ties","runs_per_game","allowed_per_game"]);
        const batSrc=sourceRef("batting_lines.csv",period,["pa","avg","obp","slg","ops","hr","bb","so"]);
        const pitSrc=sourceRef("pitching_lines.csv",period,["innings","era","whip","k9"]);
        addFact(facts,dataFact("勝敗",`${record.wins||0}勝${record.losses||0}敗${record.ties||0}分（${record.games||0}試合）`,"record",gameSrc));
        addFact(facts,dataFact("1試合平均得失点",record.runs_per_game==null?null:`得点 ${valueText(record.runs_per_game,2)} / 失点 ${valueText(record.allowed_per_game,2)}`,"runs",gameSrc));
        addFact(facts,dataFact("チーム打撃",bat.ops==null?null:`打率${rate(bat.avg)} / OPS ${rate(bat.ops)} / ${bat.hr||0}本塁打`,"team_batting",batSrc));
        addFact(facts,dataFact("チーム投球",pit.era==null?null:`防御率${valueText(pit.era)} / WHIP ${valueText(pit.whip)} / K/9 ${valueText(pit.k9)}`,"team_pitching",pitSrc));
        refs.push(gameSrc,batSrc,pitSrc);
        if((period?.games||0)<5)cautions.push(`${periodLabels[periodKey]}は${period?.games||0}試合の小標本です`);
      }
    }
    if(!facts.length)cautions.push("根拠データが不足しています。Claudeには不足項目を推測しないよう指示します");
    cautions.push("対戦相手・球場・日程などを完全には補正していません");
    cautions.push("数値の変化と原因を区別し、因果関係を断定しないでください");
    const angleMap={
      batting:["選択期間の打撃成績をシーズン全体と比較する","長打・四球・三振のどこが変化したか確認する","結果と短期的な偶然を分けて考える"],
      pitching:["防御率だけでなくWHIP・奪三振・与四球を見る","登板数と投球回を踏まえて変化を確認する","結果と投球内容を分けて考える"],
      pitch:["球種構成と球速を確認する","カウントや対戦打者による違いを追加検証する","配球の変化から投手の意図を断定しない"],
      record:["勝敗と得失点の関係を見る","打撃と投手陣のどちらが目立ったか確認する","対戦相手と球場の影響を考える"],
      advanced:["従来指標とセイバー指標の違いを見る","リーグ平均との比較を確認する","指標の定義と標本数を明記する"],
    };
    const angles=angleMap[focus]||angleMap.record;
    const uniqueRefs=refs.filter((ref,index,array)=>ref&&array.findIndex(other=>JSON.stringify(other)===JSON.stringify(ref))===index);
    const periodLabel=periodLabels[periodKey]||periodLabels.season;
    return {
      id:"custom-idea",rank:"MY",type:outputType,type_label:"自分の記事案",team:team||"対象未指定",
      league:team&&["ソフトバンク","日本ハム","オリックス","楽天","西武","ロッテ"].includes(team)?"パ":"全",
      title:theme,theme,
      reason:facts.length?`${subject}の${periodLabel}について、収集済みデータから${facts.length}個の根拠を組み立てました。入力した疑問への答えは断定せず、数字から確認できる範囲を記事の出発点にします。`:"入力テーマは保持しましたが、対象を一意に特定できる根拠データがありません。選手・球団・試合を選ぶと精度が上がります。",
      facts,angles,cautions:[...new Set(cautions)],source_refs:uniqueRefs,
      custom_meta:{period:periodKey,focus,player_id:player?.id||null,game_id:game?.game_id||null},
    };
  }
  root.ArticleLab={buildBrief,fillPrompt,filterIdeas,safeFileName,buildCustomIdea,inferPeriod,inferFocus};
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
    const useTeamCatalog=state.scope!=="hawksPriority"&&(state.data?.team_ideas||[]).length;
    const pool=useTeamCatalog?state.data.team_ideas:state.data?.ideas;
    const rows=filterIdeas(pool,state.scope,state.type).slice(0,5).map((idea,index)=>({...idea,rank:index+1}));
    $("ideas").innerHTML=rows.length?rows.map(renderCard).join(""):'<div class="empty-card">この条件に合う記事候補はありません。データ不足を推測で補完していないため、別の条件を選んでください。</div>';
  }
  function findIdea(id){return id==="custom-idea"?state.customIdea:state.data?.ideas?.find(x=>x.id===id)}
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
  function playerOptionLabel(player){return `${player.name}（${player.team}・${player.kind==="pitcher"?"投手":"野手"}）`}
  function populatePlayers(){
    const selectedTeam=$("customTeam").value;
    const players=(state.data?.custom_context?.players||[]).filter(player=>!selectedTeam||player.team===selectedTeam);
    state.playerLabels=new Map();
    $("customPlayerOptions").innerHTML=players.map(player=>{const label=playerOptionLabel(player);state.playerLabels.set(label,player.id);return `<option value="${esc(label)}"></option>`}).join("");
  }
  function populateGames(){
    const selectedTeam=$("customTeam").value;
    const games=(state.data?.custom_context?.games||[]).filter(game=>!selectedTeam||selectedTeam===game.home||selectedTeam===game.away);
    $("customGame").innerHTML='<option value="">最新の該当試合</option>'+games.map(game=>`<option value="${esc(game.game_id)}">${esc(game.date)} ${esc(game.away)} ${esc(game.away_score)}－${esc(game.home_score)} ${esc(game.home)}</option>`).join("");
  }
  function populateCustomControls(){
    const teams=state.data?.custom_context?.teams||[];
    $("customTeam").innerHTML='<option value="">入力から自動判定</option>'+teams.map(row=>`<option value="${esc(row.team)}">${esc(row.team)}</option>`).join("");
    const pacific=teams.filter(row=>row.league==="パ");const central=teams.filter(row=>row.league==="セ");
    const teamOptions=rows=>rows.map(row=>`<option value="team:${esc(row.team)}">${esc(row.team)}</option>`).join("");
    $("scopeFilter").innerHTML='<option value="hawksPriority">ソフトバンク優先</option><option value="pacific">パ・リーグ</option><option value="central">セ・リーグ</option><option value="all">全12球団</option>'+
      (pacific.length?`<optgroup label="パ・リーグ各球団">${teamOptions(pacific)}</optgroup>`:"")+
      (central.length?`<optgroup label="セ・リーグ各球団">${teamOptions(central)}</optgroup>`:"");
    populatePlayers();populateGames();
  }
  function createCustomIdea(openPrompt=false){
    const playerText=$("customPlayer").value.trim();
    const idea=buildCustomIdea({
      theme:$("customTheme").value,target:$("customTarget").value,team:$("customTeam").value,
      playerId:state.playerLabels.get(playerText)||"",playerText,gameId:$("customGame").value,
      period:$("customPeriod").value,focus:$("customFocus").value,
    },state.data?.custom_context,state.data?.data_date);
    if(idea.error){$("customStatus").textContent=idea.error;$("customPreview").innerHTML="";return null}
    state.customIdea=idea;$("customPreview").innerHTML=renderCard(idea);
    const hasFacts=(idea.facts||[]).length;
    $("customStatus").textContent=hasFacts?`${hasFacts}件の根拠データを確認しました。内容を確認してプロンプトを生成できます。`:"対象を特定できませんでした。選手・球団・試合を選ぶと根拠を追加できます。";
    if(openPrompt)openWorkspace("prompt",idea);
    else $("customPreview").scrollIntoView({behavior:window.matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth",block:"nearest"});
    return idea;
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
      $("selectionNote").textContent=data.selection_note||"実在する収集データだけを使います。";populateCustomControls();render();
    }catch(error){$("statusBadge").textContent="error";$("ideas").innerHTML=`<div class="error-card">${esc(error.message)}<br>Daily workflowで build_article_ideas.py を実行してください。</div>`}
  }
  $("scopeFilter").addEventListener("change",e=>{state.scope=e.target.value;render()});
  $("typeFilter").addEventListener("change",e=>{state.type=e.target.value;render()});
  $("ideas").addEventListener("click",e=>{const prompt=e.target.closest("[data-prompt]");const brief=e.target.closest("[data-brief]");if(prompt)openWorkspace("prompt",findIdea(prompt.dataset.prompt));if(brief)openWorkspace("brief",findIdea(brief.dataset.brief))});
  $("customPreview").addEventListener("click",e=>{const prompt=e.target.closest("[data-prompt]");const brief=e.target.closest("[data-brief]");if(prompt)openWorkspace("prompt",state.customIdea);if(brief)openWorkspace("brief",state.customIdea)});
  $("buildCustomIdea").addEventListener("click",()=>createCustomIdea(false));
  $("buildCustomPrompt").addEventListener("click",()=>createCustomIdea(true));
  $("customTeam").addEventListener("change",()=>{$("customPlayer").value="";populatePlayers();populateGames()});
  $("customTarget").addEventListener("change",e=>{if(e.target.value==="game")$("customGame").focus()});
  document.querySelectorAll("[data-close]").forEach(x=>x.addEventListener("click",closeWorkspace));
  $("copyButton").addEventListener("click",copyText);$("downloadButton").addEventListener("click",download);
  document.addEventListener("keydown",e=>{if(e.key==="Escape"&&!$("workspace").hidden)closeWorkspace()});
  init();
})(typeof globalThis!=="undefined"?globalThis:this);
