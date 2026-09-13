"""Re-fetch roads (in 14 km chunks) for scan blocks that lack them and recompute approach."""
import json, sys, time
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import search as s
from backend.terrain import fetch_raster, TO_LL, TO_UTM, finite

B = 28000
for path in sorted(Path('.cache/scan').glob('*.json')):
    r = json.loads(path.read_text())
    if r.get('roads') is not None:
        continue
    b = r['block']; west, south = b['x'], b['y']
    pts = []
    ok = True
    for cy in range(south, south + B, 14000):
        for cx in range(west, west + B, 14000):
            xy = s.roads(cx, cy, cx + 14000, cy + 14000)
            if xy is None:
                ok = False; break
            pts.append(xy)
            time.sleep(2)
        if not ok: break
    if not ok:
        print(path.name, 'roads still unavailable'); continue
    road_xy = np.vstack([p for p in pts if len(p)]) if any(len(p) for p in pts) else np.zeros((0, 2))
    coarse = fetch_raster(west - 42000, south - 42000, B + 84000, 100)
    for c in r['candidates']:
        bx, by = TO_UTM.transform(*c['bottom'])
        if not len(road_xy):
            c['approach'] = dict(road=None, distance_km=None, gain_m=None, hours=None, complete=False); continue
        d = np.hypot(road_xy[:, 0] - bx, road_xy[:, 1] - by); k = int(np.argmin(d))
        rz = coarse.sample(road_xy[k, 0], road_xy[k, 1])
        gain = float(c['bottom_elevation'] - rz) if np.isfinite(rz) and c['bottom_elevation'] is not None else None
        hours = d[k] / 1000 / 4 + (max(gain, 0) / 400 if gain is not None else 0)
        c['approach'] = dict(road=list(TO_LL.transform(*road_xy[k])), distance_km=round(float(d[k]) / 1000, 2), gain_m=finite(gain) if gain is not None else None, hours=round(float(hours), 2), complete=gain is not None)
    r['roads'] = int(len(road_xy))
    path.write_text(json.dumps(r))
    print(path.name, 'roads fixed:', len(road_xy), 'points')
