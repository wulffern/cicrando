"""Origin-specific scan planning and assembly over reusable, origin-independent terrain graphs."""
from __future__ import annotations

from collections import deque
import hashlib
import json
import math
import os
from pathlib import Path
import time

import httpx

from .blocks import run_blocks
from .graph import build
from .loops import parking_spots
from .regions import BLOCK_M, Region, approach_blocks
from .terrain import TO_UTM
from .toppturs import drive_minutes

ROUTING = dict(lower=20, upper=30, max_ascent=35, horizontal=4, vertical=400,
               margin=12000, reach_km=12, walk_km=12, walk_gain=400, descent_max=35)


def parking_key(lon, lat):
    # Match graph.build's exported parking coordinates across overlapping blocks.
    return round(lon, 5), round(lat, 5)


def cache_directory(root, routing):
    overrides = Path('data/winter_roads.json')
    identity = dict(algorithm='adaptive-portals-v6-runout-elev-trailheads', terrain='Kartverket-DTM-10m', routing=routing,
                    winter_overrides=overrides.read_text() if overrides.exists() else '')
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
    return Path(root) / 'graph-v3' / digest


def plan_scan(region: Region, max_drive_hours=None, access='open', routing=None, terrain_buffer_km=12):
    """Discover and qualify parking before requesting terrain. Unknown times are never zero."""
    if max_drive_hours is not None and (not math.isfinite(max_drive_hours) or max_drive_hours <= 0):
        raise ValueError('Maximum driving hours must be positive and finite')
    allowed = {'open': {'plowed', 'unknown'}, 'plowed': {'plowed'}, 'all': {'plowed', 'unknown', 'closed'}}
    if access not in allowed:
        raise ValueError('Access must be open, plowed, or all')
    routing = dict(ROUTING if routing is None else routing)
    if not math.isfinite(terrain_buffer_km) or terrain_buffer_km < routing['reach_km']:
        raise ValueError('Terrain buffer must be finite and at least the summit approach limit')
    coverage_blocks = region.blocks()
    found, missing = {}, []
    for b in coverage_blocks:
        spots = parking_spots(b['x'], b['y'], b['x'] + BLOCK_M, b['y'] + BLOCK_M, pad=routing['margin'])
        if spots is None:
            missing.append([b['x'], b['y']])
            continue
        for spot in spots:
            if region.contains(spot['x'], spot['y']):
                found[parking_key(spot['lon'], spot['lat'])] = spot
    candidates = [p for _, p in sorted(found.items()) if p['access'] in allowed[access]]
    minutes = drive_minutes(region.origin, [(p['lon'], p['lat']) for p in candidates]) if candidates else []
    eligible, unknown, outside = [], [], []
    for p, duration in zip(candidates, minutes):
        p = dict(p, drive_min=duration)
        if duration is None:
            unknown.append([p['lon'], p['lat']])
        if max_drive_hours is None or (duration is not None and duration <= max_drive_hours * 60):
            eligible.append(p)
        elif duration is not None:
            outside.append([p['lon'], p['lat']])
    blocks = approach_blocks(eligible, terrain_buffer_km)
    ox, oy = region.centre
    for b in blocks:
        b['dist_km'] = math.hypot(b['x'] + BLOCK_M / 2 - ox, b['y'] + BLOCK_M / 2 - oy) / 1000
    blocks.sort(key=lambda b: (b['dist_km'], b['x'], b['y']))
    return dict(origin=list(region.origin), coverage=region.metadata(), max_drive_hours=max_drive_hours,
                access=access, routing=routing, terrain_buffer_km=terrain_buffer_km, coverage_blocks=coverage_blocks, terrain_blocks=blocks,
                eligible_parkings=eligible, parking_count=len(found),
                missing_parking_blocks=missing, unknown_drive_parkings=unknown,
                over_limit_parkings=outside)


def build_block(block, routing):
    x, y = block['x'], block['y']
    return build(x, y, x + BLOCK_M, y + BLOCK_M, f'{x // 1000}_{y // 1000}_', **routing)


def assemble(paths, eligible):
    """Merge selected blocks only, qualify parkings, then retain directed reachable tour nodes."""
    parkings, summits, runs, edges, remap, locations = {}, {}, {}, {}, {}, {}
    missing_tiles = 0
    for path in paths:
        g = json.loads(Path(path).read_text())
        missing_tiles += g.get('tiles_missing', 0)
        for p in g['parkings']:
            key = parking_key(*p['lonlat'])
            canonical = locations.setdefault(key, p['id'])
            remap[p['id']] = canonical
            parkings.setdefault(canonical, p)
        summits.update((s['id'], s) for s in g['summits'])
        runs.update((r['id'], r) for r in g['runs'])
        # Read edges after all parking IDs have been mapped, including IDs in later files.
        for e in g['edges']:
            key = e['from'], e['to'], e['kind']
            if key not in edges or e['hours'] < edges[key]['hours']:
                edges[key] = e
    qualified = {parking_key(p['lon'], p['lat']): p for p in eligible}
    kept_parking = {}
    for pid, p in parkings.items():
        source = qualified.get(parking_key(*p['lonlat']))
        if source is not None:
            kept_parking[pid] = dict(p, drive_min=source['drive_min'], access=source['access'])
    merged = {}
    nodes = set(kept_parking) | set(summits) | set(runs)
    for e in edges.values():
        e = dict(e, **{'from': remap.get(e['from'], e['from']), 'to': remap.get(e['to'], e['to'])})
        if e['from'] not in nodes or e['to'] not in nodes:
            continue
        key = e['from'], e['to'], e['kind']
        if key not in merged or e['hours'] < merged[key]['hours']:
            merged[key] = e
    adjacency = {}
    for e in merged.values():
        adjacency.setdefault(e['from'], []).append(e['to'])
    for r in runs.values():
        for sid in r['summits']:
            adjacency.setdefault(sid, []).append(r['id'])
    reached, queue = set(kept_parking), deque(kept_parking)
    while queue:
        for dst in adjacency.get(queue.popleft(), []):
            if dst not in reached:
                reached.add(dst)
                queue.append(dst)
    selected_runs = [dict(r, summits=[sid for sid in r['summits'] if sid in reached])
                     for r in runs.values() if r['id'] in reached]
    return dict(parkings=list(kept_parking.values()), summits=[s for s in summits.values() if s['id'] in reached],
                runs=selected_runs, edges=[e for e in merged.values() if e['from'] in reached and e['to'] in reached],
                tiles_missing=missing_tiles)


def enrich_names(summits, cache_root):
    path = Path(cache_root) / 'placenames.json'
    cache = json.loads(path.read_text()) if path.exists() else {}
    offline = os.getenv('RANDO_OFFLINE') == '1'
    dirty = False
    for summit in summits:
        key = 'peak:' + ','.join(f'{v:.4f}' for v in summit['lonlat'])
        if key not in cache and not offline:
            x, y = TO_UTM.transform(*summit['lonlat'])
            try:
                response = httpx.get('https://api.kartverket.no/stedsnavn/v1/punkt',
                                     params=dict(nord=round(y), ost=round(x), koordsys=25833, radius=600,
                                                 utkoordsys=4258, treffPerSide=20), timeout=20)
                response.raise_for_status()
                peaks = [h for h in response.json().get('navn', []) if h['navneobjekttype'] in
                         ('Fjell', 'Topp', 'Berg', 'Nut', 'Egg', 'Kam', 'Koll', 'Haug', 'Høyde', 'Ås', 'Rygg', 'Fjellkant', 'Hei')]
                cache[key] = dict(name=peaks[0]['stedsnavn'][0]['skrivemåte'] if peaks else None)
                dirty = True
            except (httpx.HTTPError, ValueError, KeyError, IndexError):
                pass  # Unknown remains retryable rather than caching a failed request.
            time.sleep(.2)
        summit['name'] = cache.get(key, {}).get('name')
    if dirty:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, ensure_ascii=False))


def execute_scan(plan, name, cache_root='.cache', workers=2, cached_only=False):
    out = cache_directory(cache_root, plan['routing'])
    paths = run_blocks(plan['terrain_blocks'], build_block, out, workers=workers, routing=plan['routing'],
                       describe=lambda g: f"{len(g['edges'])} edges", cached_only=cached_only)
    # Limit reads even if a caller/block runner returns unrelated cache entries.
    expected = {out / f"{b['x']}_{b['y']}.json" for b in plan['terrain_blocks']}
    paths = sorted(Path(p) for p in paths if Path(p) in expected)
    graph = assemble(paths, plan['eligible_parkings'])
    enrich_names(graph['summits'], cache_root)
    graph.update(origin=plan['origin'], origin_name=name, generated=time.strftime('%Y-%m-%d %H:%M'),
                 blocks=len(paths), requested_blocks=len(expected), scanned_blocks=[p.stem for p in paths], coverage=plan['coverage'],
                 max_drive_hours=plan['max_drive_hours'], access=plan['access'], routing=plan['routing'],
                 terrain_buffer_km=plan.get('terrain_buffer_km', plan['routing']['reach_km']),
                 missing_terrain_blocks=[p.stem for p in sorted(expected - set(paths))],
                 missing_parking_blocks=plan['missing_parking_blocks'],
                 unknown_drive_parkings=plan['unknown_drive_parkings'],
                 over_limit_parkings=plan['over_limit_parkings'],
                 method='Adaptive least-cost ski legs on Kartverket 10 m terrain; one-way OSRM driving times to parkings within explicit geographic coverage.')
    graph['complete'] = not (graph['missing_terrain_blocks'] or graph['missing_parking_blocks']
                             or graph['tiles_missing'] or (plan['max_drive_hours'] is not None and graph['unknown_drive_parkings']))
    return graph
