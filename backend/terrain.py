"""Metric terrain analysis. Rasterio supplies GDAL-backed elevation IO.

No synthetic terrain fallback: absent elevations propagate as unknown. Beyond Kartverket's
coverage (it reaches ~55 km into Sweden, to about 13°E) cells are filled from the open
Copernicus GLO-30 DEM — a ~30 m *surface* model, so forest canopy is included — and flagged
as coarse so callers can disclose the lower resolution rather than present it as 10 m terrain.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from threading import RLock
import hashlib
import json
import os

import httpx
import numpy as np
import rasterio
import rasterio.errors
from astral import Observer
from astral.sun import azimuth, elevation
from pyproj import Transformer, Proj
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject
from rasterio.windows import from_bounds
from zoneinfo import ZoneInfo

CACHE = Path(os.getenv('RANDO_CACHE', '.cache/terrain'))
SOURCE = 'https://hoydedata.no/arcgis/rest/services/NHM_DTM_25833/ImageServer'
COPERNICUS = 'https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_{lat}_00_{lon}_00_DEM/Copernicus_DSM_COG_10_{lat}_00_{lon}_00_DEM.tif'
TO_UTM = Transformer.from_crs(4326, 25833, always_xy=True)
TO_LL = Transformer.from_crs(25833, 4326, always_xy=True)


def geo_bbox(west, south, east, north):
    """(lon0, lat0, lon1, lat1) enclosing a UTM rectangle.

    The UTM grid is rotated against lat/lon away from the central meridian, so the SW and NE
    corners alone cut a wedge (~1 km per 13 km here) off two sides of the rectangle.
    """
    lon, lat = TO_LL.transform([west, east, east, west], [south, south, north, north])
    return min(lon), min(lat), max(lon), max(lat)
OSLO = ZoneInfo('Europe/Oslo')
LOCK = RLock()


def local_time(day: str, hour: float) -> datetime:
    return datetime.fromisoformat(day).replace(tzinfo=OSLO) + timedelta(hours=hour)


def solar(lat: float, lon: float, at: datetime) -> tuple[float, float]:
    observer = Observer(lat, lon)
    return azimuth(observer, at), elevation(observer, at, with_refraction=False)


def derivatives(z: np.ndarray, resolution: float):
    # Raster rows increase southward. Aspect is downslope, clockwise from north.
    south, east = np.gradient(z, resolution)
    slope = np.degrees(np.arctan(np.hypot(east, south)))
    aspect = np.degrees(np.arctan2(-east, south)) % 360
    aspect = np.where(slope < 0.001, np.nan, aspect)
    return slope, aspect


def matches(slope, aspect, lower=20, upper=30, bearing=180, width=45):
    delta = np.abs((aspect - bearing + 180) % 360 - 180)
    return (slope > lower) & (slope < upper) & (delta <= width)


@dataclass
class Raster:
    z: np.ndarray
    west: float
    north: float
    resolution: float
    coarse: np.ndarray | None = None   # cells filled from the ~30 m Copernicus surface model

    def sample(self, x, y):
        x, y = np.broadcast_arrays(x, y)
        cols = np.floor((x - self.west) / self.resolution).astype(int)
        rows = np.floor((self.north - y) / self.resolution).astype(int)
        valid = (cols >= 0) & (rows >= 0) & (cols < self.z.shape[1]) & (rows < self.z.shape[0])
        return np.where(valid, self.z[np.clip(rows, 0, self.z.shape[0]-1), np.clip(cols, 0, self.z.shape[1]-1)], np.nan)


def fetch_raster(west: int, south: int, size: int, resolution: int) -> Raster:
    CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(f'{SOURCE}:{west}:{south}:{size}:{resolution}:v1'.encode()).hexdigest()[:24]
    path = CACHE / f'{key}.tif'
    with LOCK:
        if not path.exists():
            if os.getenv('RANDO_OFFLINE') == '1':
                raise ValueError('Elevation tile not cached and RANDO_OFFLINE=1')
            params = dict(bbox=f'{west},{south},{west+size},{south+size}', bboxSR=25833,
                          imageSR=25833, size=f'{size//resolution},{size//resolution}',
                          format='tiff', pixelType='F32', f='image',
                          renderingRule=json.dumps({'rasterFunction': 'None'}),
                          interpolation='RSP_BilinearInterpolation', noData=-9999)
            response = httpx.get(SOURCE + '/exportImage', params=params, timeout=90, follow_redirects=True)
            response.raise_for_status()
            with MemoryFile(response.content) as mem, mem.open() as src:
                if src.count != 1 or src.dtypes[0] != 'float32':
                    raise ValueError('Elevation service returned a rendered image instead of numerical terrain')
                if src.width != size//resolution or src.height != size//resolution:
                    raise ValueError('Elevation service changed the requested grid size')
                expected = (west, south, west+size, south+size)
                if src.crs.to_epsg() != 25833 or not np.allclose(tuple(src.bounds), expected, atol=0.1):
                    raise ValueError('Elevation service returned an unexpected coordinate system or extent')
            # Unique temp name per process: parallel workers may fetch the same tile at once.
            tmp = path.with_name(f'{path.stem}.{os.getpid()}.tmp')
            tmp.write_bytes(response.content)
            try:
                tmp.replace(path)
            except FileNotFoundError:
                if not path.exists():
                    raise
                tmp.unlink(missing_ok=True)
        with rasterio.open(path) as src:
            z = src.read(1, masked=True).astype('float32').filled(np.nan)
            z[(z < -500) | (z > 9000)] = np.nan
            raster = Raster(z, src.bounds.left, src.bounds.top, resolution)
    if np.isnan(z).any():   # Kartverket returns sea as 0, so NaN means outside its coverage
        fill = copernicus_raster(west, south, size, resolution)
        if fill is not None:
            coarse = np.isnan(z) & np.isfinite(fill)
            if coarse.any():
                raster.z = np.where(coarse, fill, z)
                raster.coarse = coarse
    return raster


def copernicus_raster(west: int, south: int, size: int, resolution: int):
    """The Copernicus GLO-30 surface model warped onto the UTM33 tile; None when unavailable."""
    CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(f'{COPERNICUS}:{west}:{south}:{size}:{resolution}:v2'.encode()).hexdigest()[:24]
    path = CACHE / f'{key}.tif'
    n = size // resolution
    dst_transform = from_origin(west, south + size, resolution, resolution)
    with LOCK:
        if not path.exists():
            if os.getenv('RANDO_OFFLINE') == '1':
                return None
            lon0, lat0, lon1, lat1 = geo_bbox(west, south, west + size, south + size)
            out = np.full((n, n), np.nan, dtype='float32')
            try:
                for lat in range(int(np.floor(lat0)), int(np.ceil(lat1))):
                    for lon in range(int(np.floor(lon0)), int(np.ceil(lon1))):
                        url = COPERNICUS.format(lat=f'N{lat:02d}' if lat >= 0 else f'S{-lat:02d}', lon=f'E{lon:03d}' if lon >= 0 else f'W{-lon:03d}')
                        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR'), rasterio.open(url) as src:
                            window = from_bounds(max(lon0, lon) - 0.01, max(lat0, lat) - 0.01, min(lon1, lon + 1) + 0.01, min(lat1, lat + 1) + 0.01, src.transform)
                            # The COGs declare no nodata; use an explicit sentinel for the boundless fill.
                            nodata = src.nodata if src.nodata is not None else -32767.0
                            part = src.read(1, window=window, boundless=True, fill_value=nodata)
                            piece = np.full((n, n), np.nan, dtype='float32')
                            reproject(part, piece, src_transform=src.window_transform(window), src_crs=src.crs, src_nodata=nodata,
                                      dst_transform=dst_transform, dst_crs='EPSG:25833', dst_nodata=np.nan, resampling=Resampling.bilinear)
                            piece[(piece < -500) | (piece > 9000)] = np.nan
                            out = np.where(np.isnan(out), piece, out)
            except (rasterio.errors.RasterioIOError, httpx.HTTPError) as exc:
                import logging
                logging.getLogger('rando.terrain').warning('Copernicus DEM unavailable for %s,%s: %s', west, south, exc)
                return None
            tmp = path.with_name(f'{path.stem}.{os.getpid()}.tmp')
            with rasterio.open(tmp, 'w', driver='GTiff', width=n, height=n, count=1, dtype='float32', crs='EPSG:25833', transform=dst_transform, nodata=np.nan) as dst:
                dst.write(out, 1)
            try:
                tmp.replace(path)
            except FileNotFoundError:
                tmp.unlink(missing_ok=True)
        with rasterio.open(path) as src:
            return src.read(1).astype('float32')


def horizon(raster: Raster, x, y, heights, bearing, distances):
    """Maximum terrain angle along a grid-north ray; missing samples invalidate it."""
    angle = np.full(np.shape(heights), -90.0)
    valid = np.isfinite(heights)
    rad = np.radians(bearing)
    for d in distances:
        z = raster.sample(x + np.sin(rad)*d, y + np.cos(rad)*d)
        valid = valid & np.isfinite(z)
        angle = np.maximum(angle, np.degrees(np.arctan2(z - heights, d)))
    return np.where(valid, angle, np.nan)


@dataclass
class Area:
    key: str
    west: int
    south: int
    dem: Raster
    slope: np.ndarray
    aspect: np.ndarray
    horizons: np.ndarray
    horizon_delta: float | None
    lon: float
    lat: float
    convergence: float

    def sun_grid(self, at):
        az, alt = solar(self.lat, self.lon, at)
        # Conservative upper envelope of neighbouring 5-degree horizon rays.
        b = ((az - self.convergence) % 360) / 5
        h = np.maximum(self.horizons[int(b) % 72], self.horizons[(int(b)+1) % 72])
        h = np.repeat(np.repeat(h, 4, axis=0), 4, axis=1)
        aspect = np.radians(self.aspect)
        s = np.radians(self.slope)
        incidence = np.sin(np.radians(alt))*np.cos(s) + np.cos(np.radians(alt))*np.sin(s)*np.cos(np.radians(az)-aspect)
        incidence = np.where(self.slope < 0.001, np.sin(np.radians(alt)), incidence)
        visible = (alt > 0) & (alt > h) & (incidence > 0)
        # -1 unknown, 0 shade/night, 1 potential direct sun
        return np.where(np.isfinite(h) & np.isfinite(self.slope), visible.astype('int8'), -1)

    def metadata(self):
        corners = [TO_LL.transform(x, y) for x, y in [(self.west,self.south+4000),
                   (self.west+4000,self.south+4000),(self.west+4000,self.south),(self.west,self.south)]]
        return dict(id=self.key, coordinates=corners, center=[self.lon,self.lat],
                    resolution=10, shadow_resolution=40, horizon_radius_km=40,
                    horizon_extension_delta_degrees=self.horizon_delta,
                    coverage=round(float(np.isfinite(self.slope).mean())*100, 1),
                    source='Kartverket / Høydedata · NHM DTM, sampled at 10 m',
                    source_url=SOURCE, width=400, height=400)


def area_key(lon, lat):
    x, y = TO_UTM.transform(lon, lat)
    return f'{int(x//4000)*4000}_{int(y//4000)*4000}'


@lru_cache(maxsize=6)
def load_area(key: str) -> Area:
    west, south = map(int, key.split('_'))
    lon, lat = TO_LL.transform(west+2000, south+2000)
    # A high-resolution border prevents derivative artefacts at tile edges.
    dem = fetch_raster(west-100, south-100, 4200, 10)
    slope, aspect = derivatives(dem.z, 10)
    convergence = Proj('EPSG:25833').get_factors(lon, lat).meridian_convergence
    aspect = (aspect + convergence) % 360
    slope, aspect = slope[10:-10,10:-10], aspect[10:-10,10:-10]
    coarse = fetch_raster(west-42000, south-42000, 88000, 100)
    xs, ys = np.meshgrid(west+np.arange(100)*40+20, south+4000-np.arange(100)*40-20)
    z = dem.sample(xs, ys)
    hpath = CACHE / f'horizon_{key}_v3.npz'
    with LOCK:
        if hpath.exists():
            with np.load(hpath) as saved:
                horizons, delta = saved['h'], float(saved['delta'])
        else:
            horizons, changes = [], []
            for bearing in range(0,360,5):
                far20 = horizon(coarse, xs, ys, z, bearing, range(100,20001,100))
                far40 = horizon(coarse, xs, ys, z, bearing, range(20200,40001,200))
                # Near-field rays use fine terrain where available, coarse outside the loaded tile.
                near = np.full(z.shape, -90.0)
                for d in range(10,100,10):
                    xx, yy = xs + np.sin(np.radians(bearing))*d, ys + np.cos(np.radians(bearing))*d
                    nz = dem.sample(xx,yy)
                    nz = np.where(np.isfinite(nz),nz,coarse.sample(xx,yy))
                    near = np.maximum(near,np.degrees(np.arctan2(nz-z,d)))
                baseline = np.maximum(near,far20)
                extended = np.maximum(baseline,far40)
                horizons.append(extended)
                changes.append(extended-baseline)
            horizons = np.asarray(horizons,dtype='float32')
            differences = np.asarray(changes)
            delta = float(np.nanmax(differences)) if np.isfinite(differences).any() else float('nan')
            np.savez_compressed(hpath, h=horizons, delta=delta)
    return Area(key,west,south,dem,slope,aspect,horizons,delta if np.isfinite(delta) else None,lon,lat,convergence)


def finite(value):
    return round(float(value),2) if np.isfinite(value) else None


def route_metrics(points, horizontal_speed, vertical_speed, sampler):
    """Densify to <=10 m before sampling; route gradient is not terrain slope."""
    xy = np.array([TO_UTM.transform(*point) for point in points])
    pieces = []
    for a,b in zip(xy[:-1],xy[1:]):
        n = max(1,int(np.ceil(np.linalg.norm(b-a)/10)))
        pieces.extend(a+(b-a)*t for t in np.arange(n)/n)
    pieces.append(xy[-1])
    xy = np.array(pieces)
    if len(xy)>20001:
        raise ValueError('Route exceeds the 200 km analysis limit')
    heights, slopes = sampler(xy[:,0],xy[:,1])
    distances = np.hypot(*np.diff(xy,axis=0).T)
    known = np.isfinite(heights)
    complete = bool(known.all() and np.isfinite(slopes).all())
    gain = float(np.maximum(np.diff(heights),0).sum()) if known.all() else None
    loss = float(np.maximum(-np.diff(heights),0).sum()) if known.all() else None
    km = float(distances.sum()/1000)
    hours = km/horizontal_speed+gain/vertical_speed if complete else None
    profile = [dict(distance=round(float(d),1),elevation=finite(h),slope=finite(s))
               for d,h,s in zip(np.r_[0,np.cumsum(distances)],heights,slopes)]
    return dict(distance_km=round(km,2),ascent_m=finite(gain) if gain is not None else None,
                descent_m=finite(loss) if loss is not None else None,hours=finite(hours) if hours is not None else None,
                in_target=3<=hours<=4 if hours is not None else None,
                max_slope=finite(np.nanmax(slopes)) if np.isfinite(slopes).any() else None,
                steep_samples=int(np.sum(slopes>=30)),coverage=round(float(known.mean())*100,1),
                complete=complete,profile=profile)
