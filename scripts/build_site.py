"""Assemble the static GitHub Pages site in docs/ from data/ and the review caches.

- docs/index.html        tour viewer (site/index.html) reading docs/data/index.json
- docs/data/*.json       every data/*toppturer*.json, with a `gpx` link per tour
- docs/gpx/<set>/*.gpx   GPX files (regenerated from each dataset)
- docs/*.html            review pages, when their caches exist
"""
import json, re, shutil, subprocess, sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
docs = root / 'docs'; (docs / 'data').mkdir(parents=True, exist_ok=True); (docs / 'gpx').mkdir(exist_ok=True)
shutil.copy(root / 'site/index.html', docs / 'index.html')
(docs / 'route.html').unlink(missing_ok=True)
(docs / '.nojekyll').touch()
index = []
for src in sorted((root / 'data').glob('*toppturer*.json'), reverse=True):
    data = json.loads(src.read_text())
    slug = src.stem
    gpx_dir = docs / 'gpx' / slug
    # Regenerate GPX from this dataset so numbering matches the viewer.
    tmp = root / '.cache/toppturs.json'
    tmp.write_text(json.dumps(data))
    subprocess.run([sys.executable, str(root / 'scripts/toppturs_gpx.py'), str(gpx_dir)], check=True, cwd=root)
    files = sorted(gpx_dir.glob('[0-9]*.gpx'))
    for i, t in enumerate(data['tours']):
        t['gpx'] = f'gpx/{slug}/{files[i].name}' if i < len(files) else None
    data['gpx_all'] = f'gpx/{slug}/all-toppturer.gpx'
    data.setdefault('origin_name', 'Skarvatnet' if abs(data['origin'][0] - 9.549) < 0.01 else None)
    (docs / 'data' / src.name).write_text(json.dumps(data, ensure_ascii=False))
    index.append(dict(file=src.name, title=f"{data.get('origin_name') or 'Origin'} · {data['generated'][:10]} · {len(data['tours'])} tours"))
import numpy as np
from backend.osm_extract import main_road_segments
ROADS = main_road_segments(root / '.cache/osm')
CAR_M = 300   # crossing the road right beside the parking is normal
CELL = 0.02  # degrees; road segments are bucketed by every grid cell their bounding box touches
GRID = {}
if len(ROADS):
    lo = np.floor(np.minimum(ROADS[:, :2], ROADS[:, 2:]) / CELL).astype(int)
    hi = np.floor(np.maximum(ROADS[:, :2], ROADS[:, 2:]) / CELL).astype(int)
    for i in range(len(ROADS)):
        for cx in range(lo[i, 0], hi[i, 0] + 1):
            for cy in range(lo[i, 1], hi[i, 1] + 1):
                GRID.setdefault((cx, cy), []).append(i)


def road_crossings(line, near_car=None):
    """How many main-road segments a polyline properly crosses (touching an end does not count).
    near_car='start'/'end': crossings within CAR_M of that end are ignored (the road beside the car park)."""
    if not line or len(line) < 2:
        return 0
    a = np.asarray([p[:2] for p in line], float)
    if near_car:
        step = np.hypot(np.diff(a[:, 0]) * 111320 * np.cos(np.radians(a[:-1, 1])), np.diff(a[:, 1]) * 110540)
        if near_car == 'end':
            a, step = a[::-1], step[::-1]
        keep = np.concatenate([[0], np.cumsum(step)]) > CAR_M   # points beyond CAR_M, plus the one before
        first = max(int(np.argmax(keep)) - 1, 0) if keep.any() else len(a)
        a = a[first:]
        if len(a) < 2:
            return 0
    (x0, y0), (x1, y1) = np.floor(a.min(0) / CELL).astype(int), np.floor(a.max(0) / CELL).astype(int)
    ids = {i for cx in range(x0, x1 + 1) for cy in range(y0, y1 + 1) for i in GRID.get((cx, cy), ())}
    if not ids:
        return 0
    q = ROADS[sorted(ids)]
    p0, p1 = a[:-1, None, :], a[1:, None, :]
    q0, q1 = q[None, :, :2], q[None, :, 2:]
    cross = lambda o, u, v: (u[..., 0] - o[..., 0]) * (v[..., 1] - o[..., 1]) - (u[..., 1] - o[..., 1]) * (v[..., 0] - o[..., 0])
    d1, d2 = cross(q0, q1, p0), cross(q0, q1, p1)
    d3, d4 = cross(p0, p1, q0), cross(p0, p1, q1)
    return int(((d1 * d2 < 0) & (d3 * d4 < 0)).sum())


graphs = []
for src in sorted((root / 'data').glob('graph-*.json'), reverse=True):
    g = json.loads(src.read_text())
    ldir_src = src.with_suffix('.lines')
    ldir = docs / 'data' / 'lines' / src.stem
    shutil.rmtree(ldir, ignore_errors=True)
    lines = {}
    if g.get('lines_dir') and ldir_src.exists():
        for f in ldir_src.glob('*.json'):
            lines.update(json.loads(f.read_text()))
    else:  # legacy inline geometry
        for e in g['edges']:
            lines[f"{e['from']}>{e['to']}>{e['kind']}"] = e.pop('line', None)
        for r in g['runs']:
            lines[r['id']] = r.pop('line', None)
            for sid, a in (r.get('approach') or {}).items():
                lines[f"{r['id']}>{sid}>approach"] = a.pop('line', None)
    # One geometry file per summit (every line a tour from it can draw), so picking a summit on a
    # phone fetches ~100 kB instead of its whole 28 km block (up to 18 MB). Elevation to whole metres.
    keys = {}
    for e in g['edges']:
        if e['kind'] == 'skin':
            keys.setdefault(e['to'], []).append(f"{e['from']}>{e['to']}>skin")
    walks = {}
    for e in g['edges']:
        if e['kind'] == 'walk':
            walks.setdefault(e['from'], []).append(f"{e['from']}>{e['to']}>walk")
    for r in g['runs']:
        for sid in r['summits']:
            keys.setdefault(sid, []).extend([r['id'], f"{r['id']}>{sid}>approach", *walks.get(r['id'], [])])
    rnd = lambda l: [[p[0], p[1], round(p[2])] if len(p) > 2 else p for p in l]
    ldir.mkdir(parents=True)
    for sid, ks in keys.items():
        shard = {k: rnd(lines[k]) for k in ks if lines.get(k)}
        (ldir / f'{sid}.json').write_text(json.dumps(shard, separators=(',', ':')))
    g['lines_by'] = 'summit'
    # Largest single descent on each ascent (highest point so far minus where you are), so the
    # viewer can skip ascents that lose height they have to win back, e.g. dropping into a valley first.
    for e in g['edges']:
        line = lines.get(f"{e['from']}>{e['to']}>{e['kind']}")
        if e['kind'] == 'skin' and line and len(line[0]) > 2:
            hi, drop = line[0][2], 0
            for pt in line:
                hi = max(hi, pt[2])
                drop = max(drop, hi - pt[2])
            e['drop_m'] = round(drop)
    # Main-road crossings (motorway/trunk/primary, OSM) on every leg, so the viewer can avoid them.
    if len(ROADS):
        for e in g['edges']:
            e['roads_x'] = road_crossings(lines.get(f"{e['from']}>{e['to']}>{e['kind']}"), 'start' if e['kind'] == 'skin' else 'end')
        for r in g['runs']:
            r['roads_x'] = road_crossings(lines.get(r['id']))
            for sid, a in (r.get('approach') or {}).items():
                a['roads_x'] = road_crossings(lines.get(f"{r['id']}>{sid}>approach"))
    # Drop fields the viewer never reads: the phone parses this whole file before showing anything.
    for e in g['edges']:
        for k in ('mean_slope', 'share_over_25', 'runout_m'):
            e.pop(k, None)
    for p in g['parkings']:
        p.pop('tags', None)
    for r in g['runs']:
        for k in ('top', 'start_offset_m', 'start_below_summit_m', 'band_share'):
            r.pop(k, None)
        for a in (r.get('approach') or {}).values():
            a.pop('runout_m', None)
    g['lines_dir'] = f'lines/{src.stem}'
    (docs / 'data' / src.name).write_text(json.dumps(g, ensure_ascii=False, separators=(',', ':')))
    graphs.append(dict(file=src.name, title=f"{g.get('origin_name') or 'Origin'} · {g['generated'][:10]} · {len(g['summits'])} summits, {len(g['runs'])} runs"))
(docs / 'data/index.json').write_text(json.dumps(dict(tours=index, graphs=graphs), ensure_ascii=False))
for cache, script, name in (('review.json', 'review_page.py', 'trondelag-ski-faces.html'), ('toppturs.json', 'toppturs_page.py', 'skarvatnet-toppturer.html')):
    if (root / '.cache' / cache).exists():
        subprocess.run([sys.executable, str(root / 'scripts' / script), str(docs / name)], check=True, cwd=root)
print('site built:', len(index), 'datasets;', sum(1 for _ in docs.rglob('*.gpx')), 'gpx files')
