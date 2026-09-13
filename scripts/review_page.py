"""Render .cache/review.json as a self-contained review page. Usage: review_page.py OUT.html"""
import json, sys, html
from pathlib import Path
data = json.loads(Path('.cache/review.json').read_text())
out = Path(sys.argv[1])
payload = json.dumps([{k: c.get(k) for k in ('rank','score','peak','near','top','bottom','center','top_elevation','bottom_elevation','drop','band_length_m','length_m','mean_slope','max_raw_slope','steep_share','aspect','terrain','forest_share','forest_type','approach','sun_hours','block_dist_km')} for c in data['candidates']], ensure_ascii=False)
page = r'''<title>Trøndelag Ski Faces</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Semi+Condensed:wght@500;600;700&family=Source+Sans+3:ital,wght@0,400;0,600;1,400&display=swap">
<style>
:root{--paper:#f2f5f7;--card:#ffffff;--ink:#17252e;--ink2:#46596a;--mute:#7d8c99;--line:#d5dde4;--accent:#c9490f;--birch:#4e8a3a;--spruce:#1f5b46;--mixed:#7c8a2a;--open:#c9490f;--keep:#1f7a4d;--maybe:#b7791f;--skip:#8a95a0;--warn:#a8321f;--warnbg:#fbe9e5;--sun:#e2a72e}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--paper:#121a20;--card:#1a242c;--ink:#e6ecf1;--ink2:#b3c0cb;--mute:#7f8f9c;--line:#2c3a45;--accent:#f0733a;--birch:#7fc465;--spruce:#5fb391;--mixed:#b9c85a;--open:#f0733a;--keep:#5fcf93;--maybe:#e6b04a;--skip:#7f8f9c;--warn:#ff8a70;--warnbg:#3a201b;--sun:#f0c25a}}
:root[data-theme="dark"]{--paper:#121a20;--card:#1a242c;--ink:#e6ecf1;--ink2:#b3c0cb;--mute:#7f8f9c;--line:#2c3a45;--accent:#f0733a;--birch:#7fc465;--spruce:#5fb391;--mixed:#b9c85a;--open:#f0733a;--keep:#5fcf93;--maybe:#e6b04a;--skip:#7f8f9c;--warn:#ff8a70;--warnbg:#3a201b;--sun:#f0c25a}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:"Source Sans 3",-apple-system,"Segoe UI",Roboto,sans-serif;font-size:15px;line-height:1.45;padding-inline:clamp(16px,3vw,40px);padding-block:28px 60px}
h1,h2,.display{font-family:"Barlow Semi Condensed","Arial Narrow",sans-serif;font-weight:700;letter-spacing:.01em;text-wrap:balance}
h1{font-size:clamp(30px,4vw,44px);margin:0;line-height:1}
.lead{max-width:68ch;color:var(--ink2);margin:10px 0 0}
header{display:flex;flex-wrap:wrap;gap:24px 40px;align-items:flex-end;justify-content:space-between;border-bottom:2px solid var(--ink);padding-bottom:18px}
.stats{display:flex;gap:22px;flex-wrap:wrap;font-variant-numeric:tabular-nums}
.stats div{display:flex;flex-direction:column}.stats b{font-family:"Barlow Semi Condensed",sans-serif;font-size:26px;line-height:1;font-weight:600}.stats span{font-size:12px;color:var(--mute);text-transform:uppercase;letter-spacing:.08em}
.controls{display:flex;flex-wrap:wrap;gap:10px 18px;align-items:end;padding:16px 0;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--paper);z-index:2}
.controls label{display:flex;flex-direction:column;gap:3px;font-size:12px;color:var(--ink2);text-transform:uppercase;letter-spacing:.06em;font-weight:600}
.controls select,.controls input{font:inherit;font-size:14px;padding:5px 8px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--ink);min-width:110px}
.controls .count{margin-left:auto;color:var(--ink2);font-variant-numeric:tabular-nums}
.controls button{font:inherit;font-size:14px;padding:6px 12px;border:1px solid var(--ink);border-radius:6px;background:var(--card);color:var(--ink);cursor:pointer}
.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:13px;color:var(--ink2);padding:12px 0}
.legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;vertical-align:-1px}
ol{list-style:none;margin:0;padding:0;display:grid;gap:8px}
.row{display:grid;grid-template-columns:52px minmax(180px,1.4fr) minmax(150px,1fr) minmax(120px,.9fr) minmax(120px,.9fr) minmax(150px,1fr) auto;gap:6px 14px;align-items:start;background:var(--card);border:1px solid var(--line);border-left:5px solid var(--open);border-radius:6px;padding:10px 14px;font-variant-numeric:tabular-nums}
.row.trees{border-left-color:var(--birch)}.row.trees.conifer{border-left-color:var(--spruce)}.row.mixed{border-left-color:var(--mixed)}
.row.st-keep{box-shadow:inset 0 0 0 2px var(--keep)}.row.st-skip{opacity:.5}.row.st-maybe{box-shadow:inset 0 0 0 2px var(--maybe)}
.rank{font-family:"Barlow Semi Condensed",sans-serif;font-size:28px;font-weight:600;line-height:1;color:var(--ink)}
.rank small{display:block;font-size:11px;color:var(--mute);font-family:"Source Sans 3",sans-serif;font-weight:400;margin-top:2px}
.name{font-weight:600;font-size:16px}.name small,.cell small{display:block;color:var(--mute);font-size:12.5px;font-weight:400}
.cell b{font-weight:600}
.warn{color:var(--warn);font-weight:600}
.links{display:flex;flex-direction:column;gap:4px;font-size:13px}.links a{color:var(--accent);text-decoration:none;font-weight:600}.links a:hover{text-decoration:underline}
.review{grid-column:1/-1;display:flex;flex-wrap:wrap;gap:6px;align-items:center;border-top:1px dashed var(--line);padding-top:8px;margin-top:2px}
.review button{font:inherit;font-size:12.5px;padding:3px 10px;border-radius:999px;border:1px solid var(--line);background:transparent;color:var(--ink2);cursor:pointer}
.review button.on.keep{background:var(--keep);border-color:var(--keep);color:#fff}.review button.on.maybe{background:var(--maybe);border-color:var(--maybe);color:#fff}.review button.on.skip{background:var(--skip);border-color:var(--skip);color:#fff}
.review input{flex:1;min-width:160px;font:inherit;font-size:13px;padding:4px 8px;border:1px solid var(--line);border-radius:6px;background:var(--paper);color:var(--ink)}
.sunbar{display:inline-block;height:8px;background:var(--sun);border-radius:2px;vertical-align:middle;margin-right:5px}
.method{margin-top:36px;max-width:72ch;color:var(--ink2);font-size:14px}.method h2{font-size:20px;margin:0 0 6px;color:var(--ink)}
.method ul{padding-left:18px}
button:focus-visible,a:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media (max-width:900px){.row{grid-template-columns:44px 1fr 1fr}.row .cell:nth-child(n+4){grid-column:2/-1}.links{flex-direction:row;gap:14px;grid-column:2/-1}}
@media (prefers-reduced-motion: no-preference){.row{transition:box-shadow .15s}}
</style>
<header>
 <div><h1>Trøndelag Ski Faces</h1><p class="lead">Fall-line runs with long continuous 20–30° skiing, scanned from Kartverket 10 m terrain across the mountain blocks within about 180 km of Trondheim. Ranked by <em>in-band run length ÷ (1 + approach hours)</em>. Mark rows keep / maybe / skip — your marks stay in this browser.</p></div>
 <div class="stats"><div><b id="s-shown">0</b><span>shown</span></div><div><b id="s-pool">0</b><span>in pool</span></div><div><b>__BLOCKS__</b><span>blocks scanned</span></div><div><b>__RAW__</b><span>raw runs</span></div></div>
</header>
<div class="controls">
 <label>Terrain<select id="f-terrain"><option value="all">All</option><option value="open">Open</option><option value="trees">Trees</option><option value="deciduous">Birch / deciduous</option><option value="conifer">Spruce / conifer</option><option value="mixed">Mixed</option></select></label>
 <label>Bottom ≥ m<input id="f-bottom" type="number" value="500" step="50" min="0"></label>
 <label>Approach ≤ h<input id="f-approach" type="number" value="2.5" step="0.25" min="0"></label>
 <label>Aspect<select id="f-aspect"><option value="all">Any</option><option value="N">N (315–45°)</option><option value="E">E (45–135°)</option><option value="S">S (135–225°)</option><option value="W">W (225–315°)</option></select></label>
 <label>Sort<select id="f-sort"><option value="score">Score</option><option value="band">Continuous length</option><option value="drop">Drop</option><option value="approach">Approach</option><option value="sun">Sun hours</option></select></label>
 <label>Show<select id="f-limit"><option value="100">Top 100</option><option value="50">Top 50</option><option value="300">All</option></select></label>
 <label>Marks<select id="f-mark"><option value="all">All</option><option value="keep">Keep</option><option value="maybe">Maybe</option><option value="unmarked">Unmarked</option></select></label>
 <button id="copy" type="button">Copy shortlist</button>
 <span class="count" id="count"></span>
</div>
<div class="legend"><span><i style="background:var(--open)"></i>Open</span><span><i style="background:var(--birch)"></i>Birch / deciduous trees</span><span><i style="background:var(--spruce)"></i>Spruce / conifer trees</span><span><i style="background:var(--mixed)"></i>Mixed</span><span><i style="background:var(--sun)"></i>Potential sun 09–15 on 15 Mar</span></div>
<ol id="list"></ol>
<div class="method"><h2>How to read this</h2><ul>
<li><b>Continuous length</b> is metres along the fall line where 3×3-smoothed slope stays within 20–30°; the run may include short gentler benches (≤30 % of its length) but ends at anything steeper. Max slope is the raw 10 m value on the line — a 30–31° reading is a single steep step, not a cliff.</li>
<li><b>Approach</b> is straight-line from the nearest OpenStreetMap road to the bottom of the run, timed at 4 km/h + 400 m/h. Winter plowing, parking and the terrain in between are unknown — treat it as a lower bound.</li>
<li><b>Trees</b> come from NIBIO AR5 (Treslag). Birch usually means skiable spacing; spruce usually does not. Nothing here measures tree density.</li>
<li><b>Sun</b> is potential direct sun at the run's midpoint on 15 March, 09–15, from 100 m terrain horizons — geometry, not weather.</li>
<li>Generated __GEN__. Nothing on this page is a snow-stability assessment. Check NVE steepness/runout and the Varsom forecast for anything you keep.</li></ul></div>
<script>
const DATA=__DATA__;
const compass=d=>d==null?'?':['N','NE','E','SE','S','SW','W','NW'][Math.round(d/45)%8];
const dur=h=>h==null?'?':`${Math.floor(h)}h ${String(Math.round((h%1)*60)).padStart(2,'0')}`;
let marks={};try{marks=JSON.parse(localStorage.getItem('rando.review.marks')||'{}')}catch{}
const save=()=>{try{localStorage.setItem('rando.review.marks',JSON.stringify(marks))}catch{}};
const key=c=>c.center.map(v=>v.toFixed(4)).join(',');
const $=id=>document.getElementById(id);
function sector(a){if(a==null)return null;if(a>=315||a<45)return'N';if(a<135)return'E';if(a<225)return'S';return'W'}
function filtered(){
 const t=$('f-terrain').value,b=+$('f-bottom').value,ap=+$('f-approach').value,as=$('f-aspect').value,mk=$('f-mark').value;
 let rows=DATA.filter(c=>(c.bottom_elevation??0)>=b&&(c.approach?.hours??99)<=ap&&(as==='all'||sector(c.aspect)===as));
 rows=rows.filter(c=>t==='all'||(t==='open'&&c.terrain==='open')||(t==='trees'&&(c.terrain==='trees'||c.terrain==='mixed'))||(t==='mixed'&&c.terrain==='mixed')||((t==='deciduous'||t==='conifer')&&c.terrain!=='open'&&c.forest_type===t));
 rows=rows.filter(c=>{const m=marks[key(c)]?.mark;return mk==='all'||(mk==='unmarked'?!m:m===mk)});
 const s=$('f-sort').value;
 rows.sort((x,y)=>s==='score'?y.score-x.score:s==='band'?y.band_length_m-x.band_length_m:s==='drop'?(y.drop||0)-(x.drop||0):s==='approach'?(x.approach?.hours??99)-(y.approach?.hours??99):(y.sun_hours||0)-(x.sun_hours||0));
 return rows.slice(0,+$('f-limit').value);
}
function render(){
 const rows=filtered();$('s-shown').textContent=rows.length;$('s-pool').textContent=DATA.length;$('count').textContent=`${rows.length} shown`;
 $('list').innerHTML=rows.map((c,i)=>{const m=marks[key(c)]||{};const a=c.approach||{};const utm=null;
  const tree=c.terrain==='open'?'Open':c.terrain==='trees'?`${c.forest_type==='deciduous'?'Birch':c.forest_type==='conifer'?'Spruce':'Mixed'} trees · ${c.forest_share}%`:c.terrain==='mixed'?`Part forest (${c.forest_type==='deciduous'?'birch':c.forest_type==='conifer'?'spruce':'mixed'}) · ${c.forest_share}%`:'Terrain ?';
  return `<li class="row ${c.terrain||''} ${c.forest_type||''} ${m.mark?'st-'+m.mark:''}" data-k="${key(c)}">
  <div class="rank">${i+1}<small>#${c.rank} · ${c.score}</small></div>
  <div class="name">${c.peak?c.peak.replace(/ \(.*/,''):(c.near||'Unnamed').replace(/ \(.*/,'')}<small>${[c.peak,c.near].filter(Boolean).join(' · ')||'no place name within 3 km'}<br>${c.center[1].toFixed(4)}, ${c.center[0].toFixed(4)} · ${c.block_dist_km} km from Trondheim (straight line)</small></div>
  <div class="cell"><b>${c.band_length_m} m</b> continuous 20–30°<small>run ${c.length_m} m · ${Math.round(c.drop)} m drop · ${Math.round(c.top_elevation)}→${Math.round(c.bottom_elevation)} m</small></div>
  <div class="cell"><b>${compass(c.aspect)}</b> ${Math.round(c.aspect)}°<small>mean ${c.mean_slope?.toFixed(0)}°, max ${c.max_raw_slope?.toFixed(0)}°${c.steep_share>0?` <span class="warn">· ${c.steep_share}% ≥30°</span>`:''}</small></div>
  <div class="cell"><b>${tree}</b><small><span class="sunbar" style="width:${Math.min(60,(c.sun_hours||0)*10)}px"></span>${c.sun_hours==null?'sun ?':c.sun_hours+' h sun'}</small></div>
  <div class="cell"><b>${a.hours==null?'Approach ?':'≈ '+dur(a.hours)}</b><small>${a.distance_km==null?'no road data':`≥ ${a.distance_km} km, ${a.gain_m==null?'?':(a.gain_m>=0?'+':'')+Math.round(a.gain_m)} m from road`}</small></div>
  <div class="links"><a target="_blank" rel="noreferrer" href="https://norgeskart.no/#!?project=norgeskart&layers=1002&zoom=13&lat=${c.center[1]}&lon=${c.center[0]}&markerLat=${c.top[1]}&markerLon=${c.top[0]}&panel=Koordinater">Norgeskart</a><a target="_blank" rel="noreferrer" href="https://www.google.com/maps/dir/?api=1&origin=Trondheim&destination=${a.road?a.road[1]+','+a.road[0]:c.bottom[1]+','+c.bottom[0]}">Drive</a><a target="_blank" rel="noreferrer" href="https://www.google.com/maps/@?api=1&map_action=map&basemap=satellite&center=${c.center[1]},${c.center[0]}&zoom=15">Satellite</a></div>
  <div class="review">${['keep','maybe','skip'].map(k=>`<button type="button" class="${k} ${m.mark===k?'on':''}" data-mark="${k}">${k[0].toUpperCase()+k.slice(1)}</button>`).join('')}<input type="text" id="note-${c.rank}" placeholder="Note" value="${(m.note||'').replace(/"/g,'&quot;')}" data-note></div></li>`}).join('');
}
$('list').addEventListener('click',e=>{const b=e.target.closest('button[data-mark]');if(!b)return;const k=b.closest('.row').dataset.k;marks[k]={...marks[k],mark:marks[k]?.mark===b.dataset.mark?undefined:b.dataset.mark};save();render();});
$('list').addEventListener('input',e=>{if(!e.target.matches('[data-note]'))return;const k=e.target.closest('.row').dataset.k;marks[k]={...marks[k],note:e.target.value};save();});
for(const id of ['f-terrain','f-bottom','f-approach','f-aspect','f-sort','f-limit','f-mark'])$(id).addEventListener('input',render);
$('copy').addEventListener('click',async()=>{const kept=DATA.filter(c=>marks[key(c)]?.mark==='keep');const text=kept.map(c=>`${(c.peak||c.near||'Unnamed').replace(/ \(.*/,'')}\t${c.center[1].toFixed(5)},${c.center[0].toFixed(5)}\t${c.band_length_m} m ${compass(c.aspect)}\t${c.terrain}\tapproach ${dur(c.approach?.hours)}\t${marks[key(c)]?.note||''}`).join('\n');try{await navigator.clipboard.writeText(text);$('copy').textContent=`Copied ${kept.length}`;setTimeout(()=>$('copy').textContent='Copy shortlist',1500)}catch{alert(text)}});
render();
</script>'''
page = page.replace('__DATA__', payload).replace('__BLOCKS__', str(data['blocks'])).replace('__RAW__', str(data['raw'])).replace('__GEN__', html.escape(data['generated']))
out.write_text(page)
print(out, len(page)//1000, 'kB', len(data['candidates']), 'candidates')
