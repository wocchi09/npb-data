(function(root) {
  'use strict';
  const ratio = (a, b) => b ? a / b : null;
  const key = r => [r.date, r.game_id, r.atbat_index].join('|');
  const known = v => typeof v === 'number' && Number.isFinite(v);
  const expand = (columns, rows) => rows.map(r => Object.fromEntries(columns.map((c, i) => [c, r[i]])));
  function decode(data) { return {player: data.player, atbats: expand(data.ab_columns, data.atbats), pitches: expand(data.pitch_columns, data.pitches)}; }
  function validate(s) {
    const validDate = d => /^\d{4}-\d{2}-\d{2}$/.test(d || '') && !isNaN(Date.parse(d)) && new Date(d).toISOString().slice(0, 10) === d;
    if (![s.a0, s.a1, s.b0, s.b1].every(validDate)) return '4つの日付を正しく指定してください。';
    if (s.a0 > s.a1 || s.b0 > s.b1) return '開始日は終了日以前にしてください。';
    if (s.a0 <= s.b1 && s.b0 <= s.a1) return '期間Aと期間Bが重なっています。重ならない期間を指定してください。';
    return '';
  }
  function wilson(successes, total) {
    if (!total) return null;
    const z = 1.96, p = successes / total, d = 1 + z*z/total;
    const mid = (p + z*z/(2*total)) / d, margin = z*Math.sqrt(p*(1-p)/total + z*z/(4*total*total))/d;
    return [Math.max(0, mid-margin), Math.min(1, mid+margin)];
  }
  function pitchMatches(p, s) {
    return (!s.type || p.pitch_type === s.type) && (!s.count || p.count_before === s.count) && (!s.zone || p.zone_label === s.zone);
  }
  function cohort(data, s, lo, hi) {
    let abs = data.atbats.filter(r => r.date >= lo && r.date <= hi &&
      (!s.hand || (data.player.role === 'pitcher' ? r.bat_hand : r.pit_hand) === s.hand) &&
      (!s.risp || r.risp === (s.risp === 'yes')));
    const allowed = new Set(abs.map(key));
    const all = data.pitches.filter(r => allowed.has(key(r)));
    const pitches = all.filter(p => pitchMatches(p, s));
    if (s.type || s.count || s.zone) {
      const qualifying = new Set(pitches.map(key));
      abs = abs.filter(r => qualifying.has(key(r)));
    }
    return {atbats: abs, pitches, all};
  }
  function summarize(c) {
    const ps = c.pitches, abs = c.atbats;
    // OPS uses only complete PA components; missing values are never silently zero-filled.
    const fields = ['ab','hit','single','double','triple','hr','bb','hbp','sf'];
    const complete = abs.filter(r => fields.every(f => known(r[f])));
    const sum = f => complete.reduce((n,r) => n+r[f],0);
    const obp = ratio(sum('hit')+sum('bb')+sum('hbp'), sum('ab')+sum('bb')+sum('hbp')+sum('sf'));
    const slg = ratio(sum('single')+2*sum('double')+3*sum('triple')+4*sum('hr'), sum('ab'));
    const swings = ps.filter(p => p.is_swing === true && typeof p.is_miss === 'boolean');
    const misses = swings.filter(p => p.is_miss).length;
    const outside = ps.filter(p => p.in_zone === false && typeof p.is_swing === 'boolean');
    const chase = outside.filter(p => p.is_swing).length;
    const speeds = ps.filter(p => p.pitch_type === 'ストレート' && known(p.speed_kmh) && p.speed_kmh > 0);
    const types = {}, zones = {};
    ps.forEach(p => { if(p.pitch_type) types[p.pitch_type]=(types[p.pitch_type]||0)+1; if(p.zone_label) zones[p.zone_label]=(zones[p.zone_label]||0)+1; });
    return {pa: abs.length, pitches: ps.length, games: new Set(abs.map(r=>r.game_id)).size,
      ops: obp == null || slg == null ? null : obp+slg, complete_pa: complete.length,
      whiff: ratio(misses, swings.length), swings: swings.length, misses, whiff_ci: wilson(misses,swings.length),
      chase: ratio(chase,outside.length), outside: outside.length, chase_ci: wilson(chase,outside.length),
      speed: ratio(speeds.reduce((n,p)=>n+p.speed_kmh,0),speeds.length), speed_n: speeds.length,
      types,zones, quality: {speed: ps.filter(p=>known(p.speed_kmh)&&p.speed_kmh>0).length,
        zone: ps.filter(p=>p.zone_label).length, result: ps.filter(p=>typeof p.is_swing==='boolean'&&typeof p.is_miss==='boolean').length,
        type: ps.filter(p=>p.pitch_type).length}};
  }
  function sequences(c, s) {
    const groups = new Map();
    c.all.forEach(p=>{const k=key(p);if(!groups.has(k))groups.set(k,[]);groups.get(k).push(p);});
    const transitions = new Map();
    groups.forEach(ps=>{
      ps.sort((a,b)=>a.pitch_no-b.pitch_no);
      for(let i=1;i<ps.length;i++) {
        const a=ps[i-1],b=ps[i];
        if (!known(a.pitch_no)||b.pitch_no!==a.pitch_no+1||!a.pitch_type||!b.pitch_type||!pitchMatches(b,s)) continue;
        const label=[a.pitch_type,a.zone_label||'コース未取得',b.pitch_type].join(' → ');
        if(!transitions.has(label))transitions.set(label,{label,n:0,swings:0,misses:0,refs:new Set()});
        const t=transitions.get(label); t.n++; t.refs.add(key(b));
        if(b.is_swing===true && typeof b.is_miss==='boolean'){t.swings++;if(b.is_miss)t.misses++;}
      }
    });
    return [...transitions.values()].map(t=>({...t,whiff:ratio(t.misses,t.swings),refs:[...t.refs]})).sort((a,b)=>b.n-a.n||a.label.localeCompare(b.label));
  }
  function compare(data,s) {
    const error=validate(s);if(error)throw new Error(error);
    const a=cohort(data,s,s.a0,s.a1),b=cohort(data,s,s.b0,s.b1);
    return {a,b,sa:summarize(a),sb:summarize(b),seqA:sequences(a,s),seqB:sequences(b,s)};
  }
  function replay(r) {
    if(!/^\d{4}-\d{2}-\d{2}$/.test(r.date)||!/^\d+$/.test(r.game_id)||!/^\d+$/.test(r.atbat_index))return null;
    return 'pitch_replay.html?'+new URLSearchParams({game:'data/'+r.date.replace(/-/g,'/')+'/'+r.game_id+'.json',atbat:r.atbat_index});
  }
  const api={decode,validate,wilson,cohort,summarize,sequences,compare,replay,key};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.Workbench=api;
})(typeof window!=='undefined'?window:globalThis);
