export type Point = [number, number];
export type Preferences = { day: string; start: number; end: number; hour: number; lower: number; upper: number; bearing: number; width: number; mode: 'sun'|'shade'|'aspect'; horizontal: number; vertical: number };
export type Area = { id: string; coordinates: Point[]; center: Point; resolution: number; shadow_resolution: number; horizon_radius_km: number; horizon_extension_delta_degrees: number|null; coverage: number; source: string };
export type Inspection = {lon:number;lat:number;elevation:number|null;slope:number|null;aspect:number|null;nearby:{radius_m:number;min:number|null;max:number|null;median:number|null;steep_percent:number|null;coverage:number};sun_hours:number|null;windows:{start:number;end:number}[];intervals:{hour:number;sun:boolean|null}[];shadow_complete:boolean};
export type RouteResult = {distance_km:number;ascent_m:number|null;descent_m:number|null;hours:number|null;in_target:boolean|null;max_slope:number|null;steep_samples:number;coverage:number;complete:boolean;profile:{distance:number;elevation:number|null;slope:number|null}[]};
export type Candidate={id:string;top:Point;bottom:Point;center:Point;line:Point[];top_elevation:number|null;bottom_elevation:number|null;drop:number|null;band_drop:number|null;band_length_m:number;length_m:number;mean_slope:number|null;max_raw_slope:number|null;steep_share:number;aspect:number|null;top_area_m2:number;forest_share:number|null;forest_type:'conifer'|'deciduous'|'mixed'|null;terrain:'open'|'trees'|'mixed'|null;approach:{road:Point|null;distance_km:number|null;gain_m:number|null;hours:number|null;complete:boolean}|null;sun_hours:number|null};
export type SearchResult={count:number;candidates:Candidate[];tiles_missing:number;roads:number|null;forest:boolean;bounds:[Point,Point];method:string};
export type Tour={summit:Point;elevation:number;name:string|null;kind:string|null;dist:number|null;drive_min:number|null;ascent:{start:Point;line:Point[];length_m:number;gain_m:number;loss_m:number;max_slope:number;mean_slope:number;share_over_30:number;share_over_25:number;hours:number;forest_share:number|null};descent:{band_length_m:number;drop:number;top_elevation:number;bottom_elevation:number;mean_slope:number;max_slope:number;steep_share:number;band_share:number;aspect:number|null;forest_share:number|null;forest_type:'conifer'|'deciduous'|'mixed'|null;start_offset_m:number;start_below_summit_m:number;end:Point;end_to_car_km:number;line:Point[]}|null};
export type TourSet={origin:Point;max_drive:number;generated:string;blocks:number;summits:number;tours:Tour[];file:string};
export type Bounds=[number,number,number,number]; // west, south, east, north
export const REGIONS = [
  {name:'Oppdal · Storhornet', center:[9.55,62.64] as Point},
  {name:'Trollheimen · Gjevilvassdalen',center:[9.38,62.73] as Point},
  {name:'Meråker · Fonnfjellet',center:[11.64,63.39] as Point},
];
export function osloDate(date = new Date()): string {
  const parts = new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Oslo',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(date);
  return ['year','month','day'].map(k=>parts.find(p=>p.type===k)!.value).join('-');
}
export const defaults: Preferences = {day:osloDate(),start:9,end:15,hour:12,lower:20,upper:30,bearing:180,width:45,mode:'sun',horizontal:4,vertical:400};
export function clock(hour:number):string { const minutes=Math.round(hour*60); return `${String(Math.floor(minutes/60)).padStart(2,'0')}:${String(minutes%60).padStart(2,'0')}`; }
export function duration(hours:number|null) { return hours===null?'Unknown':`${Math.floor(hours)}h ${Math.round((hours%1)*60)}m`; }
export function compass(degrees:number|null) {return degrees===null?'Unknown':['N','NE','E','SE','S','SW','W','NW'][Math.round(degrees/45)%8];}
export async function api<T>(url:string, options?:RequestInit):Promise<T> {
  const res=await fetch(url,options);
  if(!res.ok){let message=`Request failed (${res.status})`; try {const body=await res.json(); message=typeof body.detail==='string'?body.detail:message;}catch{/* non-JSON gateway error */}throw new Error(message);}
  return res.json();
}
export function validPoints(value:unknown):value is Point[] {
  return Array.isArray(value)&&value.length<=5000&&value.every(p=>Array.isArray(p)&&p.length===2&&Number.isFinite(p[0])&&Number.isFinite(p[1])&&p[0]>=7&&p[0]<=13&&p[1]>=62&&p[1]<=64.5);
}
export function parseGPX(xml:string):Point[] {
  if(xml.length>5_000_000)throw new Error('Please use a GPX smaller than 5 MB.');
  const doc=new DOMParser().parseFromString(xml,'application/xml');
  if(doc.querySelector('parsererror'))throw new Error('This is not a valid GPX file.');
  const tracks=Array.from(doc.getElementsByTagNameNS('*','trk'));
  // Rando tour files carry an "Up" and a "Down" track: take the ascent. Otherwise require one track.
  const up=tracks.find(t=>/^Up\b/.test(t.getElementsByTagNameNS('*','name')[0]?.textContent??''));
  const scope=up??(tracks.length===1?tracks[0]:doc);
  if(!up&&tracks.length>1)throw new Error('This GPX has several tracks. Import a single continuous ascent track, or a Rando tour file with an "Up" track.');
  const segments=Array.from(scope.getElementsByTagNameNS('*','trkseg'));
  if(segments.length>1)throw new Error('Import a single continuous ascent track. This GPX contains multiple segments.');
  const routes=Array.from(doc.getElementsByTagNameNS('*','rte'));
  if(routes.length>1)throw new Error('Import one ascent route at a time.');
  let nodes=Array.from(scope.getElementsByTagNameNS('*','trkpt'));
  if(!nodes.length)nodes=Array.from(doc.getElementsByTagNameNS('*','rtept'));
  const points=nodes.map(n=>[n.hasAttribute('lon')?Number(n.getAttribute('lon')):NaN,n.hasAttribute('lat')?Number(n.getAttribute('lat')):NaN]);
  if(points.length<2||!validPoints(points))throw new Error('Use 2–5,000 track points within the Trondheim pilot (62–64.5°N, 7–13°E).');
  return points;
}
export function toGPX(points:Point[]):string {
  return `<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="Rando" xmlns="http://www.topografix.com/GPX/1/1"><trk><name>Rando ascent</name><trkseg>${points.map(([lon,lat])=>`<trkpt lat="${lat}" lon="${lon}"/>`).join('')}</trkseg></trk></gpx>`;
}
export function download(content:string,name:string,type:string) {
  const url=URL.createObjectURL(new Blob([content],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
export function validPreferences(v:unknown):v is Preferences {
  if(!v||typeof v!=='object')return false;
  const p=v as Preferences;
  return typeof p.day==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(p.day)&&!Number.isNaN(Date.parse(p.day))&&
    [p.start,p.end,p.hour,p.lower,p.upper,p.bearing,p.width,p.horizontal,p.vertical].every(Number.isFinite)&&
    p.start>=0&&p.start<p.end&&p.end<=24&&p.hour>=0&&p.hour<24&&p.lower>=0&&p.lower<p.upper&&p.upper<=60&&
    p.bearing>=0&&p.bearing<=360&&p.width>=0&&p.width<=180&&p.horizontal>=0.5&&p.horizontal<=10&&p.vertical>=100&&p.vertical<=1500&&['sun','shade','aspect'].includes(p.mode);
}
export type SavedPlan={version:1;name:string;preferences:Preferences;points:Point[];center:Point};
export function parsePlan(text:string):SavedPlan {
  const p=JSON.parse(text);
  if(p.version!==1||typeof p.name!=='string'||!validPreferences(p.preferences)||!validPoints(p.points)||!validPoints([p.center]))throw new Error('This plan is invalid or uses an unsupported version.');
  return p;
}
