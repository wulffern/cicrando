"""Route graph for multi-leg summit tours: parkings, summits and runs joined by least-cost legs.

Nodes: parking spots (OSM, with winter-access class), summits, and fall-line runs (top → bottom).
Edges: skin legs parking→summit and run-bottom→summit, walk legs run-bottom→parking, and the
implicit summit→run descent. Legs are least-cost paths on a terrain-adaptive mesh (10 m cells
wherever slope ≥15°, coarser over gentle ground; ≥35° impassable, 30–35° ×4) — gentle terrain
possibilities, not checked routes. A static page reads the graph.
"""
from __future__ import annotations

import logging
import numpy as np
from scipy import ndimage

from .loops import parking_spots, run_candidates
from .search import build_mosaic, fall_line_drop, forest_mask, runout_mask, water_mask
from .terrain import TO_LL, derivatives, finite
from .toppturs import ascent_costs, find_peaks, path_stats
from . import mesh

logger = logging.getLogger('rando.graph')


def line(cells, W, north, step, z=None):
    # Only omit collinear cells. Keep every turn and cap segment length; arbitrary
    # subsampling can draw a chord through terrain the walked path avoided.
    cells = np.asarray(cells)
    keep = np.zeros(len(cells), dtype=bool)
    keep[::step] = True
    keep[0] = keep[-1] = True
    if len(cells) > 2:
        delta = np.diff(cells, axis=0)
        keep[1:-1] |= np.any(delta[1:] != delta[:-1], axis=1)
    selected = cells[keep]
    if len(selected) == 1:
        selected = np.repeat(selected, 2, axis=0)
    lon, lat = TO_LL.transform(W + selected[:, 1] * 10 + 5, north - selected[:, 0] * 10 - 5)
    pts = np.round(np.column_stack((lon, lat)), 7)
    if z is not None:
        elev = np.round(z[selected[:, 0], selected[:, 1]], 1)
        pts = np.column_stack((pts, elev))
    return pts.tolist()


class Router:
    """Least-cost legs on the terrain-adaptive mesh (see backend.mesh), one Dijkstra per source."""

    def __init__(self, costs, slope, refine_deg=15.0, endpoints=(), water=None, runout=None):
        self.costs, self.slope, self.refine_deg, self.water, self.runout = costs, slope, refine_deg, water, runout
        self.endpoints = set(map(tuple, endpoints))
        self._build()

    def _build(self):
        self.leaf, self.crow, self.ccol, self.size, lcost = mesh.build_mesh(
            self.costs, self.slope, self.refine_deg, self.endpoints)
        self.indptr, self.dst, self.w = mesh.build_graph(self.leaf, self.crow, self.ccol, lcost, self.size)
        self.component = mesh.components(self.indptr, self.dst)

    def _pin(self, cells):
        # Batch callers should supply all endpoints at construction, avoiding rebuilds.
        extra = {tuple(c) for c in cells if self.size[self.leaf[tuple(c)]] > 1}
        if extra:
            self.endpoints.update(extra)
            self._build()

    def legs(self, source, targets, z, slope, forest, W, north, horizontal, vertical):
        """Legs from one source cell to the reachable target cells; list of (target index, stats)."""
        sr, sc = source
        if not np.isfinite(self.costs[sr, sc]):
            return []
        targets = [(i, tuple(c)) for i, c in targets if np.isfinite(self.costs[tuple(c)])]
        if not targets:
            return []
        self._pin([source] + [c for _, c in targets])
        component = self.component[self.leaf[sr, sc]]
        ids = [(i, int(self.leaf[c])) for i, c in targets
               if self.component[self.leaf[c]] == component]
        target_cells = dict(targets)
        if not ids:
            return []
        dist, pred = mesh.dijkstra(self.indptr, self.dst, self.w, int(self.leaf[sr, sc]), np.array([t for _, t in ids], dtype=np.int32))
        out = []
        for i, t in ids:
            if not np.isfinite(dist[t]):
                continue
            path = mesh.path_cells(pred, self.crow, self.ccol, self.size, t, (sr, sc), target_cells[i])
            stats = path_stats(path[:, 0], path[:, 1], z, slope, forest, horizontal, vertical, self.water, self.runout)
            stats['line'] = line(path, W, north, 8, z)
            out.append((i, stats))
        return out


def build(west, south, east, north, prefix, lower=20, upper=30, max_ascent=35, horizontal=4, vertical=400, margin=12000, reach_km=12, walk_km=12, walk_gain=400, descent_max=35):
    W, S, E, N = west - margin, south - margin, east + margin, north + margin
    mosaic = build_mosaic(W, S, E, N); z = mosaic.z
    slope, aspect = derivatives(z, 10)
    forest = forest_mask(W, S, E, N, z.shape)
    water = water_mask(W, S, E, N, z.shape)
    runout = runout_mask(W, S, E, N, z.shape)
    spots = parking_spots(west, south, east, north, pad=margin)
    if spots is None:
        raise RuntimeError('Parking/road data unavailable')
    costs = ascent_costs(slope, max_ascent, lower, water, runout)
    smooth = ndimage.uniform_filter(np.nan_to_num(slope, nan=90.0), 3)
    # A run may cross short sections up to `descent_max` (reported), but never a raw ≥ descent_max cell.
    ok = (smooth < descent_max) & (np.nan_to_num(slope, nan=90.0) < descent_max) & (smooth > 3) & np.isfinite(slope)
    counted = ok & (smooth > lower) & (smooth < upper)
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
                twin['summits'].append(sid); twin['top_cells'][sid] = (int(dr[0]), int(dc[0])); continue
            rid = f'{prefix}r{len(runs)}'
            entry = {k: v for k, v in run.items() if k not in ('cells', 'end')}
            entry.update(id=rid, summits=[sid], top_cell=(int(dr[0]), int(dc[0])), top_cells={sid: (int(dr[0]), int(dc[0]))}, bottom_cell=(int(dr[-1]), int(dc[-1])),
                         top=[round(v, 5) for v in TO_LL.transform(W + dc[0] * 10 + 5, mosaic.north - dr[0] * 10 - 5)],
                         bottom=[round(v, 5) for v in TO_LL.transform(W + dc[-1] * 10 + 5, mosaic.north - dr[-1] * 10 - 5)],
                         line=line(np.column_stack([dr, dc]), W, mosaic.north, 3, z))
            runs.append(entry)
    parkings = []
    for s in spots:
        r, c = cell(s['x'], s['y'])
        if inside(r, c) and np.isfinite(costs[r, c]):
            parkings.append(dict(id=f'{prefix}p{len(parkings)}', cell=(r, c), lonlat=[round(s['lon'], 5), round(s['lat'], 5)], name=s['name'], access=s['access'], road=s['road'], tags=s['tags']))
    # Run discovery is complete; release full-block scratch rasters before allocating CSR.
    del smooth, ok, counted, band_len, target, aspect, _
    endpoints = ([s['cell'] for s in summits] + [p['cell'] for p in parkings]
                 + [r['bottom_cell'] for r in runs] + [c for r in runs for c in r['top_cells'].values()])
    router = Router(costs, slope, endpoints=endpoints, water=water, runout=runout)
    # Connector from each summit to the top of each of its runs: a least-cost leg, never a straight line.
    for summit in summits:
        mine = [(i, r['top_cells'][summit['id']]) for i, r in enumerate(runs) if summit['id'] in r['summits']]
        for i, st in router.legs(summit['cell'], mine, z, slope, forest, W, mosaic.north, horizontal, vertical):
            runs[i].setdefault('approach', {})[summit['id']] = dict(line=st['line'], length_m=st['length_m'], gain_m=st['gain_m'], loss_m=st['loss_m'], max_slope=st['max_slope'], hours=st['hours'], lake_m=st['lake_m'], runout_m=st['runout_m'])
    for r in runs:  # a summit without a gentle connector to the run top does not get that run
        r['summits'] = [sid for sid in r['summits'] if sid in r.get('approach', {})]
    runs = [r for r in runs if r['summits']]
    edges = []
    summit_targets = [(i, s['cell']) for i, s in enumerate(summits)]
    parking_targets = [(i, p['cell']) for i, p in enumerate(parkings)]
    reach, walk = reach_km * 100, walk_km * 100
    for p in parkings:
        near = [(i, c) for i, c in summit_targets if np.hypot(c[0] - p['cell'][0], c[1] - p['cell'][1]) <= reach]
        for i, st in router.legs(p['cell'], near, z, slope, forest, W, mosaic.north, horizontal, vertical):
            edges.append(dict(**{'from': p['id'], 'to': summits[i]['id'], 'kind': 'skin'}, **st))
    for run in runs:
        b = run['bottom_cell']
        near_s = [(i, c) for i, c in summit_targets if np.hypot(c[0] - b[0], c[1] - b[1]) <= reach]
        near_p = [(i, c) for i, c in parking_targets if np.hypot(c[0] - b[0], c[1] - b[1]) <= walk]
        targets = [(('skin', i), c) for i, c in near_s] + [(('walk', i), c) for i, c in near_p]
        for (kind, i), st in router.legs(b, targets, z, slope, forest, W, mosaic.north, horizontal, vertical):
            if kind == 'skin' or st['gain_m'] <= walk_gain:
                destination = summits[i]['id'] if kind == 'skin' else parkings[i]['id']
                edges.append(dict(**{'from': run['id'], 'to': destination, 'kind': kind}, **st))
    for s in summits:
        del s['cell']
    for r in runs:
        del r['top_cell'], r['bottom_cell'], r['top_cells']
    for p in parkings:
        del p['cell']
    return dict(parkings=parkings, summits=summits, runs=runs, edges=edges, tiles_missing=mosaic.tiles_missing, water=water is not None, runout=runout is not None)
