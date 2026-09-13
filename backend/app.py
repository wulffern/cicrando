from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from threading import Lock
import json
import logging
import os
import time
import uuid

import httpx
import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field, model_validator

from .search import MAX_SIDE, search
from .terrain import (Area, CACHE, TO_UTM, area_key, fetch_raster, derivatives,
                      finite, load_area, local_time, matches, route_metrics, solar)

app = FastAPI(title='Rando terrain planner', version='0.1.0')
logger = logging.getLogger('rando')
pool = ThreadPoolExecutor(max_workers=1)
search_pool = ThreadPoolExecutor(max_workers=1)
jobs = {}
job_lock = Lock()


class Location(BaseModel):
    lon: float = Field(ge=7,le=13)
    lat: float = Field(ge=62,le=64.5)


class RouteRequest(BaseModel):
    points: list[tuple[float,float]] = Field(min_length=2,max_length=5000)
    horizontal_speed: float = Field(default=4,ge=0.5,le=10)
    vertical_speed: float = Field(default=400,ge=100,le=1500)

    @model_validator(mode='after')
    def valid_route(self):
        for lon,lat in self.points:
            Location(lon=lon,lat=lat)
        xy = np.array([TO_UTM.transform(*p) for p in self.points])
        if np.hypot(*np.diff(xy,axis=0).T).sum()>200000:
            raise ValueError('Maximum route length is 200 km')
        keys = {area_key(*p) for p in self.points}
        if len(keys)>20:
            raise ValueError('Keep a route within 20 analysis tiles')
        return self


def get_area(key):
    try:
        x,y = map(int,key.split('_'))
        if x%4000 or y%4000 or not (-100000<x<500000 and 6800000<y<7300000):
            raise ValueError()
    except (ValueError,TypeError):
        raise HTTPException(422,'Invalid area identifier')
    # Only serve successfully prepared areas; never trigger expensive work with tile GETs.
    if not any(j.get('area_id') == key and j['status']=='ready' for j in jobs.values()):
        raise HTTPException(404,'Load this area first')
    return load_area(key)


@app.get('/api/health')
def health():
    return {'status':'ok','terrain':'Kartverket NHM DTM','timezone':'Europe/Oslo'}


@app.post('/api/areas')
def prepare(location: Location):
    key = area_key(location.lon,location.lat)
    with job_lock:
        for id,job in jobs.items():
            if job.get('area_id') == key and job['status'] != 'error':
                return {'job':id,**job}
        active = sum(j['status']=='loading' for j in jobs.values())
        if active >= 3:
            raise HTTPException(429,'Terrain queue is full. Try again after the current area loads.')
        id = uuid.uuid4().hex
        jobs[id] = {'status':'loading','area_id':key}
    def work():
        try:
            area = load_area(key)
            jobs[id] = {'status':'ready','area_id':key,'area':area.metadata()}
        except Exception:
            logger.exception('Terrain preparation failed for %s',key)
            jobs[id] = {'status':'error','area_id':key,'message':'Terrain could not be loaded from Kartverket. Check the connection and retry.'}
    pool.submit(work)
    return {'job':id,**jobs[id]}


class SearchRequest(BaseModel):
    west: float = Field(ge=7,le=13); east: float = Field(ge=7,le=13)
    south: float = Field(ge=62,le=64.5); north: float = Field(ge=62,le=64.5)
    lower: float = Field(default=20,ge=0,le=60); upper: float = Field(default=30,ge=1,le=90)
    min_length: float = Field(default=500,ge=100,le=5000)
    day: date; start: float = Field(default=9,ge=0,le=23); end: float = Field(default=15,gt=0,le=24)
    horizontal_speed: float = Field(default=4,ge=0.5,le=10); vertical_speed: float = Field(default=400,ge=100,le=1500)

    @model_validator(mode='after')
    def valid(self):
        if self.lower>=self.upper: raise ValueError('Minimum slope must be below maximum slope')
        if self.end<=self.start: raise ValueError('Outing end must be after start')
        if self.east<=self.west or self.north<=self.south: raise ValueError('Empty search extent')
        return self


@app.post('/api/search')
def start_search(body: SearchRequest):
    # Snap the extent outward to the 4 km tile grid in UTM 33.
    xs,ys = zip(*[TO_UTM.transform(lon,lat) for lon,lat in [(body.west,body.south),(body.east,body.south),(body.west,body.north),(body.east,body.north)]])
    west,south = int(min(xs)//4000)*4000, int(min(ys)//4000)*4000
    east,north = int(-(-max(xs)//4000))*4000, int(-(-max(ys)//4000))*4000
    if east-west>MAX_SIDE or north-south>MAX_SIDE:
        raise HTTPException(422,f'Zoom in: the search extent may be at most {MAX_SIDE//1000} km across.')
    with job_lock:
        if sum(j['status']=='loading' and j.get('kind')=='search' for j in jobs.values())>=2:
            raise HTTPException(429,'Two searches are already running. Wait for one to finish.')
        id = uuid.uuid4().hex
        jobs[id] = {'status':'loading','kind':'search','extent':[west,south,east,north]}
    def work():
        try:
            result = search(west,south,east,north,body.lower,body.upper,body.min_length,body.day.isoformat(),body.start,body.end,body.horizontal_speed,body.vertical_speed)
            jobs[id] = {'status':'ready','kind':'search','result':result}
        except Exception:
            logger.exception('Search failed for %s',(west,south,east,north))
            jobs[id] = {'status':'error','kind':'search','message':'Search failed: terrain could not be loaded for this extent.'}
    search_pool.submit(work)
    return {'job':id,**jobs[id]}


@app.get('/api/jobs/{id}')
def job_status(id: str):
    if id not in jobs:
        raise HTTPException(404,'Unknown terrain job')
    return jobs[id]


@app.get('/api/areas/{key}/overlay.png')
def overlay(key: str, day: date, hour: float=Query(12,ge=0,le=23.99),
            lower: float=Query(20,ge=0,le=60), upper: float=Query(30,ge=1,le=90),
            bearing: float=Query(180,ge=0,le=360),width: float=Query(45,ge=0,le=180),
            mode: str=Query('sun',pattern='^(sun|shade|aspect)$')):
    if lower>=upper:
        raise HTTPException(422,'Minimum slope must be below maximum slope')
    area = get_area(key)
    mask = matches(area.slope,area.aspect,lower,upper,bearing,width)
    rgba = np.zeros((400,400,4),dtype='uint8')
    if mode=='aspect':
        rgba[mask] = [42,157,143,185]
    else:
        sun = area.sun_grid(local_time(day.isoformat(),hour))
        # Green/violet keep clear of the NVE yellow-red steepness and blue runout palette.
        rgba[mask & (sun==1)] = [140,214,60,210 if mode=='sun' else 70]
        rgba[mask & (sun==0)] = [126,86,214,210 if mode=='shade' else 70]
        rgba[mask & (sun==-1)] = [130,130,130,150]
    # Steep cells remain visible, independently of preference filters.
    rgba[area.slope>=30] = [40,40,40,90]
    rgba[~np.isfinite(area.slope)] = [100,100,100,130]
    out = BytesIO()
    Image.fromarray(rgba).save(out,format='PNG')
    return Response(out.getvalue(),media_type='image/png',headers={'Cache-Control':'private, max-age=3600'})


@app.get('/api/areas/{key}/inspect')
def inspect(key: str, lon: float, lat: float, day: date,
            start: float=Query(9,ge=0,le=23),end: float=Query(15,gt=0,le=24)):
    if end<=start:
        raise HTTPException(422,'Outing end must be after start')
    area = get_area(key)
    x,y = TO_UTM.transform(lon,lat)
    c,r = int(np.floor((x-area.west)/10)),int(np.floor((area.south+4000-y)/10))
    if not 0<=c<400 or not 0<=r<400:
        raise HTTPException(422,'Select a point inside the loaded area')
    # Inspection statistics cover a clearly labelled 100 m radius, not a claimed face polygon.
    rr,cc=np.ogrid[:400,:400]
    nearby=area.slope[(rr-r)**2+(cc-c)**2<=10**2]
    known=nearby[np.isfinite(nearby)]
    intervals=[]
    for minute in range(round(start*60),round(end*60),10):
        at=local_time(day.isoformat(),minute/60)
        az,alt=solar(lat,lon,at)
        b=((az-area.convergence)%360)/5
        h=max(area.horizons[int(b)%72,r//4,c//4],area.horizons[(int(b)+1)%72,r//4,c//4])
        slope,aspect=area.slope[r,c],area.aspect[r,c]
        incidence=np.sin(np.radians(alt))*np.cos(np.radians(slope))+np.cos(np.radians(alt))*np.sin(np.radians(slope))*np.cos(np.radians(az-aspect))
        if slope<0.001:
            incidence=np.sin(np.radians(alt))
        state=None if not np.isfinite(h) or not np.isfinite(slope) else bool(alt>0 and alt>h and incidence>0)
        intervals.append({'time':at.isoformat(),'hour':minute/60,'sun':state,'minutes':min(10,round(end*60)-minute)})
    windows=[]
    for slot in intervals:
        if slot['sun'] is True:
            if windows and abs(windows[-1]['end']-slot['hour'])<0.001:
                windows[-1]['end']=slot['hour']+slot['minutes']/60
            else:
                windows.append({'start':slot['hour'],'end':slot['hour']+slot['minutes']/60})
    complete=all(i['sun'] is not None for i in intervals)
    return dict(lon=lon,lat=lat,elevation=finite(area.dem.sample(x,y)),slope=finite(area.slope[r,c]),aspect=finite(area.aspect[r,c]),
                nearby=dict(radius_m=100,min=finite(known.min()) if len(known) else None,
                            max=finite(known.max()) if len(known) else None,
                            median=finite(np.median(known)) if len(known) else None,
                            steep_percent=round(float(np.mean(known>=30))*100,1) if len(known) else None,
                            coverage=round(len(known)/len(nearby)*100,1)),
                sun_hours=round(sum(i['minutes'] for i in intervals if i['sun'])/60,2) if complete else None,
                windows=windows,intervals=intervals,shadow_complete=complete)


@lru_cache(maxsize=24)
def route_tile(key):
    west,south=map(int,key.split('_'))
    dem=fetch_raster(west-100,south-100,4200,10)
    slopes,_=derivatives(dem.z,10)
    from .terrain import Raster
    return dem,Raster(slopes,dem.west,dem.north,10)


@app.post('/api/route')
def analyze_route(body: RouteRequest):
    def sample(xs,ys):
        keys=np.array([f'{int(x//4000)*4000}_{int(y//4000)*4000}' for x,y in zip(xs,ys)])
        if len(np.unique(keys))>20:
            raise ValueError('Keep a route within 20 analysis tiles')
        heights,slopes=np.full(xs.shape,np.nan),np.full(xs.shape,np.nan)
        for key in np.unique(keys):
            mask=keys==key
            try:
                dem,sl=route_tile(key)
                heights[mask],slopes[mask]=dem.sample(xs[mask],ys[mask]),sl.sample(xs[mask],ys[mask])
            except (httpx.HTTPError,ValueError,rasterio.errors.RasterioError):
                logger.warning('Missing route terrain %s',key)
        return heights,slopes
    import rasterio
    try:
        return route_metrics(body.points,body.horizontal_speed,body.vertical_speed,sample)
    except ValueError as exc:
        raise HTTPException(422,str(exc))


forecast_cache={}
forecast_lock=Lock()


def cached_json(url,params=None,ttl=900,met=False):
    key=url+json.dumps(params,sort_keys=True)
    with forecast_lock:
        old=forecast_cache.get(key)
    if old and old['expires']>time.time():
        return old['value']
    headers={'User-Agent':os.getenv('RANDO_USER_AGENT','cicrando/0.1 local terrain planner (https://github.com/wulffern/cicrando)')}
    if old and old.get('modified'):
        headers['If-Modified-Since']=old['modified']
    response=httpx.get(url,params=params,headers=headers,timeout=20,follow_redirects=True)
    if response.status_code==304 and old:
        value=old['value']
    else:
        response.raise_for_status()
        value=response.json()
    # Honour longer provider cache lifetimes; never poll faster than 15 minutes.
    expires=time.time()+ttl
    if response.headers.get('Expires'):
        from email.utils import parsedate_to_datetime
        try:
            expires=max(expires,parsedate_to_datetime(response.headers['Expires']).timestamp())
        except (ValueError,TypeError):
            pass
    with forecast_lock:
        if len(forecast_cache)>256:
            forecast_cache.clear()
        forecast_cache[key]={'value':value,'expires':expires,'modified':response.headers.get('Last-Modified')}
    return value


@app.get('/api/conditions')
def conditions(lon: float=Query(ge=7,le=13),lat: float=Query(ge=62,le=64.5),day: date=Query(),altitude: int=Query(1000,ge=-100,le=2500)):
    result={'fetched_at':datetime.now(timezone.utc).isoformat(),'avalanche':None,'weather':None,'errors':{}}
    base=os.getenv('RANDO_NVE_API','https://api01.nve.no/hydrology/forecast/avalanche/v6.3.2/api')
    try:
        result['avalanche']=cached_json(f'{base}/AvalancheWarningByCoordinates/Detail/{lat:.4f}/{lon:.4f}/2/{day}/{day}')
    except (httpx.HTTPError,ValueError):
        result['errors']['avalanche']='Avalanche forecast unavailable. Check Varsom directly.'
    try:
        result['weather']=cached_json('https://api.met.no/weatherapi/locationforecast/2.0/compact',
                                      dict(lat=f'{lat:.4f}',lon=f'{lon:.4f}',altitude=altitude),met=True)
    except (httpx.HTTPError,ValueError):
        result['errors']['weather']='Weather forecast unavailable. Check Yr directly.'
    return result


@app.get('/api/tours')
def tours():
    """Latest summit-tour scan from data/ (produced by scripts/toppturs_scan.py); 404 when none."""
    files = sorted(Path('data').glob('*toppturer*.json'))
    if not files:
        raise HTTPException(404, 'No summit-tour scan found. Run scripts/toppturs_scan.py first.')
    body = json.loads(files[-1].read_text())
    body['file'] = files[-1].name
    return body


if Path('dist').exists():
    app.mount('/',StaticFiles(directory='dist',html=True),name='frontend')
