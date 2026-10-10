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
