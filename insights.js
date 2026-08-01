(function(){
  "use strict";

  var insightState={tab:"summary",loaded:false,loading:false,year:"",players:[],teams:[],
    batting:[],pitching:[],games:[],registration:null,daily:[],playerKey:"",playerSearch:"",
    formKind:"batter",previewA:"ソフトバンク",previewB:"日本ハム"};
  var INSIGHT_TABS=[
    ["summary","今日のまとめ"],["player","選手カルテ"],["preview","対戦プレビュー"],
    ["form","好調・不調"],["roster","公示タイムライン"],["teams","球団ダッシュボード"]
  ];

  function iNum(value){var n=Number(value);return isFinite(n)?n:0;}
  function iRate(value,digits){return value==null||!isFinite(Number(value))?"-":Number(value).toFixed(digits==null?3:digits).replace(/^0\./,".");}
  function iPct(value){return value==null||!isFinite(Number(value))?"-":(Number(value)*100).toFixed(1)+"%";}
  function iDate(value){return String(value||"").replace(/-/g,"/");}
  function iKey(row){return row.player_key||row.key||((row.team||"")+"|"+(row.player||row.name||""));}
  function iPlayer(key){return insightState.players.find(function(player){return player.key===key;});}
  function iTeamOrder(team){var all=TEAM_ORDER_PA.concat(TEAM_ORDER_SE);var index=all.indexOf(team);return index<0?99:index;}
  function iTeamPlayers(team,kind){return insightState.players.filter(function(player){
    if(player.team!==team)return false;
    return kind==="pitcher"?!!player.pitching:!!player.batting;
  });}
  function iGroup(rows){var grouped={};(rows||[]).forEach(function(row){
    var key=iKey(row);if(!grouped[key])grouped[key]=[];grouped[key].push(row);
  });return grouped;}
  function iLatestRows(rows,count){return rows.slice().sort(function(a,b){
    return String(a.date).localeCompare(String(b.date))||String(a.game_id).localeCompare(String(b.game_id));
  }).slice(-count);}
  function iBatAgg(rows){
    var a={games:rows.length,ab:0,pa:0,hits:0,singles:0,doubles:0,triples:0,hr:0,rbi:0,runs:0,bb:0,hbp:0,so:0,sb:0};
    rows.forEach(function(r){
      a.ab+=iNum(r.ab);a.hits+=iNum(r.hits);a.singles+=iNum(r.singles);a.doubles+=iNum(r.doubles);
      a.triples+=iNum(r.triples);a.hr+=iNum(r.hr);a.rbi+=iNum(r.rbi);a.runs+=iNum(r.runs);
      a.bb+=iNum(r.bb);a.hbp+=iNum(r.hbp);a.so+=iNum(r.so);a.sb+=iNum(r.sb);
      a.pa+=iNum(r.ab)+iNum(r.bb)+iNum(r.hbp)+iNum(r.sac);
    });
    var tb=a.singles+2*a.doubles+3*a.triples+4*a.hr;
    a.avg=a.ab?a.hits/a.ab:null;a.obp=a.pa?(a.hits+a.bb+a.hbp)/a.pa:null;a.slg=a.ab?tb/a.ab:null;
    a.ops=a.obp==null||a.slg==null?null:a.obp+a.slg;return a;
  }
  function iPitAgg(rows){
    var a={games:rows.length,outs:0,er:0,ra:0,so:0,bb:0,hits:0,hr:0,pitches:0};
    rows.forEach(function(r){a.outs+=iNum(r.outs);a.er+=iNum(r.earned_runs);a.ra+=iNum(r.runs_allowed);
      a.so+=iNum(r.so);a.bb+=iNum(r.bb);a.hits+=iNum(r.hits_allowed);a.hr+=iNum(r.hr_allowed);a.pitches+=iNum(r.pitches);});
    var ip=a.outs/3;a.innings=outsToIp(a.outs);a.era=ip?a.er*9/ip:null;a.whip=ip?(a.hits+a.bb)/ip:null;
    a.k9=ip?a.so*9/ip:null;return a;
  }
  function iConfidence(volume,high,medium){return volume>=high?"高":volume>=medium?"中":"低";}
  function iRosterPlayer(player){
    var rows=(insightState.registration&&insightState.registration.players)||[];
    var name=normName(player.name||"");
    return rows.find(function(row){return row.team===player.team&&normName(row.name||"")===name;});
  }

  async function insightFetchJson(path){var response=await fetch(path+"?t="+Date.now());return response.ok?response.json():null;}
  async function insightLoadData(){
    if(insightState.loaded)return;
    if(insightState.loading)return insightState.loading;
    insightState.loading=(async function(){
      var year=(dp.value||todayJST()).slice(0,4);insightState.year=year;
      if(!seasonData){var playerData=await insightFetchJson("data/"+year+"/players/stats.json");seasonData=playerData&&playerData.players||[];}
      insightState.players=seasonData||[];
      var teamData=await insightFetchJson("data/"+year+"/teams/stats.json");
      insightState.teams=teamData&&teamData.teams||[];
      var datasets=await Promise.all([loadSplitFile("batting_lines"),loadSplitFile("pitching_lines"),loadSplitFile("games"),loadRegistrationData()]);
      insightState.batting=datasets[0].rows||[];insightState.pitching=datasets[1].rows||[];insightState.games=datasets[2].rows||[];
      insightState.registration=datasets[3]||null;
      var dates=((insightState.registration&&insightState.registration.dates)||[]).slice(-14).filter(function(day){return day.additions||day.removals;});
      insightState.daily=(await Promise.all(dates.map(async function(day){
        var data=await insightFetchJson("data/"+year+"/roster/daily/"+day.date+".json");
        return data||{date:day.date,additions:[],removals:[],registered:[]};
      }))).filter(Boolean);
      var candidates=insightState.players.filter(function(player){return (player.batting&&player.batting.pa)||(player.pitching&&player.pitching.outs);});
      candidates.sort(function(a,b){return iTeamOrder(a.team)-iTeamOrder(b.team)||iNum(a.number)-iNum(b.number);});
      if(!insightState.playerKey){
        var defaultPlayer=candidates.find(function(player){return player.team==="ソフトバンク"&&normName(player.name).indexOf("近藤健介")>=0;})||candidates[0];
        insightState.playerKey=defaultPlayer&&defaultPlayer.key||"";
      }
      insightState.loaded=true;
    })().finally(function(){insightState.loading=false;});
    return insightState.loading;
  }

  window.loadInsights=async function(){
    var view=document.getElementById("insightsView");if(!view)return;
    view.innerHTML='<div class="msg">インサイトを集計中…</div>';
    try{await insightLoadData();renderInsights();}catch(error){
      console.error("insights",error);view.innerHTML='<div class="msg">インサイトを読み込めませんでした</div>';
    }
  };
  window.setInsightTab=function(tab){insightState.tab=tab;renderInsights();};

  function renderInsights(){
    var view=document.getElementById("insightsView");if(!view)return;
    var latest=insightLatestDate();
    var h='<div class="insight-shell motion-enter"><div class="insight-hero"><h2>NPB INSIGHTS</h2><p>既存データを横断して、選手・対戦・調子・公示・球団状態をひとつの画面で読む。最新集計 '+iDate(latest)+'</p></div>'+
      '<div class="insight-tabs">'+INSIGHT_TABS.map(function(tab){return '<button class="insight-tab'+(insightState.tab===tab[0]?' on':'')+'" onclick="setInsightTab(\''+tab[0]+'\')">'+tab[1]+'</button>';}).join("")+'</div>'+
      '<div id="insightBody">';
    if(insightState.tab==="summary")h+=insightSummary();
    else if(insightState.tab==="player")h+=insightPlayerCard();
    else if(insightState.tab==="preview")h+=insightPreview();
    else if(insightState.tab==="form")h+=insightForm();
    else if(insightState.tab==="roster")h+=insightRoster();
    else h+=insightTeams();
    view.innerHTML=h+'</div></div>';motionSchedule(view);
  }
  function insightLatestDate(){return insightState.games.reduce(function(max,row){return row.date>max?row.date:max;},"");}
  function insightLatestGames(){var date=insightLatestDate();return insightState.games.filter(function(row){return row.date===date;});}
  function insightPlayerName(row){return row.player||row.name||"-";}
  function insightPlayerRow(row,value,meta,index){return '<div class="insight-row"><span class="rank">'+(index+1)+'</span><span class="who">'+
    esc(insightPlayerName(row))+' '+teamBadge(row.team)+'<span class="meta"> '+esc(meta||"")+'</span></span><span class="value">'+esc(value)+'</span></div>';}

  function insightSummary(){
    var date=insightLatestDate(),games=insightLatestGames();
    var bat=insightState.batting.filter(function(row){return row.date===date;}).sort(function(a,b){
      return (iNum(b.hr)*5+iNum(b.hits)*2+iNum(b.rbi)+iNum(b.runs))-(iNum(a.hr)*5+iNum(a.hits)*2+iNum(a.rbi)+iNum(a.runs));
    }).slice(0,5);
    var pit=insightState.pitching.filter(function(row){return row.date===date;}).sort(function(a,b){
      return (iNum(b.outs)+iNum(b.so)*1.5-iNum(b.earned_runs)*4)-(iNum(a.outs)+iNum(a.so)*1.5-iNum(a.earned_runs)*4);
    }).slice(0,5);
    var homers=insightState.batting.filter(function(row){return row.date===date&&iNum(row.hr)>0;});
    var runs=games.reduce(function(total,g){return total+iNum(g.home_score)+iNum(g.away_score);},0);
    var h='<div class="insight-grid"><section class="insight-card wide"><h3>'+iDate(date)+' 今日のNPBまとめ</h3><div class="insight-kpis">'+
      insightKpi(games.length,"試合")+insightKpi(runs,"総得点")+insightKpi(homers.reduce(function(n,r){return n+iNum(r.hr);},0),"本塁打")+
      insightKpi(pit.reduce(function(n,r){return n+iNum(r.so);},0),"奪三振")+'</div></section>';
    h+='<section class="insight-card"><h3>注目打者</h3><div class="insight-list">'+bat.map(function(row,index){
      return insightPlayerRow(row,iNum(row.hits)+"安打 "+iNum(row.rbi)+"打点",iNum(row.hr)?iNum(row.hr)+"本塁打":"",index);
    }).join("")+'</div></section>';
    h+='<section class="insight-card"><h3>注目投手</h3><div class="insight-list">'+pit.map(function(row,index){
      return insightPlayerRow(row,outsToIp(iNum(row.outs))+"回 "+iNum(row.so)+"K","自責"+iNum(row.earned_runs),index);
    }).join("")+'</div></section>';
    h+='<section class="insight-card wide"><h3>試合結果</h3><div class="insight-list">'+games.map(function(game,index){
      var text=esc(game.away)+' '+iNum(game.away_score)+' － '+iNum(game.home_score)+' '+esc(game.home);
      return '<div class="insight-row"><span class="rank">'+(index+1)+'</span><span class="who">'+text+'<span class="meta"> '+esc(game.stadium||"")+'</span></span><span class="value">'+esc(game.state||"試合終了")+'</span></div>';
    }).join("")+'</div><div class="insight-comment">'+insightSummaryComment(games,bat,pit,homers)+'</div></section></div>';
    return h;
  }
  function insightKpi(value,label){return '<div class="insight-kpi"><b>'+esc(String(value))+'</b><span>'+label+'</span></div>';}
  function insightSummaryComment(games,bat,pit,homers){
    if(!games.length)return "対象日の試合データがありません。";
    var top=bat[0],ace=pit[0];return "全"+games.length+"試合で"+homers.reduce(function(n,r){return n+iNum(r.hr);},0)+"本塁打。"+
      (top?insightPlayerName(top)+"が打撃面で目立ち、":"")+(ace?insightPlayerName(ace)+"が投手陣の上位評価です。":"")+
      "単日の順位は出場機会の影響が大きいため、好調・不調タブの複数試合集計と合わせて確認してください。";
  }

  function insightCandidates(){return insightState.players.filter(function(player){return (player.batting&&player.batting.pa)||(player.pitching&&player.pitching.outs);})
    .filter(function(player){var q=normName(insightState.playerSearch||"");return !q||normName(player.name).indexOf(q)>=0||normName(player.team).indexOf(q)>=0;})
    .sort(function(a,b){return iTeamOrder(a.team)-iTeamOrder(b.team)||iNum(a.number)-iNum(b.number);});}
  window.insightPlayerSearch=function(value){insightState.playerSearch=value;renderInsights();};
  window.insightSelectPlayer=function(key){insightState.playerKey=key;renderInsights();};
  function insightPlayerCard(){
    var candidates=insightCandidates(),player=iPlayer(insightState.playerKey)||candidates[0];if(player)insightState.playerKey=player.key;
    var options=candidates.map(function(p){return '<option value="'+esc(p.key)+'"'+(player&&p.key===player.key?' selected':'')+'>'+esc(p.team)+' #'+esc(p.number||'-')+' '+esc(p.name)+'</option>';}).join("");
    var h='<div class="insight-formbar"><label>選手検索<input value="'+esc(insightState.playerSearch)+'" placeholder="選手名・球団" oninput="insightPlayerSearch(this.value)"></label><label>選手<select onchange="insightSelectPlayer(this.value)">'+options+'</select></label></div>';
    if(!player)return h+'<div class="insight-empty">該当選手がいません</div>';
    var b=player.batting||{},p=player.pitching||{},isPitcher=!!p.outs,rows=isPitcher?playerRows({rows:insightState.pitching},player):playerRows({rows:insightState.batting},player);
    var recent=isPitcher?iPitAgg(iLatestRows(rows,3)):iBatAgg(iLatestRows(rows,5));var roster=iRosterPlayer(player);
    var meta=(isPitcher?"投手":"野手")+" ／ "+(player.hand||"-")+" ／ 主位置 "+(player.position||"-");
    h+='<div class="insight-grid"><section class="insight-card wide"><div class="insight-profile-head" style="--team-color:'+(tColor(player.team)||'var(--accent)')+';--team-text:'+tTextColor(player.team)+'"><div class="avatar">'+esc((player.name||"?").slice(0,1))+'</div><div><h3>'+esc(player.name)+(player.number?' <span class="no">#'+esc(player.number)+'</span>':'')+' '+teamBadge(player.team)+'</h3><div class="note">'+esc(player.team)+' ／ '+esc(meta)+'</div><div style="margin-top:5px">'+(roster?(roster.current_registered?'<span class="insight-tag on">一軍登録中</span>':'<span class="insight-tag">抹消中</span>'):'<span class="insight-tag">公示情報なし</span>')+'</div></div></div></section>';
    h+='<section class="insight-card"><h3>シーズン成績</h3><div class="insight-kpis">'+(isPitcher?
      insightKpi(iRate(p.era,2),"防御率")+insightKpi(p.innings||outsToIp(p.outs||0),"投球回")+insightKpi(p.so||0,"奪三振")+insightKpi(iRate(p.whip,2),"WHIP"):
      insightKpi(iRate(b.avg),"打率")+insightKpi(iRate(b.ops),"OPS")+insightKpi(b.hr||0,"本塁打")+insightKpi(b.rbi||0,"打点"))+'</div></section>';
    h+='<section class="insight-card"><h3>'+(isPitcher?'直近3登板':'直近5試合')+'</h3><div class="insight-kpis">'+(isPitcher?
      insightKpi(iRate(recent.era,2),"防御率")+insightKpi(recent.innings,"投球回")+insightKpi(recent.so,"奪三振")+insightKpi(iRate(recent.whip,2),"WHIP"):
      insightKpi(iRate(recent.avg),"打率")+insightKpi(iRate(recent.ops),"OPS")+insightKpi(recent.hr,"本塁打")+insightKpi(recent.rbi,"打点"))+'</div></section>';
    h+='<section class="insight-card"><h3>コンディション寸評</h3><div class="insight-comment">'+insightPlayerComment(player,recent,isPitcher)+'</div><div class="insight-actions"><button class="btn" onclick="insightOpenGraph(\''+esc(player.key)+'\','+isPitcher+')">推移グラフ</button><button class="btn" onclick="openMatchups(\''+esc(player.key)+'\',\''+(isPitcher?'pitcher':'batter')+'\')">対戦成績</button></div></section>';
    h+='<section class="insight-card"><h3>一軍登録</h3>'+(roster?'<div class="insight-kpis">'+insightKpi(roster.registered_days||0,"登録日数")+insightKpi(roster.registration_count||0,"登録回数")+insightKpi(iDate(roster.first_registered),"初回登録")+insightKpi(iDate(roster.last_deregistered)||"-","最終抹消")+'</div>'+insightPeriods(roster):'<div class="insight-empty">公示データとの照合なし</div>')+'</section></div>';
    return h;
  }
  function insightPlayerComment(player,recent,isPitcher){
    if(isPitcher){var season=player.pitching||{},delta=season.era!=null&&recent.era!=null?season.era-recent.era:0;
      return "直近3登板は防御率"+iRate(recent.era,2)+"。シーズン防御率との差は"+(delta>=0?"改善 ":"悪化 ")+Math.abs(delta).toFixed(2)+"です。直近は"+recent.innings+"回のため、役割と登板間隔も合わせて評価してください。";}
    var b=player.batting||{},d=b.ops!=null&&recent.ops!=null?recent.ops-b.ops:0;
    return "直近5試合のOPSは"+iRate(recent.ops)+"。シーズンOPS比で"+(d>=0?"＋":"－")+Math.abs(d).toFixed(3)+"です。直近"+recent.pa+"打席のため、対戦相手や球場による振れを含みます。";
  }
  function insightPeriods(roster){var periods=(roster.periods||[]).slice(-4);if(!periods.length)return "";var max=Math.max.apply(null,periods.map(function(p){return p.days||1;}));
    return '<div class="insight-periods">'+periods.map(function(period){return '<div class="insight-period"><span>'+iDate(period.from)+'〜'+(period.to?iDate(period.to):'登録中')+'</span><i style="width:'+Math.max(8,(period.days||1)/max*100)+'%"></i><b>'+iNum(period.days)+'日</b></div>';}).join("")+'</div>';}
  window.insightOpenGraph=function(key,isPitcher){pgKind=isPitcher?"pitcher":"batter";pgMetric=isPitcher?"era":"ops";pgSelectedKeys=[key];pgParamsApplied=true;setView("playergraph");};

  function insightTeamRecent(team,count){var rows=insightState.games.filter(function(g){return g.home===team||g.away===team;}).sort(function(a,b){return String(a.date).localeCompare(String(b.date));}).slice(-count);
    var out={games:rows.length,wins:0,losses:0,runs:0,allowed:0};rows.forEach(function(g){var home=g.home===team,rf=iNum(home?g.home_score:g.away_score),ra=iNum(home?g.away_score:g.home_score);out.runs+=rf;out.allowed+=ra;if(rf>ra)out.wins++;else if(rf<ra)out.losses++;});return out;}
  function insightTeamSeason(team){var batters=iTeamPlayers(team,"batter"),pitchers=iTeamPlayers(team,"pitcher"),pa=0,weightedOps=0,outs=0,er=0;
    batters.forEach(function(p){var b=p.batting||{};pa+=iNum(b.pa);weightedOps+=iNum(b.ops)*iNum(b.pa);});pitchers.forEach(function(p){var q=p.pitching||{};outs+=iNum(q.outs);er+=iNum(q.earned_runs);});
    var meta=insightState.teams.find(function(row){return row.team===team;})||{};return {ops:pa?weightedOps/pa:null,era:outs?er*27/outs:null,der:meta.der,games:meta.games||0};}
  window.insightPreviewChange=function(side,value){if(side==="a")insightState.previewA=value;else insightState.previewB=value;if(insightState.previewA===insightState.previewB){var all=TEAM_ORDER_PA.concat(TEAM_ORDER_SE);insightState.previewB=all.find(function(team){return team!==insightState.previewA;})||"";}renderInsights();};
  function insightPreview(){var teams=TEAM_ORDER_PA.concat(TEAM_ORDER_SE),a=insightState.previewA,b=insightState.previewB;
    var options=function(selected){return teams.map(function(team){return '<option value="'+esc(team)+'"'+(team===selected?' selected':'')+'>'+esc(team)+'</option>';}).join("");};
    var ar=insightTeamRecent(a,5),br=insightTeamRecent(b,5),as=insightTeamSeason(a),bs=insightTeamSeason(b),forms=insightFormRows("batter");
    var ah=forms.find(function(x){return x.player.team===a;}),bh=forms.find(function(x){return x.player.team===b;});
    var metrics=[["直近5試合 得点",ar.runs,br.runs],["直近5試合 失点",ar.allowed,br.allowed],["チームOPS",as.ops,bs.ops],["チーム防御率",as.era,bs.era],["DER",as.der,bs.der]];
    var h='<div class="insight-formbar"><label>チームA<select onchange="insightPreviewChange(\'a\',this.value)">'+options(a)+'</select></label><label>チームB<select onchange="insightPreviewChange(\'b\',this.value)">'+options(b)+'</select></label></div>'+
      '<div class="insight-grid"><section class="insight-card wide"><h3>対戦カードプレビュー</h3><div class="insight-matchup"><div class="insight-team">'+teamBadge(a)+'<b>'+esc(a)+'</b><span class="record">直近5試合 '+ar.wins+'勝'+ar.losses+'敗</span></div><div class="insight-vs">VS</div><div class="insight-team">'+teamBadge(b)+'<b>'+esc(b)+'</b><span class="record">直近5試合 '+br.wins+'勝'+br.losses+'敗</span></div></div>'+insightCompareBars(metrics)+'</section>';
    h+='<section class="insight-card"><h3>'+esc(a)+' 注目選手</h3>'+(ah?insightPlayerRow(ah.player,iRate(ah.recent.ops)+" OPS","直近5試合",0):'<div class="insight-empty">対象なし</div>')+'</section>';
    h+='<section class="insight-card"><h3>'+esc(b)+' 注目選手</h3>'+(bh?insightPlayerRow(bh.player,iRate(bh.recent.ops)+" OPS","直近5試合",0):'<div class="insight-empty">対象なし</div>')+'</section>';
    h+='<section class="insight-card wide"><h3>読みどころ</h3><div class="insight-comment">'+insightPreviewComment(a,b,ar,br,as,bs,ah,bh)+'</div><div class="note" style="margin-top:7px">予測勝率ではありません。シーズン累計と直近5試合を並べた、試合前確認用の比較です。予告先発が収集済みの場合は対戦成績ページも併用してください。</div></section></div>';return h;}
  function insightCompareBars(metrics){return '<div class="insight-bars">'+metrics.map(function(m){var av=iNum(m[1]),bv=iNum(m[2]),max=Math.max(Math.abs(av),Math.abs(bv),.001);return '<div class="insight-bar"><b>'+m[0]+'</b><div class="insight-track"><div class="insight-fill" style="width:'+Math.max(4,av/max*100)+'%"></div></div><span>'+iRate(av,av<10?3:0)+'</span><span>'+iRate(bv,bv<10?3:0)+'</span></div>';}).join("")+'</div>';}
  function insightPreviewComment(a,b,ar,br,as,bs,ah,bh){var offense=ar.runs>=br.runs?a:b,defense=ar.allowed<=br.allowed?a:b;return "直近5試合の得点は"+offense+"、失点抑止は"+defense+"が優位です。"+(ah&&bh?"好調打者は"+a+"の"+ah.player.name+"、"+b+"の"+bh.player.name+"。":"")+"短期成績は日程と対戦相手の影響を受けるため、チームOPS・防御率・DERのシーズン値を基準線として見てください。";}

  function insightFormRows(kind){var isPitcher=kind==="pitcher",rows=isPitcher?insightState.pitching:insightState.batting,groups=iGroup(rows),out=[];
    Object.keys(groups).forEach(function(key){var player=iPlayer(key)||insightState.players.find(function(p){return p.name===insightPlayerName(groups[key][0])&&p.team===groups[key][0].team;});if(!player)return;
      if(isPitcher){var q=player.pitching||{},recent=iPitAgg(iLatestRows(groups[key],3));if(iNum(q.games)<3||recent.outs<6||q.era==null||recent.era==null)return;out.push({player:player,recent:recent,season:q,delta:iNum(q.era)-recent.era,volume:recent.outs});}
      else{var b=player.batting||{},rb=iBatAgg(iLatestRows(groups[key],5));if(iNum(b.pa)<30||rb.pa<8||b.ops==null||rb.ops==null)return;out.push({player:player,recent:rb,season:b,delta:rb.ops-iNum(b.ops),volume:rb.pa});}
    });return out.sort(function(a,b){return b.delta-a.delta;});}
  window.insightSetFormKind=function(kind){insightState.formKind=kind;renderInsights();};
  function insightForm(){var kind=insightState.formKind,rows=insightFormRows(kind),hot=rows.slice(0,10),cold=rows.slice(-10).reverse(),isPitcher=kind==="pitcher";
    var rowHtml=function(item,index,type){var value=isPitcher?(iRate(item.recent.era,2)+" ERA"):(iRate(item.recent.ops)+" OPS");var meta=(item.delta>=0?"改善 ":"低下 ")+Math.abs(item.delta).toFixed(isPitcher?2:3)+" ／ 信頼度 "+iConfidence(item.volume,isPitcher?18:18,isPitcher?9:12);return '<div class="insight-row"><span class="rank">'+(index+1)+'</span><span class="who">'+esc(item.player.name)+' '+teamBadge(item.player.team)+'<span class="meta"> '+meta+'</span></span><span><span class="insight-tag '+type+'">'+value+'</span></span></div>';};
    return '<div class="stabs"><button class="stab'+(kind==='batter'?' on':'')+'" onclick="insightSetFormKind(\'batter\')">野手</button><button class="stab'+(kind==='pitcher'?' on':'')+'" onclick="insightSetFormKind(\'pitcher\')">投手</button></div><div class="insight-grid"><section class="insight-card"><h3>急上昇</h3><div class="insight-list">'+hot.map(function(x,i){return rowHtml(x,i,'hot');}).join("")+'</div></section><section class="insight-card"><h3>下降傾向</h3><div class="insight-list">'+cold.map(function(x,i){return rowHtml(x,i,'cold');}).join("")+'</div></section><section class="insight-card wide"><h3>判定方法</h3><div class="note">野手は直近5試合OPSとシーズンOPSの差（シーズン30打席以上・直近8打席以上）、投手は直近3登板防御率とシーズン防御率の差（シーズン3登板以上・直近2回以上）で判定。出場量から信頼度を併記し、故障や対戦相手は推測しません。</div></section></div>';}

  function insightRoster(){var daily=insightState.daily.slice().reverse(),counts={};daily.forEach(function(day){(day.additions||[]).concat(day.removals||[]).forEach(function(row){counts[row.team]=(counts[row.team]||0)+1;});});var ranking=Object.keys(counts).sort(function(a,b){return counts[b]-counts[a];});
    var timeline=daily.map(function(day){var adds=day.additions||[],removes=day.removals||[];return '<div class="insight-event"><span></span><b>'+iDate(day.date)+'</b><div><div class="changes"><span class="insight-tag on">登録 '+adds.length+'</span><span class="insight-tag">抹消 '+removes.length+'</span></div><div class="note">'+esc(adds.slice(0,4).map(function(x){return x.name;}).join('、')||'登録なし')+(adds.length>4?' ほか':'')+(removes.length?' ／ 抹消 '+esc(removes.slice(0,4).map(function(x){return x.name;}).join('、')):'')+'</div></div></div>';}).join("");
    return '<div class="insight-grid"><section class="insight-card wide"><h3>直近の登録・抹消</h3><div class="insight-timeline">'+(timeline||'<div class="insight-empty">直近14日間に入れ替えはありません</div>')+'</div></section><section class="insight-card"><h3>入れ替えが多い球団</h3><div class="insight-list">'+ranking.slice(0,6).map(function(team,index){return '<div class="insight-row"><span class="rank">'+(index+1)+'</span><span class="who">'+teamBadge(team)+' '+esc(team)+'</span><span class="value">'+counts[team]+'人</span></div>';}).join("")+'</div></section><section class="insight-card"><h3>現在の登録状況</h3><div class="insight-kpis">'+insightKpi(insightState.registration&&insightState.registration.current_registered_count||0,"登録選手")+insightKpi(insightState.registration&&insightState.registration.covered_days||0,"集計日数")+insightKpi(daily.reduce(function(n,d){return n+(d.additions||[]).length;},0),"直近の登録")+insightKpi(daily.reduce(function(n,d){return n+(d.removals||[]).length;},0),"直近の抹消")+'</div><div class="insight-actions"><button class="btn" onclick="setView(\'roster\')">公示一覧を開く</button></div></section></div>';}

  function insightTeamStyle(team,season,recent){var bats=iTeamPlayers(team,"batter"),hrs=bats.reduce(function(n,p){return n+iNum((p.batting||{}).hr);},0);if(season.ops>=.72&&hrs>=60)return "長打型";if(recent.allowed/recent.games<=3.2)return "投手・守備型";if(season.der>=.7)return "守備安定型";if(recent.runs/recent.games>=4)return "攻撃型";return "バランス型";}
  function insightTeams(){var teams=TEAM_ORDER_PA.concat(TEAM_ORDER_SE);var cards=teams.map(function(team){var recent=insightTeamRecent(team,10),season=insightTeamSeason(team),style=insightTeamStyle(team,season,recent);return '<div class="insight-team-card" style="border-left:5px solid '+(tColor(team)||'var(--accent)')+'"><h4>'+teamBadge(team)+' '+esc(team)+' <span class="insight-tag">'+style+'</span></h4><div class="mini-stats"><div><b>'+iRate(season.ops)+'</b><span>OPS</span></div><div><b>'+iRate(season.era,2)+'</b><span>防御率</span></div><div><b>'+iRate(season.der,3)+'</b><span>DER</span></div><div><b>'+recent.wins+'-'+recent.losses+'</b><span>直近10試合</span></div><div><b>'+iRate(recent.games?recent.runs/recent.games:null,2)+'</b><span>得点/試合</span></div><div><b>'+iRate(recent.games?recent.allowed/recent.games:null,2)+'</b><span>失点/試合</span></div></div></div>';}).join("");
    return '<section class="insight-card"><h3>12球団コンディション</h3><div class="insight-team-grid">'+cards+'</div><div class="note" style="margin-top:9px">OPS・防御率・DERはシーズン累計、勝敗と得失点は直近10試合。スタイル名は表示値による説明用分類で、優劣や将来予測ではありません。</div></section>';}
  if(new URLSearchParams(location.search).get("view")==="insights")setView("insights");
})();
