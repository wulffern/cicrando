import React,{useCallback,useEffect,useMemo,useRef,useState} from 'react';
import {AlertTriangle,ChevronDown,ChevronUp,Download,Info,LoaderCircle,Mountain,Navigation,Pencil,Save,Search,Sun,Trash2,Undo2,Upload,X} from 'lucide-react';
import MapView from './Map';
import {Area,Bounds,Candidate,Inspection,Point,Preferences,REGIONS,RouteResult,SavedPlan,SearchResult,Tour,TourSet,api,clock,compass,defaults,download,duration,osloDate,parseGPX,parsePlan,toGPX,validPreferences,validPoints} from './lib';

type Job={job:string;status:'loading'|'ready'|'error';area_id:string;area?:Area;message?:string};
type SearchJob={job:string;status:'loading'|'ready'|'error';result?:SearchResult;message?:string};
type Weather={properties:{meta:{updated_at:string};timeseries:{time:string;data:{instant:{details:{air_temperature?:number;cloud_area_fraction?:number;wind_speed?:number;wind_from_direction?:number}};next_1_hours?:{details:{precipitation_amount?:number}}}}[]}};
type Problem={AvalancheProblemTypeName:string;AvalancheExtName:string;AvalCauseName:string;AvalProbabilityName:string;AvalTriggerSimpleName:string;DestructiveSizeExtName:string;AvalPropagationName:string;ValidExpositions:string;ExposedHeight1:number;ExposedHeight2:number;ExposedHeightFill:number;TriggerSenitivityPropagationDestuctiveSizeText:string};
type Warning={RegId:number;RegionName:string;DangerLevel:string;DangerLevelName:string;ValidFrom:string;ValidTo:string;PublishTime:string;NextWarningTime:string|null;MainText:string|null;AvalancheDanger:string|null;SnowSurface:string|null;CurrentWeaklayers:string|null;LatestAvalancheActivity:string|null;LatestObservations:string|null;EmergencyWarning:string|null;Author:string|null;DangerIncreaseTime:string|null;DangerDecreaseTime:string|null;AvalancheProblems:Problem[]|null;AvalancheAdvices:{Text:string}[]|null;MountainWeather:{Comment?:string|null;MeasurementTypes?:{Name:string;MeasurementSubTypes:{Name:string;Value:string}[]}[]}|null};
type Conditions={fetched_at:string;avalanche:Warning[]|null;weather:Weather|null;errors:{avalanche?:string;weather?:string}};

const PLANS_KEY='rando.plans.v1',PREF_KEY='rando.preferences.v1';
function loadJSON<T>(key:string,check:(v:unknown)=>v is T,fallback:T):T{try{const v=JSON.parse(localStorage.getItem(key)??'');return check(v)?v:fallback;}catch{return fallback;}}
const isPlans=(v:unknown):v is SavedPlan[]=>Array.isArray(v)&&v.every(p=>{try{parsePlan(JSON.stringify(p));return true;}catch{return false;}});
function expositions(bits:string){return bits.split('').map((b,i)=>b==='1'?['N','NE','E','SE','S','SW','W','NW'][i]:null).filter(Boolean).join(' ')||'none';}
function heightText(p:Problem){const h1=p.ExposedHeight1,h2=p.ExposedHeight2;switch(p.ExposedHeightFill){case 1:return `above ${h1} m`;case 2:return `below ${h1} m`;case 3:return `above ${h1} m and below ${h2} m`;case 4:return `between ${h2} m and ${h1} m`;default:return 'all elevations';}}
function fmtTime(iso:string){return new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/Oslo',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}).format(new Date(iso.endsWith('Z')||/[+-]\d\d:\d\d$/.test(iso)?iso:iso+'+02:00'));}

export default function App(){
 const [preferences,setPreferences]=useState<Preferences>(()=>loadJSON(PREF_KEY,validPreferences,defaults));
 const [center,setCenter]=useState<Point>(REGIONS[0].center),[flyTarget,setFlyTarget]=useState<Point>(REGIONS[0].center);
 const [area,setArea]=useState<Area|null>(null),[loading,setLoading]=useState(false),[areaError,setAreaError]=useState('');
 const [selected,setSelected]=useState<Point|null>(null),[inspection,setInspection]=useState<Inspection|null>(null),[inspectError,setInspectError]=useState('');
 const [points,setPoints]=useState<Point[]>([]),[drawing,setDrawing]=useState(false),[route,setRoute]=useState<RouteResult|null>(null),[routeError,setRouteError]=useState(''),[routeBusy,setRouteBusy]=useState(false);
 const [hazards,setHazards]=useState(true),[conditions,setConditions]=useState<Conditions|null>(null),[conditionsError,setConditionsError]=useState('');
 const [plans,setPlans]=useState<SavedPlan[]>(()=>loadJSON(PLANS_KEY,isPlans,[])),[planName,setPlanName]=useState('');
 const [sheet,setSheet]=useState<'peek'|'half'|'full'>('half'),[section,setSection]=useState<string>('tours'),[notice,setNotice]=useState('');
 const [tourSet,setTourSet]=useState<TourSet|null>(null),[tourError,setTourError]=useState(''),[activeTour,setActiveTour]=useState<number|null>(null),[tourSlope,setTourSlope]=useState(35),[tourMaxH,setTourMaxH]=useState(4.5),[tourMinRun,setTourMinRun]=useState(300),[tourSort,setTourSort]=useState<'run'|'hours'|'drive'|'elev'>('run'),[showTours,setShowTours]=useState(true);
 const [view,setView]=useState<Bounds|null>(null),[searching,setSearching]=useState(false),[searchError,setSearchError]=useState(''),[result,setResult]=useState<SearchResult|null>(null),[minLength,setMinLength]=useState(500),[terrainFilter,setTerrainFilter]=useState<'all'|'open'|'trees'>('all'),[active,setActive]=useState<string|null>(null);
 const gpxInput=useRef<HTMLInputElement>(null),planInput=useRef<HTMLInputElement>(null);
 const update=(patch:Partial<Preferences>)=>setPreferences(p=>({...p,...patch}));
 useEffect(()=>{try{localStorage.setItem(PREF_KEY,JSON.stringify(preferences));}catch{/* private mode */}},[preferences]);
 useEffect(()=>{try{localStorage.setItem(PLANS_KEY,JSON.stringify(plans));}catch{/* private mode */}},[plans]);
 useEffect(()=>{if(!notice)return;const t=setTimeout(()=>setNotice(''),4000);return()=>clearTimeout(t);},[notice]);

 const loadArea=useCallback(async(p:Point)=>{
  setLoading(true);setAreaError('');setSelected(null);setInspection(null);
  try{
   let job=await api<Job>('/api/areas',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lon:p[0],lat:p[1]})});
   const id=job.job;
   while(job.status==='loading'){await new Promise(r=>setTimeout(r,700));job=await api<Job>(`/api/jobs/${id}`);}
   if(job.status==='error'||!job.area)throw new Error(job.message??'Terrain could not be loaded.');
   setArea(job.area);setFlyTarget(job.area.center);
  }catch(e){setAreaError(e instanceof Error?e.message:'Terrain could not be loaded.');}
  finally{setLoading(false);}
 },[]);

 // Inspection follows the selected point, the day and the outing window.
 useEffect(()=>{
  if(!area||!selected)return;
  const [lon,lat]=selected;const ctrl=new AbortController();
  const qs=new URLSearchParams({lon:String(lon),lat:String(lat),day:preferences.day,start:String(preferences.start),end:String(preferences.end)});
  setInspectError('');
  api<Inspection>(`/api/areas/${area.id}/inspect?${qs}`,{signal:ctrl.signal}).then(setInspection).catch(e=>{if(!(e instanceof DOMException))setInspectError(e.message);});
  return()=>ctrl.abort();
 },[area,selected,preferences.day,preferences.start,preferences.end]);

 useEffect(()=>{
  if(points.length<2){setRoute(null);return;}
  const ctrl=new AbortController();setRouteBusy(true);setRouteError('');
  const t=setTimeout(()=>api<RouteResult>('/api/route',{method:'POST',headers:{'Content-Type':'application/json'},signal:ctrl.signal,body:JSON.stringify({points,horizontal_speed:preferences.horizontal,vertical_speed:preferences.vertical})}).then(setRoute).catch(e=>{if(!(e instanceof DOMException))setRouteError(e.message);}).finally(()=>{if(!ctrl.signal.aborted)setRouteBusy(false);}),300);
  return()=>{ctrl.abort();clearTimeout(t);};
 },[points,preferences.horizontal,preferences.vertical]);

 const forecastPoint=area?area.center:center;
 useEffect(()=>{
  const ctrl=new AbortController();setConditionsError('');
  const altitude=Math.round(Math.min(2500,Math.max(0,inspection?.elevation??1000)));
  api<Conditions>(`/api/conditions?lon=${forecastPoint[0].toFixed(4)}&lat=${forecastPoint[1].toFixed(4)}&day=${preferences.day}&altitude=${altitude}`,{signal:ctrl.signal}).then(setConditions).catch(e=>{if(!(e instanceof DOMException))setConditionsError(e.message);});
  return()=>ctrl.abort();
 },[forecastPoint[0],forecastPoint[1],preferences.day,inspection?.elevation]);

 useEffect(()=>{api<TourSet>('/api/tours').then(setTourSet).catch(e=>setTourError(e.message));},[]);
 const tours=useMemo(()=>{
  if(!tourSet)return [] as Tour[];
  const rows=tourSet.tours.filter(t=>t.ascent.max_slope<=tourSlope&&t.ascent.hours<=tourMaxH&&(tourMinRun===0||(t.descent&&t.descent.band_length_m>=tourMinRun)));
  return rows.sort((x,y)=>tourSort==='run'?(y.descent?.band_length_m??0)-(x.descent?.band_length_m??0):tourSort==='hours'?x.ascent.hours-y.ascent.hours:tourSort==='drive'?(x.drive_min??999)-(y.drive_min??999):y.elevation-x.elevation);
 },[tourSet,tourSlope,tourMaxH,tourMinRun,tourSort]);
 const activeTourObj=activeTour===null?null:tours[activeTour]??null;
 useEffect(()=>{setActiveTour(null);},[tourSlope,tourMaxH,tourMinRun,tourSort]);
 const pickTour=(i:number)=>{setActiveTour(i);const t=tours[i];if(t){setFlyTarget(t.summit);setSelected(t.summit);}};
 const useAscent=(t:Tour)=>{setPoints(t.ascent.line);setDrawing(false);setSection('route');setNotice(`Ascent of ${t.name??'unnamed summit'} loaded as route.`);};
 const runSearch=async()=>{
  if(!view)return;
  setSearching(true);setSearchError('');setActive(null);
  try{
   const body={west:view[0],south:view[1],east:view[2],north:view[3],lower:preferences.lower,upper:preferences.upper,min_length:minLength,day:preferences.day,start:preferences.start,end:preferences.end,horizontal_speed:preferences.horizontal,vertical_speed:preferences.vertical};
   let job=await api<SearchJob>('/api/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
   const id=job.job;
   while(job.status==='loading'){await new Promise(r=>setTimeout(r,1000));job=await api<SearchJob>(`/api/jobs/${id}`);}
   if(job.status==='error'||!job.result)throw new Error(job.message??'Search failed.');
   setResult(job.result);
  }catch(e){setSearchError(e instanceof Error?e.message:'Search failed.');}
  finally{setSearching(false);}
 };
 const shown=useMemo(()=>(result?.candidates??[]).filter(c=>terrainFilter==='all'||c.terrain===terrainFilter||(terrainFilter==='trees'&&c.terrain==='mixed')),[result,terrainFilter]);
 const pick=(c:Candidate)=>{setActive(c.id);setFlyTarget(c.center);setSelected(c.center);};
 const onPoint=useCallback((p:Point)=>{if(drawing)setPoints(ps=>ps.length>=5000?ps:[...ps,p]);else setSelected(p);},[drawing]);
 const importGPX=async(file:File)=>{try{const pts=parseGPX(await file.text());setPoints(pts);setDrawing(false);setFlyTarget(pts[0]);setNotice(`Imported ${pts.length} points.`);}catch(e){setRouteError(e instanceof Error?e.message:'Import failed');}};
 const importPlan=async(file:File)=>{try{const plan=parsePlan(await file.text());applyPlan(plan);setPlans(ps=>[plan,...ps.filter(p=>p.name!==plan.name)].slice(0,50));setNotice(`Imported plan “${plan.name}”.`);}catch(e){setNotice(e instanceof Error?e.message:'Import failed');}};
 const applyPlan=(plan:SavedPlan)=>{setPreferences(plan.preferences);setPoints(plan.points);setFlyTarget(plan.center);setDrawing(false);};
 const savePlan=()=>{const name=planName.trim()||`Plan ${new Date().toLocaleDateString('en-GB')}`;const plan:SavedPlan={version:1,name,preferences,points,center:area?.center??center};setPlans(ps=>[plan,...ps.filter(p=>p.name!==name)].slice(0,50));setPlanName('');setNotice(`Saved “${name}” on this device.`);};

 const warning=conditions?.avalanche?.[0]??null;
 const forecastState=useMemo(()=>{
  if(!conditions)return null;
  if(conditions.errors.avalanche)return {kind:'unavailable' as const,text:conditions.errors.avalanche};
  if(!warning)return {kind:'missing' as const,text:'No avalanche forecast was returned for this location and date.'};
  const from=warning.ValidFrom.slice(0,10),to=warning.ValidTo.slice(0,10);
  if(preferences.day<from||preferences.day>to)return {kind:'range' as const,text:`The returned forecast is valid ${from} – ${to}, not for ${preferences.day}. Forecasts are published one to two days ahead.`};
  if(preferences.day<osloDate())return {kind:'stale' as const,text:'This forecast is for a past date and no longer describes current conditions.'};
  if(warning.DangerLevel==='0')return {kind:'missing' as const,text:'No danger level is assessed for this date. Regional forecasting typically runs December – May.'};
  return {kind:'ok' as const,text:''};
 },[conditions,warning,preferences.day]);

 const weatherHours=useMemo(()=>{
  const ts=conditions?.weather?.properties.timeseries??[];
  return ts.filter(t=>osloDate(new Date(t.time))===preferences.day).map(t=>{const h=Number(new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/Oslo',hour:'2-digit',hourCycle:'h23'}).format(new Date(t.time)));return {hour:h,...t.data.instant.details,precip:t.data.next_1_hours?.details.precipitation_amount};}).filter(t=>t.hour>=preferences.start&&t.hour<preferences.end);
 },[conditions,preferences.day,preferences.start,preferences.end]);

 const directions=`https://www.google.com/maps/dir/?api=1&origin=Trondheim&destination=${forecastPoint[1].toFixed(5)},${forecastPoint[0].toFixed(5)}`;
 const toggle=(id:string)=>setSection(s=>s===id?'':id);

 return <div className={`app sheet-${sheet}`}>
  <MapView center={flyTarget} area={area} preferences={preferences} points={points} selected={selected} drawing={drawing} hazards={hazards} loading={loading} onPoint={onPoint} onCenter={setCenter} onView={setView} onLoadArea={loadArea} candidates={shown} activeCandidate={active} onCandidate={id=>{const c=shown.find(x=>x.id===id);if(c)pick(c);}} tours={showTours?tours:[]} activeTour={activeTour} onTour={i=>{pickTour(i);setSection('tours');}}/>
  <aside className="panel" aria-label="Planning panel">
   <button className="sheet-handle" aria-label="Resize panel" onClick={()=>setSheet(s=>s==='peek'?'half':s==='half'?'full':'peek')}><span/></button>
   <header className="panel-header">
    <div><h1>Rando</h1><p>Ski faces, mountain shadows and forecasts around Trondheim.</p></div>
    <div className="time-row">
     <label>Date <input type="date" value={preferences.day} onChange={e=>{if(e.target.value)update({day:e.target.value});}}/></label>
     <label>Window <span className="inline"><input type="number" min={0} max={23} value={preferences.start} onChange={e=>{const v=Number(e.target.value);if(v>=0&&v<preferences.end)update({start:v,hour:Math.min(Math.max(preferences.hour,v),preferences.end)});}}/>–<input type="number" min={1} max={24} value={preferences.end} onChange={e=>{const v=Number(e.target.value);if(v<=24&&v>preferences.start)update({end:v,hour:Math.min(preferences.hour,v)});}}/></span></label>
    </div>
    <label className="slider"><span>Map time <strong>{clock(preferences.hour)}</strong> Europe/Oslo</span><input type="range" min={0} max={24-1/6} step={1/6} value={preferences.hour} onChange={e=>update({hour:Number(e.target.value)})}/></label>
   </header>
   {notice&&<div className="notice" role="status">{notice}</div>}
   {areaError&&<div className="error" role="alert"><AlertTriangle size={14}/>{areaError}</div>}

   <Section id="tours" title="Toppturer" open={section==="tours"} onToggle={toggle}>
    {tourError?<p className="hint">{tourError}</p>:!tourSet?<p className="hint">Loading tours…</p>:<>
     <p className="warning">This is an automatically generated list. I have not checked them all. Do not attempt these if you’re a beginner.</p>
     <p className="hint">{tourSet.tours.length} summits within {tourSet.max_drive} min of the scan origin ({tourSet.summits} scanned, {tourSet.generated}). Blue = gentlest ascent line under 35°, orange = best 20–30° descent. Click a summit on the map or a card.</p>
     <div className="grid2">
      <label>Ascent max slope<select value={tourSlope} onChange={e=>setTourSlope(Number(e.target.value))}>{[35,30,28,25].map(v=><option key={v} value={v}>≤ {v}°</option>)}</select></label>
      <label>Ascent ≤ h<input type="number" min={0.5} max={12} step={0.5} value={tourMaxH} onChange={e=>{const v=Number(e.target.value);if(v>0)setTourMaxH(v);}}/></label>
      <label>Descent ≥ m<input type="number" min={0} max={3000} step={50} value={tourMinRun} onChange={e=>{const v=Number(e.target.value);if(v>=0)setTourMinRun(v);}}/></label>
      <label>Sort<select value={tourSort} onChange={e=>setTourSort(e.target.value as typeof tourSort)}><option value="run">Descent length</option><option value="hours">Ascent time</option><option value="drive">Drive</option><option value="elev">Elevation</option></select></label>
     </div>
     <label className="check"><input type="checkbox" checked={showTours} onChange={e=>setShowTours(e.target.checked)}/>Show tour lines on the map ({tours.length})</label>
     {activeTourObj&&<div className="tour-detail">
      <strong><Mountain size={14}/> {activeTourObj.name??'Unnamed summit'} {Math.round(activeTourObj.elevation)} m</strong>
      <span>Up {duration(activeTourObj.ascent.hours)} · +{activeTourObj.ascent.gain_m} m over {(activeTourObj.ascent.length_m/1000).toFixed(1)} km · max <b className={activeTourObj.ascent.max_slope>=30?'warn':'ok'}>{activeTourObj.ascent.max_slope.toFixed(0)}°</b>{activeTourObj.ascent.share_over_30>0&&<b className="warn"> · {activeTourObj.ascent.share_over_30}% on 30–35°</b>}</span>
      {activeTourObj.descent?<span>Down {activeTourObj.descent.band_length_m} m of 20–30° · {compass(activeTourObj.descent.aspect)} · {Math.round(activeTourObj.descent.drop)} m drop · max {activeTourObj.descent.max_slope.toFixed(0)}° · {activeTourObj.descent.forest_share?`${activeTourObj.descent.forest_type==='deciduous'?'birch':activeTourObj.descent.forest_type==='conifer'?'spruce':'mixed'} ${activeTourObj.descent.forest_share}%`:'open'} · ends {activeTourObj.descent.end_to_car_km} km from car</span>:<span>No 300 m run of 20–30° near the top.</span>}
      <span>Drive {activeTourObj.drive_min} min · start {activeTourObj.ascent.start[1].toFixed(4)}, {activeTourObj.ascent.start[0].toFixed(4)}</span>
      <div className="toolbar"><button className="on" onClick={()=>useAscent(activeTourObj)}><Pencil size={14}/>Use ascent as route</button><button onClick={()=>loadArea(activeTourObj.summit)}><Sun size={14}/>Explore area at summit</button></div>
     </div>}
     <ol className="cands">{tours.slice(0,60).map((t,i)=><li key={t.summit.join(',')}><button className={`cand${i===activeTour?' on':''}`} onClick={()=>pickTour(i)}>
      <span className={`rank ${t.descent?.forest_type==='deciduous'?'trees':t.descent?.forest_type==='conifer'?'spruce':t.descent?'open':'unknown'}`}>{i+1}</span>
      <strong>{t.name??'Unnamed'} {Math.round(t.elevation)} m · {t.drive_min} min drive</strong>
      <span>Up {duration(t.ascent.hours)}, +{t.ascent.gain_m} m, max {t.ascent.max_slope.toFixed(0)}°{t.ascent.share_over_30>0&&<em className="warn"> ({t.ascent.share_over_30}% on 30–35°)</em>}</span>
      <span>{t.descent?`Down ${t.descent.band_length_m} m ${compass(t.descent.aspect)} · ${Math.round(t.descent.drop)} m · ${t.descent.forest_share?`${t.descent.forest_type==='deciduous'?'birch':t.descent.forest_type==='conifer'?'spruce':'mixed'} ${t.descent.forest_share}%`:'open'}`:'No 20–30° run near the top'}</span>
     </button></li>)}</ol>
     {tours.length>60&&<p className="hint">Showing 60 of {tours.length}; tighten the filters to see the rest.</p>}
     <p className="caution"><Info size={13}/><span>Ascent lines are what the terrain permits under 35°, not checked routes: cornices, narrow cliff bands, rivers and closed roads are invisible to them. Drive times are summer roads.</span></p>
    </>}
   </Section>

   <Section id="find" title="Find candidates" open={section==="find"} onToggle={toggle}>
    <div className="chips">{REGIONS.map(r=><button key={r.name} className="chip" onClick={()=>setFlyTarget([...r.center] as Point)}>{r.name}</button>)}</div>
    <div className="grid2">
     <label>Continuous run ≥ m<input type="number" min={100} max={5000} step={50} value={minLength} onChange={e=>{const v=Number(e.target.value);if(v>=100&&v<=5000)setMinLength(v);}}/></label>
     <label>Slope band<span className="inline"><input type="number" min={0} max={59} value={preferences.lower} onChange={e=>{const v=Number(e.target.value);if(v>=0&&v<preferences.upper)update({lower:v});}}/>–<input type="number" min={1} max={60} value={preferences.upper} onChange={e=>{const v=Number(e.target.value);if(v<=60&&v>preferences.lower)update({upper:v});}}/></span></label>
    </div>
    <div className="toolbar"><button className="on" disabled={searching||!view} onClick={runSearch}>{searching?<LoaderCircle className="spin" size={14}/>:<Search size={14}/>}{searching?'Scanning terrain…':'Search this map view'}</button>
     <div className="segmented small" role="radiogroup" aria-label="Terrain type">{(['all','open','trees'] as const).map(t=><button key={t} role="radio" aria-checked={terrainFilter===t} className={terrainFilter===t?'on':''} onClick={()=>setTerrainFilter(t)}>{t==='all'?'All':t==='open'?'Open':'Trees'}</button>)}</div></div>
    <p className="hint">Scans up to 30 × 30 km of 10 m terrain for fall-line runs with at least {minLength} m of continuous {preferences.lower}–{preferences.upper}° skiing, then ranks by approach from the nearest road. First scan of a region takes up to a minute.</p>
    {searchError&&<p className="error">{searchError}</p>}
    {result&&<>
     {result.tiles_missing>0&&<p className="caution"><AlertTriangle size={13}/><span>{result.tiles_missing} terrain tiles could not be loaded; parts of this extent are unsearched.</span></p>}
     {result.roads===null&&<p className="caution"><AlertTriangle size={13}/><span>Road data (OpenStreetMap) unavailable — approach distances unknown.</span></p>}
     {!result.forest&&<p className="caution"><AlertTriangle size={13}/><span>Forest data (NIBIO AR5) unavailable — open/tree classification unknown.</span></p>}
     {shown.length===0?<p className="hint">No runs matched{result.count>0?' this terrain filter':''}. Try a shorter continuous length, a wider band, or another area.</p>:<ol className="cands">{shown.map((c,i)=><li key={c.id}><button className={`cand${c.id===active?' on':''}`} onClick={()=>pick(c)}>
      <span className={`rank ${c.terrain??'unknown'}`}>{i+1}</span>
      <strong>{c.band_length_m} m of {preferences.lower}–{preferences.upper}° · {compass(c.aspect)} · {c.top_elevation===null?'?':Math.round(c.top_elevation)}→{c.bottom_elevation===null?'?':Math.round(c.bottom_elevation)} m</strong>
      <span>Run {c.length_m} m, {c.drop===null?'?':Math.round(c.drop)} m drop · mean {c.mean_slope?.toFixed(0)}°, max {c.max_raw_slope?.toFixed(0)}°{c.steep_share>0&&<em className="warn"> · {c.steep_share}% ≥30°</em>}</span>
      <span>{c.approach?.hours===null||c.approach===null?'Approach unknown':`Approach ≥ ${c.approach.distance_km} km, ${c.approach.gain_m===null?'?':Math.round(c.approach.gain_m)} m from road ≈ ${duration(c.approach.hours)}`} · {c.terrain==null?'terrain ?':c.terrain==='trees'?`${c.forest_type==='deciduous'?'birch/deciduous':c.forest_type==='conifer'?'spruce/conifer':'mixed'} trees (${c.forest_share}%)`:c.terrain==='mixed'?`part ${c.forest_type==='deciduous'?'birch':c.forest_type==='conifer'?'spruce':'mixed'} forest (${c.forest_share}%)`:'open'} · sun ≈ {c.sun_hours===null?'?':`${c.sun_hours} h`}</span>
     </button></li>)}</ol>}
     <details><summary>Method and limits</summary><p className="pre">{result.method}</p></details>
    </>}
    <p className="caution"><Info size={13}/><span>Candidates are geometry only. Approach is straight-line from an OSM road: winter plowing, parking and terrain in between are unknown. Check the NVE layers and the forecast before choosing.</span></p>
   </Section>

   <Section id="terrain" title="Terrain preference" open={section==="terrain"} onToggle={toggle}>
    <div className="chips">{REGIONS.map(r=><button key={r.name} className="chip" onClick={()=>setFlyTarget([...r.center] as Point)}>{r.name}</button>)}</div>
    <div className="grid2">
     <label>Min slope °<input type="number" min={0} max={59} value={preferences.lower} onChange={e=>{const v=Number(e.target.value);if(v>=0&&v<preferences.upper)update({lower:v});}}/></label>
     <label>Max slope °<input type="number" min={1} max={60} value={preferences.upper} onChange={e=>{const v=Number(e.target.value);if(v<=60&&v>preferences.lower)update({upper:v});}}/></label>
    </div>
    <p className="hint">Strict bounds: a cell matches only if {preferences.lower}° &lt; slope &lt; {preferences.upper}°. Terrain ≥30° stays marked dark regardless.</p>
    <div className="chips"><button className={`chip${preferences.bearing===180&&preferences.width===45?' on':''}`} onClick={()=>update({bearing:180,width:45})}>South ±45°</button><button className={`chip${preferences.bearing===0&&preferences.width===45?' on':''}`} onClick={()=>update({bearing:0,width:45})}>North ±45°</button><button className={`chip${preferences.width===180?' on':''}`} onClick={()=>update({width:180})}>Any aspect</button></div>
    <div className="grid2">
     <label>Aspect °<input type="number" min={0} max={360} value={preferences.bearing} onChange={e=>{const v=Number(e.target.value);if(v>=0&&v<=360)update({bearing:v});}}/></label>
     <label>± width °<input type="number" min={0} max={180} value={preferences.width} onChange={e=>{const v=Number(e.target.value);if(v>=0&&v<=180)update({width:v});}}/></label>
    </div>
    <div className="segmented" role="radiogroup" aria-label="Sunlight mode">{(['sun','shade','aspect'] as const).map(m=><button key={m} role="radio" aria-checked={preferences.mode===m} className={preferences.mode===m?'on':''} onClick={()=>update({mode:m})}>{m==='sun'?'Seek sun':m==='shade'?'Seek shade':'Aspect only'}</button>)}</div>
    <label className="check"><input type="checkbox" checked={hazards} onChange={e=>setHazards(e.target.checked)}/>Show NVE steepness and runout (Bratthet med utløp 2024)</label>
    {area?<dl className="facts">
     <div><dt>Terrain</dt><dd>{area.resolution} m grid · {area.coverage}% covered</dd></div>
     <div><dt>Shadows</dt><dd>{area.shadow_resolution} m grid, 5° horizon rays to {area.horizon_radius_km} km</dd></div>
     <div><dt>Horizon check</dt><dd>{area.horizon_extension_delta_degrees===null?'unknown':`20→40 km changed horizons by up to ${area.horizon_extension_delta_degrees.toFixed(1)}°`}</dd></div>
     <div><dt>Source</dt><dd>{area.source}</dd></div>
    </dl>:<p className="hint">Move the map and press “Explore this area” to load 4 × 4 km of terrain.</p>}
    <p className="caution"><Info size={13}/><span>Terrain matches describe shape and light only. They are not a snow-stability or safety assessment.</span></p>
   </Section>

   <Section id="inspect" title="Inspect a point" open={section==="inspect"} onToggle={toggle}>
    {!area?<p className="hint">Load an area, then tap the map.</p>:!selected?<p className="hint">Tap inside the loaded area to inspect elevation, slope, aspect and sun windows.</p>:inspectError?<p className="error">{inspectError}</p>:!inspection?<p className="hint">Reading…</p>:<>
     <dl className="facts">
      <div><dt>Elevation</dt><dd>{inspection.elevation===null?'Unknown':`${Math.round(inspection.elevation)} m`}</dd></div>
      <div><dt>Slope</dt><dd>{inspection.slope===null?'Unknown':`${inspection.slope.toFixed(1)}°`}</dd></div>
      <div><dt>Aspect</dt><dd>{inspection.aspect===null?'Unknown':`${compass(inspection.aspect)} (${Math.round(inspection.aspect)}°)`}</dd></div>
      <div><dt>Within {inspection.nearby.radius_m} m</dt><dd>{inspection.nearby.median===null?'Unknown':`${inspection.nearby.min}–${inspection.nearby.max}°, median ${inspection.nearby.median}°`}<br/>{inspection.nearby.steep_percent!==null&&<span className={inspection.nearby.steep_percent>0?'warn':''}>{inspection.nearby.steep_percent}% of cells ≥30°</span>} · {inspection.nearby.coverage}% covered</dd></div>
      <div><dt>Potential sun</dt><dd>{inspection.sun_hours===null?'Partly unknown':`${inspection.sun_hours} h between ${clock(preferences.start)} and ${clock(preferences.end)}`}{inspection.windows.length>0&&<><br/>{inspection.windows.map(w=>`${clock(w.start)}–${clock(w.end)}`).join(', ')}</>}</dd></div>
     </dl>
     <div className="timeline" aria-label="Sun timeline">{inspection.intervals.map((i,k)=><span key={k} title={`${clock(i.hour)} ${i.sun===null?'unknown':i.sun?'sun':'shade'}`} className={i.sun===null?'unknown':i.sun?'sun':'shade'}/>)}</div>
     <div className="timeline-labels"><span>{clock(preferences.start)}</span><span>{clock(preferences.end)}</span></div>
     {weatherHours.length>0&&<><p className="hint">Forecast cloud cover (MET Norway) — separate from terrain sunlight:</p><div className="timeline" aria-label="Cloud cover">{weatherHours.map(h=><span key={h.hour} className="cloud" style={{opacity:0.15+0.85*((h.cloud_area_fraction??0)/100)}} title={`${h.hour}:00 · ${Math.round(h.cloud_area_fraction??0)}% cloud · ${h.air_temperature}°C · ${h.wind_speed} m/s`}/>)}</div></>}
     {!inspection.shadow_complete&&<p className="caution"><AlertTriangle size={13}/><span>Some horizon rays cross missing terrain; sun windows are incomplete.</span></p>}
    </>}
   </Section>

   <Section id="route" title="Ascent route" open={section==="route"} onToggle={toggle}>
    <div className="toolbar">
     <button className={drawing?'on':''} onClick={()=>setDrawing(d=>!d)}><Pencil size={14}/>{drawing?'Drawing…':'Draw'}</button>
     <button disabled={!points.length} onClick={()=>setPoints(p=>p.slice(0,-1))}><Undo2 size={14}/>Undo</button>
     <button disabled={!points.length} onClick={()=>{setPoints([]);setDrawing(false);}}><Trash2 size={14}/>Clear</button>
     <button onClick={()=>gpxInput.current?.click()}><Upload size={14}/>GPX</button>
     <button disabled={points.length<2} onClick={()=>download(toGPX(points),'rando-ascent.gpx','application/gpx+xml')}><Download size={14}/>GPX</button>
     <input ref={gpxInput} type="file" accept=".gpx,application/gpx+xml" hidden onChange={e=>{const f=e.target.files?.[0];if(f)importGPX(f);e.target.value='';}}/>
    </div>
    <div className="grid2">
     <label>Flat pace km/h<input type="number" min={0.5} max={10} step={0.5} value={preferences.horizontal} onChange={e=>{const v=Number(e.target.value);if(v>=0.5&&v<=10)update({horizontal:v});}}/></label>
     <label>Climb m/h<input type="number" min={100} max={1500} step={50} value={preferences.vertical} onChange={e=>{const v=Number(e.target.value);if(v>=100&&v<=1500)update({vertical:v});}}/></label>
    </div>
    {routeError&&<p className="error">{routeError}</p>}
    {points.length<2?<p className="hint">Draw on the map or import a GPX ascent. {points.length===1&&'One more point needed.'}</p>:route?<>
     <dl className="facts">
      <div><dt>Distance</dt><dd>{route.distance_km} km</dd></div>
      <div><dt>Ascent / descent</dt><dd>{route.ascent_m===null?'Unknown':`+${Math.round(route.ascent_m)} m`} / {route.descent_m===null?'Unknown':`−${Math.round(route.descent_m)} m`}</dd></div>
      <div><dt>Moving time</dt><dd><strong>{duration(route.hours)}</strong>{route.in_target!==null&&<span className={route.in_target?'ok':'warn'}> · {route.in_target?'within 3–4 h':'outside 3–4 h'}</span>}</dd></div>
      <div><dt>Terrain slope</dt><dd>max {route.max_slope===null?'unknown':`${route.max_slope}°`}{route.steep_samples>0&&<span className="warn"> · {route.steep_samples} samples ≥30° ({(route.steep_samples*10/1000).toFixed(2)} km)</span>}</dd></div>
      <div><dt>Coverage</dt><dd>{route.coverage}%{!route.complete&&<span className="warn"> · incomplete terrain, estimate withheld</span>}</dd></div>
     </dl>
     <Profile profile={route.profile}/>
     <p className="hint">Moving time = distance ÷ {preferences.horizontal} km/h + ascent ÷ {preferences.vertical} m/h. Breaks, snow and transitions need extra allowance.</p>
    </>:<p className="hint">{routeBusy?'Analysing route…':'Waiting for analysis.'}</p>}
   </Section>

   <Section id="forecast" title="Avalanche & weather" open={section==="forecast"} onToggle={toggle}>
    {conditionsError&&<p className="error">{conditionsError}</p>}
    {!conditions?<p className="hint">Loading forecasts…</p>:<>
     {forecastState&&forecastState.kind!=='ok'&&<p className={`caution ${forecastState.kind}`}><AlertTriangle size={13}/><span>{forecastState.text}</span></p>}
     {warning&&<div className="forecast">
      <div className={`danger level-${warning.DangerLevel}`}><span className="level">{warning.DangerLevel}</span><div><strong>{warning.DangerLevelName}</strong><span>{warning.RegionName} · valid {warning.ValidFrom.slice(0,10)} – {warning.ValidTo.slice(0,10)}</span><span>Published {fmtTime(warning.PublishTime)}{warning.NextWarningTime&&` · next ${fmtTime(warning.NextWarningTime)}`}</span></div></div>
      {warning.EmergencyWarning&&warning.EmergencyWarning!=='Not given'&&<p className="error"><AlertTriangle size={14}/>{warning.EmergencyWarning}</p>}
      {warning.MainText&&<p className="lead">{warning.MainText}</p>}
      {(warning.DangerIncreaseTime||warning.DangerDecreaseTime)&&<p className="hint">{warning.DangerIncreaseTime&&`Danger increases from ${fmtTime(warning.DangerIncreaseTime)}. `}{warning.DangerDecreaseTime&&`Danger decreases from ${fmtTime(warning.DangerDecreaseTime)}.`}</p>}
      {warning.AvalancheProblems?.map((p,i)=><div className="problem" key={i}><strong>{p.AvalancheProblemTypeName}</strong><span>{p.AvalancheExtName} · {p.AvalCauseName}</span><span>Aspects {expositions(p.ValidExpositions)} · {heightText(p)}</span><span>{p.AvalTriggerSimpleName} · {p.AvalProbabilityName} · size {p.DestructiveSizeExtName} · {p.AvalPropagationName}</span>{p.TriggerSenitivityPropagationDestuctiveSizeText&&<em>{p.TriggerSenitivityPropagationDestuctiveSizeText}</em>}</div>)}
      {warning.AvalancheAdvices&&warning.AvalancheAdvices.length>0&&<><h4>Advice</h4><ul>{warning.AvalancheAdvices.map((a,i)=><li key={i}>{a.Text}</li>)}</ul></>}
      {[['Avalanche danger',warning.AvalancheDanger],['Snow surface',warning.SnowSurface],['Weak layers',warning.CurrentWeaklayers],['Latest avalanche activity',warning.LatestAvalancheActivity],['Latest observations',warning.LatestObservations],['Mountain weather',warning.MountainWeather?.Comment]].filter(([,t])=>t).map(([h,t])=><details key={h as string}><summary>{h}</summary><p className="pre">{t}</p></details>)}
      {warning.MountainWeather?.MeasurementTypes&&<details><summary>Mountain weather measurements</summary><ul>{warning.MountainWeather.MeasurementTypes.map((m,i)=><li key={i}>{m.Name}: {m.MeasurementSubTypes.map(s=>`${s.Name} ${s.Value}`).join(', ')}</li>)}</ul></details>}
      <p className="hint">Source: NVE avalanche forecast (RegId {warning.RegId}{warning.Author&&`, ${warning.Author}`}) via api01.nve.no, fetched {fmtTime(conditions.fetched_at)}. Full forecast at <a href="https://www.varsom.no/en/avalanches/forecast/" target="_blank" rel="noreferrer">varsom.no</a>.</p>
     </div>}
     <h4>Weather {preferences.day}</h4>
     {conditions.errors.weather?<p className="caution"><AlertTriangle size={13}/><span>{conditions.errors.weather}</span></p>:weatherHours.length===0?<p className="hint">No MET forecast covers this day and window (forecasts reach about nine days ahead).</p>:<table className="weather"><thead><tr><th>Time</th><th>Cloud</th><th>Temp</th><th>Wind</th><th>Precip</th></tr></thead><tbody>{weatherHours.map(h=><tr key={h.hour}><td>{String(h.hour).padStart(2,'0')}:00</td><td>{h.cloud_area_fraction===undefined?'–':`${Math.round(h.cloud_area_fraction)}%`}</td><td>{h.air_temperature===undefined?'–':`${h.air_temperature.toFixed(0)}°`}</td><td>{h.wind_speed===undefined?'–':`${h.wind_speed} m/s ${compass(h.wind_from_direction??null)}`}</td><td>{h.precip===undefined?'–':`${h.precip} mm`}</td></tr>)}</tbody></table>}
     {conditions.weather&&<p className="hint">MET Norway locationforecast, updated {fmtTime(conditions.weather.properties.meta.updated_at)}, at {Math.round(Math.min(2500,Math.max(0,inspection?.elevation??1000)))} m. Cloud cover is a forecast; terrain sunlight is geometry.</p>}
    </>}
    <p className="caution"><Info size={13}/><span>Read the terrain: <a href="https://www.varsom.no/avalanches/about-avalanches/avalanche-terrain/" target="_blank" rel="noreferrer">Varsom on avalanche terrain</a>. Shade, north aspects and sub-30° slopes are not safety guarantees.</span></p>
   </Section>

   <Section id="plans" title="Plans & travel" open={section==="plans"} onToggle={toggle}>
    <a className="link" href={directions} target="_blank" rel="noreferrer"><Navigation size={14}/>Driving directions from Trondheim</a>
    <div className="toolbar"><input type="text" placeholder="Plan name" value={planName} onChange={e=>setPlanName(e.target.value)} maxLength={60}/><button onClick={savePlan}><Save size={14}/>Save</button><button onClick={()=>planInput.current?.click()}><Upload size={14}/>Import</button><input ref={planInput} type="file" accept=".json,application/json" hidden onChange={e=>{const f=e.target.files?.[0];if(f)importPlan(f);e.target.value='';}}/></div>
    {plans.length===0?<p className="hint">Saved plans stay in this browser. Export a plan file to move it to another device.</p>:<ul className="plans">{plans.map(p=><li key={p.name}><button className="plan-name" onClick={()=>applyPlan(p)}>{p.name}<span>{p.preferences.day} · {p.points.length} pts</span></button><button aria-label={`Export ${p.name}`} onClick={()=>download(JSON.stringify(p),`${p.name.replace(/[^\w-]+/g,'_')}.rando.json`,'application/json')}><Download size={14}/></button><button aria-label={`Delete ${p.name}`} onClick={()=>setPlans(ps=>ps.filter(x=>x.name!==p.name))}><X size={14}/></button></li>)}</ul>}
    <p className="hint"><Sun size={12}/> Solar geometry: astral, refraction ignored. Map © Kartverket; hazards © NVE; weather © MET Norway.</p>
   </Section>
  </aside>
 </div>;
}

function Section({id,title,open,onToggle,children}:{id:string;title:string;open:boolean;onToggle:(id:string)=>void;children:React.ReactNode}){
 return <section className={`panel-section${open?' open':''}`}><button className="section-head" aria-expanded={open} onClick={()=>onToggle(id)}><span>{title}</span>{open?<ChevronUp size={16}/>:<ChevronDown size={16}/>}</button>{open&&<div className="section-body">{children}</div>}</section>;
}

function Profile({profile}:{profile:RouteResult['profile']}){
 const known=profile.filter(p=>p.elevation!==null);
 if(known.length<2)return <p className="hint">Elevation profile unavailable: terrain missing along the route.</p>;
 const W=320,H=90,maxD=profile[profile.length-1].distance||1;
 const els=known.map(p=>p.elevation as number),lo=Math.min(...els),hi=Math.max(...els),span=Math.max(hi-lo,50);
 const x=(d:number)=>(d/maxD)*W,y=(e:number)=>H-((e-lo)/span)*(H-10)-5;
 const path=profile.map((p,i)=>p.elevation===null?'':`${i===0||profile[i-1].elevation===null?'M':'L'}${x(p.distance).toFixed(1)},${y(p.elevation).toFixed(1)}`).join('');
 return <svg className="profile" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Elevation profile with steep sections">
  {profile.slice(1).map((p,i)=>p.slope!==null&&p.slope>=30?<rect key={i} x={x(profile[i].distance)} y={0} width={Math.max(1,x(p.distance)-x(profile[i].distance))} height={H} className="steep"/>:null)}
  <path d={path} fill="none" strokeWidth={2} className="line"/>
  <text x={2} y={12} className="tick">{Math.round(hi)} m</text><text x={2} y={24} className="tick">{Math.round(lo)} m</text><text x={W-2} y={H-2} textAnchor="end" className="tick">{(maxD/1000).toFixed(1)} km</text>
 </svg>;
}
