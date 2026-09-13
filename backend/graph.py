"""Route graph for multi-leg summit tours: parkings, summits and runs joined by least-cost legs.

Nodes: parking spots (OSM, with winter-access class), summits, and fall-line runs (top → bottom).
Edges: skin legs parking→summit and run-bottom→summit, walk legs run-bottom→parking, and the
implicit summit→run descent. Legs are least-cost paths on the 10 m grid (≥35° impassable,
30–35° ×4) — gentle terrain possibilities, not checked routes. A static page chains the edges.
"""
from __future__ import annotations

import logging
import numpy as np
from scipy import ndimage
from skimage.graph import MCP_Geometric

from .loops import parking_spots, run_candidates
from .search import build_mosaic, fall_line_drop, forest_mask
from .terrain import TO_LL, derivatives, finite
from .toppturs import ascent_costs, find_peaks, path_stats

logger = logging.getLogger('rando.graph')


def line(cells, W, north, step):
    pts = [list(TO_LL.transform(W + c * 10 + 5, north - r * 10 + -5)) for r, c in cells[::step]]
    last = cells[-1]
    pts.append(list(TO_LL.transform(W + last[1] * 10 + 5, north - last[0] * 10 - 5)))
    return [[round(x, 5), round(y, 5)] for x, y in pts]


def legs_from(source, targets, costs, z, slope, forest, W, north, radius_cells, horizontal, vertical):
    """Least-cost legs from one source cell to the target cells within the window; list of (target index, stats)."""
    sr, sc = source
    wr0, wr1 = max(0, sr - radius_cells), min(z.shape[0], sr + radius_cells); wc0, wc1 = max(0, sc - radius_cells), min(z.shape[1], sc + radius_cells)
    if not np.isfinite(costs[sr, sc]):
        return []
    mcp = MCP_Geometric(costs[wr0:wr1, wc0:wc1], fully_connected=True)
    cumulative, _ = mcp.find_costs(starts=[(sr - wr0, sc - wc0)])
    out = []
    for i, (tr, tc) in targets:
        if not (wr0 <= tr < wr1 and wc0 <= tc < wc1) or not np.isfinite(cumulative[tr - wr0, tc - wc0]):
            continue
        path = np.array(mcp.traceback((tr - wr0, tc - wc0))) + (wr0, wc0)
        stats = path_stats(path[:, 0], path[:, 1], z, slope, forest, horizontal, vertical)
        stats['line'] = line(path, W, north, 8)
        out.append((i, stats))
    return out


def build(west, south, east, north, prefix, lower=20, upper=30, max_ascent=35, horizontal=4, vertical=400, margin=6000, reach_km=7, walk_km=5):
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
    r0, c0 = margin // 10, margin // 10
    cell = lambda x, y: (int((mosaic.north - y) // 10), int((x - W) // 10))
    inside = lambda r, c: 0 <= r < z.shape[0] and 0 <= c < z.shape[1]
    # Summits inside the block proper; runs; parkings anywhere in the padded window.
    summits, runs = [], []
    for pr, pc in find_peaks(z):
        if not (r0 <= pr < r0 + (north - south) // 10 and c0 <= pc < c0 + (east - west) // 10):
            continue
        sid = f'{prefix}s{len(summits)}'
        summits.append(dict(id=sid, cell=(int(pr), int(pc)), lonlat=[round(v, 5) for v in TO_LL.transform(W + pc * 10 + 5, mosaic.north - pr * 10 - 5)], elevation=finite(z[pr, pc])))
        for run in run_candidates(pr, pc, z, band_len, counted, target, ok, slope, aspect, forest):
            dr, dc = np.divmod(run['cells'], z.shape[1])
            # Merge with an existing run whose bottom is within 100 m and top within 200 m.
            twin = next((r for r in runs if np.hypot(r['bottom_cell'][0] - dr[-1], r['bottom_cell'][1] - dc[-1]) < 10 and np.hypot(r['top_cell'][0] - dr[0], r['top_cell'][1] - dc[0]) < 20), None)
            if twin:
                twin['summits'].append(sid); continue
            rid = f'{prefix}r{len(runs)}'
            entry = {k: v for k, v in run.items() if k not in ('cells', 'end')}
            entry.update(id=rid, summits=[sid], top_cell=(int(dr[0]), int(dc[0])), bottom_cell=(int(dr[-1]), int(dc[-1])),
                         top=[round(v, 5) for v in TO_LL.transform(W + dc[0] * 10 + 5, mosaic.north - dr[0] * 10 - 5)],
                         bottom=[round(v, 5) for v in TO_LL.transform(W + dc[-1] * 10 + 5, mosaic.north - dr[-1] * 10 - 5)],
                         line=line(np.column_stack([dr, dc]), W, mosaic.north, 3))
            runs.append(entry)
    parkings = []
    for s in spots:
        r, c = cell(s['x'], s['y'])
        if inside(r, c) and np.isfinite(costs[r, c]):
            parkings.append(dict(id=f'{prefix}p{len(parkings)}', cell=(r, c), lonlat=[round(s['lon'], 5), round(s['lat'], 5)], name=s['name'], access=s['access'], road=s['road'], tags=s['tags']))
    edges = []
    summit_targets = [(i, s['cell']) for i, s in enumerate(summits)]
    parking_targets = [(i, p['cell']) for i, p in enumerate(parkings)]
    reach, walk = reach_km * 100, walk_km * 100
    for p in parkings:
        near = [(i, c) for i, c in summit_targets if np.hypot(c[0] - p['cell'][0], c[1] - p['cell'][1]) <= reach]
        for i, st in legs_from(p['cell'], near, costs, z, slope, forest, W, mosaic.north, reach, horizontal, vertical):
            edges.append(dict(**{'from': p['id'], 'to': summits[i]['id'], 'kind': 'skin'}, **st))
    for run in runs:
        b = run['bottom_cell']
        near_s = [(i, c) for i, c in summit_targets if np.hypot(c[0] - b[0], c[1] - b[1]) <= reach]
        near_p = [(i, c) for i, c in parking_targets if np.hypot(c[0] - b[0], c[1] - b[1]) <= walk]
        for i, st in legs_from(b, near_s, costs, z, slope, forest, W, mosaic.north, reach, horizontal, vertical):
            edges.append(dict(**{'from': run['id'], 'to': summits[i]['id'], 'kind': 'skin'}, **st))
        for i, st in legs_from(b, near_p, costs, z, slope, forest, W, mosaic.north, walk, horizontal, vertical):
            if st['gain_m'] <= 250:
                edges.append(dict(**{'from': run['id'], 'to': parkings[i]['id'], 'kind': 'walk'}, **st))
    for s in summits:
        del s['cell']
    for r in runs:
        del r['top_cell'], r['bottom_cell']
    for p in parkings:
        del p['cell']
    return dict(parkings=parkings, summits=summits, runs=runs, edges=edges, tiles_missing=mosaic.tiles_missing)
