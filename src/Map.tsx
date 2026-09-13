import {useEffect,useRef,useState} from 'react';
import maplibregl from 'maplibre-gl';
import {Crosshair,Minus,Plus,LoaderCircle,Mountain} from 'lucide-react';
import {Area,Bounds,Candidate,Point,Preferences,Tour} from './lib';

type Props={center:Point;area:Area|null;preferences:Preferences;points:Point[];selected:Point|null;drawing:boolean;hazards:boolean;loading:boolean;onPoint:(p:Point)=>void;onCenter:(p:Point)=>void;onView:(b:Bounds)=>void;onLoadArea:(p:Point)=>void;candidates:Candidate[];activeCandidate:string|null;onCandidate:(id:string)=>void;tours:Tour[];activeTour:number|null;onTour:(i:number)=>void};
const RUNOUT='https://gis3.nve.no/arcgis/rest/services/wmts/Bratthet_med_utlop_2024/MapServer';
export default function MapView(props:Props){
 const container=useRef<HTMLDivElement>(null),map=useRef<maplibregl.Map|null>(null),latest=useRef(props);
 latest.current=props;
 const [ready,setReady]=useState(false),[error,setError]=useState('');
 const marker=useRef<maplibregl.Marker|null>(null);
 useEffect(()=>{
  if(!container.current)return;
  let m:maplibregl.Map;
  try{m=new maplibregl.Map({container:container.current,center:latest.current.center,zoom:12.3,minZoom:7,maxZoom:17,maxBounds:[[7,62],[13,64.5]],style:{version:8,sources:{topo:{type:'raster',tiles:['https://cache.kartverket.no/v1/wmts/1.0.0/topo/default/webmercator/{z}/{y}/{x}.png'],tileSize:256,attribution:'© <a href="https://kartverket.no">Kartverket</a>'}},layers:[{id:'topo',type:'raster',source:'topo','paint':{'raster-saturation':-0.55}}]},attributionControl:{compact:true}});}catch{setError('This browser could not start the map. Enable WebGL or try another browser.');return;}
  map.current=m;
  const observer=new ResizeObserver(()=>m.resize());observer.observe(container.current);
  m.on('load',()=>{
   m.addSource('hazards',{type:'raster',tiles:[`${RUNOUT}/tile/{z}/{y}/{x}`],tileSize:256,minzoom:5,maxzoom:16,attribution:'© <a href="https://varsom.no">NVE / Varsom</a>'});
   m.addLayer({id:'hazards',type:'raster',source:'hazards',paint:{'raster-opacity':0.4},layout:{visibility:latest.current.hazards?'visible':'none'}});
   m.addSource('route',{type:'geojson',data:{type:'FeatureCollection',features:[]}});
   m.addLayer({id:'route-outline',type:'line',source:'route',paint:{'line-color':'#fff','line-width':7}});
   m.addLayer({id:'route-line',type:'line',source:'route',paint:{'line-color':'#173d35','line-width':3}});
   m.addSource('candidates',{type:'geojson',data:{type:'FeatureCollection',features:[]}});
   m.addLayer({id:'candidates-halo',type:'line',source:'candidates',paint:{'line-color':'#fff','line-width':['case',['get','active'],9,6],'line-opacity':0.9}});
   m.addLayer({id:'candidates',type:'line',source:'candidates',paint:{'line-color':['match',['get','terrain'],'trees','#2f7d32','mixed','#8a9a2b','#d9480f'],'line-width':['case',['get','active'],5,3]}});
   m.addLayer({id:'candidate-tops',type:'circle',source:'candidates',filter:['==',['geometry-type'],'Point'],paint:{'circle-radius':['case',['get','active'],7,5],'circle-color':['match',['get','terrain'],'trees','#2f7d32','mixed','#8a9a2b','#d9480f'],'circle-stroke-color':'#fff','circle-stroke-width':2}});
   m.on('click','candidates-halo',e=>{const id=e.features?.[0]?.properties?.id;if(id){latest.current.onCandidate(String(id));e.preventDefault();}});
   m.on('mouseenter','candidates-halo',()=>{m.getCanvas().style.cursor='pointer';});m.on('mouseleave','candidates-halo',()=>{m.getCanvas().style.cursor=latest.current.drawing?'crosshair':'';});
   m.addSource('tours',{type:'geojson',data:{type:'FeatureCollection',features:[]}});
   m.addLayer({id:'tours-halo',type:'line',source:'tours',filter:['==',['geometry-type'],'LineString'],paint:{'line-color':'#fff','line-width':['case',['get','active'],8,4],'line-opacity':['case',['get','active'],0.95,0.6]}});
   m.addLayer({id:'tours',type:'line',source:'tours',filter:['==',['geometry-type'],'LineString'],paint:{'line-color':['match',['get','leg'],'up','#2b6cb0','#d9480f'],'line-width':['case',['get','active'],4,2],'line-opacity':['case',['get','active'],1,0.55],'line-dasharray':['case',['==',['get','leg'],'up'],['literal',[1,0]],['literal',[2,1.2]]]}});
   m.addLayer({id:'tour-summits',type:'circle',source:'tours',filter:['==',['geometry-type'],'Point'],paint:{'circle-radius':['case',['get','active'],7,4.5],'circle-color':'#173d35','circle-stroke-color':'#fff','circle-stroke-width':2}});
   m.on('click','tour-summits',e=>{const i=e.features?.[0]?.properties?.i;if(i!==undefined){latest.current.onTour(Number(i));e.preventDefault();}});
   m.on('click','tours-halo',e=>{const i=e.features?.[0]?.properties?.i;if(i!==undefined){latest.current.onTour(Number(i));e.preventDefault();}});
   m.on('mouseenter','tour-summits',()=>{m.getCanvas().style.cursor='pointer';});m.on('mouseleave','tour-summits',()=>{m.getCanvas().style.cursor=latest.current.drawing?'crosshair':'';});
   m.addSource('waypoints',{type:'geojson',data:{type:'FeatureCollection',features:[]}});
   m.addLayer({id:'waypoints',type:'circle',source:'waypoints',paint:{'circle-radius':4,'circle-color':'#fff','circle-stroke-color':'#173d35','circle-stroke-width':2}});
   setReady(true);
  });
  m.on('click',e=>{if(!e.defaultPrevented)latest.current.onPoint([e.lngLat.lng,e.lngLat.lat]);});
  m.on('moveend',()=>{const c=m.getCenter();latest.current.onCenter([c.lng,c.lat]);const b=m.getBounds();latest.current.onView([b.getWest(),b.getSouth(),b.getEast(),b.getNorth()]);});
  m.on('error',e=>{const sourceId=(e as {sourceId?:string}).sourceId;if(sourceId==='hazards')setError('NVE overlay unavailable. Runout coverage is unknown; check Varsom.');else if(sourceId==='topo')setError('Background map could not load. Check your internet connection.');else if(sourceId==='analysis')setError('Terrain overlay could not load. Retry loading this area.');});
  return()=>{observer.disconnect();marker.current?.remove();marker.current=null;m.remove();map.current=null;setReady(false);};
 },[]);
 useEffect(()=>{map.current?.flyTo({center:props.center,zoom:12.3,duration:900});},[props.center]);
 useEffect(()=>{if(ready)map.current?.setLayoutProperty('hazards','visibility',props.hazards?'visible':'none');},[ready,props.hazards]);
 useEffect(()=>{if(map.current)map.current.getCanvas().style.cursor=props.drawing?'crosshair':'';},[props.drawing,ready]);
 useEffect(()=>{
  const m=map.current;if(!ready||!m)return;
  (m.getSource('route') as maplibregl.GeoJSONSource).setData({type:'Feature',properties:{},geometry:{type:'LineString',coordinates:props.points.length>=2?props.points:[]}});
  (m.getSource('waypoints') as maplibregl.GeoJSONSource).setData({type:'FeatureCollection',features:props.points.map((p,i)=>({type:'Feature',properties:{i},geometry:{type:'Point',coordinates:p}}))});
 },[props.points,ready]);
 useEffect(()=>{
  const m=map.current;if(!ready||!m)return;
  (m.getSource('candidates') as maplibregl.GeoJSONSource).setData({type:'FeatureCollection',features:props.candidates.flatMap((c,i)=>[
   {type:'Feature',properties:{id:c.id,terrain:c.terrain??'open',active:c.id===props.activeCandidate,rank:''},geometry:{type:'LineString',coordinates:c.line}},
   {type:'Feature',properties:{id:c.id,terrain:c.terrain??'open',active:c.id===props.activeCandidate,rank:String(i+1)},geometry:{type:'Point',coordinates:c.top}}])});
 },[props.candidates,props.activeCandidate,ready]);
 useEffect(()=>{
  const m=map.current;if(!ready||!m)return;
  (m.getSource('tours') as maplibregl.GeoJSONSource).setData({type:'FeatureCollection',features:props.tours.flatMap((t,i)=>{const active=i===props.activeTour;const f:GeoJSON.Feature[]=[
   {type:'Feature',properties:{i,active,leg:'up'},geometry:{type:'LineString',coordinates:t.ascent.line}},
   {type:'Feature',properties:{i,active},geometry:{type:'Point',coordinates:t.summit}}];
   if(t.descent)f.push({type:'Feature',properties:{i,active,leg:'down'},geometry:{type:'LineString',coordinates:t.descent.start_offset_m>60?[t.summit,...t.descent.line]:t.descent.line}});
   return f;})});
 },[props.tours,props.activeTour,ready]);
 useEffect(()=>{if(!map.current)return;marker.current?.remove();marker.current=null;if(props.selected)marker.current=new maplibregl.Marker({color:'#173d35'}).setLngLat(props.selected).addTo(map.current);},[props.selected,ready]);
 useEffect(()=>{
  const m=map.current;if(!ready||!m||!props.area)return;
  const area=props.area,p=props.preferences;
  if(area.coordinates.length!==4)return;
  const quad=area.coordinates as [Point,Point,Point,Point];
  const qs=new URLSearchParams({day:p.day,hour:String(p.hour),lower:String(p.lower),upper:String(p.upper),bearing:String(p.bearing),width:String(p.width),mode:p.mode});
  let cancelled=false;let url:string|undefined;
  const abort=new AbortController();
  const timer=setTimeout(async()=>{
   try{
    const response=await fetch(`/api/areas/${area.id}/overlay.png?${qs}`,{signal:abort.signal});if(!response.ok)throw new Error('overlay');
    url=URL.createObjectURL(await response.blob());if(cancelled){URL.revokeObjectURL(url);return;}
    const source=m.getSource('analysis') as maplibregl.ImageSource|undefined;
    if(source)source.updateImage({url,coordinates:quad});else{m.addSource('analysis',{type:'image',url,coordinates:quad});m.addLayer({id:'analysis',type:'raster',source:'analysis',paint:{'raster-opacity':0.8,'raster-resampling':'nearest','raster-fade-duration':0}},'route-outline');}
    const outline:{type:'Feature';properties:Record<string,never>;geometry:{type:'Polygon';coordinates:Point[][]}}={type:'Feature',properties:{},geometry:{type:'Polygon',coordinates:[[...area.coordinates,area.coordinates[0]]]}};
    if(m.getSource('boundary'))(m.getSource('boundary') as maplibregl.GeoJSONSource).setData(outline);else{m.addSource('boundary',{type:'geojson',data:outline});m.addLayer({id:'boundary',type:'line',source:'boundary',paint:{'line-color':'#173d35','line-width':1.5,'line-dasharray':[4,3]}});}
   }catch(e){if(!cancelled&&!(e instanceof DOMException&&e.name==='AbortError'))setError('Terrain overlay unavailable. Try loading the area again.');}
  },180);
  return()=>{cancelled=true;abort.abort();clearTimeout(timer);if(url)URL.revokeObjectURL(url);};
 },[ready,props.area,props.preferences.day,props.preferences.hour,props.preferences.lower,props.preferences.upper,props.preferences.bearing,props.preferences.width,props.preferences.mode]);
 return <div className="map-shell"><div ref={container} className="map-canvas" aria-label="Interactive terrain map"/>
  <div className="map-top"><span className="map-label"><span className="dot"/> TRONDHEIM & THE MOUNTAINS</span><button className="map-load" disabled={props.loading||!ready} onClick={()=>{setError('');const c=map.current!.getCenter();props.onLoadArea([c.lng,c.lat]);}}>{props.loading?<LoaderCircle className="spin" size={15}/>:<Crosshair size={15}/>} {props.loading?'Reading the terrain…':'Explore this area'}</button></div>
  <div className="map-tools"><button aria-label="Zoom in" onClick={()=>map.current?.zoomIn()}><Plus size={20}/></button><button aria-label="Zoom out" onClick={()=>map.current?.zoomOut()}><Minus size={20}/></button><button aria-label="Reset north" onClick={()=>map.current?.resetNorth()}><span className="north">N ↑</span></button></div>
  {!props.area&&!props.loading&&<div className="map-hint"><Mountain size={20}/><div><strong>A little closer to your next tour.</strong><span>Move the map, then explore a 4 × 4 km area.</span></div></div>}
  {props.loading&&<div className="map-hint"><LoaderCircle className="spin" size={20}/><div><strong>Looking beyond the next ridge</strong><span>Loading elevation and calculating mountain horizons. First load can take a minute.</span></div></div>}
  {props.drawing&&<div className="draw-hint">Tap to add ascent points · use Undo to remove the last point</div>}
  {error&&<div className="map-error" role="alert">{error}<button onClick={()=>setError('')} aria-label="Dismiss map message">×</button></div>}
  <div className="map-legend"><span><i className="sun-dot"/>Sunlit match</span><span><i className="shade-dot"/>Shaded match</span><span><i className="steep-dot"/>≥30° (10 m grid)</span><span><i className="unknown-dot"/>Unknown</span>{props.candidates.length>0&&<><span><i className="cand-open"/>Open run</span><span><i className="cand-trees"/>Tree run</span><span><i className="cand-mixed"/>Mixed</span></>}{props.preferences.mode==='aspect'&&<span><i className="aspect-dot"/>Aspect match</span>}{props.tours.length>0&&<><span><i className="tour-up"/>Tour up</span><span><i className="tour-down"/>Tour down</span></>}{props.hazards&&<><span><i className="nve-steep"/>NVE steepness classes from 27°</span><span><i className="nve-runout"/>NVE runout (short → long)</span></>}</div>
 </div>;
}
