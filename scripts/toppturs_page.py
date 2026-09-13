"""Render .cache/toppturs.json as a review page. Usage: toppturs_page.py OUT.html"""
import json, sys, html
from pathlib import Path
data = json.loads(Path('.cache/toppturs.json').read_text())
out = Path(sys.argv[1])
payload = json.dumps(data['tours'], ensure_ascii=False)
page = r'''<title>Skarvatnet Toppturer</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Semi+Condensed:wght@500;600;700&family=Source+Sans+3:ital,wght@0,400;0,600;1,400&display=swap">
<style>
:root{--paper:#f2f5f7;--card:#ffffff;--ink:#17252e;--ink2:#46596a;--mute:#7d8c99;--line:#d5dde4;--accent:#c9490f;--up:#2b6cb0;--birch:#4e8a3a;--spruce:#1f5b46;--mixed:#7c8a2a;--open:#c9490f;--keep:#1f7a4d;--maybe:#b7791f;--skip:#8a95a0;--warn:#a8321f;--ok:#1f7a4d}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--paper:#121a20;--card:#1a242c;--ink:#e6ecf1;--ink2:#b3c0cb;--mute:#7f8f9c;--line:#2c3a45;--accent:#f0733a;--up:#7fb2f0;--birch:#7fc465;--spruce:#5fb391;--mixed:#b9c85a;--open:#f0733a;--keep:#5fcf93;--maybe:#e6b04a;--skip:#7f8f9c;--warn:#ff8a70;--ok:#5fcf93}}
:root[data-theme="dark"]{--paper:#121a20;--card:#1a242c;--ink:#e6ecf1;--ink2:#b3c0cb;--mute:#7f8f9c;--line:#2c3a45;--accent:#f0733a;--up:#7fb2f0;--birch:#7fc465;--spruce:#5fb391;--mixed:#b9c85a;--open:#f0733a;--keep:#5fcf93;--maybe:#e6b04a;--skip:#7f8f9c;--warn:#ff8a70;--ok:#5fcf93}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:"Source Sans 3",-apple-system,"Segoe UI",Roboto,sans-serif;font-size:15px;line-height:1.45;padding-inline:clamp(16px,3vw,40px);padding-block:28px 60px}
h1,h2{font-family:"Barlow Semi Condensed","Arial Narrow",sans-serif;font-weight:700;letter-spacing:.01em;text-wrap:balance}
h1{font-size:clamp(30px,4vw,44px);margin:0;line-height:1}
.lead{max-width:70ch;color:var(--ink2);margin:10px 0 0}
header{display:flex;flex-wrap:wrap;gap:24px 40px;align-items:flex-end;justify-content:space-between;border-bottom:2px solid var(--ink);padding-bottom:18px}
.stats{display:flex;gap:22px;flex-wrap:wrap;font-variant-numeric:tabular-nums}
.stats div{display:flex;flex-direction:column}.stats b{font-family:"Barlow Semi Condensed",sans-serif;font-size:26px;line-height:1;font-weight:600}.stats span{font-size:12px;color:var(--mute);text-transform:uppercase;letter-spacing:.08em}
.controls{display:flex;flex-wrap:wrap;gap:10px 18px;align-items:end;padding:16px 0;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--paper);z-index:2}
.controls label{display:flex;flex-direction:column;gap:3px;font-size:12px;color:var(--ink2);text-transform:uppercase;letter-spacing:.06em;font-weight:600}
.controls select,.controls input{font:inherit;font-size:14px;padding:5px 8px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--ink);min-width:100px}
.controls button{font:inherit;font-size:14px;padding:6px 12px;border:1px solid var(--ink);border-radius:6px;background:var(--card);color:var(--ink);cursor:pointer}
.controls .count{margin-left:auto;color:var(--ink2);font-variant-numeric:tabular-nums}
ol{list-style:none;margin:16px 0 0;padding:0;display:grid;gap:8px}
.row{display:grid;grid-template-columns:52px minmax(170px,1.2fr) minmax(200px,1.3fr) minmax(200px,1.3fr) auto;gap:6px 14px;align-items:start;background:var(--card);border:1px solid var(--line);border-radius:6px;padding:10px 14px;font-variant-numeric:tabular-nums}
.row.st-keep{box-shadow:inset 0 0 0 2px var(--keep)}.row.st-skip{opacity:.5}.row.st-maybe{box-shadow:inset 0 0 0 2px var(--maybe)}
.rank{font-family:"Barlow Semi Condensed",sans-serif;font-size:28px;font-weight:600;line-height:1}
.rank small{display:block;font-size:11px;color:var(--mute);font-family:"Source Sans 3",sans-serif;font-weight:400;margin-top:2px}
.name{font-weight:600;font-size:17px}.name small,.cell small{display:block;color:var(--mute);font-size:12.5px;font-weight:400}
.cell{border-left:3px solid var(--line);padding-left:10px}.cell.up{border-left-color:var(--up)}.cell.down{border-left-color:var(--open)}.cell.down.deciduous{border-left-color:var(--birch)}.cell.down.conifer{border-left-color:var(--spruce)}.cell.down.mixed{border-left-color:var(--mixed)}
.cell b{font-weight:600}.warn{color:var(--warn);font-weight:600}.ok{color:var(--ok);font-weight:600}
.bar{display:flex;height:6px;border-radius:3px;overflow:hidden;background:var(--line);margin-top:4px;max-width:220px}.bar i{display:block;height:100%}
.links{display:flex;flex-direction:column;gap:4px;font-size:13px}.links a{color:var(--accent);text-decoration:none;font-weight:600}.links a:hover{text-decoration:underline}
.review{grid-column:1/-1;display:flex;flex-wrap:wrap;gap:6px;align-items:center;border-top:1px dashed var(--line);padding-top:8px;margin-top:2px}
.review button{font:inherit;font-size:12.5px;padding:3px 10px;border-radius:999px;border:1px solid var(--line);background:transparent;color:var(--ink2);cursor:pointer}
.review button.on.keep{background:var(--keep);border-color:var(--keep);color:#fff}.review button.on.maybe{background:var(--maybe);border-color:var(--maybe);color:#fff}.review button.on.skip{background:var(--skip);border-color:var(--skip);color:#fff}
.review input{flex:1;min-width:160px;font:inherit;font-size:13px;padding:4px 8px;border:1px solid var(--line);border-radius:6px;background:var(--paper);color:var(--ink)}
.method{margin-top:36px;max-width:74ch;color:var(--ink2);font-size:14px}.method h2{font-size:20px;margin:0 0 6px;color:var(--ink)}.method ul{padding-left:18px}
button:focus-visible,a:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media (max-width:900px){.row{grid-template-columns:44px 1fr}.row .cell,.links{grid-column:2}.links{flex-direction:row;gap:14px}}
</style>
<header>
 <div><h1>Skarvatnet Toppturer</h1><p class="lead">Summits within __DRIVE__ min drive of Skarvatnet (Oppdal), each with the gentlest ascent line the terrain allows from a road — nothing steeper than 35°, and 30–35° avoided where possible — and the best continuous 20–30° descent from near the top. Ranked by descent length. Mark keep / maybe / skip; marks stay in this browser.</p></div>
 <div class="stats"><div><b id="s-shown">0</b><span>shown</span></div><div><b>__N__</b><span>summits in 1 h</span></div><div><b>__ALL__</b><span>summits scanned</span></div></div>
</header>
<div class="controls">
 <label>Ascent max slope ≤<select id="f-slope"><option value="35">35°</option><option value="30">30°</option><option value="28">28°</option><option value="25">25°</option></select></label>
 <label>Ascent ≤ h<input id="f-hours" type="number" value="4.5" step="0.5" min="0"></label>
 <label>Ascent ≥ h<input id="f-minh" type="number" value="0" step="0.5" min="0"></label>
 <label>Descent ≥ m<input id="f-run" type="number" value="300" step="50" min="0"></label>
 <label>Descent aspect<select id="f-aspect"><option value="all">Any</option><option value="N">N</option><option value="E">E</option><option value="S">S</option><option value="W">W</option></select></label>
 <label>Drive ≤ min<input id="f-drive" type="number" value="__DRIVE__" step="5" min="0"></label>
 <label>Sort<select id="f-sort"><option value="run">Descent length</option><option value="drop">Descent drop</option><option value="hours">Ascent time</option><option value="drive">Drive</option><option value="elev">Elevation</option></select></label>
 <label>Marks<select id="f-mark"><option value="all">All</option><option value="keep">Keep</option><option value="maybe">Maybe</option><option value="unmarked">Unmarked</option></select></label>
 <button id="copy" type="button">Copy shortlist</button><span class="count" id="count"></span>
</div>
<ol id="list"></ol>
<div class="method"><h2>How to read this</h2><ul>
<li><b>Ascent</b> is a least-cost path on the 10 m grid from the nearest OpenStreetMap road: cells ≥35° are impassable, 30–35° cost ×4, 25–30° ×1.8, 20–25° ×1.3, so the line hunts for the gentlest way up. Max slope is the raw 10 m value under the line; "≥30°" is the share of the line on 30–35° ground. It is a terrain possibility, not a checked route — cornices, cliff bands narrower than 10 m, rivers and private roads are invisible to it.</li>
<li><b>Descent</b> is the longest fall-line run inside 20–30° that starts within 800 m of and at most 200 m below the summit; "to car" is the straight-line distance from its bottom to where the ascent left the road.</li>
<li><b>Drive</b> is OSRM routing on OpenStreetMap from Skarvatnet to the ascent start — summer roads; winter closures and where you can actually park are unknown.</li>
<li>Trees from NIBIO AR5 (birch usually skiable, spruce usually not). Generated __GEN__. Nothing here is a snow-stability assessment — check NVE steepness/runout and the Varsom forecast for anything you keep.</li></ul></div>
<script>
const DATA=__DATA__;
const compass=d=>d==null?'?':['N','NE','E','SE','S','SW','W','NW'][Math.round(d/45)%8];
const dur=h=>h==null?'?':`${Math.floor(h)}h ${String(Math.round((h%1)*60)).padStart(2,'0')}`;
const sector=a=>a==null?null:(a>=315||a<45)?'N':a<135?'E':a<225?'S':'W';
let marks={};try{marks=JSON.parse(localStorage.getItem('rando.toppturs.marks')||'{}')}catch{}
const save=()=>{try{localStorage.setItem('rando.toppturs.marks',JSON.stringify(marks))}catch{}};
const key=t=>t.summit.map(v=>v.toFixed(4)).join(',');const $=id=>document.getElementById(id);
function filtered(){
 const sl=+$('f-slope').value,h=+$('f-hours').value,mh=+$('f-minh').value,run=+$('f-run').value,as=$('f-aspect').value,dr=+$('f-drive').value,mk=$('f-mark').value,s=$('f-sort').value;
 let rows=DATA.filter(t=>t.ascent&&t.ascent.max_slope<=sl&&t.ascent.hours<=h&&t.ascent.hours>=mh&&(t.drive_min??999)<=dr&&(run===0?true:(t.descent&&t.descent.band_length_m>=run))&&(as==='all'||(t.descent&&sector(t.descent.aspect)===as)));
 rows=rows.filter(t=>{const m=marks[key(t)]?.mark;return mk==='all'||(mk==='unmarked'?!m:m===mk)});
 rows.sort((x,y)=>s==='run'?((y.descent?.band_length_m||0)-(x.descent?.band_length_m||0)):s==='drop'?((y.descent?.drop||0)-(x.descent?.drop||0)):s==='hours'?x.ascent.hours-y.ascent.hours:s==='drive'?x.drive_min-y.drive_min:y.elevation-x.elevation);
 return rows;
}
function render(){
 const rows=filtered();$('s-shown').textContent=rows.length;$('count').textContent=`${rows.length} shown`;
 $('list').innerHTML=rows.map((t,i)=>{const m=marks[key(t)]||{};const a=t.ascent,d=t.descent;
  const tree=d?(d.forest_share===0||d.forest_share==null?'open':`${d.forest_type==='deciduous'?'birch':d.forest_type==='conifer'?'spruce':'mixed'} ${d.forest_share}%`):'';
  return `<li class="row ${m.mark?'st-'+m.mark:''}" data-k="${key(t)}">
  <div class="rank">${i+1}<small>${t.drive_min} min drive</small></div>
  <div class="name">${t.name||'Unnamed summit'} <span style="font-weight:400">${Math.round(t.elevation)} m</span><small>${t.name?`${t.kind.toLowerCase()} · name ${t.dist} m from the grid summit`:'no named summit within 600 m'}<br>${t.summit[1].toFixed(4)}, ${t.summit[0].toFixed(4)}</small></div>
  <div class="cell up"><b>Up ${dur(a.hours)}</b> · +${a.gain_m} m over ${(a.length_m/1000).toFixed(1)} km<small>max <span class="${a.max_slope>=30?'warn':'ok'}">${a.max_slope.toFixed(0)}°</span>, mean ${a.mean_slope.toFixed(0)}° · ${a.share_over_30>0?`<span class="warn">${a.share_over_30}% on 30–35°</span>`:'never over 30°'} · ${a.share_over_25}% over 25° · forest ${a.forest_share??'?'}%</small><div class="bar" title="share of ascent over 25° / over 30°"><i style="width:${a.share_over_25}%;background:var(--maybe)"></i><i style="width:${a.share_over_30}%;background:var(--warn)"></i></div></div>
  ${d?`<div class="cell down ${d.forest_type||''}"><b>Down ${d.band_length_m} m</b> of 20–30° · ${compass(d.aspect)} ${Math.round(d.aspect)}°<small>${Math.round(d.drop)} m drop, ${Math.round(d.top_elevation)}→${Math.round(d.bottom_elevation)} m · mean ${d.mean_slope.toFixed(0)}°, max ${d.max_slope.toFixed(0)}°${d.steep_share>0?` <span class="warn">· ${d.steep_share}% ≥30°</span>`:''}<br>starts ${d.start_offset_m} m from summit, ${Math.round(d.start_below_summit_m)} m below · ${tree} · ends ${d.end_to_car_km} km from car</small></div>`:`<div class="cell down"><b>No 300 m run</b> of 20–30° near the summit<small>gentle or broken terrain near the top</small></div>`}
  <div class="links"><a target="_blank" rel="noreferrer" href="https://norgeskart.no/#!?project=norgeskart&layers=1002&zoom=13&lat=${t.summit[1]}&lon=${t.summit[0]}&markerLat=${t.summit[1]}&markerLon=${t.summit[0]}">Norgeskart</a><a target="_blank" rel="noreferrer" href="https://www.google.com/maps/dir/?api=1&origin=62.69398,9.54917&destination=${a.start[1]},${a.start[0]}">Drive to start</a><a target="_blank" rel="noreferrer" href="https://www.google.com/maps/@?api=1&map_action=map&basemap=satellite&center=${t.summit[1]},${t.summit[0]}&zoom=14">Satellite</a></div>
  <div class="review">${['keep','maybe','skip'].map(k=>`<button type="button" class="${k} ${m.mark===k?'on':''}" data-mark="${k}">${k[0].toUpperCase()+k.slice(1)}</button>`).join('')}<input type="text" id="note-${key(t).replace(/[^\d]/g,'')}" placeholder="Note" value="${(m.note||'').replace(/"/g,'&quot;')}" data-note></div></li>`}).join('');
}
$('list').addEventListener('click',e=>{const b=e.target.closest('button[data-mark]');if(!b)return;const k=b.closest('.row').dataset.k;marks[k]={...marks[k],mark:marks[k]?.mark===b.dataset.mark?undefined:b.dataset.mark};save();render();});
$('list').addEventListener('input',e=>{if(!e.target.matches('[data-note]'))return;const k=e.target.closest('.row').dataset.k;marks[k]={...marks[k],note:e.target.value};save();});
for(const id of ['f-slope','f-hours','f-minh','f-run','f-aspect','f-drive','f-sort','f-mark'])$(id).addEventListener('input',render);
$('copy').addEventListener('click',async()=>{const kept=DATA.filter(t=>marks[key(t)]?.mark==='keep');const text=kept.map(t=>`${t.name||'Unnamed'} ${Math.round(t.elevation)} m\t${t.summit[1].toFixed(5)},${t.summit[0].toFixed(5)}\tup ${dur(t.ascent.hours)} max ${t.ascent.max_slope.toFixed(0)}°\tdown ${t.descent?t.descent.band_length_m+' m '+compass(t.descent.aspect):'-'}\t${t.drive_min} min\t${marks[key(t)]?.note||''}`).join('\n');try{await navigator.clipboard.writeText(text);$('copy').textContent=`Copied ${kept.length}`;setTimeout(()=>$('copy').textContent='Copy shortlist',1500)}catch{alert(text)}});
render();
</script>'''
page = page.replace('__DATA__', payload).replace('__DRIVE__', str(int(data['max_drive']))).replace('__N__', str(len(data['tours']))).replace('__ALL__', str(data['summits'])).replace('__GEN__', html.escape(data['generated']))
out.write_text(page)
print(out, len(page)//1000, 'kB', len(data['tours']), 'tours')
