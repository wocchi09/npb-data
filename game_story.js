(function(root,factory){
  var api=factory();
  if(typeof module!=="undefined"&&module.exports) module.exports=api;
  Object.keys(api).forEach(function(key){root[key]=api[key];});
})(typeof globalThis!=="undefined"?globalThis:this,function(){
  "use strict";

  function number(value){
    value=Number(value);
    return isFinite(value)?value:0;
  }
  function scoreFor(scoreAt,team,fallback){
    var rows=scoreAt||[];
    for(var i=0;i<rows.length;i++){
      if(rows[i].team===team) return number(rows[i].score);
    }
    return fallback;
  }
  function eventType(beforeBat,beforeOpp,afterBat,afterOpp,beforeTotal){
    if(beforeTotal===0&&afterBat>afterOpp) return "先制";
    if(beforeBat<beforeOpp&&afterBat>afterOpp) return "逆転";
    if(beforeBat<beforeOpp&&afterBat===afterOpp) return "同点";
    if(beforeBat===beforeOpp&&afterBat>afterOpp) return "勝ち越し";
    if(afterBat<afterOpp) return "追撃";
    return "追加点";
  }
  function importance(type,inning,margin,runs){
    var points=number(runs)*1.2+Math.min(number(inning),12)*0.12;
    if(type==="逆転") points+=4;
    else if(type==="勝ち越し") points+=3.2;
    else if(type==="同点") points+=2.8;
    else if(type==="先制") points+=1.2;
    if(number(inning)>=7&&Math.abs(number(margin))<=2) points+=2;
    return points;
  }
  function resultText(atbat){
    var summary=String(atbat.result_summary||"").replace(/\s*＋\d+点\s*$/," ").trim();
    if(!summary) summary="得点";
    return summary;
  }
  function buildGameStory(game){
    game=game||{};
    var home=game.home||"ホーム",away=game.away||"ビジター";
    var scores={};scores[home]=0;scores[away]=0;
    var events=[],pitchingChanges=[],currentPitcher={},leadChanges=0,ties=0;
    (game.atbats||[]).forEach(function(atbat){
      if(atbat&&atbat.valid===false) return;
      var batting=atbat.batting_team;
      if(!batting||!atbat.score_at) return;
      var fielding=batting===home?away:home;
      var pitcher=(atbat.pitcher&&atbat.pitcher.name)||"";
      if(pitcher&&currentPitcher[fielding]&&currentPitcher[fielding]!==pitcher){
        pitchingChanges.push({
          inning:number(atbat.inning),half:atbat.top_bottom||"",
          label:number(atbat.inning)+"回"+(atbat.top_bottom||""),
          team:fielding,pitcher:pitcher
        });
      }
      if(pitcher) currentPitcher[fielding]=pitcher;
      var beforeHome=scores[home],beforeAway=scores[away];
      var afterHome=scoreFor(atbat.score_at,home,beforeHome);
      var afterAway=scoreFor(atbat.score_at,away,beforeAway);
      var runs=(afterHome+afterAway)-(beforeHome+beforeAway);
      if(runs>0){
        var beforeBat=batting===home?beforeHome:beforeAway;
        var beforeOpp=batting===home?beforeAway:beforeHome;
        var afterBat=batting===home?afterHome:afterAway;
        var afterOpp=batting===home?afterAway:afterHome;
        var type=eventType(beforeBat,beforeOpp,afterBat,afterOpp,beforeHome+beforeAway);
        if(type==="逆転"||type==="勝ち越し") leadChanges++;
        if(type==="同点") ties++;
        var batter=(atbat.batter&&atbat.batter.name)||"打者";
        var inning=number(atbat.inning),half=atbat.top_bottom||"";
        events.push({
          inning:inning,half:half,label:inning+"回"+half,type:type,
          team:batting,opponent:fielding,batter:batter,
          pitcher:pitcher,
          result:resultText(atbat),detail:String(atbat.result_detail||""),
          runs:runs,home_score:afterHome,away_score:afterAway,
          score:away+" "+afterAway+" - "+afterHome+" "+home,
          importance:importance(type,inning,afterBat-afterOpp,runs),
          is_homerun:/本塁打|本$/.test(String(atbat.result_summary||""))
        });
      }
      scores[home]=afterHome;scores[away]=afterAway;
    });

    var result=game.result||{},homeScore=number(result.home_score),awayScore=number(result.away_score);
    if(result.home_score==null) homeScore=scores[home];
    if(result.away_score==null) awayScore=scores[away];
    var winner=homeScore>awayScore?home:awayScore>homeScore?away:"";
    var loser=winner==home?away:winner==away?home:"";
    var turningPoint=events.slice().sort(function(a,b){return b.importance-a.importance;})[0]||null;
    var headline=winner?
      winner+"が"+awayScore+"－"+homeScore+(winner===home?"":"")+"で勝利":
      away+"と"+home+"は"+awayScore+"－"+homeScore+"で引き分け";
    // 表示順は常にビジター得点－ホーム得点。文章では勝者を先頭にする。
    if(winner===home) headline=home+"が"+homeScore+"－"+awayScore+"で勝利";
    else if(winner===away) headline=away+"が"+awayScore+"－"+homeScore+"で勝利";
    var sentences=[];
    if(events.length){
      var first=events[0];
      sentences.push(first.team+"が"+first.label+"に"+first.runs+"点を"+(first.type==="先制"?"先制":"記録"));
      if(turningPoint&&turningPoint!==first){
        sentences.push(turningPoint.label+"、"+turningPoint.batter+"の"+turningPoint.result+"が大きな転機となった");
      }
    }
    if(result.win_pitcher) sentences.push("勝利投手は"+result.win_pitcher);
    return {
      headline:headline,summary:sentences.join("。")+(sentences.length?"。":""),
      events:events,pitching_changes:pitchingChanges,turning_point:turningPoint,lead_changes:leadChanges,ties:ties,
      final:{home:home,away:away,home_score:homeScore,away_score:awayScore,winner:winner,loser:loser}
    };
  }

  return {buildGameStory:buildGameStory,gameStoryEventType:eventType};
});

(function(){
  "use strict";
  if(typeof document==="undefined") return;

  function addStoryLabHomeLink(){
    if(document.getElementById("story-lab-home-link")) return;
    var nav=document.querySelector(".viewswitch");
    if(!nav) return;

    var link=document.createElement("a");
    link.id="story-lab-home-link";
    link.href="story_insights.html";
    link.setAttribute("aria-label","NPB STORY LABを開く");
    link.innerHTML='<span style="font-size:18px">⚾</span><span><b>NPB STORY LAB</b><small>勝利のポイント・追い込んでからの配球・直近10試合の変化を見る</small></span><strong>開く →</strong>';
    link.style.cssText=[
      "display:flex","align-items:center","gap:10px","width:100%","margin:10px 0 4px",
      "padding:11px 14px","border:2px solid var(--accent)","border-radius:12px",
      "background:linear-gradient(135deg,var(--panel),var(--panel2))","color:var(--ink)",
      "text-decoration:none","box-shadow:var(--shadow)","font-family:var(--font-ui)"
    ].join(";");

    var label=link.querySelector("span:nth-child(2)");
    if(label) label.style.cssText="display:flex;flex:1;min-width:0;flex-direction:column;line-height:1.4";
    var title=link.querySelector("b");
    if(title) title.style.cssText="font-size:13px;color:var(--accent);letter-spacing:.04em";
    var sub=link.querySelector("small");
    if(sub) sub.style.cssText="font-size:10px;color:var(--muted);font-weight:500;margin-top:2px";
    var action=link.querySelector("strong");
    if(action) action.style.cssText="font-size:12px;color:var(--accent);white-space:nowrap";

    link.addEventListener("mouseenter",function(){link.style.transform="translateY(-1px)";});
    link.addEventListener("mouseleave",function(){link.style.transform="none";});
    nav.insertAdjacentElement("afterend",link);
  }

  if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",addStoryLabHomeLink);
  else addStoryLabHomeLink();
})();
