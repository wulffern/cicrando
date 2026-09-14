"""Candidate ski-face search: continuous fall-line runs inside a slope band, plus road approach.

Faces are found on a mosaic of 10 m tiles so runs may cross tile edges. Roads come from
OpenStreetMap via Overpass (ODbL); approach is straight-line and a lower bound. Forest and tree
species come from NIBIO AR5 (Treslag) rendered by WMS and decoded from its legend colours.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
import os

import httpx
import numpy as np
from PIL import Image
from scipy import ndimage

from .terrain import CACHE, TO_LL, TO_UTM, derivatives, fetch_raster, finite, geo_bbox, local_time, solar

logger = logging.getLogger('rando.search')
OVERPASS = 'https://overpass-api.de/api/interpreter'
OVERPASS_MIRRORS = ('https://overpass.kumi.systems/api/interpreter', 'https://maps.mail.ru/osm/tools/overpass/api/interpreter')
FOREST_CHUNK = 14000   # metres; larger forest queries time out on public Overpass
ROAD_TYPES = 'motorway|trunk|primary|secondary|tertiary|unclassified|residential'
MAX_SIDE = 30000        # metres; 30 km square = 56 tiles
MAX_ITER = 600          # fall-line chain length cap in cells (6 km at 10 m)
# D8 neighbour offsets as (row, col) with row increasing southward.
OFFSETS = [(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1)]


@dataclass
class Mosaic:
    z: np.ndarray
    west: int
    south: int
    tiles_missing: int

    @property
    def north(self):
        return self.south + self.z.shape[0] * 10


def build_mosaic(west: int, south: int, east: int, north: int) -> Mosaic:
    """Paste the inner 400x400 of each 4 km tile; missing tiles stay NaN (never synthetic)."""
    rows, cols = (north - south) // 10, (east - west) // 10
    z = np.full((rows, cols), np.nan, dtype='float32')
    missing = 0
    for ty in range(south, north, 4000):
        for tx in range(west, east, 4000):
            try:
                tile = fetch_raster(tx - 100, ty - 100, 4200, 10)
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning('Search tile %s_%s unavailable: %s', tx, ty, exc)
                missing += 1
                continue
            r0, c0 = (north - (ty + 4000)) // 10, (tx - west) // 10
            z[r0:r0 + 400, c0:c0 + 400] = tile.z[10:-10, 10:-10]
    return Mosaic(z, west, south, missing)


def fall_line_drop(z, ok, counted):
    """Propagate along steepest descent while `ok` holds (slope below the upper bound).

    Returns [total drop, total length, band drop, band length] grids and the D8 target grid, so
    gentle interruptions are tolerated but anything steeper than the band ends the run.
    Memory-lean: int32 indices, one shifted grid at a time (a 50 km mosaic is 25 M cells).
    """
    z = np.asarray(z, dtype='float32')
    rows, cols = z.shape
    n_cells = rows * cols
    padded = np.pad(z, 1, constant_values=np.nan)
    best_gain = np.full(z.shape, -np.inf, dtype='float32')
    target = np.full(z.shape, -1, dtype=np.int32)
    flat = np.arange(n_cells, dtype=np.int32).reshape(z.shape)
    for dr, dc in OFFSETS:
        nz = padded[1 + dr:1 + dr + rows, 1 + dc:1 + dc + cols]
        gain = (z - nz) / np.float32(10 * np.hypot(dr, dc))
        better = np.isfinite(gain) & (gain > best_gain)
        np.copyto(best_gain, gain, where=better)
        r_src = slice(max(0, -dr), rows - max(0, dr)); c_src = slice(max(0, -dc), cols - max(0, dc))
        r_dst = slice(max(0, dr), rows - max(0, -dr)); c_dst = slice(max(0, dc), cols - max(0, -dc))
        # Only the window where the neighbour exists can be "better"; write targets there directly.
        sub = better[r_src, c_src]
        target[r_src, c_src][sub] = flat[r_dst, c_dst][sub]
        del gain, better, sub
    del padded
    idx = np.flatnonzero(ok & (target.ravel() >= 0) & (best_gain.ravel() > 0)).astype(np.int32)
    del best_gain
    tgt = target.ravel()[idx]
    dz = (z.ravel()[idx] - z.ravel()[tgt]).astype('float32')
    step = np.hypot(10 * np.abs(idx // cols - tgt // cols), 10 * np.abs(idx % cols - tgt % cols)).astype('float32')
    dl = np.hypot(step, dz).astype('float32')
    del step
    ok_t = ok.ravel()[tgt]
    inband = counted.ravel()[idx]
    increments = [dz, dl, np.where(inband, dz, 0), np.where(inband, dl, 0)]  # total drop, total length, band drop, band length
    # Pointer jumping: each pass doubles the chain length already summed, so long runs converge in
    # ~log2(length) passes instead of one pass per cell. A step into terrain that is not `ok`
    # contributes nothing and ends the chain (its target becomes a sink).
    n = len(idx)
    pos = np.full(n_cells, -1, dtype=np.int32); pos[idx] = np.arange(n, dtype=np.int32)
    nxt = np.where(ok_t, pos[tgt], -1).astype(np.int32)
    del pos
    sums = [np.where(ok_t, inc, 0).astype('float32') for inc in increments]
    del increments, dz, dl
    for _ in range(64):
        live = np.flatnonzero(nxt >= 0)
        if not len(live):
            break
        j = nxt[live]
        for acc in sums:
            acc[live] += acc[j]
        nxt[live] = nxt[j]
    full = []
    for acc in sums:
        f = np.zeros(n_cells, dtype='float32'); f[idx] = acc; full.append(f.reshape(z.shape))
    return full, target


OFFLINE = os.getenv('RANDO_OFFLINE') == '1'   # use cached vendor data only; never call the network


def overpass(query, timeout):
    """Query the public Overpass API, falling back to a mirror; None when both fail."""
    if OFFLINE:
        return None
    for url in (*OVERPASS_MIRRORS[::-1], OVERPASS):  # fastest mirror first; the primary has been rate-limiting
        try:
            response = httpx.post(url, data={'data': query}, timeout=timeout, headers={'User-Agent': 'cicrando/0.1 terrain planner'})
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning('Overpass %s failed: %s', url, exc)
    return None


def trace(start, target, ok, z):
    """Follow the fall line from a top cell while the slope stays below the upper bound."""
    path, cell, seen = [start], start, {start}
    while True:
        nxt = target.ravel()[cell]
        if nxt < 0 or not ok.ravel()[nxt] or nxt in seen or len(path) > MAX_ITER:
            break
        path.append(nxt); seen.add(nxt); cell = nxt
    return np.array(path)


def cached_roads(lon0, lat0, lon1, lat1):
    """Union of earlier Overpass road responses clipped to the bbox, used when Overpass is down.

    Coverage is only as good as the earlier queries; None when nothing cached overlaps.
    """
    points = []
    for path in CACHE.glob('*.json'):
        try:
            data = json.loads(path.read_text())
        except ValueError:
            continue
        elements = data.get('elements') if isinstance(data, dict) else None
        if not elements or 'highway' not in elements[0].get('tags', {}):
            continue
        points.extend((n['lon'], n['lat']) for way in elements for n in way.get('geometry', [])
                      if lon0 <= n['lon'] <= lon1 and lat0 <= n['lat'] <= lat1)
    if not points:
        return None
    logger.warning('Using cached road data for %.2f,%.2f–%.2f,%.2f (%d points)', lon0, lat0, lon1, lat1, len(points))
    lon, lat = np.array(points).T
    x, y = TO_UTM.transform(lon, lat)
    return np.column_stack([x, y])


def roads(west, south, east, north):
    """OSM driveable roads inside a padded UTM bbox as UTM points; None when unavailable."""
    lon0, lat0, lon1, lat1 = geo_bbox(west - 3000, south - 3000, east + 3000, north + 3000)
    key = hashlib.sha256(f'roads:{lat0:.3f}:{lon0:.3f}:{lat1:.3f}:{lon1:.3f}:v1'.encode()).hexdigest()[:24]
    path = CACHE / f'{key}.json'
    if path.exists():
        data = json.loads(path.read_text())
    else:
        query = f'[out:json][timeout:90];way["highway"~"^({ROAD_TYPES})$"]({lat0:.5f},{lon0:.5f},{lat1:.5f},{lon1:.5f});out geom;'
        data = overpass(query, 120)
        if data is None:
            return cached_roads(lon0, lat0, lon1, lat1)
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
    points = [(n['lon'], n['lat']) for way in data.get('elements', []) for n in way.get('geometry', [])]
    if not points:
        return np.zeros((0, 2))
    lon, lat = np.array(points).T
    x, y = TO_UTM.transform(lon, lat)
    return np.column_stack([x, y])


AR5 = 'https://wms.nibio.no/cgi-bin/ar5'
# AR5 "Treslag" legend colours (NIBIO WMS): conifer, deciduous, mixed forest; anything else is open.
TREE_COLOURS = {(125, 191, 110): 1, (128, 255, 8): 2, (158, 204, 115): 3}
TREE_NAMES = {1: 'conifer', 2: 'deciduous', 3: 'mixed'}


def forest_tile(tx, ty):
    """AR5 tree-species classes for one 4 km tile at 10 m: 0 open, 1 conifer, 2 deciduous, 3 mixed."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f'ar5_treslag_{tx}_{ty}_v1.png'
    if not path.exists():
        # The layer only renders at scales ≥ 1:50 000, so request 4 m pixels and downsample.
        params = dict(service='WMS', request='GetMap', version='1.1.1', layers='Treslag', styles='', srs='EPSG:25833',
                      bbox=f'{tx},{ty},{tx+4000},{ty+4000}', width=1000, height=1000, format='image/png', transparent='true')
        response = httpx.get(AR5, params=params, timeout=90, headers={'User-Agent': 'cicrando/0.1 terrain planner'})
        response.raise_for_status()
        if not response.headers.get('content-type', '').startswith('image/png'):
            raise ValueError('AR5 WMS returned no image')
        tmp = path.with_name(f'{path.stem}.{os.getpid()}.tmp')
        tmp.write_bytes(response.content)
        try:
            tmp.replace(path)
        except FileNotFoundError:
            tmp.unlink(missing_ok=True)
    try:
        rgba = np.array(Image.open(path).convert('RGBA').resize((400, 400), Image.NEAREST))
    except (OSError, SyntaxError):
        # A truncated file from an interrupted write: drop it and fetch again once.
        path.unlink(missing_ok=True)
        logger.warning('Corrupt AR5 tile %s_%s replaced', tx, ty)
        return forest_tile(tx, ty)
    classes = np.zeros((400, 400), dtype='uint8')
    for colour, code in TREE_COLOURS.items():
        classes[(rgba[..., 3] > 0) & np.all(rgba[..., :3] == colour, axis=-1)] = code
    return classes


# AR5 "Arealtype" legend colours: fresh water, sea, glacier.
WATER_COLOURS = {(145, 231, 255): 1, (204, 254, 254): 2, (230, 255, 255): 3}
WATER_NAMES = {1: 'lake', 2: 'sea', 3: 'glacier'}


def water_tile(tx, ty):
    """AR5 water classes for one 4 km tile at 10 m: 0 land, 1 lake, 2 sea, 3 glacier."""
    return _ar5_tile(tx, ty, 'Arealtype', WATER_COLOURS, 'ar5_arealtype')


def water_mask(west, south, east, north, shape):
    """Water class grid for the extent; None when NIBIO AR5 is unavailable."""
    out = np.zeros(shape, dtype='uint8')
    for ty in range(south, north, 4000):
        for tx in range(west, east, 4000):
            try:
                tile = water_tile(tx, ty)
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning('AR5 water tile %s_%s unavailable: %s', tx, ty, exc)
                return None
            r0, c0 = (north - (ty + 4000)) // 10, (tx - west) // 10
            out[r0:r0 + 400, c0:c0 + 400] = tile
    return out


def _ar5_tile(tx, ty, layer, colours, prefix):
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f'{prefix}_{tx}_{ty}_v1.png'
    if not path.exists():
        if os.getenv('RANDO_OFFLINE') == '1':
            raise ValueError(f'{layer} tile not cached and RANDO_OFFLINE=1')
        params = dict(service='WMS', request='GetMap', version='1.1.1', layers=layer, styles='', srs='EPSG:25833',
                      bbox=f'{tx},{ty},{tx+4000},{ty+4000}', width=1000, height=1000, format='image/png', transparent='true')
        response = httpx.get(AR5, params=params, timeout=90, headers={'User-Agent': 'cicrando/0.1 terrain planner'})
        response.raise_for_status()
        if not response.headers.get('content-type', '').startswith('image/png'):
            raise ValueError('AR5 WMS returned no image')
        tmp = path.with_name(f'{path.stem}.{os.getpid()}.tmp')
        tmp.write_bytes(response.content)
        try:
            tmp.replace(path)
        except FileNotFoundError:
            tmp.unlink(missing_ok=True)
    try:
        rgba = np.array(Image.open(path).convert('RGBA').resize((400, 400), Image.NEAREST))
    except (OSError, SyntaxError):
        path.unlink(missing_ok=True)
        logger.warning('Corrupt AR5 %s tile %s_%s replaced', layer, tx, ty)
        return _ar5_tile(tx, ty, layer, colours, prefix)
    classes = np.zeros((400, 400), dtype='uint8')
    for colour, code in colours.items():
        classes[(rgba[..., 3] > 0) & np.all(rgba[..., :3] == colour, axis=-1)] = code
    return classes


NVE_BRATTHET = 'https://gis3.nve.no/arcgis/rest/services/wmts/Bratthet_med_utlop_2024/MapServer/export'
# "runout_encoded_lo" (long/most conservative modelled runout distance) swatch colour.
RUNOUT_COLOUR = (154, 177, 230)


def runout_tile(tx, ty):
    """NVE modelled avalanche runout ('lo', most conservative) for one 4 km tile at 10 m: 0/1."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f'nve_runout_{tx}_{ty}_v1.png'
    if not path.exists():
        if os.getenv('RANDO_OFFLINE') == '1':
            raise ValueError('NVE runout tile not cached and RANDO_OFFLINE=1')
        params = dict(bbox=f'{tx},{ty},{tx+4000},{ty+4000}', bboxSR=25833, imageSR=25833, size='1000,1000',
                      format='png32', transparent='true', layers='show:4', f='image')
        response = httpx.get(NVE_BRATTHET, params=params, timeout=90, headers={'User-Agent': 'cicrando/0.1 terrain planner'})
        response.raise_for_status()
        if not response.headers.get('content-type', '').startswith('image/png'):
            raise ValueError('NVE runout service returned no image')
        tmp = path.with_name(f'{path.stem}.{os.getpid()}.tmp')
        tmp.write_bytes(response.content)
        try:
            tmp.replace(path)
        except FileNotFoundError:
            tmp.unlink(missing_ok=True)
    try:
        rgba = np.array(Image.open(path).convert('RGBA').resize((400, 400), Image.NEAREST))
    except (OSError, SyntaxError):
        path.unlink(missing_ok=True)
        logger.warning('Corrupt NVE runout tile %s_%s replaced', tx, ty)
        return runout_tile(tx, ty)
    return ((rgba[..., 3] > 0) & np.all(rgba[..., :3] == RUNOUT_COLOUR, axis=-1)).astype('uint8')


def runout_mask(west, south, east, north, shape):
    """Modelled avalanche runout grid (1 = inside the conservative runout zone) for the extent.

    Advisory only, not a stability assessment: coverage is a model output, not verified terrain.
    None when the NVE service is unavailable.
    """
    out = np.zeros(shape, dtype='uint8')
    for ty in range(south, north, 4000):
        for tx in range(west, east, 4000):
            try:
                tile = runout_tile(tx, ty)
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning('NVE runout tile %s_%s unavailable: %s', tx, ty, exc)
                return None
            r0, c0 = (north - (ty + 4000)) // 10, (tx - west) // 10
            out[r0:r0 + 400, c0:c0 + 400] = tile
    return out


def forest_mask(west, south, east, north, shape):
    """Tree-species class grid for the search extent; None when NIBIO AR5 is unavailable."""
    out = np.zeros(shape, dtype='uint8')
    for ty in range(south, north, 4000):
        for tx in range(west, east, 4000):
            try:
                tile = forest_tile(tx, ty)
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning('AR5 tile %s_%s unavailable: %s', tx, ty, exc)
                return None
            r0, c0 = (north - (ty + 4000)) // 10, (tx - west) // 10
            out[r0:r0 + 400, c0:c0 + 400] = tile
    return out


def sun_hours(coarse, x, y, z, slope, aspect, lon, lat, day, start, end):
    """Approximate potential sun at one point using 100 m terrain horizons only."""
    bearings = np.arange(0, 360, 5)
    horizons = np.full(72, -90.0)
    dist = np.arange(100, 40001, 200)
    for i, b in enumerate(bearings):
        zz = coarse.sample(x + np.sin(np.radians(b)) * dist, y + np.cos(np.radians(b)) * dist)
        ok = np.isfinite(zz)
        if not ok.all():
            return None
        horizons[i] = np.degrees(np.arctan2(zz - z, dist)).max()
    minutes, s, a = 0, np.radians(slope), np.radians(aspect)
    for minute in range(round(start * 60), round(end * 60), 10):
        az, alt = solar(lat, lon, local_time(day, minute / 60))
        h = max(horizons[int(az // 5) % 72], horizons[(int(az // 5) + 1) % 72])
        inc = np.sin(np.radians(alt)) * np.cos(s) + np.cos(np.radians(alt)) * np.sin(s) * np.cos(np.radians(az) - a)
        if alt > 0 and alt > h and inc > 0:
            minutes += min(10, round(end * 60) - minute)
    return round(minutes / 60, 1)


def search(west, south, east, north, lower, upper, min_length, day, start, end, horizontal, vertical, limit=60, band_share=0.6):
    mosaic = build_mosaic(west, south, east, north)
    z = mosaic.z
    slope, aspect = derivatives(z, 10)
    # A 3x3 mean tames 10 m noise for the band test; raw slope is still reported.
    smooth = ndimage.uniform_filter(np.nan_to_num(slope, nan=90.0), 3)
    valid = np.isfinite(slope)
    ok = (smooth < upper) & (smooth > 3) & valid          # run continues: not steeper than the band, still descending
    counted = ok & (smooth > lower)                       # counts towards continuous in-band skiing
    (total_drop, total_len, band_drop, band_len), target = fall_line_drop(np.nan_to_num(z, nan=-1e9), ok.ravel(), counted.ravel())
    tops = (band_len >= min_length) & counted
    labels, count = ndimage.label(tops, structure=np.ones((3, 3)))
    coarse = fetch_raster(west - 42000, south - 42000, (east - west) + 84000, 100) if count else None
    road_xy = roads(west, south, east, north) if count else None
    forest = forest_mask(west, south, east, north, z.shape) if count else None
    candidates = []
    for label in range(1, count + 1):
        cells = np.flatnonzero(labels.ravel() == label)
        if len(cells) < 5:
            continue
        top = cells[np.argmax(band_len.ravel()[cells])]
        path = trace(top, target, ok, z)
        # The run ends at its last in-band cell; the gentle runout below is not part of the face.
        inband = counted.ravel()[path]
        path = path[:np.flatnonzero(inband)[-1] + 1]
        r, c = np.divmod(path, z.shape[1])
        xs, ys = west + c * 10 + 5, mosaic.north - r * 10 - 5
        zs, raw = z.ravel()[path], slope.ravel()[path]
        # The D8 line hugs gully floors; drop runs whose raw slope along the line falls out of the band,
        # and runs where gentle interruptions make up more than the allowed share.
        if not lower - 1 <= np.nanmean(raw) <= upper or inband[:len(path)].mean() < band_share:
            continue
        asp = aspect.ravel()[path]
        asp = asp[np.isfinite(asp)]
        mean_aspect = float(np.degrees(np.arctan2(np.sin(np.radians(asp)).mean(), np.cos(np.radians(asp)).mean())) % 360) if len(asp) else None
        length = float(np.hypot(np.diff(xs), np.diff(ys)).sum())
        mid = len(path) // 2
        lon, lat = TO_LL.transform(xs[mid], ys[mid])
        trees = None if forest is None else forest.ravel()[path]
        forest_share = None if trees is None else round(float((trees > 0).mean()) * 100)
        terrain = None if forest_share is None else ('trees' if forest_share >= 60 else 'open' if forest_share <= 20 else 'mixed')
        forest_type = None if trees is None or not (trees > 0).any() else TREE_NAMES[int(np.bincount(trees[trees > 0], minlength=4)[1:].argmax()) + 1]
        item = dict(id=f'{west}_{south}_{label}', top=list(TO_LL.transform(xs[0], ys[0])), bottom=list(TO_LL.transform(xs[-1], ys[-1])),
                    center=[lon, lat], line=[list(TO_LL.transform(x, y)) for x, y in zip(xs[::3], ys[::3])] + [list(TO_LL.transform(xs[-1], ys[-1]))],
                    top_elevation=finite(zs[0]), bottom_elevation=finite(zs[-1]), drop=finite(zs[0] - zs[-1]),
                    band_drop=finite(band_drop.ravel()[top]), band_length_m=round(float(band_len.ravel()[top])), length_m=round(length),
                    mean_slope=finite(np.nanmean(raw)), max_raw_slope=finite(np.nanmax(raw)),
                    steep_share=round(float(np.mean(raw >= 30)) * 100, 1), aspect=finite(mean_aspect) if mean_aspect is not None else None,
                    band_share=round(float(inband[:len(path)].mean()) * 100), top_area_m2=int(len(cells) * 100), forest_share=forest_share, forest_type=forest_type, terrain=terrain, approach=None,
                    sun_hours=sun_hours(coarse, xs[mid], ys[mid], zs[mid], float(np.nanmean(raw)), mean_aspect or 0, lon, lat, day, start, end))
        if road_xy is not None and len(road_xy):
            d = np.hypot(road_xy[:, 0] - xs[-1], road_xy[:, 1] - ys[-1])
            k = int(np.argmin(d))
            rz = coarse.sample(road_xy[k, 0], road_xy[k, 1])
            gain = float(zs[-1] - rz) if np.isfinite(rz) else None
            hours = d[k] / 1000 / horizontal + (max(gain, 0) / vertical if gain is not None else 0)
            item['approach'] = dict(road=list(TO_LL.transform(*road_xy[k])), distance_km=round(float(d[k]) / 1000, 2),
                                    gain_m=finite(gain) if gain is not None else None, hours=round(float(hours), 2), complete=gain is not None)
        elif road_xy is not None:
            item['approach'] = dict(road=None, distance_km=None, gain_m=None, hours=None, complete=False)
        candidates.append(item)
    candidates.sort(key=lambda c: (c['approach'] is None or c['approach']['hours'] is None, (c['approach'] or {}).get('hours') or 0, -(c['band_length_m'] or 0)))
    return dict(count=len(candidates), candidates=candidates[:limit], tiles_missing=mosaic.tiles_missing,
                roads=None if road_xy is None else int(len(road_xy)), forest=forest is not None,
                bounds=[list(TO_LL.transform(west, south)), list(TO_LL.transform(east, north))],
                method=f'Fall-line runs on 10 m terrain. A run continues while 3×3-smoothed slope stays below {upper}°; '
                       f'it qualifies when at least {min_length} m of run length lies within {lower}–{upper}° and, between top and last in-band cell, at least {int(band_share*100)}% of cells are in band. '
                       'Approach is straight-line from the nearest OSM road (winter access and parking unknown). '
                       'Trees/open and tree species from NIBIO AR5 (Treslag). Sun hours use 100 m horizons.')
