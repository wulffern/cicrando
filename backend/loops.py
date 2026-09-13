"""Summit loops: park, skin up the gentlest line, ski the best 20–30° run, return to the car.

Start points are OSM parking areas (fallback: road points). Winter access is classified from
OSM/NVDB tags, road class and data/winter_roads.json overrides — 'plowed', 'unknown' or 'closed'.
Legs are least-cost paths on the 10 m grid from the parking spot (≥35° impassable), so the ascent
and the return from the run's bottom are both gentle terrain possibilities, not checked routes.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx
import numpy as np
from scipy import ndimage
from skimage.graph import MCP_Geometric

from .search import CACHE, build_mosaic, fall_line_drop, forest_mask, overpass, trace, TREE_NAMES
from .terrain import TO_LL, TO_UTM, derivatives, finite
from .toppturs import ascent_costs, find_peaks, path_stats

logger = logging.getLogger('rando.loops')
PLOWED = {'motorway', 'trunk', 'primary', 'secondary', 'tertiary'}
NVDB = 'https://nvdbapiles.atlas.vegvesen.no/vegobjekter'


def osm_access(west, south, east, north):
    """Parking spots and winter-tagged roads for a UTM bbox; cached; None when Overpass is down."""
    lon0, lat0 = TO_LL.transform(west, south); lon1, lat1 = TO_LL.transform(east, north)
    path = CACHE / f'access_{west}_{south}_{east}_{north}_v1.json'
    if path.exists():
        return json.loads(path.read_text())
    bb = f'({lat0:.4f},{lon0:.4f},{lat1:.4f},{lon1:.4f})'
    query = (f'[out:json][timeout:120];(node["amenity"="parking"]{bb};way["amenity"="parking"]{bb};'
             f'way["highway"]["winter_service"="no"]{bb};way["highway"]["seasonal"]{bb};way["highway"]["snowplowing"="no"]{bb};'
             f'way["highway"~"^(motorway|trunk|primary|secondary|tertiary|unclassified|residential|service|track)$"]{bb};);out center tags geom;')
    data = overpass(query, 200)
    if data is None:
        return None
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return data


def nvdb_unplowed(west, south, east, north):
    """NVDB 810 segments with 'Ingen vinterdrift' as UTM point arrays; empty when unavailable."""
    url = f'{NVDB}/810?kartutsnitt={west},{south},{east},{north}&inkluder=egenskaper,geometri&srid=5973&antall=1000'
    pts = []
    try:
        for _ in range(60):
            d = httpx.get(url, headers={'Accept': 'application/json', 'X-Client': 'cicrando'}, timeout=60).json()
            for o in d.get('objekter', []):
                klass = next((e.get('verdi') for e in o.get('egenskaper', []) if e['navn'] == 'Vinterdriftsklasse'), None)
                if klass == 'Ingen vinterdrift':
                    wkt = o.get('geometri', {}).get('wkt', '')
                    for token in wkt.replace('(', ' ').replace(')', ' ').replace(',', ' , ').split(','):
                        nums = token.split()
                        if len(nums) >= 2:
                            try:
                                pts.append((float(nums[0]), float(nums[1])))
                            except ValueError:
                                pass
            nxt = d.get('metadata', {}).get('neste')
            if not nxt or not d.get('objekter'):
                break
            url = nxt['href']
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning('NVDB unavailable: %s', exc)
    return np.array(pts) if pts else np.zeros((0, 2))


def parking_spots(west, south, east, north):
    """Parking points with winter-access class; None when no access data at all."""
    data = osm_access(west - 5000, south - 5000, east + 5000, north + 5000)
    if data is None:
        return None
    roads, closed_pts, spots = [], [], []
    for e in data['elements']:
        t = e.get('tags', {})
        geom = e.get('geometry') or ([{'lat': e['lat'], 'lon': e['lon']}] if 'lat' in e else [{'lat': e['center']['lat'], 'lon': e['center']['lon']}] if 'center' in e else [])
        if t.get('amenity') == 'parking':
            c = e.get('center') or {'lat': e.get('lat'), 'lon': e.get('lon')}
            if c.get('lat') is not None:
                spots.append(dict(lon=c['lon'], lat=c['lat'], name=t.get('name'), tags={k: t[k] for k in ('access', 'fee', 'parking', 'capacity', 'winter_service', 'description') if k in t}))
        elif 'highway' in t:
            closed = t.get('winter_service') == 'no' or t.get('snowplowing') == 'no' or t.get('seasonal') in ('summer', 'yes')
            for n in geom:
                roads.append((n['lon'], n['lat'], t['highway'], closed))
    if not spots:
        return []
    rx, ry = TO_UTM.transform(np.array([r[0] for r in roads]), np.array([r[1] for r in roads])) if roads else (np.zeros(0), np.zeros(0))
    nvdb = nvdb_unplowed(west - 5000, south - 5000, east + 5000, north + 5000)
    overrides = json.loads(Path('data/winter_roads.json').read_text()).get('overrides', []) if Path('data/winter_roads.json').exists() else []
    for s in spots:
        x, y = TO_UTM.transform(s['lon'], s['lat']); s['x'], s['y'] = float(x), float(y)
        status, road = 'unknown', None
        if len(rx):
            d = np.hypot(rx - x, ry - y); k = int(np.argmin(d))
            if d[k] <= 80:
                road = roads[k][2]
                status = 'closed' if roads[k][3] else 'plowed' if road in PLOWED else 'unknown'
        if len(nvdb) and np.hypot(nvdb[:, 0] - x, nvdb[:, 1] - y).min() <= 60:
            status = 'closed'
        if s['tags'].get('winter_service') == 'no':
            status = 'closed'
        for o in overrides:
            ox, oy = TO_UTM.transform(*o['near'])
            if np.hypot(ox - x, oy - y) <= o.get('radius_m', 300):
                status = 'closed' if o['status'] == 'closed' else 'plowed'
        s['access'] = status; s['road'] = road
    return spots


def run_candidates(pr, pc, z, band_len, counted, target, ok, slope, aspect, forest, max_runs=4):
    """Up to `max_runs` distinct fall-line runs starting within 800 m / 200 m below the summit."""
    rr, cc = np.ogrid[:z.shape[0], :z.shape[1]]
    near = ((rr - pr) ** 2 + (cc - pc) ** 2 <= 80 ** 2) & counted & (np.nan_to_num(z, nan=-1e9) >= z[pr, pc] - 200)
    order = np.argsort(-np.where(near, band_len, 0).ravel())[:400]
    runs, ends = [], []
    for top in order:
        if band_len.ravel()[top] < 300:
            break
        run = trace(int(top), target, ok, z)
        inband = counted.ravel()[run]
        run = run[:np.flatnonzero(inband)[-1] + 1]
        dr, dc = np.divmod(run, z.shape[1])
        if any(np.hypot(dr[-1] - er, dc[-1] - ec) < 60 for er, ec in ends):
            continue  # same run, different top cell
        raw = slope[dr, dc]
        if not 19 <= np.nanmean(raw) <= 30 or inband[:len(run)].mean() < 0.6:
            continue
        asp = aspect[dr, dc]; asp = asp[np.isfinite(asp)]
        mean_aspect = float(np.degrees(np.arctan2(np.sin(np.radians(asp)).mean(), np.cos(np.radians(asp)).mean())) % 360) if len(asp) else None
        trees = None if forest is None else forest[dr, dc]
        runs.append(dict(cells=run, end=(int(dr[-1]), int(dc[-1])), band_length_m=round(float(band_len.ravel()[top])), drop=finite(z[dr[0], dc[0]] - z[dr[-1], dc[-1]]),
                         top_elevation=finite(z[dr[0], dc[0]]), bottom_elevation=finite(z[dr[-1], dc[-1]]), mean_slope=finite(np.nanmean(raw)), max_slope=finite(np.nanmax(raw)),
                         steep_share=round(float(np.mean(raw >= 30)) * 100, 1), band_share=round(float(inband[:len(run)].mean()) * 100), aspect=finite(mean_aspect) if mean_aspect is not None else None,
                         forest_share=None if trees is None else round(float((trees > 0).mean()) * 100),
                         forest_type=None if trees is None or not (trees > 0).any() else TREE_NAMES[int(np.bincount(trees[trees > 0], minlength=4)[1:].argmax()) + 1],
                         start_offset_m=round(float(np.hypot(dr[0] - pr, dc[0] - pc) * 10)), start_below_summit_m=finite(z[pr, pc] - z[dr[0], dc[0]])))
        ends.append((dr[-1], dc[-1]))
        if len(runs) >= max_runs:
            break
    return runs


def loops(west, south, east, north, lower=20, upper=30, max_ascent=35, horizontal=4, vertical=400, margin=6000, max_parkings=4, search_km=7,
          return_max_km=4.0, return_max_gain=150, include_closed=False):
    W, S, E, N = west - margin, south - margin, east + margin, north + margin
    mosaic = build_mosaic(W, S, E, N); z = mosaic.z
    slope, aspect = derivatives(z, 10)
    forest = forest_mask(W, S, E, N, z.shape)
    spots = parking_spots(west, south, east, north)
    if spots is None:
        raise RuntimeError('Parking/road data unavailable')
    costs = ascent_costs(slope, max_ascent, lower)
    smooth = ndimage.uniform_filter(np.nan_to_num(slope, nan=90.0), 3)
    ok = (smooth < upper) & (smooth > 3) & np.isfinite(slope)
    counted = ok & (smooth > lower)
    (_, _, _, band_len), target = fall_line_drop(np.nan_to_num(z, nan=-1e9), ok.ravel(), counted.ravel())
    sx = np.array([s['x'] for s in spots]); sy = np.array([s['y'] for s in spots])
    r0, c0 = margin // 10, margin // 10
    tours = []
    for pr, pc in find_peaks(z):
        if not (r0 <= pr < r0 + (north - south) // 10 and c0 <= pc < c0 + (east - west) // 10):
            continue
        px, py = W + pc * 10 + 5, mosaic.north - pr * 10 - 5
        d = np.hypot(sx - px, sy - py)
        order = [i for i in np.argsort(d) if d[i] <= search_km * 1000 and (include_closed or spots[i]['access'] != 'closed')][:max_parkings]
        runs = run_candidates(pr, pc, z, band_len, counted, target, ok, slope, aspect, forest)
        summit = dict(summit=list(TO_LL.transform(px, py)), elevation=finite(z[pr, pc]), options=[])
        for i in order:
            s = spots[i]
            sr, sc = int((mosaic.north - s['y']) // 10), int((s['x'] - W) // 10)
            if not (0 <= sr < z.shape[0] and 0 <= sc < z.shape[1]) or not np.isfinite(costs[sr, sc]):
                continue
            # Window around parking + summit + all run ends, padded 1.5 km.
            rows = [pr, sr] + [r['end'][0] for r in runs]; cols = [pc, sc] + [r['end'][1] for r in runs]
            wr0, wr1 = max(0, min(rows) - 150), min(z.shape[0], max(rows) + 150); wc0, wc1 = max(0, min(cols) - 150), min(z.shape[1], max(cols) + 150)
            mcp = MCP_Geometric(costs[wr0:wr1, wc0:wc1], fully_connected=True)
            cumulative, _ = mcp.find_costs(starts=[(sr - wr0, sc - wc0)])
            if not np.isfinite(cumulative[pr - wr0, pc - wc0]):
                continue
            up = np.array(mcp.traceback((pr - wr0, pc - wc0))) + (wr0, wc0)
            ascent = path_stats(up[:, 0], up[:, 1], z, slope, forest, horizontal, vertical)
            ascent['line'] = [list(TO_LL.transform(W + c * 10 + 5, mosaic.north - r * 10 - 5)) for r, c in up[::5]] + [summit['summit']]
            best = None
            for run in runs:
                er, ec = run['end']
                if not np.isfinite(cumulative[er - wr0, ec - wc0]):
                    continue
                back = np.array(mcp.traceback((er - wr0, ec - wc0))) + (wr0, wc0)
                back = back[::-1]  # from run end to the car
                ret = path_stats(back[:, 0], back[:, 1], z, slope, forest, horizontal, vertical)
                if ret['length_m'] > return_max_km * 1000 or ret['gain_m'] > return_max_gain:
                    continue
                score = run['band_length_m'] - 0.3 * ret['length_m'] - 3 * ret['gain_m']
                if best is None or score > best[0]:
                    best = (score, run, ret, back)
            if best is None:
                continue
            score, run, ret, back = best
            dr, dc = np.divmod(run['cells'], z.shape[1])
            descent = {k: v for k, v in run.items() if k not in ('cells', 'end')}
            descent['line'] = [list(TO_LL.transform(W + c * 10 + 5, mosaic.north - r * 10 - 5)) for r, c in zip(dr[::3], dc[::3])] + [list(TO_LL.transform(W + dc[-1] * 10 + 5, mosaic.north - dr[-1] * 10 - 5))]
            ret['line'] = [list(TO_LL.transform(W + c * 10 + 5, mosaic.north - r * 10 - 5)) for r, c in back[::5]] + [[s['lon'], s['lat']]]
            down_hours = round(run['band_length_m'] / 8000 + descent['start_offset_m'] / 4000, 2)
            summit['options'].append(dict(parking=dict(lon=s['lon'], lat=s['lat'], name=s['name'], access=s['access'], road=s['road'], tags=s['tags'], distance_km=round(float(d[i]) / 1000, 2)),
                                          ascent=ascent, descent=descent, back=ret, score=round(float(score)),
                                          total_hours=round(ascent['hours'] + down_hours + ret['hours'], 2)))
        if summit['options']:
            summit['options'].sort(key=lambda o: -o['score'])
            tours.append(summit)
    return dict(tours=tours, parkings=len(spots), tiles_missing=mosaic.tiles_missing, forest=forest is not None,
                method=f'Loops from OSM parking within {search_km} km of each summit. Ascent and return are least-cost paths from the car (≥{max_ascent}° impassable, 30–35° ×4). '
                       f'Descent: best 20–30° run near the summit whose bottom can be walked back to the car in ≤{return_max_km} km with ≤{return_max_gain} m of climbing. '
                       'Winter access: plowed = county road or better; unknown = minor road; closed = OSM/NVDB tag or data/winter_roads.json.')
