(function(root,factory){
  var api=factory();
  if(typeof module!=="undefined"&&module.exports) module.exports=api;
  Object.keys(api).forEach(function(key){root[key]=api[key];});
})(typeof globalThis!=="undefined"?globalThis:this,function(){
  "use strict";

  function rounded(ctx,x,y,w,h,r){
    r=Math.min(r,w/2,h/2);ctx.beginPath();ctx.moveTo(x+r,y);ctx.arcTo(x+w,y,x+w,y+h,r);
    ctx.arcTo(x+w,y+h,x,y+h,r);ctx.arcTo(x,y+h,x,y,r);ctx.arcTo(x,y,x+w,y,r);ctx.closePath();
  }
  function fitText(ctx,text,maxWidth,startSize,minSize,weight){
    var size=startSize;text=String(text||"");
    do{ctx.font=(weight||700)+" "+size+"px 'Noto Sans JP','Yu Gothic UI',sans-serif";size-=2;}
    while(size>=minSize&&ctx.measureText(text).width>maxWidth);
    return text;
  }
  function drawLines(ctx,lines,x,y,maxWidth,lineHeight,maxLines){
    (lines||[]).slice(0,maxLines||6).forEach(function(line,index){
      fitText(ctx,line,maxWidth,31,21,700);ctx.fillText(String(line),x,y+index*lineHeight);
    });
  }
  function drawSocialCard(canvas,model){
    if(!canvas||!model) return;
    var ctx=canvas.getContext("2d"),w=1200,h=675;canvas.width=w;canvas.height=h;
    var gradient=ctx.createLinearGradient(0,0,w,h);gradient.addColorStop(0,"#fff9f0");gradient.addColorStop(.62,"#fff1dd");gradient.addColorStop(1,"#ffd8a8");
    ctx.fillStyle=gradient;ctx.fillRect(0,0,w,h);
    ctx.fillStyle=model.accent||"#e8590c";ctx.fillRect(0,0,24,h);ctx.fillRect(0,0,w,12);
    ctx.globalAlpha=.09;ctx.fillStyle=model.accent||"#e8590c";ctx.beginPath();ctx.arc(1080,85,210,0,Math.PI*2);ctx.fill();ctx.beginPath();ctx.arc(1040,650,290,0,Math.PI*2);ctx.fill();ctx.globalAlpha=1;
    ctx.fillStyle="#6b4a28";ctx.font="800 24px Roboto,'Noto Sans JP',sans-serif";ctx.letterSpacing="4px";ctx.fillText("NPB SCOREBOARD",70,62);
    ctx.textAlign="right";ctx.font="700 23px 'Noto Sans JP',sans-serif";ctx.fillStyle="#9a7b57";ctx.fillText(model.date||"",1130,62);ctx.textAlign="left";
    ctx.fillStyle=model.accent||"#e8590c";ctx.font="800 28px 'Noto Sans JP',sans-serif";ctx.fillText(model.kicker||"TODAY'S NPB",70,118);
    fitText(ctx,model.title,1060,58,34,800);ctx.fillStyle="#3d2510";ctx.fillText(model.title||"",70,181);

    rounded(ctx,70,220,1060,340,28);ctx.fillStyle="rgba(255,255,255,.82)";ctx.fill();ctx.strokeStyle="rgba(232,89,12,.22)";ctx.lineWidth=2;ctx.stroke();
    if(model.layout==="score"){
      ctx.textAlign="center";fitText(ctx,model.away,310,38,24,800);ctx.fillStyle=model.away_color||"#3d2510";ctx.fillText(model.away||"",290,300);
      fitText(ctx,model.home,310,38,24,800);ctx.fillStyle=model.home_color||"#3d2510";ctx.fillText(model.home||"",910,300);
      ctx.font="800 112px Roboto,'Noto Sans JP',sans-serif";ctx.fillStyle="#3d2510";ctx.fillText(String(model.away_score),390,420);ctx.fillText(String(model.home_score),810,420);
      ctx.font="700 52px Roboto,sans-serif";ctx.fillStyle="#9a7b57";ctx.fillText("–",600,400);
      ctx.font="700 23px 'Noto Sans JP',sans-serif";ctx.fillStyle="#6b4a28";ctx.fillText(model.subtitle||"試合終了",600,470);
      ctx.font="600 22px 'Noto Sans JP',sans-serif";ctx.fillStyle="#9a7b57";ctx.fillText(model.detail||"",600,520);ctx.textAlign="left";
    }else if(model.layout==="mvp"){
      ctx.fillStyle=model.badge_color||model.accent||"#e8590c";rounded(ctx,105,255,215,64,18);ctx.fill();
      ctx.fillStyle="#fff";ctx.font="800 25px 'Noto Sans JP',sans-serif";ctx.textAlign="center";ctx.fillText(model.badge||"MVP",212,297);ctx.textAlign="left";
      fitText(ctx,model.primary,730,55,34,800);ctx.fillStyle="#3d2510";ctx.fillText(model.primary||"",360,306);
      ctx.font="700 28px 'Noto Sans JP',sans-serif";ctx.fillStyle=model.accent||"#e8590c";ctx.fillText(model.secondary||"",108,380);
      ctx.font="600 25px 'Noto Sans JP',sans-serif";ctx.fillStyle="#6b4a28";drawLines(ctx,model.lines,108,435,930,42,3);
    }else{
      ctx.fillStyle=model.accent||"#e8590c";ctx.font="800 82px Roboto,'Noto Sans JP',sans-serif";ctx.fillText(String(model.count||0),105,330);
      ctx.font="800 25px 'Noto Sans JP',sans-serif";ctx.fillStyle="#6b4a28";ctx.fillText(model.count_label||"本",105,370);
      ctx.font="700 28px 'Noto Sans JP',sans-serif";ctx.fillStyle="#3d2510";drawLines(ctx,model.lines,300,294,760,47,6);
    }
    ctx.fillStyle="#9a7b57";ctx.font="600 19px 'Noto Sans JP',sans-serif";ctx.fillText(model.footer||"収集済みNPB公式記録をもとに作成",70,625);
    ctx.textAlign="right";ctx.fillStyle=model.accent||"#e8590c";ctx.font="800 22px Roboto,sans-serif";ctx.fillText("#NPB",1130,625);ctx.textAlign="left";
  }
  function socialCardBlob(canvas){
    return new Promise(function(resolve){canvas.toBlob(resolve,"image/png",1);});
  }
  async function downloadSocialCard(canvas,fileName){
    var blob=await socialCardBlob(canvas),link=document.createElement("a");
    link.href=URL.createObjectURL(blob);link.download=fileName||"npb-card.png";link.click();
    setTimeout(function(){URL.revokeObjectURL(link.href);},1000);return blob;
  }
  async function copySocialCard(canvas){
    var blob=await socialCardBlob(canvas);
    if(!navigator.clipboard||typeof ClipboardItem==="undefined") throw new Error("clipboard unavailable");
    await navigator.clipboard.write([new ClipboardItem({"image/png":blob})]);return blob;
  }
  return {drawSocialCard:drawSocialCard,downloadSocialCard:downloadSocialCard,copySocialCard:copySocialCard};
});
