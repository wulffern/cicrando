"""Build the multi-leg route graph around an origin. Usage: graph_scan.py LON LAT NAME [radius_km]

Per-block graphs are cached in .cache/graph/, merged into data/graph-<name>-<date>.json with
OSRM drive minutes to every parking and Kartverket names for summits.
"""
import json, sys, time, logging
from pathlib import Path
import numpy as np
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.graph import build
from backend.blocks import run_blocks
from backend.toppturs import drive_minutes
from backend.terrain import TO_UTM

logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(message)s')
lon, lat, name = float(sys.argv[1]), float(sys.argv[2]), sys.argv[3]
radius = float(sys.argv[4]) if len(sys.argv) > 4 else 60
B = 28000
ox, oy = TO_UTM.transform(lon, lat)
blocks = [b for b in json.load(open('.cache/scan_blocks.json')) if np.hypot(b['x'] + B / 2 - ox, b['y'] + B / 2 - oy) / 1000 <= radius]
# Old graphs contain centre-cost approximations and unchecked simplified lines.
out = Path('.cache/graph-v2')

def worker(b):
    return build(b['x'], b['y'], b['x'] + B, b['y'] + B, f"{b['x']//1000}_{b['y']//1000}_")

if __name__ == '__main__':
    run_blocks(sorted(blocks, key=lambda b: b['dist_km']), worker, out, workers=2,
               describe=lambda g: f"{len(g['parkings'])} parkings, {len(g['summits'])} summits, {len(g['runs'])} runs, {len(g['edges'])} edges")

if __name__ == '__main__':
    merged = dict(parkings=[], summits=[], runs=[], edges=[])
    for p in sorted(out.glob('*.json')):
        g = json.loads(p.read_text())
        for k in merged:
            merged[k].extend(g[k])
    # Parkings appear in every block whose padded window holds them: keep one per location and remap edges.
    seen, keep, remap = {}, [], {}
    for p in merged['parkings']:
        key = (p['lonlat'][0], p['lonlat'][1])
        if key in seen:
            remap[p['id']] = seen[key]
        else:
            seen[key] = p['id']; keep.append(p)
    merged['parkings'] = keep
    for e in merged['edges']:
        e['from'] = remap.get(e['from'], e['from']); e['to'] = remap.get(e['to'], e['to'])
    dedup = {}
    for e in merged['edges']:
        k = (e['from'], e['to'])
        if k not in dedup or e['hours'] < dedup[k]['hours']:
            dedup[k] = e
    merged['edges'] = list(dedup.values())
    print(f"merged: {len(merged['parkings'])} parkings, {len(merged['summits'])} summits, {len(merged['runs'])} runs, {len(merged['edges'])} edges", flush=True)
    minutes = drive_minutes((lon, lat), [tuple(p['lonlat']) for p in merged['parkings']])
    for p, m in zip(merged['parkings'], minutes):
        p['drive_min'] = m
    names = Path('.cache/placenames.json'); cache = json.loads(names.read_text()) if names.exists() else {}
    for s in merged['summits']:
        key = 'peak:' + ','.join(f'{v:.4f}' for v in s['lonlat'])
        if key not in cache:
            x, y = TO_UTM.transform(*s['lonlat'])
            try:
                r = httpx.get('https://api.kartverket.no/stedsnavn/v1/punkt', params=dict(nord=round(y), ost=round(x), koordsys=25833, radius=600, utkoordsys=4258, treffPerSide=20), timeout=20)
                hits = r.json().get('navn', []) if r.status_code == 200 else []
            except (httpx.HTTPError, ValueError):
                hits = []
            peaks = [h for h in hits if h['navneobjekttype'] in ('Fjell', 'Topp', 'Berg', 'Nut', 'Egg', 'Kam', 'Koll', 'Haug', 'Høyde', 'Ås', 'Rygg', 'Fjellkant', 'Hei')]
            cache[key] = dict(name=peaks[0]['stedsnavn'][0]['skrivemåte'] if peaks else None, kind=peaks[0]['navneobjekttype'] if peaks else None, dist=round(peaks[0]['meterFraPunkt']) if peaks else None)
            names.write_text(json.dumps(cache, ensure_ascii=False)); time.sleep(0.2)
        s['name'] = cache[key]['name']
    merged.update(origin=[lon, lat], origin_name=name, generated=time.strftime('%Y-%m-%d %H:%M'), blocks=len(blocks),
                  method='Least-cost legs on Kartverket 10 m terrain (≥35° impassable, 30–35° ×4, 25–30° ×1.8, 20–25° ×1.3); runs are fall-line 20–30° lines; parkings from OpenStreetMap with winter access from OSM/NVDB tags, road class and data/winter_roads.json; drive times from OSRM.')
    Path(f'data/graph-{name.lower()}-{time.strftime("%Y-%m-%d")}.json').write_text(json.dumps(merged, ensure_ascii=False))
    print('done', flush=True)
