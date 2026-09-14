"""Summit tours: named summits, the gentlest ascent from a road, and the best 20–30° descent.

Ascent uses a least-cost path over the 10 m grid where cells ≥ `max_ascent` degrees are impassable
and 30–35° is heavily penalised; the result is the safest line the terrain allows, not a checked
route. Descent reuses the fall-line run search. Drive times come from OSRM (OpenStreetMap roads).
"""
from __future__ import annotations

import logging
import httpx
import numpy as np
from scipy import ndimage
from skimage.graph import MCP_Geometric

from .search import build_mosaic, fall_line_drop, forest_mask, roads, trace, TREE_NAMES
from .terrain import TO_LL, TO_UTM, derivatives, finite

logger = logging.getLogger('rando.toppturs')
OSRM = 'https://router.project-osrm.org'


def find_peaks(z, window_m=1500, min_elevation=900, min_relief=150):
    """Local maxima of the 10 m grid with at least `min_relief` over their window."""
    size = window_m // 10
    zz = np.nan_to_num(z, nan=-1e9)
    top = (zz == ndimage.maximum_filter(zz, size=size)) & (zz >= min_elevation)
    relief = zz - ndimage.minimum_filter(np.nan_to_num(z, nan=1e9), size=size)
    return np.argwhere(top & (relief >= min_relief))


def ascent_costs(slope, max_ascent, lower=20, water=None):
    """Cost per metre: gentle 1, 20–25° 1.3, 25–30° 1.8, 30–max 4; steeper or unknown impassable.

    With an AR5 water grid: sea and glacier impassable, lakes crossable at double cost (ice unknown).
    """
    cost = np.full(slope.shape, np.inf, dtype='float32')
    ok = np.isfinite(slope) & (slope < max_ascent)
    cost[ok] = 1 + np.select([slope[ok] >= 30, slope[ok] >= 25, slope[ok] >= lower], [3.0, 0.8, 0.3], 0)
    if water is not None:
        cost[water >= 2] = np.inf
        cost[water == 1] *= 2
    return cost


def path_stats(rows, cols, z, slope, forest, horizontal, vertical, water=None):
    zs, raw = z[rows, cols], slope[rows, cols]
    xs, ys = cols * 10.0, rows * 10.0
    steps = np.hypot(np.diff(xs), np.diff(ys))
    dz = np.diff(zs)
    length = float(np.hypot(steps, dz).sum())
    gain = float(np.maximum(dz, 0).sum())
    return dict(length_m=round(length), gain_m=round(gain), loss_m=round(float(np.maximum(-dz, 0).sum())),
                max_slope=finite(np.nanmax(raw)), mean_slope=finite(np.nanmean(raw)),
                share_over_30=round(float(np.mean(raw >= 30)) * 100, 1), share_over_25=round(float(np.mean(raw >= 25)) * 100, 1),
                share_band=round(float(np.mean((raw >= 20) & (raw < 30))) * 100, 1),
                hours=round(length / 1000 / horizontal + gain / vertical, 2),
                forest_share=None if forest is None else round(float((forest[rows, cols] > 0).mean()) * 100),
                lake_m=None if water is None else int(np.sum(water[rows, cols] == 1)) * 10)


def drive_minutes(origin, points):
    """OSRM driving minutes from origin (lon, lat) to each point; cached per pair; None when unroutable."""
    import json
    from .search import CACHE, OFFLINE
    cache_path = CACHE / 'osrm_drive_v1.json'
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    key = lambda p: f'{origin[0]:.4f},{origin[1]:.4f}>{p[0]:.4f},{p[1]:.4f}'
    out = [cache.get(key(p), 'miss') for p in points]
    missing = [i for i, v in enumerate(out) if v == 'miss']
    if missing and OFFLINE:
        logger.warning('%d drive times not cached and RANDO_OFFLINE=1', len(missing))
    fetched = _osrm([points[i] for i in missing], origin) if missing and not OFFLINE else [None] * len(missing)
    for i, v in zip(missing, fetched):
        out[i] = v
        if v is not None:
            cache[key(points[i])] = v
    CACHE.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache))
    return [None if v == 'miss' else v for v in out]


def _osrm(points, origin):
    out = []
    for i in range(0, len(points), 90):
        batch = points[i:i + 90]
        coords = ';'.join(f'{lon:.5f},{lat:.5f}' for lon, lat in [origin] + batch)
        try:
            r = httpx.get(f'{OSRM}/table/v1/driving/{coords}', params=dict(sources=0, annotations='duration'), timeout=60,
                          headers={'User-Agent': 'cicrando/0.1 terrain planner'})
            r.raise_for_status()
            durations = r.json()['durations'][0][1:]
            out.extend(None if d is None else round(d / 60) for d in durations)
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            logger.warning('OSRM unavailable: %s', exc)
            out.extend([None] * len(batch))
    return out


def toppturs(west, south, east, north, lower=20, upper=30, max_ascent=35, min_run=300, horizontal=4, vertical=400, margin=4000):
    """Summits inside the block, with ascent from roads and descent runs computed on a margin-padded mosaic."""
    W, S, E, N = west - margin, south - margin, east + margin, north + margin
    mosaic = build_mosaic(W, S, E, N)
    z = mosaic.z
    slope, aspect = derivatives(z, 10)
    forest = forest_mask(W, S, E, N, z.shape)
    road_xy = roads(W, S, E, N)
    if road_xy is None or not len(road_xy):
        raise RuntimeError('Road data unavailable for this block')
    rc = np.column_stack([((mosaic.north - road_xy[:, 1]) // 10).astype(int), ((road_xy[:, 0] - W) // 10).astype(int)])
    inside = (rc[:, 0] >= 0) & (rc[:, 0] < z.shape[0]) & (rc[:, 1] >= 0) & (rc[:, 1] < z.shape[1])
    rc = np.unique(rc[inside], axis=0)
    costs = ascent_costs(slope, max_ascent, lower)
    rc = rc[np.isfinite(costs[rc[:, 0], rc[:, 1]])]
    mcp = MCP_Geometric(costs, fully_connected=True)
    cumulative, _ = mcp.find_costs(starts=[tuple(p) for p in rc])
    smooth = ndimage.uniform_filter(np.nan_to_num(slope, nan=90.0), 3)
    ok = (smooth < upper) & (smooth > 3) & np.isfinite(slope)
    counted = ok & (smooth > lower)
    (total_drop, total_len, band_drop, band_len), target = fall_line_drop(np.nan_to_num(z, nan=-1e9), ok.ravel(), counted.ravel())
    peaks = find_peaks(z)
    r0, c0 = margin // 10, margin // 10
    tours = []
    for pr, pc in peaks:
        if not (r0 <= pr < r0 + (north - south) // 10 and c0 <= pc < c0 + (east - west) // 10):
            continue  # summit belongs to a neighbouring block
        if not np.isfinite(cumulative[pr, pc]):
            tours.append(dict(summit=list(TO_LL.transform(W + pc * 10 + 5, mosaic.north - pr * 10 - 5)), elevation=finite(z[pr, pc]), ascent=None, descent=None))
            continue
        path = np.array(mcp.traceback((pr, pc)))
        rows, cols = path[:, 0], path[:, 1]
        ascent = path_stats(rows, cols, z, slope, forest, horizontal, vertical)
        start = (W + cols[0] * 10 + 5, mosaic.north - rows[0] * 10 - 5)
        ascent['start'] = list(TO_LL.transform(*start))
        ascent['line'] = [list(TO_LL.transform(W + c * 10 + 5, mosaic.north - r * 10 - 5)) for r, c in path[::5]] + [list(TO_LL.transform(W + pc * 10 + 5, mosaic.north - pr * 10 - 5))]
        # Best continuous run starting within 800 m of, and at most 200 m below, the summit.
        rr, cc = np.ogrid[:z.shape[0], :z.shape[1]]
        near = ((rr - pr) ** 2 + (cc - pc) ** 2 <= 80 ** 2) & counted & (np.nan_to_num(z, nan=-1e9) >= z[pr, pc] - 200)
        descent = None
        if near.any():
            cand = np.where(near, band_len, 0)
            top = int(np.argmax(cand))
            if band_len.ravel()[top] >= min_run:
                run = trace(top, target, ok, z)
                inband = counted.ravel()[run]
                run = run[:np.flatnonzero(inband)[-1] + 1]
                dr, dc = np.divmod(run, z.shape[1])
                raw = slope[dr, dc]
                asp = aspect[dr, dc]; asp = asp[np.isfinite(asp)]
                mean_aspect = float(np.degrees(np.arctan2(np.sin(np.radians(asp)).mean(), np.cos(np.radians(asp)).mean())) % 360) if len(asp) else None
                end = (W + dc[-1] * 10 + 5, mosaic.north - dr[-1] * 10 - 5)
                trees = None if forest is None else forest[dr, dc]
                descent = dict(band_length_m=round(float(band_len.ravel()[top])), drop=finite(z[dr[0], dc[0]] - z[dr[-1], dc[-1]]),
                               top_elevation=finite(z[dr[0], dc[0]]), bottom_elevation=finite(z[dr[-1], dc[-1]]),
                               mean_slope=finite(np.nanmean(raw)), max_slope=finite(np.nanmax(raw)), steep_share=round(float(np.mean(raw >= 30)) * 100, 1),
                               band_share=round(float(inband[:len(run)].mean()) * 100), aspect=finite(mean_aspect) if mean_aspect is not None else None,
                               forest_share=None if trees is None else round(float((trees > 0).mean()) * 100),
                               forest_type=None if trees is None or not (trees > 0).any() else TREE_NAMES[int(np.bincount(trees[trees > 0], minlength=4)[1:].argmax()) + 1],
                               start_offset_m=round(float(np.hypot(dr[0] - pr, dc[0] - pc) * 10)), start_below_summit_m=finite(z[pr, pc] - z[dr[0], dc[0]]),
                               end=list(TO_LL.transform(*end)), end_to_car_km=round(float(np.hypot(end[0] - start[0], end[1] - start[1])) / 1000, 2),
                               line=[list(TO_LL.transform(W + c * 10 + 5, mosaic.north - r * 10 - 5)) for r, c in zip(dr[::3], dc[::3])] + [list(TO_LL.transform(*end))])
        tours.append(dict(summit=list(TO_LL.transform(W + pc * 10 + 5, mosaic.north - pr * 10 - 5)), elevation=finite(z[pr, pc]), ascent=ascent, descent=descent))
    return dict(tours=tours, tiles_missing=mosaic.tiles_missing, forest=forest is not None,
                method=f'Summits: 10 m local maxima ≥900 m with ≥150 m relief in 1.5 km. Ascent: least-cost path from OSM roads; cells ≥{max_ascent}° impassable, 30–{max_ascent}° cost ×4, 25–30° ×1.8, 20–25° ×1.3. Descent: best fall-line run (≥{min_run} m within {lower}–{upper}°) starting within 800 m of and ≤200 m below the summit.')
