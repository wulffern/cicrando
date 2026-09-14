"""Candidates from what is already scanned — no terrain work.

Usage: assemble.py --origin LON LAT --name NAME [--radius-km 80 | --corridor] [--max-drive-hours 2] [--access open]
Reads block graphs already in .cache/graph-v3/<params>/, qualifies parkings (cached access data,
cached/OSRM drive times), assembles data/graph-<name>-<date>.json and lists blocks a scan would add.
"""
import argparse, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.graph_scan import plan_scan, execute_scan, cache_directory, ROUTING
from backend.regions import Region, Corridor

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument('--origin', nargs=2, type=float, required=True, metavar=('LON', 'LAT'))
ap.add_argument('--name', required=True)
ap.add_argument('--radius-km', type=float, default=80)
ap.add_argument('--corridor', action='store_true', help='use the Trondheim corridor legs from scripts/corridor_scan.py')
ap.add_argument('--buffer-km', type=float, default=25)
ap.add_argument('--max-drive-hours', type=float)
ap.add_argument('--access', choices=('open', 'plowed', 'all'), default='open')
a = ap.parse_args()
if a.corridor:
    from scripts.corridor_scan import LEGS
    region = Corridor(tuple(a.origin), LEGS, a.buffer_km, a.name)
else:
    region = Region(tuple(a.origin), 'circle', a.radius_km)
t0 = time.time()
plan = plan_scan(region, max_drive_hours=a.max_drive_hours, access=a.access)
cache = cache_directory('.cache', plan['routing'])
have = {p.stem for p in cache.glob('*.json')}
want = [f"{b['x']}_{b['y']}" for b in plan['terrain_blocks']]
print(f"{plan['parking_count']} parkings in coverage, {len(plan['eligible_parkings'])} eligible; terrain blocks wanted {len(want)}, scanned {sum(1 for w in want if w in have)}, missing {[w for w in want if w not in have]}")
graph = execute_scan(plan, a.name, cached_only=True)
out = Path(f'data/graph-{a.name.lower()}-{time.strftime("%Y-%m-%d")}.json')
from backend.store import save
save(graph, out)
print('wrote', out, {k: len(graph[k]) for k in ('parkings', 'summits', 'runs', 'edges')}, f'in {time.time()-t0:.0f} s; complete: {graph["complete"]}')
